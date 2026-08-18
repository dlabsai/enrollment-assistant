"""Persistent, cross-worker state and event delivery for API eval runs."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg import sql
from sqlalchemy import desc, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import get_session
from app.models import EvalRunEvent as EvalRunEventRecord
from app.models import EvalRunJob as EvalRunJobRecord
from app.utils import current_time_utc

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from uuid import UUID

    from psycopg import AsyncConnection

logger = logging.getLogger(__name__)

EVAL_RUN_NOTIFY_CHANNEL = "eval_run_stream"
_ACTIVE_STATUSES = ("start", "cancelling")
_CURRENT_RUN_TTL = timedelta(hours=6)
_STALE_HEARTBEAT_AFTER = timedelta(seconds=30)


class ActiveEvalRunExistsError(RuntimeError):
    """Raised when persisted state already contains an active run for a user."""


@dataclass(frozen=True)
class EvalRunSnapshot:
    run_id: str
    user_id: UUID | None
    suite: str
    status: str
    report_id: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class PersistedEvalRunEvent:
    sequence: int
    event: str
    payload: dict[str, object]


def _snapshot(job: EvalRunJobRecord) -> EvalRunSnapshot:
    return EvalRunSnapshot(
        run_id=job.run_id,
        user_id=job.started_by_user_id,
        suite=job.suite,
        status=job.status,
        report_id=job.report_id,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _psycopg_dsn() -> str:
    return str(settings.SQLALCHEMY_DATABASE_URI).replace("postgresql+psycopg://", "postgresql://")


async def _notify(session: Any, run_id: str) -> None:
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVAL_RUN_NOTIFY_CHANNEL, "payload": json.dumps({"run_id": run_id})},
    )


def _apply_event_to_job(
    job: EvalRunJobRecord, event: str, payload: dict[str, object], now: datetime
) -> None:
    job.heartbeat_at = now
    if event == "report":
        report_id = payload.get("report_id")
        if isinstance(report_id, str):
            job.report_id = report_id
        return
    if event == "error":
        message = payload.get("message")
        if isinstance(message, str):
            job.error_message = message
        return
    if event != "status":
        return

    status = payload.get("status")
    if not isinstance(status, str):
        return
    job.status = status
    message = payload.get("message")
    if isinstance(message, str):
        job.error_message = message
    if status not in _ACTIVE_STATUSES:
        job.completed_at = now


async def _append_event(
    session: Any, job: EvalRunJobRecord, event: str, payload: dict[str, object], *, now: datetime
) -> None:
    _apply_event_to_job(job, event, payload, now)
    session.add(
        EvalRunEventRecord(
            run_id=job.run_id, event_type=event, payload=payload, created_at=now, updated_at=now
        )
    )
    await session.flush()
    await _notify(session, job.run_id)


async def create_eval_run(
    *, run_id: str, user_id: UUID, suite: str, initial_payload: dict[str, object]
) -> EvalRunSnapshot:
    await _expire_stale_runs()
    now = current_time_utc()
    async with get_session() as session:
        job = EvalRunJobRecord(
            run_id=run_id,
            started_by_user_id=user_id,
            suite=suite,
            status="start",
            started_at=now,
            heartbeat_at=now,
        )
        session.add(job)
        try:
            await session.flush()
            await _append_event(session, job, "status", initial_payload, now=now)
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint_name != "uq_eval_run_job_active_user":
                raise
            raise ActiveEvalRunExistsError("An eval run is already running") from error
        return _snapshot(job)


async def publish_eval_run_event(run_id: str, event: str, payload: dict[str, object]) -> None:
    now = current_time_utc()
    async with get_session() as session:
        job = await session.scalar(
            select(EvalRunJobRecord).where(EvalRunJobRecord.run_id == run_id).with_for_update()
        )
        if job is None:
            logger.warning("Skipping event for missing eval run %s", run_id)
            return
        if job.status not in _ACTIVE_STATUSES:
            logger.warning(
                "Skipping event for terminal eval run %s with status %s", run_id, job.status
            )
            return
        await _append_event(session, job, event, payload, now=now)
        await session.commit()


async def heartbeat_eval_run(run_id: str) -> str | None:
    async with get_session() as session:
        job = await session.scalar(
            select(EvalRunJobRecord).where(EvalRunJobRecord.run_id == run_id)
        )
        if job is None:
            return None
        if job.status in _ACTIVE_STATUSES:
            job.heartbeat_at = current_time_utc()
            await session.commit()
        return job.status


async def _expire_stale_runs() -> None:
    now = current_time_utc()
    stale_before = now - _STALE_HEARTBEAT_AFTER
    async with get_session() as session:
        jobs = list(
            (
                await session.execute(
                    select(EvalRunJobRecord)
                    .where(
                        EvalRunJobRecord.status.in_(_ACTIVE_STATUSES),
                        EvalRunJobRecord.heartbeat_at < stale_before,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for job in jobs:
            message = "Eval run worker stopped before completion"
            await _append_event(
                session, job, "error", {"message": message, "run_id": job.run_id}, now=now
            )
            await _append_event(
                session,
                job,
                "status",
                {"status": "error", "message": message, "run_id": job.run_id},
                now=now,
            )
        if jobs:
            await session.commit()


async def get_current_eval_run(user_id: UUID) -> EvalRunSnapshot | None:
    await _expire_stale_runs()
    cutoff = current_time_utc() - _CURRENT_RUN_TTL
    async with get_session() as session:
        job = await session.scalar(
            select(EvalRunJobRecord)
            .where(
                EvalRunJobRecord.started_by_user_id == user_id,
                or_(
                    EvalRunJobRecord.status.in_(_ACTIVE_STATUSES),
                    EvalRunJobRecord.completed_at >= cutoff,
                ),
            )
            .order_by(desc(EvalRunJobRecord.started_at), desc(EvalRunJobRecord.created_at))
            .limit(1)
        )
        return None if job is None else _snapshot(job)


async def get_eval_run(run_id: str, user_id: UUID) -> EvalRunSnapshot | None:
    await _expire_stale_runs()
    async with get_session() as session:
        job = await session.scalar(
            select(EvalRunJobRecord).where(
                EvalRunJobRecord.run_id == run_id, EvalRunJobRecord.started_by_user_id == user_id
            )
        )
        return None if job is None else _snapshot(job)


async def list_eval_run_events(
    run_id: str, user_id: UUID, *, after_sequence: int = 0
) -> list[PersistedEvalRunEvent] | None:
    async with get_session() as session:
        owns_run = await session.scalar(
            select(EvalRunJobRecord.run_id).where(
                EvalRunJobRecord.run_id == run_id, EvalRunJobRecord.started_by_user_id == user_id
            )
        )
        if owns_run is None:
            return None
        rows = list(
            (
                await session.execute(
                    select(EvalRunEventRecord)
                    .where(
                        EvalRunEventRecord.run_id == run_id,
                        EvalRunEventRecord.sequence > after_sequence,
                    )
                    .order_by(EvalRunEventRecord.sequence.asc())
                )
            )
            .scalars()
            .all()
        )
        return [
            PersistedEvalRunEvent(
                sequence=row.sequence,
                event=row.event_type,
                payload=cast("dict[str, object]", row.payload),
            )
            for row in rows
        ]


async def request_eval_run_cancellation(run_id: str, user_id: UUID) -> EvalRunSnapshot | None:
    now = current_time_utc()
    async with get_session() as session:
        job = await session.scalar(
            select(EvalRunJobRecord)
            .where(
                EvalRunJobRecord.run_id == run_id, EvalRunJobRecord.started_by_user_id == user_id
            )
            .with_for_update()
        )
        if job is None:
            return None
        if job.status == "start":
            await _append_event(
                session, job, "status", {"status": "cancelling", "run_id": run_id}, now=now
            )
            await session.commit()
        return _snapshot(job)


def parse_eval_run_notification(raw_payload: str) -> str | None:
    try:
        payload: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    run_id = cast("dict[str, object]", payload).get("run_id")
    return run_id if isinstance(run_id, str) else None


async def _iter_notifications(connection: AsyncConnection[Any]) -> AsyncGenerator[str]:
    async for notification in connection.notifies():
        if notification.channel != EVAL_RUN_NOTIFY_CHANNEL:
            continue
        run_id = parse_eval_run_notification(notification.payload)
        if run_id is not None:
            yield run_id


@asynccontextmanager
async def listen_eval_run_notifications() -> AsyncGenerator[AsyncIterator[str]]:
    connection = await psycopg.AsyncConnection.connect(_psycopg_dsn(), autocommit=True)
    try:
        await connection.execute(
            sql.SQL("LISTEN {}").format(sql.Identifier(EVAL_RUN_NOTIFY_CHANNEL))
        )
        yield _iter_notifications(connection)
    finally:
        await connection.close()
