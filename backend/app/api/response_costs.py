from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict, cast

from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from sqlalchemy import func

if TYPE_CHECKING:
    from datetime import datetime

_MODEL_DATE_PART_COUNT = 4
RESPONSE_COST_EXCLUDED_AGENT_NAMES = frozenset(
    {"grounding", "summary", "title", "title_transcript"}
)


class ResponseCostBreakdown(TypedDict, total=False):
    input_cost: float | None
    cache_read_input_cost: float | None
    output_cost: float | None


@dataclass(frozen=True)
class ResponseCostSpan:
    total_cost: float | None
    input_tokens: int | None
    output_tokens: int | None
    attributes: dict[str, Any] | None
    created_at: datetime | None


@dataclass(frozen=True)
class ResponseCostSummary:
    response_cost: float | None
    input_tokens: int | None
    cache_read_input_tokens: int | None
    output_tokens: int | None
    cost_breakdown: ResponseCostBreakdown | None


def add_optional_float(current: float | None, value: float | None) -> float | None:
    if value is None:
        return current
    return (current or 0.0) + value


def add_optional_int(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return (current or 0) + value


def int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return int(value)
    return None


def uncached_input_tokens(input_tokens: Any, cache_read_input_tokens: Any) -> int | None:
    input_token_count = int_or_none(input_tokens)
    if input_token_count is None:
        return None
    return max(0, input_token_count - (int_or_none(cache_read_input_tokens) or 0))


def _normalized_model_candidates(model: str) -> list[str]:
    model_without_provider = model.split("/", 1)[-1]
    candidates = [model, model_without_provider]
    model_name_parts = model_without_provider.rsplit("-", 3)
    if len(model_name_parts) == _MODEL_DATE_PART_COUNT and all(
        part.isdigit() for part in model_name_parts[-3:]
    ):
        candidates.append(model_name_parts[0])
    return list(dict.fromkeys(candidates))


def price_usage(
    *,
    model: str,
    provider_id: str | None,
    genai_request_timestamp: datetime | None,
    input_tokens: int = 0,
    cache_read_tokens: int = 0,
    output_tokens: int = 0,
) -> float | None:
    usage = PriceUsage(
        input_tokens=input_tokens, cache_read_tokens=cache_read_tokens, output_tokens=output_tokens
    )
    for model_candidate in _normalized_model_candidates(model):
        try:
            return float(
                calc_price(
                    usage,
                    model_candidate,
                    provider_id=provider_id,
                    genai_request_timestamp=genai_request_timestamp,
                ).total_price
            )
        except LookupError:
            continue
    return None


def cost_breakdown_from_metrics(
    metrics: Any, *, genai_request_timestamp: datetime | None
) -> ResponseCostBreakdown | None:
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    if not isinstance(metrics, list):
        return None

    input_cost: float | None = None
    cache_read_input_cost: float | None = None
    output_cost: float | None = None
    for metric in cast(list[Any], metrics):
        if not isinstance(metric, dict):
            continue
        metric_data = cast(dict[str, Any], metric)
        model = metric_data.get("configured_model") or metric_data.get("model_name")
        if not isinstance(model, str):
            continue
        provider_id = metric_data.get("provider_name")
        if not isinstance(provider_id, str):
            provider_id = None

        input_tokens = int_or_none(metric_data.get("input_tokens")) or 0
        cache_read_tokens = int_or_none(metric_data.get("cache_read_tokens")) or 0
        output_tokens = int_or_none(metric_data.get("output_tokens")) or 0

        input_cost = add_optional_float(
            input_cost,
            price_usage(
                model=model,
                provider_id=provider_id,
                genai_request_timestamp=genai_request_timestamp,
                input_tokens=uncached_input_tokens(input_tokens, cache_read_tokens) or 0,
            ),
        )
        cache_read_input_cost = add_optional_float(
            cache_read_input_cost,
            price_usage(
                model=model,
                provider_id=provider_id,
                genai_request_timestamp=genai_request_timestamp,
                input_tokens=cache_read_tokens,
                cache_read_tokens=cache_read_tokens,
            ),
        )
        output_cost = add_optional_float(
            output_cost,
            price_usage(
                model=model,
                provider_id=provider_id,
                genai_request_timestamp=genai_request_timestamp,
                output_tokens=output_tokens,
            ),
        )

    if input_cost is None and cache_read_input_cost is None and output_cost is None:
        return None
    return {
        "input_cost": input_cost,
        "cache_read_input_cost": cache_read_input_cost,
        "output_cost": output_cost,
    }


def cost_breakdown_from_attributes(
    attributes: dict[str, Any] | None, *, genai_request_timestamp: datetime | None
) -> ResponseCostBreakdown | None:
    if attributes is None:
        return None
    return cost_breakdown_from_metrics(
        attributes.get("app.llm_response_metrics"), genai_request_timestamp=genai_request_timestamp
    )


def cache_read_input_tokens_from_attributes(attributes: dict[str, Any] | None) -> int | None:
    if attributes is None:
        return None
    return int_or_none(attributes.get("gen_ai.usage.cache_read.input_tokens"))


def include_response_cost_span(attributes: dict[str, Any] | None) -> bool:
    if attributes is None:
        return True
    agent_name = attributes.get("gen_ai.agent.name")
    return not isinstance(agent_name, str) or agent_name not in RESPONSE_COST_EXCLUDED_AGENT_NAMES


def response_cost_span_condition(span: Any) -> Any:
    return ~func.coalesce(
        func.jsonb_extract_path_text(span.attributes, "gen_ai.agent.name"), ""
    ).in_(tuple(RESPONSE_COST_EXCLUDED_AGENT_NAMES))


def merge_cost_breakdowns(
    current: ResponseCostBreakdown | None, value: ResponseCostBreakdown | None
) -> ResponseCostBreakdown | None:
    if value is None:
        return current
    if current is None:
        return value
    return {
        "input_cost": add_optional_float(current.get("input_cost"), value.get("input_cost")),
        "cache_read_input_cost": add_optional_float(
            current.get("cache_read_input_cost"), value.get("cache_read_input_cost")
        ),
        "output_cost": add_optional_float(current.get("output_cost"), value.get("output_cost")),
    }


def summarize_response_costs(spans: list[ResponseCostSpan]) -> ResponseCostSummary:
    total_cost: float | None = None
    input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None
    cost_breakdown: ResponseCostBreakdown | None = None

    for span in spans:
        if not include_response_cost_span(span.attributes):
            continue
        if span.total_cost is not None:
            total_cost = add_optional_float(total_cost, float(span.total_cost))
        cost_breakdown = merge_cost_breakdowns(
            cost_breakdown,
            cost_breakdown_from_attributes(
                span.attributes, genai_request_timestamp=span.created_at
            ),
        )
        input_tokens = add_optional_int(input_tokens, span.input_tokens)
        cache_read_input_tokens = add_optional_int(
            cache_read_input_tokens, cache_read_input_tokens_from_attributes(span.attributes)
        )
        output_tokens = add_optional_int(output_tokens, span.output_tokens)

    return ResponseCostSummary(
        response_cost=total_cost,
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
        cost_breakdown=cost_breakdown,
    )
