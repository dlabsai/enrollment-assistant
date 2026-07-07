from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel

from app.api.response_costs import cost_breakdown_from_metrics, uncached_input_tokens
from app.models import OtelSpan

TraceOverviewItemType = Literal[
    "agent",
    "llm",
    "tool",
    "retrieval",
    "embedding",
    "url_guardrails",
    "conversation_turn",
    "evaluation",
    "evaluation_case",
    "evaluation_result",
    "other",
]


class TraceOverviewItemOut(BaseModel):
    id: str
    span_id: str
    parent_span_id: str | None
    type: TraceOverviewItemType
    title: str
    subtitle: str | None = None
    start_time: dt.datetime | None = None
    duration_ms: float | None = None
    status_code: str | None = None
    data: dict[str, Any]


def build_trace_overview(spans: list[OtelSpan]) -> list[TraceOverviewItemOut]:
    grouped_operations = _group_tool_child_operations(spans)
    guardrail_counts = _count_guardrails_by_conversation_turn(spans)

    overview: list[TraceOverviewItemOut] = []
    for span in spans:
        if span.span_id in grouped_operations.hidden_span_ids:
            continue
        overview.append(
            _project_span(
                span,
                embedding_spans=grouped_operations.embeddings_by_tool_span_id.get(span.span_id, []),
                guardrail_counts=guardrail_counts.get(span.span_id),
            )
        )

    return overview


@dataclass(frozen=True)
class _GroupedToolOperations:
    hidden_span_ids: set[str]
    embeddings_by_tool_span_id: dict[str, list[OtelSpan]]


@dataclass(frozen=True)
class _GuardrailCounts:
    checks: int = 0
    failures: int = 0


def _group_tool_child_operations(spans: list[OtelSpan]) -> _GroupedToolOperations:
    spans_by_id = {span.span_id: span for span in spans}
    hidden_span_ids: set[str] = set()
    embeddings_by_tool_span_id: dict[str, list[OtelSpan]] = {}

    for span in spans:
        if not (_is_retrieval_span(span) or _is_embedding_span(span)):
            continue
        tool_span_id = _nearest_tool_ancestor_id(span, spans_by_id)
        if tool_span_id is None:
            continue

        hidden_span_ids.add(span.span_id)
        if _is_embedding_span(span):
            embeddings_by_tool_span_id.setdefault(tool_span_id, []).append(span)

    for grouped_spans in embeddings_by_tool_span_id.values():
        grouped_spans.sort(key=_span_sort_key)

    return _GroupedToolOperations(
        hidden_span_ids=hidden_span_ids, embeddings_by_tool_span_id=embeddings_by_tool_span_id
    )


def _nearest_tool_ancestor_id(span: OtelSpan, spans_by_id: dict[str, OtelSpan]) -> str | None:
    parent_span_id = span.parent_span_id
    while parent_span_id:
        parent_span = spans_by_id.get(parent_span_id)
        if parent_span is None:
            return None
        if _is_tool_span(parent_span):
            return parent_span.span_id
        parent_span_id = parent_span.parent_span_id
    return None


def _count_guardrails_by_conversation_turn(spans: list[OtelSpan]) -> dict[str, _GuardrailCounts]:
    spans_by_id = {span.span_id: span for span in spans}
    counts: dict[str, _GuardrailCounts] = {}

    for span in spans:
        attributes = span.attributes or {}
        is_valid = attributes.get("app.guardrails.result.is_valid")
        if not isinstance(is_valid, bool):
            continue

        parent_span_id = span.parent_span_id
        while parent_span_id:
            parent_span = spans_by_id.get(parent_span_id)
            if parent_span is None:
                break
            if "handle_conversation_turn" in parent_span.name:
                current = counts.get(parent_span.span_id, _GuardrailCounts())
                counts[parent_span.span_id] = _GuardrailCounts(
                    checks=current.checks + 1, failures=current.failures + (0 if is_valid else 1)
                )
                break
            parent_span_id = parent_span.parent_span_id

    return counts


def _is_tool_span(span: OtelSpan) -> bool:
    attributes = span.attributes or {}
    return (
        _string_value(attributes.get("gen_ai.operation.name")) == "execute_tool"
        or _string_value(attributes.get("gen_ai.tool.name")) is not None
        or span.name.startswith("execute_tool ")
    )


def _is_retrieval_span(span: OtelSpan) -> bool:
    attributes = span.attributes or {}
    return _string_value(
        attributes.get("gen_ai.operation.name")
    ) == "retrieval" or span.name.startswith("retrieval ")


def _is_embedding_span(span: OtelSpan) -> bool:
    attributes = span.attributes or {}
    return (
        _string_value(attributes.get("gen_ai.operation.name")) == "embeddings"
        or span.is_embedding is True
        or span.name.startswith("embeddings ")
    )


def _is_evaluation_span(span: OtelSpan) -> bool:
    return span.parent_span_id is None and span.name.startswith("Evaluation:")


def _is_evaluation_case_span(span: OtelSpan) -> bool:
    attributes = span.attributes or {}
    return (
        span.name.startswith("eval_run ")
        and _string_value(attributes.get("app.eval.case_name")) is not None
        and attributes.get("app.eval.run_index") is not None
    )


def _is_evaluation_result_span(span: OtelSpan) -> bool:
    attributes = span.attributes or {}
    return (
        span.name == "gen_ai.evaluation.result"
        or _string_value(attributes.get("gen_ai.evaluation.name")) is not None
    )


def _span_sort_key(span: OtelSpan) -> dt.datetime:
    return (
        span.start_time
        or span.span_time
        or span.created_at
        or dt.datetime.min.replace(tzinfo=dt.UTC)
    )


def _project_span(
    span: OtelSpan,
    *,
    embedding_spans: list[OtelSpan] | None = None,
    guardrail_counts: _GuardrailCounts | None = None,
) -> TraceOverviewItemOut:
    attributes = span.attributes or {}
    operation_name = _string_value(attributes.get("gen_ai.operation.name"))

    if _is_evaluation_result_span(span):
        return _evaluation_result_item(span, attributes)
    if _is_evaluation_case_span(span):
        return _evaluation_case_item(span, attributes)
    if _is_evaluation_span(span):
        return _evaluation_item(span, attributes)
    if "handle_conversation_turn" in span.name:
        return _conversation_turn_item(span, attributes, guardrail_counts=guardrail_counts)
    if span.name == "url_guardrails":
        return _url_guardrails_item(span, attributes)
    if _is_tool_span(span):
        return _tool_item(span, attributes, embedding_spans=embedding_spans or [])
    if _is_retrieval_span(span):
        return _retrieval_item(span, attributes)
    if _is_embedding_span(span):
        return _embedding_item(span, attributes)
    if _string_value(attributes.get("gen_ai.agent.name")) is not None:
        return _agent_item(span, attributes)
    if operation_name == "chat" or span.request_model is not None or span.is_ai is True:
        return _llm_item(span, attributes)
    return _base_item(span, item_type="other", title=span.name, data={})


def _tool_item(
    span: OtelSpan, attributes: dict[str, Any], *, embedding_spans: list[OtelSpan]
) -> TraceOverviewItemOut:
    tool_name = _string_value(attributes.get("gen_ai.tool.name")) or _suffix_after(
        span.name, "execute_tool "
    )
    tool_type = _string_value(attributes.get("gen_ai.tool.type"))
    arguments = _json_attribute(span, attributes, "gen_ai.tool.call.arguments")
    result = _json_or_string_attribute(attributes, "gen_ai.tool.call.result")
    dedupe = _json_attribute(span, attributes, "app.document_tool.find_document_chunks.dedupe")
    embedding_data = _embedding_summary(embedding_spans[0]) if embedding_spans else {}
    return _base_item(
        span,
        item_type="tool",
        title=f"Tool: {tool_name}" if tool_name else "Tool",
        subtitle=tool_type,
        data=_compact(
            {
                "tool_name": tool_name,
                "tool_type": tool_type,
                "call_id": _string_value(attributes.get("gen_ai.tool.call.id")),
                "arguments": arguments,
                "embedding_model": embedding_data.get("model"),
                "embedding_duration_ms": embedding_data.get("duration_ms"),
                "embedding_input_tokens": embedding_data.get("input_tokens"),
                "dedupe": dedupe,
                "result": result,
            }
        ),
    )


def _embedding_summary(span: OtelSpan) -> dict[str, Any]:
    attributes = span.attributes or {}
    return _compact(
        {
            "duration_ms": span.duration_ms,
            "model": _string_value(attributes.get("gen_ai.request.model")) or span.request_model,
            "input_tokens": _first_present(
                span.input_tokens,
                _json_value(
                    span, "gen_ai.usage.input_tokens", attributes.get("gen_ai.usage.input_tokens")
                ),
            ),
        }
    )


def _retrieval_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    data_source_id = _string_value(attributes.get("gen_ai.data_source.id")) or _suffix_after(
        span.name, "retrieval "
    )
    documents = _json_attribute(span, attributes, "gen_ai.retrieval.documents")
    return _base_item(
        span,
        item_type="retrieval",
        title=f"Retrieval: {data_source_id}" if data_source_id else "Retrieval",
        subtitle=_string_value(attributes.get("gen_ai.retrieval.query.text")),
        data=_compact(
            {
                "data_source_id": data_source_id,
                "query": _string_value(attributes.get("gen_ai.retrieval.query.text")),
                "top_k": _json_value(
                    span, "gen_ai.request.top_k", attributes.get("gen_ai.request.top_k")
                ),
                "documents": documents,
            }
        ),
    )


def _embedding_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    model = _string_value(attributes.get("gen_ai.request.model")) or span.request_model
    return _base_item(
        span,
        item_type="embedding",
        title=f"Embeddings: {model}" if model else "Embeddings",
        data=_compact(
            {
                "model": model,
                "provider_name": span.provider_name
                or _string_value(attributes.get("gen_ai.provider.name")),
                "input_tokens": _first_present(
                    span.input_tokens,
                    _json_value(
                        span,
                        "gen_ai.usage.input_tokens",
                        attributes.get("gen_ai.usage.input_tokens"),
                    ),
                ),
            }
        ),
    )


def _llm_usage_data(span: OtelSpan, attributes: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _first_present(
        span.input_tokens,
        _json_value(span, "gen_ai.usage.input_tokens", attributes.get("gen_ai.usage.input_tokens")),
    )
    cache_read_input_tokens = _json_value(
        span,
        "gen_ai.usage.cache_read.input_tokens",
        attributes.get("gen_ai.usage.cache_read.input_tokens"),
    )
    output_tokens = _first_present(
        span.output_tokens,
        _json_value(
            span, "gen_ai.usage.output_tokens", attributes.get("gen_ai.usage.output_tokens")
        ),
    )
    return {
        "input_tokens": input_tokens,
        "uncached_input_tokens": uncached_input_tokens(input_tokens, cache_read_input_tokens),
        "cache_read_input_tokens": cache_read_input_tokens,
        "output_tokens": output_tokens,
    }


def _agent_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    agent_name = _string_value(attributes.get("gen_ai.agent.name"))
    model = _model_value(span, attributes)
    output_messages = _json_attribute(span, attributes, "gen_ai.output.messages")
    system_instructions = _string_value(attributes.get("gen_ai.system_instructions"))
    guardrails_is_valid = _json_attribute(span, attributes, "app.guardrails.result.is_valid")
    guardrails_feedback = _string_value(attributes.get("app.guardrails.result.feedback"))
    llm_response_metrics = _json_attribute(span, attributes, "app.llm_response_metrics")
    return _base_item(
        span,
        item_type="agent",
        title=f"Agent: {agent_name}" if agent_name else "Agent",
        subtitle=model,
        data=_compact(
            {
                "agent_name": agent_name,
                "model": model,
                "provider_name": span.provider_name
                or _string_value(attributes.get("gen_ai.provider.name")),
                "reasoning_effort": _string_value(attributes.get("app.reasoning_effort")),
                **_llm_usage_data(span, attributes),
                "total_cost": span.total_cost,
                "cost_breakdown": cost_breakdown_from_metrics(
                    llm_response_metrics, genai_request_timestamp=span.created_at
                ),
                "llm_response_metrics": llm_response_metrics,
                "system_instructions": system_instructions,
                "output_messages": output_messages,
                "output_text": _first_message_content(output_messages),
                "guardrails_is_valid": guardrails_is_valid,
                "guardrails_feedback": guardrails_feedback,
            }
        ),
    )


def _llm_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    model = _model_value(span, attributes)
    output_messages = _json_attribute(span, attributes, "gen_ai.output.messages")
    system_instructions = _string_value(attributes.get("gen_ai.system_instructions"))
    llm_response_metrics = _json_attribute(span, attributes, "app.llm_response_metrics")
    return _base_item(
        span,
        item_type="llm",
        title=f"LLM: {model}" if model else "LLM",
        data=_compact(
            {
                "model": model,
                "provider_name": span.provider_name
                or _string_value(attributes.get("gen_ai.provider.name")),
                "server_address": span.server_address,
                "reasoning_effort": _string_value(attributes.get("app.reasoning_effort")),
                **_llm_usage_data(span, attributes),
                "total_cost": span.total_cost,
                "cost_breakdown": cost_breakdown_from_metrics(
                    llm_response_metrics, genai_request_timestamp=span.created_at
                ),
                "llm_response_metrics": llm_response_metrics,
                "system_instructions": system_instructions,
                "output_messages": output_messages,
                "output_text": _first_message_content(output_messages),
            }
        ),
    )


def _url_guardrails_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    is_valid = _json_attribute(span, attributes, "app.guardrails.url.is_valid")
    blog_urls = _json_attribute(span, attributes, "app.guardrails.url.blog_urls")
    unknown_urls = _json_attribute(span, attributes, "app.guardrails.url.unknown_urls")
    return _base_item(
        span,
        item_type="url_guardrails",
        title="URL Guardrails",
        subtitle="Allowed" if is_valid is True else "Blocked" if is_valid is False else None,
        data=_compact(
            {
                "is_valid": is_valid,
                "blog_urls": blog_urls if _is_non_empty_list(blog_urls) else None,
                "unknown_urls": unknown_urls if _is_non_empty_list(unknown_urls) else None,
            }
        ),
    )


def _conversation_turn_item(
    span: OtelSpan, attributes: dict[str, Any], *, guardrail_counts: _GuardrailCounts | None = None
) -> TraceOverviewItemOut:
    guardrail_failures = guardrail_counts.failures if guardrail_counts is not None else None
    chatbot_retry_count = max(guardrail_counts.checks - 1, 0) if guardrail_counts else None
    input_messages = _json_attribute(span, attributes, "gen_ai.input.messages")
    return _base_item(
        span,
        item_type="conversation_turn",
        title="Conversation Turn",
        subtitle=_string_value(attributes.get("app.message_id")),
        data=_compact(
            {
                "conversation_id": _string_value(attributes.get("app.conversation_id")),
                "message_id": _string_value(attributes.get("app.message_id")),
                "conversation_turn": _json_attribute(span, attributes, "app.conversation_turn"),
                "input_messages": input_messages,
                "input_text": _first_message_content(input_messages),
                "guardrails_blocked": _json_attribute(span, attributes, "app.guardrails_blocked"),
                "guardrail_failures": guardrail_failures,
                "guardrail_retries": chatbot_retry_count,
                "total_time": _first_present(
                    span.total_time, _json_attribute(span, attributes, "app.total_time")
                ),
                "guardrail_time": _json_attribute(span, attributes, "app.guardrail_time"),
                "chatbot_times": _json_attribute(span, attributes, "app.chatbot_times"),
                "guardrail_times": _json_attribute(span, attributes, "app.guardrail_times"),
            }
        ),
    )


def _evaluation_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    dataset_name = _string_value(attributes.get("dataset_name")) or _suffix_after(
        span.name, "Evaluation:"
    )
    return _base_item(
        span,
        item_type="evaluation",
        title=f"Evaluation: {dataset_name}" if dataset_name else "Evaluation",
        data=_compact(
            {
                "dataset_name": dataset_name,
                "total_cases": _json_attribute(span, attributes, "total_cases"),
                "repeats": _json_attribute(span, attributes, "repeats"),
                "total_runs": _json_attribute(span, attributes, "total_runs"),
                "max_concurrency": _json_attribute(span, attributes, "max_concurrency"),
            }
        ),
    )


def _evaluation_case_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    case_name = _string_value(attributes.get("app.eval.case_name"))
    run_index = _json_attribute(span, attributes, "app.eval.run_index")
    case_title = f"Case Run: {case_name}" if case_name else "Case Run"
    if run_index is not None:
        case_title = f"{case_title} #{run_index}"
    return _base_item(
        span,
        item_type="evaluation_case",
        title=case_title,
        data=_compact({"case_name": case_name, "run_index": run_index}),
    )


def _evaluation_result_item(span: OtelSpan, attributes: dict[str, Any]) -> TraceOverviewItemOut:
    evaluation_name = _string_value(attributes.get("gen_ai.evaluation.name"))
    score_label = _string_value(attributes.get("gen_ai.evaluation.score.label"))
    score_value = _json_attribute(span, attributes, "gen_ai.evaluation.score.value")
    explanation = _string_value(attributes.get("gen_ai.evaluation.explanation"))
    title = f"Evaluation Result: {evaluation_name}" if evaluation_name else "Evaluation Result"
    subtitle = score_label or (str(score_value) if score_value is not None else None)
    return _base_item(
        span,
        item_type="evaluation_result",
        title=title,
        subtitle=subtitle,
        data=_compact(
            {
                "evaluation_name": evaluation_name,
                "score_label": score_label,
                "score_value": score_value,
                "explanation": explanation,
                "evaluator_name": _string_value(attributes.get("app.eval.evaluator.name")),
                "result_kind": _string_value(attributes.get("app.eval.result.kind")),
                "case_name": _string_value(attributes.get("app.eval.case_name")),
                "run_index": _json_attribute(span, attributes, "app.eval.run_index"),
            }
        ),
    )


def _base_item(
    span: OtelSpan,
    *,
    item_type: TraceOverviewItemType,
    title: str,
    data: dict[str, Any],
    subtitle: str | None = None,
) -> TraceOverviewItemOut:
    return TraceOverviewItemOut(
        id=span.span_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        type=item_type,
        title=title,
        subtitle=subtitle,
        start_time=span.start_time or span.span_time or span.created_at,
        duration_ms=span.duration_ms,
        status_code=span.status_code,
        data=data,
    )


def _model_value(span: OtelSpan, attributes: dict[str, Any]) -> str | None:
    return _string_value(attributes.get("gen_ai.request.model")) or span.request_model


def _json_attribute(span: OtelSpan, attributes: dict[str, Any], key: str) -> Any:
    if key not in attributes:
        return None
    return _json_value(span, key, attributes[key])


def _json_or_string_attribute(attributes: dict[str, Any], key: str) -> Any:
    if key not in attributes:
        return None
    value = attributes[key]
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _json_value(span: OtelSpan, key: str, value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in trace span {span.span_id} attribute {key}: {value}"
        ) from error


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _suffix_after(value: str, prefix: str) -> str | None:
    if value.startswith(prefix):
        suffix = value[len(prefix) :].strip()
        return suffix or None
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _is_non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and value != []


def _first_message_content(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in cast(list[Any], messages):
        if isinstance(message, dict):
            content = _string_value(cast(dict[str, Any], message).get("content"))
            if content is not None:
                return content
    return None


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
