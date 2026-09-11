from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

DECEMBER = 12


class TimeGranularity(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True)
class TimeBucketBoundary:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class TimeSeriesBoundary:
    key: datetime
    start: datetime
    end: datetime


def select_time_granularity(start: datetime | None, end: datetime | None) -> TimeGranularity:
    if start is None or end is None:
        return TimeGranularity.DAY

    duration = end - start
    if duration <= timedelta(hours=72):
        return TimeGranularity.HOUR
    if duration <= timedelta(days=90):
        return TimeGranularity.DAY
    if duration <= timedelta(days=365 * 2):
        return TimeGranularity.WEEK
    return TimeGranularity.MONTH


def floor_time_bucket(value: datetime, granularity: TimeGranularity) -> datetime:
    if granularity == TimeGranularity.HOUR:
        return value.replace(minute=0, second=0, microsecond=0)
    if granularity == TimeGranularity.DAY:
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == TimeGranularity.WEEK:
        day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_time_bucket(value: datetime, granularity: TimeGranularity) -> datetime:
    if granularity == TimeGranularity.HOUR:
        return value + timedelta(hours=1)
    if granularity == TimeGranularity.DAY:
        return value + timedelta(days=1)
    if granularity == TimeGranularity.WEEK:
        return value + timedelta(days=7)
    if value.month == DECEMBER:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def iter_time_bucket_boundaries(
    start: datetime, end: datetime, granularity: TimeGranularity
) -> list[TimeBucketBoundary]:
    current = floor_time_bucket(start, granularity)
    final = floor_time_bucket(end, granularity)
    boundaries: list[TimeBucketBoundary] = []
    while current <= final:
        next_bucket = next_time_bucket(current, granularity)
        boundaries.append(TimeBucketBoundary(start=current, end=next_bucket))
        current = next_bucket
    return boundaries


def build_time_series_boundaries(
    bucket_keys: Iterable[datetime],
    start: datetime | None,
    end: datetime | None,
    granularity: TimeGranularity,
) -> list[TimeSeriesBoundary]:
    keys = sorted({key.astimezone(UTC) for key in bucket_keys})
    if start is None and end is None:
        return [
            TimeSeriesBoundary(key=key, start=key, end=next_time_bucket(key, granularity))
            for key in keys
        ]

    range_start = start.astimezone(UTC) if start is not None else (keys[0] if keys else None)
    range_end = end.astimezone(UTC) if end is not None else (keys[-1] if keys else None)
    if range_start is None or range_end is None:
        return []

    range_end_exclusive = range_end + timedelta(microseconds=1) if end is not None else None
    return [
        TimeSeriesBoundary(
            key=boundary.start,
            start=max(boundary.start, range_start) if start is not None else boundary.start,
            end=(
                min(boundary.end, range_end_exclusive)
                if range_end_exclusive is not None
                else boundary.end
            ),
        )
        for boundary in iter_time_bucket_boundaries(range_start, range_end, granularity)
    ]
