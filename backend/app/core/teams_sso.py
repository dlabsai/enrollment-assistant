from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, status
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization
from joserfc.jwt import JWTClaimsRegistry
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.config import settings

_OPENID_CONFIGURATION_TIMEOUT_SECONDS = 10.0
_OPENID_CONFIGURATION_ADAPTER = TypeAdapter(dict[str, Any])


class _JwksPayload(BaseModel):
    keys: list[dict[str, str | list[str]]]


@dataclass(frozen=True, slots=True)
class TeamsSsoIdentity:
    tenant_id: str
    object_id: str
    email: str
    name: str


async def validate_teams_sso_token(token: str) -> TeamsSsoIdentity:
    _ensure_teams_sso_is_configured()

    openid_configuration = await _fetch_openid_configuration()
    jwks_uri = _read_jwks_uri(openid_configuration)
    try:
        key_set = KeySet.import_key_set(await _fetch_jwks(jwks_uri))
    except (TypeError, ValueError, JoseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid Teams SSO signing keys payload",
        ) from exc

    try:
        decoded_token = jwt.decode(token, key_set, algorithms=["RS256"])
        claims = decoded_token.claims
        JWTClaimsRegistry(
            exp={"essential": True},
            iss={"essential": True, "values": list(_allowed_issuers())},
            aud={"essential": True, "values": settings.TEAMS_SSO_AUDIENCE_VALUES},
            tid={"essential": True, "value": settings.TEAMS_SSO_TENANT_ID},
            oid={"essential": True},
        ).validate(claims)
    except JoseError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Teams SSO token"
        ) from exc

    claims_dict = dict(claims)
    tenant_id = _read_required_string_claim(claims_dict, "tid")
    object_id = _read_required_string_claim(claims_dict, "oid")
    email = _extract_email(claims_dict)
    name = _extract_name(claims_dict, email)

    return TeamsSsoIdentity(tenant_id=tenant_id, object_id=object_id, email=email, name=name)


def _ensure_teams_sso_is_configured() -> None:
    if not settings.TEAMS_SSO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Teams SSO is not enabled"
        )

    if settings.TEAMS_SSO_TENANT_ID == "" or not settings.TEAMS_SSO_AUDIENCE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Teams SSO is not fully configured",
        )


async def _fetch_openid_configuration() -> dict[str, Any]:
    configuration_url = (
        f"https://login.microsoftonline.com/{settings.TEAMS_SSO_TENANT_ID}"
        "/v2.0/.well-known/openid-configuration"
    )

    try:
        async with httpx.AsyncClient(timeout=_OPENID_CONFIGURATION_TIMEOUT_SECONDS) as client:
            response = await client.get(configuration_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to download Teams SSO metadata",
        ) from exc

    try:
        return _OPENID_CONFIGURATION_ADAPTER.validate_python(response.json())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid Teams SSO metadata response",
        ) from exc


async def _fetch_jwks(jwks_uri: str) -> KeySetSerialization:
    try:
        async with httpx.AsyncClient(timeout=_OPENID_CONFIGURATION_TIMEOUT_SECONDS) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to download Teams SSO signing keys",
        ) from exc

    try:
        payload = _JwksPayload.model_validate(response.json())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid Teams SSO signing key response",
        ) from exc

    return {"keys": payload.keys}


def _read_jwks_uri(openid_configuration: dict[str, Any]) -> str:
    jwks_uri = openid_configuration.get("jwks_uri")
    if isinstance(jwks_uri, str) and jwks_uri != "":
        return jwks_uri
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Teams SSO metadata is missing a JWKS URI",
    )


def _read_required_string_claim(claims: dict[str, Any], key: str) -> str:
    value = claims.get(key)
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Teams SSO token is missing the {key} claim",
    )


def _extract_email(claims: dict[str, Any]) -> str:
    for claim_name in ("email", "preferred_username", "upn"):
        value = claims.get(claim_name)
        if isinstance(value, str) and value.strip() != "" and "@" in value:
            return value.strip().lower()

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Teams SSO token is missing an email claim"
    )


def _extract_name(claims: dict[str, Any], fallback_email: str) -> str:
    for claim_name in ("name", "preferred_username", "upn"):
        value = claims.get(claim_name)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    return fallback_email


def _allowed_issuers() -> set[str]:
    tenant_id = settings.TEAMS_SSO_TENANT_ID
    return {
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://login.microsoftonline.com/{tenant_id}/",
        f"https://sts.windows.net/{tenant_id}/",
    }
