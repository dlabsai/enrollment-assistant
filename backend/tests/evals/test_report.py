from __future__ import annotations

from datetime import UTC, datetime

from app.evals.report import EvaluationReport


def test_evaluation_report_id_is_not_a_markdown_filename() -> None:
    report: EvaluationReport[dict[str, object], dict[str, object], object] = EvaluationReport(
        name="demo_va_chatbot_eval"
    )

    report_id = report.report_id(datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC))

    assert report_id.startswith("eval-demo-va-chatbot-eval-20260427-120000-")
    assert not report_id.endswith(".md")
    assert "." not in report_id
