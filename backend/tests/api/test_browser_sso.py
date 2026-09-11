from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.core.entra_identity import EntraIdentity
from app.main import app
from app.models import MicrosoftBrowserAuthFlow, User


def _configure_browser_sso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_SSO_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_SSO_TENANT_ID", "tenant-id")
    monkeypatch.setattr(settings, "BROWSER_SSO_CLIENT_ID", "client-id")
    monkeypatch.setattr(
        settings, "BROWSER_SSO_REDIRECT_URI", "http://testserver/api/auth/microsoft/callback"
    )
    monkeypatch.setattr(settings, "BROWSER_SSO_ALLOWED_EMAIL_DOMAIN", "example.edu")
    monkeypatch.setattr(settings, "FRONTEND_HOST", "http://frontend.test")


def _flow() -> dict[str, str]:
    return {
        "auth_uri": "https://login.microsoftonline.test/authorize",
        "state": f"state-{uuid4()}",
        "code_verifier": f"verifier-{uuid4()}",
    }


@pytest.mark.asyncio
async def test_auth_config_reports_auth_feature_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_SSO_ENABLED", True)
    monkeypatch.setattr(settings, "PASSWORD_REGISTRATION_ENABLED", True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"{settings.API_STR}/auth/config")

    assert response.status_code == 200
    assert response.json() == {
        "browser_microsoft_sso_enabled": True,
        "password_registration_enabled": True,
    }


@pytest.mark.asyncio
async def test_browser_sso_start_is_disabled_by_default(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    del transactional_session
    monkeypatch.setattr(settings, "BROWSER_SSO_ENABLED", False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"{settings.API_STR}/auth/microsoft/start")

    assert response.status_code == 503
    assert response.json() == {"detail": "Browser Microsoft sign in is not enabled"}


@pytest.mark.asyncio
async def test_browser_sso_start_stores_flow_and_sets_binding_cookie(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_browser_sso(monkeypatch)
    flow = _flow()

    async def fake_initiate() -> dict[str, str]:
        return flow

    monkeypatch.setattr(auth_routes, "initiate_microsoft_browser_sso", fake_initiate)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"{settings.API_STR}/auth/microsoft/start", params={"return_to": "/chats?owner=me"}
        )

    assert response.status_code == 302
    assert response.headers["location"] == flow["auth_uri"]
    cookie_header = response.headers["set-cookie"].lower()
    assert settings.BROWSER_SSO_FLOW_COOKIE_NAME in cookie_header
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert f"path={settings.API_STR}/auth/microsoft" in cookie_header

    stored = await transactional_session.scalar(select(MicrosoftBrowserAuthFlow))
    assert stored is not None
    assert stored.flow == flow
    assert stored.return_path == "/chats?owner=me"


@pytest.mark.asyncio
async def test_browser_sso_start_rejects_external_return_path(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    del transactional_session
    _configure_browser_sso(monkeypatch)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"{settings.API_STR}/auth/microsoft/start",
            params={"return_to": "https://evil.example/steal"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid authentication return path"}


@pytest.mark.asyncio
async def test_browser_sso_callback_creates_local_session_with_same_origin_redirect(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_browser_sso(monkeypatch)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    flow = _flow()
    email = f"browser-{uuid4()}@example.edu"
    object_id = f"object-{uuid4()}"

    async def fake_initiate() -> dict[str, str]:
        return flow

    async def fake_complete(
        *, flow: dict[str, object], auth_response: dict[str, str]
    ) -> EntraIdentity:
        assert flow["state"] == auth_response["state"]
        assert auth_response["code"] == "authorization-code"
        return EntraIdentity(
            tenant_id="tenant-id", object_id=object_id, email=email, name="Browser User"
        )

    monkeypatch.setattr(auth_routes, "initiate_microsoft_browser_sso", fake_initiate)
    monkeypatch.setattr(auth_routes, "complete_microsoft_browser_sso", fake_complete)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        start_response = await client.get(
            f"{settings.API_STR}/auth/microsoft/start", params={"return_to": "/chats"}
        )
        assert start_response.status_code == 302

        callback_response = await client.get(
            f"{settings.API_STR}/auth/microsoft/callback",
            params={"state": flow["state"], "code": "authorization-code"},
        )

        assert callback_response.status_code == 302
        assert callback_response.headers["location"] == "/chats"
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
        assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        assert client.cookies.get(settings.BROWSER_SSO_FLOW_COOKIE_NAME) is None

    user = await transactional_session.scalar(select(User).where(func.lower(User.email) == email))
    assert user is not None
    assert user.name == "Browser User"
    assert user.entra_tenant_id == "tenant-id"
    assert user.entra_object_id == object_id
    assert await transactional_session.scalar(select(func.count(MicrosoftBrowserAuthFlow.id))) == 0


@pytest.mark.asyncio
async def test_browser_sso_callback_rejects_email_outside_allowed_domain(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_browser_sso(monkeypatch)
    flow = _flow()
    email = f"browser-{uuid4()}@example.com"

    async def fake_initiate() -> dict[str, str]:
        return flow

    async def fake_complete(
        *, flow: dict[str, object], auth_response: dict[str, str]
    ) -> EntraIdentity:
        del flow, auth_response
        return EntraIdentity(
            tenant_id="tenant-id", object_id=f"object-{uuid4()}", email=email, name="Wrong Domain"
        )

    monkeypatch.setattr(auth_routes, "initiate_microsoft_browser_sso", fake_initiate)
    monkeypatch.setattr(auth_routes, "complete_microsoft_browser_sso", fake_complete)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get(f"{settings.API_STR}/auth/microsoft/start")
        response = await client.get(
            f"{settings.API_STR}/auth/microsoft/callback",
            params={"state": flow["state"], "code": "authorization-code"},
        )

    assert response.status_code == 302
    assert response.headers["location"] == ("http://frontend.test/?auth_error=microsoft_sso")
    assert (
        await transactional_session.scalar(select(User).where(func.lower(User.email) == email))
        is None
    )


@pytest.mark.asyncio
async def test_browser_sso_callback_requires_the_starting_browser_cookie(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_browser_sso(monkeypatch)
    flow = _flow()

    async def fake_initiate() -> dict[str, str]:
        return flow

    monkeypatch.setattr(auth_routes, "initiate_microsoft_browser_sso", fake_initiate)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as starting_client:
        await starting_client.get(f"{settings.API_STR}/auth/microsoft/start")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as different_client:
        response = await different_client.get(
            f"{settings.API_STR}/auth/microsoft/callback",
            params={"state": flow["state"], "code": "authorization-code"},
        )

    assert response.status_code == 302
    assert response.headers["location"] == ("http://frontend.test/?auth_error=microsoft_sso")
    assert await transactional_session.scalar(select(MicrosoftBrowserAuthFlow)) is not None
