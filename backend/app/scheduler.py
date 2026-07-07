import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.core.db import engine
from app.rag.pipeline import RagPipelineAlreadyRunningError, run_rag_sync_pipeline

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_SYNC_DATA_LOCK_ID = 20_260_407_03


def configure_scheduler_jobs() -> None:
    scheduler.add_job(  # type: ignore[call-arg]
        sync_data_job,
        trigger="cron",
        hour=3,
        minute=0,
        timezone="America/New_York",
        max_instances=1,
        id="sync_data",
        replace_existing=True,
    )


@asynccontextmanager
async def _job_lock(lock_id: int, *, job_name: str) -> AsyncGenerator[bool]:
    async with engine.connect() as conn:
        acquired = bool(
            await conn.scalar(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id})
        )
        if not acquired:
            logger.info(
                "Skipping %s because another scheduler worker already holds the lock", job_name
            )
            yield False
            return

        try:
            yield True
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})


async def sync_data_job() -> None:
    """Run the shared RAG data synchronization pipeline on the scheduler cadence."""
    async with _job_lock(_SYNC_DATA_LOCK_ID, job_name="sync_data_job") as acquired:
        if not acquired:
            return

        logger.info("Starting scheduled data sync job")

        try:
            await run_rag_sync_pipeline(job_name="sync_data_job", job_trigger="scheduled")
            logger.info("Data sync job completed successfully")
        except RagPipelineAlreadyRunningError:
            logger.info(
                "Skipping sync_data_job because another RAG pipeline worker already holds the lock"
            )
        except Exception:
            logger.exception("Error in sync_data_job")
