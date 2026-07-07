from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.chat.tools.utils import get_azure_openai_client
from app.core.db import engine, get_session
from app.rag.build import build_search_db
from app.rag.demo_corpus.generate import write_demo_rag_data
from app.rag.job_tracking import (
    create_rag_build_job,
    finish_rag_build_job,
    record_rag_build_progress,
    record_rag_build_source_stats,
)

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

_RAG_PIPELINE_LOCK_ID = 20_260_407_02

RagPipelineStepKey = Literal["demo_corpus_ingest", "build_search_db", "vacuum_database"]
RagPipelineStepStatus = Literal["pending", "running", "completed", "skipped", "error"]
RagPipelineJobTrigger = Literal["manual", "scheduled", "cli"]
RagPipelineProgressCallback = Callable[["RagPipelineProgressSnapshot"], Awaitable[None]]
RagPipelineJobStartedCallback = Callable[["UUID"], Awaitable[None]]


class RagPipelineAlreadyRunningError(RuntimeError):
    """Raised when another worker already holds the RAG pipeline advisory lock."""


class RagPipelineStepSnapshot(BaseModel):
    key: RagPipelineStepKey
    label: str
    status: RagPipelineStepStatus


class RagPipelineProgressSnapshot(BaseModel):
    steps: list[RagPipelineStepSnapshot]
    current_step: RagPipelineStepKey | None = None
    finished_steps: int
    total_steps: int


@dataclass(frozen=True)
class _PipelineStepDefinition:
    key: RagPipelineStepKey
    label: str


class _RagPipelineLockHandle:
    def __init__(self, connection: AsyncConnection, *, job_name: str) -> None:
        self._connection = connection
        self._released = False
        self._job_name = job_name

    async def release(self) -> None:
        if self._released:
            return

        try:
            await self._connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _RAG_PIPELINE_LOCK_ID}
            )
        finally:
            await self._connection.close()
            self._released = True
            logger.debug("Released RAG pipeline advisory lock for %s", self._job_name)


async def try_acquire_rag_pipeline_lock(*, job_name: str) -> _RagPipelineLockHandle | None:
    connection = await engine.connect()
    acquired = bool(
        await connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": _RAG_PIPELINE_LOCK_ID}
        )
    )
    if not acquired:
        await connection.close()
        logger.info(
            "Skipping %s because another RAG pipeline worker already holds the lock", job_name
        )
        return None

    logger.debug("Acquired RAG pipeline advisory lock for %s", job_name)
    return _RagPipelineLockHandle(connection, job_name=job_name)


def _build_step_definitions() -> list[_PipelineStepDefinition]:
    return [
        _PipelineStepDefinition(key="demo_corpus_ingest", label="Demo corpus ingest"),
        _PipelineStepDefinition(key="build_search_db", label="Build search DB"),
        _PipelineStepDefinition(key="vacuum_database", label="Vacuum database"),
    ]


def _build_snapshot(
    steps: list[RagPipelineStepSnapshot], *, current_step: RagPipelineStepKey | None = None
) -> RagPipelineProgressSnapshot:
    return RagPipelineProgressSnapshot(
        steps=[step.model_copy() for step in steps],
        current_step=current_step,
        finished_steps=sum(step.status in {"completed", "skipped"} for step in steps),
        total_steps=len(steps),
    )


async def _publish_progress(
    callback: RagPipelineProgressCallback | None,
    steps: list[RagPipelineStepSnapshot],
    *,
    current_step: RagPipelineStepKey | None = None,
) -> None:
    if callback is None:
        return

    await callback(_build_snapshot(steps, current_step=current_step))


async def _run_step(
    steps: list[RagPipelineStepSnapshot],
    definition: _PipelineStepDefinition,
    operation: Callable[[], Awaitable[None]],
    *,
    callback: RagPipelineProgressCallback | None,
) -> None:
    step = next(step for step in steps if step.key == definition.key)
    step.status = "running"
    await _publish_progress(callback, steps, current_step=definition.key)
    logger.info("Starting RAG pipeline step: %s", definition.label)

    try:
        await operation()
    except Exception:
        step.status = "error"
        await _publish_progress(callback, steps, current_step=definition.key)
        logger.exception("RAG pipeline step failed: %s", definition.label)
        raise
    else:
        step.status = "completed"
        await _publish_progress(callback, steps, current_step=None)
        logger.info("Completed RAG pipeline step: %s", definition.label)


async def run_rag_sync_pipeline(
    *,
    job_name: str,
    progress_callback: RagPipelineProgressCallback | None = None,
    force_rebuild: bool = False,
    job_trigger: RagPipelineJobTrigger = "manual",
    started_by_user_id: UUID | None = None,
    job_started_callback: RagPipelineJobStartedCallback | None = None,
) -> UUID:
    job_id = await create_rag_build_job(
        job_name=job_name,
        trigger=job_trigger,
        force_rebuild=force_rebuild,
        started_by_user_id=started_by_user_id,
    )
    if job_started_callback is not None:
        await job_started_callback(job_id)

    async def publish_progress(snapshot: RagPipelineProgressSnapshot) -> None:
        await record_rag_build_progress(job_id, snapshot)
        if progress_callback is not None:
            await progress_callback(snapshot)

    try:
        lock = await try_acquire_rag_pipeline_lock(job_name=job_name)
    except asyncio.CancelledError:
        await finish_rag_build_job(
            job_id, status="cancelled", error_message="RAG build was cancelled"
        )
        raise
    except Exception as exc:
        await finish_rag_build_job(job_id, status="failed", error_message=str(exc))
        raise

    if lock is None:
        error_message = "RAG build is already running"
        await finish_rag_build_job(job_id, status="skipped", error_message=error_message)
        raise RagPipelineAlreadyRunningError(error_message)

    try:
        steps = [
            RagPipelineStepSnapshot(key=definition.key, label=definition.label, status="pending")
            for definition in _build_step_definitions()
        ]

        await _publish_progress(publish_progress, steps, current_step=None)

        async def run_demo_corpus_ingest() -> None:
            stats = await asyncio.to_thread(write_demo_rag_data)
            logger.info("Wrote Demo University RAG corpus: %s documents", stats.total_documents)

        await _run_step(
            steps,
            _PipelineStepDefinition(key="demo_corpus_ingest", label="Demo corpus ingest"),
            run_demo_corpus_ingest,
            callback=publish_progress,
        )

        async def run_build_search_db() -> None:
            async with get_session() as session:
                await build_search_db(
                    get_azure_openai_client(),
                    session,
                    force_rebuild=force_rebuild,
                    dry_run=False,
                    source_stats_callback=lambda stats: record_rag_build_source_stats(
                        job_id, stats
                    ),
                )

        await _run_step(
            steps,
            _PipelineStepDefinition(key="build_search_db", label="Build search DB"),
            run_build_search_db,
            callback=publish_progress,
        )

        async def run_vacuum() -> None:
            async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
                for table_name in ("document", "document_content_chunk", "guardrail_url_registry"):
                    await conn.execute(text(f"VACUUM ANALYZE {table_name}"))

        await _run_step(
            steps,
            _PipelineStepDefinition(key="vacuum_database", label="Vacuum database"),
            run_vacuum,
            callback=publish_progress,
        )
    except asyncio.CancelledError:
        await finish_rag_build_job(
            job_id, status="cancelled", error_message="RAG build was cancelled"
        )
        raise
    except Exception as exc:
        await finish_rag_build_job(job_id, status="failed", error_message=str(exc))
        raise
    else:
        await finish_rag_build_job(job_id, status="completed")
        return job_id
    finally:
        await lock.release()
