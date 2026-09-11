from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.main import app
from app.models import User

_TEST_USER_REGISTRATION_TOKEN = "test-user-registration-token"  # noqa: S105


def _registration_payload(*, email: str, token: str) -> dict[str, str]:
    password = "StrongPassword123!"  # noqa: S105
    return {
        "name": "Registration Test User",
        "email": email,
        "password": password,
        "confirm_password": password,
        "registration_token": token,
    }


@pytest.mark.asyncio
async def test_password_registration_is_rejected_when_disabled(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PASSWORD_REGISTRATION_ENABLED", False)
    monkeypatch.setattr(settings, "USER_REGISTRATION_TOKEN", _TEST_USER_REGISTRATION_TOKEN)
    email = f"registration-disabled-{uuid4()}@example.com"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/auth/register",
            json=_registration_payload(email=email, token=_TEST_USER_REGISTRATION_TOKEN),
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Password registration is not enabled"}
    assert await transactional_session.scalar(select(User).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_password_registration_accepts_configured_token_when_enabled(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"registration-enabled-{uuid4()}@example.com"
    monkeypatch.setattr(settings, "PASSWORD_REGISTRATION_ENABLED", True)
    monkeypatch.setattr(settings, "USER_REGISTRATION_TOKEN", _TEST_USER_REGISTRATION_TOKEN)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/auth/register",
            json=_registration_payload(email=email, token=_TEST_USER_REGISTRATION_TOKEN),
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}

    user = await transactional_session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert (
        user.group_id == (await get_group_for_slug(transactional_session, SystemGroupSlug.USER)).id
    )
