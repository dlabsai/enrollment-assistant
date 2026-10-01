from __future__ import annotations

from typing import TYPE_CHECKING

from app.chat.config import TEMPLATES_DIR
from app.chat.template_utils import create_jinja_environment_with_db, load_deployed_templates
from app.core.config import settings
from app.models import (
    ComplianceInstructionsVersion,
    ComplianceItem,
    ComplianceScreening,
    Message,
    PromptSetScope,
)

from .screener import OUTPUT_TOKENS, SCREENING_VERSION
from .sources import source_selection

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.rbac import PermissionKey
    from app.models import User


class NoEligibleMessagesError(Exception):
    pass


class ScreeningTooLargeError(Exception):
    pass


async def _load_agent_prompt(session: AsyncSession) -> str:
    _, templates = await load_deployed_templates(
        session, is_internal=True, scope=PromptSetScope.COMPLIANCE
    )
    environment = create_jinja_environment_with_db(TEMPLATES_DIR, templates, is_internal=True)
    return environment.get_template("compliance_screening_agent.j2").render()


async def admit_screening(
    session: AsyncSession,
    *,
    screening_id: UUID,
    requester: User,
    permissions: Mapping[PermissionKey, bool],
    instructions: ComplianceInstructionsVersion,
    start: datetime,
    end: datetime,
    requested_at: datetime,
) -> ComplianceScreening:
    selected = (
        await session.execute(
            source_selection(requester, permissions, start, min(end, requested_at))
            .order_by(Message.created_at, Message.id)
            .limit(settings.COMPLIANCE_MAX_MESSAGES + 1)
        )
    ).all()
    if not selected:
        raise NoEligibleMessagesError
    if len(selected) > settings.COMPLIANCE_MAX_MESSAGES:
        raise ScreeningTooLargeError

    agent_prompt = await _load_agent_prompt(session)
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
            "agent_prompt": agent_prompt,
        },
    )
    session.add(screening)
    await session.flush()
    session.add_all(
        ComplianceItem(
            screening_id=screening.id,
            message_id=message_id,
            conversation_id=conversation_id,
            owner_id=owner_id,
            requested_by_id=requester.id,
        )
        for message_id, conversation_id, owner_id in selected
    )
    await session.flush()
    return screening
