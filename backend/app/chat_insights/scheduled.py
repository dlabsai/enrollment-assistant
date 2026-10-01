from __future__ import annotations

from app.core.config import settings
from app.core.db import get_session
from app.utils import current_time_utc, logger

from .service import admit_run

SCHEDULER_TIMEZONE = "America/New_York"


async def admit_nightly_run() -> None:
    if not settings.CHAT_INSIGHTS_WORKER_ENABLED:
        logger.warning("Skipping nightly chat insights because its worker is disabled")
        return
    async with get_session() as session:
        admission = await admit_run(
            session, trigger="scheduled", requested_by_user_id=None, cutoff_at=current_time_utc()
        )
        if admission.created:
            logger.info("Queued nightly chat-insight run %s", admission.run.id)
        else:
            logger.info("Chat-insight run %s is already active", admission.run.id)
