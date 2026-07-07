from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import Conversation, PublicChatContact, User
from tests.api.auth_helpers import authenticate_client


async def _create_admin_user(session: AsyncSession) -> User:
    group = await get_group_for_slug(session, SystemGroupSlug.ADMIN)
    user = User(
        email="public-contact-admin@example.com",
        name="Public Contact Admin",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_public_chat_contact_creates_pending_record(
    transactional_session: AsyncSession,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/consent",
            json={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ADA@EXAMPLE.COM",
                "phone": "5551234567",
                "zip": "12345",
                "visitor_id": "visitor-1",
                "environment": "local",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] is None
    assert body["consented_at"] is not None

    contact = await transactional_session.scalar(select(PublicChatContact))
    assert contact is not None
    assert contact.first_name == "Ada"
    assert contact.last_name == "Lovelace"
    assert contact.email == "ada@example.com"
    assert contact.phone == "5551234567"
    assert contact.zip_code == "12345"
    assert contact.visitor_id == "visitor-1"
    assert contact.conversation_id is None
    assert contact.consented_at is not None
    assert contact.environment == "local"


@pytest.mark.asyncio
async def test_public_chat_contact_links_pending_record_to_public_conversation(
    transactional_session: AsyncSession,
) -> None:
    conversation = Conversation(
        title="Public chat", user=False, project="demo", user_id=None, is_public=True
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    pending = PublicChatContact(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone="5551234567",
        zip_code="12345",
        visitor_id="visitor-1",
        conversation_id=None,
        consented_at=conversation.created_at,
    )
    transactional_session.add(pending)
    await transactional_session.flush()
    original_consented_at = pending.consented_at

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/consent",
            json={
                "first_name": "Ada",
                "last_name": "Byron",
                "email": "ada.byron@example.com",
                "phone": "5557654321",
                "zip": "54321",
                "visitor_id": "visitor-1",
                "conversation_id": str(conversation.id),
            },
        )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == str(conversation.id)

    contacts = (await transactional_session.scalars(select(PublicChatContact))).all()
    assert len(contacts) == 1
    contact = contacts[0]
    assert contact.id == pending.id
    assert contact.conversation_id == conversation.id
    assert contact.last_name == "Byron"
    assert contact.email == "ada.byron@example.com"
    assert contact.phone == "5557654321"
    assert contact.zip_code == "54321"
    assert contact.consented_at == original_consented_at


@pytest.mark.asyncio
async def test_public_chat_contact_rejects_internal_conversation(
    transactional_session: AsyncSession,
) -> None:
    conversation = Conversation(
        title="Internal chat", user=False, project="demo", user_id=None, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{settings.API_STR}/consent",
            json={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "phone": "5551234567",
                "zip": "12345",
                "visitor_id": "visitor-1",
                "conversation_id": str(conversation.id),
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Conversation is not public"


@pytest.mark.asyncio
async def test_public_chat_contact_surfaces_in_internal_conversation_review(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_admin_user(transactional_session)
    conversation = Conversation(
        title="Public chat", user=False, project="demo", user_id=None, is_public=True
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    transactional_session.add(
        PublicChatContact(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="5551234567",
            zip_code="12345",
            visitor_id="visitor-1",
            conversation_id=conversation.id,
            consented_at=conversation.created_at,
        )
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        paginated_response = await client.get(
            f"{settings.API_STR}/conversations/paginated",
            params={"platform": "public", "limit": 20, "offset": 0},
        )
        filtered_response = await client.get(
            f"{settings.API_STR}/conversations/paginated",
            params={
                "platform": "public",
                "user_email": "ada@example.com",
                "limit": 20,
                "offset": 0,
            },
        )
        users_response = await client.get(
            f"{settings.API_STR}/conversations/users", params={"platform": "public"}
        )
        detail_response = await client.get(f"{settings.API_STR}/conversations/{conversation.id}")

    assert paginated_response.status_code == 200
    item = paginated_response.json()["items"][0]
    assert item["id"] == str(conversation.id)
    assert item["user_name"] == "Ada Lovelace"
    assert item["user_email"] == "ada@example.com"

    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] == 1

    assert users_response.status_code == 200
    assert users_response.json() == [
        {"name": "Ada Lovelace", "email": "ada@example.com", "platform": "public"}
    ]

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["user_name"] == "Ada Lovelace"
    assert detail_body["user_email"] == "ada@example.com"
