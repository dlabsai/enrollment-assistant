# pyright: reportPrivateUsage=false

import asyncio
from typing import Any, Self, cast

import pytest
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app import otel
from app.core.db import async_session_factory
from app.core.db import engine as main_database_engine
from app.otel import (
    _OTEL_EXPORT_TARGET_ROUTES,
    _drop_gen_ai_usage_detail_aliases,
    _RouteTraceFilteringSpanProcessor,
    otel_export_scope,
    otel_session_factory_scope,
    persist_span,
)


class _Delegate(SpanProcessor):
    def __init__(self) -> None:
        self.ended_spans: list[ReadableSpan] = []

    def on_end(self, span: ReadableSpan) -> None:
        self.ended_spans.append(span)


def _root_span(
    *, route: str | None = None, method: str | None = None, name: str = ""
) -> ReadableSpan:
    attributes: dict[str, str] = {}
    if route is not None:
        attributes["http.route"] = route
    if method is not None:
        attributes["http.method"] = method
    span_type = type("Span", (), {"parent": None, "attributes": attributes, "name": name})
    return cast(ReadableSpan, span_type())


def test_otel_route_filter_allows_internal_chat_and_eval_routes() -> None:
    processor = _RouteTraceFilteringSpanProcessor(_Delegate(), routes=_OTEL_EXPORT_TARGET_ROUTES)

    assert processor._is_allowed_route_root(  # noqa: SLF001
        _root_span(route="/api/messages/internal/stream", method="POST")
    )
    assert processor._is_allowed_route_root(  # noqa: SLF001
        _root_span(route="/api/evals/runs/stream", method="POST")
    )
    assert processor._is_allowed_route_root(  # noqa: SLF001
        _root_span(name="POST /api/evals/runs/stream")
    )
    assert not processor._is_allowed_route_root(  # noqa: SLF001
        _root_span(route="/api/evals/reports", method="GET")
    )


@pytest.mark.asyncio
async def test_otel_session_factory_scope_persists_span_with_override() -> None:
    persisted: list[object] = []
    events: list[str] = []

    class FakeSession:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            events.append("exit")

        def add(self, obj: object) -> None:
            persisted.append(obj)

        async def commit(self) -> None:
            events.append("commit")

        async def rollback(self) -> None:
            events.append("rollback")

        async def close(self) -> None:
            events.append("close")

    def fake_session_factory() -> FakeSession:
        return FakeSession()

    with otel_session_factory_scope(cast(Any, fake_session_factory)):
        await persist_span(
            {
                "trace_id": "1234567890abcdef1234567890abcdef",
                "span_id": "1234567890abcdef",
                "name": "eval span",
            }
        )

    assert len(persisted) == 1
    assert events == ["commit", "close", "exit"]


@pytest.mark.asyncio
async def test_telemetry_uses_same_database_through_an_independently_sized_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(otel, "_telemetry_engine", None)
    monkeypatch.setattr(otel, "_telemetry_session_factory", None)
    monkeypatch.setattr(otel.settings, "OTEL_POSTGRES_POOL_SIZE", 7)
    monkeypatch.setattr(otel.settings, "OTEL_POSTGRES_MAX_OVERFLOW", 0)
    monkeypatch.setattr(otel.settings, "OTEL_POSTGRES_POOL_TIMEOUT_SECONDS", 11.0)

    telemetry_session_factory = otel._get_telemetry_session_factory()  # noqa: SLF001
    telemetry_engine = otel._telemetry_engine  # noqa: SLF001

    assert telemetry_engine is not None
    assert telemetry_engine.url == main_database_engine.url
    assert telemetry_engine.pool is not main_database_engine.pool
    assert isinstance(telemetry_engine.pool, AsyncAdaptedQueuePool)
    assert telemetry_engine.pool.size() == 7
    assert telemetry_session_factory is not async_session_factory

    await otel.close_telemetry_database_pool()

    assert otel._telemetry_engine is None  # noqa: SLF001
    assert otel._telemetry_session_factory is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_wait_for_pending_spans_can_drain_only_one_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases = {101: asyncio.Event(), 202: asyncio.Event()}
    started: set[int] = set()
    completed: set[int] = set()

    async def fake_persist_span(span_data: dict[str, Any]) -> None:
        trace_id = cast(int, span_data["trace_id"])
        started.add(trace_id)
        await releases[trace_id].wait()
        completed.add(trace_id)

    monkeypatch.setattr(otel, "_persist_span", fake_persist_span)

    def fake_span_to_payload(span: ReadableSpan) -> dict[str, int]:
        assert span.context is not None
        return {"trace_id": span.context.trace_id}

    monkeypatch.setattr(otel, "_span_to_payload", fake_span_to_payload)
    processor = otel._DatabaseSpanProcessor()  # noqa: SLF001

    def span(trace_id: int) -> ReadableSpan:
        return cast(
            ReadableSpan,
            type(
                "Span",
                (),
                {"context": type("SpanContext", (), {"trace_id": trace_id})(), "end_time": 1},
            )(),
        )

    processor.on_end(span(101))
    processor.on_end(span(202))
    await asyncio.sleep(0)

    try:
        assert started == {101, 202}
        releases[101].set()
        await otel.wait_for_pending_spans(trace_id=101)

        assert completed == {101}
        assert 101 not in otel._background_tasks_by_trace  # noqa: SLF001
        assert 202 in otel._background_tasks_by_trace  # noqa: SLF001
    finally:
        releases[101].set()
        releases[202].set()
        await otel.wait_for_pending_spans()

    assert completed == {101, 202}
    assert not otel._background_tasks  # noqa: SLF001
    assert not otel._background_tasks_by_trace  # noqa: SLF001


@pytest.mark.asyncio
async def test_span_persistence_scope_excludes_other_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases = {101: asyncio.Event(), 202: asyncio.Event()}
    completed: set[int] = set()

    async def fake_persist_span(span_data: dict[str, Any]) -> None:
        trace_id = cast(int, span_data["trace_id"])
        await releases[trace_id].wait()
        completed.add(trace_id)

    def fake_span_to_payload(span: ReadableSpan) -> dict[str, int]:
        assert span.context is not None
        return {"trace_id": span.context.trace_id}

    monkeypatch.setattr(otel, "_persist_span", fake_persist_span)
    monkeypatch.setattr(otel, "_span_to_payload", fake_span_to_payload)
    processor = otel._DatabaseSpanProcessor()  # noqa: SLF001

    def span(trace_id: int) -> ReadableSpan:
        return cast(
            ReadableSpan,
            type(
                "Span",
                (),
                {"context": type("SpanContext", (), {"trace_id": trace_id})(), "end_time": 1},
            )(),
        )

    async def end_span_in_child_task(trace_id: int) -> None:
        processor.on_end(span(trace_id))

    with otel.span_persistence_scope() as response_scope:
        await asyncio.create_task(end_span_in_child_task(101))
    processor.on_end(span(202))
    await asyncio.sleep(0)

    try:
        releases[101].set()
        await otel.wait_for_pending_spans(scope=response_scope)

        assert completed == {101}
        assert not response_scope
        assert 202 in otel._background_tasks_by_trace  # noqa: SLF001
    finally:
        releases[101].set()
        releases[202].set()
        await otel.wait_for_pending_spans()

    assert completed == {101, 202}


def test_otel_export_scope_bypasses_route_filter() -> None:
    delegate = _Delegate()
    processor = _RouteTraceFilteringSpanProcessor(delegate, routes=_OTEL_EXPORT_TARGET_ROUTES)
    span_context = type("SpanContext", (), {"trace_id": 1})()
    span = cast(
        ReadableSpan,
        type(
            "Span",
            (),
            {"context": span_context, "parent": None, "attributes": {}, "name": "eval_run case #1"},
        )(),
    )

    with otel_export_scope(enabled=True):
        processor.on_end(span)

    assert delegate.ended_spans == [span]


def test_drops_pydantic_ai_usage_detail_aliases() -> None:
    attributes = _drop_gen_ai_usage_detail_aliases(
        {
            "gen_ai.usage.input_tokens": 2065,
            "gen_ai.usage.details.cache_read_tokens": 2048,
            "gen_ai.usage.details.cache_write_tokens": 1024,
            "gen_ai.usage.details.provider_specific_tokens": 512,
        }
    )

    assert attributes == {"gen_ai.usage.input_tokens": 2065}


def test_dropping_cache_token_detail_aliases_keeps_canonical_values() -> None:
    attributes = _drop_gen_ai_usage_detail_aliases(
        {"gen_ai.usage.cache_read.input_tokens": 40, "gen_ai.usage.details.cache_read_tokens": 2048}
    )

    assert attributes == {"gen_ai.usage.cache_read.input_tokens": 40}
