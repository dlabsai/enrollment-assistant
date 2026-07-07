from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.api import response_costs


def test_cost_breakdown_uses_generation_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    seen_timestamps: list[datetime | None] = []

    def fake_calc_price(
        usage: Any,
        model_ref: str,
        *,
        provider_id: str | None = None,
        genai_request_timestamp: datetime | None = None,
    ) -> SimpleNamespace:
        del usage, model_ref, provider_id
        seen_timestamps.append(genai_request_timestamp)
        return SimpleNamespace(total_price=1.0)

    monkeypatch.setattr(response_costs, "calc_price", fake_calc_price)

    breakdown = response_costs.cost_breakdown_from_metrics(
        '[{"configured_model":"gpt-5.5","provider_name":"azure","input_tokens":10,"cache_read_tokens":4,"output_tokens":2}]',
        genai_request_timestamp=timestamp,
    )

    assert breakdown == {"input_cost": 1.0, "cache_read_input_cost": 1.0, "output_cost": 1.0}
    assert seen_timestamps == [timestamp, timestamp, timestamp]


def test_price_usage_tries_aliases_for_lookup_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_models: list[str] = []

    def fake_calc_price(
        usage: Any,
        model_ref: str,
        *,
        provider_id: str | None = None,
        genai_request_timestamp: datetime | None = None,
    ) -> SimpleNamespace:
        del usage, provider_id, genai_request_timestamp
        seen_models.append(model_ref)
        if model_ref == "azure/gpt-5.5":
            raise LookupError("unknown deployment alias")
        return SimpleNamespace(total_price=2.0)

    monkeypatch.setattr(response_costs, "calc_price", fake_calc_price)

    assert (
        response_costs.price_usage(
            model="azure/gpt-5.5", provider_id="azure", genai_request_timestamp=None, input_tokens=1
        )
        == 2.0
    )
    assert seen_models == ["azure/gpt-5.5", "gpt-5.5"]


def test_price_usage_propagates_unexpected_pricing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_calc_price(
        usage: Any,
        model_ref: str,
        *,
        provider_id: str | None = None,
        genai_request_timestamp: datetime | None = None,
    ) -> SimpleNamespace:
        del usage, model_ref, provider_id, genai_request_timestamp
        raise RuntimeError("pricing data corrupted")

    monkeypatch.setattr(response_costs, "calc_price", fake_calc_price)

    with pytest.raises(RuntimeError, match="pricing data corrupted"):
        response_costs.price_usage(
            model="gpt-5.5", provider_id="azure", genai_request_timestamp=None, input_tokens=1
        )


def test_summarize_response_costs_aggregates_tokens_cost_and_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_calc_price(
        usage: Any,
        model_ref: str,
        *,
        provider_id: str | None = None,
        genai_request_timestamp: datetime | None = None,
    ) -> SimpleNamespace:
        del model_ref, provider_id, genai_request_timestamp
        return SimpleNamespace(total_price=float(usage.input_tokens + usage.output_tokens))

    monkeypatch.setattr(response_costs, "calc_price", fake_calc_price)

    summary = response_costs.summarize_response_costs(
        [
            response_costs.ResponseCostSpan(
                total_cost=0.25,
                input_tokens=10,
                output_tokens=3,
                attributes={
                    "gen_ai.usage.cache_read.input_tokens": "4",
                    "app.llm_response_metrics": (
                        '[{"configured_model":"gpt-5.5","input_tokens":10,'
                        '"cache_read_tokens":4,"output_tokens":3}]'
                    ),
                },
                created_at=None,
            ),
            response_costs.ResponseCostSpan(
                total_cost=0.75,
                input_tokens=5,
                output_tokens=2,
                attributes={"gen_ai.usage.cache_read.input_tokens": 1},
                created_at=None,
            ),
        ]
    )

    assert summary.response_cost == 1.0
    assert summary.input_tokens == 15
    assert summary.cache_read_input_tokens == 5
    assert summary.output_tokens == 5
    assert summary.cost_breakdown == {
        "input_cost": 6.0,
        "cache_read_input_cost": 4.0,
        "output_cost": 3.0,
    }


def test_summarize_response_costs_excludes_helper_agent_spans() -> None:
    summary = response_costs.summarize_response_costs(
        [
            response_costs.ResponseCostSpan(
                total_cost=0.25,
                input_tokens=10,
                output_tokens=3,
                attributes={"gen_ai.agent.name": "chatbot"},
                created_at=None,
            ),
            response_costs.ResponseCostSpan(
                total_cost=0.75,
                input_tokens=50,
                output_tokens=7,
                attributes={"gen_ai.agent.name": "grounding"},
                created_at=None,
            ),
            response_costs.ResponseCostSpan(
                total_cost=0.5,
                input_tokens=30,
                output_tokens=4,
                attributes={"gen_ai.agent.name": "summary"},
                created_at=None,
            ),
            response_costs.ResponseCostSpan(
                total_cost=0.5,
                input_tokens=20,
                output_tokens=2,
                attributes={"gen_ai.agent.name": "title"},
                created_at=None,
            ),
            response_costs.ResponseCostSpan(
                total_cost=0.5,
                input_tokens=25,
                output_tokens=3,
                attributes={"gen_ai.agent.name": "title_transcript"},
                created_at=None,
            ),
        ]
    )

    assert summary.response_cost == 0.25
    assert summary.input_tokens == 10
    assert summary.output_tokens == 3
