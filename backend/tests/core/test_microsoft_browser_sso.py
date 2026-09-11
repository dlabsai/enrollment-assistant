from time import time
from typing import Any

import pytest

from app.core import microsoft_browser_sso
from app.core.config import settings


def _configure_browser_sso_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_SSO_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_SSO_TENANT_ID", "tenant-id")
    monkeypatch.setattr(settings, "BROWSER_SSO_CLIENT_ID", "client-id")
    monkeypatch.setattr(
        settings, "BROWSER_SSO_REDIRECT_URI", "https://app.example/api/auth/microsoft/callback"
    )
    monkeypatch.setattr(settings, "BROWSER_SSO_ALLOWED_EMAIL_DOMAIN", "example.edu")


def _identity_claims(*, email: str = "person@example.edu") -> dict[str, Any]:
    return {
        "iss": "https://login.microsoftonline.com/tenant-id/v2.0",
        "aud": "client-id",
        "tid": "tenant-id",
        "oid": "object-id",
        "name": "Post User",
        "preferred_username": email,
        "email": email,
        "exp": int(time()) + 300,
    }


@pytest.mark.asyncio
async def test_initiate_microsoft_browser_sso_uses_pkce_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_browser_sso_settings(monkeypatch)

    class FakeApplication:
        def initiate_auth_code_flow(self, **kwargs: Any) -> dict[str, str]:
            assert kwargs["scopes"] == ["email"]
            assert kwargs["redirect_uri"] == ("https://app.example/api/auth/microsoft/callback")
            assert kwargs["domain_hint"] == "example.edu"
            return {
                "auth_uri": "https://login.example/authorize",
                "state": "state",
                "code_verifier": "verifier",
            }

    monkeypatch.setattr(microsoft_browser_sso, "_create_application", FakeApplication)

    flow = await microsoft_browser_sso.initiate_microsoft_browser_sso()

    assert flow["state"] == "state"
    assert flow["code_verifier"] == "verifier"


@pytest.mark.asyncio
async def test_complete_microsoft_browser_sso_returns_validated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_browser_sso_settings(monkeypatch)

    class FakeApplication:
        def acquire_token_by_auth_code_flow(
            self, flow: dict[str, Any], auth_response: dict[str, str]
        ) -> dict[str, Any]:
            assert flow["state"] == auth_response["state"]
            return {"id_token_claims": _identity_claims()}

    monkeypatch.setattr(microsoft_browser_sso, "_create_application", FakeApplication)

    identity = await microsoft_browser_sso.complete_microsoft_browser_sso(
        flow={"state": "state"}, auth_response={"state": "state", "code": "code"}
    )

    assert identity.tenant_id == "tenant-id"
    assert identity.object_id == "object-id"
    assert identity.email == "person@example.edu"
    assert identity.name == "Post User"


@pytest.mark.asyncio
async def test_complete_microsoft_browser_sso_rejects_other_email_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_browser_sso_settings(monkeypatch)

    class FakeApplication:
        def acquire_token_by_auth_code_flow(
            self, flow: dict[str, Any], auth_response: dict[str, str]
        ) -> dict[str, Any]:
            del flow, auth_response
            return {"id_token_claims": _identity_claims(email="person@example.com")}

    monkeypatch.setattr(microsoft_browser_sso, "_create_application", FakeApplication)

    with pytest.raises(microsoft_browser_sso.MicrosoftBrowserSsoAuthenticationError):
        await microsoft_browser_sso.complete_microsoft_browser_sso(
            flow={"state": "state"}, auth_response={"state": "state", "code": "code"}
        )


@pytest.mark.asyncio
async def test_complete_microsoft_browser_sso_rejects_microsoft_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_browser_sso_settings(monkeypatch)

    class FakeApplication:
        def acquire_token_by_auth_code_flow(
            self, flow: dict[str, Any], auth_response: dict[str, str]
        ) -> dict[str, str]:
            del flow, auth_response
            return {"error": "interaction_required"}

    monkeypatch.setattr(microsoft_browser_sso, "_create_application", FakeApplication)

    with pytest.raises(microsoft_browser_sso.MicrosoftBrowserSsoAuthenticationError):
        await microsoft_browser_sso.complete_microsoft_browser_sso(
            flow={"state": "state"}, auth_response={"state": "state", "error": "access_denied"}
        )
