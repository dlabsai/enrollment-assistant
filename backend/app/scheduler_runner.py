from __future__ import annotations

import asyncio
import contextlib
import signal

from app.core.config import settings
from app.otel import configure_otel_span_processor
from app.scheduler import configure_scheduler_jobs, scheduler
from app.utils import configure_observability, logger


async def _wait_for_shutdown() -> None:
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signal_number, shutdown_event.set)

    await shutdown_event.wait()


async def main() -> None:
    configure_observability()
    configure_otel_span_processor()

    if not settings.SCHEDULER:
        logger.info("Standalone scheduler disabled because SCHEDULER=false")
        return

    logger.info("Starting standalone scheduler")
    configure_scheduler_jobs()
    scheduler.start()
    logger.info("Standalone scheduler started successfully")

    try:
        await _wait_for_shutdown()
    finally:
        logger.info("Shutting down standalone scheduler")
        scheduler.shutdown()
        logger.info("Standalone scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
