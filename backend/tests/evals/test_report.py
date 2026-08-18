from __future__ import annotations

from datetime import UTC, datetime

from app.chat.evals.chatbot import ChatbotOutput
from app.evals.report import EvaluationReport
from app.evals.storage import _output_to_json  # pyright: ignore[reportPrivateUsage]


def test_evaluation_report_id_uses_name_and_timestamp() -> None:
    report: EvaluationReport[dict[str, object], dict[str, object], object] = EvaluationReport(
        name="demo_va_chatbot_eval"
    )

    report_id = report.report_id(datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC))

    assert report_id == "eval-demo-va-chatbot-eval-20260427-120000-000000"


def test_structured_chatbot_output_persists_response_and_retry_count() -> None:
    output = ChatbotOutput(
        chatbot_response="Assistant response",
        system_prompt="Rendered internal instructions",
        retrieved_tool_context="Tool context used by the judge",
        guardrail_retries=2,
    )

    assert _output_to_json(output) == {
        "chatbot_response": "Assistant response",
        "guardrail_retries": 2,
    }
