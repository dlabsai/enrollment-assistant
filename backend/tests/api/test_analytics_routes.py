from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import Conversation, Message, OtelSpan, PublicChatContact, User
from tests.api.auth_helpers import authenticate_client


async def _create_user(
    session: AsyncSession, *, group_slug: SystemGroupSlug, email_prefix: str
) -> User:
    group = await get_group_for_slug(session, group_slug)
    user = User(
        email=f"{email_prefix}-{uuid4()}@example.com",
        name=f"{group_slug.value.title()} User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _conversation(
    *, title: str, created_at: datetime, is_public: bool, user_id: object | None
) -> Conversation:
    return Conversation(
        title=title,
        user=False,
        project="demo",
        user_id=user_id,
        is_public=is_public,
        created_at=created_at,
        updated_at=created_at,
    )


def _messages(conversation: Conversation, *, count: int, created_at: datetime) -> list[Message]:
    return [
        Message(
            role="assistant" if index % 2 else "user",
            content=f"Message {index}",
            conversation=conversation,
            created_at=created_at + timedelta(minutes=index),
            updated_at=created_at + timedelta(minutes=index),
        )
        for index in range(count)
    ]


def _turn_span(
    *,
    trace_id: str,
    conversation: Conversation,
    started_at: datetime,
    total_time: float,
    is_internal: bool | None = None,
) -> OtelSpan:
    resolved_is_internal = not conversation.is_public if is_internal is None else is_internal
    return OtelSpan(
        trace_id=trace_id,
        span_id=f"turn-{trace_id}",
        parent_span_id=None,
        name="handle_conversation_turn",
        kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=started_at,
        end_time=started_at + timedelta(seconds=total_time),
        span_time=started_at,
        duration_ms=total_time * 1000,
        attributes={
            "app.conversation_id": str(conversation.id),
            "app.is_internal": resolved_is_internal,
            "app.total_time": total_time,
        },
        events=None,
        links=None,
        resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
        scope={"name": "demo-va", "version": "test", "schema_url": None},
        request_model=None,
        provider_name=None,
        server_address=None,
        input_tokens=None,
        output_tokens=None,
        total_cost=None,
        is_ai=False,
        is_embedding=False,
        is_internal=resolved_is_internal,
        conversation_id=conversation.id,
        message_id=None,
        total_time=total_time,
    )


@pytest.mark.asyncio
async def test_analytics_routes_require_permissions(transactional_session: AsyncSession) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="analytics-user"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        conversations_response = await client.get("/api/analytics/conversations")
        public_response = await client.get("/api/analytics/public-usage")

    assert conversations_response.status_code == 403
    assert conversations_response.json() == {"detail": "Access denied"}
    assert public_response.status_code == 403
    assert public_response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_conversation_analytics_aggregates_chats_and_response_times(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="analytics-admin"
    )
    started_at = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)

    internal_conversation = _conversation(
        title="Internal", created_at=started_at, is_public=False, user_id=admin.id
    )
    public_conversation = _conversation(
        title="Public lead",
        created_at=started_at + timedelta(hours=1),
        is_public=True,
        user_id=None,
    )
    public_dropoff = _conversation(
        title="Public drop-off",
        created_at=started_at + timedelta(hours=2),
        is_public=True,
        user_id=None,
    )
    transactional_session.add_all([internal_conversation, public_conversation, public_dropoff])
    await transactional_session.flush()
    transactional_session.add_all(
        [
            *_messages(internal_conversation, count=4, created_at=started_at),
            *_messages(public_conversation, count=2, created_at=started_at + timedelta(hours=1)),
            *_messages(public_dropoff, count=1, created_at=started_at + timedelta(hours=2)),
            _turn_span(
                trace_id="analytics-internal",
                conversation=internal_conversation,
                started_at=started_at,
                total_time=3.0,
            ),
            _turn_span(
                trace_id="analytics-public",
                conversation=public_conversation,
                started_at=started_at + timedelta(hours=1),
                total_time=8.0,
            ),
            _turn_span(
                trace_id="analytics-otel-internal-on-public-conversation",
                conversation=public_conversation,
                started_at=started_at + timedelta(hours=1, minutes=30),
                total_time=12.0,
                is_internal=True,
            ),
        ]
    )
    await transactional_session.commit()

    params = {
        "start": (started_at - timedelta(hours=1)).isoformat(),
        "end": (started_at + timedelta(hours=3)).isoformat(),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/analytics/conversations", params=params)
        public_response = await client.get(
            "/api/analytics/conversations", params={**params, "platform": "public"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 3
    assert body["total_messages"] == 7
    assert abs(body["avg_messages_per_conversation"] - (7 / 3)) < 0.000001
    assert abs(body["single_message_rate"] - (1 / 3)) < 0.000001
    assert body["length_buckets"] == [
        {"label": "1", "conversations": 1},
        {"label": "2-3", "conversations": 1},
        {"label": "4-6", "conversations": 1},
        {"label": "7-9", "conversations": 0},
        {"label": "10+", "conversations": 0},
    ]
    assert body["response_time_buckets"][:2] == [
        {"label": "0-<5s", "responses": 1},
        {"label": "5-<10s", "responses": 1},
    ]
    assert body["response_time_stats"]["min"] == 3.0
    assert body["response_time_stats"]["max"] == 12.0
    assert len(body["hourly_activity"]) == 24

    assert public_response.status_code == 200
    public_body = public_response.json()
    assert public_body["total_conversations"] == 2
    assert public_body["total_messages"] == 3
    assert public_body["response_time_buckets"][1] == {"label": "5-<10s", "responses": 1}
    assert sum(bucket["responses"] for bucket in public_body["response_time_buckets"]) == 1


@pytest.mark.asyncio
async def test_public_usage_aggregates_public_contacts_as_leads(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="public-analytics-admin",
    )
    started_at = datetime(2026, 2, 2, 10, 0, tzinfo=UTC)
    public_conversation = _conversation(
        title="Public lead", created_at=started_at, is_public=True, user_id=None
    )
    public_repeat_visitor = _conversation(
        title="Public repeat visitor",
        created_at=started_at + timedelta(minutes=30),
        is_public=True,
        user_id=None,
    )
    internal_conversation = _conversation(
        title="Internal", created_at=started_at, is_public=False, user_id=admin.id
    )
    transactional_session.add_all(
        [public_conversation, public_repeat_visitor, internal_conversation]
    )
    await transactional_session.flush()
    transactional_session.add_all(
        [
            *_messages(public_conversation, count=2, created_at=started_at),
            *_messages(
                public_repeat_visitor, count=1, created_at=started_at + timedelta(minutes=30)
            ),
            *_messages(internal_conversation, count=5, created_at=started_at),
            PublicChatContact(
                first_name="Ada",
                last_name="Lovelace",
                email="ada@example.com",
                phone="5551234567",
                zip_code="12345",
                visitor_id="visitor-1",
                conversation_id=public_conversation.id,
                consented_at=started_at,
            ),
            PublicChatContact(
                first_name="Ada",
                last_name="Lovelace",
                email="ada@example.com",
                phone="5557654321",
                zip_code="12345",
                visitor_id="visitor-2",
                conversation_id=public_repeat_visitor.id,
                consented_at=started_at + timedelta(minutes=30),
            ),
        ]
    )
    await transactional_session.commit()

    params = {
        "start": (started_at - timedelta(hours=1)).isoformat(),
        "end": (started_at + timedelta(hours=2)).isoformat(),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/analytics/public-usage", params=params)

    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 2
    assert body["total_messages"] == 3
    assert body["total_leads"] == 1
    assert body["lead_capture_rate"] == 0.5
    assert body["depth_buckets"] == [
        {"label": "1", "conversations": 1},
        {"label": "2-3", "conversations": 1},
        {"label": "4-6", "conversations": 0},
        {"label": "7-9", "conversations": 0},
        {"label": "10+", "conversations": 0},
    ]
    assert sum(entry["leads"] for entry in body["daily"]) == 1
    assert len(body["hourly_activity"]) == 24
