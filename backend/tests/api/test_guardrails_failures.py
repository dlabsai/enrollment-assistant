from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.api.guardrails_failures import GuardrailsTraceSpan, guardrails_failures_from_spans


def _span(
    *, span_id: str, name: str, attributes: dict[str, Any], seconds: int
) -> GuardrailsTraceSpan:
    started_at = datetime(2026, 5, 24, 12, 0, tzinfo=UTC) + timedelta(seconds=seconds)
    return GuardrailsTraceSpan(
        trace_id="trace-1",
        span_id=span_id,
        name=name,
        start_time=started_at,
        span_time=started_at,
        created_at=started_at,
        attributes=attributes,
    )


def _chatbot_span(
    span_id: str, response: str, *, seconds: int, agent_name: str = "chatbot"
) -> GuardrailsTraceSpan:
    return _span(
        span_id=span_id,
        name=f"invoke_agent {agent_name}",
        attributes={
            "gen_ai.agent.name": agent_name,
            "gen_ai.output.messages": json.dumps([{"role": "assistant", "content": response}]),
        },
        seconds=seconds,
    )


def test_guardrails_failures_from_spans_groups_failed_attempts_by_chatbot_response() -> None:
    failures = guardrails_failures_from_spans(
        [
            _chatbot_span("chatbot-1", "Use the made-up page.", seconds=1),
            _span(
                span_id="llm-guardrails-1",
                name="invoke_agent guardrails",
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "app.guardrails.result.is_valid": False,
                    "app.guardrails.result.feedback": "Do not invent URLs.",
                },
                seconds=2,
            ),
            _span(
                span_id="url-guardrails-1",
                name="url_guardrails",
                attributes={
                    "app.guardrails.url.is_valid": False,
                    "app.guardrails.url.blog_urls": '["https://demo-university.example.edu/blog/nope"]',
                    "app.guardrails.url.unknown_urls": '["https://demo-university.example.edu/made-up"]',
                },
                seconds=3,
            ),
            _chatbot_span("chatbot-2", "Use another bad page.", seconds=4),
            _span(
                span_id="llm-guardrails-2",
                name="invoke_agent guardrails",
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "app.guardrails.result.is_valid": True,
                },
                seconds=5,
            ),
            _span(
                span_id="url-guardrails-2",
                name="url_guardrails",
                attributes={
                    "app.guardrails.url.is_valid": False,
                    "app.guardrails.url.blog_urls": "[]",
                    "app.guardrails.url.unknown_urls": '["https://demo-university.example.edu/other-made-up"]',
                },
                seconds=6,
            ),
            _chatbot_span("chatbot-3", "Use the approved page.", seconds=7),
            _span(
                span_id="llm-guardrails-3",
                name="invoke_agent guardrails",
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "app.guardrails.result.is_valid": True,
                },
                seconds=8,
            ),
            _span(
                span_id="url-guardrails-3",
                name="url_guardrails",
                attributes={
                    "app.guardrails.url.is_valid": True,
                    "app.guardrails.url.blog_urls": "[]",
                    "app.guardrails.url.unknown_urls": "[]",
                },
                seconds=9,
            ),
        ]
    )

    assert [failure.model_dump(exclude_none=True) for failure in failures or []] == [
        {
            "assistant_message": "Use the made-up page.",
            "llm_guardrails_feedback": "Do not invent URLs.",
            "invalid_urls": [
                "https://demo-university.example.edu/blog/nope",
                "https://demo-university.example.edu/made-up",
            ],
        },
        {
            "assistant_message": "Use another bad page.",
            "invalid_urls": ["https://demo-university.example.edu/other-made-up"],
        },
    ]


def test_guardrails_failures_from_spans_accepts_legacy_chatbot_merged_spans() -> None:
    failures = guardrails_failures_from_spans(
        [
            _chatbot_span(
                "chatbot-merged-1", "Legacy blocked answer.", seconds=1, agent_name="chatbot_merged"
            ),
            _span(
                span_id="llm-guardrails-1",
                name="invoke_agent guardrails",
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "app.guardrails.result.is_valid": "false",
                    "app.guardrails.result.feedback": "Historical response still failed.",
                },
                seconds=2,
            ),
            _span(
                span_id="url-guardrails-1",
                name="url_guardrails",
                attributes={
                    "app.guardrails.url.is_valid": False,
                    "app.guardrails.url.blog_urls": "[]",
                    "app.guardrails.url.unknown_urls": '["https://catalog.demo-university.example.edu/.\\u201d"]',
                },
                seconds=3,
            ),
        ]
    )

    assert [failure.model_dump(exclude_none=True) for failure in failures or []] == [
        {
            "assistant_message": "Legacy blocked answer.",
            "llm_guardrails_feedback": "Historical response still failed.",
            "invalid_urls": ["https://catalog.demo-university.example.edu/.\u201d"],
        }
    ]


def test_guardrails_failures_from_spans_keeps_llm_failure_without_feedback() -> None:
    failures = guardrails_failures_from_spans(
        [
            _chatbot_span("chatbot-1", "Unsupported answer.", seconds=1),
            _span(
                span_id="llm-guardrails-1",
                name="invoke_agent guardrails",
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "app.guardrails.result.is_valid": "false",
                },
                seconds=2,
            ),
        ]
    )

    assert [failure.model_dump(exclude_none=True) for failure in failures or []] == [
        {"assistant_message": "Unsupported answer."}
    ]


def test_guardrails_failures_from_spans_fails_on_malformed_json() -> None:
    with pytest.raises(ValueError, match=r"gen_ai\.output\.messages"):
        guardrails_failures_from_spans(
            [
                _span(
                    span_id="chatbot-1",
                    name="invoke_agent chatbot",
                    attributes={
                        "gen_ai.agent.name": "chatbot",
                        "gen_ai.output.messages": "not-json",
                    },
                    seconds=1,
                )
            ]
        )


def test_guardrails_failures_from_spans_fails_on_malformed_url_json() -> None:
    with pytest.raises(ValueError, match=r"app\.guardrails\.url\.unknown_urls"):
        guardrails_failures_from_spans(
            [
                _chatbot_span("chatbot-1", "Use a bad URL.", seconds=1),
                _span(
                    span_id="url-guardrails-1",
                    name="url_guardrails",
                    attributes={
                        "app.guardrails.url.is_valid": False,
                        "app.guardrails.url.blog_urls": "[]",
                        "app.guardrails.url.unknown_urls": "not-json",
                    },
                    seconds=2,
                ),
            ]
        )
