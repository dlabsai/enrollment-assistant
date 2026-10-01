from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.scheduled import SCHEDULER_USER_EMAIL
from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
from app.core.security import get_password_hash
from app.main import app
from app.models import (
    AssistantMessageMetadata,
    ChatGenerationAttempt,
    Conversation,
    Message,
    MessageFeedback,
    PublicChatContact,
    Rating,
    User,
)
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


def _assistant_metadata(
    message: Message, *, retries: int | None, turn: int, total_time: float | None = None
) -> AssistantMessageMetadata:
    return AssistantMessageMetadata(
        message=message,
        system_prompt_rendered="System prompt",
        conversation_turn=turn,
        chatbot_model_settings={"model": "azure/test"},
        guardrail_retry_count=retries,
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
        quality_response = await client.get("/api/analytics/quality")
        adoption_response = await client.get("/api/analytics/adoption")
        public_response = await client.get("/api/analytics/public-usage")

    assert conversations_response.status_code == 403
    assert conversations_response.json() == {"detail": "Access denied"}
    assert quality_response.status_code == 403
    assert quality_response.json() == {"detail": "Access denied"}
    assert adoption_response.status_code == 403
    assert adoption_response.json() == {"detail": "Access denied"}
    assert public_response.status_code == 403
    assert public_response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_quality_summary_uses_feedback_time_and_excludes_non_live_chat(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="quality-reviewer"
    )
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="quality-owner"
    )
    second_reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="quality-second-reviewer",
    )
    started_at = datetime(2026, 8, 1, 12, tzinfo=UTC)
    feedback_at = started_at + timedelta(days=30)

    internal = _conversation(
        title="Internal quality", created_at=started_at, is_public=False, user_id=owner.id
    )
    public = _conversation(
        title="Public quality", created_at=started_at, is_public=True, user_id=None
    )
    draft = _conversation(
        title="Draft quality", created_at=started_at, is_public=False, user_id=reviewer.id
    )
    draft.prompt_source = "draft"
    investigation = _conversation(
        title="Investigation quality", created_at=started_at, is_public=False, user_id=reviewer.id
    )
    investigation.kind = "investigation"

    first_pass = Message(
        role="assistant",
        content="First pass",
        conversation=internal,
        created_at=started_at,
        updated_at=started_at,
    )
    blocked = Message(
        role="assistant",
        content="Blocked raw response",
        conversation=internal,
        guardrails_blocked=True,
        created_at=started_at + timedelta(hours=1),
        updated_at=started_at + timedelta(hours=1),
    )
    unknown_retry = Message(
        role="assistant",
        content="Public response",
        conversation=public,
        created_at=started_at + timedelta(hours=2),
        updated_at=started_at + timedelta(hours=2),
    )
    draft_message = Message(
        role="assistant",
        content="Draft response",
        conversation=draft,
        guardrails_blocked=True,
        created_at=started_at + timedelta(hours=3),
        updated_at=started_at + timedelta(hours=3),
    )
    investigation_message = Message(
        role="assistant",
        content="Investigation response",
        conversation=investigation,
        created_at=started_at + timedelta(hours=4),
        updated_at=started_at + timedelta(hours=4),
    )
    transactional_session.add_all(
        [
            internal,
            public,
            draft,
            investigation,
            first_pass,
            blocked,
            unknown_retry,
            draft_message,
            investigation_message,
            _assistant_metadata(first_pass, retries=0, turn=1),
            _assistant_metadata(blocked, retries=2, turn=2),
            _assistant_metadata(draft_message, retries=3, turn=1),
            _assistant_metadata(investigation_message, retries=0, turn=1),
            MessageFeedback(
                message=first_pass,
                user_id=reviewer.id,
                rating=Rating.THUMBS_UP,
                created_at=feedback_at,
                updated_at=feedback_at,
            ),
            MessageFeedback(
                message=blocked,
                user_id=reviewer.id,
                rating=Rating.THUMBS_DOWN,
                created_at=feedback_at,
                updated_at=feedback_at,
            ),
            MessageFeedback(
                message=blocked,
                user_id=second_reviewer.id,
                rating=Rating.THUMBS_UP,
                created_at=feedback_at,
                updated_at=feedback_at,
            ),
            MessageFeedback(
                message=unknown_retry,
                user_id=reviewer.id,
                rating=Rating.THUMBS_UP,
                created_at=feedback_at,
                updated_at=feedback_at,
            ),
            MessageFeedback(
                message=draft_message,
                user_id=reviewer.id,
                rating=Rating.THUMBS_DOWN,
                created_at=feedback_at,
                updated_at=feedback_at,
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get(
            "/api/analytics/quality",
            params={
                "start": started_at.isoformat(),
                "end": (started_at + timedelta(days=2)).isoformat(),
            },
        )
        feedback_response = await client.get(
            "/api/analytics/quality",
            params={
                "start": feedback_at.isoformat(),
                "end": (feedback_at + timedelta(days=2)).isoformat(),
            },
        )
        public_response = await client.get(
            "/api/analytics/quality",
            params={
                "platform": "public",
                "start": feedback_at.isoformat(),
                "end": (feedback_at + timedelta(days=2)).isoformat(),
            },
        )
        feedback_drilldown_response = await client.get(
            "/api/feedback",
            params={
                "rating": "thumbs_down",
                "exclude_draft": True,
                "start": feedback_at.isoformat(),
                "end": (feedback_at + timedelta(days=2)).isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "assistant_responses": 3,
        "retry_observed_responses": 2,
        "retry_affected_responses": 1,
        "retry_attempts": 2,
        "blocked_responses": 1,
        "ratings": 0,
        "thumbs_up": 0,
        "thumbs_down": 0,
        "retry_affected_rate": 0.5,
        "blocked_rate": pytest.approx(1 / 3),
        "positive_rate": None,
        "response_samples": 0,
        "median_response_seconds": None,
        "p95_response_seconds": None,
        "failed_generations": 0,
        "tracked_generation_attempts": 0,
        "generation_failure_rate": None,
    }
    assert body["time_granularity"] == "hour"
    assert len(body["series"]) == 49
    assert [
        (
            point["retry_attempts"],
            point["blocked_responses"],
            point["thumbs_up"],
            point["thumbs_down"],
        )
        for point in body["series"][:4]
    ] == [(0, 0, 0, 0), (2, 1, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)]
    assert feedback_response.status_code == 200
    feedback_summary = feedback_response.json()["summary"]
    assert feedback_summary["assistant_responses"] == 0
    assert feedback_summary["ratings"] == 4
    assert feedback_summary["thumbs_up"] == 3
    assert feedback_summary["thumbs_down"] == 1
    assert feedback_summary["positive_rate"] == 0.75
    assert feedback_response.json()["series"][0]["thumbs_up"] == 3
    assert feedback_response.json()["series"][0]["thumbs_down"] == 1

    assert public_response.status_code == 200
    public_summary = public_response.json()["summary"]
    assert public_summary["assistant_responses"] == 0
    assert public_summary["ratings"] == 1
    assert public_summary["thumbs_up"] == 1
    assert public_response.json()["series"][0]["thumbs_up"] == 1
    assert public_response.json()["series"][0]["thumbs_down"] == 0

    assert feedback_drilldown_response.status_code == 200
    assert feedback_drilldown_response.json()["total"] == 1
    assert feedback_drilldown_response.json()["items"][0]["message_id"] == str(blocked.id)


@pytest.mark.asyncio
async def test_quality_reports_metadata_responsiveness_and_tracked_failures(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="quality-responsiveness-reviewer",
    )
    owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="quality-responsiveness-owner",
    )
    now = datetime.now(UTC)
    started_at = now - timedelta(hours=1)
    conversation = _conversation(
        title="Responsiveness", created_at=started_at, is_public=False, user_id=owner.id
    )
    messages = [
        Message(
            role="assistant",
            content=f"Response {index}",
            conversation=conversation,
            guardrails_blocked=index == 2,
            created_at=started_at + timedelta(minutes=index),
            updated_at=started_at + timedelta(minutes=index),
        )
        for index in range(3)
    ]
    transactional_session.add_all([conversation, *messages])
    await transactional_session.flush()
    transactional_session.add_all(
        [
            _assistant_metadata(message, retries=0, turn=index + 1, total_time=total_time)
            for index, (message, total_time) in enumerate(
                zip(messages, (10.0, 20.0, 100.0), strict=True)
            )
        ]
        + [
            ChatGenerationAttempt(
                user_id=owner.id,
                conversation_id=conversation.id,
                request_fingerprint=str(index) * 64,
                status=status,
                created_at=created_at,
                updated_at=created_at,
            )
            for index, (status, created_at) in enumerate(
                [
                    ("completed", started_at),
                    ("failed", started_at + timedelta(minutes=1)),
                    ("pending", now - timedelta(minutes=16)),
                    ("pending", now - timedelta(minutes=5)),
                ],
                start=1,
            )
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get(
            "/api/analytics/quality",
            params={
                "platform": "internal",
                "user_group": "staff",
                "start": (started_at - timedelta(hours=2)).isoformat(),
                "end": (now + timedelta(minutes=1)).isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]
    assert summary["response_samples"] == 3
    assert summary["median_response_seconds"] == 20
    assert summary["p95_response_seconds"] == pytest.approx(92)
    assert summary["tracked_generation_attempts"] == 3
    assert summary["failed_generations"] == 2
    assert summary["generation_failure_rate"] == pytest.approx(2 / 3)
    assert sum(point["samples"] for point in body["responsiveness_series"]) == 3
    assert sum(point["tracked_attempts"] for point in body["failure_series"]) == 3
    assert sum((point["failed_generations"] or 0) for point in body["failure_series"]) == 2
    assert any(
        point["tracked_attempts"] == 0 and point["failed_generations"] is None
        for point in body["failure_series"]
    )
    assert sum(bucket["count"] for bucket in body["response_time_buckets"]) == 3
    assert body["response_time_buckets"][-1] == {
        "label": "≥100s",
        "lower_bound": 100.0,
        "upper_bound": None,
        "count": 1,
        "overflow": True,
    }


@pytest.mark.asyncio
async def test_quality_response_histogram_keeps_p99_in_a_normal_bucket(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="quality-histogram-reviewer",
    )
    owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="quality-histogram-owner",
    )
    created_at = datetime(2094, 1, 1, 12, tzinfo=UTC)
    conversation = _conversation(
        title="Exact P99 duration", created_at=created_at, is_public=False, user_id=owner.id
    )
    message = Message(
        role="assistant",
        content="Exact P99 response",
        conversation=conversation,
        created_at=created_at,
        updated_at=created_at,
    )
    transactional_session.add_all([conversation, message])
    await transactional_session.flush()
    transactional_session.add(_assistant_metadata(message, retries=0, turn=1, total_time=100.0))
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get(
            "/api/analytics/quality",
            params={
                "platform": "internal",
                "user_group": "staff",
                "start": (created_at - timedelta(minutes=1)).isoformat(),
                "end": (created_at + timedelta(minutes=1)).isoformat(),
            },
        )

    assert response.status_code == 200
    buckets = response.json()["response_time_buckets"]
    assert next(bucket for bucket in buckets if bucket["count"] == 1) == {
        "label": "100s-<110s",
        "lower_bound": 100.0,
        "upper_bound": 110.0,
        "count": 1,
        "overflow": False,
    }
    assert buckets[-1] == {
        "label": "≥110s",
        "lower_bound": 110.0,
        "upper_bound": None,
        "count": 0,
        "overflow": True,
    }


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
async def test_conversation_analytics_aggregates_chats_and_turns(
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
    investigation = _conversation(
        title="Investigation",
        created_at=started_at + timedelta(hours=2),
        is_public=False,
        user_id=admin.id,
    )
    investigation.kind = "investigation"
    transactional_session.add_all(
        [internal_conversation, public_conversation, public_dropoff, investigation]
    )
    await transactional_session.flush()
    transactional_session.add_all(
        [
            *_messages(internal_conversation, count=4, created_at=started_at),
            *_messages(public_conversation, count=2, created_at=started_at + timedelta(hours=1)),
            *_messages(public_dropoff, count=1, created_at=started_at + timedelta(hours=2)),
            *_messages(investigation, count=3, created_at=started_at + timedelta(hours=2)),
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
    assert body["total_turns"] == 4
    assert body["avg_turns_per_conversation"] == pytest.approx(4 / 3)
    assert sum(row["turns"] for row in body["series"]) == 4
    assert body["time_granularity"] == "hour"
    assert body["series"][0]["bucket_start"] == "2026-02-01T11:00:00Z"
    assert body["series"][0]["bucket_end"] == "2026-02-01T12:00:00Z"
    assert body["length_buckets"] == [
        {"label": "0", "conversations": 0, "min_turns": 0, "max_turns": 0, "overflow": False},
        {"label": "1", "conversations": 2, "min_turns": 1, "max_turns": 1, "overflow": False},
        {"label": "2", "conversations": 1, "min_turns": 2, "max_turns": 2, "overflow": False},
        {"label": ">2", "conversations": 0, "min_turns": 3, "max_turns": None, "overflow": True},
    ]
    assert len(body["hourly_activity"]) == 24
    assert sum(row["turns"] for row in body["hourly_activity"]) == 4

    assert public_response.status_code == 200
    public_body = public_response.json()
    assert public_body["total_conversations"] == 2
    assert public_body["total_turns"] == 2


@pytest.mark.asyncio
async def test_chat_length_distribution_uses_exact_counts_through_discrete_p99(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="analytics-length-admin",
    )
    started_at = datetime(2091, 1, 1, 12, tzinfo=UTC)
    conversations = [
        _conversation(
            title=f"Length {index}", created_at=started_at, is_public=False, user_id=admin.id
        )
        for index in range(100)
    ]
    transactional_session.add_all(conversations)
    await transactional_session.flush()
    transactional_session.add_all(
        [
            Message(
                role="user", content="One turn", conversation=conversation, created_at=started_at
            )
            for conversation in conversations[:98]
        ]
        + [
            Message(
                role="user",
                content=f"Outlier turn {index}",
                conversation=conversations[-1],
                created_at=started_at + timedelta(seconds=index),
            )
            for index in range(20)
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/analytics/conversations",
            params={
                "start": (started_at - timedelta(minutes=1)).isoformat(),
                "end": (started_at + timedelta(minutes=1)).isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["length_stats"]["p99"] == 1
    assert body["length_buckets"] == [
        {"label": "0", "conversations": 1, "min_turns": 0, "max_turns": 0, "overflow": False},
        {"label": "1", "conversations": 98, "min_turns": 1, "max_turns": 1, "overflow": False},
        {"label": ">1", "conversations": 1, "min_turns": 2, "max_turns": None, "overflow": True},
    ]


@pytest.mark.asyncio
async def test_chat_analytics_declares_adaptive_granularity_and_exact_boundaries(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="analytics-granularity-admin",
    )
    start = datetime(2090, 1, 1, 12, 30, tzinfo=UTC)
    ranges = [
        (timedelta(hours=72), "hour"),
        (timedelta(hours=72, seconds=1), "day"),
        (timedelta(days=90, seconds=1), "week"),
        (timedelta(days=731), "month"),
    ]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        responses = [
            await client.get(
                "/api/analytics/conversations",
                params={"start": start.isoformat(), "end": (start + duration).isoformat()},
            )
            for duration, _ in ranges
        ]

    for response, (duration, expected_granularity) in zip(responses, ranges, strict=True):
        assert response.status_code == 200
        body = response.json()
        assert body["time_granularity"] == expected_granularity
        points = body["series"]
        assert points
        assert datetime.fromisoformat(points[0]["bucket_start"]) == start
        assert datetime.fromisoformat(points[-1]["bucket_end"]) == (
            start + duration + timedelta(microseconds=1)
        )
        assert all(
            datetime.fromisoformat(point["bucket_start"])
            < datetime.fromisoformat(point["bucket_end"])
            for point in points
        )
        assert all(
            previous["bucket_end"] == current["bucket_start"]
            for previous, current in pairwise(points)
        )


@pytest.mark.asyncio
async def test_chat_analytics_buckets_turns_for_chats_created_in_range(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="turn-analytics-admin"
    )
    started_at = datetime(2026, 2, 2, 10, 0, tzinfo=UTC)
    conversation = _conversation(
        title="Turn timing", created_at=started_at, is_public=False, user_id=admin.id
    )
    older_conversation = _conversation(
        title="Older chat",
        created_at=started_at - timedelta(hours=1),
        is_public=False,
        user_id=admin.id,
    )
    transactional_session.add_all([conversation, older_conversation])
    await transactional_session.flush()
    transactional_session.add_all(
        [
            Message(
                role=role,
                content=f"{role} message",
                conversation=conversation,
                created_at=created_at,
                updated_at=created_at,
            )
            for role, created_at in [
                ("user", started_at + timedelta(minutes=10)),
                ("assistant", started_at + timedelta(minutes=15)),
                ("user", started_at + timedelta(hours=1, minutes=10)),
                ("assistant", started_at + timedelta(hours=1, minutes=15)),
                ("assistant", started_at + timedelta(hours=2, minutes=15)),
            ]
        ]
        + [
            Message(
                role="user",
                content="Continued older chat",
                conversation=older_conversation,
                created_at=started_at + timedelta(minutes=20),
                updated_at=started_at + timedelta(minutes=20),
            )
        ]
    )
    await transactional_session.commit()
    await transactional_session.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))

    params = {"start": started_at.isoformat(), "end": (started_at + timedelta(hours=3)).isoformat()}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/analytics/conversations", params=params)
        eastern_response = await client.get(
            "/api/analytics/conversations",
            params={**params, "browser_time_zone": "America/New_York"},
        )
        start_only = started_at - timedelta(minutes=30)
        start_only_response = await client.get(
            "/api/analytics/conversations", params={"start": start_only.isoformat()}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_turns"] == 2
    turns_by_bucket = {
        datetime.fromisoformat(row["bucket_start"]): row["turns"] for row in body["series"]
    }
    assert turns_by_bucket[started_at] == 1
    assert turns_by_bucket[started_at + timedelta(hours=1)] == 1
    assert turns_by_bucket[started_at + timedelta(hours=2)] == 0
    assert body["hourly_activity"][10] == {"hour": 10, "turns": 1}
    assert body["hourly_activity"][11] == {"hour": 11, "turns": 1}
    assert body["hourly_activity"][12] == {"hour": 12, "turns": 0}
    assert eastern_response.status_code == 200
    eastern_activity = eastern_response.json()["hourly_activity"]
    assert eastern_activity[5] == {"hour": 5, "turns": 1}
    assert eastern_activity[6] == {"hour": 6, "turns": 1}
    assert eastern_activity[10] == {"hour": 10, "turns": 0}
    assert start_only_response.status_code == 200
    assert start_only_response.json()["series"][0][
        "bucket_start"
    ] == start_only.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_chat_analytics_hourly_activity_observes_eastern_dst(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="analytics-eastern-dst-admin",
    )
    activity_time = datetime(2026, 7, 1, 10, tzinfo=UTC)
    conversation = _conversation(
        title="Eastern summer activity", created_at=activity_time, is_public=False, user_id=admin.id
    )
    transactional_session.add(conversation)
    await transactional_session.flush()
    transactional_session.add(
        Message(
            role="user", content="Summer turn", conversation=conversation, created_at=activity_time
        )
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/analytics/conversations",
            params={
                "start": (activity_time - timedelta(minutes=1)).isoformat(),
                "end": (activity_time + timedelta(minutes=1)).isoformat(),
                "browser_time_zone": "America/New_York",
            },
        )

    assert response.status_code == 200
    hourly_activity = response.json()["hourly_activity"]
    assert hourly_activity[6] == {"hour": 6, "turns": 1}
    assert hourly_activity[5] == {"hour": 5, "turns": 0}


@pytest.mark.asyncio
async def test_adoption_uses_selected_zone_days_and_only_internal_user_messages(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="adoption-selected-zone-reviewer",
    )
    active_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-selected-zone-active",
    )
    assistant_only_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-selected-zone-assistant-only",
    )
    public_owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-selected-zone-public",
    )
    activity_time = datetime(2098, 3, 1, 7, 30, tzinfo=UTC)
    active_chat = _conversation(
        title="Selected-zone activity",
        created_at=activity_time,
        is_public=False,
        user_id=active_owner.id,
    )
    second_active_chat = _conversation(
        title="Second selected-zone activity",
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
    assert body["time_granularity"] == "hour"
    assert len(body["series"]) == 24
    assert sum(point["active_users"] for point in body["series"]) == 1
    active_point = next(point for point in body["series"] if point["active_users"] == 1)
    assert active_point["bucket_start"] == "2098-03-01T07:00:00Z"
    assert active_point["bucket_end"] == "2098-03-01T07:59:00.000001Z"


@pytest.mark.asyncio
async def test_hourly_adoption_mau_does_not_include_later_same_day_activity(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="adoption-hourly-reviewer",
    )
    owners = [
        await _create_user(
            transactional_session,
            group_slug=SystemGroupSlug.USER,
            email_prefix=f"adoption-hourly-owner-{index}",
        )
        for index in range(2)
    ]
    start = datetime(2098, 3, 2, tzinfo=UTC)
    conversations = [
        _conversation(title=f"Hourly {index}", created_at=start, is_public=False, user_id=owner.id)
        for index, owner in enumerate(owners)
    ]
    transactional_session.add_all(conversations)
    await transactional_session.flush()
    transactional_session.add_all(
        [
            Message(
                role="user",
                content="Earlier activity",
                conversation=conversations[0],
                created_at=start + timedelta(hours=1, minutes=10),
            ),
            Message(
                role="user",
                content="Later activity",
                conversation=conversations[1],
                created_at=start + timedelta(hours=3, minutes=10),
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get(
            "/api/analytics/adoption",
            params={
                "start": start.isoformat(),
                "end": (start + timedelta(hours=3, minutes=59)).isoformat(),
                "browser_time_zone": "UTC",
            },
        )

    assert response.status_code == 200
    points = response.json()["series"]
    assert points[1]["active_users"] == 1
    assert points[1]["monthly_active_users"] == 1
    assert points[3]["active_users"] == 1
    assert points[3]["monthly_active_users"] == 2


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
    empty_body = empty_response.json()
    assert empty_body["new_accounts"] == 0
    assert empty_body["active_new_accounts"] == 0
    assert empty_body["latest_daily_active_users"] == 0
    assert empty_body["monthly_active_users"] == 0
    assert empty_body["average_daily_active_users"] == 0.0
    assert empty_body["stickiness"] == 0.0
    assert empty_body["time_granularity"] == "hour"
    assert len(empty_body["series"]) == 24
    assert all(point["active_users"] == 0 for point in empty_body["series"])
    assert invalid_timezone_response.status_code == 200
    assert invalid_timezone_response.json() == empty_body
    assert future_response.status_code == 400
    assert future_response.json() == {"detail": "Invalid time range"}


@pytest.mark.asyncio
async def test_adoption_reports_account_growth_and_internal_activity(
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
    new_account_without_activity = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="adoption-unused-new-account",
    )
    service_account = await transactional_session.scalar(
        select(User).where(User.email == SCHEDULER_USER_EMAIL)
    )
    assert service_account is not None

    first_day = datetime(2098, 3, 1, 12, tzinfo=UTC)
    second_day = first_day + timedelta(days=1)
    last_day = first_day + timedelta(days=30)
    prior_day = first_day - timedelta(days=14)
    for account in (reviewer, limited_reviewer, staff_one, staff_two, prior_staff, developer):
        account.created_at = prior_day
        account.updated_at = prior_day
    staff_two.created_at = second_day
    staff_two.updated_at = second_day
    new_account_without_activity.created_at = second_day
    new_account_without_activity.updated_at = second_day
    service_account.created_at = second_day
    service_account.updated_at = second_day
    await transactional_session.commit()

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
        unused_new_account_response = await client.get(
            "/api/analytics/adoption",
            params={**time_params, "user_email": new_account_without_activity.email},
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
    assert len(body["series"]) == 31
    assert body["time_granularity"] == "day"
    assert body["series"][0] == {
        "bucket_start": "2098-03-01T00:00:00Z",
        "bucket_end": "2098-03-02T00:00:00Z",
        "new_accounts": 0,
        "active_users": 1,
        "monthly_active_users": 2,
    }
    assert body["series"][1]["active_users"] == 1
    assert sum(point["new_accounts"] for point in body["series"]) == 2
    assert body["new_accounts"] == 2
    assert body["active_new_accounts"] == 1
    assert body["latest_daily_active_users"] == 2
    assert body["monthly_active_users"] == 3
    assert body["average_daily_active_users"] == pytest.approx(4 / 31)
    assert body["stickiness"] == pytest.approx(2 / 3)

    assert staff_response.status_code == 200
    assert staff_response.json()["latest_daily_active_users"] == 1
    assert staff_response.json()["monthly_active_users"] == 2
    assert exact_response.status_code == 200
    assert exact_response.json()["active_new_accounts"] == 1
    assert exact_response.json()["latest_daily_active_users"] == 0
    assert exact_response.json()["monthly_active_users"] == 1
    assert developer_response.status_code == 200
    assert developer_response.json()["latest_daily_active_users"] == 1
    assert developer_response.json()["monthly_active_users"] == 1
    assert unused_new_account_response.status_code == 200
    assert unused_new_account_response.json()["new_accounts"] == 1
    assert unused_new_account_response.json()["active_new_accounts"] == 0
    assert hidden_response.status_code == 200
    assert hidden_response.json()["monthly_active_users"] == 0
    assert conflict_response.status_code == 400
    assert conflict_response.json() == {"detail": "Specify only one of user_email or user_group"}


@pytest.mark.asyncio
async def test_public_analytics_reports_leads_and_message_depth(
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
    assert body["total_leads"] == 1
    assert body["time_granularity"] == "hour"
    assert body["depth_buckets"] == [
        {"label": "0", "conversations": 0, "overflow": False},
        {"label": "1", "conversations": 1, "overflow": False},
        {"label": "2", "conversations": 1, "overflow": False},
        {"label": ">2", "conversations": 0, "overflow": True},
    ]
    assert sum(entry["leads"] for entry in body["series"]) == 1
    assert datetime.fromisoformat(body["series"][0]["bucket_start"]) == (
        started_at - timedelta(hours=1)
    )
    assert datetime.fromisoformat(body["series"][-1]["bucket_end"]) == (
        started_at + timedelta(hours=2, microseconds=1)
    )


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
    assert exact_body["total_turns"] == 1
    assert sum(row["turns"] for row in exact_body["series"]) == 1
    assert sum(row["turns"] for row in exact_body["hourly_activity"]) == 1
    assert exact_body["length_buckets"][1] == {
        "label": "1",
        "conversations": 1,
        "min_turns": 1,
        "max_turns": 1,
        "overflow": False,
    }
    developer_body = developer_response.json()
    assert developer_response.status_code == 200
    assert developer_body["total_turns"] == 2
    assert developer_body["length_buckets"][2] == {
        "label": "2",
        "conversations": 1,
        "min_turns": 2,
        "max_turns": 2,
        "overflow": False,
    }
    assert hidden_response.status_code == 200
    assert hidden_response.json()["total_conversations"] == 0
    assert conflict_response.status_code == 400
    assert conflict_response.json()["detail"] == "Specify only one of user_email or user_group"
