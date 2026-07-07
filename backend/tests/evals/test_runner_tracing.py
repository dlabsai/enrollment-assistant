from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from app.evals.dataset import Dataset
from app.evals.evaluator import EvaluationReason, Evaluator, EvaluatorContext, EvaluatorOutput
from app.evals.runner import evaluate

if TYPE_CHECKING:
    from collections.abc import Generator


class FakeSpan:
    def __init__(self, name: str, attributes: dict[str, object] | None = None) -> None:
        self.name = name
        self.attributes: dict[str, object] = dict(attributes or {})

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class SpanRecorder:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    @contextmanager
    def span(self, name: str, **attributes: object) -> Generator[FakeSpan]:
        span = FakeSpan(name, attributes)
        self.spans.append(span)
        yield span


class MixedEvaluator(Evaluator[str, str, None]):
    @property
    def name(self) -> str:
        return "mixed_judge"

    async def evaluate(self, ctx: EvaluatorContext[str, str, None]) -> EvaluatorOutput:
        assert ctx.inputs == "hello"
        assert ctx.output == "HELLO"
        return {
            "passed": EvaluationReason(value=False, reason="not grounded enough"),
            "confidence": 0.25,
            "category": "needs_review",
        }


class ErrorEvaluator(Evaluator[str, str, None]):
    @property
    def name(self) -> str:
        return "broken_judge"

    async def evaluate(self, ctx: EvaluatorContext[str, str, None]) -> EvaluatorOutput:
        del ctx
        raise RuntimeError("judge failed")


@pytest.mark.asyncio
async def test_evaluate_records_genai_evaluation_result_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SpanRecorder()
    monkeypatch.setattr("app.evals.runner.telemetry.span", recorder.span)

    dataset: Dataset[str, str, None] = Dataset(name="unit_eval")
    dataset.add_case("case_a", "hello")

    async def task(value: str) -> str:
        return value.upper()

    report = await evaluate(dataset, task, [MixedEvaluator()], repeats=1, max_concurrency=1)

    assert report.cases[0].run_results[0].assertions["passed"].value is False

    result_spans = [span for span in recorder.spans if span.name == "gen_ai.evaluation.result"]
    assert len(result_spans) == 3

    passed_span = next(
        span for span in result_spans if span.attributes["gen_ai.evaluation.name"] == "passed"
    )
    assert passed_span.attributes["gen_ai.evaluation.score.label"] == "fail"
    assert passed_span.attributes["gen_ai.evaluation.score.value"] == 0.0
    assert passed_span.attributes["gen_ai.evaluation.explanation"] == "not grounded enough"
    assert passed_span.attributes["app.eval.case_name"] == "case_a"
    assert passed_span.attributes["app.eval.run_index"] == 1
    assert passed_span.attributes["app.eval.evaluator.name"] == "mixed_judge"
    assert passed_span.attributes["app.eval.result.kind"] == "assertion"

    confidence_span = next(
        span for span in result_spans if span.attributes["gen_ai.evaluation.name"] == "confidence"
    )
    assert confidence_span.attributes["gen_ai.evaluation.score.value"] == 0.25
    assert "gen_ai.evaluation.score.label" not in confidence_span.attributes
    assert confidence_span.attributes["app.eval.result.kind"] == "score"

    label_span = next(
        span for span in result_spans if span.attributes["gen_ai.evaluation.name"] == "category"
    )
    assert label_span.attributes["gen_ai.evaluation.score.label"] == "needs_review"
    assert "gen_ai.evaluation.score.value" not in label_span.attributes
    assert label_span.attributes["app.eval.result.kind"] == "label"


@pytest.mark.asyncio
async def test_evaluate_records_genai_span_for_evaluator_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SpanRecorder()
    monkeypatch.setattr("app.evals.runner.telemetry.span", recorder.span)

    dataset: Dataset[str, str, None] = Dataset(name="unit_eval")
    dataset.add_case("case_a", "hello")

    async def task(value: str) -> str:
        return value.upper()

    report = await evaluate(dataset, task, [ErrorEvaluator()], repeats=1, max_concurrency=1)

    run_result = report.cases[0].run_results[0]
    assert run_result.assertions["broken_judge_error"].value is False
    assert run_result.assertions["broken_judge_error"].reason == "judge failed"

    result_spans = [span for span in recorder.spans if span.name == "gen_ai.evaluation.result"]
    assert len(result_spans) == 1
    error_span = result_spans[0]
    assert error_span.attributes["gen_ai.evaluation.name"] == "broken_judge_error"
    assert error_span.attributes["gen_ai.evaluation.score.label"] == "fail"
    assert error_span.attributes["gen_ai.evaluation.score.value"] == 0.0
    assert error_span.attributes["gen_ai.evaluation.explanation"] == "judge failed"
    assert error_span.attributes["app.eval.evaluator.name"] == "broken_judge"
    assert error_span.attributes["app.eval.result.kind"] == "assertion"
