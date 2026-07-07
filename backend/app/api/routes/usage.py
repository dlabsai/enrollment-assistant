from __future__ import annotations

import uuid  # noqa: TC003
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, Integer, String, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import ColumnElement

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.response_costs import price_usage
from app.api.schemas import PageOut, PaginationParams
from app.api.trace_projection import TraceOverviewItemOut, build_trace_overview
from app.core.rbac import (
    PermissionKey,
    can_view_chat_owner,
    get_effective_permission_map,
    user_has_permission,
)
from app.models import Conversation, OtelSpan, RbacGroup, User
from app.rag.constants import EMBEDDING_MODEL

if TYPE_CHECKING:
    from collections.abc import Iterable

router = APIRouter(prefix="/usage", tags=["usage"])

_EARLIEST_TIME = datetime.min.replace(tzinfo=UTC)
_PROVIDER_PREFIXES = frozenset({"azure", "openai", "openrouter"})
_EMBEDDING_PRICE_PROVIDER = "azure"
UsageAccessUser = Annotated[CurrentUser, Depends(require_permission(PermissionKey.ACCESS_USAGE))]
TracesAccessUser = Annotated[CurrentUser, Depends(require_permission(PermissionKey.ACCESS_TRACES))]


class UsageTraceBasicOut(BaseModel):
    created_at: datetime
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost: float | None
    duration: float | None
    is_error: bool
    is_public: bool | None


class UsageDailyOut(BaseModel):
    date: datetime
    requests: int
    tokens: int
    cost: float
    embedding_requests: int
    embedding_tokens: int
    embedding_cost: float
    errors: int
    avg_duration: float


class UsageModelOut(BaseModel):
    model: str
    requests: int
    tokens: int
    cost: float


class UsageSummaryOut(BaseModel):
    total_requests: int
    total_tokens: int
    total_cost: float
    total_embedding_requests: int
    total_embedding_tokens: int
    total_embedding_cost: float
    total_embedding_avg_duration: float
    total_errors: int
    avg_duration: float


class UsageOverviewOut(BaseModel):
    summary: UsageSummaryOut
    daily: list[UsageDailyOut]
    models: list[UsageModelOut]
    latest_traces: list[UsageTraceBasicOut]


def _use_hourly_buckets(start: datetime | None, end: datetime | None) -> bool:
    return start is not None and end is not None and end - start <= timedelta(hours=24)


def _build_usage_daily_data(
    rows: Iterable[Any], start: datetime | None, end: datetime | None, *, use_hourly: bool
) -> list[UsageDailyOut]:
    if not use_hourly or start is None or end is None:
        return [
            UsageDailyOut(
                date=row.date,
                requests=row.requests,
                tokens=row.tokens,
                cost=float(row.cost),
                embedding_requests=row.embedding_requests,
                embedding_tokens=row.embedding_tokens,
                embedding_cost=float(row.embedding_cost),
                errors=row.errors,
                avg_duration=float(row.avg_duration or 0),
            )
            for row in rows
        ]

    row_map = {row.date: row for row in rows}
    current = start.replace(minute=0, second=0, microsecond=0)
    end_bucket = end.replace(minute=0, second=0, microsecond=0)
    hourly_rows: list[UsageDailyOut] = []
    while current <= end_bucket:
        row = row_map.get(current)
        if row is None:
            hourly_rows.append(
                UsageDailyOut(
                    date=current,
                    requests=0,
                    tokens=0,
                    cost=0.0,
                    embedding_requests=0,
                    embedding_tokens=0,
                    embedding_cost=0.0,
                    errors=0,
                    avg_duration=0.0,
                )
            )
        else:
            hourly_rows.append(
                UsageDailyOut(
                    date=row.date,
                    requests=row.requests,
                    tokens=row.tokens,
                    cost=float(row.cost),
                    embedding_requests=row.embedding_requests,
                    embedding_tokens=row.embedding_tokens,
                    embedding_cost=float(row.embedding_cost),
                    errors=row.errors,
                    avg_duration=float(row.avg_duration or 0),
                )
            )
        current += timedelta(hours=1)

    return hourly_rows


def _strip_model_provider_prefix(model: str, provider: str) -> str:
    slash_prefix = f"{provider}/"
    colon_prefix = f"{provider}:"
    if model.startswith(slash_prefix):
        return model.removeprefix(slash_prefix)
    if model.startswith(colon_prefix):
        return model.removeprefix(colon_prefix)
    return model


def _display_provider(provider: str | None, server: str | None, model: str) -> str | None:
    if provider in {"azure", "azure.ai.openai"} or model.startswith("azure/"):
        return "azure"
    if provider == "openrouter" or model.startswith("openrouter/"):
        return "openrouter"
    if provider == "openai" or model.startswith("openai/"):
        if server == "openrouter.ai":
            return "openrouter"
        return "openai"
    return None


def _format_model_display(model: str, provider: str | None, server: str | None) -> str:
    display_provider = _display_provider(provider, server, model)
    if display_provider is None:
        return model
    return f"{display_provider}:{_strip_model_provider_prefix(model, display_provider)}"


def _format_model_from_attributes(attributes: dict[str, Any]) -> str | None:
    model_value = attributes.get("gen_ai.request.model")
    if model_value is None:
        return None
    provider_value = attributes.get("gen_ai.provider.name")
    server_value = attributes.get("server.address")
    provider = str(provider_value) if provider_value is not None else None
    server = str(server_value) if server_value is not None else None
    return _format_model_display(str(model_value), provider, server)


def _format_model_from_span(span: OtelSpan) -> str | None:
    if span.request_model is not None:
        return _format_model_display(span.request_model, span.provider_name, span.server_address)
    attributes = span.attributes or {}
    return _format_model_from_attributes(attributes)


@lru_cache(maxsize=1)
def _embedding_cost_per_token_by_model() -> dict[str, float]:
    rate = price_usage(
        model=EMBEDDING_MODEL,
        provider_id=_EMBEDDING_PRICE_PROVIDER,
        genai_request_timestamp=None,
        input_tokens=1,
    )
    if rate is None:
        return {}
    return {
        EMBEDDING_MODEL: rate,
        _format_model_display(EMBEDDING_MODEL, _EMBEDDING_PRICE_PROVIDER, None): rate,
    }


def _estimated_embedding_cost(model: str, input_tokens: int | None) -> float | None:
    if input_tokens is None:
        return None
    rate = _embedding_cost_per_token_by_model().get(model)
    if rate is None:
        return None
    return input_tokens * rate


def _effective_span_cost(span: OtelSpan, model: str) -> float | None:
    if span.total_cost is not None:
        return span.total_cost
    if span.is_embedding is not True:
        return None
    return _estimated_embedding_cost(model, span.input_tokens)


def _provider_prefixed_model_expr(
    base_model_expr: ColumnElement[str], provider: str
) -> ColumnElement[str]:
    slash_prefix = f"{provider}/%"
    colon_prefix = f"{provider}:%"
    stripped_model_expr: ColumnElement[str] = case(
        (base_model_expr.ilike(slash_prefix), func.substring(base_model_expr, len(provider) + 2)),
        (base_model_expr.ilike(colon_prefix), func.substring(base_model_expr, len(provider) + 2)),
        else_=base_model_expr,
    )
    return func.concat(f"{provider}:", stripped_model_expr)


def _build_model_display_expr(
    base_model_expr: ColumnElement[str],
    provider_expr: ColumnElement[str],
    server_expr: ColumnElement[str],
) -> ColumnElement[str]:
    azure_model_expr = _provider_prefixed_model_expr(base_model_expr, "azure")
    openai_model_expr = _provider_prefixed_model_expr(base_model_expr, "openai")
    openrouter_model_expr = _provider_prefixed_model_expr(base_model_expr, "openrouter")
    return case(
        (provider_expr.in_(("azure", "azure.ai.openai")), azure_model_expr),
        (provider_expr == "openrouter", openrouter_model_expr),
        ((provider_expr == "openai") & (server_expr == "openrouter.ai"), openrouter_model_expr),
        (provider_expr == "openai", openai_model_expr),
        (base_model_expr.ilike("azure/%"), azure_model_expr),
        (base_model_expr.ilike("openrouter/%"), openrouter_model_expr),
        (base_model_expr.ilike("openai/%"), openai_model_expr),
        else_=base_model_expr,
    )


def _build_model_filter(
    model_expr: ColumnElement[str], models: Iterable[str] | None
) -> ColumnElement[bool] | None:
    if not models:
        return None

    filters: list[ColumnElement[bool]] = []
    for raw_value in models:
        value = raw_value.strip().removesuffix(":")
        if value == "":
            continue
        if value in _PROVIDER_PREFIXES:
            filters.append(model_expr.ilike(f"{value}:%"))
        else:
            filters.append(model_expr == value)
    if not filters:
        return None
    return or_(*filters)


def _build_effective_cost_expr(
    *,
    stored_cost_expr: ColumnElement[float],
    is_embedding_expr: ColumnElement[bool],
    input_tokens_expr: ColumnElement[int],
    model_expr: ColumnElement[str],
) -> ColumnElement[Any]:
    token_count_expr: ColumnElement[int] = func.coalesce(input_tokens_expr, 0)
    cost_per_token_by_model = _embedding_cost_per_token_by_model()
    if not cost_per_token_by_model:
        return stored_cost_expr

    estimated_embedding_cost_expr = case(
        *(
            (model_expr == model, token_count_expr * rate)
            for model, rate in cost_per_token_by_model.items()
        ),
        else_=None,
    )
    return case(
        (stored_cost_expr.is_not(None), stored_cost_expr),
        (is_embedding_expr, estimated_embedding_cost_expr),
        else_=stored_cost_expr,
    )


class TraceSummaryOut(BaseModel):
    trace_id: str
    started_at: datetime | None
    duration_ms: float | None
    span_count: int
    root_span_name: str | None
    model: str | None
    is_error: bool
    is_public: bool | None
    conversation_id: uuid.UUID | None
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
    attributes: dict[str, Any] | None
    events: list[dict[str, Any]] | None
    links: list[dict[str, Any]] | None
    resource: dict[str, Any] | None
    scope: dict[str, Any] | None


class TraceDetailOut(BaseModel):
    trace_id: str
    started_at: datetime | None
    duration_ms: float | None
    span_count: int
    is_public: bool | None
    conversation_id: uuid.UUID | None
    spans: list[TraceSpanOut]
    overview: list[TraceOverviewItemOut]


@dataclass(frozen=True)
class _TraceContext:
    is_public: bool | None
    conversation_id: uuid.UUID | None
    conversation: Conversation | None


class TraceAccessSource(StrEnum):
    PAGE = "page"
    CHAT_TRACE = "chat_trace"
    CHAT_ACTIVITY = "chat_activity"
    CHATS_TRACE = "chats_trace"


def _is_admin_user(current_user: CurrentUser) -> bool:
    return current_user.group.slug in {"admin", "dev"}


async def _get_conversation_owner_group_slug(
    session: SessionDep, conversation: Conversation, current_user: CurrentUser
) -> str | None:
    if conversation.user_id is None:
        return None

    if conversation.user_id == current_user.id:
        return current_user.group.slug

    return await session.scalar(
        select(RbacGroup.slug)
        .join(User, User.group_id == RbacGroup.id)
        .where(User.id == conversation.user_id)
    )


async def _ensure_trace_access(
    context: _TraceContext,
    current_user: CurrentUser,
    session: SessionDep,
    source: TraceAccessSource,
) -> None:
    required_permission = {
        TraceAccessSource.PAGE: PermissionKey.ACCESS_TRACES,
        TraceAccessSource.CHAT_TRACE: PermissionKey.CHAT_VIEW_TRACE,
        TraceAccessSource.CHAT_ACTIVITY: PermissionKey.CHAT_VIEW_ACTIVITY,
        TraceAccessSource.CHATS_TRACE: PermissionKey.CHATS_VIEW_TRACE,
    }[source]
    if not await user_has_permission(session, current_user, required_permission):
        raise HTTPException(status_code=403, detail="Access denied")

    if source == TraceAccessSource.CHATS_TRACE and not await user_has_permission(
        session, current_user, PermissionKey.ACCESS_CHATS
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    conversation = context.conversation
    if conversation is not None:
        if conversation.is_public:
            if not _is_admin_user(current_user):
                raise HTTPException(status_code=403, detail="Access denied")
            return

        if source == TraceAccessSource.CHATS_TRACE:
            permission_map = await get_effective_permission_map(session, current_user)
            owner_group_slug = await _get_conversation_owner_group_slug(
                session, conversation, current_user
            )
            if can_view_chat_owner(
                permission_map=permission_map,
                owner_group_slug=owner_group_slug,
                is_owner=conversation.user_id == current_user.id,
            ):
                return
            raise HTTPException(status_code=403, detail="Access denied")

        if conversation.user_id == current_user.id or _is_admin_user(current_user):
            return

        raise HTTPException(status_code=403, detail="Access denied")

    if context.is_public is not None:
        if not _is_admin_user(current_user):
            raise HTTPException(status_code=403, detail="Access denied")
        return

    raise HTTPException(status_code=404, detail="Trace not found")


async def _resolve_trace_context_map(
    session: SessionDep, trace_ids: list[str]
) -> dict[str, _TraceContext]:
    if not trace_ids:
        return {}

    context_rows = (
        await session.execute(
            select(OtelSpan.trace_id, OtelSpan.conversation_id, OtelSpan.is_internal)
            .where(OtelSpan.trace_id.in_(trace_ids))
            .where((OtelSpan.conversation_id.is_not(None)) | (OtelSpan.is_internal.is_not(None)))
        )
    ).all()

    grouped: dict[str, _TraceContext] = {}
    conversation_ids: set[uuid.UUID] = set()
    for row in context_rows:
        current = grouped.get(
            row.trace_id, _TraceContext(is_public=None, conversation_id=None, conversation=None)
        )
        conversation_id = row.conversation_id or current.conversation_id
        if conversation_id is not None:
            conversation_ids.add(conversation_id)

        is_public = current.is_public
        if row.is_internal is not None:
            is_public = not bool(row.is_internal)

        grouped[row.trace_id] = _TraceContext(
            is_public=is_public, conversation_id=conversation_id, conversation=None
        )

    conversations: dict[uuid.UUID, Conversation] = {}
    if conversation_ids:
        conversation_rows = (
            (
                await session.execute(
                    select(Conversation).where(Conversation.id.in_(conversation_ids))
                )
            )
            .scalars()
            .all()
        )
        conversations = {conversation.id: conversation for conversation in conversation_rows}

    resolved: dict[str, _TraceContext] = {}
    for trace_id, context in grouped.items():
        conversation = (
            conversations.get(context.conversation_id)
            if context.conversation_id is not None
            else None
        )
        resolved[trace_id] = _TraceContext(
            is_public=conversation.is_public if conversation is not None else context.is_public,
            conversation_id=context.conversation_id,
            conversation=conversation,
        )

    return resolved


async def _build_trace_meta_map(
    session: SessionDep, trace_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not trace_ids:
        return {}

    root_name_expr = func.max(
        case((OtelSpan.parent_span_id.is_(None), OtelSpan.name), else_=None)
    ).label("root_span_name")
    error_expr = func.bool_or(OtelSpan.status_code == "ERROR").label("is_error")
    ai_expr = func.bool_or(OtelSpan.is_ai).label("is_ai")
    model_expr = func.max(OtelSpan.request_model).label("request_model")

    rows = (
        await session.execute(
            select(OtelSpan.trace_id, root_name_expr, error_expr, ai_expr, model_expr)
            .where(OtelSpan.trace_id.in_(trace_ids))
            .group_by(OtelSpan.trace_id)
        )
    ).all()

    return {
        row.trace_id: {
            "root_span_name": row.root_span_name,
            "is_error": bool(row.is_error),
            "is_ai": bool(row.is_ai),
            "model": row.request_model,
        }
        for row in rows
    }


def _trace_duration_ms(started_at: datetime | None, ended_at: datetime | None) -> float | None:
    if started_at is None or ended_at is None:
        return None
    return (ended_at - started_at).total_seconds() * 1000


@router.get("/summary", response_model=UsageOverviewOut)
async def get_usage_summary(
    session: SessionDep,
    current_user: UsageAccessUser,
    platform: Annotated[str | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    models: Annotated[list[str] | None, Query()] = None,
    latest_limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> Any:
    _ = current_user
    if platform not in {None, "both", "internal", "public"}:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")

    platform_value = "both" if platform in (None, "both") else platform

    span_time_expr: ColumnElement[datetime] = func.coalesce(
        OtelSpan.span_time, OtelSpan.start_time, OtelSpan.created_at
    )
    base_model_expr: ColumnElement[str] = cast(OtelSpan.request_model, String)
    provider_expr: ColumnElement[str] = cast(OtelSpan.provider_name, String)
    server_expr: ColumnElement[str] = cast(OtelSpan.server_address, String)
    model_expr = _build_model_display_expr(base_model_expr, provider_expr, server_expr)
    input_tokens_expr: ColumnElement[int] = cast(OtelSpan.input_tokens, Integer)
    output_tokens_expr: ColumnElement[int] = cast(OtelSpan.output_tokens, Integer)
    tokens_expr: ColumnElement[int] = func.coalesce(input_tokens_expr, 0) + func.coalesce(
        output_tokens_expr, 0
    )
    stored_cost_expr: ColumnElement[float] = cast(OtelSpan.total_cost, Float)
    duration_expr: ColumnElement[float | None] = case(
        (OtelSpan.duration_ms.is_not(None), OtelSpan.duration_ms / 1000.0), else_=None
    )
    is_embedding_expr: ColumnElement[bool] = func.coalesce(OtelSpan.is_embedding, False)
    effective_cost_expr = _build_effective_cost_expr(
        stored_cost_expr=stored_cost_expr,
        is_embedding_expr=is_embedding_expr,
        input_tokens_expr=input_tokens_expr,
        model_expr=model_expr,
    )
    is_error_expr: ColumnElement[bool] = OtelSpan.status_code == "ERROR"

    filters: list[Any] = [OtelSpan.request_model.is_not(None), OtelSpan.is_ai.is_(True)]
    if start is not None:
        filters.append(span_time_expr >= start)
    if end is not None:
        filters.append(span_time_expr <= end)
    model_filter = _build_model_filter(model_expr, models)
    if model_filter is not None:
        filters.append(model_filter)

    trace_context_subquery = None
    platform_filter = None
    if platform_value in {"internal", "public"}:
        trace_context_subquery = (
            select(
                OtelSpan.trace_id.label("trace_id"),
                func.max(cast(OtelSpan.conversation_id, String)).label("conversation_id"),
                func.bool_or(OtelSpan.is_internal).label("is_internal"),
            )
            .where(or_(OtelSpan.conversation_id.is_not(None), OtelSpan.is_internal.is_not(None)))
            .group_by(OtelSpan.trace_id)
            .subquery()
        )

        is_public_expr = case(
            (
                trace_context_subquery.c.is_internal.is_not(None),
                ~trace_context_subquery.c.is_internal,
            ),
            (Conversation.is_public.is_not(None), Conversation.is_public),
            else_=None,
        )
        is_public_filter_expr = func.coalesce(is_public_expr, False)
        platform_filter = is_public_filter_expr.is_(platform_value == "public")

    def apply_platform_filters(statement: Any) -> Any:
        if trace_context_subquery is None:
            return statement
        return statement.outerjoin(
            trace_context_subquery, trace_context_subquery.c.trace_id == OtelSpan.trace_id
        ).outerjoin(
            Conversation, Conversation.id == cast(trace_context_subquery.c.conversation_id, PGUUID)
        )

    use_hourly_buckets = _use_hourly_buckets(start, end)
    bucket_unit = "hour" if use_hourly_buckets else "day"
    time_bucket = func.date_trunc(bucket_unit, span_time_expr)
    daily_stmt = select(
        time_bucket.label("date"),
        func.coalesce(func.sum(case((~is_embedding_expr, 1), else_=0)), 0).label("requests"),
        func.coalesce(func.sum(case((~is_embedding_expr, tokens_expr), else_=0)), 0).label(
            "tokens"
        ),
        func.coalesce(
            func.sum(
                case((~is_embedding_expr, func.coalesce(effective_cost_expr, 0.0)), else_=0.0)
            ),
            0.0,
        ).label("cost"),
        func.coalesce(func.sum(case((is_embedding_expr, 1), else_=0)), 0).label(
            "embedding_requests"
        ),
        func.coalesce(func.sum(case((is_embedding_expr, tokens_expr), else_=0)), 0).label(
            "embedding_tokens"
        ),
        func.coalesce(
            func.sum(case((is_embedding_expr, func.coalesce(effective_cost_expr, 0.0)), else_=0.0)),
            0.0,
        ).label("embedding_cost"),
        func.coalesce(func.sum(case(((~is_embedding_expr) & is_error_expr, 1), else_=0)), 0).label(
            "errors"
        ),
        func.avg(case((~is_embedding_expr, duration_expr), else_=None)).label("avg_duration"),
    ).select_from(OtelSpan)
    daily_stmt = apply_platform_filters(daily_stmt).where(*filters)
    if platform_filter is not None:
        daily_stmt = daily_stmt.where(platform_filter)
    daily_stmt = daily_stmt.group_by(time_bucket).order_by(time_bucket)

    daily_rows = (await session.execute(daily_stmt)).all()
    daily_data = _build_usage_daily_data(daily_rows, start, end, use_hourly=use_hourly_buckets)

    summary_stmt = select(
        func.coalesce(func.sum(case((~is_embedding_expr, 1), else_=0)), 0).label("total_requests"),
        func.coalesce(func.sum(case((~is_embedding_expr, tokens_expr), else_=0)), 0).label(
            "total_tokens"
        ),
        func.coalesce(
            func.sum(
                case((~is_embedding_expr, func.coalesce(effective_cost_expr, 0.0)), else_=0.0)
            ),
            0.0,
        ).label("total_cost"),
        func.coalesce(func.sum(case((is_embedding_expr, 1), else_=0)), 0).label(
            "total_embedding_requests"
        ),
        func.coalesce(func.sum(case((is_embedding_expr, tokens_expr), else_=0)), 0).label(
            "total_embedding_tokens"
        ),
        func.coalesce(
            func.sum(case((is_embedding_expr, func.coalesce(effective_cost_expr, 0.0)), else_=0.0)),
            0.0,
        ).label("total_embedding_cost"),
        func.avg(case((is_embedding_expr, duration_expr), else_=None)).label(
            "total_embedding_avg_duration"
        ),
        func.coalesce(func.sum(case(((~is_embedding_expr) & is_error_expr, 1), else_=0)), 0).label(
            "total_errors"
        ),
        func.avg(case((~is_embedding_expr, duration_expr), else_=None)).label("avg_duration"),
    ).select_from(OtelSpan)
    summary_stmt = apply_platform_filters(summary_stmt).where(*filters)
    if platform_filter is not None:
        summary_stmt = summary_stmt.where(platform_filter)
    summary_row = (await session.execute(summary_stmt)).one()

    model_stmt = select(
        model_expr.label("model"),
        func.count(OtelSpan.id).label("requests"),
        func.coalesce(func.sum(tokens_expr), 0).label("tokens"),
        func.coalesce(func.sum(func.coalesce(effective_cost_expr, 0.0)), 0.0).label("cost"),
    ).select_from(OtelSpan)
    model_stmt = apply_platform_filters(model_stmt).where(*filters)
    if platform_filter is not None:
        model_stmt = model_stmt.where(platform_filter)
    model_stmt = model_stmt.group_by(model_expr).order_by(func.count(OtelSpan.id).desc())

    model_rows = (await session.execute(model_stmt)).all()

    span_stmt = select(OtelSpan)
    span_stmt = apply_platform_filters(span_stmt).where(*filters)
    if platform_filter is not None:
        span_stmt = span_stmt.where(platform_filter)
    span_stmt = span_stmt.order_by(span_time_expr.desc()).limit(latest_limit)

    spans = (await session.execute(span_stmt)).scalars().all()
    context_map = await _resolve_trace_context_map(session, [span.trace_id for span in spans])

    latest_traces: list[UsageTraceBasicOut] = []
    for span in spans:
        model_value = _format_model_from_span(span)
        if model_value is None:
            continue
        context = context_map.get(span.trace_id)
        latest_traces.append(
            UsageTraceBasicOut(
                created_at=span.start_time or span.span_time or span.created_at,
                model=model_value,
                prompt_tokens=span.input_tokens,
                completion_tokens=span.output_tokens,
                cost=_effective_span_cost(span, model_value),
                duration=(span.duration_ms / 1000.0) if span.duration_ms is not None else None,
                is_error=span.status_code == "ERROR",
                is_public=context.is_public if context is not None else None,
            )
        )

    return UsageOverviewOut(
        summary=UsageSummaryOut(
            total_requests=summary_row.total_requests,
            total_tokens=summary_row.total_tokens,
            total_cost=float(summary_row.total_cost),
            total_embedding_requests=summary_row.total_embedding_requests,
            total_embedding_tokens=summary_row.total_embedding_tokens,
            total_embedding_cost=float(summary_row.total_embedding_cost),
            total_embedding_avg_duration=float(summary_row.total_embedding_avg_duration or 0),
            total_errors=summary_row.total_errors,
            avg_duration=float(summary_row.avg_duration or 0),
        ),
        daily=daily_data,
        models=[
            UsageModelOut(
                model=row.model, requests=row.requests, tokens=row.tokens, cost=float(row.cost)
            )
            for row in model_rows
        ],
        latest_traces=latest_traces,
    )


async def _build_trace_detail(
    trace_id: str, session: SessionDep, current_user: CurrentUser, *, source: TraceAccessSource
) -> TraceDetailOut:
    span_time_expr = func.coalesce(OtelSpan.start_time, OtelSpan.span_time, OtelSpan.created_at)
    spans = (
        (
            await session.execute(
                select(OtelSpan).where(OtelSpan.trace_id == trace_id).order_by(span_time_expr.asc())
            )
        )
        .scalars()
        .all()
    )
    if not spans:
        raise HTTPException(status_code=404, detail="Trace not found")

    context_map = await _resolve_trace_context_map(session, [trace_id])
    context = context_map.get(
        trace_id, _TraceContext(is_public=None, conversation_id=None, conversation=None)
    )
    await _ensure_trace_access(context, current_user, session, source)

    start_times = [span.start_time or span.span_time or span.created_at for span in spans]
    end_times = [span.end_time or span.created_at for span in spans]
    started_at = min(start_times) if start_times else None
    ended_at = max(end_times) if end_times else None

    return TraceDetailOut(
        trace_id=trace_id,
        started_at=started_at,
        duration_ms=_trace_duration_ms(started_at, ended_at),
        span_count=len(spans),
        is_public=context.is_public,
        conversation_id=context.conversation_id,
        spans=[
            TraceSpanOut(
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
            for span in spans
        ],
        overview=build_trace_overview(list(spans)),
    )


@router.get("/trace-index", response_model=PageOut[TraceSummaryOut])
async def get_trace_index(
    session: SessionDep,
    page_params: Annotated[PaginationParams, Depends()],
    current_user: TracesAccessUser,
    ai_only: Annotated[bool, Query()] = False,
    platform: Annotated[str | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> Any:
    if platform not in {None, "both", "internal", "public"}:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")

    span_time_expr = func.coalesce(OtelSpan.start_time, OtelSpan.span_time, OtelSpan.created_at)
    started_at_expr = func.min(span_time_expr).label("started_at")
    ended_at_expr = func.max(func.coalesce(OtelSpan.end_time, OtelSpan.created_at)).label(
        "ended_at"
    )
    latest_start_expr = func.max(span_time_expr).label("latest_start")
    span_count_expr = func.count(OtelSpan.id).label("span_count")

    summary_stmt = select(
        OtelSpan.trace_id, started_at_expr, ended_at_expr, latest_start_expr, span_count_expr
    ).group_by(OtelSpan.trace_id)

    if ai_only:
        ai_trace_ids_stmt = select(func.distinct(OtelSpan.trace_id)).where(OtelSpan.is_ai.is_(True))
        summary_stmt = summary_stmt.where(OtelSpan.trace_id.in_(ai_trace_ids_stmt))
    if start is not None:
        summary_stmt = summary_stmt.having(started_at_expr >= start)
    if end is not None:
        summary_stmt = summary_stmt.having(started_at_expr <= end)

    summary_rows = (await session.execute(summary_stmt)).all()
    trace_ids = [row.trace_id for row in summary_rows]
    latest_start_by_trace = {row.trace_id: row.latest_start for row in summary_rows}
    context_map = await _resolve_trace_context_map(session, trace_ids)
    meta_map = await _build_trace_meta_map(session, trace_ids)

    items: list[TraceSummaryOut] = []
    for row in summary_rows:
        context = context_map.get(
            row.trace_id, _TraceContext(is_public=None, conversation_id=None, conversation=None)
        )
        try:
            await _ensure_trace_access(context, current_user, session, TraceAccessSource.PAGE)
        except HTTPException:
            continue

        if platform == "public" and context.is_public is not True:
            continue
        if platform == "internal" and context.is_public is not False:
            continue

        meta = meta_map.get(row.trace_id, {})
        items.append(
            TraceSummaryOut(
                trace_id=row.trace_id,
                started_at=row.started_at,
                duration_ms=_trace_duration_ms(row.started_at, row.ended_at),
                span_count=row.span_count,
                root_span_name=meta.get("root_span_name"),
                model=meta.get("model"),
                is_error=bool(meta.get("is_error", False)),
                is_public=context.is_public,
                conversation_id=context.conversation_id,
                is_ai=bool(meta.get("is_ai", False)),
            )
        )

    sort_by = page_params.sort_by
    if sort_by == "duration_ms":
        items.sort(key=lambda item: item.duration_ms or 0.0, reverse=page_params.descending)
    elif sort_by == "span_count":
        items.sort(key=lambda item: item.span_count, reverse=page_params.descending)
    elif sort_by == "latest_start":
        items.sort(
            key=lambda item: latest_start_by_trace.get(item.trace_id) or _EARLIEST_TIME,
            reverse=page_params.descending,
        )
    else:
        items.sort(
            key=lambda item: item.started_at or _EARLIEST_TIME, reverse=page_params.descending
        )

    total = len(items)
    end_offset = page_params.offset + page_params.limit if page_params.limit > 0 else None
    return PageOut[TraceSummaryOut](items=items[page_params.offset : end_offset], total=total)


@router.get("/trace/{trace_id}", response_model=TraceDetailOut)
async def get_trace_detail(
    trace_id: str, session: SessionDep, current_user: TracesAccessUser
) -> Any:
    return await _build_trace_detail(trace_id, session, current_user, source=TraceAccessSource.PAGE)


@router.get("/trace-by-message/{message_id}", response_model=TraceDetailOut)
async def get_trace_detail_by_message_id(
    message_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    source: Annotated[TraceAccessSource, Query()] = TraceAccessSource.PAGE,
) -> Any:
    span_time_expr = func.coalesce(OtelSpan.start_time, OtelSpan.span_time, OtelSpan.created_at)
    row = (
        await session.execute(
            select(OtelSpan.trace_id)
            .where(OtelSpan.message_id == message_id)
            .order_by(span_time_expr.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found for message")

    return await _build_trace_detail(row.trace_id, session, current_user, source=source)
