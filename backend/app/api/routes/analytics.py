from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, Integer, case, cast, func, or_, select
from sqlalchemy.sql import ColumnElement

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.rbac import PermissionKey
from app.models import Conversation, Message, OtelSpan, PublicChatContact

if TYPE_CHECKING:
    from collections.abc import Sequence

router = APIRouter(prefix="/analytics", tags=["analytics"])

MESSAGE_BUCKET_1 = 1
MESSAGE_BUCKET_2 = 2
MESSAGE_BUCKET_3 = 3
MESSAGE_BUCKET_4 = 4
MESSAGE_BUCKET_6 = 6
MESSAGE_BUCKET_7 = 7
MESSAGE_BUCKET_9 = 9
MESSAGE_BUCKET_10 = 10

RESPONSE_BUCKET_5 = 5
RESPONSE_BUCKET_10 = 10
RESPONSE_BUCKET_15 = 15
RESPONSE_BUCKET_20 = 20
RESPONSE_BUCKET_25 = 25

AnalyticsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_ANALYTICS))
]
PublicAnalyticsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_PUBLIC_ANALYTICS))
]


class ConversationAnalyticsDailyOut(BaseModel):
    date: datetime
    conversations: int
    messages: int
    avg_messages_per_conversation: float
    single_message_rate: float


class ConversationAnalyticsBucketOut(BaseModel):
    label: str
    conversations: int


class ConversationAnalyticsHourlyOut(BaseModel):
    hour: int
    messages: int


class ConversationAnalyticsStatsOut(BaseModel):
    min: float | None
    p50: float | None
    median: float | None
    avg: float | None
    p75: float | None
    p90: float | None
    p95: float | None
    p99: float | None
    max: float | None


class ConversationAnalyticsResponseTimeBucketOut(BaseModel):
    label: str
    responses: int


class ConversationAnalyticsSummaryOut(BaseModel):
    total_conversations: int
    total_messages: int
    avg_messages_per_conversation: float
    single_message_rate: float
    daily: list[ConversationAnalyticsDailyOut]
    length_buckets: list[ConversationAnalyticsBucketOut]
    hourly_activity: list[ConversationAnalyticsHourlyOut]
    length_stats: ConversationAnalyticsStatsOut | None
    response_time_buckets: list[ConversationAnalyticsResponseTimeBucketOut]
    response_time_stats: ConversationAnalyticsStatsOut | None


class PublicUsageDailyOut(BaseModel):
    date: datetime
    conversations: int
    messages: int
    avg_messages_per_conversation: float
    drop_off_rate: float
    leads: int


class PublicUsageBucketOut(BaseModel):
    label: str
    conversations: int


class PublicUsageHourlyOut(BaseModel):
    hour: int
    messages: int


class PublicUsageSummaryOut(BaseModel):
    total_conversations: int
    total_messages: int
    avg_messages_per_conversation: float
    drop_off_rate: float
    total_leads: int
    lead_capture_rate: float
    daily: list[PublicUsageDailyOut]
    depth_buckets: list[PublicUsageBucketOut]
    hourly_activity: list[PublicUsageHourlyOut]


def _use_hourly_buckets(start: datetime | None, end: datetime | None) -> bool:
    return start is not None and end is not None and end - start <= timedelta(hours=24)


def _build_conversation_daily_series(
    rows: Sequence[Any], start: datetime | None, end: datetime | None, *, use_hourly: bool
) -> list[ConversationAnalyticsDailyOut]:
    if not use_hourly or start is None or end is None:
        return [
            ConversationAnalyticsDailyOut(
                date=row.date,
                conversations=row.conversations,
                messages=row.messages,
                avg_messages_per_conversation=float(row.avg_messages_per_conversation),
                single_message_rate=float(row.single_message_rate),
            )
            for row in rows
        ]

    row_map = {row.date: row for row in rows}
    current = start.replace(minute=0, second=0, microsecond=0)
    end_bucket = end.replace(minute=0, second=0, microsecond=0)
    hourly_rows: list[ConversationAnalyticsDailyOut] = []
    while current <= end_bucket:
        row = row_map.get(current)
        if row is None:
            hourly_rows.append(
                ConversationAnalyticsDailyOut(
                    date=current,
                    conversations=0,
                    messages=0,
                    avg_messages_per_conversation=0.0,
                    single_message_rate=0.0,
                )
            )
        else:
            hourly_rows.append(
                ConversationAnalyticsDailyOut(
                    date=row.date,
                    conversations=row.conversations,
                    messages=row.messages,
                    avg_messages_per_conversation=float(row.avg_messages_per_conversation),
                    single_message_rate=float(row.single_message_rate),
                )
            )
        current += timedelta(hours=1)

    return hourly_rows


def _build_public_usage_daily_series(
    rows: Sequence[Any], start: datetime | None, end: datetime | None, *, use_hourly: bool
) -> list[PublicUsageDailyOut]:
    if not use_hourly or start is None or end is None:
        return [
            PublicUsageDailyOut(
                date=row.date,
                conversations=row.conversations,
                messages=row.messages,
                avg_messages_per_conversation=float(row.avg_messages_per_conversation),
                drop_off_rate=float(row.drop_off_rate),
                leads=row.leads,
            )
            for row in rows
        ]

    row_map = {row.date: row for row in rows}
    current = start.replace(minute=0, second=0, microsecond=0)
    end_bucket = end.replace(minute=0, second=0, microsecond=0)
    hourly_rows: list[PublicUsageDailyOut] = []
    while current <= end_bucket:
        row = row_map.get(current)
        if row is None:
            hourly_rows.append(
                PublicUsageDailyOut(
                    date=current,
                    conversations=0,
                    messages=0,
                    avg_messages_per_conversation=0.0,
                    drop_off_rate=0.0,
                    leads=0,
                )
            )
        else:
            hourly_rows.append(
                PublicUsageDailyOut(
                    date=row.date,
                    conversations=row.conversations,
                    messages=row.messages,
                    avg_messages_per_conversation=float(row.avg_messages_per_conversation),
                    drop_off_rate=float(row.drop_off_rate),
                    leads=row.leads,
                )
            )
        current += timedelta(hours=1)

    return hourly_rows


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


def _analytics_stats_from_row(
    row: Any, *, min_field: str, max_field: str, avg_field: str
) -> ConversationAnalyticsStatsOut | None:
    min_value = getattr(row, min_field)
    if min_value is None:
        return None
    return ConversationAnalyticsStatsOut(
        min=float(min_value),
        p50=float(row.p50 or 0),
        median=float(row.p50 or 0),
        avg=float(getattr(row, avg_field) or 0),
        p75=float(row.p75 or 0),
        p90=float(row.p90 or 0),
        p95=float(row.p95 or 0),
        p99=float(row.p99 or 0),
        max=float(getattr(row, max_field) or 0),
    )


@router.get("/conversations", response_model=ConversationAnalyticsSummaryOut)
async def get_conversation_analytics_summary(
    session: SessionDep,
    current_user: AnalyticsAccessUser,
    platform: Annotated[str | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> Any:
    _ = current_user
    if platform not in {None, "both", "public", "internal"}:
        raise HTTPException(status_code=400, detail="Invalid platform")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")

    platform_value = "both" if platform in (None, "both") else platform
    platform_conditions: list[Any] = []
    if platform_value in {"both", "public"}:
        platform_conditions.append(Conversation.is_public.is_(True))
    if platform_value in {"both", "internal"}:
        platform_conditions.append(Conversation.is_public.is_(False))
    platform_filter = or_(*platform_conditions)

    conversation_time_filters, message_time_filters = _conversation_time_filters(start, end)
    message_count_subquery = _message_count_subquery(message_time_filters)
    message_count = func.coalesce(message_count_subquery.c.message_count, 0)
    single_message_rate_expr = func.avg(case((message_count <= 1, 1), else_=0))

    use_hourly_buckets = _use_hourly_buckets(start, end)
    bucket_unit = "hour" if use_hourly_buckets else "day"
    time_bucket = func.date_trunc(bucket_unit, Conversation.created_at)

    daily_stmt = (
        select(
            time_bucket.label("date"),
            func.count(Conversation.id).label("conversations"),
            func.coalesce(func.sum(message_count), 0).label("messages"),
            func.coalesce(func.avg(message_count), 0).label("avg_messages_per_conversation"),
            func.coalesce(single_message_rate_expr, 0).label("single_message_rate"),
        )
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .where(platform_filter, *conversation_time_filters)
        .group_by(time_bucket)
        .order_by(time_bucket)
    )
    daily_rows = (await session.execute(daily_stmt)).all()
    daily_series = _build_conversation_daily_series(
        daily_rows, start, end, use_hourly=use_hourly_buckets
    )

    message_stats_stmt = (
        select(
            func.count(Conversation.id).label("total_conversations"),
            func.coalesce(func.sum(message_count), 0).label("total_messages"),
            func.coalesce(func.avg(message_count), 0).label("avg_messages_per_conversation"),
            func.coalesce(single_message_rate_expr, 0).label("single_message_rate"),
            func.min(message_count).label("min_messages"),
            func.max(message_count).label("max_messages"),
            func.percentile_cont(0.5).within_group(message_count).label("p50"),
            func.percentile_cont(0.75).within_group(message_count).label("p75"),
            func.percentile_cont(0.9).within_group(message_count).label("p90"),
            func.percentile_cont(0.95).within_group(message_count).label("p95"),
            func.percentile_cont(0.99).within_group(message_count).label("p99"),
            func.avg(message_count).label("avg_messages"),
            func.sum(case((message_count == MESSAGE_BUCKET_1, 1), else_=0)).label("bucket_1"),
            func.sum(
                case((message_count.between(MESSAGE_BUCKET_2, MESSAGE_BUCKET_3), 1), else_=0)
            ).label("bucket_2_3"),
            func.sum(
                case((message_count.between(MESSAGE_BUCKET_4, MESSAGE_BUCKET_6), 1), else_=0)
            ).label("bucket_4_6"),
            func.sum(
                case((message_count.between(MESSAGE_BUCKET_7, MESSAGE_BUCKET_9), 1), else_=0)
            ).label("bucket_7_9"),
            func.sum(case((message_count >= MESSAGE_BUCKET_10, 1), else_=0)).label(
                "bucket_10_plus"
            ),
        )
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .where(platform_filter, *conversation_time_filters)
    )
    message_stats = (await session.execute(message_stats_stmt)).one()

    hour_bucket = func.date_part("hour", Message.created_at)
    hourly_stmt = (
        select(
            func.cast(hour_bucket, Integer).label("hour"), func.count(Message.id).label("messages")
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(platform_filter, *message_time_filters)
        .group_by(hour_bucket)
        .order_by(hour_bucket)
    )
    hourly_rows = {row.hour: row.messages for row in await session.execute(hourly_stmt)}

    response_time_expr: ColumnElement[float] = cast(OtelSpan.total_time, Float)
    span_time_expr = func.coalesce(OtelSpan.span_time, OtelSpan.start_time, OtelSpan.created_at)
    response_time_filters: list[Any] = [OtelSpan.total_time.is_not(None), response_time_expr >= 0]
    response_is_public_expr = case(
        (OtelSpan.is_internal.is_not(None), ~OtelSpan.is_internal),
        (Conversation.is_public.is_not(None), Conversation.is_public),
        else_=None,
    )
    if platform_value == "internal":
        response_time_filters.append(response_is_public_expr.is_(False))
    elif platform_value == "public":
        response_time_filters.append(response_is_public_expr.is_(True))
    if start is not None:
        response_time_filters.append(span_time_expr >= start)
    if end is not None:
        response_time_filters.append(span_time_expr <= end)

    response_time_stmt = (
        select(
            func.min(response_time_expr).label("min_time"),
            func.percentile_cont(0.5).within_group(response_time_expr).label("p50"),
            func.percentile_cont(0.75).within_group(response_time_expr).label("p75"),
            func.percentile_cont(0.9).within_group(response_time_expr).label("p90"),
            func.percentile_cont(0.95).within_group(response_time_expr).label("p95"),
            func.percentile_cont(0.99).within_group(response_time_expr).label("p99"),
            func.avg(response_time_expr).label("avg_time"),
            func.max(response_time_expr).label("max_time"),
            func.sum(case((response_time_expr < RESPONSE_BUCKET_5, 1), else_=0)).label(
                "bucket_0_5"
            ),
            func.sum(
                case(
                    (
                        (response_time_expr >= RESPONSE_BUCKET_5)
                        & (response_time_expr < RESPONSE_BUCKET_10),
                        1,
                    ),
                    else_=0,
                )
            ).label("bucket_5_10"),
            func.sum(
                case(
                    (
                        (response_time_expr >= RESPONSE_BUCKET_10)
                        & (response_time_expr < RESPONSE_BUCKET_15),
                        1,
                    ),
                    else_=0,
                )
            ).label("bucket_10_15"),
            func.sum(
                case(
                    (
                        (response_time_expr >= RESPONSE_BUCKET_15)
                        & (response_time_expr < RESPONSE_BUCKET_20),
                        1,
                    ),
                    else_=0,
                )
            ).label("bucket_15_20"),
            func.sum(
                case(
                    (
                        (response_time_expr >= RESPONSE_BUCKET_20)
                        & (response_time_expr < RESPONSE_BUCKET_25),
                        1,
                    ),
                    else_=0,
                )
            ).label("bucket_20_25"),
            func.sum(case((response_time_expr >= RESPONSE_BUCKET_25, 1), else_=0)).label(
                "bucket_25_plus"
            ),
        )
        .select_from(OtelSpan)
        .outerjoin(Conversation, Conversation.id == OtelSpan.conversation_id)
        .where(*response_time_filters)
    )
    response_time_stats_row = (await session.execute(response_time_stmt)).one()

    bucket_counts = {
        "1": message_stats.bucket_1 or 0,
        "2-3": message_stats.bucket_2_3 or 0,
        "4-6": message_stats.bucket_4_6 or 0,
        "7-9": message_stats.bucket_7_9 or 0,
        "10+": message_stats.bucket_10_plus or 0,
    }
    response_time_bucket_defs = [
        ("0-<5s", response_time_stats_row.bucket_0_5 or 0),
        ("5-<10s", response_time_stats_row.bucket_5_10 or 0),
        ("10-<15s", response_time_stats_row.bucket_10_15 or 0),
        ("15-<20s", response_time_stats_row.bucket_15_20 or 0),
        ("20-<25s", response_time_stats_row.bucket_20_25 or 0),
        ("≥25s", response_time_stats_row.bucket_25_plus or 0),
    ]

    return ConversationAnalyticsSummaryOut(
        total_conversations=message_stats.total_conversations,
        total_messages=message_stats.total_messages,
        avg_messages_per_conversation=float(message_stats.avg_messages_per_conversation),
        single_message_rate=float(message_stats.single_message_rate),
        daily=daily_series,
        length_buckets=[
            ConversationAnalyticsBucketOut(label=label, conversations=bucket_counts[label])
            for label in bucket_counts
        ],
        hourly_activity=[
            ConversationAnalyticsHourlyOut(hour=hour, messages=hourly_rows.get(hour, 0))
            for hour in range(24)
        ],
        length_stats=_analytics_stats_from_row(
            message_stats,
            min_field="min_messages",
            max_field="max_messages",
            avg_field="avg_messages",
        ),
        response_time_buckets=[
            ConversationAnalyticsResponseTimeBucketOut(label=label, responses=count)
            for label, count in response_time_bucket_defs
        ],
        response_time_stats=_analytics_stats_from_row(
            response_time_stats_row,
            min_field="min_time",
            max_field="max_time",
            avg_field="avg_time",
        ),
    )


@router.get("/public-usage", response_model=PublicUsageSummaryOut)
async def get_public_usage_summary(
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
    message_count = func.coalesce(message_count_subquery.c.message_count, 0)
    drop_off_rate = func.avg(case((message_count <= 1, 1), else_=0))

    use_hourly_buckets = _use_hourly_buckets(start, end)
    bucket_unit = "hour" if use_hourly_buckets else "day"
    time_bucket = func.date_trunc(bucket_unit, Conversation.created_at)

    daily_stmt = (
        select(
            time_bucket.label("date"),
            func.count(Conversation.id).label("conversations"),
            func.coalesce(func.sum(message_count), 0).label("messages"),
            func.coalesce(func.avg(message_count), 0).label("avg_messages_per_conversation"),
            func.coalesce(drop_off_rate, 0).label("drop_off_rate"),
            func.count(func.distinct(PublicChatContact.email)).label("leads"),
        )
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .outerjoin(PublicChatContact, Conversation.id == PublicChatContact.conversation_id)
        .where(Conversation.is_public.is_(True), *conversation_time_filters)
        .group_by(time_bucket)
        .order_by(time_bucket)
    )
    daily_rows = (await session.execute(daily_stmt)).all()
    daily_series = _build_public_usage_daily_series(
        daily_rows, start, end, use_hourly=use_hourly_buckets
    )

    counts_stmt = (
        select(
            Conversation.id,
            func.coalesce(message_count_subquery.c.message_count, 0).label("message_count"),
        )
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .where(Conversation.is_public.is_(True), *conversation_time_filters)
    )
    conversation_counts = [row.message_count for row in await session.execute(counts_stmt)]

    bucket_defs = [("1", 1, 1), ("2-3", 2, 3), ("4-6", 4, 6), ("7-9", 7, 9), ("10+", 10, None)]
    bucket_counts = {label: 0 for label, _, _ in bucket_defs}
    for count in conversation_counts:
        for label, low, high in bucket_defs:
            if count >= low and (high is None or count <= high):
                bucket_counts[label] += 1
                break

    hour_bucket = func.date_part("hour", Message.created_at)
    hourly_stmt = (
        select(
            func.cast(hour_bucket, Integer).label("hour"), func.count(Message.id).label("messages")
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.is_public.is_(True), *message_time_filters)
        .group_by(hour_bucket)
        .order_by(hour_bucket)
    )
    hourly_rows = {row.hour: row.messages for row in await session.execute(hourly_stmt)}

    overall_stmt = (
        select(
            func.count(Conversation.id).label("total_conversations"),
            func.coalesce(func.sum(message_count), 0).label("total_messages"),
            func.coalesce(func.avg(message_count), 0).label("avg_messages_per_conversation"),
            func.coalesce(drop_off_rate, 0).label("drop_off_rate"),
            func.count(func.distinct(PublicChatContact.email)).label("total_leads"),
        )
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .outerjoin(PublicChatContact, Conversation.id == PublicChatContact.conversation_id)
        .where(Conversation.is_public.is_(True), *conversation_time_filters)
    )
    overall = (await session.execute(overall_stmt)).one()

    return PublicUsageSummaryOut(
        total_conversations=overall.total_conversations,
        total_messages=overall.total_messages,
        avg_messages_per_conversation=float(overall.avg_messages_per_conversation),
        drop_off_rate=float(overall.drop_off_rate),
        total_leads=overall.total_leads,
        lead_capture_rate=(
            float(overall.total_leads) / overall.total_conversations
            if overall.total_conversations
            else 0
        ),
        daily=daily_series,
        depth_buckets=[
            PublicUsageBucketOut(label=label, conversations=bucket_counts[label])
            for label, _, _ in bucket_defs
        ],
        hourly_activity=[
            PublicUsageHourlyOut(hour=hour, messages=hourly_rows.get(hour, 0)) for hour in range(24)
        ],
    )
