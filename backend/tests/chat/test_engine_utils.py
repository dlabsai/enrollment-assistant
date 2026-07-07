from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest
from pydantic_ai import Agent

from app.chat.engine_utils import ModelSettings, run_agent


class _FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


async def _run_fake_agent(
    monkeypatch: pytest.MonkeyPatch, model_settings: ModelSettings, **run_kwargs: Any
) -> _FakeSpan:
    spans: list[_FakeSpan] = []

    @contextmanager
    def fake_span(_name: str) -> Generator[_FakeSpan]:
        span = _FakeSpan()
        spans.append(span)
        yield span

    async def fake_agent_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(output="response", new_messages=list)

    monkeypatch.setattr("app.chat.engine_utils.telemetry.span", fake_span)

    agent = cast(Agent[None, str], SimpleNamespace(run=fake_agent_run))

    await run_agent(agent, "User prompt", model_settings, **run_kwargs)

    return spans[0]


@pytest.mark.asyncio
async def test_run_agent_stores_system_prompt_on_otel_span(monkeypatch: pytest.MonkeyPatch) -> None:
    span = await _run_fake_agent(
        monkeypatch, ModelSettings(model="test-model"), system_prompt="System instructions"
    )

    assert span.attributes["gen_ai.system_instructions"] == "System instructions"
    assert "gen_ai.input.messages" not in span.attributes


@pytest.mark.asyncio
async def test_run_agent_stores_reasoning_effort_on_otel_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = await _run_fake_agent(
        monkeypatch, ModelSettings(model="azure/gpt-5.5", reasoning_effort="xhigh")
    )

    assert span.attributes["app.reasoning_effort"] == "xhigh"


@pytest.mark.asyncio
async def test_run_agent_calls_result_handler_before_span_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _FakeSpan()
    span_open = False
    handler_saw_open_span: bool | None = None

    @contextmanager
    def fake_span(_name: str) -> Generator[_FakeSpan]:
        nonlocal span_open
        span_open = True
        yield span
        span_open = False

    async def fake_agent_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(output="response", new_messages=list)

    def result_handler(result: Any) -> None:
        nonlocal handler_saw_open_span
        assert result.output == "response"
        handler_saw_open_span = span_open
        span.set_attribute("app.result_handler", "inside-span")

    monkeypatch.setattr("app.chat.engine_utils.telemetry.span", fake_span)

    agent = cast(Agent[None, str], SimpleNamespace(run=fake_agent_run))

    await run_agent(
        agent, "User prompt", ModelSettings(model="test-model"), result_handler=result_handler
    )

    assert handler_saw_open_span is True
    assert span.attributes["app.result_handler"] == "inside-span"
