from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select

from app.core.db import get_session
from app.models import RagBuildJob
from app.rag.build_notifications import active_manual_rag_build_snapshot_events
from app.rag.job_tracking import create_rag_build_job, finish_rag_build_job, start_rag_build_job

if TYPE_CHECKING:
    from uuid import UUID


@pytest.mark.asyncio
async def test_rag_job_becomes_active_only_after_executor_owns_it(db_engine: object) -> None:
    del db_engine
    pending_job_id = await create_rag_build_job(
        job_name="test_pending_rag_job",
        trigger="manual",
        force_rebuild=False,
        started_by_user_id=None,
    )
    skipped_job_id: UUID | None = None

    try:
        active_job_id, events = await active_manual_rag_build_snapshot_events()
        assert active_job_id is None
        assert events == []

        await start_rag_build_job(pending_job_id)
        active_job_id, events = await active_manual_rag_build_snapshot_events()
        assert active_job_id == pending_job_id
        assert events == [("status", {"job_id": str(pending_job_id), "status": "start"})]

        await finish_rag_build_job(pending_job_id, status="completed")

        skipped_job_id = await create_rag_build_job(
            job_name="test_skipped_rag_job",
            trigger="manual",
            force_rebuild=False,
            started_by_user_id=None,
        )
        await finish_rag_build_job(
            skipped_job_id, status="skipped", error_message="RAG build is already running"
        )

        async with get_session() as session:
            skipped_job = await session.scalar(
                select(RagBuildJob).where(RagBuildJob.id == skipped_job_id)
            )
        assert skipped_job is not None
        assert skipped_job.status == "skipped"
        assert skipped_job.finished_at is not None
    finally:
        async with get_session() as session:
            await session.execute(
                delete(RagBuildJob).where(
                    RagBuildJob.id.in_(
                        [pending_job_id, *([] if skipped_job_id is None else [skipped_job_id])]
                    )
                )
            )
            await session.commit()
