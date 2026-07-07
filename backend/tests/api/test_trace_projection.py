from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.api.trace_projection import build_trace_overview
from app.models import OtelSpan


def _span(
    *,
    span_id: str,
    name: str,
    attributes: dict[str, Any],
    parent_span_id: str | None = None,
    request_model: str | None = None,
    is_ai: bool = False,
    is_embedding: bool | None = False,
    duration_ms: float = 123.0,
) -> OtelSpan:
    started_at = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
    return cast(
        OtelSpan,
        SimpleNamespace(
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind="INTERNAL",
            status_code="OK",
            start_time=started_at,
            span_time=started_at,
            created_at=started_at,
            duration_ms=duration_ms,
            attributes=attributes,
            request_model=request_model,
            provider_name=None,
            server_address=None,
            input_tokens=None,
            output_tokens=None,
            total_cost=None,
            is_ai=is_ai,
            is_embedding=is_embedding,
            total_time=None,
        ),
    )


def test_trace_projection_projects_tool_arguments_and_result() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="tool-1",
                parent_span_id="agent-1",
                name="execute_tool find_document_chunks",
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "find_document_chunks",
                    "gen_ai.tool.type": "datastore",
                    "gen_ai.tool.call.id": "call-1",
                    "gen_ai.tool.call.arguments": '{"content_search_query":"tuition"}',
                    "gen_ai.tool.call.result": '[{"type":"website_page","id":1,"title":"Tuition"}]',
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "tool"
    assert item.title == "Tool: find_document_chunks"
    assert item.parent_span_id == "agent-1"
    assert item.data == {
        "tool_name": "find_document_chunks",
        "tool_type": "datastore",
        "call_id": "call-1",
        "arguments": {"content_search_query": "tuition"},
        "result": [{"type": "website_page", "id": 1, "title": "Tuition"}],
    }


def test_trace_projection_projects_find_document_chunks_trace_only_dedupe() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="tool-1",
                name="execute_tool find_document_chunks",
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "find_document_chunks",
                    "gen_ai.tool.call.result": "[]",
                    "app.document_tool.find_document_chunks.schema": "find_document_chunks.v2",
                    "app.document_tool.find_document_chunks.dedupe": (
                        '{"effective_limit":50,"candidate_count":150,"unique_candidates":139,'
                        '"unique_results":50,"candidate_collapsed_occurrences":11,'
                        '"returned_collapsed_occurrences":2,'
                        '"omitted_candidate_collapsed_occurrences":9}'
                    ),
                },
            )
        ]
    )

    assert "result_schema" not in overview[0].data
    assert overview[0].data["dedupe"] == {
        "effective_limit": 50,
        "candidate_count": 150,
        "unique_candidates": 139,
        "unique_results": 50,
        "candidate_collapsed_occurrences": 11,
        "returned_collapsed_occurrences": 2,
        "omitted_candidate_collapsed_occurrences": 9,
    }
    assert overview[0].data["result"] == []


def test_trace_projection_hides_tool_child_retrieval_and_projects_embedding_summary() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="tool-1",
                parent_span_id="agent-1",
                name="execute_tool find_document_chunks",
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "find_document_chunks",
                    "gen_ai.tool.type": "datastore",
                    "gen_ai.tool.call.arguments": '{"content_search_query":"financial aid"}',
                    "gen_ai.tool.call.result": '[{"type":"website_page","id":1,"title":"Tuition"}]',
                },
                duration_ms=500.0,
            ),
            _span(
                span_id="retrieval-1",
                parent_span_id="tool-1",
                name="retrieval demo-rag",
                attributes={
                    "gen_ai.operation.name": "retrieval",
                    "gen_ai.data_source.id": "demo-rag",
                    "gen_ai.retrieval.query.text": "financial aid",
                    "gen_ai.request.top_k": 50,
                    "gen_ai.retrieval.documents": '[{"id":"website_page:1:chunk:2","score":0.92}]',
                },
                duration_ms=240.0,
            ),
            _span(
                span_id="embedding-1",
                parent_span_id="retrieval-1",
                name="embeddings text-embedding-3-large",
                attributes={
                    "gen_ai.operation.name": "embeddings",
                    "gen_ai.provider.name": "azure.ai.openai",
                    "gen_ai.request.model": "text-embedding-3-large",
                    "gen_ai.response.model": "text-embedding-3-large",
                    "gen_ai.usage.input_tokens": 6,
                },
                is_embedding=True,
                duration_ms=180.0,
            ),
        ]
    )

    assert [item.span_id for item in overview] == ["tool-1"]
    item = overview[0]
    assert item.type == "tool"
    assert item.data["embedding_model"] == "text-embedding-3-large"
    assert item.data["embedding_duration_ms"] == 180.0
    assert item.data["embedding_input_tokens"] == 6
    assert "retrievals" not in item.data
    assert "embeddings" not in item.data
    assert item.data["result"] == [{"type": "website_page", "id": 1, "title": "Tuition"}]


def test_trace_projection_projects_orphan_retrieval_documents() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="retrieval-1",
                name="retrieval demo-rag",
                attributes={
                    "gen_ai.operation.name": "retrieval",
                    "gen_ai.data_source.id": "demo-rag",
                    "gen_ai.retrieval.query.text": "financial aid",
                    "gen_ai.request.top_k": 50,
                    "gen_ai.retrieval.documents": '[{"id":"website_page:1:chunk:2","score":0.92}]',
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "retrieval"
    assert item.title == "Retrieval: demo-rag"
    assert item.subtitle == "financial aid"
    assert item.data == {
        "data_source_id": "demo-rag",
        "query": "financial aid",
        "top_k": 50,
        "documents": [{"id": "website_page:1:chunk:2", "score": 0.92}],
    }


def test_trace_projection_projects_non_empty_url_guardrails_arrays() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="guardrails-1",
                name="url_guardrails",
                attributes={
                    "app.guardrails.url.blog_urls": '["https://demo-university.example.edu/blog/nope"]',
                    "app.guardrails.url.unknown_urls": '["https://example.edu/nope"]',
                    "app.guardrails.url.is_valid": "false",
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "url_guardrails"
    assert item.title == "URL Guardrails"
    assert item.subtitle == "Blocked"
    assert item.data == {
        "is_valid": False,
        "blog_urls": ["https://demo-university.example.edu/blog/nope"],
        "unknown_urls": ["https://example.edu/nope"],
    }


def test_trace_projection_omits_empty_url_guardrails_arrays() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="guardrails-1",
                name="url_guardrails",
                attributes={
                    "app.guardrails.url.blog_urls": "[]",
                    "app.guardrails.url.unknown_urls": "[]",
                    "app.guardrails.url.is_valid": "true",
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "url_guardrails"
    assert item.data == {"is_valid": True}


def test_trace_projection_projects_agent_output_messages() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="chatbot",
                name="invoke_agent chatbot",
                is_ai=True,
                attributes={
                    "gen_ai.agent.name": "chatbot",
                    "gen_ai.request.model": "azure/gpt-5.5",
                    "gen_ai.output.messages": (
                        '[{"role":"assistant","content":'
                        '"Tell them Demo University is accredited."}]'
                    ),
                    "gen_ai.system_instructions": "Use approved Demo University facts.",
                    "app.llm_response_metrics": '[{"request_index":1,"output_tokens":9}]',
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "agent"
    assert item.title == "Agent: chatbot"
    assert item.subtitle == "azure/gpt-5.5"
    assert item.data["model"] == "azure/gpt-5.5"
    assert item.data["output_text"] == "Tell them Demo University is accredited."
    assert item.data["system_instructions"] == "Use approved Demo University facts."
    assert item.data["output_messages"] == [
        {"role": "assistant", "content": "Tell them Demo University is accredited."}
    ]
    assert item.data["llm_response_metrics"] == [{"request_index": 1, "output_tokens": 9}]


def test_trace_projection_projects_grounding_agent_output_messages() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="grounding",
                name="invoke_agent grounding",
                is_ai=True,
                attributes={
                    "gen_ai.agent.name": "grounding",
                    "gen_ai.request.model": "azure/gpt-5.5",
                    "gen_ai.output.messages": (
                        '[{"role":"assistant","content":"{\\"grounding_source_keys\\":[\\"tool-1:website_page:42:search:0\\"]}"}]'
                    ),
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "agent"
    assert item.title == "Agent: grounding"
    assert item.data["output_text"] == (
        '{"grounding_source_keys":["tool-1:website_page:42:search:0"]}'
    )


def test_trace_projection_projects_agent_cache_read_tokens() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="chatbot",
                name="invoke_agent chatbot",
                is_ai=True,
                attributes={
                    "gen_ai.agent.name": "chatbot",
                    "gen_ai.request.model": "azure/gpt-5.5",
                    "gen_ai.usage.input_tokens": 100,
                    "gen_ai.usage.cache_read.input_tokens": 40,
                    "gen_ai.usage.output_tokens": 20,
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "agent"
    assert item.data["input_tokens"] == 100
    assert item.data["uncached_input_tokens"] == 60
    assert item.data["cache_read_input_tokens"] == 40
    assert item.data["output_tokens"] == 20


def test_trace_projection_projects_reasoning_effort_for_agents_and_llms() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="agent",
                name="invoke_agent investigation",
                is_ai=True,
                attributes={
                    "gen_ai.agent.name": "investigation",
                    "gen_ai.request.model": "azure/gpt-5.5",
                    "app.reasoning_effort": "xhigh",
                },
            ),
            _span(
                span_id="llm",
                name="chat azure/gpt-5.5",
                is_ai=True,
                attributes={
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": "azure/gpt-5.5",
                    "app.reasoning_effort": "high",
                },
            ),
        ]
    )

    assert overview[0].type == "agent"
    assert overview[0].data["reasoning_effort"] == "xhigh"
    assert overview[1].type == "llm"
    assert overview[1].data["reasoning_effort"] == "high"


def test_trace_projection_projects_guardrails_result() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="guardrails",
                name="invoke_agent guardrails",
                is_ai=True,
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "gen_ai.request.model": "azure/gpt-5.5",
                    "app.guardrails.result.is_valid": False,
                    "app.guardrails.result.feedback": "Use allowed URLs only.",
                },
            )
        ]
    )

    item = overview[0]
    assert item.type == "agent"
    assert item.title == "Agent: guardrails"
    assert item.subtitle == "azure/gpt-5.5"
    assert item.data["model"] == "azure/gpt-5.5"
    assert item.data["guardrails_is_valid"] is False
    assert item.data["guardrails_feedback"] == "Use allowed URLs only."


def test_trace_projection_projects_conversation_turn_from_handle_span_attributes() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="turn-root",
                parent_span_id="eval-run",
                name="Calling app.chat.engine.handle_conversation_turn",
                attributes={
                    "app.conversation_id": "conversation-id",
                    "app.message_id": "message-id",
                    "app.conversation_turn": 2,
                    "gen_ai.input.messages": (
                        '[{"role":"user","content":"What programs are online?"}]'
                    ),
                    "app.guardrails_blocked": False,
                    "app.guardrail_retries": 2,
                    "app.total_time": 12.5,
                    "app.guardrail_time": 1.0,
                    "app.chatbot_times": [3.1, 4.2],
                },
            ),
            _span(
                span_id="guardrails-invalid-1",
                parent_span_id="turn-root",
                name="invoke_agent guardrails",
                attributes={"app.guardrails.result.is_valid": False},
            ),
            _span(
                span_id="guardrails-invalid-2",
                parent_span_id="turn-root",
                name="invoke_agent guardrails",
                attributes={"app.guardrails.result.is_valid": False},
            ),
            _span(
                span_id="guardrails-valid",
                parent_span_id="turn-root",
                name="invoke_agent guardrails",
                attributes={"app.guardrails.result.is_valid": True},
            ),
        ]
    )

    item = next(item for item in overview if item.span_id == "turn-root")
    assert item.type == "conversation_turn"
    assert item.title == "Conversation Turn"
    assert item.data == {
        "conversation_id": "conversation-id",
        "message_id": "message-id",
        "conversation_turn": 2,
        "input_messages": [{"role": "user", "content": "What programs are online?"}],
        "input_text": "What programs are online?",
        "guardrails_blocked": False,
        "guardrail_failures": 2,
        "guardrail_retries": 2,
        "total_time": 12.5,
        "guardrail_time": 1.0,
        "chatbot_times": [3.1, 4.2],
    }


def test_trace_projection_projects_eval_trace_rows() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="eval-root",
                name="Evaluation: guardrails_eval",
                attributes={
                    "dataset_name": "guardrails_eval",
                    "total_cases": 2,
                    "repeats": 1,
                    "total_runs": 2,
                    "max_concurrency": 1,
                },
            ),
            _span(
                span_id="case-run",
                parent_span_id="eval-root",
                name="eval_run internal_valid_accreditation_response #1",
                attributes={
                    "app.eval.case_name": "internal_valid_accreditation_response",
                    "app.eval.run_index": 1,
                },
            ),
            _span(
                span_id="eval-result",
                parent_span_id="case-run",
                name="gen_ai.evaluation.result",
                attributes={
                    "gen_ai.evaluation.name": "passed",
                    "gen_ai.evaluation.score.label": "fail",
                    "gen_ai.evaluation.score.value": 0.0,
                    "gen_ai.evaluation.explanation": "Response was not grounded.",
                    "app.eval.case_name": "internal_valid_accreditation_response",
                    "app.eval.run_index": 1,
                    "app.eval.evaluator.name": "GuardrailsJudge",
                    "app.eval.result.kind": "assertion",
                },
            ),
        ]
    )

    assert [item.type for item in overview] == [
        "evaluation",
        "evaluation_case",
        "evaluation_result",
    ]

    root_item = overview[0]
    assert root_item.title == "Evaluation: guardrails_eval"
    assert root_item.data == {
        "dataset_name": "guardrails_eval",
        "total_cases": 2,
        "repeats": 1,
        "total_runs": 2,
        "max_concurrency": 1,
    }

    case_item = overview[1]
    assert case_item.title == "Case Run: internal_valid_accreditation_response #1"
    assert case_item.data == {"case_name": "internal_valid_accreditation_response", "run_index": 1}

    result_item = overview[2]
    assert result_item.title == "Evaluation Result: passed"
    assert result_item.subtitle == "fail"
    assert result_item.data == {
        "evaluation_name": "passed",
        "score_label": "fail",
        "score_value": 0.0,
        "explanation": "Response was not grounded.",
        "evaluator_name": "GuardrailsJudge",
        "result_kind": "assertion",
        "case_name": "internal_valid_accreditation_response",
        "run_index": 1,
    }


def test_trace_projection_preserves_plain_text_tool_results() -> None:
    overview = build_trace_overview(
        [
            _span(
                span_id="tool-1",
                name="execute_tool find_document_titles",
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "find_document_titles",
                    "gen_ai.tool.call.result": (
                        "| id | type | title |\n|---:|---|---|\n| 22 | website_program | MBA |"
                    ),
                },
            )
        ]
    )

    assert overview[0].data["result"] == (
        "| id | type | title |\n|---:|---|---|\n| 22 | website_program | MBA |"
    )


def test_trace_projection_fails_loudly_on_invalid_canonical_json() -> None:
    with pytest.raises(ValueError, match=r"gen_ai\.tool\.call\.arguments"):
        build_trace_overview(
            [
                _span(
                    span_id="tool-1",
                    name="execute_tool retrieve_documents",
                    attributes={
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": "retrieve_documents",
                        "gen_ai.tool.call.arguments": "not-json",
                    },
                )
            ]
        )
