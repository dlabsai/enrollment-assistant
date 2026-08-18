from __future__ import annotations

import asyncio
import contextlib
import signal

from app.chat.provider_http import close_provider_http_clients
from app.chat.tools.utils import close_embedding_client
from app.core.config import settings
from app.core.db import close_database_pools
from app.otel import close_telemetry_database_pool, configure_otel_span_processor
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
        try:
            logger.info("Shutting down standalone scheduler")
            scheduler.shutdown()
            logger.info("Standalone scheduler stopped")
        finally:
            try:
                await close_embedding_client()
            finally:
                try:
                    await close_provider_http_clients()
                finally:
                    try:
                        await close_database_pools()
                    finally:
                        await close_telemetry_database_pool()


if __name__ == "__main__":
    asyncio.run(main())
