from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.models import Conversation, Message, User

RULE = "Flag guarantees of admission."
MESSAGE = "Admission is guaranteed."
START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(days=1)


async def make_user(session: AsyncSession, group: SystemGroupSlug) -> User:
    assigned = await get_group_for_slug(session, group)
    user = User(
        email=f"compliance-{uuid4()}@example.com",
        name=group.value,
        password_hash=str(uuid4()),
        is_active=True,
        group_id=assigned.id,
    )
    session.add(user)
    await session.flush()
    return user


async def make_chat(
    session: AsyncSession,
    owner: User,
    *,
    content: str = MESSAGE,
    public: bool = False,
    draft: bool = False,
    kind: str = "chat",
) -> tuple[Conversation, Message]:
    chat = Conversation(
        title="Admission question",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=public,
        prompt_source="draft" if draft else None,
        kind=kind,
        created_at=START - timedelta(days=10),
    )
    session.add(chat)
    await session.flush()
    question = Message(
        conversation_id=chat.id,
        role="user",
        content="Can admission be promised?",
        created_at=START - timedelta(days=1),
    )
    session.add(question)
    await session.flush()
    message = Message(
        conversation_id=chat.id,
        role="assistant",
        content=content,
        parent_id=question.id,
        created_at=START + timedelta(hours=1),
    )
    session.add(message)
    await session.flush()
    return chat, message


async def save_rule(client: AsyncClient, content: str = RULE) -> dict[str, Any]:
    current = (await client.get("/api/compliance/instructions")).json()["current"]
    response = await client.post(
        "/api/compliance/instructions",
        json={"content": content, "base_version_id": current["id"] if current else None},
    )
    assert response.status_code == 200, response.text
    return response.json()


def period() -> dict[str, str]:
    return {"start": START.isoformat(), "end": END.isoformat()}


async def start_screening(client: AsyncClient, version_id: str) -> str:
    screening_id = str(uuid4())
    response = await client.post(
        "/api/compliance/screenings",
        json={**period(), "id": screening_id, "instructions_version_id": version_id},
    )
    assert response.status_code == 200, response.text
    return screening_id
