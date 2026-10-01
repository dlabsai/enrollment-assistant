from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.chat.provider_http import close_provider_http_clients
from app.chat.tools.utils import close_embedding_client
from app.chat_insights.worker import start_worker as start_chat_insights_worker
from app.compliance.worker import start_worker
from app.core.config import settings
from app.core.db import close_database_pools
from app.db_observability import DatabaseObservabilityMiddleware
from app.otel import close_telemetry_database_pool, configure_otel_span_processor
from app.scheduler import configure_scheduler_jobs, scheduler
from app.utils import configure_observability, logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

configure_observability()
configure_otel_span_processor()

_TEAMS_FRAME_ANCESTORS = (
    "https://*.cloud.microsoft "
    "https://teams.microsoft.com "
    "https://*.teams.microsoft.com "
    "https://*.microsoft365.com "
    "https://*.office.com "
    "https://outlook.office.com "
    "https://outlook.office365.com "
    "https://outlook-sdf.office.com "
    "https://outlook-sdf.office365.com"
)


def custom_generate_unique_id(route: APIRoute) -> str:
    if route.tags:
        return f"{route.tags[0]}-{route.name}"
    return route.name


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    scheduler_started = False
    compliance_worker = start_worker()
    chat_insights_worker = start_chat_insights_worker()
    try:
        if settings.SCHEDULER:
            logger.info("Starting scheduler")

            configure_scheduler_jobs()

            scheduler.start()
            scheduler_started = True
            logger.info("Scheduler started successfully")

        yield
    finally:
        if chat_insights_worker is not None:
            chat_insights_worker.cancel()
            with suppress(asyncio.CancelledError):
                await chat_insights_worker
        if compliance_worker is not None:
            compliance_worker.cancel()
            with suppress(asyncio.CancelledError):
                await compliance_worker
        try:
            if scheduler_started:
                logger.info("Shutting down scheduler")
                scheduler.shutdown()
                logger.info("Scheduler stopped")
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


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    openapi_url=f"{settings.API_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)
app.add_middleware(DatabaseObservabilityMiddleware)

if settings.ALL_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALL_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def prevent_user_settings_caching(request: Request, response: Response) -> None:
    # Validation/auth failures can contain personal input too, before a route returns.
    if request.url.path.rstrip("/") == f"{settings.API_STR}/user-settings":
        response.headers["Cache-Control"] = "no-store"


@app.middleware("http")
async def add_response_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    prevent_user_settings_caching(request, response)
    if settings.TEAMS_SSO_ENABLED and "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = f"frame-ancestors {_TEAMS_FRAME_ANCESTORS};"
    return response


@app.exception_handler(Exception)
async def exception_handler(request: Request, exception: Exception) -> JSONResponse:
    # TODO: don't expose exception details in production
    response = JSONResponse(
        {"error": str(exception)}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )

    request_origin = request.headers.get("origin", "")
    if "*" in settings.ALL_CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif request_origin in settings.ALL_CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = request_origin

    # Unhandled errors are rendered outside the normal response-header middleware.
    prevent_user_settings_caching(request, response)
    return response


app.include_router(api_router, prefix=settings.API_STR)
