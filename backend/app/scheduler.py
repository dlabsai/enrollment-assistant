import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.chat.generation_attempts import fail_stale_generation_attempts
from app.chat_insights.scheduled import admit_nightly_run
from app.compliance.scheduled import SCHEDULER_TIMEZONE, admit_daily_screening
from app.core.db import engine, get_session
from app.rag.pipeline import RagPipelineAlreadyRunningError, run_rag_sync_pipeline
from app.utils import current_time_utc

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_SYNC_DATA_LOCK_ID = 20_260_407_03
_SCHEDULED_SCREENING_LOCK_ID = 20_260_407_04
_CHAT_INSIGHTS_LOCK_ID = 20_260_919_02


def configure_scheduler_jobs() -> None:
    scheduler.add_job(  # type: ignore[call-arg]
        fail_stale_generation_attempts_job,
        trigger="interval",
        minutes=5,
        next_run_time=current_time_utc(),
        max_instances=1,
        coalesce=True,
        id="fail_stale_generation_attempts",
        replace_existing=True,
    )
    scheduler.add_job(  # type: ignore[call-arg]
        scheduled_chat_insights_job,
        trigger="cron",
        hour=1,
        minute=0,
        timezone=SCHEDULER_TIMEZONE,
        max_instances=1,
        coalesce=True,
        id="scheduled_chat_insights",
        replace_existing=True,
    )
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


async def fail_stale_generation_attempts_job() -> None:
    try:
        async with get_session() as session:
            failed_count = await fail_stale_generation_attempts(session)
        if failed_count:
            logger.warning("Marked %d stale chat generation attempts as failed", failed_count)
    except Exception:
        logger.exception("Stale chat generation attempt sweep failed")


async def scheduled_chat_insights_job() -> None:
    async with _job_lock(
        _CHAT_INSIGHTS_LOCK_ID, job_name="scheduled_chat_insights_job"
    ) as acquired:
        if not acquired:
            return

        try:
            await admit_nightly_run()
        except Exception:
            logger.exception("Scheduled chat-insight admission failed")


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
