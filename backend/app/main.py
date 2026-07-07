from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.otel import configure_otel_span_processor
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
    logger.info("Starting scheduler")

    configure_scheduler_jobs()

    scheduler.start()
    logger.info("Scheduler started successfully")

    yield

    logger.info("Shutting down scheduler")
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan if settings.SCHEDULER else None,
    openapi_url=f"{settings.API_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

if settings.ALL_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALL_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def add_teams_frame_ancestors_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
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

    return response


app.include_router(api_router, prefix=settings.API_STR)
