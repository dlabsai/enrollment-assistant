from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.chat.evals.chatbot import (
    CHATBOT_JUDGE_SYSTEM_PROMPT,
    ChatbotInput,
    ChatbotJudge,
    ChatbotJudgeResult,
    ChatbotOutput,
    format_retrieved_tool_context,
)
from app.evals import EvaluationReason, EvaluatorContext


def test_format_retrieved_tool_context_preserves_tool_results() -> None:
    context = format_retrieved_tool_context(
        [
            {
                "role": "tool",
                "name": "find_document_chunks",
                "content": [
                    {
                        "title": "Tuition & Fees",
                        "url": "https://demo-university.example.edu/tuition",
                    }
                ],
            }
        ]
    )

    assert "find_document_chunks" in context
    assert "Tuition & Fees" in context
    assert "https://demo-university.example.edu/tuition" in context


def _context() -> EvaluatorContext[ChatbotInput, ChatbotOutput, Any]:
    return EvaluatorContext(
        inputs=ChatbotInput(
            user_input="What tuition page should I use?",
            criteria="Use grounded tuition information.",
            test_case_id="tuition",
        ),
        output=ChatbotOutput(
            chatbot_response="Use https://demo-university.example.edu/financial-aid/tuition-fees/.",
            system_prompt="Rules only; no precomputed helper response.",
            retrieved_tool_context="retrieve_documents returned Tuition & Fees page.",
        ),
        expected_output=None,
        metadata=None,
        duration=1.0,
    )


async def _evaluate_with_captured_prompt(
    monkeypatch: pytest.MonkeyPatch, judge: ChatbotJudge
) -> tuple[dict[str, Any], dict[str, Any]]:
    captured: dict[str, Any] = {}

    async def fake_run_agent(**kwargs: Any) -> tuple[Any, float]:
        captured["agent"] = kwargs["agent"]
        captured["prompt"] = kwargs["prompt"]
        return (
            SimpleNamespace(
                output=ChatbotJudgeResult(
                    reasoning="grounded in context",
                    follows_guidelines=True,
                    is_grounded=True,
                    passed=True,
                )
            ),
            0.0,
        )

    monkeypatch.setattr("app.chat.evals.chatbot.run_agent", fake_run_agent)
    result = await judge.evaluate(_context())
    return captured, result


@pytest.mark.asyncio
async def test_chatbot_judge_receives_retrieved_tool_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = ChatbotJudge(model="test")

    captured, result = await _evaluate_with_captured_prompt(monkeypatch, judge)

    assert "<retrieved_tool_context>" in captured["prompt"]
    assert "retrieve_documents returned Tuition & Fees page" in captured["prompt"]
    assert "<retrieved_tool_context>" in CHATBOT_JUDGE_SYSTEM_PROMPT
    assert "<search-results> section" not in CHATBOT_JUDGE_SYSTEM_PROMPT
    assert result["passed"] == EvaluationReason(value=True, reason="grounded in context")
    assert result["is_grounded"] is True
