from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.baggage import get_baggage
from pydantic_ai.messages import TextPart

from app.chat import title
from app.otel_genai import genai_agent_name_scope

_GEN_AI_AGENT_NAME_ATTRIBUTE = "gen_ai.agent.name"


def test_genai_agent_name_scope_sets_and_restores_baggage() -> None:
    previous_agent_name = get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE)

    with genai_agent_name_scope("summary"):
        assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == "summary"

    assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == previous_agent_name


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

    result = await title._run_title_prompt(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        "Title this", agent_name="title"
    )

    assert result == "Generated title"
    assert seen_agent_names == ["title"]
    assert get_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE) == previous_agent_name
