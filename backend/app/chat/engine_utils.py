from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from pydantic import BaseModel
from pydantic_ai import Agent, AgentRunResult, AgentStreamEvent, RunContext
from pydantic_ai.messages import ModelResponse
from pydantic_ai.settings import ModelSettings as PydanticModelSettings

from app import telemetry

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Awaitable, Callable, Sequence

    from pydantic_ai.messages import ModelMessage


type ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]


@dataclass
class ModelSettings:
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: ReasoningEffort | None = None

    def to_pydantic_settings(self) -> PydanticModelSettings:
        """Convert to PydanticAI ModelSettings."""
        if "gpt-5" in self.model:
            if self.reasoning_effort is None:
                return PydanticModelSettings()
            thinking = "minimal" if self.reasoning_effort == "none" else self.reasoning_effort
            return PydanticModelSettings(thinking=thinking)
        return PydanticModelSettings(temperature=self.temperature or 0.0)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        data: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort is not None:
            data["reasoning_effort"] = self.reasoning_effort
        return data


def _split_provider_model(model: str) -> tuple[str | None, str]:
    if "/" in model:
        provider_id, model_ref = model.split("/", 1)
        return provider_id or None, model_ref
    if ":" in model:
        provider_id, model_ref = model.split(":", 1)
        return provider_id or None, model_ref
    return None, model


def _collect_llm_response_metrics[T](
    result: AgentRunResult[T], configured_model: str
) -> tuple[list[dict[str, Any]], dict[str, int | float | None]]:
    provider_id, configured_model_ref = _split_provider_model(configured_model)
    metrics: list[dict[str, Any]] = []

    total_input_tokens = 0
    total_cache_read_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0

    saw_input_tokens = False
    saw_cache_read_tokens = False
    saw_output_tokens = False
    saw_cost = False

    # Use messages produced by this run only. When guardrails retries pass prior
    # chatbot messages via `message_history`, `all_messages()` also includes
    # earlier attempts and would double-count usage/cost on retry spans.
    for message in result.new_messages():
        if not isinstance(message, ModelResponse):
            continue

        input_tokens = message.usage.input_tokens
        cache_read_tokens = message.usage.cache_read_tokens
        output_tokens = message.usage.output_tokens

        cost: float | None = None
        try:
            cost = float(
                calc_price(
                    PriceUsage(
                        input_tokens=input_tokens,
                        cache_read_tokens=cache_read_tokens,
                        output_tokens=output_tokens,
                    ),
                    configured_model_ref,
                    provider_id=provider_id,
                    genai_request_timestamp=message.timestamp,
                ).total_price
            )
        except Exception:
            try:
                cost = float(message.cost().total_price)
            except Exception:
                cost = None

        total_input_tokens += input_tokens
        saw_input_tokens = True
        total_cache_read_tokens += cache_read_tokens
        saw_cache_read_tokens = True
        total_output_tokens += output_tokens
        saw_output_tokens = True
        if cost is not None:
            total_cost += cost
            saw_cost = True

        metrics.append(
            {
                "request_index": len(metrics) + 1,
                "configured_model": configured_model,
                "model_name": message.model_name,
                "provider_name": message.provider_name,
                "provider_url": message.provider_url,
                "input_tokens": input_tokens,
                "cache_read_tokens": cache_read_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
            }
        )

    return metrics, {
        "input_tokens": total_input_tokens if saw_input_tokens else None,
        "cache_read_tokens": total_cache_read_tokens if saw_cache_read_tokens else None,
        "output_tokens": total_output_tokens if saw_output_tokens else None,
        "cost": total_cost if saw_cost else None,
    }


def _genai_output_messages_attribute(content: str) -> str:
    return json.dumps([{"role": "assistant", "content": content}], separators=(",", ":"))


def _trace_output_text(output: Any, *, agent_name: str | None) -> str | None:
    if isinstance(output, str) and output.strip():
        return output
    if isinstance(output, BaseModel) and agent_name == "grounding":
        return json.dumps(output.model_dump(mode="json"), separators=(",", ":"))
    return None


async def run_agent[D, T](
    agent: Agent[D, T],
    prompt: str | None,
    model_settings: ModelSettings,
    *,
    deps: D | None = None,
    metadata: dict[str, Any] | None = None,
    agent_name: str | None = None,
    system_prompt: str | None = None,
    message_history: Sequence[ModelMessage] | None = None,
    event_handler: Callable[[AgentStreamEvent], Awaitable[None]] | None = None,
    result_handler: Callable[[AgentRunResult[T]], None] | None = None,
) -> tuple[AgentRunResult[T], float]:
    """Run an agent with standard boilerplate for timing and tracing.

    Returns:
        Tuple of (result, duration)

    """
    pydantic_settings = model_settings.to_pydantic_settings()

    event_stream_handler: Any = None
    if event_handler is not None:

        async def handle_event_stream(
            _ctx: RunContext[D], event_stream: AsyncIterable[AgentStreamEvent]
        ) -> None:
            async for event in event_stream:
                await event_handler(event)

        event_stream_handler = handle_event_stream

    span_name = f"invoke_agent {agent_name}" if agent_name is not None else "invoke_agent"
    start_time = time.time()
    with telemetry.span(span_name) as span:
        is_ai = True
        span.set_attribute("app.is_ai", is_ai)
        span.set_attribute("gen_ai.request.model", model_settings.model)
        if model_settings.reasoning_effort is not None:
            span.set_attribute("app.reasoning_effort", model_settings.reasoning_effort)
        if system_prompt is not None and system_prompt.strip():
            span.set_attribute("gen_ai.system_instructions", system_prompt)
        if agent_name is not None:
            span.set_attribute("gen_ai.agent.name", agent_name)
        if metadata is not None:
            conversation_id = metadata.get("conversation_id")
            if conversation_id is not None:
                span.set_attribute("app.conversation_id", conversation_id)
            if "conversation_turn" in metadata:
                span.set_attribute("app.conversation_turn", metadata["conversation_turn"])
            if "is_internal" in metadata:
                span.set_attribute("app.is_internal", metadata["is_internal"])
            if "user_id" in metadata:
                span.set_attribute("app.user_id", metadata["user_id"])

        if deps is not None:
            if event_stream_handler is None:
                result = await agent.run(
                    prompt,
                    deps=deps,
                    model_settings=pydantic_settings,
                    metadata=metadata,
                    message_history=message_history,
                )
            else:
                result = await agent.run(
                    prompt,
                    deps=deps,
                    model_settings=pydantic_settings,
                    metadata=metadata,
                    message_history=message_history,
                    event_stream_handler=event_stream_handler,
                )
        elif event_stream_handler is None:
            result = await agent.run(
                prompt,
                deps=deps,  # type: ignore[arg-type]
                model_settings=pydantic_settings,
                metadata=metadata,
                message_history=message_history,
            )
        else:
            result = await agent.run(
                prompt,
                deps=deps,  # type: ignore[arg-type]
                model_settings=pydantic_settings,
                metadata=metadata,
                message_history=message_history,
                event_stream_handler=event_stream_handler,
            )

        if result_handler is not None:
            result_handler(result)

        trace_output_text = _trace_output_text(result.output, agent_name=agent_name)
        if trace_output_text is not None:
            span.set_attribute(
                "gen_ai.output.messages", _genai_output_messages_attribute(trace_output_text)
            )

        if isinstance(result.output, BaseModel) and agent_name == "guardrails":
            output_data = result.output.model_dump(mode="json")
            is_valid = output_data.get("is_valid")
            feedback = output_data.get("feedback")
            if isinstance(is_valid, bool):
                span.set_attribute("app.guardrails.result.is_valid", is_valid)
            if isinstance(feedback, str) and feedback.strip():
                span.set_attribute("app.guardrails.result.feedback", feedback)

        llm_response_metrics, llm_usage_totals = _collect_llm_response_metrics(
            result, model_settings.model
        )
        if llm_response_metrics:
            span.set_attribute(
                "app.llm_response_metrics", json.dumps(llm_response_metrics, separators=(",", ":"))
            )
            span.set_attribute("app.llm_response_count", len(llm_response_metrics))
        if llm_usage_totals["input_tokens"] is not None:
            span.set_attribute("gen_ai.usage.input_tokens", llm_usage_totals["input_tokens"])
        if llm_usage_totals["cache_read_tokens"] is not None:
            span.set_attribute(
                "gen_ai.usage.cache_read.input_tokens", llm_usage_totals["cache_read_tokens"]
            )
        if llm_usage_totals["output_tokens"] is not None:
            span.set_attribute("gen_ai.usage.output_tokens", llm_usage_totals["output_tokens"])
        if llm_usage_totals["cost"] is not None:
            span.set_attribute("operation.cost", llm_usage_totals["cost"])
    duration = time.time() - start_time

    return result, duration


type MessageDict = dict[str, Any]


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    result_lines: list[str] = []
    last_was_empty = False

    for line in lines:
        if not line.strip():
            if not last_was_empty:
                result_lines.append("")
                last_was_empty = True
        else:
            result_lines.append(line.lstrip())
            last_was_empty = False

    return "\n".join(result_lines).strip()


def get_assistant_message_content(message: dict[str, Any]) -> str:
    return message.get(
        "content",
        "[The LLM provider returned an empty assistant message. "
        "This could be due to the provider's guardrails.]",
    )


def get_current_date_gmt_minus_4() -> str:
    return datetime.now(timezone(timedelta(hours=-4))).strftime("%d %b %Y")
