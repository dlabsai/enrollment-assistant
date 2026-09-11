import asyncio
from pathlib import Path
from time import time
from typing import Any, cast

import msal

from app.core.config import settings
from app.core.entra_identity import EntraIdentity

_SCOPES = ["email"]


class MicrosoftBrowserSsoConfigurationError(RuntimeError):
    pass


class MicrosoftBrowserSsoAuthenticationError(Exception):
    pass


class MicrosoftBrowserSsoUnavailableError(RuntimeError):
    pass


def _ensure_configuration() -> None:
    if not settings.BROWSER_SSO_ENABLED:
        raise MicrosoftBrowserSsoConfigurationError("Browser Microsoft SSO is not enabled")

    required_values = {
        "BROWSER_SSO_TENANT_ID": settings.BROWSER_SSO_TENANT_ID,
        "BROWSER_SSO_CLIENT_ID": settings.BROWSER_SSO_CLIENT_ID,
        "BROWSER_SSO_REDIRECT_URI": settings.BROWSER_SSO_REDIRECT_URI,
        "BROWSER_SSO_CERTIFICATE_THUMBPRINT": settings.BROWSER_SSO_CERTIFICATE_THUMBPRINT,
    }
    missing = [name for name, value in required_values.items() if value.strip() == ""]
    if missing:
        raise MicrosoftBrowserSsoConfigurationError(
            f"Browser Microsoft SSO is missing configuration: {', '.join(missing)}"
        )


def _certificate_private_key() -> str:
    private_key = settings.BROWSER_SSO_CERTIFICATE_PRIVATE_KEY.strip()
    if private_key:
        return private_key.replace("\\n", "\n")

    path_value = settings.BROWSER_SSO_CERTIFICATE_PRIVATE_KEY_PATH.strip()
    if path_value == "":
        raise MicrosoftBrowserSsoConfigurationError(
            "Browser Microsoft SSO certificate private key is not configured"
        )

    path = Path(path_value).expanduser()
    if not path.is_file():
        raise MicrosoftBrowserSsoConfigurationError(
            "Browser Microsoft SSO certificate private key file does not exist"
        )
    return path.read_text()


def _create_application() -> msal.ConfidentialClientApplication:
    _ensure_configuration()
    return msal.ConfidentialClientApplication(
        settings.BROWSER_SSO_CLIENT_ID.strip(),
        authority=(f"https://login.microsoftonline.com/{settings.BROWSER_SSO_TENANT_ID.strip()}"),
        client_credential={
            "thumbprint": settings.BROWSER_SSO_CERTIFICATE_THUMBPRINT.strip().replace(":", ""),
            "private_key": _certificate_private_key(),
        },
        timeout=settings.BROWSER_SSO_REQUEST_TIMEOUT_SECONDS,
        exclude_scopes=["offline_access"],
    )


def _initiate_auth_code_flow() -> dict[str, Any]:
    try:
        application = _create_application()
        flow = cast(
            "dict[str, Any]",
            application.initiate_auth_code_flow(  # pyright: ignore[reportUnknownMemberType]
                scopes=_SCOPES,
                redirect_uri=settings.BROWSER_SSO_REDIRECT_URI.strip(),
                domain_hint=settings.BROWSER_SSO_ALLOWED_EMAIL_DOMAIN.strip(),
            ),
        )
    except MicrosoftBrowserSsoConfigurationError:
        raise
    except Exception as exc:
        raise MicrosoftBrowserSsoUnavailableError("Failed to start browser Microsoft SSO") from exc

    auth_uri = flow.get("auth_uri")
    state = flow.get("state")
    code_verifier = flow.get("code_verifier")
    if not all(
        isinstance(value, str) and value != "" for value in (auth_uri, state, code_verifier)
    ):
        raise MicrosoftBrowserSsoUnavailableError(
            "Microsoft returned an incomplete browser auth flow"
        )
    return flow


async def initiate_microsoft_browser_sso() -> dict[str, Any]:
    return await asyncio.to_thread(_initiate_auth_code_flow)


def _read_required_string_claim(claims: dict[str, Any], key: str) -> str:
    value = claims.get(key)
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    raise MicrosoftBrowserSsoAuthenticationError(f"Microsoft identity is missing the {key} claim")


def _extract_email(claims: dict[str, Any]) -> str:
    for key in ("email", "preferred_username", "upn"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip() != "" and "@" in value:
            return value.strip().lower()
    raise MicrosoftBrowserSsoAuthenticationError("Microsoft identity is missing an email claim")


def _extract_name(claims: dict[str, Any], fallback_email: str) -> str:
    for key in ("name", "preferred_username", "upn"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    return fallback_email


def _validate_identity_claims(claims: dict[str, Any]) -> EntraIdentity:
    tenant_id = _read_required_string_claim(claims, "tid")
    if tenant_id != settings.BROWSER_SSO_TENANT_ID.strip():
        raise MicrosoftBrowserSsoAuthenticationError("Microsoft identity has the wrong tenant")

    audience = _read_required_string_claim(claims, "aud")
    if audience != settings.BROWSER_SSO_CLIENT_ID.strip():
        raise MicrosoftBrowserSsoAuthenticationError("Microsoft identity has the wrong audience")

    expected_issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    issuer = _read_required_string_claim(claims, "iss")
    if issuer != expected_issuer:
        raise MicrosoftBrowserSsoAuthenticationError("Microsoft identity has the wrong issuer")

    expires_at = claims.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int | float):
        raise MicrosoftBrowserSsoAuthenticationError(
            "Microsoft identity is missing the expiration claim"
        )
    if expires_at <= time():
        raise MicrosoftBrowserSsoAuthenticationError("Microsoft identity has expired")

    email = _extract_email(claims)
    expected_domain = settings.BROWSER_SSO_ALLOWED_EMAIL_DOMAIN.strip().casefold()
    _, separator, email_domain = email.rpartition("@")
    if separator == "" or email_domain.casefold() != expected_domain:
        raise MicrosoftBrowserSsoAuthenticationError(
            "Microsoft identity does not use an allowed email domain"
        )

    object_id = _read_required_string_claim(claims, "oid")
    return EntraIdentity(
        tenant_id=tenant_id, object_id=object_id, email=email, name=_extract_name(claims, email)
    )


def _complete_auth_code_flow(flow: dict[str, Any], auth_response: dict[str, str]) -> EntraIdentity:
    try:
        application = _create_application()
        result = cast(
            "dict[str, Any]",
            application.acquire_token_by_auth_code_flow(  # pyright: ignore[reportUnknownMemberType]
                flow, auth_response
            ),
        )
    except MicrosoftBrowserSsoConfigurationError:
        raise
    except ValueError as exc:
        raise MicrosoftBrowserSsoAuthenticationError(
            "Microsoft rejected the browser auth response"
        ) from exc
    except Exception as exc:
        raise MicrosoftBrowserSsoUnavailableError(
            "Failed to complete browser Microsoft SSO"
        ) from exc

    if isinstance(result.get("error"), str):
        raise MicrosoftBrowserSsoAuthenticationError("Microsoft did not complete browser sign in")

    claims = result.get("id_token_claims")
    if not isinstance(claims, dict):
        raise MicrosoftBrowserSsoAuthenticationError(
            "Microsoft sign in did not return identity claims"
        )
    return _validate_identity_claims(cast("dict[str, Any]", claims))


async def complete_microsoft_browser_sso(
    *, flow: dict[str, Any], auth_response: dict[str, str]
) -> EntraIdentity:
    return await asyncio.to_thread(_complete_auth_code_flow, flow, auth_response)
