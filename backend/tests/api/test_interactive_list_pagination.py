from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import Conversation, Message, MessageFeedback, User
from app.models import Rating as MessageRating
from tests.api.auth_helpers import authenticate_client


@pytest.mark.asyncio
async def test_interactive_lists_retain_filtered_total_beyond_last_page(
    transactional_session: AsyncSession,
) -> None:
    group = await get_group_for_slug(transactional_session, SystemGroupSlug.DEV)
    reviewer = User(
        email=f"interactive-pagination-{uuid4()}@example.com",
        name="Interactive pagination reviewer",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    transactional_session.add(reviewer)
    await transactional_session.flush()

    conversation = Conversation(
        title="Out-of-range pagination",
        user=False,
        project="demo",
        user_id=reviewer.id,
        is_public=False,
    )
    transactional_session.add(conversation)
    await transactional_session.flush()
    message = Message(role="assistant", content="Answer", conversation=conversation)
    transactional_session.add(message)
    await transactional_session.flush()
    transactional_session.add(
        MessageFeedback(
            message_id=message.id,
            user_id=reviewer.id,
            rating=MessageRating.THUMBS_UP,
            text="Useful",
        )
    )
    await transactional_session.commit()

    params = {"limit": 1, "offset": 999, "user_email": reviewer.email}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        conversations_response = await client.get("/api/conversations/paginated", params=params)
        messages_response = await client.get("/api/messages", params=params)
        feedback_response = await client.get("/api/feedback", params=params)

    for response in (conversations_response, messages_response, feedback_response):
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 1}
