import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.compliance.scheduled import SCHEDULER_TIMEZONE, admit_daily_screening
from app.core.db import engine
from app.rag.pipeline import RagPipelineAlreadyRunningError, run_rag_sync_pipeline

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_SYNC_DATA_LOCK_ID = 20_260_407_03
_SCHEDULED_SCREENING_LOCK_ID = 20_260_407_04


def configure_scheduler_jobs() -> None:
    scheduler.add_job(  # type: ignore[call-arg]
        scheduled_screening_job,
        trigger="cron",
        hour=2,
        minute=30,
        timezone=SCHEDULER_TIMEZONE,
        max_instances=1,
        coalesce=True,
        id="scheduled_screening",
        replace_existing=True,
    )
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


async def scheduled_screening_job() -> None:
    async with _job_lock(
        _SCHEDULED_SCREENING_LOCK_ID, job_name="scheduled_screening_job"
    ) as acquired:
        if not acquired:
            return

        try:
            await admit_daily_screening()
        except Exception:
            logger.exception("Scheduled screening failed")


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
