from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.core import teams_sso
from app.core.config import settings


def _configure_teams_sso_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TEAMS_SSO_ENABLED", True)
    monkeypatch.setattr(settings, "TEAMS_SSO_TENANT_ID", "tenant-id")
    monkeypatch.setattr(settings, "TEAMS_SSO_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "TEAMS_SSO_RESOURCE", "api://client-id")
    monkeypatch.setattr(settings, "TEAMS_SSO_ALLOWED_AUDIENCES", "")


async def _install_jwks_mocks(monkeypatch: pytest.MonkeyPatch, public_jwk: dict[str, Any]) -> None:
    async def fake_fetch_openid_configuration() -> dict[str, str]:
        return {"jwks_uri": "https://example.test/jwks"}

    async def fake_fetch_jwks(jwks_uri: str) -> dict[str, list[dict[str, Any]]]:
        assert jwks_uri == "https://example.test/jwks"
        return {"keys": [public_jwk]}

    monkeypatch.setattr(teams_sso, "_fetch_openid_configuration", fake_fetch_openid_configuration)
    monkeypatch.setattr(teams_sso, "_fetch_jwks", fake_fetch_jwks)


def _build_teams_token(*, private_key: Any, audience: str) -> str:
    now = datetime.now(UTC)
    public_jwk = cast(dict[str, Any], private_key.as_dict(private=False))
    claims = {
        "iss": "https://login.microsoftonline.com/tenant-id/v2.0",
        "aud": audience,
        "tid": "tenant-id",
        "oid": f"oid-{uuid4()}",
        "name": "Teams Example User",
        "preferred_username": "Teams.User@Example.com",
        "email": "Teams.User@Example.com",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    return jwt.encode({"alg": "RS256", "kid": public_jwk["kid"]}, claims, private_key)


@pytest.mark.asyncio
async def test_validate_teams_sso_token_accepts_valid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_teams_sso_settings(monkeypatch)
    private_key: Any = RSAKey.generate_key(2048, private=True, auto_kid=True)
    public_jwk = cast(dict[str, Any], private_key.as_dict(private=False))
    await _install_jwks_mocks(monkeypatch, public_jwk)

    identity = await teams_sso.validate_teams_sso_token(
        _build_teams_token(private_key=private_key, audience="client-id")
    )

    assert identity.tenant_id == "tenant-id"
    assert identity.object_id.startswith("oid-")
    assert identity.email == "teams.user@example.com"
    assert identity.name == "Teams Example User"


@pytest.mark.asyncio
async def test_validate_teams_sso_token_rejects_invalid_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_teams_sso_settings(monkeypatch)
    private_key: Any = RSAKey.generate_key(2048, private=True, auto_kid=True)
    public_jwk = cast(dict[str, Any], private_key.as_dict(private=False))
    await _install_jwks_mocks(monkeypatch, public_jwk)

    with pytest.raises(HTTPException) as exc_info:
        await teams_sso.validate_teams_sso_token(
            _build_teams_token(private_key=private_key, audience="wrong-audience")
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid Teams SSO token"
