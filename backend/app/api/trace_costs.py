from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import OtelSpan

if TYPE_CHECKING:
    from collections.abc import Iterable


def trace_total_cost(spans: Iterable[OtelSpan]) -> float | None:
    """Sum persisted span costs for a trace."""
    total_cost: float | None = None
    for span in spans:
        if span.total_cost is not None:
            total_cost = span.total_cost if total_cost is None else total_cost + span.total_cost
    return total_cost


def span_display_costs(spans: Iterable[OtelSpan]) -> dict[str, float]:
    """Return display costs keyed by span id: own cost, else descendant costs."""
    spans_by_id = {span.span_id: span for span in spans}
    display_costs: dict[str, float] = {}

    for span in spans_by_id.values():
        cost = span.total_cost
        if cost is None:
            continue

        display_costs[span.span_id] = cost
        parent_span_id = span.parent_span_id
        visited_span_ids = {span.span_id}
        while parent_span_id is not None and parent_span_id not in visited_span_ids:
            parent_span = spans_by_id.get(parent_span_id)
            if parent_span is None:
                break

            visited_span_ids.add(parent_span_id)
            if parent_span.total_cost is None:
                display_costs[parent_span_id] = display_costs.get(parent_span_id, 0.0) + cost
            parent_span_id = parent_span.parent_span_id

    return display_costs
