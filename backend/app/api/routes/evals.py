from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn, cast

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import ColumnElement, case, func, select

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.schemas import PageOut, PaginationParams
from app.api.trace_projection import TraceOverviewItemOut, build_trace_overview
from app.core.db import get_session
from app.core.rbac import PermissionKey
from app.evals.case_management import (
    EvalCaseConflictError,
    EvalCaseDefinition,
    EvalCaseManagementError,
    EvalCaseNotFoundError,
    EvalCaseValidationError,
    create_eval_case_overlay,
    delete_eval_case_overlay,
    list_active_eval_case_ids,
    list_eval_case_definitions,
    resolve_eval_case_payloads_for_run,
    restore_disk_eval_case_overlay,
    update_eval_case_overlay,
)
from app.evals.runtime import EvalRunRequestConfig, EvalSuite, parse_test_cases_filter
from app.evals.service import (
    EVAL_RUN_MANAGER,
    EvalRunAlreadyRunningError,
    EvalRunNotFoundError,
    EvalRunPaths,
)
from app.evals.service import EvalRunSnapshot as EvalRunSnapshotModel
from app.evals.storage import (
    EvalReportSortBy,
    EvalReportSummaryRecord,
    count_eval_reports,
    eval_report_session,
    list_eval_report_summaries,
)
from app.evals.storage import get_eval_report as get_stored_eval_report
from app.models import EvalCaseResult, EvalCaseRunResult, EvalRunRecord, OtelSpan

router = APIRouter(prefix="/evals", tags=["evals"])

EvalsAccessUser = Annotated[CurrentUser, Depends(require_permission(PermissionKey.ACCESS_EVALS))]
EvalsStreamAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_EVALS), scope="function")
]

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = BACKEND_ROOT / "reports" / "logs"


class EvalReportSummaryOut(BaseModel):
    id: str
    title: str
    name: str
    suite: str
    generated_at: datetime
    repeats: int
    concurrency: int
    pass_threshold: float
    status: str
    case_count: int
    run_count: int
    is_internal: bool | None
    model_configs: dict[str, object]
    pass_rate_average: float | None
    duration_median_average: float | None


class EvalEvaluationResultOut(BaseModel):
    name: str
    value: object
    reason: str | None = None


class EvalCaseRunResultOut(BaseModel):
    run_index: int
    output: object | None
    duration: float
    error: str | None
    otel_trace_id: str | None
    otel_span_id: str | None
    assertions: dict[str, EvalEvaluationResultOut]
    scores: dict[str, EvalEvaluationResultOut]
    labels: dict[str, EvalEvaluationResultOut]


class EvalCaseResultOut(BaseModel):
    name: str
    inputs: object
    expected_output: object | None
    metadata: object | None
    stats: dict[str, object]
    runs: list[EvalCaseRunResultOut]


class EvalReportDetailOut(EvalReportSummaryOut):
    config: dict[str, object]
    additional_settings: dict[str, object]
    cases: list[EvalCaseResultOut]


class EvalTestCasesOut(BaseModel):
    suite: str
    cases: list[str]


class EvalCasePayloadIn(BaseModel):
    suite: str
    payload: dict[str, object]


class EvalCaseOut(BaseModel):
    suite: str
    case_id: str
    status: str
    active: bool
    payload: dict[str, object]
    payload_hash: str
    canonical_payload: dict[str, object] | None
    disk_hash: str | None
    overlay_base_disk_hash: str | None
    has_disk_changes: bool
    created_at: datetime | None
    updated_at: datetime | None


class EvalRunSnapshotOut(BaseModel):
    run_id: str
    suite: str
    status: str
    report_id: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class TraceSummaryOut(BaseModel):
    trace_id: str
    started_at: datetime | None
    duration_ms: float | None
    span_count: int
    root_span_name: str | None
    model: str | None
    is_error: bool
    is_public: bool | None
    conversation_id: str | None
    is_ai: bool


class TraceSpanOut(BaseModel):
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str | None
    status_code: str | None
    status_message: str | None
    start_time: datetime | None
    end_time: datetime | None
    duration_ms: float | None
    attributes: dict[str, object] | None
    events: list[dict[str, object]] | None
    links: list[dict[str, object]] | None
    resource: dict[str, object] | None
    scope: dict[str, object] | None


class TraceDetailOut(BaseModel):
    trace_id: str
    started_at: datetime | None
    duration_ms: float | None
    span_count: int
    is_public: bool | None
    conversation_id: str | None
    spans: list[TraceSpanOut]
    overview: list[TraceOverviewItemOut]


class EvalRunRequest(BaseModel):
    suite: str
    repeat: int = 1
    max_concurrency: int = 5
    test_cases: str | None = None
    pass_threshold: float = 0.9
    chatbot_model: str | None = None
    guardrail_model: str | None = None
    evaluation_model: str | None = None
    rebuild_rag: bool = False


def _format_sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _eval_run_snapshot_out(snapshot: EvalRunSnapshotModel) -> EvalRunSnapshotOut:
    return EvalRunSnapshotOut(
        run_id=snapshot.run_id,
        suite=snapshot.suite,
        status=snapshot.status,
        report_id=snapshot.report_id,
        error_message=snapshot.error_message,
        started_at=snapshot.started_at,
        completed_at=snapshot.completed_at,
    )


def _trace_duration_ms(started_at: datetime | None, ended_at: datetime | None) -> float | None:
    if started_at is None or ended_at is None:
        return None
    return (ended_at - started_at).total_seconds() * 1000


def _span_time_expr() -> ColumnElement[datetime]:
    return func.coalesce(OtelSpan.start_time, OtelSpan.span_time, OtelSpan.created_at)


def _trace_span_out(span: OtelSpan) -> TraceSpanOut:
    return TraceSpanOut(
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        kind=span.kind,
        status_code=span.status_code,
        status_message=span.status_message,
        start_time=span.start_time,
        end_time=span.end_time,
        duration_ms=span.duration_ms,
        attributes=span.attributes,
        events=span.events,
        links=span.links,
        resource=span.resource,
        scope=span.scope,
    )


def _resolve_eval_suite_name(suite: str) -> EvalSuite:
    try:
        return EvalSuite(suite)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Unsupported eval suite") from error


def _humanize_eval_name(name: str) -> str:
    words = [word for word in name.replace("-", "_").split("_") if word]
    if not words:
        return "Eval Run"
    acronyms = {"ai", "api", "llm", "rag", "url", "va"}
    return " ".join(word.upper() if word.lower() in acronyms else word.title() for word in words)


def _report_is_internal(report: EvalRunRecord) -> bool | None:
    values: set[bool] = set()
    for case_record in report.cases:
        if isinstance(case_record.inputs, dict):
            is_internal = case_record.inputs.get("is_internal")
            if isinstance(is_internal, bool):
                values.add(is_internal)
    return values.pop() if len(values) == 1 else None


def _case_stat_number(case_record: EvalCaseResult, key: str) -> float | None:
    value = case_record.stats.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _average_defined(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _report_pass_rate_average(report: EvalRunRecord) -> float | None:
    return _average_defined(
        [
            pass_rate
            for case_record in report.cases
            if (pass_rate := _case_stat_number(case_record, "pass_rate")) is not None
        ]
    )


def _report_duration_median_average(report: EvalRunRecord) -> float | None:
    return _average_defined(
        [
            duration_median
            for case_record in report.cases
            if (duration_median := _case_stat_number(case_record, "duration_median")) is not None
        ]
    )


def _result_out(payload: object) -> EvalEvaluationResultOut:
    if not isinstance(payload, dict):
        return EvalEvaluationResultOut(name="result", value=payload, reason=None)
    value_by_key = cast(dict[str, object], payload)
    reason = value_by_key.get("reason")
    return EvalEvaluationResultOut(
        name=str(value_by_key.get("name", "result")),
        value=value_by_key.get("value"),
        reason=str(reason) if reason is not None else None,
    )


def _result_map_out(values: dict[str, object]) -> dict[str, EvalEvaluationResultOut]:
    return {key: _result_out(value) for key, value in values.items()}


def _case_run_out(run: EvalCaseRunResult) -> EvalCaseRunResultOut:
    return EvalCaseRunResultOut(
        run_index=run.run_index,
        output=run.output,
        duration=run.duration,
        error=run.error,
        otel_trace_id=run.otel_trace_id,
        otel_span_id=run.otel_span_id,
        assertions=_result_map_out(run.assertions),
        scores=_result_map_out(run.scores),
        labels=_result_map_out(run.labels),
    )


def _case_out(case_record: EvalCaseResult) -> EvalCaseResultOut:
    return EvalCaseResultOut(
        name=case_record.name,
        inputs=case_record.inputs,
        expected_output=case_record.expected_output,
        metadata=case_record.metadata_json,
        stats=case_record.stats,
        runs=[_case_run_out(run) for run in case_record.runs],
    )


def _case_definition_out(case_definition: EvalCaseDefinition) -> EvalCaseOut:
    return EvalCaseOut(
        suite=case_definition.suite.value,
        case_id=case_definition.case_id,
        status=case_definition.status,
        active=case_definition.active,
        payload=case_definition.payload,
        payload_hash=case_definition.payload_hash,
        canonical_payload=case_definition.canonical_payload,
        disk_hash=case_definition.disk_hash,
        overlay_base_disk_hash=case_definition.overlay_base_disk_hash,
        has_disk_changes=case_definition.has_disk_changes,
        created_at=case_definition.created_at,
        updated_at=case_definition.updated_at,
    )


def _raise_case_management_error(error: EvalCaseManagementError) -> NoReturn:
    if isinstance(error, EvalCaseNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, EvalCaseConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, EvalCaseValidationError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=400, detail=str(error)) from error


def _report_summary_out(report: EvalRunRecord) -> EvalReportSummaryOut:
    return _report_summary_record_out(
        EvalReportSummaryRecord(
            report_id=report.report_id,
            name=report.name,
            suite=report.suite,
            generated_at=report.generated_at,
            repeats=report.repeats,
            max_concurrency=report.max_concurrency,
            pass_threshold=report.pass_threshold,
            status=report.status,
            case_count=len(report.cases),
            run_count=sum(len(case_record.runs) for case_record in report.cases),
            is_internal=_report_is_internal(report),
            model_configs=report.model_configs,
            pass_rate_average=_report_pass_rate_average(report),
            duration_median_average=_report_duration_median_average(report),
        )
    )


def _report_summary_record_out(summary: EvalReportSummaryRecord) -> EvalReportSummaryOut:
    return EvalReportSummaryOut(
        id=summary.report_id,
        title=_humanize_eval_name(summary.name or summary.suite),
        name=summary.name,
        suite=summary.suite,
        generated_at=summary.generated_at,
        repeats=summary.repeats,
        concurrency=summary.max_concurrency,
        pass_threshold=summary.pass_threshold,
        status=summary.status,
        case_count=summary.case_count,
        run_count=summary.run_count,
        is_internal=summary.is_internal,
        model_configs=summary.model_configs,
        pass_rate_average=summary.pass_rate_average,
        duration_median_average=summary.duration_median_average,
    )


def _report_detail_out(report: EvalRunRecord) -> EvalReportDetailOut:
    summary = _report_summary_out(report)
    return EvalReportDetailOut(
        **summary.model_dump(),
        config=report.config,
        additional_settings=report.additional_settings,
        cases=[_case_out(case_record) for case_record in report.cases],
    )


@router.get("/test-cases", response_model=EvalTestCasesOut)
async def list_eval_test_cases(
    session: SessionDep, suite: Annotated[str, Query()], _current_user: EvalsAccessUser
) -> EvalTestCasesOut:
    del _current_user
    suite_name = _resolve_eval_suite_name(suite)
    cases = await list_active_eval_case_ids(session, suite_name)
    return EvalTestCasesOut(suite=suite, cases=cases)


@router.get("/cases", response_model=list[EvalCaseOut])
async def list_eval_cases(
    session: SessionDep, suite: Annotated[str, Query()], _current_user: EvalsAccessUser
) -> list[EvalCaseOut]:
    del _current_user
    suite_name = _resolve_eval_suite_name(suite)
    try:
        cases = await list_eval_case_definitions(session, suite_name)
    except EvalCaseManagementError as error:
        _raise_case_management_error(error)
    return [_case_definition_out(case_definition) for case_definition in cases]


@router.post("/cases", response_model=EvalCaseOut)
async def create_eval_case(
    payload: EvalCasePayloadIn, session: SessionDep, current_user: EvalsAccessUser
) -> EvalCaseOut:
    suite_name = _resolve_eval_suite_name(payload.suite)
    try:
        case_definition = await create_eval_case_overlay(
            session, suite=suite_name, payload=payload.payload, user_id=current_user.id
        )
    except EvalCaseManagementError as error:
        _raise_case_management_error(error)
    return _case_definition_out(case_definition)


@router.put("/cases/{case_id}", response_model=EvalCaseOut)
async def update_eval_case(
    case_id: str, payload: EvalCasePayloadIn, session: SessionDep, current_user: EvalsAccessUser
) -> EvalCaseOut:
    suite_name = _resolve_eval_suite_name(payload.suite)
    try:
        case_definition = await update_eval_case_overlay(
            session,
            suite=suite_name,
            case_id=case_id,
            payload=payload.payload,
            user_id=current_user.id,
        )
    except EvalCaseManagementError as error:
        _raise_case_management_error(error)
    return _case_definition_out(case_definition)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_eval_case(
    case_id: str, session: SessionDep, suite: Annotated[str, Query()], current_user: EvalsAccessUser
) -> None:
    suite_name = _resolve_eval_suite_name(suite)
    try:
        await delete_eval_case_overlay(
            session, suite=suite_name, case_id=case_id, user_id=current_user.id
        )
    except EvalCaseManagementError as error:
        _raise_case_management_error(error)


@router.post("/cases/{case_id}/restore", response_model=EvalCaseOut)
async def restore_eval_case(
    case_id: str,
    session: SessionDep,
    suite: Annotated[str, Query()],
    _current_user: EvalsAccessUser,
) -> EvalCaseOut:
    del _current_user
    suite_name = _resolve_eval_suite_name(suite)
    try:
        case_definition = await restore_disk_eval_case_overlay(
            session, suite=suite_name, case_id=case_id
        )
    except EvalCaseManagementError as error:
        _raise_case_management_error(error)
    return _case_definition_out(case_definition)


@router.get("/trace-index", response_model=PageOut[TraceSummaryOut])
async def get_eval_trace_index(
    _current_user: EvalsAccessUser,
    page_params: Annotated[PaginationParams, Depends()],
    ai_only: Annotated[bool, Query()] = False,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> PageOut[TraceSummaryOut]:
    del _current_user
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")

    span_time_expr = _span_time_expr()
    started_at_expr = func.min(span_time_expr).label("started_at")
    ended_at_expr = func.max(func.coalesce(OtelSpan.end_time, OtelSpan.created_at)).label(
        "ended_at"
    )
    latest_start_expr = func.max(span_time_expr).label("latest_start")
    span_count_expr = func.count(OtelSpan.id).label("span_count")
    root_name_expr = func.max(
        case((OtelSpan.parent_span_id.is_(None), OtelSpan.name), else_=None)
    ).label("root_span_name")
    error_expr = func.bool_or(OtelSpan.status_code == "ERROR").label("is_error")
    ai_expr = func.bool_or(OtelSpan.is_ai).label("is_ai")
    model_expr = func.max(OtelSpan.request_model).label("model")

    stmt = select(
        OtelSpan.trace_id,
        started_at_expr,
        ended_at_expr,
        latest_start_expr,
        span_count_expr,
        root_name_expr,
        error_expr,
        ai_expr,
        model_expr,
    ).group_by(OtelSpan.trace_id)
    if ai_only:
        ai_trace_ids = select(func.distinct(OtelSpan.trace_id)).where(OtelSpan.is_ai.is_(True))
        stmt = stmt.where(OtelSpan.trace_id.in_(ai_trace_ids))
    if start is not None:
        stmt = stmt.having(started_at_expr >= start)
    if end is not None:
        stmt = stmt.having(started_at_expr <= end)

    async with eval_report_session() as session:
        rows = (await session.execute(stmt)).all()

    items = [
        TraceSummaryOut(
            trace_id=row.trace_id,
            started_at=row.started_at,
            duration_ms=_trace_duration_ms(row.started_at, row.ended_at),
            span_count=row.span_count,
            root_span_name=row.root_span_name,
            model=row.model,
            is_error=bool(row.is_error),
            is_public=None,
            conversation_id=None,
            is_ai=bool(row.is_ai),
        )
        for row in rows
    ]

    earliest_time = datetime.min.replace(tzinfo=UTC)
    if page_params.sort_by == "duration_ms":
        items.sort(key=lambda item: item.duration_ms or 0.0, reverse=page_params.descending)
    elif page_params.sort_by == "span_count":
        items.sort(key=lambda item: item.span_count, reverse=page_params.descending)
    elif page_params.sort_by == "latest_start":
        latest_start_by_trace = {row.trace_id: row.latest_start for row in rows}
        items.sort(
            key=lambda item: latest_start_by_trace.get(item.trace_id) or earliest_time,
            reverse=page_params.descending,
        )
    else:
        items.sort(
            key=lambda item: item.started_at or earliest_time, reverse=page_params.descending
        )

    total = len(items)
    end_offset = page_params.offset + page_params.limit if page_params.limit > 0 else None
    return PageOut[TraceSummaryOut](items=items[page_params.offset : end_offset], total=total)


@router.get("/trace/{trace_id}", response_model=TraceDetailOut)
async def get_eval_trace_detail(trace_id: str, _current_user: EvalsAccessUser) -> TraceDetailOut:
    del _current_user
    span_time_expr = _span_time_expr()
    async with eval_report_session() as session:
        spans = list(
            (
                await session.execute(
                    select(OtelSpan)
                    .where(OtelSpan.trace_id == trace_id)
                    .order_by(span_time_expr.asc())
                )
            )
            .scalars()
            .all()
        )

    if not spans:
        raise HTTPException(status_code=404, detail="Trace not found")

    start_times = [span.start_time or span.span_time or span.created_at for span in spans]
    end_times = [span.end_time or span.created_at for span in spans]
    started_at = min(start_times) if start_times else None
    ended_at = max(end_times) if end_times else None
    return TraceDetailOut(
        trace_id=trace_id,
        started_at=started_at,
        duration_ms=_trace_duration_ms(started_at, ended_at),
        span_count=len(spans),
        is_public=None,
        conversation_id=None,
        spans=[_trace_span_out(span) for span in spans],
        overview=build_trace_overview(spans),
    )


@router.get("/reports", response_model=PageOut[EvalReportSummaryOut])
async def list_eval_reports(
    _current_user: EvalsAccessUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query()] = None,
    sort_by: Annotated[EvalReportSortBy, Query()] = "generated_at",
    descending: Annotated[bool, Query()] = True,
) -> PageOut[EvalReportSummaryOut]:
    del _current_user
    async with eval_report_session() as session:
        total = await count_eval_reports(session, search=search)
        reports = await list_eval_report_summaries(
            session,
            descending=descending,
            limit=limit,
            offset=offset,
            search=search,
            sort_by=sort_by,
        )

    return PageOut[EvalReportSummaryOut](
        items=[_report_summary_record_out(report) for report in reports], total=total
    )


@router.get("/reports/{report_id}", response_model=EvalReportDetailOut)
async def get_eval_report(report_id: str, _current_user: EvalsAccessUser) -> EvalReportDetailOut:
    del _current_user
    async with eval_report_session() as session:
        report = await get_stored_eval_report(session, report_id)

    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    return _report_detail_out(report)


@router.post("/runs/stream")
async def run_eval_stream(
    run_request: EvalRunRequest, request: Request, current_user: EvalsStreamAccessUser
) -> StreamingResponse:
    if run_request.repeat < 1:
        raise HTTPException(status_code=400, detail="Repeat must be at least 1")

    if run_request.max_concurrency < 1:
        raise HTTPException(status_code=400, detail="Max concurrency must be at least 1")

    if not 0 < run_request.pass_threshold <= 1:
        raise HTTPException(status_code=400, detail="Pass threshold must be between 0 and 1")

    suite = _resolve_eval_suite_name(run_request.suite)
    selected_test_cases = parse_test_cases_filter(run_request.test_cases)
    try:
        async with get_session() as session:
            case_payloads = await resolve_eval_case_payloads_for_run(
                session, suite, selected_test_cases
            )
    except EvalCaseManagementError as error:
        _raise_case_management_error(error)

    config = EvalRunRequestConfig(
        suite=suite,
        repeat=run_request.repeat,
        max_concurrency=run_request.max_concurrency,
        test_cases=selected_test_cases,
        case_payloads=case_payloads,
        pass_threshold=run_request.pass_threshold,
        rebuild_rag=run_request.rebuild_rag,
        chatbot_model=run_request.chatbot_model,
        guardrail_model=run_request.guardrail_model,
        evaluation_model=run_request.evaluation_model,
    )
    paths = EvalRunPaths(logs_dir=LOGS_DIR)
    try:
        job = EVAL_RUN_MANAGER.start_run(config, paths=paths, user_id=current_user.id)
    except EvalRunAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    async def event_stream() -> AsyncGenerator[str]:
        async for event in job.subscribe():
            if await request.is_disconnected():
                return
            yield _format_sse(event.event, event.payload)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs/current", response_model=EvalRunSnapshotOut | None)
async def get_current_eval_run(current_user: EvalsAccessUser) -> EvalRunSnapshotOut | None:
    job = EVAL_RUN_MANAGER.current_run(current_user.id)
    if job is None:
        return None
    return _eval_run_snapshot_out(job.snapshot())


@router.post("/runs/{run_id}/stream")
async def stream_existing_eval_run(
    run_id: str, request: Request, current_user: EvalsStreamAccessUser
) -> StreamingResponse:
    try:
        job = EVAL_RUN_MANAGER.get_run(run_id, user_id=current_user.id)
    except EvalRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Eval run not found") from error

    async def event_stream() -> AsyncGenerator[str]:
        async for event in job.subscribe():
            if await request.is_disconnected():
                return
            yield _format_sse(event.event, event.payload)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/cancel", response_model=EvalRunSnapshotOut)
async def cancel_eval_run(run_id: str, current_user: EvalsAccessUser) -> EvalRunSnapshotOut:
    try:
        job = EVAL_RUN_MANAGER.get_run(run_id, user_id=current_user.id)
    except EvalRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Eval run not found") from error
    await job.cancel()
    return _eval_run_snapshot_out(job.snapshot())
