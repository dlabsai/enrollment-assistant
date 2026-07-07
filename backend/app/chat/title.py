import logging
from typing import TYPE_CHECKING

from pydantic_ai import ModelRequest
from pydantic_ai.direct import model_request
from pydantic_ai.messages import TextPart

from app.chat.agents import get_pydantic_ai_model_name
from app.chat.config import TEMPLATES_DIR
from app.chat.template_utils import get_runtime_jinja_environment
from app.core.config import settings
from app.core.db import get_session
from app.models import Conversation, PromptSetScope
from app.otel_genai import genai_agent_name_scope

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

_TITLE_MAX_LENGTH = 60


def build_fallback_title(user_prompt: str) -> str:
    trimmed = user_prompt.strip()
    if len(trimmed) <= _TITLE_MAX_LENGTH:
        return trimmed
    return f"{trimmed[:_TITLE_MAX_LENGTH].rstrip()}..."


def _normalize_title(title: str, fallback: str) -> str:
    normalized = title.strip()
    for char in ('"', "'", "“", "”", "`"):
        normalized = normalized.strip(char)
    if not normalized:
        return fallback

    first_line = normalized.splitlines()[0].strip()
    if not first_line:
        return fallback

    first_line = first_line.rstrip(".!?")
    if len(first_line) <= _TITLE_MAX_LENGTH:
        return first_line

    return f"{first_line[:_TITLE_MAX_LENGTH].rstrip()}..."


async def _render_title_prompt(user_prompt: str, *, is_internal: bool) -> str:
    env = await get_runtime_jinja_environment(
        TEMPLATES_DIR, is_internal=is_internal, scope=PromptSetScope.TITLE
    )
    template = env.get_template("title_agent.j2")
    return template.render(user_prompt=user_prompt)


async def _render_title_transcript_prompt(transcript: str, *, is_internal: bool) -> str:
    env = await get_runtime_jinja_environment(
        TEMPLATES_DIR, is_internal=is_internal, scope=PromptSetScope.TITLE_TRANSCRIPT
    )
    template = env.get_template("title_agent_transcript.j2")
    return template.render(transcript=transcript)


async def _run_title_prompt(prompt: str, *, agent_name: str) -> str:
    with genai_agent_name_scope(agent_name):
        response = await model_request(
            get_pydantic_ai_model_name(settings.SUMMARIZER_MODEL),
            [ModelRequest.user_text_prompt(prompt)],
        )

    first_part = response.parts[0]
    if isinstance(first_part, TextPart):
        return first_part.content

    msg = "Title generation returned an unexpected response format"
    raise ValueError(msg)


async def generate_conversation_title(
    user_prompt: str, *, conversation_id: UUID | None = None, is_internal: bool = False
) -> str:
    fallback = build_fallback_title(user_prompt)
    prompt = await _render_title_prompt(user_prompt.strip(), is_internal=is_internal)

    try:
        output = await _run_title_prompt(prompt, agent_name="title")
        return _normalize_title(output, fallback)
    except Exception:
        logger.exception(
            "Error generating conversation title",
            extra={"conversation_id": str(conversation_id) if conversation_id else None},
        )
        return fallback


async def generate_conversation_title_from_transcript(
    transcript: str,
    *,
    conversation_id: UUID | None = None,
    is_internal: bool = False,
    fallback: str,
) -> str:
    normalized_transcript = transcript.strip()
    if normalized_transcript == "":
        return fallback

    prompt = await _render_title_transcript_prompt(normalized_transcript, is_internal=is_internal)

    try:
        output = await _run_title_prompt(prompt, agent_name="title_transcript")
        return _normalize_title(output, fallback)
    except Exception:
        logger.exception(
            "Error generating conversation title from transcript",
            extra={"conversation_id": str(conversation_id) if conversation_id else None},
        )
        return fallback


async def update_conversation_title(
    conversation_id: UUID, user_prompt: str, *, is_internal: bool
) -> None:
    try:
        title = await generate_conversation_title(
            user_prompt, conversation_id=conversation_id, is_internal=is_internal
        )

        async with get_session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if not conversation:
                logger.warning(
                    "Conversation not found while updating title",
                    extra={"conversation_id": str(conversation_id)},
                )
                return

            conversation.title = title
    except Exception:
        logger.exception(
            "Failed to update conversation title", extra={"conversation_id": str(conversation_id)}
        )
