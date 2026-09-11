from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.core.config import settings
from app.core.db import get_session
from app.core.rbac import PermissionKey, get_effective_permission_map
from app.models import ComplianceScreening, User
from app.utils import current_time_utc

from .admission import NoEligibleMessagesError, ScreeningTooLargeError, admit_screening
from .failures import SCHEDULED_TOO_LARGE
from .queries import current_instructions
from .screener import OUTPUT_TOKENS, SCREENING_VERSION

logger = logging.getLogger(__name__)

SCHEDULER_USER_NAME = "Screening Scheduler"
SCHEDULER_USER_EMAIL = "screening-scheduler@system.invalid"
SCHEDULER_TIMEZONE = "America/New_York"
_EASTERN = ZoneInfo(SCHEDULER_TIMEZONE)
_REQUIRED_PERMISSIONS = (
    PermissionKey.ACCESS_COMPLIANCE,
    PermissionKey.CHATS_VIEW_USERS,
    PermissionKey.CHATS_VIEW_ADMINS,
)


def previous_eastern_day(now: datetime) -> tuple[date, datetime, datetime]:
    local_date = now.astimezone(_EASTERN).date() - timedelta(days=1)
    start = datetime.combine(local_date, time.min, tzinfo=_EASTERN).astimezone(UTC)
    end = (
        datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=_EASTERN)
        - timedelta(microseconds=1)
    ).astimezone(UTC)
    return local_date, start, end


def scheduled_screening_id(local_date: date) -> UUID:
    return uuid5(NAMESPACE_URL, f"demo:compliance-screening:{local_date.isoformat()}")


async def admit_daily_screening(*, now: datetime | None = None) -> UUID | None:
    if not settings.COMPLIANCE_WORKER_ENABLED:
        logger.warning("Skipping scheduled screening because the Compliance worker is disabled")
        return None

    requested_at = now or current_time_utc()
    local_date, start, end = previous_eastern_day(requested_at)
    screening_id = scheduled_screening_id(local_date)

    async with get_session() as session:
        requester = await session.scalar(select(User).where(User.email == SCHEDULER_USER_EMAIL))
        if requester is None or not requester.is_active:
            raise RuntimeError("The Screening Scheduler service user is unavailable")
        if requester.name != SCHEDULER_USER_NAME:
            raise RuntimeError("The Screening Scheduler service user has an invalid name")

        existing = await session.get(ComplianceScreening, screening_id)
        if existing is not None:
            if (
                existing.created_by_id != requester.id
                or existing.start_at != start
                or existing.end_at != end
            ):
                raise RuntimeError("The scheduled screening identifier is already in use")
            logger.info("Scheduled screening for %s already exists", local_date)
            return existing.id

        permissions = await get_effective_permission_map(session, requester)
        missing_permissions = [
            permission.value
            for permission in _REQUIRED_PERMISSIONS
            if not permissions.get(permission)
        ]
        if missing_permissions:
            raise RuntimeError(
                "The Screening Scheduler service user is missing required permissions: "
                + ", ".join(missing_permissions)
            )

        await session.execute(text("SELECT pg_advisory_xact_lock(74218)"))
        instructions = await current_instructions(session)
        if instructions is None:
            logger.warning("Skipping scheduled screening because no instructions are saved")
            return None

        try:
            screening = await admit_screening(
                session,
                screening_id=screening_id,
                requester=requester,
                permissions=permissions,
                instructions=instructions,
                start=start,
                end=end,
                requested_at=requested_at,
            )
        except NoEligibleMessagesError:
            logger.info("Skipping scheduled screening for %s: no eligible messages", local_date)
            return None
        except ScreeningTooLargeError:
            screening = ComplianceScreening(
                id=screening_id,
                created_at=requested_at,
                created_by_id=requester.id,
                instructions_version_id=instructions.id,
                start_at=start,
                end_at=end,
                model_name=settings.COMPLIANCE_MODEL,
                screening_version=SCREENING_VERSION,
                model_settings={
                    "max_tokens": OUTPUT_TOKENS,
                    "max_input_characters": settings.COMPLIANCE_MAX_INPUT_CHARACTERS,
                },
                admission_error_code=SCHEDULED_TOO_LARGE,
            )
            session.add(screening)
            await session.flush()
            logger.warning(
                "Scheduled screening for %s exceeds the %s-message limit",
                local_date,
                settings.COMPLIANCE_MAX_MESSAGES,
            )
            return screening.id

        logger.info("Created scheduled screening %s for %s", screening.id, local_date)
        return screening.id
