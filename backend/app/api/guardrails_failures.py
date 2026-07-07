from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from datetime import datetime

from pydantic import BaseModel

CHATBOT_AGENT_NAMES = ("chatbot", "chatbot_merged")
GUARDRAILS_AGENT_NAMES = (*CHATBOT_AGENT_NAMES, "guardrails")
GUARDRAILS_URL_SPAN_NAME = "url_guardrails"


@dataclass(frozen=True)
class GuardrailsTraceSpan:
    trace_id: str
    span_id: str
    name: str
    start_time: datetime | None
    span_time: datetime | None
    created_at: datetime | None
    attributes: dict[str, Any] | None


class GuardrailsFailureOut(BaseModel):
    assistant_message: str
    llm_guardrails_feedback: str | None = None
    invalid_urls: list[str] | None = None


def _span_time_key(span: GuardrailsTraceSpan) -> Any:
    return span.start_time or span.span_time or span.created_at


def _bool_value(span: GuardrailsTraceSpan, key: str, value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    parsed = _json_value(span, key, value)
    return parsed if isinstance(parsed, bool) else None


def _json_value(span: GuardrailsTraceSpan, key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value

    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in trace span {span.span_id} attribute {key}: {value}"
        ) from error


def _first_output_text(span: GuardrailsTraceSpan) -> str | None:
    attributes = span.attributes or {}
    key = "gen_ai.output.messages"
    messages = _json_value(span, key, attributes.get(key))
    if not isinstance(messages, list):
        return None
    for message in cast(list[Any], messages):
        if not isinstance(message, dict):
            continue
        content = cast(dict[str, Any], message).get("content")
        if isinstance(content, str) and content.strip() != "":
            return content
    return None


def _is_chatbot_attempt_span(span: GuardrailsTraceSpan) -> bool:
    attributes = span.attributes or {}
    return attributes.get("gen_ai.agent.name") in CHATBOT_AGENT_NAMES


def _llm_guardrails_failure(span: GuardrailsTraceSpan) -> tuple[bool, str | None]:
    attributes = span.attributes or {}
    if attributes.get("gen_ai.agent.name") != "guardrails":
        return False, None
    key = "app.guardrails.result.is_valid"
    if _bool_value(span, key, attributes.get(key)) is not False:
        return False, None
    feedback = attributes.get("app.guardrails.result.feedback")
    return True, feedback if isinstance(feedback, str) and feedback.strip() != "" else None


def _url_guardrails_failure_urls(span: GuardrailsTraceSpan) -> list[str] | None:
    if span.name != GUARDRAILS_URL_SPAN_NAME:
        return None
    attributes = span.attributes or {}
    valid_key = "app.guardrails.url.is_valid"
    if _bool_value(span, valid_key, attributes.get(valid_key)) is not False:
        return None

    urls: list[str] = []
    for key in ("app.guardrails.url.blog_urls", "app.guardrails.url.unknown_urls"):
        value = _json_value(span, key, attributes.get(key))
        if isinstance(value, list):
            urls.extend(url for url in cast(list[Any], value) if isinstance(url, str))
    return urls


def guardrails_failures_from_spans(
    spans: list[GuardrailsTraceSpan],
) -> list[GuardrailsFailureOut] | None:
    failures: list[GuardrailsFailureOut] = []
    current_response: str | None = None
    current_feedback: str | None = None
    current_invalid_urls: list[str] = []
    current_failed = False

    def flush_current() -> None:
        nonlocal current_failed, current_feedback, current_invalid_urls
        if current_response is not None and current_failed:
            failures.append(
                GuardrailsFailureOut(
                    assistant_message=current_response,
                    llm_guardrails_feedback=current_feedback,
                    invalid_urls=current_invalid_urls or None,
                )
            )
        current_failed = False
        current_feedback = None
        current_invalid_urls = []

    for span in sorted(spans, key=_span_time_key):
        if _is_chatbot_attempt_span(span):
            flush_current()
            current_response = _first_output_text(span)
            continue

        llm_failed, feedback = _llm_guardrails_failure(span)
        if llm_failed:
            current_failed = True
            if feedback is not None:
                current_feedback = feedback

        invalid_urls = _url_guardrails_failure_urls(span)
        if invalid_urls is not None:
            current_failed = True
            current_invalid_urls.extend(invalid_urls)

    flush_current()
    return failures or None


def dump_guardrails_failures_from_spans(
    spans: list[GuardrailsTraceSpan],
) -> list[dict[str, Any]] | None:
    failures = guardrails_failures_from_spans(spans)
    if failures is None:
        return None
    return [failure.model_dump(exclude_none=True) for failure in failures]
