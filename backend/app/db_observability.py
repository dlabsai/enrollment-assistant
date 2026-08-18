from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast
from weakref import WeakSet

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, ExceptionContext
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Sequence

logger = logging.getLogger("demo-va")

PoolName = Literal["main", "interactive", "otel"]

DATABASE_PERSISTENCE_FORCE_ATTRIBUTE = "app.force_otel_database_persistence"
_OBSERVATION_SCHEMA = "db-request.v1"
_SLOW_CHECKOUT_WAIT_NS = 5_000_000_000
_CHECKOUT_LEASE_KEY_PREFIX = "app.db.checkout_lease."
_SQL_TIMER_KEY_PREFIX = "app.db.sql_timer."


@dataclass(slots=True)
class PoolObservation:
    checkout_count: int = 0
    physical_connect_count: int = 0
    checkout_wait_count: int = 0
    checkout_wait_ns_total: int = 0
    checkout_wait_ns_max: int = 0
    connection_hold_count: int = 0
    connection_hold_ns_total: int = 0
    connection_hold_ns_max: int = 0
    checked_out_peak: int = 0
    overflow_peak: int = 0
    sql_count: int = 0
    sql_error_count: int = 0
    sql_ns_total: int = 0
    sql_ns_max: int = 0
    timeout_count: int = 0

    @property
    def has_activity(self) -> bool:
        return self.checkout_count > 0 or self.sql_count > 0 or self.timeout_count > 0

    def record_checkout(self, *, checked_out: int, overflow: int) -> None:
        self.checkout_count += 1
        self.checked_out_peak = max(self.checked_out_peak, checked_out)
        self.overflow_peak = max(self.overflow_peak, overflow)

    def record_physical_connect(self) -> None:
        self.physical_connect_count += 1

    def record_checkout_wait(self, duration_ns: int) -> None:
        duration_ns = max(duration_ns, 0)
        self.checkout_wait_count += 1
        self.checkout_wait_ns_total += duration_ns
        self.checkout_wait_ns_max = max(self.checkout_wait_ns_max, duration_ns)

    def record_timeout(self, duration_ns: int) -> None:
        self.timeout_count += 1
        self.record_checkout_wait(duration_ns)

    def record_connection_hold(self, duration_ns: int) -> None:
        duration_ns = max(duration_ns, 0)
        self.connection_hold_count += 1
        self.connection_hold_ns_total += duration_ns
        self.connection_hold_ns_max = max(self.connection_hold_ns_max, duration_ns)

    def record_sql(self, duration_ns: int, *, errored: bool) -> None:
        duration_ns = max(duration_ns, 0)
        self.sql_count += 1
        self.sql_error_count += int(errored)
        self.sql_ns_total += duration_ns
        self.sql_ns_max = max(self.sql_ns_max, duration_ns)


@dataclass(slots=True)
class DatabaseObservation:
    started_wall_ns: int = field(default_factory=time.time_ns)
    started_monotonic_ns: int = field(default_factory=time.perf_counter_ns)
    pools: dict[PoolName, PoolObservation] = field(
        default_factory=lambda: {
            "main": PoolObservation(),
            "interactive": PoolObservation(),
            "otel": PoolObservation(),
        }
    )

    @property
    def has_activity(self) -> bool:
        return any(pool.has_activity for pool in self.pools.values())


@dataclass(slots=True)
class _CheckoutAttempt:
    observation: DatabaseObservation
    pool_name: PoolName
    started_ns: int
    acquired: bool = False


@dataclass(slots=True)
class _CheckoutLease:
    observation: DatabaseObservation
    pool_name: PoolName
    started_ns: int


@dataclass(slots=True)
class _SqlTimer:
    observation: DatabaseObservation
    pool_name: PoolName
    started_ns: int


_current_observation: ContextVar[DatabaseObservation | None] = ContextVar(
    "database_observation", default=None
)
_checkout_attempt: ContextVar[_CheckoutAttempt | None] = ContextVar(
    "database_checkout_attempt", default=None
)
_instrumented_engines: WeakSet[Engine] = WeakSet()


@contextmanager
def database_observation_scope() -> Generator[DatabaseObservation]:
    observation = DatabaseObservation()
    token = _current_observation.set(observation)
    try:
        yield observation
    finally:
        _current_observation.reset(token)


def current_database_observation() -> DatabaseObservation | None:
    return _current_observation.get()


def _run_sync_checkout_operation[T](pool_name: PoolName, operation: Callable[[], T]) -> T:
    observation = _current_observation.get()
    if observation is None:
        return operation()

    attempt = _CheckoutAttempt(
        observation=observation, pool_name=pool_name, started_ns=time.perf_counter_ns()
    )
    token = _checkout_attempt.set(attempt)
    try:
        return operation()
    except SQLAlchemyTimeoutError:
        if not attempt.acquired:
            observation.pools[pool_name].record_timeout(time.perf_counter_ns() - attempt.started_ns)
        raise
    finally:
        _checkout_attempt.reset(token)


async def _run_async_checkout_operation[T](
    pool_name: PoolName, operation: Callable[[], Awaitable[T]]
) -> T:
    observation = _current_observation.get()
    if observation is None:
        return await operation()

    attempt = _CheckoutAttempt(
        observation=observation, pool_name=pool_name, started_ns=time.perf_counter_ns()
    )
    token = _checkout_attempt.set(attempt)
    try:
        return await operation()
    except SQLAlchemyTimeoutError:
        if not attempt.acquired:
            observation.pools[pool_name].record_timeout(time.perf_counter_ns() - attempt.started_ns)
        raise
    finally:
        _checkout_attempt.reset(token)


class MainSynchronousSession(Session):
    pass


class InteractiveSynchronousSession(Session):
    pass


class TelemetrySynchronousSession(Session):
    pass


def _invoke_orm_statement(pool_name: PoolName, execute_state: ORMExecuteState) -> Any:
    return _run_sync_checkout_operation(pool_name, execute_state.invoke_statement)


def _observe_main_orm_execute(execute_state: ORMExecuteState) -> Any:
    return _invoke_orm_statement("main", execute_state)


def _observe_interactive_orm_execute(execute_state: ORMExecuteState) -> Any:
    return _invoke_orm_statement("interactive", execute_state)


def _observe_telemetry_orm_execute(execute_state: ORMExecuteState) -> Any:
    return _invoke_orm_statement("otel", execute_state)


event.listen(MainSynchronousSession, "do_orm_execute", _observe_main_orm_execute, retval=True)
event.listen(
    InteractiveSynchronousSession, "do_orm_execute", _observe_interactive_orm_execute, retval=True
)
event.listen(
    TelemetrySynchronousSession, "do_orm_execute", _observe_telemetry_orm_execute, retval=True
)


class _ObservedAsyncSession(AsyncSession):
    pool_name: ClassVar[PoolName]

    async def commit(self) -> None:
        await _run_async_checkout_operation(self.pool_name, super().commit)

    async def flush(self, objects: Sequence[Any] | None = None) -> None:
        parent_flush = super().flush
        await _run_async_checkout_operation(self.pool_name, lambda: parent_flush(objects))


class MainAsyncSession(_ObservedAsyncSession):
    pool_name = "main"
    sync_session_class = MainSynchronousSession


class InteractiveAsyncSession(_ObservedAsyncSession):
    pool_name = "interactive"
    sync_session_class = InteractiveSynchronousSession


class TelemetryAsyncSession(_ObservedAsyncSession):
    pool_name = "otel"
    sync_session_class = TelemetrySynchronousSession


def _pool_count(pool: object, method_name: str) -> int:
    method = getattr(pool, method_name, None)
    if not callable(method):
        return 0
    try:
        value = method()
    except Exception:
        return 0
    if not isinstance(value, (int, float)):
        return 0
    return max(int(value), 0)


def _finish_checkout_lease(connection_record: Any, *, pool_name: PoolName) -> None:
    lease = connection_record.info.pop(f"{_CHECKOUT_LEASE_KEY_PREFIX}{pool_name}", None)
    if not isinstance(lease, _CheckoutLease):
        return
    lease.observation.pools[lease.pool_name].record_connection_hold(
        time.perf_counter_ns() - lease.started_ns
    )


def _finish_sql_timer(connection: Connection, *, pool_name: PoolName, errored: bool) -> None:
    timers_value = connection.info.get(f"{_SQL_TIMER_KEY_PREFIX}{pool_name}")
    if not isinstance(timers_value, list) or not timers_value:
        return
    timers = cast(list[object], timers_value)
    timer = timers.pop()
    if not isinstance(timer, _SqlTimer):
        return
    timer.observation.pools[timer.pool_name].record_sql(
        time.perf_counter_ns() - timer.started_ns, errored=errored
    )


def instrument_async_engine(engine: AsyncEngine, *, pool_name: PoolName) -> None:
    sync_engine = engine.sync_engine
    if sync_engine in _instrumented_engines:
        return
    _instrumented_engines.add(sync_engine)
    pool = sync_engine.pool

    def on_connect(_dbapi_connection: object, _connection_record: Any) -> None:
        observation = _current_observation.get()
        if observation is not None:
            observation.pools[pool_name].record_physical_connect()

    def on_checkout(
        _dbapi_connection: object, connection_record: Any, _connection_proxy: object
    ) -> None:
        observation = _current_observation.get()
        if observation is None:
            return

        observation.pools[pool_name].record_checkout(
            checked_out=_pool_count(pool, "checkedout"), overflow=_pool_count(pool, "overflow")
        )
        attempt = _checkout_attempt.get()
        if (
            attempt is not None
            and attempt.observation is observation
            and attempt.pool_name == pool_name
            and not attempt.acquired
        ):
            attempt.acquired = True
            observation.pools[pool_name].record_checkout_wait(
                time.perf_counter_ns() - attempt.started_ns
            )
        connection_record.info[f"{_CHECKOUT_LEASE_KEY_PREFIX}{pool_name}"] = _CheckoutLease(
            observation=observation, pool_name=pool_name, started_ns=time.perf_counter_ns()
        )

    def on_checkin(_dbapi_connection: object, connection_record: Any) -> None:
        _finish_checkout_lease(connection_record, pool_name=pool_name)

    def on_invalidate(
        _dbapi_connection: object, connection_record: Any, _exception: BaseException | None
    ) -> None:
        _finish_checkout_lease(connection_record, pool_name=pool_name)

    def before_cursor_execute(
        connection: Connection,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        observation = _current_observation.get()
        if observation is None:
            lease = connection.info.get(f"{_CHECKOUT_LEASE_KEY_PREFIX}{pool_name}")
            if isinstance(lease, _CheckoutLease):
                observation = lease.observation
        if observation is None:
            return
        timers_value = connection.info.setdefault(f"{_SQL_TIMER_KEY_PREFIX}{pool_name}", [])
        if isinstance(timers_value, list):
            timers = cast(list[object], timers_value)
            timers.append(
                _SqlTimer(
                    observation=observation, pool_name=pool_name, started_ns=time.perf_counter_ns()
                )
            )

    def after_cursor_execute(
        connection: Connection,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        _finish_sql_timer(connection, pool_name=pool_name, errored=False)

    def handle_error(exception_context: ExceptionContext) -> None:
        connection = exception_context.connection
        if connection is not None:
            _finish_sql_timer(connection, pool_name=pool_name, errored=True)

    event.listen(pool, "connect", on_connect)
    event.listen(pool, "checkout", on_checkout)
    event.listen(pool, "checkin", on_checkin)
    event.listen(pool, "invalidate", on_invalidate)
    event.listen(sync_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", after_cursor_execute)
    event.listen(sync_engine, "handle_error", handle_error)


def _milliseconds(value_ns: int) -> float:
    return round(value_ns / 1_000_000, 3)


def database_observation_attributes(
    observation: DatabaseObservation,
    *,
    method: str,
    route: str,
    status_code: int | None,
    ended_monotonic_ns: int | None = None,
) -> dict[str, str | bool | int | float]:
    ended_ns = ended_monotonic_ns or time.perf_counter_ns()
    attributes: dict[str, str | bool | int | float] = {
        DATABASE_PERSISTENCE_FORCE_ATTRIBUTE: True,
        "app.db.observation.schema": _OBSERVATION_SCHEMA,
        "db.system.name": "postgresql",
        "http.method": method,
        "http.route": route,
        "process.pid": os.getpid(),
        "app.db.request.duration_ms": _milliseconds(
            max(ended_ns - observation.started_monotonic_ns, 0)
        ),
    }
    if status_code is not None:
        attributes["http.status_code"] = status_code

    for pool_name, pool in observation.pools.items():
        if not pool.has_activity:
            continue
        prefix = f"app.db.{pool_name}"
        if pool_name == "main":
            configured_pool_size = settings.POSTGRES_POOL_SIZE
            configured_max_overflow = settings.POSTGRES_MAX_OVERFLOW
        elif pool_name == "interactive":
            configured_pool_size = settings.INTERACTIVE_POSTGRES_POOL_SIZE
            configured_max_overflow = settings.INTERACTIVE_POSTGRES_MAX_OVERFLOW
        else:
            configured_pool_size = settings.OTEL_POSTGRES_POOL_SIZE
            configured_max_overflow = settings.OTEL_POSTGRES_MAX_OVERFLOW
        attributes.update(
            {
                f"{prefix}.configured.size": configured_pool_size,
                f"{prefix}.configured.max_overflow": configured_max_overflow,
                f"{prefix}.checkout.count": pool.checkout_count,
                f"{prefix}.physical_connect.count": pool.physical_connect_count,
                f"{prefix}.checkout_wait.count": pool.checkout_wait_count,
                f"{prefix}.checkout_wait_ms.total": _milliseconds(pool.checkout_wait_ns_total),
                f"{prefix}.checkout_wait_ms.max": _milliseconds(pool.checkout_wait_ns_max),
                f"{prefix}.checkout_wait.slow": (
                    pool.checkout_wait_ns_max >= _SLOW_CHECKOUT_WAIT_NS
                ),
                f"{prefix}.connection_hold.count": pool.connection_hold_count,
                f"{prefix}.connection_hold_ms.total": _milliseconds(pool.connection_hold_ns_total),
                f"{prefix}.connection_hold_ms.max": _milliseconds(pool.connection_hold_ns_max),
                f"{prefix}.checked_out.peak": pool.checked_out_peak,
                f"{prefix}.overflow.peak": pool.overflow_peak,
                f"{prefix}.sql.count": pool.sql_count,
                f"{prefix}.sql.error_count": pool.sql_error_count,
                f"{prefix}.sql_ms.total": _milliseconds(pool.sql_ns_total),
                f"{prefix}.sql_ms.max": _milliseconds(pool.sql_ns_max),
                f"{prefix}.timeout.count": pool.timeout_count,
            }
        )
    return attributes


def _emit_database_observation(
    observation: DatabaseObservation, *, method: str, route: str, status_code: int | None
) -> None:
    if not observation.has_activity:
        return
    try:
        for pool_name, pool in observation.pools.items():
            if pool.checkout_wait_ns_max >= _SLOW_CHECKOUT_WAIT_NS:
                logger.warning(
                    "Slow database pool checkout method=%s route=%s pool=%s wait_ms=%.3f",
                    method,
                    route,
                    pool_name,
                    _milliseconds(pool.checkout_wait_ns_max),
                )
        tracer = trace.get_tracer("app.database-observability")
        span = tracer.start_span(
            f"database activity {method} {route}",
            context=Context(),
            kind=SpanKind.INTERNAL,
            attributes=database_observation_attributes(
                observation, method=method, route=route, status_code=status_code
            ),
            start_time=observation.started_wall_ns,
        )
        if any(pool.timeout_count for pool in observation.pools.values()):
            span.set_status(Status(StatusCode.ERROR, "database pool checkout timeout"))
        span.end()
    except Exception:
        logger.exception("Failed to emit database observation span")


class DatabaseObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.DATABASE_OBSERVABILITY_ENABLED:
            await self.app(scope, receive, send)
            return

        status_code: int | None = None

        async def observe_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = cast(int, message["status"])
            await send(message)

        observation = DatabaseObservation()
        token: Token[DatabaseObservation | None] = _current_observation.set(observation)
        try:
            await self.app(scope, receive, observe_send)
        finally:
            _current_observation.reset(token)
            route_object = scope.get("route")
            route_value = getattr(route_object, "path", None)
            route = route_value if isinstance(route_value, str) else "<unmatched>"
            method_value = scope.get("method")
            method = method_value if isinstance(method_value, str) else "UNKNOWN"
            _emit_database_observation(
                observation, method=method.upper(), route=route, status_code=status_code
            )
