import logging
from typing import TYPE_CHECKING

from pydantic_ai import ModelRequest
from pydantic_ai.direct import model_request
from pydantic_ai.messages import TextPart

from app.chat.agents import get_pydantic_ai_model_name
from app.chat.config import TEMPLATES_DIR
from app.chat.engine_utils import (
    build_max_tokens_settings,
    set_direct_model_response_span_attributes,
)
from app.chat.template_utils import get_runtime_jinja_environment
from app.core.config import settings
from app.core.db import get_session
from app.models import Conversation, PromptSetScope
from app.otel import otel_export_scope
from app.otel_genai import genai_helper_trace_scope

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


async def _run_title_prompt(
    prompt: str,
    *,
    agent_name: str,
    conversation_id: UUID | None = None,
    trigger_message_id: UUID | None = None,
    is_internal: bool | None = None,
) -> str:
    configured_model = settings.TITLE_MODEL
    with (
        otel_export_scope(enabled=True),
        genai_helper_trace_scope(
            agent_name,
            model=configured_model,
            conversation_id=str(conversation_id) if conversation_id is not None else None,
            trigger_message_id=(
                str(trigger_message_id) if trigger_message_id is not None else None
            ),
            is_internal=is_internal,
        ) as span,
    ):
        response = await model_request(
            get_pydantic_ai_model_name(configured_model),
            [ModelRequest.user_text_prompt(prompt)],
            model_settings=build_max_tokens_settings(settings.TITLE_MODEL_MAX_TOKENS),
            instrument=False,
        )
        set_direct_model_response_span_attributes(span, response, configured_model=configured_model)

    first_part = response.parts[0]
    if isinstance(first_part, TextPart):
        return first_part.content

    msg = "Title generation returned an unexpected response format"
    raise ValueError(msg)


async def generate_conversation_title(
    user_prompt: str,
    *,
    conversation_id: UUID | None = None,
    trigger_message_id: UUID | None = None,
    is_internal: bool = False,
) -> str:
    fallback = build_fallback_title(user_prompt)
    prompt = await _render_title_prompt(user_prompt.strip(), is_internal=is_internal)

    try:
        output = await _run_title_prompt(
            prompt,
            agent_name="title",
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            is_internal=is_internal,
        )
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
    trigger_message_id: UUID | None = None,
    is_internal: bool = False,
    fallback: str,
) -> str:
    normalized_transcript = transcript.strip()
    if normalized_transcript == "":
        return fallback

    prompt = await _render_title_transcript_prompt(normalized_transcript, is_internal=is_internal)

    try:
        output = await _run_title_prompt(
            prompt,
            agent_name="title_transcript",
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            is_internal=is_internal,
        )
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
