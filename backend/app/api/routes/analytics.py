from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from math import ceil, floor, log10
from typing import TYPE_CHECKING, Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Date as SqlDate
from sqlalchemy import Float, Integer, case, cast, false, func, or_, select, true
from sqlalchemy.sql import ColumnElement

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.routes.analytics_time import (
    TimeGranularity,
    build_time_series_boundaries,
    iter_time_bucket_boundaries,
    select_time_granularity,
)
from app.api.routes.owner_group_filter import (
    OwnerGroup,
    apply_aggregate_owner_filter,
    build_owner_group_filter,
    validate_exclusive_user_filters,
)
from app.compliance.scheduled import SCHEDULER_USER_EMAIL
from app.core.rbac import (
    PermissionKey,
    get_allowed_chat_owner_group_slugs,
    get_effective_permission_map,
)
from app.models import (
    AssistantMessageMetadata,
    ChatGenerationAttempt,
    Conversation,
    Message,
    MessageFeedback,
    PublicChatContact,
    Rating,
    RbacGroup,
    User,
)
from app.utils import current_time_utc

if TYPE_CHECKING:
    from collections.abc import Sequence

router = APIRouter(prefix="/analytics", tags=["analytics"])

GENERATION_ATTEMPT_STALE_AFTER = timedelta(minutes=15)
RESPONSE_HISTOGRAM_TARGET_BUCKETS = 12
NICE_HISTOGRAM_MULTIPLIERS = (1.0, 2.0, 2.5, 5.0, 10.0)

AnalyticsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_ANALYTICS))
]
AdoptionAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_ADOPTION))
]
PublicAnalyticsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_PUBLIC_ANALYTICS))
]


class ConversationAnalyticsTimeSeriesPointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    conversations: int
    turns: int


class ConversationAnalyticsBucketOut(BaseModel):
    label: str
    conversations: int
    min_turns: int
    max_turns: int | None
    overflow: bool


class ConversationAnalyticsHourlyOut(BaseModel):
    hour: int
    turns: int


class ConversationAnalyticsStatsOut(BaseModel):
    min: float | None
    p50: float | None
    avg: float | None
    p75: float | None
    p90: float | None
    p95: float | None
    p99: float | None
    max: float | None


class ConversationAnalyticsSummaryOut(BaseModel):
    total_conversations: int
    total_turns: int
    avg_turns_per_conversation: float
    time_granularity: TimeGranularity
    series: list[ConversationAnalyticsTimeSeriesPointOut]
    length_buckets: list[ConversationAnalyticsBucketOut]
    hourly_activity: list[ConversationAnalyticsHourlyOut]
    length_stats: ConversationAnalyticsStatsOut | None


class QualitySummaryMetricsOut(BaseModel):
    assistant_responses: int
    retry_observed_responses: int
    retry_affected_responses: int
    retry_attempts: int
    blocked_responses: int
    ratings: int
    thumbs_up: int
    thumbs_down: int
    retry_affected_rate: float | None
    blocked_rate: float | None
    positive_rate: float | None
    response_samples: int
    median_response_seconds: float | None
    p95_response_seconds: float | None
    failed_generations: int
    tracked_generation_attempts: int
    generation_failure_rate: float | None


class QualitySeriesPointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    retry_attempts: int
    blocked_responses: int
    thumbs_up: int
    thumbs_down: int


class QualityResponsivenessPointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    samples: int
    median_seconds: float | None
    p95_seconds: float | None


class QualityFailurePointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    tracked_attempts: int
    failed_generations: int | None


class QualityResponseTimeBucketOut(BaseModel):
    label: str
    lower_bound: float
    upper_bound: float | None
    count: int
    overflow: bool


class QualitySummaryOut(BaseModel):
    summary: QualitySummaryMetricsOut
    time_granularity: TimeGranularity
    series: list[QualitySeriesPointOut]
    responsiveness_series: list[QualityResponsivenessPointOut]
    failure_series: list[QualityFailurePointOut]
    response_time_buckets: list[QualityResponseTimeBucketOut]


class AdoptionTimeSeriesPointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    new_accounts: int
    active_users: int
    monthly_active_users: int


class AdoptionSummaryOut(BaseModel):
    new_accounts: int
    active_new_accounts: int
    latest_daily_active_users: int
    monthly_active_users: int
    average_daily_active_users: float
    stickiness: float
    time_granularity: TimeGranularity
    series: list[AdoptionTimeSeriesPointOut]


class PublicAnalyticsTimeSeriesPointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    leads: int


class PublicAnalyticsDepthBucketOut(BaseModel):
    label: str
    conversations: int
    overflow: bool


class PublicAnalyticsSummaryOut(BaseModel):
    total_leads: int
    time_granularity: TimeGranularity
    series: list[PublicAnalyticsTimeSeriesPointOut]
    depth_buckets: list[PublicAnalyticsDepthBucketOut]


def _build_conversation_series(
    conversation_rows: Sequence[Any],
    turn_rows: Sequence[Any],
    start: datetime | None,
    end: datetime | None,
    *,
    granularity: TimeGranularity,
) -> list[ConversationAnalyticsTimeSeriesPointOut]:
    conversations_by_date = {row.date: row.conversations for row in conversation_rows}
    turns_by_date = {row.date: row.turns for row in turn_rows}
    boundaries = build_time_series_boundaries(
        conversations_by_date.keys() | turns_by_date.keys(), start, end, granularity
    )
    return [
        ConversationAnalyticsTimeSeriesPointOut(
            bucket_start=boundary.start,
            bucket_end=boundary.end,
            conversations=int(conversations_by_date.get(boundary.key, 0)),
            turns=int(turns_by_date.get(boundary.key, 0)),
        )
        for boundary in boundaries
    ]


def _build_public_analytics_series(
    rows: Sequence[Any],
    start: datetime | None,
    end: datetime | None,
    *,
    granularity: TimeGranularity,
) -> list[PublicAnalyticsTimeSeriesPointOut]:
    row_map = {row.date: row for row in rows}
    boundaries = build_time_series_boundaries(set(row_map), start, end, granularity)
    return [
        PublicAnalyticsTimeSeriesPointOut(
            bucket_start=boundary.start,
            bucket_end=boundary.end,
            leads=int(row_map[boundary.key].leads) if boundary.key in row_map else 0,
        )
        for boundary in boundaries
    ]


def _quality_metrics(
    *,
    assistant_responses: int,
    retry_observed_responses: int,
    retry_affected_responses: int,
    retry_attempts: int,
    blocked_responses: int,
    ratings: int,
    thumbs_up: int,
    thumbs_down: int,
    response_samples: int = 0,
    median_response_seconds: float | None = None,
    p95_response_seconds: float | None = None,
    failed_generations: int = 0,
    tracked_generation_attempts: int = 0,
) -> QualitySummaryMetricsOut:
    return QualitySummaryMetricsOut(
        assistant_responses=assistant_responses,
        retry_observed_responses=retry_observed_responses,
        retry_affected_responses=retry_affected_responses,
        retry_attempts=retry_attempts,
        blocked_responses=blocked_responses,
        ratings=ratings,
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down,
        retry_affected_rate=(
            retry_affected_responses / retry_observed_responses
            if retry_observed_responses
            else None
        ),
        blocked_rate=(blocked_responses / assistant_responses if assistant_responses else None),
        positive_rate=thumbs_up / ratings if ratings else None,
        response_samples=response_samples,
        median_response_seconds=median_response_seconds,
        p95_response_seconds=p95_response_seconds,
        failed_generations=failed_generations,
        tracked_generation_attempts=tracked_generation_attempts,
        generation_failure_rate=(
            failed_generations / tracked_generation_attempts
            if tracked_generation_attempts
            else None
        ),
    )


def _build_quality_series(
    message_rows: Sequence[Any],
    feedback_rows: Sequence[Any],
    *,
    start: datetime | None,
    end: datetime | None,
    granularity: TimeGranularity,
) -> list[QualitySeriesPointOut]:
    messages_by_date = {row.date: row for row in message_rows}
    feedback_by_date = {row.date: row for row in feedback_rows}
    boundaries = build_time_series_boundaries(
        messages_by_date.keys() | feedback_by_date.keys(), start, end, granularity
    )

    result: list[QualitySeriesPointOut] = []
    for boundary in boundaries:
        message_row = messages_by_date.get(boundary.key)
        feedback_row = feedback_by_date.get(boundary.key)
        result.append(
            QualitySeriesPointOut(
                bucket_start=boundary.start,
                bucket_end=boundary.end,
                retry_attempts=int(message_row.retry_attempts if message_row else 0),
                blocked_responses=int(message_row.blocked_responses if message_row else 0),
                thumbs_up=int(feedback_row.thumbs_up if feedback_row else 0),
                thumbs_down=int(feedback_row.thumbs_down if feedback_row else 0),
            )
        )
    return result


def _summarize_quality_rows(
    message_rows: Sequence[Any],
    feedback_rows: Sequence[Any],
    *,
    responsiveness_row: Any,
    attempt_rows: Sequence[Any],
) -> QualitySummaryMetricsOut:
    def total(rows: Sequence[Any], field: str) -> int:
        return sum(int(getattr(row, field) or 0) for row in rows)

    response_samples = int(responsiveness_row.samples or 0)
    return _quality_metrics(
        assistant_responses=total(message_rows, "assistant_responses"),
        retry_observed_responses=total(message_rows, "retry_observed_responses"),
        retry_affected_responses=total(message_rows, "retry_affected_responses"),
        retry_attempts=total(message_rows, "retry_attempts"),
        blocked_responses=total(message_rows, "blocked_responses"),
        ratings=total(feedback_rows, "ratings"),
        thumbs_up=total(feedback_rows, "thumbs_up"),
        thumbs_down=total(feedback_rows, "thumbs_down"),
        response_samples=response_samples,
        median_response_seconds=(
            float(responsiveness_row.median_seconds) if response_samples else None
        ),
        p95_response_seconds=(float(responsiveness_row.p95_seconds) if response_samples else None),
        failed_generations=total(attempt_rows, "failed_generations"),
        tracked_generation_attempts=total(attempt_rows, "tracked_attempts"),
    )


def _build_exact_count_distribution(
    frequencies: dict[int, int],
) -> list[tuple[str, int, bool, int, int | None]]:
    total = sum(frequencies.values())
    if total == 0:
        return []

    percentile_position = ceil(total * 0.99)
    cumulative = 0
    p99 = 0
    for value, count in sorted(frequencies.items()):
        cumulative += count
        if cumulative >= percentile_position:
            p99 = value
            break

    buckets: list[tuple[str, int, bool, int, int | None]] = [
        (str(value), frequencies.get(value, 0), False, value, value) for value in range(p99 + 1)
    ]
    buckets.append(
        (
            f">{p99}",
            sum(count for value, count in frequencies.items() if value > p99),
            True,
            p99 + 1,
            None,
        )
    )
    return buckets


def _nice_histogram_step(p99: float) -> float:
    if p99 <= 0:
        return 1.0
    raw_step = p99 / RESPONSE_HISTOGRAM_TARGET_BUCKETS
    magnitude = 10 ** floor(log10(raw_step))
    normalized = raw_step / magnitude
    nice = next(multiplier for multiplier in NICE_HISTOGRAM_MULTIPLIERS if normalized <= multiplier)
    return nice * magnitude


def _format_duration_boundary(value: float) -> str:
    return f"{value:g}s"


def _build_responsiveness_series(
    rows: Sequence[Any],
    *,
    start: datetime | None,
    end: datetime | None,
    granularity: TimeGranularity,
) -> list[QualityResponsivenessPointOut]:
    row_map = {row.date: row for row in rows}
    boundaries = build_time_series_boundaries(set(row_map), start, end, granularity)
    return [
        QualityResponsivenessPointOut(
            bucket_start=boundary.start,
            bucket_end=boundary.end,
            samples=(int(row_map[boundary.key].samples) if boundary.key in row_map else 0),
            median_seconds=(
                float(row_map[boundary.key].median_seconds)
                if boundary.key in row_map and row_map[boundary.key].median_seconds is not None
                else None
            ),
            p95_seconds=(
                float(row_map[boundary.key].p95_seconds)
                if boundary.key in row_map and row_map[boundary.key].p95_seconds is not None
                else None
            ),
        )
        for boundary in boundaries
    ]


def _build_failure_series(
    rows: Sequence[Any],
    *,
    start: datetime | None,
    end: datetime | None,
    granularity: TimeGranularity,
) -> list[QualityFailurePointOut]:
    row_map = {row.date: row for row in rows}
    boundaries = build_time_series_boundaries(set(row_map), start, end, granularity)
    result: list[QualityFailurePointOut] = []
    for boundary in boundaries:
        row = row_map.get(boundary.key)
        tracked_attempts = int(row.tracked_attempts) if row else 0
        result.append(
            QualityFailurePointOut(
                bucket_start=boundary.start,
                bucket_end=boundary.end,
                tracked_attempts=tracked_attempts,
                failed_generations=(
                    int(row.failed_generations) if row is not None and tracked_attempts else None
                ),
            )
        )
    return result


def _build_response_time_buckets(
    count_rows: Sequence[Any], *, step: float, normal_bucket_count: int
) -> list[QualityResponseTimeBucketOut]:
    counts = {int(row.bucket_index): int(row.count) for row in count_rows}
    buckets = [
        QualityResponseTimeBucketOut(
            label=(
                f"{_format_duration_boundary(index * step)}-"
                f"<{_format_duration_boundary((index + 1) * step)}"
            ),
            lower_bound=index * step,
            upper_bound=(index + 1) * step,
            count=counts.get(index, 0),
            overflow=False,
        )
        for index in range(normal_bucket_count)
    ]
    overflow_start = normal_bucket_count * step
    buckets.append(
        QualityResponseTimeBucketOut(
            label=f"≥{_format_duration_boundary(overflow_start)}",
            lower_bound=overflow_start,
            upper_bound=None,
            count=counts.get(normal_bucket_count, 0),
            overflow=True,
        )
    )
    return buckets


def _turn_count_subquery(message_time_filters: list[Any]) -> Any:
    turn_count_stmt = select(
        Message.conversation_id.label("conversation_id"), func.count(Message.id).label("turn_count")
    ).where(Message.role == "user")
    if message_time_filters:
        turn_count_stmt = turn_count_stmt.where(*message_time_filters)
    return turn_count_stmt.group_by(Message.conversation_id).subquery()


def _message_count_subquery(message_time_filters: list[Any]) -> Any:
    message_count_stmt = select(
        Message.conversation_id.label("conversation_id"),
        func.count(Message.id).label("message_count"),
    )
    if message_time_filters:
        message_count_stmt = message_count_stmt.where(*message_time_filters)
    return message_count_stmt.group_by(Message.conversation_id).subquery()


def _conversation_time_filters(
    start: datetime | None, end: datetime | None
) -> tuple[list[Any], list[Any]]:
    conversation_time_filters: list[Any] = []
    message_time_filters: list[Any] = []
    if start is not None:
        conversation_time_filters.append(Conversation.created_at >= start)
        message_time_filters.append(Message.created_at >= start)
    if end is not None:
        conversation_time_filters.append(Conversation.created_at <= end)
        message_time_filters.append(Message.created_at <= end)
    return conversation_time_filters, message_time_filters


def _conversation_length_stats(row: Any) -> ConversationAnalyticsStatsOut | None:
    if row.min_turns is None:
        return None
    return ConversationAnalyticsStatsOut(
        min=float(row.min_turns),
        p50=float(row.p50 or 0),
        avg=float(row.avg_turns_per_conversation or 0),
        p75=float(row.p75 or 0),
        p90=float(row.p90 or 0),
        p95=float(row.p95 or 0),
        p99=float(row.p99 or 0),
        max=float(row.max_turns or 0),
    )


@router.get("/conversations", response_model=ConversationAnalyticsSummaryOut)
async def get_conversation_analytics_summary(
    session: SessionDep,
    current_user: AnalyticsAccessUser,
    platform: Annotated[str | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    browser_time_zone: Annotated[str, Query()] = "UTC",
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
) -> Any:
    if platform not in {None, "both", "public", "internal"}:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")
    validate_exclusive_user_filters(user_email=user_email, user_group=user_group)
    permission_map = (
        await get_effective_permission_map(session, current_user)
        if user_group is not None or (user_email is not None and user_email.strip() != "")
        else {}
    )

    platform_value = "both" if platform in (None, "both") else platform
    platform_conditions: list[Any] = []
    if platform_value in {"both", "public"}:
        platform_conditions.append(Conversation.is_public.is_(True))
    if platform_value in {"both", "internal"}:
        platform_conditions.append(Conversation.is_public.is_(False))
    platform_filter = or_(*platform_conditions)

    def apply_user_filters(statement: Any) -> Any:
        return apply_aggregate_owner_filter(
            statement,
            current_user=current_user,
            permission_map=permission_map,
            user_email=user_email,
            user_group=user_group,
            include_internal=platform_value != "public",
        )

    conversation_time_filters, message_time_filters = _conversation_time_filters(start, end)
    turn_count_subquery = _turn_count_subquery(message_time_filters)
    turn_count = func.coalesce(turn_count_subquery.c.turn_count, 0)

    time_granularity = select_time_granularity(start, end)
    conversation_bucket = func.date_trunc(time_granularity.value, Conversation.created_at, "UTC")
    turn_bucket = func.date_trunc(time_granularity.value, Message.created_at, "UTC")

    conversation_daily_stmt = (
        select(
            conversation_bucket.label("date"), func.count(Conversation.id).label("conversations")
        )
        .where(Conversation.kind == "chat", platform_filter, *conversation_time_filters)
        .group_by(conversation_bucket)
        .order_by(conversation_bucket)
    )
    conversation_daily_stmt = apply_user_filters(conversation_daily_stmt)
    conversation_daily_rows = (await session.execute(conversation_daily_stmt)).all()

    turn_daily_stmt = (
        select(turn_bucket.label("date"), func.count(Message.id).label("turns"))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.role == "user",
            Conversation.kind == "chat",
            platform_filter,
            *conversation_time_filters,
            *message_time_filters,
        )
        .group_by(turn_bucket)
        .order_by(turn_bucket)
    )
    turn_daily_stmt = apply_user_filters(turn_daily_stmt)
    turn_daily_rows = (await session.execute(turn_daily_stmt)).all()
    series = _build_conversation_series(
        conversation_daily_rows, turn_daily_rows, start, end, granularity=time_granularity
    )

    turn_stats_stmt = (
        select(
            func.count(Conversation.id).label("total_conversations"),
            func.coalesce(func.sum(turn_count), 0).label("total_turns"),
            func.coalesce(func.avg(turn_count), 0).label("avg_turns_per_conversation"),
            func.min(turn_count).label("min_turns"),
            func.max(turn_count).label("max_turns"),
            func.percentile_cont(0.5).within_group(turn_count).label("p50"),
            func.percentile_cont(0.75).within_group(turn_count).label("p75"),
            func.percentile_cont(0.9).within_group(turn_count).label("p90"),
            func.percentile_cont(0.95).within_group(turn_count).label("p95"),
            func.percentile_disc(0.99).within_group(turn_count).label("p99"),
        )
        .outerjoin(turn_count_subquery, Conversation.id == turn_count_subquery.c.conversation_id)
        .where(Conversation.kind == "chat", platform_filter, *conversation_time_filters)
    )
    turn_stats_stmt = apply_user_filters(turn_stats_stmt)
    turn_stats = (await session.execute(turn_stats_stmt)).one()

    turn_distribution_stmt = (
        select(turn_count.label("value"), func.count(Conversation.id).label("conversations"))
        .outerjoin(turn_count_subquery, Conversation.id == turn_count_subquery.c.conversation_id)
        .where(Conversation.kind == "chat", platform_filter, *conversation_time_filters)
        .group_by(turn_count)
        .order_by(turn_count)
    )
    turn_distribution_stmt = apply_user_filters(turn_distribution_stmt)
    turn_distribution_rows = (await session.execute(turn_distribution_stmt)).all()

    timezone = _resolve_time_zone(browser_time_zone)
    hour_bucket = func.date_part("hour", func.timezone(timezone.key, Message.created_at))
    hourly_stmt = (
        select(func.cast(hour_bucket, Integer).label("hour"), func.count(Message.id).label("turns"))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.role == "user",
            Conversation.kind == "chat",
            platform_filter,
            *conversation_time_filters,
            *message_time_filters,
        )
        .group_by(hour_bucket)
        .order_by(hour_bucket)
    )
    hourly_stmt = apply_user_filters(hourly_stmt)
    hourly_rows = {row.hour: row.turns for row in await session.execute(hourly_stmt)}
    length_distribution = _build_exact_count_distribution(
        {int(row.value): int(row.conversations) for row in turn_distribution_rows}
    )

    return ConversationAnalyticsSummaryOut(
        total_conversations=turn_stats.total_conversations,
        total_turns=turn_stats.total_turns,
        avg_turns_per_conversation=float(turn_stats.avg_turns_per_conversation),
        time_granularity=time_granularity,
        series=series,
        length_buckets=[
            ConversationAnalyticsBucketOut(
                label=label,
                conversations=conversations,
                min_turns=min_turns,
                max_turns=max_turns,
                overflow=overflow,
            )
            for label, conversations, overflow, min_turns, max_turns in length_distribution
        ],
        hourly_activity=[
            ConversationAnalyticsHourlyOut(hour=hour, turns=hourly_rows.get(hour, 0))
            for hour in range(24)
        ],
        length_stats=_conversation_length_stats(turn_stats),
    )


@router.get("/quality", response_model=QualitySummaryOut)
async def get_quality_summary(
    session: SessionDep,
    current_user: AnalyticsAccessUser,
    platform: Annotated[str | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
) -> QualitySummaryOut:
    if platform not in {None, "both", "public", "internal"}:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")
    validate_exclusive_user_filters(user_email=user_email, user_group=user_group)
    permission_map = (
        await get_effective_permission_map(session, current_user)
        if user_group is not None or (user_email is not None and user_email.strip() != "")
        else {}
    )

    platform_value = "both" if platform in (None, "both") else platform
    platform_conditions: list[Any] = []
    if platform_value in {"both", "public"}:
        platform_conditions.append(Conversation.is_public.is_(True))
    if platform_value in {"both", "internal"}:
        platform_conditions.append(Conversation.is_public.is_(False))

    eligible_message_scope_stmt = (
        select(
            Message.id.label("message_id"),
            Message.created_at.label("created_at"),
            Message.guardrails_blocked.label("guardrails_blocked"),
            AssistantMessageMetadata.guardrail_retry_count.label("guardrail_retry_count"),
            AssistantMessageMetadata.total_time.label("total_time"),
        )
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(AssistantMessageMetadata, AssistantMessageMetadata.message_id == Message.id)
        .where(
            Message.role == "assistant",
            Conversation.kind == "chat",
            or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"),
            or_(*platform_conditions),
        )
    )
    eligible_message_scope_stmt = apply_aggregate_owner_filter(
        eligible_message_scope_stmt,
        current_user=current_user,
        permission_map=permission_map,
        user_email=user_email,
        user_group=user_group,
        include_internal=platform_value != "public",
    )
    feedback_message_scope = eligible_message_scope_stmt.subquery()

    message_scope_stmt = eligible_message_scope_stmt
    if start is not None:
        message_scope_stmt = message_scope_stmt.where(Message.created_at >= start)
    if end is not None:
        message_scope_stmt = message_scope_stmt.where(Message.created_at <= end)
    message_scope = message_scope_stmt.subquery()

    time_granularity = select_time_granularity(start, end)
    message_bucket = func.date_trunc(time_granularity.value, message_scope.c.created_at, "UTC")
    response_seconds: ColumnElement[float] = cast(message_scope.c.total_time, Float)
    response_filter = message_scope.c.total_time.is_not(None) & (response_seconds >= 0)
    message_series_stmt = (
        select(
            message_bucket.label("date"),
            func.count(message_scope.c.message_id).label("assistant_responses"),
            func.count(message_scope.c.guardrail_retry_count).label("retry_observed_responses"),
            func.count()
            .filter(message_scope.c.guardrail_retry_count > 0)
            .label("retry_affected_responses"),
            func.coalesce(func.sum(message_scope.c.guardrail_retry_count), 0).label(
                "retry_attempts"
            ),
            func.coalesce(
                func.sum(case((message_scope.c.guardrails_blocked.is_(True), 1), else_=0)), 0
            ).label("blocked_responses"),
            func.count().filter(response_filter).label("samples"),
            func.percentile_cont(0.5)
            .within_group(response_seconds)
            .filter(response_filter)
            .label("median_seconds"),
            func.percentile_cont(0.95)
            .within_group(response_seconds)
            .filter(response_filter)
            .label("p95_seconds"),
        )
        .select_from(message_scope)
        .group_by(message_bucket)
        .order_by(message_bucket)
    )
    message_rows = (await session.execute(message_series_stmt)).all()

    feedback_bucket = func.date_trunc(time_granularity.value, MessageFeedback.created_at, "UTC")
    feedback_series_stmt = (
        select(
            feedback_bucket.label("date"),
            func.count(MessageFeedback.id).label("ratings"),
            func.count().filter(MessageFeedback.rating == Rating.THUMBS_UP).label("thumbs_up"),
            func.count().filter(MessageFeedback.rating == Rating.THUMBS_DOWN).label("thumbs_down"),
        )
        .select_from(MessageFeedback)
        .join(
            feedback_message_scope,
            feedback_message_scope.c.message_id == MessageFeedback.message_id,
        )
    )
    if start is not None:
        feedback_series_stmt = feedback_series_stmt.where(MessageFeedback.created_at >= start)
    if end is not None:
        feedback_series_stmt = feedback_series_stmt.where(MessageFeedback.created_at <= end)
    feedback_series_stmt = feedback_series_stmt.group_by(feedback_bucket).order_by(feedback_bucket)
    feedback_rows = (await session.execute(feedback_series_stmt)).all()

    responsiveness_summary_stmt = select(
        func.count().filter(response_filter).label("samples"),
        func.percentile_cont(0.5)
        .within_group(response_seconds)
        .filter(response_filter)
        .label("median_seconds"),
        func.percentile_cont(0.95)
        .within_group(response_seconds)
        .filter(response_filter)
        .label("p95_seconds"),
        func.percentile_cont(0.99)
        .within_group(response_seconds)
        .filter(response_filter)
        .label("p99_seconds"),
    ).select_from(message_scope)
    responsiveness_summary = (await session.execute(responsiveness_summary_stmt)).one()

    response_time_buckets: list[QualityResponseTimeBucketOut] = []
    if responsiveness_summary.samples:
        histogram_step = _nice_histogram_step(float(responsiveness_summary.p99_seconds or 0))
        p99_seconds = float(responsiveness_summary.p99_seconds or 0)
        normal_bucket_count = max(1, floor(p99_seconds / histogram_step) + 1)
        normal_upper_bound = normal_bucket_count * histogram_step
        if normal_upper_bound <= p99_seconds:
            normal_bucket_count += 1
            normal_upper_bound = normal_bucket_count * histogram_step
        histogram_index = case(
            (
                response_seconds < normal_upper_bound,
                cast(func.floor(response_seconds / histogram_step), Integer),
            ),
            else_=normal_bucket_count,
        )
        histogram_stmt = (
            select(histogram_index.label("bucket_index"), func.count().label("count"))
            .select_from(message_scope)
            .where(response_filter)
            .group_by(histogram_index)
            .order_by(histogram_index)
        )
        histogram_rows = (await session.execute(histogram_stmt)).all()
        response_time_buckets = _build_response_time_buckets(
            histogram_rows, step=histogram_step, normal_bucket_count=normal_bucket_count
        )

    attempt_rows: Sequence[Any] = []
    if platform_value != "public":
        attempt_scope_stmt = (
            select(
                ChatGenerationAttempt.created_at.label("created_at"),
                ChatGenerationAttempt.status.label("status"),
            )
            .select_from(ChatGenerationAttempt)
            .join(Conversation, Conversation.id == ChatGenerationAttempt.conversation_id)
            .where(
                Conversation.is_public.is_(False),
                Conversation.kind == "chat",
                or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"),
            )
        )
        if start is not None:
            attempt_scope_stmt = attempt_scope_stmt.where(ChatGenerationAttempt.created_at >= start)
        if end is not None:
            attempt_scope_stmt = attempt_scope_stmt.where(ChatGenerationAttempt.created_at <= end)
        attempt_scope_stmt = apply_aggregate_owner_filter(
            attempt_scope_stmt,
            current_user=current_user,
            permission_map=permission_map,
            user_email=user_email,
            user_group=user_group,
            include_internal=True,
        )
        attempt_scope = attempt_scope_stmt.subquery()
        stale_cutoff = current_time_utc() - GENERATION_ATTEMPT_STALE_AFTER
        stale_pending = (attempt_scope.c.status == "pending") & (
            attempt_scope.c.created_at <= stale_cutoff
        )
        failed_attempt = (attempt_scope.c.status == "failed") | stale_pending
        tracked_attempt = attempt_scope.c.status.in_(("completed", "failed")) | stale_pending
        attempt_bucket = func.date_trunc(time_granularity.value, attempt_scope.c.created_at, "UTC")
        attempt_series_stmt = (
            select(
                attempt_bucket.label("date"),
                func.count().filter(tracked_attempt).label("tracked_attempts"),
                func.count().filter(failed_attempt).label("failed_generations"),
            )
            .select_from(attempt_scope)
            .group_by(attempt_bucket)
            .order_by(attempt_bucket)
        )
        attempt_rows = (await session.execute(attempt_series_stmt)).all()

    return QualitySummaryOut(
        summary=_summarize_quality_rows(
            message_rows,
            feedback_rows,
            responsiveness_row=responsiveness_summary,
            attempt_rows=attempt_rows,
        ),
        time_granularity=time_granularity,
        series=_build_quality_series(
            message_rows, feedback_rows, start=start, end=end, granularity=time_granularity
        ),
        responsiveness_series=_build_responsiveness_series(
            message_rows, start=start, end=end, granularity=time_granularity
        ),
        failure_series=_build_failure_series(
            attempt_rows, start=start, end=end, granularity=time_granularity
        ),
        response_time_buckets=response_time_buckets,
    )


def _resolve_time_zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ValueError, ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _apply_adoption_account_filter(
    base_stmt: Any,
    *,
    current_user: User,
    permission_map: dict[PermissionKey, bool],
    user_email: str | None,
    user_group: OwnerGroup | None,
) -> Any:
    normalized_email = user_email.strip() if user_email is not None else ""
    statement = base_stmt.join(RbacGroup, User.group_id == RbacGroup.id)
    if normalized_email != "":
        visibility_conditions: list[Any] = []
        if permission_map.get(PermissionKey.CHATS_VIEW_OWN, False):
            visibility_conditions.append(User.id == current_user.id)
        allowed_group_slugs = get_allowed_chat_owner_group_slugs(permission_map)
        if allowed_group_slugs:
            visibility_conditions.append(RbacGroup.slug.in_(sorted(allowed_group_slugs)))
        statement = statement.where(
            User.email == normalized_email,
            or_(*visibility_conditions) if visibility_conditions else false(),
        )
    return build_owner_group_filter(
        statement, owner_group=user_group, include_internal=True, permission_map=permission_map
    )


@router.get("/adoption", response_model=AdoptionSummaryOut)
async def get_adoption_summary(
    session: SessionDep,
    current_user: AdoptionAccessUser,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    browser_time_zone: Annotated[str, Query()] = "UTC",
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
) -> AdoptionSummaryOut:
    end_value = end or current_time_utc()
    if start is not None and start > end_value:
        raise HTTPException(status_code=400, detail="Invalid time range")
    validate_exclusive_user_filters(user_email=user_email, user_group=user_group)
    permission_map = (
        await get_effective_permission_map(session, current_user)
        if user_group is not None or (user_email is not None and user_email.strip() != "")
        else {}
    )

    first_account_stmt = select(func.min(User.created_at)).where(
        User.created_at <= end_value, User.email != SCHEDULER_USER_EMAIL
    )
    first_account_stmt = _apply_adoption_account_filter(
        first_account_stmt,
        current_user=current_user,
        permission_map=permission_map,
        user_email=user_email,
        user_group=user_group,
    )
    first_account_at = await session.scalar(first_account_stmt)

    timezone = _resolve_time_zone(browser_time_zone)
    activity_day = cast(func.timezone(timezone.key, Message.created_at), SqlDate)
    selected_activity = Message.created_at >= start if start is not None else true()
    activity_stmt = (
        select(
            activity_day.label("date"),
            Conversation.user_id.label("user_id"),
            func.bool_or(selected_activity).label("selected_activity"),
        )
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.role == "user",
            Conversation.is_public.is_(False),
            Conversation.kind == "chat",
            or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"),
            Conversation.user_id.is_not(None),
            Message.created_at <= end_value,
        )
        .group_by(activity_day, Conversation.user_id)
    )
    if start is not None:
        first_display_day = start.astimezone(timezone).date()
        lookback_start = datetime.combine(
            first_display_day - timedelta(days=29), time.min, timezone
        )
        activity_stmt = activity_stmt.where(Message.created_at >= lookback_start)
    activity_stmt = apply_aggregate_owner_filter(
        activity_stmt,
        current_user=current_user,
        permission_map=permission_map,
        user_email=user_email,
        user_group=user_group,
        include_internal=True,
    ).where(User.email != SCHEDULER_USER_EMAIL)
    activity_rows = (await session.execute(activity_stmt)).all()

    active_by_day: dict[date, set[str]] = {}
    active_account_ids: set[str] = set()
    selected_count_by_day: dict[date, int] = {}
    for row in activity_rows:
        user_id = str(row.user_id)
        active_by_day.setdefault(row.date, set()).add(user_id)
        if row.selected_activity:
            active_account_ids.add(user_id)
            selected_count_by_day[row.date] = selected_count_by_day.get(row.date, 0) + 1

    display_end = end_value.astimezone(timezone).date()
    first_account_day = (
        first_account_at.astimezone(timezone).date()
        if first_account_at is not None
        else display_end
    )
    display_start = (
        start.astimezone(timezone).date()
        if start is not None
        else min(min(active_by_day, default=display_end), first_account_day)
    )
    selected_days = (display_end - display_start).days + 1
    latest_daily_active_users = selected_count_by_day.get(display_end, 0)
    latest_monthly_users: set[str] = set()
    for offset in range(30):
        latest_monthly_users.update(active_by_day.get(display_end - timedelta(days=offset), ()))
    monthly_active_users = len(latest_monthly_users)

    series_start = start or datetime.combine(display_start, time.min, timezone).astimezone(UTC)
    time_granularity = select_time_granularity(series_start, end_value)
    if time_granularity == TimeGranularity.HOUR:
        activity_bucket = func.date_trunc("hour", Message.created_at, "UTC")
        series_query_start = datetime.combine(
            series_start.astimezone(timezone).date(), time.min, timezone
        ).astimezone(UTC)
    else:
        activity_bucket = func.date_trunc(
            time_granularity.value, func.timezone(timezone.key, Message.created_at)
        )
        series_query_start = series_start
    series_stmt = (
        select(
            activity_bucket.label("date"),
            Conversation.user_id.label("user_id"),
            func.bool_or(Message.created_at >= series_start).label("selected_activity"),
        )
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.role == "user",
            Conversation.is_public.is_(False),
            Conversation.kind == "chat",
            or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"),
            Conversation.user_id.is_not(None),
            Message.created_at >= series_query_start,
            Message.created_at <= end_value,
        )
        .group_by(activity_bucket, Conversation.user_id)
        .order_by(activity_bucket)
    )
    series_stmt = apply_aggregate_owner_filter(
        series_stmt,
        current_user=current_user,
        permission_map=permission_map,
        user_email=user_email,
        user_group=user_group,
        include_internal=True,
    ).where(User.email != SCHEDULER_USER_EMAIL)
    series_rows = (await session.execute(series_stmt)).all()

    account_bucket = (
        func.date_trunc("hour", User.created_at, "UTC")
        if time_granularity == TimeGranularity.HOUR
        else func.date_trunc(time_granularity.value, func.timezone(timezone.key, User.created_at))
    )
    account_series_stmt = select(account_bucket.label("date"), User.id.label("account_id")).where(
        User.created_at >= series_start,
        User.created_at <= end_value,
        User.email != SCHEDULER_USER_EMAIL,
    )
    account_series_stmt = _apply_adoption_account_filter(
        account_series_stmt,
        current_user=current_user,
        permission_map=permission_map,
        user_email=user_email,
        user_group=user_group,
    )
    account_rows = (await session.execute(account_series_stmt)).all()
    accounts_by_bucket: dict[datetime, int] = {}
    new_account_ids: set[str] = set()
    for row in account_rows:
        accounts_by_bucket[row.date] = accounts_by_bucket.get(row.date, 0) + 1
        new_account_ids.add(str(row.account_id))
    new_accounts = len(new_account_ids)

    all_users_by_bucket: dict[datetime, set[str]] = {}
    selected_users_by_bucket: dict[datetime, set[str]] = {}
    for row in series_rows:
        user_id = str(row.user_id)
        all_users_by_bucket.setdefault(row.date, set()).add(user_id)
        if row.selected_activity:
            selected_users_by_bucket.setdefault(row.date, set()).add(user_id)

    range_end_exclusive = end_value + timedelta(microseconds=1)
    if time_granularity == TimeGranularity.HOUR:
        raw_boundaries = iter_time_bucket_boundaries(series_start, end_value, time_granularity)
        chart_boundaries = [
            (
                max(boundary.start, series_start),
                min(boundary.end, range_end_exclusive),
                boundary.start,
            )
            for boundary in raw_boundaries
        ]
    else:
        local_start = series_start.astimezone(timezone)
        local_end = end_value.astimezone(timezone)
        local_boundaries = iter_time_bucket_boundaries(local_start, local_end, time_granularity)
        chart_boundaries = [
            (
                max(boundary.start.astimezone(UTC), series_start),
                min(boundary.end.astimezone(UTC), range_end_exclusive),
                boundary.start.replace(tzinfo=None),
            )
            for boundary in local_boundaries
        ]

    series: list[AdoptionTimeSeriesPointOut] = []
    for bucket_start, bucket_end, row_key in chart_boundaries:
        reference_time = min(bucket_end, end_value)
        if reference_time == bucket_end:
            reference_time -= timedelta(microseconds=1)
        reference_day = reference_time.astimezone(timezone).date()
        rolling_users: set[str] = set()
        if time_granularity == TimeGranularity.HOUR:
            for offset in range(1, 30):
                rolling_users.update(active_by_day.get(reference_day - timedelta(days=offset), ()))
            for activity_key, users in all_users_by_bucket.items():
                if (
                    activity_key <= row_key
                    and activity_key.astimezone(timezone).date() == reference_day
                ):
                    rolling_users.update(users)
        else:
            for offset in range(30):
                rolling_users.update(active_by_day.get(reference_day - timedelta(days=offset), ()))
        series.append(
            AdoptionTimeSeriesPointOut(
                bucket_start=bucket_start,
                bucket_end=bucket_end,
                new_accounts=accounts_by_bucket.get(row_key, 0),
                active_users=len(selected_users_by_bucket.get(row_key, ())),
                monthly_active_users=len(rolling_users),
            )
        )

    return AdoptionSummaryOut(
        new_accounts=new_accounts,
        active_new_accounts=len(new_account_ids & active_account_ids),
        latest_daily_active_users=latest_daily_active_users,
        monthly_active_users=monthly_active_users,
        average_daily_active_users=(
            sum(
                selected_count_by_day.get(display_start + timedelta(days=offset), 0)
                for offset in range(selected_days)
            )
            / selected_days
        ),
        stickiness=(
            latest_daily_active_users / monthly_active_users if monthly_active_users else 0
        ),
        time_granularity=time_granularity,
        series=series,
    )


@router.get("/public-usage", response_model=PublicAnalyticsSummaryOut)
async def get_public_analytics_summary(
    session: SessionDep,
    current_user: PublicAnalyticsAccessUser,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> Any:
    _ = current_user
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")

    conversation_time_filters, message_time_filters = _conversation_time_filters(start, end)
    message_count_subquery = _message_count_subquery(message_time_filters)

    time_granularity = select_time_granularity(start, end)
    time_bucket = func.date_trunc(time_granularity.value, Conversation.created_at, "UTC")

    lead_series_stmt = (
        select(
            time_bucket.label("date"),
            func.count(func.distinct(PublicChatContact.email)).label("leads"),
        )
        .outerjoin(PublicChatContact, Conversation.id == PublicChatContact.conversation_id)
        .where(Conversation.is_public.is_(True), *conversation_time_filters)
        .group_by(time_bucket)
        .order_by(time_bucket)
    )
    lead_rows = (await session.execute(lead_series_stmt)).all()
    series = _build_public_analytics_series(lead_rows, start, end, granularity=time_granularity)

    message_count = func.coalesce(message_count_subquery.c.message_count, 0)
    counts_stmt = (
        select(message_count.label("value"), func.count(Conversation.id).label("conversations"))
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .where(Conversation.is_public.is_(True), *conversation_time_filters)
        .group_by(message_count)
        .order_by(message_count)
    )
    count_rows = (await session.execute(counts_stmt)).all()
    depth_distribution = _build_exact_count_distribution(
        {int(row.value): int(row.conversations) for row in count_rows}
    )

    total_leads = (
        await session.execute(
            select(func.count(func.distinct(PublicChatContact.email)))
            .select_from(Conversation)
            .outerjoin(PublicChatContact, Conversation.id == PublicChatContact.conversation_id)
            .where(Conversation.is_public.is_(True), *conversation_time_filters)
        )
    ).scalar_one()

    return PublicAnalyticsSummaryOut(
        total_leads=total_leads,
        time_granularity=time_granularity,
        series=series,
        depth_buckets=[
            PublicAnalyticsDepthBucketOut(
                label=label, conversations=conversations, overflow=overflow
            )
            for label, conversations, overflow, _, _ in depth_distribution
        ],
    )
