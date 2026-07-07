"""Public chat endpoint for the website widget."""

from uuid import UUID  # noqa: TC003

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.chat.engine import ModelSettings, handle_conversation_turn
from app.core.config import settings
from app.core.db import async_session_factory

router = APIRouter(prefix="/chat", tags=["public-chat"])


class ChatRequest(BaseModel):
    """Public chat request fields."""

    user_prompt: str
    conversation_id: UUID | None = None
    parent_message_id: UUID | None = None


class ChatResponse(BaseModel):
    """Public chat response fields."""

    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    assistant_message: str
    parent_message_id: UUID | None
    guardrails_blocked: bool = False
    guardrails_blocked_message: str | None = None


def _get_model_settings() -> tuple[ModelSettings, ModelSettings]:
    chatbot = ModelSettings(
        model=settings.CHATBOT_MODEL,
        temperature=settings.CHATBOT_MODEL_TEMPERATURE or None,
        max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS or None,
    )
    guardrail = ModelSettings(
        model=settings.GUARDRAIL_MODEL,
        temperature=settings.GUARDRAIL_MODEL_TEMPERATURE or None,
        max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS or None,
    )
    return chatbot, guardrail


@router.post("/public/message", response_model=ChatResponse)
async def send_public_message(request: ChatRequest, session: SessionDep) -> ChatResponse:
    """Send a message from the unauthenticated public widget."""
    chatbot_settings, guardrail_settings = _get_model_settings()

    user_message_id, assistant_message_out = await handle_conversation_turn(
        project_name="demo",
        conversation_id=request.conversation_id,
        parent_message_id=request.parent_message_id,
        user_prompt=request.user_prompt,
        chatbot_model_settings=chatbot_settings,
        guardrail_model_settings=guardrail_settings,
        is_regeneration=False,
        is_internal=False,
        enable_guardrails=settings.ENABLE_GUARDRAILS,
        max_guardrails_retries=settings.MAX_GUARDRAILS_RETRIES,
        user_id=None,
        session=session,
        tool_session_factory=async_session_factory,
    )

    assert assistant_message_out.conversation_id is not None

    assistant_message = (
        assistant_message_out.guardrails_blocked_message or settings.GUARDRAILS_BLOCKED_MESSAGE
        if assistant_message_out.guardrails_blocked
        else assistant_message_out.content
    )

    return ChatResponse(
        conversation_id=assistant_message_out.conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_out.id,
        assistant_message=assistant_message,
        parent_message_id=assistant_message_out.parent_id,
        guardrails_blocked=assistant_message_out.guardrails_blocked,
        guardrails_blocked_message=assistant_message_out.guardrails_blocked_message,
    )
