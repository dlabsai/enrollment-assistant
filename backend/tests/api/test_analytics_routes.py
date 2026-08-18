from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
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
        adoption_response = await client.get("/api/analytics/adoption")
        public_response = await client.get("/api/analytics/public-usage")

    assert conversations_response.status_code == 403
    assert conversations_response.json() == {"detail": "Access denied"}
    assert adoption_response.status_code == 403
    assert adoption_response.json() == {"detail": "Access denied"}
    assert public_response.status_code == 403
    assert public_response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_analytics_owner_filter_uses_chat_scope_without_chats_page_access(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="analytics-options-reviewer",
    )
    owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="analytics-options-owner",
    )
    hidden_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="analytics-options-hidden-owner",
    )
    await replace_user_permission_overrides(
        transactional_session,
        reviewer,
        {
            PermissionKey.ACCESS_CHATS: False,
            PermissionKey.ACCESS_ANALYTICS: True,
            PermissionKey.CHATS_VIEW_USERS: True,
            PermissionKey.CHATS_VIEW_DEVS: False,
        },
    )
    started_at = datetime(2098, 1, 1, tzinfo=UTC)
    transactional_session.add_all(
        [
            _conversation(
                title="Analytics option", created_at=started_at, is_public=False, user_id=owner.id
            ),
            _conversation(
                title="Hidden analytics option",
                created_at=started_at,
                is_public=False,
                user_id=hidden_owner.id,
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get("/api/conversations/users", params={"platform": "internal"})
        hidden_analytics_response = await client.get(
            "/api/analytics/conversations",
            params={
                "user_email": hidden_owner.email,
                "start": (started_at - timedelta(hours=1)).isoformat(),
                "end": (started_at + timedelta(hours=1)).isoformat(),
            },
        )

    assert response.status_code == 200
    assert any(option["email"] == owner.email for option in response.json())
    assert all(option["email"] != hidden_owner.email for option in response.json())
    assert hidden_analytics_response.status_code == 200
    assert hidden_analytics_response.json()["total_conversations"] == 0


@pytest.mark.asyncio
async def test_adoption_access_can_load_scoped_user_options(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-options-reviewer",
    )
    owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-options-owner",
    )
    await replace_user_permission_overrides(
        transactional_session,
        reviewer,
        {
            PermissionKey.ACCESS_ADOPTION: True,
            PermissionKey.ACCESS_CHATS: False,
            PermissionKey.ACCESS_USAGE: False,
            PermissionKey.ACCESS_ANALYTICS: False,
            PermissionKey.CHATS_VIEW_USERS: True,
        },
    )
    transactional_session.add(
        _conversation(
            title="Adoption option",
            created_at=datetime(2098, 1, 2, tzinfo=UTC),
            is_public=False,
            user_id=owner.id,
        )
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get("/api/conversations/users", params={"platform": "internal"})

    assert response.status_code == 200
    assert any(option["email"] == owner.email for option in response.json())


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
async def test_adoption_uses_browser_days_and_counts_only_internal_user_messages(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="adoption-browser-day-reviewer",
    )
    active_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-browser-day-active",
    )
    assistant_only_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-browser-day-assistant-only",
    )
    public_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-browser-day-public",
    )
    activity_time = datetime(2098, 3, 1, 7, 30, tzinfo=UTC)
    active_chat = _conversation(
        title="Browser-day activity",
        created_at=activity_time,
        is_public=False,
        user_id=active_owner.id,
    )
    second_active_chat = _conversation(
        title="Second browser-day activity",
        created_at=activity_time,
        is_public=False,
        user_id=active_owner.id,
    )
    assistant_only_chat = _conversation(
        title="Assistant only",
        created_at=activity_time,
        is_public=False,
        user_id=assistant_only_owner.id,
    )
    public_chat = _conversation(
        title="Public activity", created_at=activity_time, is_public=True, user_id=public_owner.id
    )
    transactional_session.add_all(
        [active_chat, second_active_chat, assistant_only_chat, public_chat]
    )
    await transactional_session.flush()
    transactional_session.add_all(
        [
            Message(
                role="user", content="Active", conversation=active_chat, created_at=activity_time
            ),
            Message(
                role="user",
                content="Same user, another chat",
                conversation=second_active_chat,
                created_at=activity_time,
            ),
            Message(
                role="assistant",
                content="Assistant only",
                conversation=assistant_only_chat,
                created_at=activity_time,
            ),
            Message(
                role="user", content="Public", conversation=public_chat, created_at=activity_time
            ),
        ]
    )
    await transactional_session.commit()
    await transactional_session.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get(
            "/api/analytics/adoption",
            params={
                "start": datetime(2098, 2, 28, 8, tzinfo=UTC).isoformat(),
                "end": datetime(2098, 3, 1, 7, 59, tzinfo=UTC).isoformat(),
                "browser_time_zone": "America/Los_Angeles",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["latest_daily_active_users"] == 1
    assert body["monthly_active_users"] == 1
    assert body["daily"] == [
        {"date": "2098-02-28", "daily_active_users": 1, "monthly_active_users": 1}
    ]


@pytest.mark.asyncio
async def test_adoption_returns_zeroes_for_empty_range_and_rejects_future_start(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="adoption-empty-reviewer",
    )
    empty_day = datetime(2098, 4, 1, tzinfo=UTC)
    future_start = datetime.now(UTC) + timedelta(days=365)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        empty_response = await client.get(
            "/api/analytics/adoption",
            params={
                "start": empty_day.isoformat(),
                "end": empty_day.replace(hour=23, minute=59).isoformat(),
            },
        )
        future_response = await client.get(
            "/api/analytics/adoption", params={"start": future_start.isoformat()}
        )
        invalid_timezone_response = await client.get(
            "/api/analytics/adoption",
            params={
                "start": empty_day.isoformat(),
                "end": empty_day.replace(hour=23, minute=59).isoformat(),
                "browser_time_zone": "",
            },
        )

    assert empty_response.status_code == 200
    expected_empty_body = {
        "latest_daily_active_users": 0,
        "monthly_active_users": 0,
        "average_daily_active_users": 0.0,
        "stickiness": 0.0,
        "daily": [{"date": "2098-04-01", "daily_active_users": 0, "monthly_active_users": 0}],
    }
    assert empty_response.json() == expected_empty_body
    assert invalid_timezone_response.status_code == 200
    assert invalid_timezone_response.json() == expected_empty_body
    assert future_response.status_code == 400
    assert future_response.json() == {"detail": "Invalid time range"}


@pytest.mark.asyncio
async def test_adoption_reports_internal_dau_and_rolling_mau(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="adoption-reviewer"
    )
    limited_reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-limited-reviewer",
    )
    staff_one = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="adoption-staff-one"
    )
    staff_two = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="adoption-staff-two"
    )
    prior_staff = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="adoption-prior-staff"
    )
    developer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="adoption-developer"
    )
    await replace_user_permission_overrides(
        transactional_session,
        limited_reviewer,
        {
            PermissionKey.ACCESS_ADOPTION: True,
            PermissionKey.CHATS_VIEW_OWN: True,
            PermissionKey.CHATS_VIEW_USERS: False,
            PermissionKey.CHATS_VIEW_DEVS: False,
        },
    )

    first_day = datetime(2098, 3, 1, 12, tzinfo=UTC)
    second_day = first_day + timedelta(days=1)
    last_day = first_day + timedelta(days=30)
    prior_day = first_day - timedelta(days=14)
    prior_chat = _conversation(
        title="Prior staff", created_at=prior_day, is_public=False, user_id=prior_staff.id
    )
    staff_one_chat = _conversation(
        title="Staff one", created_at=first_day, is_public=False, user_id=staff_one.id
    )
    staff_two_chat = _conversation(
        title="Staff two", created_at=second_day, is_public=False, user_id=staff_two.id
    )
    developer_chat = _conversation(
        title="Developer", created_at=last_day, is_public=False, user_id=developer.id
    )
    investigation = _conversation(
        title="Investigation", created_at=last_day, is_public=False, user_id=staff_two.id
    )
    investigation.kind = "investigation"
    transactional_session.add_all(
        [prior_chat, staff_one_chat, staff_two_chat, developer_chat, investigation]
    )
    await transactional_session.flush()
    transactional_session.add_all(
        [
            Message(role="user", content="Prior", conversation=prior_chat, created_at=prior_day),
            Message(role="user", content="One", conversation=staff_one_chat, created_at=first_day),
            Message(
                role="user",
                content="Still one",
                conversation=staff_one_chat,
                created_at=first_day + timedelta(minutes=1),
            ),
            Message(
                role="user", content="Return", conversation=staff_one_chat, created_at=last_day
            ),
            Message(role="user", content="Two", conversation=staff_two_chat, created_at=second_day),
            Message(role="user", content="Dev", conversation=developer_chat, created_at=last_day),
            Message(
                role="user", content="Investigate", conversation=investigation, created_at=last_day
            ),
        ]
    )
    await transactional_session.commit()
    time_params = {
        "start": first_day.replace(hour=0).isoformat(),
        "end": last_day.replace(hour=23, minute=59).isoformat(),
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        all_response = await client.get("/api/analytics/adoption", params=time_params)
        staff_response = await client.get(
            "/api/analytics/adoption", params={**time_params, "user_group": "staff"}
        )
        exact_response = await client.get(
            "/api/analytics/adoption", params={**time_params, "user_email": staff_two.email}
        )
        developer_response = await client.get(
            "/api/analytics/adoption", params={**time_params, "user_email": developer.email}
        )
        conflict_response = await client.get(
            "/api/analytics/adoption",
            params={**time_params, "user_email": staff_one.email, "user_group": "staff"},
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, limited_reviewer.id)
        hidden_response = await client.get(
            "/api/analytics/adoption", params={**time_params, "user_email": staff_one.email}
        )

    assert all_response.status_code == 200
    body = all_response.json()
    assert len(body["daily"]) == 31
    assert body["daily"][0] == {
        "date": "2098-03-01",
        "daily_active_users": 1,
        "monthly_active_users": 2,
    }
    assert body["daily"][1]["daily_active_users"] == 1
    assert body["latest_daily_active_users"] == 2
    assert body["monthly_active_users"] == 3
    assert body["average_daily_active_users"] == pytest.approx(4 / 31)
    assert body["stickiness"] == pytest.approx(2 / 3)

    assert staff_response.status_code == 200
    assert staff_response.json()["latest_daily_active_users"] == 1
    assert staff_response.json()["monthly_active_users"] == 2
    assert exact_response.status_code == 200
    assert exact_response.json()["latest_daily_active_users"] == 0
    assert exact_response.json()["monthly_active_users"] == 1
    assert developer_response.status_code == 200
    assert developer_response.json()["latest_daily_active_users"] == 1
    assert developer_response.json()["monthly_active_users"] == 1
    assert hidden_response.status_code == 200
    assert hidden_response.json()["monthly_active_users"] == 0
    assert conflict_response.status_code == 400
    assert conflict_response.json() == {"detail": "Specify only one of user_email or user_group"}


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


@pytest.mark.asyncio
async def test_chat_analytics_filters_by_user_group_and_email(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="analytics-filter-reviewer",
    )
    limited_reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="analytics-filter-limited",
    )
    staff_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="analytics-filter-staff",
    )
    developer_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="analytics-filter-developer",
    )
    await replace_user_permission_overrides(
        transactional_session,
        limited_reviewer,
        {
            PermissionKey.ACCESS_ANALYTICS: True,
            PermissionKey.CHATS_VIEW_OWN: True,
            PermissionKey.CHATS_VIEW_USERS: False,
            PermissionKey.CHATS_VIEW_DEVS: False,
        },
    )

    started_at = datetime(2098, 2, 1, 12, 0, tzinfo=UTC)
    staff_conversation = _conversation(
        title="Staff analytics", created_at=started_at, is_public=False, user_id=staff_owner.id
    )
    developer_conversation = _conversation(
        title="Developer analytics",
        created_at=started_at,
        is_public=False,
        user_id=developer_owner.id,
    )
    transactional_session.add_all([staff_conversation, developer_conversation])
    await transactional_session.flush()
    transactional_session.add_all(
        [
            *_messages(staff_conversation, count=2, created_at=started_at),
            *_messages(developer_conversation, count=4, created_at=started_at),
            _turn_span(
                trace_id="analytics-user-staff",
                conversation=staff_conversation,
                started_at=started_at,
                total_time=3,
            ),
            _turn_span(
                trace_id="analytics-user-developer",
                conversation=developer_conversation,
                started_at=started_at,
                total_time=8,
            ),
        ]
    )
    await transactional_session.commit()
    time_params = {
        "start": (started_at - timedelta(hours=1)).isoformat(),
        "end": (started_at + timedelta(hours=1)).isoformat(),
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        all_response = await client.get("/api/analytics/conversations", params=time_params)
        staff_response = await client.get(
            "/api/analytics/conversations", params={**time_params, "user_group": "staff"}
        )
        exact_response = await client.get(
            "/api/analytics/conversations", params={**time_params, "user_email": staff_owner.email}
        )
        developer_response = await client.get(
            "/api/analytics/conversations",
            params={**time_params, "user_email": developer_owner.email},
        )
        conflict_response = await client.get(
            "/api/analytics/conversations",
            params={**time_params, "user_email": staff_owner.email, "user_group": "staff"},
        )

        authenticate_client(client, limited_reviewer.id)
        hidden_response = await client.get(
            "/api/analytics/conversations", params={**time_params, "user_email": staff_owner.email}
        )

    assert all_response.status_code == 200
    assert all_response.json()["total_conversations"] == 2
    assert staff_response.status_code == 200
    assert staff_response.json()["total_conversations"] == 1
    exact_body = exact_response.json()
    assert exact_response.status_code == 200
    assert exact_body["total_messages"] == 2
    assert sum(row["messages"] for row in exact_body["daily"]) == 2
    assert sum(row["messages"] for row in exact_body["hourly_activity"]) == 2
    assert exact_body["length_buckets"][1] == {"label": "2-3", "conversations": 1}
    developer_body = developer_response.json()
    assert developer_response.status_code == 200
    assert developer_body["total_messages"] == 4
    assert developer_body["length_buckets"][2] == {"label": "4-6", "conversations": 1}
    assert developer_body["response_time_stats"]["max"] == 8
    assert hidden_response.status_code == 200
    assert hidden_response.json()["total_conversations"] == 0
    assert hidden_response.json()["response_time_stats"] is None
    assert conflict_response.status_code == 400
    assert conflict_response.json()["detail"] == "Specify only one of user_email or user_group"
