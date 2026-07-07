# pyright: reportPrivateUsage=false

from typing import Any, Self, cast

import pytest
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

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
