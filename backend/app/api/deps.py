from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import get_session
from app.core.rbac import PermissionKey, user_has_permission
from app.core.security import verify_token
from app.models import User

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with get_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _normalize_origin(value: str, *, header_name: str) -> str:
    stripped_value = value.strip()
    if stripped_value in {"", "null"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid {header_name} header for cookie-authenticated request",
        )

    parsed_value = urlsplit(stripped_value)
    if parsed_value.scheme == "" or parsed_value.netloc == "":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid {header_name} header for cookie-authenticated request",
        )

    return f"{parsed_value.scheme}://{parsed_value.netloc}".rstrip("/")


def _normalize_origin_candidate(value: str) -> str | None:
    stripped_value = value.strip()
    if stripped_value in {"", "null"}:
        return None

    parsed_value = urlsplit(stripped_value)
    if parsed_value.scheme == "" or parsed_value.netloc == "":
        return None

    return f"{parsed_value.scheme}://{parsed_value.netloc}".rstrip("/")


def _get_request_origin(request: Request) -> str | None:
    origin_header = request.headers.get("origin")
    if origin_header is not None:
        return _normalize_origin(origin_header, header_name="Origin")

    referer_header = request.headers.get("referer")
    if referer_header is not None:
        return _normalize_origin(referer_header, header_name="Referer")

    return None


def _get_trusted_origins(request: Request) -> set[str]:
    trusted_origins = {_normalize_origin(str(request.base_url), header_name="base URL")}
    trusted_origins.update(
        normalized_origin
        for origin in settings.ALL_CORS_ORIGINS
        if origin != "*"
        for normalized_origin in [_normalize_origin_candidate(origin)]
        if normalized_origin is not None
    )
    return trusted_origins


def enforce_trusted_cookie_auth_request(request: Request, *, cookie_names: tuple[str, ...]) -> None:
    if request.method.upper() in _SAFE_METHODS:
        return

    if not any((request.cookies.get(cookie_name) or "") != "" for cookie_name in cookie_names):
        return

    request_origin = _get_request_origin(request)
    if request_origin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cookie-authenticated unsafe requests require a trusted Origin or Referer",
        )

    if request_origin not in _get_trusted_origins(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Untrusted Origin for cookie-authenticated request",
        )


async def get_current_user(session: SessionDep, request: Request) -> User:
    enforce_trusted_cookie_auth_request(request, cookie_names=(settings.ACCESS_TOKEN_COOKIE_NAME,))
    token = request.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)

    if token is None or token == "":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication credentials required"
        )

    user_id = verify_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials"
        )

    user = await session.scalar(
        select(User).options(selectinload(User.group)).where(User.id == user_id)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin_user(current_user: CurrentUser) -> User:
    """Get current user only if they are an admin or dev."""
    if current_user.group.slug not in {"admin", "dev"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


AdminUser = Annotated[User, Depends(get_admin_user)]


async def get_dev_user(current_user: CurrentUser) -> User:
    """Get current user only if they are a dev."""
    if current_user.group.slug != "dev":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dev access required")
    return current_user


DevUser = Annotated[User, Depends(get_dev_user)]


def require_permission(permission_key: PermissionKey) -> Any:
    async def dependency(session: SessionDep, current_user: CurrentUser) -> User:
        if not await user_has_permission(session, current_user, permission_key):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return current_user

    return dependency


def require_any_permission(*permission_keys: PermissionKey) -> Any:
    if len(permission_keys) == 0:
        raise ValueError("At least one permission key is required")

    async def dependency(session: SessionDep, current_user: CurrentUser) -> User:
        for permission_key in permission_keys:
            if await user_has_permission(session, current_user, permission_key):
                return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return dependency
