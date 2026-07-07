from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import RefreshToken, User


def _configure_teams_sso_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TEAMS_SSO_ENABLED", True)
    monkeypatch.setattr(settings, "TEAMS_SSO_TENANT_ID", "tenant-id")
    monkeypatch.setattr(settings, "TEAMS_SSO_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "TEAMS_SSO_RESOURCE", "api://client-id")


def _configure_cross_site_auth_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "REFRESH_TOKEN_COOKIE_SAMESITE", "none")
    monkeypatch.setattr(settings, "REFRESH_TOKEN_COOKIE_SECURE", True)


def _assert_embedded_auth_cookie(cookie_header: str, cookie_name: str) -> None:
    cookie_header_lower = cookie_header.lower()
    assert f"{cookie_name}=" in cookie_header
    assert "samesite=none" in cookie_header_lower
    assert "secure" in cookie_header_lower


def _origin_headers(origin: str) -> dict[str, str]:
    return {"Origin": origin}


async def _create_user(session: AsyncSession, *, email: str, password: str) -> User:
    group = await get_group_for_slug(session, SystemGroupSlug.USER)
    user = User(
        email=email,
        name="Test User",
        password_hash=get_password_hash(password),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_login_sets_refresh_cookie_and_refresh_rotates_token(
    transactional_session: AsyncSession,
) -> None:
    password = "StrongPassword123"  # noqa: S105
    user = await _create_user(
        transactional_session, email=f"auth-{uuid4()}@example.com", password=password
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login_response = await client.post(
            f"{settings.API_STR}/auth/login", json={"email": user.email, "password": password}
        )

        assert login_response.status_code == 200
        assert login_response.json() == {"success": True}
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
        assert settings.REFRESH_TOKEN_COOKIE_NAME in client.cookies
        initial_refresh_cookie = client.cookies[settings.REFRESH_TOKEN_COOKIE_NAME]

        me_response = await client.get(f"{settings.API_STR}/auth/me")

        assert me_response.status_code == 200
        assert me_response.json()["email"] == user.email

        refresh_response = await client.post(
            f"{settings.API_STR}/auth/refresh",
            headers=_origin_headers("http://testserver"),
            json={},
        )

        assert refresh_response.status_code == 200
        assert refresh_response.json() == {"success": True}
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
        assert client.cookies[settings.REFRESH_TOKEN_COOKIE_NAME] != initial_refresh_cookie

    tokens = list(
        (
            await transactional_session.scalars(
                select(RefreshToken)
                .where(RefreshToken.user_id == user.id)
                .order_by(RefreshToken.created_at)
            )
        ).all()
    )

    assert len(tokens) == 2
    assert tokens[0].revoked_at is not None
    assert tokens[0].replaced_by_token_hash == tokens[1].token_hash
    assert tokens[1].revoked_at is None


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token_and_clears_cookie(
    transactional_session: AsyncSession,
) -> None:
    password = "AnotherStrongPassword1"  # noqa: S105
    user = await _create_user(
        transactional_session, email=f"logout-{uuid4()}@example.com", password=password
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login_response = await client.post(
            f"{settings.API_STR}/auth/login", json={"email": user.email, "password": password}
        )

        assert login_response.status_code == 200
        cookie_value = client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        assert cookie_value

        logout_response = await client.post(
            f"{settings.API_STR}/auth/logout", headers=_origin_headers("http://testserver"), json={}
        )

        assert logout_response.status_code == 200
        assert logout_response.json() == {"success": True}
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME) is None
        assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME) is None

        me_response = await client.get(f"{settings.API_STR}/auth/me")
        assert me_response.status_code == 401

        refresh_response = await client.post(
            f"{settings.API_STR}/auth/refresh",
            headers=_origin_headers("http://testserver"),
            json={},
        )
        assert refresh_response.status_code == 401

    token = await transactional_session.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_not(None)
        )
    )
    assert token is not None


@pytest.mark.asyncio
async def test_login_upgrades_legacy_pbkdf2_password_hash(
    transactional_session: AsyncSession,
) -> None:
    password = "StrongPassword123"  # noqa: S105
    legacy_hash = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto").hash(password)
    group = await get_group_for_slug(transactional_session, SystemGroupSlug.USER)
    user = User(
        email=f"legacy-{uuid4()}@example.com",
        name="Legacy User",
        password_hash=legacy_hash,
        is_active=True,
        group_id=group.id,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    await transactional_session.refresh(user)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/auth/login", json={"email": user.email, "password": password}
        )

    assert response.status_code == 200

    await transactional_session.refresh(user)
    assert user.password_hash != legacy_hash
    assert user.password_hash.startswith("$argon2id$")


@pytest.mark.asyncio
async def test_logout_rejects_untrusted_origin_for_cookie_authenticated_request(
    transactional_session: AsyncSession,
) -> None:
    password = "AnotherStrongPassword1"  # noqa: S105
    user = await _create_user(
        transactional_session, email=f"csrf-logout-{uuid4()}@example.com", password=password
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login_response = await client.post(
            f"{settings.API_STR}/auth/login", json={"email": user.email, "password": password}
        )

        assert login_response.status_code == 200
        assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)

        logout_response = await client.post(
            f"{settings.API_STR}/auth/logout",
            headers=_origin_headers("https://evil.example"),
            json={},
        )

        assert logout_response.status_code == 403
        assert logout_response.json() == {
            "detail": "Untrusted Origin for cookie-authenticated request"
        }
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
        assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)


@pytest.mark.asyncio
async def test_refresh_rejects_untrusted_origin_for_cookie_authenticated_request(
    transactional_session: AsyncSession,
) -> None:
    password = "AnotherStrongPassword1"  # noqa: S105
    user = await _create_user(
        transactional_session, email=f"csrf-refresh-{uuid4()}@example.com", password=password
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login_response = await client.post(
            f"{settings.API_STR}/auth/login", json={"email": user.email, "password": password}
        )

        assert login_response.status_code == 200
        initial_refresh_cookie = client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        assert initial_refresh_cookie

        refresh_response = await client.post(
            f"{settings.API_STR}/auth/refresh",
            headers=_origin_headers("https://evil.example"),
            json={},
        )

        assert refresh_response.status_code == 403
        assert refresh_response.json() == {
            "detail": "Untrusted Origin for cookie-authenticated request"
        }
        assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME) == initial_refresh_cookie


@pytest.mark.asyncio
async def test_teams_sso_creates_user_and_sets_refresh_cookie(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_teams_sso_settings(monkeypatch)
    _configure_cross_site_auth_cookies(monkeypatch)
    teams_email = f"teams-{uuid4()}@example.com"
    teams_object_id = f"teams-object-{uuid4()}"

    async def fake_validate_teams_sso_token(_: str) -> auth_routes.TeamsSsoIdentity:
        return auth_routes.TeamsSsoIdentity(
            tenant_id="tenant-id", object_id=teams_object_id, email=teams_email, name="Teams User"
        )

    monkeypatch.setattr(auth_routes, "validate_teams_sso_token", fake_validate_teams_sso_token)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/auth/teams-sso", json={"token": "teams-token"}
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    cookie_headers = response.headers.get_list("set-cookie")
    _assert_embedded_auth_cookie(
        next(header for header in cookie_headers if settings.ACCESS_TOKEN_COOKIE_NAME in header),
        settings.ACCESS_TOKEN_COOKIE_NAME,
    )
    _assert_embedded_auth_cookie(
        next(header for header in cookie_headers if settings.REFRESH_TOKEN_COOKIE_NAME in header),
        settings.REFRESH_TOKEN_COOKIE_NAME,
    )

    user = await transactional_session.scalar(select(User).where(User.email == teams_email))
    assert user is not None
    assert user.name == "Teams User"
    assert user.entra_tenant_id == "tenant-id"
    assert user.entra_object_id == teams_object_id
    assert (
        user.group_id == (await get_group_for_slug(transactional_session, SystemGroupSlug.USER)).id
    )


@pytest.mark.asyncio
async def test_teams_sso_links_existing_user_by_email(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_teams_sso_settings(monkeypatch)
    teams_object_id = f"linked-object-{uuid4()}"
    mixed_case_email = f"Linked.User-{uuid4()}@Example.com"
    normalized_email = mixed_case_email.lower()

    existing_user = await _create_user(
        transactional_session,
        email=mixed_case_email,
        password="StrongPassword123",  # noqa: S106
    )
    existing_user.group_id = (
        await get_group_for_slug(transactional_session, SystemGroupSlug.ADMIN)
    ).id
    await transactional_session.commit()
    await transactional_session.refresh(existing_user)

    async def fake_validate_teams_sso_token(_: str) -> auth_routes.TeamsSsoIdentity:
        return auth_routes.TeamsSsoIdentity(
            tenant_id="tenant-id",
            object_id=teams_object_id,
            email=normalized_email,
            name="Linked Teams User",
        )

    monkeypatch.setattr(auth_routes, "validate_teams_sso_token", fake_validate_teams_sso_token)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/auth/teams-sso", json={"token": "teams-token"}
        )

    assert response.status_code == 200

    await transactional_session.refresh(existing_user)
    linked_users = list(
        (
            await transactional_session.scalars(
                select(User).where(func.lower(User.email) == normalized_email)
            )
        ).all()
    )
    assert len(linked_users) == 1
    linked_user = linked_users[0]
    assert linked_user.id == existing_user.id
    assert linked_user.name == "Linked Teams User"
    assert linked_user.email == normalized_email
    assert linked_user.entra_tenant_id == "tenant-id"
    assert linked_user.entra_object_id == teams_object_id
    assert linked_user.group_id == existing_user.group_id


@pytest.mark.asyncio
async def test_teams_sso_refresh_uses_embedded_cookie_settings(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_teams_sso_settings(monkeypatch)
    _configure_cross_site_auth_cookies(monkeypatch)
    teams_email = f"teams-refresh-{uuid4()}@example.com"
    teams_object_id = f"teams-refresh-object-{uuid4()}"

    async def fake_validate_teams_sso_token(_: str) -> auth_routes.TeamsSsoIdentity:
        return auth_routes.TeamsSsoIdentity(
            tenant_id="tenant-id",
            object_id=teams_object_id,
            email=teams_email,
            name="Teams Refresh User",
        )

    monkeypatch.setattr(auth_routes, "validate_teams_sso_token", fake_validate_teams_sso_token)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        login_response = await client.post(
            f"{settings.API_STR}/auth/teams-sso", json={"token": "teams-token"}
        )

        assert login_response.status_code == 200
        login_cookie_headers = login_response.headers.get_list("set-cookie")
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
        assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        _assert_embedded_auth_cookie(
            next(
                header
                for header in login_cookie_headers
                if settings.ACCESS_TOKEN_COOKIE_NAME in header
            ),
            settings.ACCESS_TOKEN_COOKIE_NAME,
        )
        _assert_embedded_auth_cookie(
            next(
                header
                for header in login_cookie_headers
                if settings.REFRESH_TOKEN_COOKIE_NAME in header
            ),
            settings.REFRESH_TOKEN_COOKIE_NAME,
        )

        initial_refresh_cookie = client.cookies[settings.REFRESH_TOKEN_COOKIE_NAME]
        refresh_response = await client.post(
            f"{settings.API_STR}/auth/refresh",
            headers=_origin_headers("https://testserver"),
            json={},
        )

        assert refresh_response.status_code == 200
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
        assert client.cookies[settings.REFRESH_TOKEN_COOKIE_NAME] != initial_refresh_cookie
        refresh_cookie_headers = refresh_response.headers.get_list("set-cookie")
        _assert_embedded_auth_cookie(
            next(
                header
                for header in refresh_cookie_headers
                if settings.ACCESS_TOKEN_COOKIE_NAME in header
            ),
            settings.ACCESS_TOKEN_COOKIE_NAME,
        )
        _assert_embedded_auth_cookie(
            next(
                header
                for header in refresh_cookie_headers
                if settings.REFRESH_TOKEN_COOKIE_NAME in header
            ),
            settings.REFRESH_TOKEN_COOKIE_NAME,
        )
