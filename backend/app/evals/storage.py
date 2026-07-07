"""Structured eval result persistence in the guarded eval/test database."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import Float, String, asc, desc, func, or_, select
from sqlalchemy import case as sa_case
from sqlalchemy import cast as sa_cast
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.evals.rag_data import create_session_factory
from app.evals.report import EvaluationReport, EvaluationResult
from app.evals.runtime import EvalRunConfig, EvalRunRequestConfig
from app.evals.test_db import create_test_db_engine, load_eval_database_url
from app.models import EvalCaseResult, EvalCaseRunResult, EvalRunRecord
from app.utils import current_time_utc

_EXCLUDED_STORED_OUTPUT_FIELDS = {"retrieved_tool_context"}

EvalReportSortBy = Literal[
    "audience",
    "case_count",
    "concurrency",
    "generated_at",
    "pass_threshold",
    "repeats",
    "run_count",
    "status",
    "suite",
    "title",
]


@dataclass(frozen=True)
class EvalReportSummaryRecord:
    report_id: str
    name: str
    suite: str
    generated_at: datetime
    repeats: int
    max_concurrency: int
    pass_threshold: float
    status: str
    model_configs: dict[str, Any]
    case_count: int
    run_count: int
    is_internal: bool | None
    pass_rate_average: float | None
    duration_median_average: float | None


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Mapping):
        value_mapping = cast(Mapping[Any, Any], value)
        return {str(key): _jsonable(val) for key, val in value_mapping.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        value_sequence = cast(Sequence[Any], value)
        return [_jsonable(item) for item in value_sequence]
    return str(value)


def _result_to_json(result: EvaluationResult) -> dict[str, Any]:
    return {"name": result.name, "value": _jsonable(result.value), "reason": result.reason}


def _output_to_json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
            if field.name not in _EXCLUDED_STORED_OUTPUT_FIELDS
        }
    return _jsonable(value)


def threshold_failed_case_names(
    report: EvaluationReport[Any, Any, Any], pass_threshold: float
) -> list[str]:
    """Return case names whose primary pass assertion is below threshold."""
    return [
        case.name
        for case in report.cases
        if case.stats.assertion_pass_rates.get("passed", 0) < pass_threshold
    ]


def eval_run_config_payload(config: EvalRunConfig | EvalRunRequestConfig) -> dict[str, Any]:
    """Serialize eval run config for structured report storage."""
    return {
        "suite": config.suite.value,
        "repeat": config.repeat,
        "max_concurrency": config.max_concurrency,
        "test_cases": list(config.test_cases),
        "pass_threshold": config.pass_threshold,
        "rebuild_rag": config.rebuild_rag,
        "chatbot_model": config.chatbot_model,
        "guardrail_model": config.guardrail_model,
        "evaluation_model": config.evaluation_model,
    }


async def save_eval_report(
    session_factory: async_sessionmaker[AsyncSession],
    report: EvaluationReport[Any, Any, Any],
    *,
    suite: str,
    pass_threshold: float,
    status: str,
    log_id: str | None,
    config: Mapping[str, Any],
) -> EvalRunRecord:
    """Persist an eval report as structured rows, not rendered markdown."""
    generated_at = current_time_utc()
    report_id = report.report_id(generated_at)
    model_configs = report.model_configs or report.models
    record = EvalRunRecord(
        report_id=report_id,
        suite=suite,
        name=report.name,
        generated_at=generated_at,
        repeats=report.repeats,
        max_concurrency=report.max_concurrency,
        pass_threshold=pass_threshold,
        status=status,
        log_id=log_id,
        config=_jsonable(config),
        model_configs=_jsonable(model_configs),
        additional_settings=_jsonable(report.additional_settings),
    )

    for case_index, case in enumerate(report.cases):
        case_record = EvalCaseResult(
            position=case_index,
            name=case.name,
            inputs=_jsonable(case.inputs),
            expected_output=_jsonable(case.expected_output),
            metadata_json=_jsonable(case.metadata),
            stats=_jsonable(case.stats),
        )
        for run_index, run_result in enumerate(case.run_results, start=1):
            case_record.runs.append(
                EvalCaseRunResult(
                    run_index=run_index,
                    output=_output_to_json(run_result.output),
                    duration=run_result.duration,
                    error=run_result.error,
                    otel_trace_id=run_result.otel_trace_id,
                    otel_span_id=run_result.otel_span_id,
                    assertions={
                        key: _result_to_json(result)
                        for key, result in run_result.assertions.items()
                    },
                    scores={
                        key: _result_to_json(result) for key, result in run_result.scores.items()
                    },
                    labels={
                        key: _result_to_json(result) for key, result in run_result.labels.items()
                    },
                )
            )
        record.cases.append(case_record)

    async with session_factory() as session:
        session.add(record)
        await session.commit()
        stmt = (
            select(EvalRunRecord)
            .where(EvalRunRecord.id == record.id)
            .options(selectinload(EvalRunRecord.cases).selectinload(EvalCaseResult.runs))
        )
        saved_record = await session.scalar(stmt)
        if saved_record is None:
            raise RuntimeError("Saved eval report could not be reloaded")
        return saved_record


def _case_stat_average_expr(key: str) -> Any:
    value_expr = EvalCaseResult.stats[key]
    number_expr = cast(Any, sa_cast(value_expr.as_string(), Float))
    return func.avg(sa_case((func.jsonb_typeof(value_expr) == "number", number_expr), else_=None))


def _report_metric_averages() -> Any:
    return (
        select(
            EvalCaseResult.eval_run_id.label("eval_run_id"),
            _case_stat_average_expr("pass_rate").label("pass_rate_average"),
            _case_stat_average_expr("duration_median").label("duration_median_average"),
        )
        .group_by(EvalCaseResult.eval_run_id)
        .subquery()
    )


def _report_summary_query_parts() -> tuple[Any, Any, Any, Any, Any, Any]:
    is_internal_expr = EvalCaseResult.inputs["is_internal"].as_boolean()
    case_counts = (
        select(
            EvalCaseResult.eval_run_id.label("eval_run_id"),
            func.count(EvalCaseResult.id).label("case_count"),
            func.bool_or(is_internal_expr).label("any_internal"),
            func.bool_and(is_internal_expr).label("all_internal"),
        )
        .group_by(EvalCaseResult.eval_run_id)
        .subquery()
    )
    run_counts = (
        select(
            EvalCaseResult.eval_run_id.label("eval_run_id"),
            func.count(EvalCaseRunResult.id).label("run_count"),
        )
        .join(EvalCaseRunResult, EvalCaseRunResult.case_id == EvalCaseResult.id)
        .group_by(EvalCaseResult.eval_run_id)
        .subquery()
    )
    case_count_expr = func.coalesce(case_counts.c.case_count, 0)
    run_count_expr = func.coalesce(run_counts.c.run_count, 0)
    audience_expr = case_counts.c.any_internal
    audience_all_expr = case_counts.c.all_internal
    is_internal_summary_expr = sa_case(
        (audience_expr.is_(True) & audience_all_expr.is_(True), True),
        (audience_expr.is_(False) & audience_all_expr.is_(False), False),
        else_=None,
    )
    audience_label_expr = sa_case(
        (audience_expr.is_(True) & audience_all_expr.is_(True), "internal va"),
        (audience_expr.is_(False) & audience_all_expr.is_(False), "public va"),
        else_="mixed/unknown",
    )
    return (
        case_counts,
        run_counts,
        case_count_expr,
        run_count_expr,
        is_internal_summary_expr,
        audience_label_expr,
    )


def _report_title_search_expr() -> Any:
    return func.replace(func.replace(EvalRunRecord.name, "_", " "), "-", " ")


def _report_search_condition(
    search: str | None, *, case_count_expr: Any, run_count_expr: Any, audience_label_expr: Any
) -> Any | None:
    search_text = search.strip() if search is not None else ""
    if search_text == "":
        return None

    pattern = f"%{search_text}%"
    return or_(
        EvalRunRecord.report_id.ilike(pattern),
        EvalRunRecord.name.ilike(pattern),
        _report_title_search_expr().ilike(pattern),
        EvalRunRecord.suite.ilike(pattern),
        EvalRunRecord.status.ilike(pattern),
        audience_label_expr.ilike(pattern),
        sa_cast(EvalRunRecord.generated_at, String).ilike(pattern),
        sa_cast(EvalRunRecord.repeats, String).ilike(pattern),
        sa_cast(EvalRunRecord.max_concurrency, String).ilike(pattern),
        sa_cast(EvalRunRecord.pass_threshold, String).ilike(pattern),
        sa_cast(case_count_expr, String).ilike(pattern),
        sa_cast(run_count_expr, String).ilike(pattern),
    )


def _report_sort_expr(
    sort_by: EvalReportSortBy,
    *,
    case_count_expr: Any,
    run_count_expr: Any,
    audience_label_expr: Any,
) -> Any:
    sort_expr_map: dict[EvalReportSortBy, Any] = {
        "audience": audience_label_expr.collate("C"),
        "case_count": case_count_expr,
        "concurrency": EvalRunRecord.max_concurrency,
        "generated_at": EvalRunRecord.generated_at,
        "pass_threshold": EvalRunRecord.pass_threshold,
        "repeats": EvalRunRecord.repeats,
        "run_count": run_count_expr,
        "status": EvalRunRecord.status.collate("C"),
        "suite": EvalRunRecord.suite.collate("C"),
        "title": _report_title_search_expr().collate("C"),
    }
    return sort_expr_map[sort_by]


async def count_eval_reports(session: AsyncSession, *, search: str | None) -> int:
    (
        case_counts,
        run_counts,
        case_count_expr,
        run_count_expr,
        _is_internal_expr,
        audience_label_expr,
    ) = _report_summary_query_parts()
    stmt = (
        select(func.count(EvalRunRecord.id))
        .outerjoin(case_counts, case_counts.c.eval_run_id == EvalRunRecord.id)
        .outerjoin(run_counts, run_counts.c.eval_run_id == EvalRunRecord.id)
    )
    search_condition = _report_search_condition(
        search,
        case_count_expr=case_count_expr,
        run_count_expr=run_count_expr,
        audience_label_expr=audience_label_expr,
    )
    if search_condition is not None:
        stmt = stmt.where(search_condition)
    return int((await session.execute(stmt)).scalar_one())


async def list_eval_report_summaries(
    session: AsyncSession,
    *,
    descending: bool = True,
    limit: int,
    offset: int = 0,
    search: str | None,
    sort_by: EvalReportSortBy = "generated_at",
) -> list[EvalReportSummaryRecord]:
    (
        case_counts,
        run_counts,
        case_count_expr,
        run_count_expr,
        is_internal_expr,
        audience_label_expr,
    ) = _report_summary_query_parts()
    metric_averages = _report_metric_averages()
    sort_expr = _report_sort_expr(
        sort_by,
        case_count_expr=case_count_expr,
        run_count_expr=run_count_expr,
        audience_label_expr=audience_label_expr,
    )
    order_by = desc(sort_expr) if descending else asc(sort_expr)
    stmt = (
        select(
            EvalRunRecord.report_id,
            EvalRunRecord.name,
            EvalRunRecord.suite,
            EvalRunRecord.generated_at,
            EvalRunRecord.repeats,
            EvalRunRecord.max_concurrency,
            EvalRunRecord.pass_threshold,
            EvalRunRecord.status,
            EvalRunRecord.model_configs,
            case_count_expr.label("case_count"),
            run_count_expr.label("run_count"),
            is_internal_expr.label("is_internal"),
            metric_averages.c.pass_rate_average,
            metric_averages.c.duration_median_average,
        )
        .outerjoin(case_counts, case_counts.c.eval_run_id == EvalRunRecord.id)
        .outerjoin(run_counts, run_counts.c.eval_run_id == EvalRunRecord.id)
        .outerjoin(metric_averages, metric_averages.c.eval_run_id == EvalRunRecord.id)
        .order_by(order_by, desc(EvalRunRecord.generated_at), desc(EvalRunRecord.report_id))
        .offset(offset)
        .limit(limit)
    )
    search_condition = _report_search_condition(
        search,
        case_count_expr=case_count_expr,
        run_count_expr=run_count_expr,
        audience_label_expr=audience_label_expr,
    )
    if search_condition is not None:
        stmt = stmt.where(search_condition)
    rows = (await session.execute(stmt)).all()
    return [
        EvalReportSummaryRecord(
            report_id=row.report_id,
            name=row.name,
            suite=row.suite,
            generated_at=row.generated_at,
            repeats=row.repeats,
            max_concurrency=row.max_concurrency,
            pass_threshold=row.pass_threshold,
            status=row.status,
            model_configs=cast(dict[str, Any], row.model_configs),
            case_count=int(row.case_count),
            run_count=int(row.run_count),
            is_internal=cast(bool | None, row.is_internal),
            pass_rate_average=(
                float(row.pass_rate_average) if row.pass_rate_average is not None else None
            ),
            duration_median_average=(
                float(row.duration_median_average)
                if row.duration_median_average is not None
                else None
            ),
        )
        for row in rows
    ]


async def list_eval_reports(
    session: AsyncSession,
    *,
    descending: bool = True,
    limit: int,
    offset: int = 0,
    search: str | None,
    sort_by: EvalReportSortBy = "generated_at",
) -> list[EvalRunRecord]:
    (
        case_counts,
        run_counts,
        case_count_expr,
        run_count_expr,
        _is_internal_expr,
        audience_label_expr,
    ) = _report_summary_query_parts()
    sort_expr = _report_sort_expr(
        sort_by,
        case_count_expr=case_count_expr,
        run_count_expr=run_count_expr,
        audience_label_expr=audience_label_expr,
    )
    order_by = desc(sort_expr) if descending else asc(sort_expr)
    stmt = (
        select(EvalRunRecord)
        .outerjoin(case_counts, case_counts.c.eval_run_id == EvalRunRecord.id)
        .outerjoin(run_counts, run_counts.c.eval_run_id == EvalRunRecord.id)
        .options(selectinload(EvalRunRecord.cases).selectinload(EvalCaseResult.runs))
        .order_by(order_by, desc(EvalRunRecord.generated_at), desc(EvalRunRecord.report_id))
        .offset(offset)
        .limit(limit)
    )
    search_condition = _report_search_condition(
        search,
        case_count_expr=case_count_expr,
        run_count_expr=run_count_expr,
        audience_label_expr=audience_label_expr,
    )
    if search_condition is not None:
        stmt = stmt.where(search_condition)
    return list(await session.scalars(stmt))


async def get_eval_report(session: AsyncSession, report_id: str) -> EvalRunRecord | None:
    stmt = (
        select(EvalRunRecord)
        .where(EvalRunRecord.report_id == report_id)
        .options(selectinload(EvalRunRecord.cases).selectinload(EvalCaseResult.runs))
    )
    return await session.scalar(stmt)


@asynccontextmanager
async def eval_report_session() -> AsyncGenerator[AsyncSession]:
    """Open a guarded eval/test DB session without running migrations."""
    database_url = load_eval_database_url()
    engine = create_test_db_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
