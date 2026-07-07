from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import User
from tests.api.auth_helpers import authenticate_client


async def _create_user(session: AsyncSession) -> User:
    group = await get_group_for_slug(session, SystemGroupSlug.USER)
    user = User(
        email=f"models-{uuid4()}@example.com",
        name="Models User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_models_route_returns_configured_and_cached_models(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(transactional_session)

    monkeypatch.setattr("app.api.routes.models.settings.MODELS", "azure/gpt-5.1,openrouter/*")
    monkeypatch.setattr("app.api.routes.models._openrouter_models", ["openrouter/test-model"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/models")

    assert response.status_code == 200
    assert response.json() == ["azure/gpt-5.1", "openrouter/test-model"]


@pytest.mark.asyncio
async def test_models_route_ignores_authorization_header_without_cookie() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": "ignored-token"},
    ) as client:
        response = await client.get("/api/models")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials required"}
