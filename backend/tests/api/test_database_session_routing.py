from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.deps import SessionDep

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "route_path", "request_path", "expected_pool"),
    [
        ("GET", "/conversations", "/conversations", "interactive"),
        ("GET", "/conversations/paginated", "/conversations/paginated", "interactive"),
        ("GET", "/messages", "/messages", "interactive"),
        ("GET", "/feedback", "/feedback", "interactive"),
        ("GET", "/feedback/export", "/feedback/export", "main"),
        ("GET", "/conversations/{conversation_id}", "/conversations/123", "main"),
        ("POST", "/messages", "/messages", "main"),
    ],
)
async def test_request_uses_the_pool_reserved_for_its_route(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    route_path: str,
    request_path: str,
    expected_pool: str,
) -> None:
    @asynccontextmanager
    async def main_session() -> AsyncGenerator[AsyncSession]:
        yield cast(AsyncSession, "main")

    @asynccontextmanager
    async def interactive_session() -> AsyncGenerator[AsyncSession]:
        yield cast(AsyncSession, "interactive")

    monkeypatch.setattr(deps, "get_session", main_session)
    monkeypatch.setattr(deps, "get_interactive_session", interactive_session)

    app = FastAPI()
    router = APIRouter()

    async def endpoint(session: SessionDep) -> dict[str, str]:
        return {"pool": cast(str, session)}

    router.add_api_route(route_path, endpoint, methods=[method])
    app.include_router(router, prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.request(method, f"/api{request_path}")

    assert response.status_code == 200
    assert response.json() == {"pool": expected_pool}
