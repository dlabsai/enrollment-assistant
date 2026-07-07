import hashlib
import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import RefreshToken
from app.utils import current_time_utc

if TYPE_CHECKING:
    from uuid import UUID


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _build_expiry() -> timedelta:
    return timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


async def create_refresh_token(
    session: AsyncSession, user_id: UUID, *, user_agent: str | None, ip_address: str | None
) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = _hash_refresh_token(token)
    expires_at = current_time_utc() + _build_expiry()

    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    session.add(refresh_token)
    await session.commit()
    return token


async def rotate_refresh_token(
    session: AsyncSession, token: str, *, user_agent: str | None, ip_address: str | None
) -> tuple[UUID, str]:
    token_hash = _hash_refresh_token(token)
    refresh_token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    now = current_time_utc()
    if refresh_token.revoked_at is not None:
        await _revoke_all_for_user(session, refresh_token.user_id, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token reuse detected"
        )

    if refresh_token.expires_at <= now:
        refresh_token.revoked_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )

    new_token = secrets.token_urlsafe(48)
    new_token_hash = _hash_refresh_token(new_token)

    refresh_token.revoked_at = now
    refresh_token.replaced_by_token_hash = new_token_hash

    new_refresh = RefreshToken(
        user_id=refresh_token.user_id,
        token_hash=new_token_hash,
        expires_at=now + _build_expiry(),
        user_agent=user_agent,
        ip_address=ip_address,
    )

    session.add(new_refresh)
    await session.commit()
    return refresh_token.user_id, new_token


async def revoke_refresh_token(session: AsyncSession, token: str) -> None:
    token_hash = _hash_refresh_token(token)
    refresh_token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if refresh_token is None or refresh_token.revoked_at is not None:
        return

    refresh_token.revoked_at = current_time_utc()
    await session.commit()


async def _revoke_all_for_user(session: AsyncSession, user_id: UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.commit()
