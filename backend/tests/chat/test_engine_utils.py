from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage

from app.chat.engine_utils import (
    ModelSettings,
    run_agent,
    set_direct_model_response_span_attributes,
)
from app.chat.provider_http import ProviderResponseMetadata


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


@pytest.mark.parametrize("model", ["azure/gpt-5.5", "azure/gpt-4o"])
@pytest.mark.parametrize("max_tokens", [None, 0])
def test_model_settings_omits_unset_max_tokens(model: str, max_tokens: int | None) -> None:
    pydantic_settings = ModelSettings(model=model, max_tokens=max_tokens).to_pydantic_settings()

    assert "max_tokens" not in pydantic_settings


def test_model_settings_passes_positive_max_tokens() -> None:
    pydantic_settings = ModelSettings(model="azure/gpt-5.5", max_tokens=4096).to_pydantic_settings()

    assert pydantic_settings.get("max_tokens") == 4096


def test_model_settings_sends_service_tier_only_for_azure_models() -> None:
    azure_settings = ModelSettings(model="azure/gpt-5.5", azure_service_tier="priority")
    azure = azure_settings.to_pydantic_settings()
    azure_default = ModelSettings(
        model="azure/gpt-5.5", azure_service_tier="default"
    ).to_pydantic_settings()
    openrouter = ModelSettings(
        model="openrouter/openai/gpt-5.5", azure_service_tier="priority"
    ).to_pydantic_settings()

    assert azure.get("service_tier") == "priority"
    assert azure_default.get("service_tier") == "default"
    assert "service_tier" not in openrouter
    assert azure_settings.to_dict()["azure_service_tier"] == "priority"
    assert (
        "azure_service_tier"
        not in ModelSettings(
            model="openrouter/openai/gpt-5.5", azure_service_tier="priority"
        ).to_dict()
    )


def test_model_settings_disables_reasoning_for_none_effort() -> None:
    pydantic_settings = ModelSettings(
        model="azure/gpt-5.5", reasoning_effort="none"
    ).to_pydantic_settings()

    assert pydantic_settings.get("thinking") is False


def test_model_settings_preserves_non_gpt5_temperature_and_max_tokens() -> None:
    pydantic_settings = ModelSettings(
        model="azure/gpt-4o", temperature=0.25, max_tokens=1024
    ).to_pydantic_settings()

    assert pydantic_settings == {"temperature": 0.25, "max_tokens": 1024}


def test_set_direct_model_response_span_attributes_records_usage_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _FakeSpan()
    response = ModelResponse(
        parts=[TextPart("helper output")],
        usage=RequestUsage(input_tokens=100, cache_read_tokens=20, output_tokens=10),
        model_name="helper-model-2026-01-01",
        provider_name="azure",
    )

    def fake_calc_price(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(total_price=0.123)

    monkeypatch.setattr("app.chat.engine_utils.calc_price", fake_calc_price)

    set_direct_model_response_span_attributes(
        cast(Any, span), response, configured_model="azure/helper-model"
    )

    assert span.attributes["gen_ai.response.model"] == "helper-model-2026-01-01"
    assert span.attributes["gen_ai.usage.input_tokens"] == 100
    assert span.attributes["gen_ai.usage.cache_read.input_tokens"] == 20
    assert span.attributes["gen_ai.usage.output_tokens"] == 10
    assert span.attributes["operation.cost"] == 0.123
    assert span.attributes["app.llm_response_count"] == 1


@pytest.mark.asyncio
async def test_run_agent_records_requested_and_applied_service_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _FakeSpan()
    responses = [
        ModelResponse(
            parts=[TextPart("first")],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
            model_name="gpt-5.5-2026-04-24",
            provider_name="azure",
            provider_response_id="resp-priority",
        ),
        ModelResponse(
            parts=[TextPart("second")],
            usage=RequestUsage(input_tokens=80, output_tokens=10),
            model_name="gpt-5.5-2026-04-24",
            provider_name="azure",
            provider_response_id="resp-default",
        ),
        ModelResponse(
            parts=[TextPart("streamed")],
            usage=RequestUsage(input_tokens=60, output_tokens=6),
            model_name="gpt-5.5-2026-04-24",
            provider_name="azure",
            provider_response_id="resp-without-captured-tier",
        ),
    ]
    captured_pydantic_settings: list[object] = []

    @contextmanager
    def fake_span(_name: str) -> Generator[_FakeSpan]:
        yield span

    @contextmanager
    def fake_capture(*, enabled: bool) -> Generator[list[ProviderResponseMetadata]]:
        assert enabled is True
        yield [
            ProviderResponseMetadata("resp-priority", "priority", 1000.0),
            ProviderResponseMetadata("resp-default", "default", 2000.0),
        ]

    async def fake_agent_run(*_args: object, **kwargs: object) -> SimpleNamespace:
        captured_pydantic_settings.append(kwargs["model_settings"])
        return SimpleNamespace(output="response", new_messages=lambda: responses)

    def fake_calc_price(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(total_price=0.1)

    monkeypatch.setattr("app.chat.engine_utils.telemetry.span", fake_span)
    monkeypatch.setattr("app.chat.engine_utils.capture_provider_response_metadata", fake_capture)
    monkeypatch.setattr("app.chat.engine_utils.calc_price", fake_calc_price)
    agent = cast(Agent[None, str], SimpleNamespace(run=fake_agent_run))

    await run_agent(
        agent, "User prompt", ModelSettings(model="azure/gpt-5.5", azure_service_tier="priority")
    )

    assert captured_pydantic_settings == [{"service_tier": "priority"}]
    assert span.attributes["openai.request.service_tier"] == "priority"
    assert "openai.response.service_tier" not in span.attributes
    assert json.loads(cast(str, span.attributes["app.openai.response.service_tier.counts"])) == {
        "default": 1,
        "priority": 1,
    }
    assert span.attributes["app.openai.response.service_tier.missing_count"] == 1
    assert span.attributes["app.openai.response.service_tier.fallback_count"] == 1
    metrics = json.loads(cast(str, span.attributes["app.llm_response_metrics"]))
    assert [metric.get("response_service_tier") for metric in metrics] == [
        "priority",
        "default",
        None,
    ]
    assert [metric["request_service_tier"] for metric in metrics] == [
        "priority",
        "priority",
        "priority",
    ]
    assert [metric.get("provider_duration_ms") for metric in metrics] == [1000.0, 2000.0, None]
    assert [metric.get("observed_output_tokens_per_second") for metric in metrics] == [
        20.0,
        5.0,
        None,
    ]
    assert [metric["cost_basis"] for metric in metrics] == ["standard", "standard", "standard"]


@pytest.mark.asyncio
async def test_run_agent_omits_service_tier_span_data_for_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _FakeSpan()
    response = ModelResponse(
        parts=[TextPart("response")],
        usage=RequestUsage(input_tokens=100, output_tokens=20),
        model_name="gpt-5.5-2026-04-24",
        provider_name="azure",
        provider_response_id="resp-default",
    )
    captured_pydantic_settings: list[object] = []

    @contextmanager
    def fake_span(_name: str) -> Generator[_FakeSpan]:
        yield span

    @contextmanager
    def fake_capture(*, enabled: bool) -> Generator[list[ProviderResponseMetadata]]:
        assert enabled is False
        yield []

    async def fake_agent_run(*_args: object, **kwargs: object) -> SimpleNamespace:
        captured_pydantic_settings.append(kwargs["model_settings"])
        return SimpleNamespace(output="response", new_messages=lambda: [response])

    monkeypatch.setattr("app.chat.engine_utils.telemetry.span", fake_span)
    monkeypatch.setattr("app.chat.engine_utils.capture_provider_response_metadata", fake_capture)
    agent = cast(Agent[None, str], SimpleNamespace(run=fake_agent_run))

    await run_agent(
        agent, "User prompt", ModelSettings(model="azure/gpt-5.5", azure_service_tier="default")
    )

    assert captured_pydantic_settings == [{"service_tier": "default"}]
    service_tier_attributes = {
        key: value for key, value in span.attributes.items() if "service_tier" in key
    }
    assert service_tier_attributes == {}
    metrics = json.loads(cast(str, span.attributes["app.llm_response_metrics"]))
    assert len(metrics) == 1
    assert not {
        "request_service_tier",
        "response_service_tier",
        "provider_duration_ms",
        "observed_output_tokens_per_second",
        "cost_basis",
    }.intersection(metrics[0])


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
async def test_run_agent_correlates_trigger_message_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = await _run_fake_agent(
        monkeypatch,
        ModelSettings(model="test-model"),
        metadata={"conversation_id": "conversation-1", "message_id": "message-1"},
    )

    assert span.attributes["app.conversation_id"] == "conversation-1"
    assert span.attributes["app.trigger_message_id"] == "message-1"


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


@pytest.mark.asyncio
async def test_run_agent_adapts_live_event_callback_to_pydantic_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _FakeSpan()
    received_events: list[object] = []
    expected_event = object()

    @contextmanager
    def fake_span(_name: str) -> Generator[_FakeSpan]:
        yield span

    async def fake_agent_run(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        async def event_stream() -> AsyncGenerator[object]:
            yield expected_event

        event_stream_handler = kwargs["event_stream_handler"]
        await event_stream_handler(None, event_stream())
        return SimpleNamespace(output="response", new_messages=list)

    async def handle_event(event: Any) -> None:
        received_events.append(event)

    monkeypatch.setattr("app.chat.engine_utils.telemetry.span", fake_span)
    agent = cast(Agent[None, str], SimpleNamespace(run=fake_agent_run))

    await run_agent(
        agent, "User prompt", ModelSettings(model="test-model"), event_handler=handle_event
    )

    assert received_events == [expected_event]
