import asyncio
import base64
import logging
import os
from collections import deque
from collections.abc import AsyncGenerator, Generator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TypeGuard
from uuid import UUID

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import get_current_span, get_tracer_provider
from opentelemetry.trace.span import format_span_id, format_trace_id
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import get_session
from app.models import OtelSpan

logger = logging.getLogger("demo-va")

_background_tasks: set[asyncio.Task[None]] = set()
_span_processor_provider: object | None = None
_telemetry_session_factory: async_sessionmaker[AsyncSession] | None = None
_otel_session_factory_override: ContextVar[async_sessionmaker[AsyncSession] | None] = ContextVar(
    "otel_session_factory_override", default=None
)
_otel_export_enabled: ContextVar[bool] = ContextVar("otel_export_enabled", default=False)

_LANGFUSE_OTEL_ENABLED = "LANGFUSE_OTEL_ENABLED"
_LANGFUSE_OTEL_ENDPOINT = "LANGFUSE_OTEL_ENDPOINT"
_LANGFUSE_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
_LANGFUSE_SECRET_KEY = "LANGFUSE_SECRET_KEY"  # noqa: S105
_LANGFUSE_INGESTION_VERSION = "LANGFUSE_INGESTION_VERSION"
_LANGFUSE_ENVIRONMENT = "LANGFUSE_ENVIRONMENT"
_OTEL_EXPORT_TARGET_ROUTES = (
    ("POST", "/api/messages/internal/stream"),
    ("POST", "/api/evals/runs/stream"),
)
_DROPPED_GEN_AI_USAGE_DETAILS_PREFIX = "gen_ai.usage.details."


def mark_current_span_for_otel_export() -> None:
    """Mark the active span for OTel export/persistence regardless of route filters."""
    get_current_span().set_attribute("app.force_otel_export", bool(1))


@contextmanager
def otel_export_scope(*, enabled: bool) -> Generator[None]:
    """Force OTel export/persistence for spans ending inside this scope."""
    token = _otel_export_enabled.set(enabled)
    try:
        yield
    finally:
        _otel_export_enabled.reset(token)


@contextmanager
def otel_session_factory_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> Generator[None]:
    """Persist OTel DB spans through a scoped session factory."""
    token = _otel_session_factory_override.set(session_factory)
    try:
        yield
    finally:
        _otel_session_factory_override.reset(token)


def _get_is_ai(attributes: Mapping[str, Any] | None) -> bool:
    if not attributes:
        return False
    if attributes.get("app.is_ai") is True:
        return True
    return "gen_ai.request.model" in attributes


def _get_string_attr(attributes: Mapping[str, Any] | None, key: str) -> str | None:
    if not attributes:
        return None
    value = attributes.get(key)
    if value is None:
        return None
    return str(value)


def _get_int_attr(attributes: Mapping[str, Any] | None, key: str) -> int | None:
    if not attributes:
        return None
    value = attributes.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except TypeError, ValueError:
        return None


def _get_float_attr(attributes: Mapping[str, Any] | None, key: str) -> float | None:
    if not attributes:
        return None
    value = attributes.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except TypeError, ValueError:
        return None


def _get_uuid_attr(attributes: Mapping[str, Any] | None, key: str) -> UUID | None:
    if not attributes:
        return None
    value = attributes.get(key)
    if value is None:
        return None
    try:
        return UUID(str(value))
    except TypeError, ValueError:
        return None


def _get_bool_attr(attributes: Mapping[str, Any] | None, key: str) -> bool | None:
    if not attributes:
        return None
    value = attributes.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    value_str = str(value).strip().lower()
    if value_str in {"true", "1", "yes"}:
        return True
    if value_str in {"false", "0", "no"}:
        return False
    return None


def _format_span_name(span_name: str, attributes: Mapping[str, Any] | None) -> str:
    del attributes
    return span_name


def _build_telemetry_database_url() -> str | None:
    url = os.getenv("TELEMETRY_DATABASE_URL")
    if not url:
        return None
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _as_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_langfuse_traces_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/v1/traces"):
        return normalized
    if normalized.endswith("/api/public/otel"):
        return f"{normalized}/v1/traces"
    return normalized


def _format_otel_export_routes() -> str:
    return ", ".join(f"{method} {route}" for method, route in _OTEL_EXPORT_TARGET_ROUTES)


def _create_langfuse_span_processor() -> SpanProcessor | None:
    if not _as_truthy(os.getenv(_LANGFUSE_OTEL_ENABLED)):
        return None

    endpoint = os.getenv(_LANGFUSE_OTEL_ENDPOINT, "").strip()
    public_key = os.getenv(_LANGFUSE_PUBLIC_KEY, "").strip()
    secret_key = os.getenv(_LANGFUSE_SECRET_KEY, "").strip()

    if not endpoint or not public_key or not secret_key:
        logger.warning(
            "Langfuse OTel export enabled but required env vars are missing: "
            "LANGFUSE_OTEL_ENDPOINT, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY"
        )
        return None

    auth_string = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
    headers = {"Authorization": f"Basic {auth_string}"}
    ingestion_version = os.getenv(_LANGFUSE_INGESTION_VERSION, "4").strip()
    if ingestion_version:
        headers["x-langfuse-ingestion-version"] = ingestion_version

    traces_endpoint = _normalize_langfuse_traces_endpoint(endpoint)
    exporter = OTLPSpanExporter(endpoint=traces_endpoint, headers=headers)
    logger.info(f"Configured Langfuse OTel exporter endpoint: {traces_endpoint}")
    return _RouteTraceFilteringSpanProcessor(
        BatchSpanProcessor(exporter), routes=_OTEL_EXPORT_TARGET_ROUTES
    )


class _RouteTraceFilteringSpanProcessor(SpanProcessor):
    def __init__(self, delegate: SpanProcessor, *, routes: Sequence[tuple[str, str]]) -> None:
        self.delegate = delegate
        self.routes = frozenset((method.upper(), route) for method, route in routes)
        self._pending_by_trace: dict[int, list[ReadableSpan]] = {}
        self._allowed_trace_ids: set[int] = set()
        self._blocked_trace_ids: set[int] = set()
        self._decision_order: deque[int] = deque()
        self._max_decisions = 4096
        self._max_pending_spans_per_trace = 512

    def _remember_decision(self, trace_id: int, *, allowed: bool) -> None:
        self._allowed_trace_ids.discard(trace_id)
        self._blocked_trace_ids.discard(trace_id)

        if allowed:
            self._allowed_trace_ids.add(trace_id)
        else:
            self._blocked_trace_ids.add(trace_id)

        self._decision_order.append(trace_id)
        while len(self._decision_order) > self._max_decisions:
            stale_trace_id = self._decision_order.popleft()
            self._allowed_trace_ids.discard(stale_trace_id)
            self._blocked_trace_ids.discard(stale_trace_id)
            self._pending_by_trace.pop(stale_trace_id, None)

    @staticmethod
    def _is_root_span(span: ReadableSpan) -> bool:
        return span.parent is None

    def _is_allowed_route_root(self, span: ReadableSpan) -> bool:
        if not self._is_root_span(span):
            return False

        attributes = _serialize_mapping(span.attributes)
        route = _get_string_attr(attributes, "http.route")
        method = _get_string_attr(attributes, "http.method")
        if route is not None and method is not None:
            return (method.upper(), route) in self.routes

        return any(span.name == f"{method} {route}" for method, route in self.routes)

    def on_start(self, span: ReadableSpan, parent_context: object | None = None) -> None:
        del span, parent_context

    def on_end(self, span: ReadableSpan) -> None:
        span_context = span.context
        if span_context is None:
            return

        if _otel_export_enabled.get():
            self.delegate.on_end(span)
            return

        attributes = _serialize_mapping(span.attributes)
        if attributes is not None and attributes.get("app.force_otel_export") is True:
            self.delegate.on_end(span)
            return

        trace_id = span_context.trace_id

        if trace_id in self._allowed_trace_ids:
            self.delegate.on_end(span)
            return

        if trace_id in self._blocked_trace_ids:
            return

        if self._is_allowed_route_root(span):
            self._remember_decision(trace_id, allowed=True)
            pending_spans = self._pending_by_trace.pop(trace_id, [])
            for pending_span in pending_spans:
                self.delegate.on_end(pending_span)
            self.delegate.on_end(span)
            return

        if self._is_root_span(span):
            self._remember_decision(trace_id, allowed=False)
            self._pending_by_trace.pop(trace_id, None)
            return

        pending_spans = self._pending_by_trace.setdefault(trace_id, [])
        if len(pending_spans) < self._max_pending_spans_per_trace:
            pending_spans.append(span)

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


class _OtelSpanTaggingProcessor(SpanProcessor):
    def __init__(self, environment: str | None = None) -> None:
        self.environment = environment

    def on_start(self, span: ReadableSpan, parent_context: object | None = None) -> None:
        del parent_context

        set_attribute = getattr(span, "set_attribute", None)
        if not callable(set_attribute):
            return

        if self.environment is not None:
            set_attribute("langfuse.environment", self.environment)
            set_attribute("deployment.environment.name", self.environment)

    def on_end(self, span: ReadableSpan) -> None:
        del span

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


def _get_telemetry_session_factory() -> async_sessionmaker[AsyncSession] | None:
    global _telemetry_session_factory  # noqa: PLW0603

    if _telemetry_session_factory is not None:
        return _telemetry_session_factory

    telemetry_url = _build_telemetry_database_url()
    if telemetry_url is None:
        return None

    engine = create_async_engine(telemetry_url, echo=False, poolclass=NullPool)
    _telemetry_session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    return _telemetry_session_factory


@asynccontextmanager
async def _get_otel_session() -> AsyncGenerator[AsyncSession]:
    session_factory = _otel_session_factory_override.get()
    if session_factory is None:
        session_factory = _get_telemetry_session_factory()

    if session_factory is None:
        async with get_session() as session:
            yield session
        return

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def configure_otel_span_processor() -> None:
    global _span_processor_provider  # noqa: PLW0603

    tracer_provider = get_tracer_provider()
    if tracer_provider is _span_processor_provider:
        return

    add_processor = getattr(tracer_provider, "add_span_processor", None)
    if add_processor is None:
        tracer_provider = TracerProvider()
        trace.set_tracer_provider(tracer_provider)
        add_processor = tracer_provider.add_span_processor

    langfuse_environment = os.getenv(_LANGFUSE_ENVIRONMENT, "").strip()

    add_processor(_OtelSpanTaggingProcessor(langfuse_environment or None))
    if langfuse_environment:
        logger.info(f"Configured Langfuse environment attribute: {langfuse_environment}")

    logger.info(
        "Configured OTel route filter for external export and DB persistence: "
        f"{_format_otel_export_routes()}"
    )

    langfuse_span_processor = _create_langfuse_span_processor()
    if langfuse_span_processor is not None:
        add_processor(langfuse_span_processor)

    add_processor(
        _RouteTraceFilteringSpanProcessor(
            _DatabaseSpanProcessor(), routes=_OTEL_EXPORT_TARGET_ROUTES
        )
    )
    _span_processor_provider = tracer_provider


class _DatabaseSpanProcessor(SpanProcessor):
    def on_start(self, span: ReadableSpan, parent_context: object | None = None) -> None:
        del span, parent_context

    def on_end(self, span: ReadableSpan) -> None:
        if span.end_time is None:
            return

        span_data = _span_to_payload(span)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_persist_span(span_data))
        else:
            task = loop.create_task(_persist_span(span_data))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


async def _persist_span(span_data: dict[str, Any]) -> None:
    with suppress_instrumentation():
        async with _get_otel_session() as session:
            session.add(OtelSpan(**span_data))


def _span_to_payload(span: ReadableSpan) -> dict[str, Any]:
    start_time = _ns_to_datetime(span.start_time)
    end_time = _ns_to_datetime(span.end_time)
    duration_ms = None
    if span.end_time and span.start_time:
        duration_ms = (span.end_time - span.start_time) / 1_000_000

    attributes = _drop_gen_ai_usage_detail_aliases(_serialize_mapping(span.attributes))
    formatted_name = _format_span_name(span.name, span.attributes)
    request_model = _get_string_attr(attributes, "gen_ai.request.model")
    is_ai = _get_is_ai(attributes)

    events = [
        {
            "name": event.name,
            "timestamp": _serialize_value(_ns_to_datetime(event.timestamp)),
            "attributes": _serialize_mapping(event.attributes),
        }
        for event in span.events
    ]
    links: list[dict[str, Any]] = []
    for link in span.links:
        context = link.context
        links.append(
            {
                "trace_id": format_trace_id(context.trace_id),
                "span_id": format_span_id(context.span_id),
                "attributes": _serialize_mapping(link.attributes),
            }
        )

    instrumentation_scope = span.instrumentation_scope
    scope = None
    if instrumentation_scope is not None:
        scope = {
            "name": instrumentation_scope.name,
            "version": instrumentation_scope.version,
            "schema_url": instrumentation_scope.schema_url,
        }

    resource = {
        "attributes": _serialize_mapping(span.resource.attributes),
        "schema_url": span.resource.schema_url,
    }

    parent_span_id = None
    if span.parent is not None:
        parent_span_id = format_span_id(span.parent.span_id)

    span_context = span.context
    if span_context is None:
        raise RuntimeError("Span context missing")

    return {
        "trace_id": format_trace_id(span_context.trace_id),
        "span_id": format_span_id(span_context.span_id),
        "parent_span_id": parent_span_id,
        "name": formatted_name,
        "kind": span.kind.name,
        "status_code": span.status.status_code.name,
        "status_message": span.status.description,
        "start_time": start_time,
        "end_time": end_time,
        "span_time": start_time or datetime.now(tz=UTC),
        "duration_ms": duration_ms,
        "attributes": attributes,
        "events": events or None,
        "links": links or None,
        "resource": resource,
        "scope": scope,
        "request_model": request_model,
        "provider_name": _get_string_attr(attributes, "gen_ai.provider.name"),
        "server_address": _get_string_attr(attributes, "server.address"),
        "input_tokens": _get_int_attr(attributes, "gen_ai.usage.input_tokens"),
        "output_tokens": _get_int_attr(attributes, "gen_ai.usage.output_tokens"),
        "total_cost": _get_float_attr(attributes, "operation.cost"),
        "is_ai": is_ai,
        "is_embedding": request_model is not None and "embedding" in request_model.lower(),
        "is_internal": _get_bool_attr(attributes, "app.is_internal"),
        "conversation_id": _get_uuid_attr(attributes, "app.conversation_id"),
        "message_id": _get_uuid_attr(attributes, "app.message_id"),
        "total_time": _get_float_attr(attributes, "app.total_time"),
    }


def _serialize_mapping(mapping: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not mapping:
        return None
    serialized = {str(key): _serialize_value(value) for key, value in mapping.items()}
    return serialized or None


def _drop_gen_ai_usage_detail_aliases(attributes: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop pydantic-ai usage detail aliases before persistence.

    pydantic-ai emits `gen_ai.usage.details.*` values as backwards-compatible or
    provider-specific usage details. Persist only canonical OpenTelemetry GenAI attribute names.
    """
    if not attributes:
        return attributes

    for key in list(attributes):
        if key.startswith(_DROPPED_GEN_AI_USAGE_DETAILS_PREFIX):
            attributes.pop(key, None)

    return attributes


def _is_mapping(value: Any) -> TypeGuard[Mapping[str, Any]]:
    return isinstance(value, Mapping)


def _is_sequence(value: Any) -> TypeGuard[Sequence[Any]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if _is_mapping(value):
        return {str(key): _serialize_value(val) for key, val in value.items()}
    if _is_sequence(value):
        return [_serialize_value(item) for item in value]
    return str(value)


def _ns_to_datetime(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)


def span_to_payload(span: ReadableSpan) -> dict[str, Any]:
    return _span_to_payload(span)


async def persist_span(span_data: dict[str, Any]) -> None:
    await _persist_span(span_data)


async def wait_for_pending_spans() -> None:
    tasks = list(_background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
