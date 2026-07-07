from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, select

from app.api.deps import SessionDep
from app.models import Conversation, PublicChatContact
from app.utils import current_time_utc

router = APIRouter(prefix="/consent", tags=["public-chat-contact"])


class PublicChatContactIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    phone: str = Field(min_length=1)
    zip_code: str = Field(alias="zip", min_length=1)
    visitor_id: str = Field(min_length=1)
    conversation_id: UUID | None = None
    environment: str | None = None

    @field_validator("first_name", "last_name", "email", "phone", "zip_code", "visitor_id")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("Value cannot be empty")
        return stripped

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("environment")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class PublicChatContactOut(BaseModel):
    id: UUID
    conversation_id: UUID | None
    consented_at: datetime


async def _get_public_conversation(session: SessionDep, conversation_id: UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation not found"
        )
    if not conversation.is_public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation is not public"
        )
    return conversation


async def _find_contact_for_update(
    session: SessionDep, data: PublicChatContactIn
) -> PublicChatContact | None:
    if data.conversation_id is not None:
        contact = await session.scalar(
            select(PublicChatContact).where(
                PublicChatContact.conversation_id == data.conversation_id
            )
        )
        if contact is not None:
            return contact

        # A visitor can submit the form before their first chat turn creates a conversation.
        # Link that pending row to the newly-created public conversation on the next submission.
        return await session.scalar(
            select(PublicChatContact)
            .where(PublicChatContact.visitor_id == data.visitor_id)
            .where(PublicChatContact.conversation_id.is_(None))
            .order_by(desc(PublicChatContact.created_at))
            .limit(1)
        )

    return await session.scalar(
        select(PublicChatContact)
        .where(PublicChatContact.visitor_id == data.visitor_id)
        .where(PublicChatContact.conversation_id.is_(None))
        .order_by(desc(PublicChatContact.created_at))
        .limit(1)
    )


@router.post("", response_model=PublicChatContactOut)
async def submit_public_chat_contact(data: PublicChatContactIn, session: SessionDep) -> Any:
    if data.conversation_id is not None:
        await _get_public_conversation(session, data.conversation_id)

    contact = await _find_contact_for_update(session, data)
    consented_at = current_time_utc()

    if contact is None:
        contact = PublicChatContact(
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            phone=data.phone,
            zip_code=data.zip_code,
            visitor_id=data.visitor_id,
            conversation_id=data.conversation_id,
            consented_at=consented_at,
            environment=data.environment,
        )
        session.add(contact)
    else:
        contact.first_name = data.first_name
        contact.last_name = data.last_name
        contact.email = data.email
        contact.phone = data.phone
        contact.zip_code = data.zip_code
        contact.visitor_id = data.visitor_id
        contact.conversation_id = data.conversation_id
        contact.environment = data.environment

    await session.commit()
    await session.refresh(contact)

    return PublicChatContactOut(
        id=contact.id, conversation_id=contact.conversation_id, consented_at=contact.consented_at
    )
