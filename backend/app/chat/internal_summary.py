import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai import ModelRequest
from pydantic_ai.direct import model_request
from pydantic_ai.messages import TextPart
from sqlalchemy import select

from app.chat.agents import get_pydantic_ai_model_name
from app.chat.template_utils import get_runtime_jinja_environment
from app.chat.tree_utils import get_current_branch_path
from app.core.config import settings
from app.core.db import get_session
from app.models import Conversation, Message, PromptSetScope
from app.otel_genai import genai_agent_name_scope

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _format_transcript(messages: Iterable[Message]) -> str:
    lines: list[str] = []
    for message in messages:
        role = "Staff" if message.role == "user" else "Assistant"
        content = _message_content_for_summary(message)
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def _message_content_for_summary(message: Message) -> str:
    if message.role == "assistant" and message.guardrails_blocked:
        blocked_message = message.guardrails_blocked_message or settings.GUARDRAILS_BLOCKED_MESSAGE
        return (
            "[This assistant response was blocked by guardrails. "
            f"The user was shown this message instead: {blocked_message}]"
        )
    return message.content


async def _get_active_transcript(conversation_id: UUID) -> str | None:
    async with get_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if not conversation:
            logger.warning(
                "Conversation not found while building internal summary",
                extra={"conversation_id": str(conversation_id)},
            )
            return None
        # Skip summary for public conversations
        if conversation.is_public:
            logger.debug(
                "Skipping summary generation for public conversation",
                extra={"conversation_id": str(conversation_id)},
            )
            return None

        message_path = await get_current_branch_path(session, conversation_id)
        if not message_path:
            logger.debug(
                "No messages found for internal conversation; skipping summary",
                extra={"conversation_id": str(conversation_id)},
            )
            return None

        stmt = select(Message).where(Message.id.in_(message_path))
        result = await session.execute(stmt)
        messages = list(result.scalars().all())

        messages_by_id = {message.id: message for message in messages}
        ordered_messages = [
            messages_by_id[msg_id] for msg_id in message_path if msg_id in messages_by_id
        ]

        if not ordered_messages:
            logger.debug(
                "Could not resolve ordered messages for summary",
                extra={"conversation_id": str(conversation_id)},
            )
            return None

        return _format_transcript(ordered_messages)


async def _generate_internal_summary(transcript: str) -> str:
    env = await get_runtime_jinja_environment(
        TEMPLATES_DIR, is_internal=True, scope=PromptSetScope.SUMMARY
    )
    template = env.get_template("summary_agent.j2")
    prompt = template.render(transcript=transcript)

    with genai_agent_name_scope("summary"):
        model_response = await model_request(
            get_pydantic_ai_model_name(settings.SUMMARIZER_MODEL),
            [ModelRequest.user_text_prompt(prompt)],
        )

    first_part = model_response.parts[0]
    if isinstance(first_part, TextPart):
        return first_part.content

    logger.warning(
        "Unexpected response part while generating internal summary",
        extra={"part_type": type(first_part)},
    )
    return "Summary generation returned an unexpected format."


async def summarize_internal_conversation(conversation_id: UUID) -> None:
    """Generate and persist a summary for an internal conversation without blocking the request."""
    try:
        transcript = await _get_active_transcript(conversation_id)
        if not transcript:
            return

        summary = await _generate_internal_summary(transcript)

        async with get_session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if not conversation:
                logger.warning(
                    "Conversation disappeared before saving summary",
                    extra={"conversation_id": str(conversation_id)},
                )
                return

            conversation.summary = summary
    except Exception:
        logger.exception(
            "Failed to generate or save internal conversation summary",
            extra={"conversation_id": str(conversation_id)},
        )
