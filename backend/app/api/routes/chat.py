"""Public chat endpoint for the website widget."""

from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.chat.engine import ModelSettings, handle_conversation_turn
from app.chat.tree_utils import get_current_branch_path
from app.core.config import settings
from app.core.db import async_session_factory
from app.models import Conversation, Message

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
        azure_service_tier=settings.CHATBOT_AZURE_SERVICE_TIER,
    )
    guardrail = ModelSettings(
        model=settings.GUARDRAIL_MODEL,
        temperature=settings.GUARDRAIL_MODEL_TEMPERATURE or None,
        max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS or None,
        azure_service_tier=settings.GUARDRAIL_AZURE_SERVICE_TIER,
    )
    return chatbot, guardrail


async def _resolve_parent_message_id(request: ChatRequest, session: SessionDep) -> UUID | None:
    parent_message_id = request.parent_message_id

    if request.conversation_id is None:
        if parent_message_id is not None:
            raise HTTPException(
                status_code=400, detail="A new conversation cannot have a parent message"
            )
        return None

    conversation = await session.get(Conversation, request.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversation.is_public:
        raise HTTPException(status_code=403, detail="Access denied")
    if conversation.kind != "chat":
        raise HTTPException(status_code=400, detail="Conversation is not a chat")

    if parent_message_id is None:
        if "parent_message_id" not in request.model_fields_set:
            path = await get_current_branch_path(session, request.conversation_id)
            if path:
                return path[-1]
        return None

    parent_message = await session.get(Message, parent_message_id)
    if parent_message is None:
        raise HTTPException(status_code=404, detail="Parent message not found")
    if parent_message.conversation_id != request.conversation_id:
        raise HTTPException(status_code=400, detail="Parent message is not in this conversation")
    return parent_message_id


@router.post("/public/message", response_model=ChatResponse)
async def send_public_message(request: ChatRequest, session: SessionDep) -> ChatResponse:
    """Send a message from the unauthenticated public widget."""
    parent_message_id = await _resolve_parent_message_id(request, session)
    chatbot_settings, guardrail_settings = _get_model_settings()

    user_message_id, assistant_message_out = await handle_conversation_turn(
        project_name="demo",
        conversation_id=request.conversation_id,
        parent_message_id=parent_message_id,
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
