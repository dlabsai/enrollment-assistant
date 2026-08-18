from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg import sql
from sqlalchemy import desc, select, text

from app.core.config import settings
from app.core.db import get_session
from app.models import RagBuildJob, RagBuildJobStep

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from uuid import UUID

    from psycopg import AsyncConnection

RAG_BUILD_NOTIFY_CHANNEL = "rag_build_stream"
_MAX_NOTIFY_PAYLOAD_BYTES = 7_500
_MAX_LOG_MESSAGE_BYTES = 6_000


def _psycopg_dsn() -> str:
    return str(settings.SQLALCHEMY_DATABASE_URI).replace("postgresql+psycopg://", "postgresql://")


def _json_payload(value: dict[str, Any]) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _notification_payload(event: str, payload: dict[str, Any]) -> str:
    envelope = {"event": event, "payload": payload}
    serialized = _json_payload(envelope)
    if len(serialized.encode("utf-8")) <= _MAX_NOTIFY_PAYLOAD_BYTES:
        return serialized

    message = payload.get("message")
    if event == "log" and isinstance(message, str):
        truncated_message = (
            message.encode("utf-8")[:_MAX_LOG_MESSAGE_BYTES].decode("utf-8", errors="ignore")
            + "… [truncated]"
        )
        serialized = _json_payload(
            {"event": event, "payload": {**payload, "message": truncated_message}}
        )
        if len(serialized.encode("utf-8")) <= _MAX_NOTIFY_PAYLOAD_BYTES:
            return serialized

    raise ValueError("RAG build notification payload is too large")


def parse_rag_build_notification(raw_payload: str) -> tuple[str, dict[str, Any]] | None:
    try:
        parsed: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    parsed_payload = cast("dict[str, object]", parsed)
    event = parsed_payload.get("event")
    payload = parsed_payload.get("payload")
    if not isinstance(event, str) or not isinstance(payload, dict):
        return None

    return event, cast("dict[str, Any]", payload)


async def publish_rag_build_notification(event: str, payload: dict[str, Any]) -> None:
    async with get_session() as session:
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": RAG_BUILD_NOTIFY_CHANNEL, "payload": _notification_payload(event, payload)},
        )
        await session.commit()


async def publish_rag_build_notification_with_connection(
    connection: AsyncConnection[Any], event: str, payload: dict[str, Any]
) -> None:
    await connection.execute(
        "SELECT pg_notify(%s, %s)",
        (RAG_BUILD_NOTIFY_CHANNEL, _notification_payload(event, payload)),
    )


async def _iter_rag_build_notifications(
    connection: AsyncConnection[Any],
) -> AsyncGenerator[tuple[str, dict[str, Any]]]:
    async for notification in connection.notifies():
        if notification.channel != RAG_BUILD_NOTIFY_CHANNEL:
            continue
        parsed = parse_rag_build_notification(notification.payload)
        if parsed is not None:
            yield parsed


@asynccontextmanager
async def listen_rag_build_notifications() -> AsyncGenerator[
    AsyncIterator[tuple[str, dict[str, Any]]]
]:
    connection = await psycopg.AsyncConnection.connect(_psycopg_dsn(), autocommit=True)
    try:
        await connection.execute(
            sql.SQL("LISTEN {}").format(sql.Identifier(RAG_BUILD_NOTIFY_CHANNEL))
        )
        yield _iter_rag_build_notifications(connection)
    finally:
        await connection.close()


class RagBuildNotificationPublisher:
    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue(maxsize=1000)
        self._closed = False
        self._task = asyncio.create_task(self._run())

    def publish_nowait(self, event: str, payload: dict[str, Any]) -> None:
        if self._closed:
            return

        def enqueue() -> None:
            if self._closed:
                return
            try:
                self._queue.put_nowait((event, payload))
            except asyncio.QueueFull:
                # Log events are best-effort after reconnect when no event table is allowed.
                return

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            enqueue()
        else:
            self._loop.call_soon_threadsafe(enqueue)

    async def close(self) -> None:
        await asyncio.sleep(0)
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task

    async def _run(self) -> None:
        connection = await psycopg.AsyncConnection.connect(_psycopg_dsn(), autocommit=True)
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    return
                event, payload = item
                with contextlib.suppress(Exception):
                    await publish_rag_build_notification_with_connection(connection, event, payload)
        finally:
            await connection.close()


_rag_build_log_job_id: ContextVar[UUID | None] = ContextVar("rag_build_log_job_id", default=None)


class RagBuildLogHandler(logging.Handler):
    def __init__(self, publisher: RagBuildNotificationPublisher) -> None:
        super().__init__(level=logging.INFO)
        self._publisher = publisher
        self._job_id: UUID | None = None
        self.previous_level = logging.NOTSET

    def bind(self, job_id: UUID) -> Token[UUID | None]:
        self._job_id = job_id
        return _rag_build_log_job_id.set(job_id)

    @staticmethod
    def unbind(token: Token[UUID | None]) -> None:
        _rag_build_log_job_id.reset(token)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return

        job_id = _rag_build_log_job_id.get()
        if job_id is None or job_id != self._job_id:
            return

        stream = "stderr" if record.levelno >= logging.ERROR else "stdout"
        self._publisher.publish_nowait(
            "log", {"job_id": str(job_id), "stream": stream, "message": message}
        )


def _progress_payload_from_steps(job: RagBuildJob, steps: list[RagBuildJobStep]) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "steps": [
            {"key": step.step_key, "label": step.label, "status": step.status} for step in steps
        ],
        "current_step": job.current_step,
        "finished_steps": sum(step.status in {"completed", "skipped"} for step in steps),
        "total_steps": len(steps),
    }


async def active_manual_rag_build_snapshot_events() -> tuple[
    UUID | None, list[tuple[str, dict[str, Any]]]
]:
    async with get_session() as session:
        job = await session.scalar(
            select(RagBuildJob)
            .where(
                RagBuildJob.status.in_(("running", "cancelling")), RagBuildJob.trigger == "manual"
            )
            .order_by(desc(RagBuildJob.started_at), desc(RagBuildJob.id))
            .limit(1)
        )
        if job is None:
            return None, []

        steps = list(
            (
                await session.execute(
                    select(RagBuildJobStep)
                    .where(RagBuildJobStep.job_id == job.id)
                    .order_by(RagBuildJobStep.created_at.asc(), RagBuildJobStep.step_key.asc())
                )
            )
            .scalars()
            .all()
        )

    status = "cancelling" if job.status == "cancelling" else "start"
    events: list[tuple[str, dict[str, Any]]] = [
        ("status", {"job_id": str(job.id), "status": status})
    ]
    if steps:
        events.append(("progress", _progress_payload_from_steps(job, steps)))

    return job.id, events
