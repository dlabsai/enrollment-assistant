from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.db import async_session_factory
from app.utils import logger

from .service import claim_next_run, execute_run


async def run_worker() -> None:
    while True:
        try:
            async with async_session_factory() as session:
                claim = await claim_next_run(session)
                await session.commit()
            if claim is not None:
                await execute_run(claim)
                continue
        except Exception:
            logger.warning("Chat-insight queue unavailable", exc_info=True)
        await asyncio.sleep(5)


def start_worker() -> asyncio.Task[None] | None:
    if not settings.CHAT_INSIGHTS_WORKER_ENABLED:
        return None
    return asyncio.create_task(run_worker(), name="chat-insights-worker")
