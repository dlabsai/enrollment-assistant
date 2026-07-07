"""Runner for evaluations with repeat support."""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import INVALID_SPAN_ID, INVALID_TRACE_ID, get_current_span
from opentelemetry.trace.span import format_span_id, format_trace_id

from app import telemetry

from .dataset import Case, Dataset
from .evaluator import EvaluationReason, Evaluator, EvaluatorContext, EvaluatorOutput
from .report import EvaluationReport, EvaluationResult, ModelConfig, ReportCase, RunResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.evals.runtime import EvalProgressHandler


def _exception_details(error: BaseException) -> str:
    """Return useful persisted details for eval task/evaluator failures."""
    details = "".join(traceback.format_exception(error)).strip()
    return details or f"{type(error).__name__}: {error}"


def _exception_summary(error: BaseException) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _current_otel_ids() -> tuple[str | None, str | None]:
    """Return the active OTel trace/span ids for the current eval run context."""
    span_context = get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None

    trace_id = None
    if span_context.trace_id != INVALID_TRACE_ID:
        trace_id = format_trace_id(span_context.trace_id)

    span_id = None
    if span_context.span_id != INVALID_SPAN_ID:
        span_id = format_span_id(span_context.span_id)
    return trace_id, span_id


def _evaluation_score_attributes(result: EvaluationResult) -> dict[str, str | float]:
    """Map an eval result to OTel GenAI evaluation score attributes."""
    if isinstance(result.value, bool):
        return {
            "gen_ai.evaluation.score.label": "pass" if result.value else "fail",
            "gen_ai.evaluation.score.value": 1.0 if result.value else 0.0,
        }
    if isinstance(result.value, int | float):
        return {"gen_ai.evaluation.score.value": float(result.value)}
    return {"gen_ai.evaluation.score.label": result.value}


def _record_evaluation_result_span(
    *,
    case_name: str,
    run_index: int,
    evaluator_name: str,
    result_kind: str,
    result: EvaluationResult,
) -> None:
    """Record one evaluator result using OTel GenAI evaluation semantics."""
    with telemetry.span("gen_ai.evaluation.result") as span:
        span.set_attribute("gen_ai.evaluation.name", result.name)
        for key, value in _evaluation_score_attributes(result).items():
            span.set_attribute(key, value)
        if result.reason is not None:
            span.set_attribute("gen_ai.evaluation.explanation", result.reason)
        span.set_attribute("app.eval.case_name", case_name)
        span.set_attribute("app.eval.run_index", run_index)
        span.set_attribute("app.eval.evaluator.name", evaluator_name)
        span.set_attribute("app.eval.result.kind", result_kind)


def _record_evaluation_result_spans(
    *,
    case_name: str,
    run_index: int,
    evaluator_name: str,
    assertions: dict[str, EvaluationResult],
    scores: dict[str, EvaluationResult],
    labels: dict[str, EvaluationResult],
) -> None:
    for result in assertions.values():
        _record_evaluation_result_span(
            case_name=case_name,
            run_index=run_index,
            evaluator_name=evaluator_name,
            result_kind="assertion",
            result=result,
        )
    for result in scores.values():
        _record_evaluation_result_span(
            case_name=case_name,
            run_index=run_index,
            evaluator_name=evaluator_name,
            result_kind="score",
            result=result,
        )
    for result in labels.values():
        _record_evaluation_result_span(
            case_name=case_name,
            run_index=run_index,
            evaluator_name=evaluator_name,
            result_kind="label",
            result=result,
        )


def _process_evaluator_output(
    evaluator_name: str, output: EvaluatorOutput
) -> tuple[dict[str, EvaluationResult], dict[str, EvaluationResult], dict[str, EvaluationResult]]:
    """Process evaluator output into assertions, scores, and labels."""
    assertions: dict[str, EvaluationResult] = {}
    scores: dict[str, EvaluationResult] = {}
    labels: dict[str, EvaluationResult] = {}

    def process_single(
        name: str,
        value: bool | float | str | EvaluationReason,  # noqa: FBT001
    ) -> None:
        if isinstance(value, EvaluationReason):
            actual_value = value.value
            reason = value.reason
        else:
            actual_value = value
            reason = None

        result = EvaluationResult(name=name, value=actual_value, reason=reason)

        if isinstance(actual_value, bool):
            assertions[name] = result
        elif isinstance(actual_value, (int, float)):
            scores[name] = result
        elif isinstance(actual_value, str):
            labels[name] = result

    if isinstance(output, dict):
        for key, val in output.items():
            process_single(key, val)
    else:
        process_single(evaluator_name, output)

    return assertions, scores, labels


async def _run_single[InputsT, OutputT, MetadataT](
    case: Case[InputsT, OutputT, MetadataT],
    task: Callable[[InputsT], Awaitable[OutputT]],
    evaluators: list[Evaluator[InputsT, OutputT, MetadataT]],
    semaphore: asyncio.Semaphore,
    run_index: int = 0,
    progress_handler: EvalProgressHandler | None = None,
) -> RunResult[OutputT]:
    """Run a single case."""
    async with semaphore:
        if progress_handler is not None:
            await progress_handler(
                {"type": "case_start", "case_name": case.name, "run_index": run_index}
            )

        with telemetry.span(
            "eval_run {case_name} #{run_index}", case_name=case.name, run_index=run_index
        ) as span:
            span.set_attribute("app.eval.case_name", case.name)
            span.set_attribute("app.eval.run_index", run_index)
            otel_trace_id, otel_span_id = _current_otel_ids()

            start_time = time.perf_counter()
            try:
                output = await task(case.inputs)
                duration = time.perf_counter() - start_time
            except Exception as e:
                duration = time.perf_counter() - start_time
                error_summary = _exception_summary(e)
                error_details = _exception_details(e)
                telemetry.error("Task error: {error}", error=error_summary, case_name=case.name)
                if progress_handler is not None:
                    await progress_handler(
                        {
                            "type": "case_complete",
                            "case_name": case.name,
                            "run_index": run_index,
                            "duration": duration,
                            "passed": False,
                            "error": error_summary,
                            "otel_trace_id": otel_trace_id,
                            "otel_span_id": otel_span_id,
                        }
                    )
                return RunResult(
                    output=None,
                    duration=duration,
                    error=error_details,
                    otel_trace_id=otel_trace_id,
                    otel_span_id=otel_span_id,
                )

            ctx = EvaluatorContext(
                inputs=case.inputs,
                output=output,
                expected_output=case.expected_output,
                metadata=case.metadata,
                duration=duration,
            )

            all_assertions: dict[str, EvaluationResult] = {}
            all_scores: dict[str, EvaluationResult] = {}
            all_labels: dict[str, EvaluationResult] = {}

            for evaluator in evaluators:
                try:
                    eval_output = await evaluator.evaluate(ctx)
                    assertions, scores, labels = _process_evaluator_output(
                        evaluator.name, eval_output
                    )
                    _record_evaluation_result_spans(
                        case_name=case.name,
                        run_index=run_index,
                        evaluator_name=evaluator.name,
                        assertions=assertions,
                        scores=scores,
                        labels=labels,
                    )
                    all_assertions.update(assertions)
                    all_scores.update(scores)
                    all_labels.update(labels)
                except Exception as e:
                    error_summary = _exception_summary(e)
                    error_details = _exception_details(e)
                    telemetry.error(
                        "Evaluator error: {error}", error=error_summary, evaluator=evaluator.name
                    )
                    error_result = EvaluationResult(
                        name=f"{evaluator.name}_error", value=False, reason=error_details
                    )
                    _record_evaluation_result_span(
                        case_name=case.name,
                        run_index=run_index,
                        evaluator_name=evaluator.name,
                        result_kind="assertion",
                        result=error_result,
                    )
                    all_assertions[error_result.name] = error_result

            passed = all(a.value for a in all_assertions.values()) if all_assertions else True
            telemetry.info(
                "Run complete: {status}",
                status="PASSED" if passed else "FAILED",
                case_name=case.name,
                run_index=run_index,
                duration=duration,
                assertions={k: v.value for k, v in all_assertions.items()},
                otel_trace_id=otel_trace_id,
                otel_span_id=otel_span_id,
            )

            run_result = RunResult(
                output=output,
                duration=duration,
                assertions=all_assertions,
                scores=all_scores,
                labels=all_labels,
                otel_trace_id=otel_trace_id,
                otel_span_id=otel_span_id,
            )
            if progress_handler is not None:
                await progress_handler(
                    {
                        "type": "case_complete",
                        "case_name": case.name,
                        "run_index": run_index,
                        "duration": duration,
                        "passed": passed,
                        "assertions": {key: value.value for key, value in all_assertions.items()},
                        "otel_trace_id": otel_trace_id,
                        "otel_span_id": otel_span_id,
                    }
                )
            return run_result


async def evaluate[InputsT, OutputT, MetadataT](
    dataset: Dataset[InputsT, OutputT, MetadataT],
    task: Callable[[InputsT], Awaitable[OutputT]],
    evaluators: list[Evaluator[InputsT, OutputT, MetadataT]],
    *,
    repeats: int = 1,
    max_concurrency: int = 10,
    models: dict[str, str] | None = None,
    model_configs: dict[str, ModelConfig] | None = None,
    additional_settings: dict[str, Any] | None = None,
    progress_handler: EvalProgressHandler | None = None,
) -> EvaluationReport[InputsT, OutputT, MetadataT]:
    """Run evaluation on a dataset with repeat and parallel execution support.

    All (cases x repeats) are run in parallel, limited by max_concurrency.

    Args:
        dataset: The dataset containing test cases.
        task: Async function that takes inputs and returns output.
        evaluators: List of evaluators to run on each result.
        repeats: Number of times to run each case (default: 1).
        max_concurrency: Maximum concurrent executions (default: 10).
            Set to 1 for sequential execution.
        models: Dictionary of model roles to model names used in evaluation (deprecated).
        model_configs: Dictionary of model roles to full model configurations.
        additional_settings: Dictionary of additional settings to display in the report.
        progress_handler: Optional async callback for live case progress events.

    Returns:
        EvaluationReport with results and statistics.

    """
    total_runs = len(dataset.cases) * repeats

    with telemetry.span(
        "Evaluation: {dataset_name}",
        dataset_name=dataset.name,
        total_cases=len(dataset.cases),
        repeats=repeats,
        total_runs=total_runs,
        max_concurrency=max_concurrency,
    ):
        semaphore = asyncio.Semaphore(max_concurrency)

        # Create all tasks: each case x repeats
        tasks: list[tuple[Case[InputsT, OutputT, MetadataT], asyncio.Task[RunResult[OutputT]]]] = []
        for case in dataset.cases:
            for run_idx in range(repeats):
                coro = _run_single(case, task, evaluators, semaphore, run_idx + 1, progress_handler)
                tasks.append((case, asyncio.create_task(coro)))

        # Wait for all tasks
        await asyncio.gather(*[t for _, t in tasks])

        # Group results by case
        results_by_case: dict[str, list[RunResult[OutputT]]] = {}
        for case, task_obj in tasks:
            results_by_case.setdefault(case.name, []).append(task_obj.result())

        # Build report
        report_cases: list[ReportCase[InputsT, OutputT, MetadataT]] = []
        for case in dataset.cases:
            run_results = results_by_case.get(case.name, [])
            report_case = ReportCase(
                name=case.name,
                inputs=case.inputs,
                expected_output=case.expected_output,
                metadata=case.metadata,
                run_results=run_results,
            )
            report_case.compute_stats()
            report_cases.append(report_case)

        report = EvaluationReport(
            name=dataset.name,
            cases=report_cases,
            repeats=repeats,
            max_concurrency=max_concurrency,
            models=models or {},
            model_configs=model_configs or {},
            additional_settings=additional_settings or {},
        )

        # Log summary
        passed_cases = sum(
            1
            for c in report.cases
            if c.stats and all(rate == 1.0 for rate in c.stats.assertion_pass_rates.values())
        )
        telemetry.info(
            "Evaluation complete: {passed}/{total} cases passed",
            passed=passed_cases,
            total=len(report.cases),
            dataset_name=dataset.name,
        )

        return report
