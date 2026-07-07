"""Pytest wrapper for the guardrails eval suite."""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.evals.guardrails import assert_report_meets_threshold, run_guardrails_evaluation
from app.evals.rag_data import create_session_factory
from app.evals.runtime import EvalRunConfig, EvalSuite, parse_test_cases_filter
from app.evals.storage import eval_run_config_payload, save_eval_report, threshold_failed_case_names

pytestmark = [pytest.mark.slow, pytest.mark.llm]


@pytest.mark.asyncio
@pytest.mark.eval
async def test_guardrails_evaluation(db_engine: object, request: pytest.FixtureRequest) -> None:
    """Run all guardrails eval cases with optional repeats."""
    if not isinstance(db_engine, AsyncEngine):
        raise TypeError("db_engine fixture must provide an AsyncEngine")
    config = EvalRunConfig(
        session_factory=create_session_factory(db_engine),
        suite=EvalSuite.GUARDRAILS,
        repeat=cast(int, request.config.getoption("--repeat")),
        max_concurrency=cast(int, request.config.getoption("--max-concurrency")),
        test_cases=parse_test_cases_filter(request.config.getoption("--test-cases")),
        pass_threshold=cast(float, request.config.getoption("--pass-threshold")),
        guardrail_model=request.config.getoption("--guardrail-model"),
        evaluation_model=request.config.getoption("--evaluation-model"),
    )
    report = await run_guardrails_evaluation(config)
    report.print_summary()
    failed = threshold_failed_case_names(report, config.pass_threshold)
    await save_eval_report(
        config.session_factory,
        report,
        suite=config.suite.value,
        pass_threshold=config.pass_threshold,
        status="threshold_failed" if failed else "complete",
        log_id=None,
        config=eval_run_config_payload(config),
    )
    assert_report_meets_threshold(report, config.pass_threshold)
