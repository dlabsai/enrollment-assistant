from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, desc, select

from app.core.db import get_session
from app.models import (
    RagBuildJob,
    RagBuildJobDocumentChange,
    RagBuildJobSourceStat,
    RagBuildJobStep,
)
from app.rag.build import RagBuildSourceStats
from app.utils import current_time_utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from app.rag.pipeline import RagPipelineProgressSnapshot

logger = logging.getLogger(__name__)


def _duration_ms(started_at: datetime, finished_at: datetime) -> float:
    return max((finished_at - started_at).total_seconds() * 1000, 0.0)


async def create_rag_build_job(
    *, job_name: str, trigger: str, force_rebuild: bool, started_by_user_id: UUID | None
) -> UUID:
    async with get_session() as session:
        now = current_time_utc()
        job = RagBuildJob(
            job_name=job_name,
            trigger=trigger,
            status="pending",
            force_rebuild=force_rebuild,
            started_by_user_id=started_by_user_id,
            started_at=now,
        )
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
        return job_id


async def start_rag_build_job(job_id: UUID) -> None:
    async with get_session() as session:
        job = await session.scalar(
            select(RagBuildJob).where(RagBuildJob.id == job_id).with_for_update()
        )
        if job is None:
            raise RuntimeError(f"RAG build job {job_id} no longer exists")
        if job.status != "pending":
            raise RuntimeError(f"RAG build job {job_id} cannot start from status {job.status}")
        job.status = "running"
        await session.commit()


async def record_rag_build_progress(job_id: UUID, snapshot: RagPipelineProgressSnapshot) -> None:
    async with get_session() as session:
        job = await session.scalar(select(RagBuildJob).where(RagBuildJob.id == job_id))
        if job is None:
            logger.warning("Skipping RAG build progress update for missing job %s", job_id)
            return
        if job.status not in {"running", "cancelling"}:
            logger.warning(
                "Skipping RAG build progress update for terminal job %s with status %s",
                job_id,
                job.status,
            )
            return

        now = current_time_utc()
        job.current_step = snapshot.current_step

        existing_steps = {
            step.step_key: step
            for step in (
                await session.execute(
                    select(RagBuildJobStep).where(RagBuildJobStep.job_id == job_id)
                )
            )
            .scalars()
            .all()
        }

        for step_snapshot in snapshot.steps:
            step_key = step_snapshot.key
            step = existing_steps.get(step_key)
            if step is None:
                step = RagBuildJobStep(
                    job_id=job_id,
                    step_key=step_key,
                    label=step_snapshot.label,
                    status=step_snapshot.status,
                )
                session.add(step)

            step.label = step_snapshot.label
            step.status = step_snapshot.status
            if step_snapshot.status == "running" and step.started_at is None:
                step.started_at = now
            if step_snapshot.status in {"completed", "skipped", "error"}:
                if step.started_at is None:
                    step.started_at = now
                if step.finished_at is None:
                    step.finished_at = now

        await session.commit()


async def record_rag_build_source_stats(job_id: UUID, stats: RagBuildSourceStats) -> None:
    async with get_session() as session:
        document_type = stats.document_type.value
        await session.execute(
            delete(RagBuildJobSourceStat).where(
                RagBuildJobSourceStat.job_id == job_id,
                RagBuildJobSourceStat.source_name == stats.source_name,
                RagBuildJobSourceStat.document_type == document_type,
            )
        )
        await session.execute(
            delete(RagBuildJobDocumentChange).where(
                RagBuildJobDocumentChange.job_id == job_id,
                RagBuildJobDocumentChange.source_name == stats.source_name,
                RagBuildJobDocumentChange.document_type == document_type,
            )
        )

        session.add(
            RagBuildJobSourceStat(
                job_id=job_id,
                source_name=stats.source_name,
                document_type=document_type,
                new_count=stats.new_count,
                changed_count=stats.changed_count,
                deleted_count=stats.deleted_count,
                unchanged_count=stats.unchanged_count,
                source_document_count=stats.source_document_count,
                existing_document_count=stats.existing_document_count,
            )
        )
        session.add_all(
            RagBuildJobDocumentChange(
                job_id=job_id,
                source_name=stats.source_name,
                document_type=document_type,
                change_type=change.change_type,
                source_id=change.source_id,
                source_key=change.source_key,
                title=change.title,
                url=change.url,
                previous_title=change.previous_title,
                previous_url=change.previous_url,
                source_updated_at=change.source_updated_at,
                previous_source_updated_at=change.previous_source_updated_at,
            )
            for change in stats.document_changes
        )
        await session.commit()


async def finish_rag_build_job(
    job_id: UUID, *, status: str, error_message: str | None = None
) -> None:
    async with get_session() as session:
        job = await session.scalar(select(RagBuildJob).where(RagBuildJob.id == job_id))
        if job is None:
            logger.warning("Skipping RAG build finish update for missing job %s", job_id)
            return

        if job.status not in {"pending", "running", "cancelling"}:
            logger.warning(
                "Skipping RAG build finish update for terminal job %s with status %s",
                job_id,
                job.status,
            )
            return

        finished_at = current_time_utc()
        job.status = status
        job.finished_at = finished_at
        job.duration_ms = _duration_ms(job.started_at, finished_at)
        job.current_step = None
        job.error_message = error_message
        await session.commit()


async def request_active_manual_rag_build_cancellation() -> UUID | None:
    async with get_session() as session:
        job = await session.scalar(
            select(RagBuildJob)
            .where(
                RagBuildJob.trigger == "manual", RagBuildJob.status.in_(("running", "cancelling"))
            )
            .order_by(desc(RagBuildJob.started_at), desc(RagBuildJob.id))
            .limit(1)
        )
        if job is None:
            return None

        if job.status != "cancelling":
            job.status = "cancelling"
            await session.commit()

        return job.id


async def rag_build_cancellation_requested(job_id: UUID) -> bool:
    async with get_session() as session:
        status = await session.scalar(select(RagBuildJob.status).where(RagBuildJob.id == job_id))
        return status in {"cancelling", "cancelled"}
