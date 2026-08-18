# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, cast

import pytest
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.types import Message, Receive, Scope, Send

from app import db_observability, otel
from app.core.db import async_session_factory, interactive_async_session_factory
from app.db_observability import (
    DATABASE_PERSISTENCE_FORCE_ATTRIBUTE,
    DatabaseObservabilityMiddleware,
    DatabaseObservation,
    database_observation_attributes,
    database_observation_scope,
)


def test_database_observation_attributes_are_aggregate_and_pool_specific() -> None:
    observation = DatabaseObservation(started_wall_ns=10, started_monotonic_ns=100)
    main = observation.pools["main"]
    main.record_checkout(checked_out=7, overflow=2)
    main.record_physical_connect()
    main.record_checkout_wait(2_500_000)
    main.record_connection_hold(5_000_000)
    main.record_sql(1_250_000, errored=False)
    interactive = observation.pools["interactive"]
    interactive.record_checkout(checked_out=2, overflow=0)
    interactive.record_checkout_wait(500_000)
    interactive.record_sql(250_000, errored=False)
    otel_pool = observation.pools["otel"]
    otel_pool.record_checkout(checked_out=9, overflow=0)
    otel_pool.record_sql(750_000, errored=True)

    attributes = database_observation_attributes(
        observation,
        method="GET",
        route="/api/conversations/{conversation_id}",
        status_code=200,
        ended_monotonic_ns=10_000_100,
    )

    assert attributes[DATABASE_PERSISTENCE_FORCE_ATTRIBUTE] is True
    assert attributes["http.route"] == "/api/conversations/{conversation_id}"
    assert isinstance(attributes["process.pid"], int)
    assert attributes["app.db.main.configured.size"] == 5
    assert attributes["app.db.main.configured.max_overflow"] == 3
    assert attributes["app.db.interactive.configured.size"] == 2
    assert attributes["app.db.interactive.configured.max_overflow"] == 0
    assert attributes["app.db.interactive.checkout_wait_ms.max"] == 0.5
    assert attributes["app.db.interactive.sql_ms.total"] == 0.25
    assert attributes["app.db.otel.configured.size"] == 10
    assert attributes["app.db.otel.configured.max_overflow"] == 0
    assert attributes["app.db.main.physical_connect.count"] == 1
    assert attributes["app.db.main.checkout_wait_ms.max"] == 2.5
    assert attributes["app.db.main.checkout_wait.slow"] is False
    assert attributes["app.db.main.connection_hold_ms.max"] == 5.0
    assert attributes["app.db.main.checked_out.peak"] == 7
    assert attributes["app.db.main.overflow.peak"] == 2
    assert attributes["app.db.main.sql_ms.total"] == 1.25
    assert attributes["app.db.otel.sql.error_count"] == 1
    assert all("statement" not in key and "parameter" not in key for key in attributes)
    assert all("user" not in key and "prompt" not in key for key in attributes)


def test_checkout_timeout_is_recorded_and_reraised() -> None:
    with (
        database_observation_scope() as observation,
        pytest.raises(SQLAlchemyTimeoutError, match="pool exhausted"),
    ):
        db_observability._run_sync_checkout_operation(  # noqa: SLF001
            "main", lambda: (_ for _ in ()).throw(SQLAlchemyTimeoutError("pool exhausted"))
        )

    main = observation.pools["main"]
    assert main.timeout_count == 1
    assert main.checkout_wait_count == 1
    assert main.checkout_wait_ns_max > 0


@pytest.mark.asyncio
async def test_main_engine_records_checkout_wait_hold_and_sql() -> None:
    with database_observation_scope() as observation:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1

    main = observation.pools["main"]
    assert main.checkout_count == 1
    assert main.checkout_wait_count == 1
    assert main.checkout_wait_ns_max >= 0
    assert main.connection_hold_count == 1
    assert main.connection_hold_ns_max > 0
    assert main.checked_out_peak >= 1
    assert main.sql_count == 1
    assert main.sql_error_count == 0
    assert main.sql_ns_max > 0
    assert not observation.pools["interactive"].has_activity
    assert not observation.pools["otel"].has_activity


@pytest.mark.asyncio
async def test_interactive_engine_records_separate_pool_activity() -> None:
    with database_observation_scope() as observation:
        async with interactive_async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1

    assert not observation.pools["main"].has_activity
    interactive = observation.pools["interactive"]
    assert interactive.checkout_count == 1
    assert interactive.checkout_wait_count == 1
    assert interactive.connection_hold_count == 1
    assert interactive.sql_count == 1
    assert not observation.pools["otel"].has_activity


@pytest.mark.asyncio
async def test_telemetry_engine_records_separate_pool_activity() -> None:
    await otel.close_telemetry_database_pool()
    factory = otel._get_telemetry_session_factory()  # noqa: SLF001
    try:
        with database_observation_scope() as observation:
            async with factory() as session:
                result = await session.execute(text("SELECT 1"))
                assert result.scalar_one() == 1
    finally:
        await otel.close_telemetry_database_pool()

    assert not observation.pools["main"].has_activity
    assert not observation.pools["interactive"].has_activity
    telemetry = observation.pools["otel"]
    assert telemetry.checkout_count == 1
    assert telemetry.checkout_wait_count == 1
    assert telemetry.connection_hold_count == 1
    assert telemetry.sql_count == 1


@pytest.mark.asyncio
async def test_middleware_keeps_scope_through_response_and_uses_route_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[DatabaseObservation, str, str, int | None]] = []

    class Route:
        path = "/api/conversations/{conversation_id}"

    async def fake_app(scope: Scope, _receive: Receive, send: Send) -> None:
        observation = db_observability.current_database_observation()
        assert observation is not None
        observation.pools["main"].record_checkout(checked_out=3, overflow=0)
        scope["route"] = cast(Any, Route())
        await send(cast(Message, {"type": "http.response.start", "status": 200, "headers": []}))
        observation.pools["main"].record_sql(1_000_000, errored=False)
        await send(cast(Message, {"type": "http.response.body", "body": b"ok"}))

    def capture(
        observation: DatabaseObservation, *, method: str, route: str, status_code: int | None
    ) -> None:
        captured.append((observation, method, route, status_code))

    monkeypatch.setattr(db_observability.settings, "DATABASE_OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(db_observability, "_emit_database_observation", capture)
    middleware = DatabaseObservabilityMiddleware(fake_app)
    sent: list[Message] = []

    async def receive() -> Message:
        return cast(Message, {"type": "http.request", "body": b"", "more_body": False})

    async def send(message: Message) -> None:
        sent.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "get",
            "scheme": "https",
            "path": "/api/conversations/secret-uuid",
            "raw_path": b"/api/conversations/secret-uuid",
            "query_string": b"",
            "headers": [],
            "client": None,
            "server": None,
            "root_path": "",
        },
    )
    await middleware(scope, receive, send)

    assert len(captured) == 1
    observation, method, route, status_code = captured[0]
    assert method == "GET"
    assert route == "/api/conversations/{conversation_id}"
    assert "secret-uuid" not in route
    assert status_code == 200
    assert observation.pools["main"].sql_count == 1
    assert db_observability.current_database_observation() is None
    assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]


@pytest.mark.asyncio
async def test_middleware_disabled_is_a_complete_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted = False

    async def fake_app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        assert db_observability.current_database_observation() is None

    def capture(*_args: object, **_kwargs: object) -> None:
        nonlocal emitted
        emitted = True

    monkeypatch.setattr(db_observability.settings, "DATABASE_OBSERVABILITY_ENABLED", False)
    monkeypatch.setattr(db_observability, "_emit_database_observation", capture)
    middleware = DatabaseObservabilityMiddleware(fake_app)

    async def receive() -> Message:
        return cast(Message, {"type": "http.request", "body": b"", "more_body": False})

    async def send(_message: Message) -> None:
        return None

    await middleware(cast(Scope, {"type": "http"}), receive, send)

    assert emitted is False


def test_database_only_force_attribute_is_not_external_export_force() -> None:
    class Delegate(SpanProcessor):
        def __init__(self) -> None:
            self.spans: list[ReadableSpan] = []

        def on_end(self, span: ReadableSpan) -> None:
            self.spans.append(span)

    span = cast(
        ReadableSpan,
        type(
            "Span",
            (),
            {
                "context": type("SpanContext", (), {"trace_id": 1})(),
                "parent": None,
                "attributes": {DATABASE_PERSISTENCE_FORCE_ATTRIBUTE: True},
                "name": "database activity GET /api/conversations/paginated",
            },
        )(),
    )
    external_delegate = Delegate()
    external = otel._RouteTraceFilteringSpanProcessor(  # noqa: SLF001
        external_delegate,
        routes=otel._OTEL_EXPORT_TARGET_ROUTES,  # noqa: SLF001
    )
    database_delegate = Delegate()
    database = otel._RouteTraceFilteringSpanProcessor(  # noqa: SLF001
        database_delegate,
        routes=otel._OTEL_EXPORT_TARGET_ROUTES,  # noqa: SLF001
        force_attributes=("app.force_otel_export", DATABASE_PERSISTENCE_FORCE_ATTRIBUTE),
    )

    external.on_end(span)
    database.on_end(span)

    assert external_delegate.spans == []
    assert database_delegate.spans == [span]
