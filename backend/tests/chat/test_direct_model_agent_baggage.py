from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from opentelemetry.baggage import get_baggage
from pydantic_ai.messages import TextPart

from app import otel_genai
from app.chat import title
from app.otel_genai import genai_agent_name_scope, genai_helper_trace_scope

_GEN_AI_AGENT_NAME_ATTRIBUTE = "gen_ai.agent.name"


def _ignore_response_attributes(*_args: Any, **_kwargs: Any) -> None:
    return None


def test_genai_agent_name_scope_sets_and_restores_baggage() -> None:
    previous_agent_name = get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE)

    with genai_agent_name_scope("summary"):
        assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == "summary"

    assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == previous_agent_name


def test_genai_helper_trace_scope_correlates_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[str, dict[str, object]]] = []

    class FakeTracer:
        @contextmanager
        def start_as_current_span(
            self, name: str, *, kind: object, attributes: dict[str, object]
        ) -> Any:
            del kind
            started.append((name, attributes))
            yield SimpleNamespace()

    monkeypatch.setattr(otel_genai, "_TRACER", FakeTracer())

    with genai_helper_trace_scope(
        "summary",
        model="azure/helper-model",
        conversation_id="conversation-1",
        trigger_message_id="message-1",
        is_internal=True,
    ):
        assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == "summary"

    assert started == [
        (
            "invoke_agent summary",
            {
                "gen_ai.agent.name": "summary",
                "app.is_ai": True,
                "gen_ai.request.model": "azure/helper-model",
                "app.conversation_id": "conversation-1",
                "app.trigger_message_id": "message-1",
                "app.is_internal": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_title_direct_model_request_sets_agent_name_baggage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_agent_name = get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE)
    seen_agent_names: list[object | None] = []

    async def fake_model_request(*_: Any, **__: Any) -> SimpleNamespace:
        seen_agent_names.append(get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE))
        return SimpleNamespace(parts=[TextPart(content="Generated title")])

    monkeypatch.setattr(title, "model_request", fake_model_request)
    monkeypatch.setattr(
        title, "set_direct_model_response_span_attributes", _ignore_response_attributes
    )

    result = await title._run_title_prompt(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        "Title this", agent_name="title"
    )

    assert result == "Generated title"
    assert seen_agent_names == ["title"]
    assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == previous_agent_name


@pytest.mark.asyncio
async def test_title_direct_model_request_correlates_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid4()
    message_id = uuid4()
    helper_calls: list[dict[str, object]] = []

    @contextmanager
    def fake_helper_scope(agent_name: str, **metadata: object) -> Any:
        helper_calls.append({"agent_name": agent_name, **metadata})
        with genai_agent_name_scope(agent_name):
            yield

    async def fake_model_request(*_: Any, **__: Any) -> SimpleNamespace:
        return SimpleNamespace(parts=[TextPart(content="Generated title")])

    monkeypatch.setattr(title.settings, "TITLE_MODEL", "azure/title-model")
    monkeypatch.setattr(title.settings, "SUMMARIZER_MODEL", "azure/summary-model")
    monkeypatch.setattr(title, "genai_helper_trace_scope", fake_helper_scope)
    monkeypatch.setattr(title, "model_request", fake_model_request)
    monkeypatch.setattr(
        title, "set_direct_model_response_span_attributes", _ignore_response_attributes
    )

    result = await title._run_title_prompt(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        "Title this",
        agent_name="title_transcript",
        conversation_id=conversation_id,
        trigger_message_id=message_id,
        is_internal=True,
    )

    assert result == "Generated title"
    assert helper_calls == [
        {
            "agent_name": "title_transcript",
            "model": "azure/title-model",
            "conversation_id": str(conversation_id),
            "trigger_message_id": str(message_id),
            "is_internal": True,
        }
    ]
