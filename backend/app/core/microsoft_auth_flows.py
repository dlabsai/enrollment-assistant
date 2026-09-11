import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import MicrosoftBrowserAuthFlow
from app.utils import current_time_utc


class InvalidMicrosoftAuthFlowError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ConsumedMicrosoftAuthFlow:
    flow: dict[str, Any]
    return_path: str


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def store_microsoft_auth_flow(
    session: AsyncSession, *, flow: dict[str, Any], return_path: str
) -> str:
    state = flow.get("state")
    if not isinstance(state, str) or state == "":
        raise ValueError("Microsoft auth flow is missing state")

    now = current_time_utc()
    await session.execute(
        delete(MicrosoftBrowserAuthFlow).where(MicrosoftBrowserAuthFlow.expires_at <= now)
    )

    browser_binding = secrets.token_urlsafe(32)
    session.add(
        MicrosoftBrowserAuthFlow(
            state_hash=_hash_value(state),
            browser_binding_hash=_hash_value(browser_binding),
            flow=flow,
            return_path=return_path,
            expires_at=now + timedelta(minutes=settings.BROWSER_SSO_FLOW_EXPIRE_MINUTES),
        )
    )
    await session.commit()
    return browser_binding


async def consume_microsoft_auth_flow(
    session: AsyncSession, *, state: str, browser_binding: str
) -> ConsumedMicrosoftAuthFlow:
    stored_flow = await session.scalar(
        select(MicrosoftBrowserAuthFlow)
        .where(MicrosoftBrowserAuthFlow.state_hash == _hash_value(state))
        .with_for_update()
    )
    if stored_flow is None:
        raise InvalidMicrosoftAuthFlowError

    now = current_time_utc()
    if stored_flow.expires_at <= now:
        await session.delete(stored_flow)
        await session.commit()
        raise InvalidMicrosoftAuthFlowError

    if not secrets.compare_digest(stored_flow.browser_binding_hash, _hash_value(browser_binding)):
        raise InvalidMicrosoftAuthFlowError

    consumed = ConsumedMicrosoftAuthFlow(
        flow=dict(stored_flow.flow), return_path=stored_flow.return_path
    )
    await session.delete(stored_flow)
    await session.commit()
    return consumed
