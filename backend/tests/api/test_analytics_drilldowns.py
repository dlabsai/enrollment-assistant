from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
from app.core.security import get_password_hash
from app.main import app
from app.models import Conversation, Message, User
from tests.api.auth_helpers import authenticate_client


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["internal", "public"])
async def test_volume_drilldowns_reproduce_buckets_and_keep_review_scope(
    transactional_session: AsyncSession, platform: str
) -> None:
    users: list[User] = []
    for slug in (SystemGroupSlug.DEV, SystemGroupSlug.USER):
        group = await get_group_for_slug(transactional_session, slug)
        user = User(
            email=f"volume-{uuid4()}@example.com",
            name=f"Volume {slug.value}",
            password_hash=get_password_hash("StrongPassword123"),
            is_active=True,
            group_id=group.id,
        )
        transactional_session.add(user)
        users.append(user)
    reviewer, owner = users
    await transactional_session.flush()

    cohort_start = datetime(2026, 8, 1, 12, tzinfo=UTC)
    cohort_end = datetime(2026, 8, 31, 12, tzinfo=UTC)
    bucket_start = datetime(2026, 8, 10, tzinfo=UTC)
    bucket_end = datetime(2026, 8, 11, tzinfo=UTC)
    ms = timedelta(milliseconds=1)
    created_dates = {
        "early": cohort_start,
        "first": bucket_start,
        "last": bucket_end - timedelta(microseconds=1),
        "empty": bucket_start + timedelta(hours=1),
        "next": bucket_end,
        "old": cohort_start - ms,
        "late": cohort_end + ms,
        "cohort edge": cohort_end,
        "investigation": bucket_start,
        "other platform": bucket_start,
        "developer": bucket_start,
    }
    chats: dict[str, Conversation] = {}
    for name, created_at in created_dates.items():
        chat = Conversation(
            title=name,
            user=False,
            project="postuni",
            user_id=reviewer.id if name == "developer" else owner.id,
            is_public=(platform != "public")
            if name == "other platform"
            else (False if name == "developer" else platform == "public"),
            kind="investigation" if name == "investigation" else "chat",
            created_at=created_at,
            updated_at=created_at,
        )
        chats[name] = chat
        transactional_session.add(chat)
    await transactional_session.flush()

    def message(chat_name: str, at: datetime, role: str = "user") -> Message:
        row = Message(
            conversation=chats[chat_name],
            role=role,
            content=f"{chat_name} {role} {at.isoformat()}",
            created_at=at,
            updated_at=at,
        )
        transactional_session.add(row)
        return row

    expected_turns = [
        message("early", bucket_start),
        message("early", bucket_end - timedelta(microseconds=500)),
        message("first", bucket_start + timedelta(hours=1)),
        message("last", bucket_end - timedelta(microseconds=1)),
    ]
    message("early", bucket_start - ms)
    message("early", bucket_end)
    message("first", bucket_start, role="assistant")
    # Latest activity must not replace creation time when selecting Chats.
    message("first", cohort_end + timedelta(days=1))
    message("next", bucket_end)
    message("cohort edge", cohort_end)
    message("early", cohort_end + timedelta(microseconds=1))
    for name in ("old", "late", "investigation", "other platform", "developer"):
        message(name, bucket_start + timedelta(hours=2))
    await transactional_session.commit()
    expected_chat_ids = {str(chats[name].id) for name in ("first", "last", "empty")}
    expected_message_ids = {str(row.id) for row in expected_turns}

    scope = {"platform": platform}
    if platform == "internal":
        scope["user_group"] = "staff"
    cohort = {"start": cohort_start.isoformat(), "end": cohort_end.isoformat()}
    creation_filter = {
        **scope,
        "analytics_start": bucket_start.isoformat(),
        "analytics_end_before": bucket_end.isoformat(),
    }
    turn_filter = {
        **scope,
        "role": "user",
        "start": bucket_start.isoformat(),
        "end_before": bucket_end.isoformat(),
        "conversation_start": cohort["start"],
        "conversation_end": cohort["end"],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        analytics = await client.get("/api/analytics/conversations", params={**scope, **cohort})
        assert analytics.status_code == 200
        bucket = next(
            row
            for row in analytics.json()["series"]
            if datetime.fromisoformat(row["bucket_start"]) == bucket_start
        )
        chat_ids: set[str] = set()
        message_ids: set[str] = set()
        for offset in range(4):
            chats_page = await client.get(
                "/api/conversations/paginated",
                params={**creation_filter, "limit": 1, "offset": offset},
            )
            assert chats_page.status_code == 200
            assert chats_page.json()["total"] == bucket["conversations"] == 3
            chat_ids.update(row["id"] for row in chats_page.json()["items"])
            turns_page = await client.get(
                "/api/messages", params={**turn_filter, "limit": 1, "offset": offset}
            )
            assert turns_page.status_code == 200
            assert turns_page.json()["total"] == bucket["turns"] == 4
            message_ids.update(row["id"] for row in turns_page.json()["items"])
        assert chat_ids == expected_chat_ids
        assert message_ids == expected_message_ids

        exported = await client.get("/api/conversations/export", params=creation_filter)
        assert exported.status_code == 200
        assert exported.headers["x-chat-export-included-count"] == "3"
        with ZipFile(BytesIO(exported.content)) as archive:
            transcripts = [
                archive.read(name).decode() for name in archive.namelist() if name.endswith(".txt")
            ]
        assert len(transcripts) == 3
        for name in ("first", "last", "empty"):
            assert any(f"Chat: {name}\n" in transcript for transcript in transcripts)

        # The clipped final bucket includes the exact inclusive dashboard end,
        # but not a later microsecond in an otherwise eligible chat.
        final_bucket = analytics.json()["series"][-1]
        final_chats = await client.get(
            "/api/conversations/paginated",
            params={
                **scope,
                "analytics_start": final_bucket["bucket_start"],
                "analytics_end_before": final_bucket["bucket_end"],
            },
        )
        final_turns = await client.get(
            "/api/messages",
            params={
                **turn_filter,
                "start": final_bucket["bucket_start"],
                "end_before": final_bucket["bucket_end"],
            },
        )
        assert final_chats.status_code == final_turns.status_code == 200
        assert final_chats.json()["total"] == final_bucket["conversations"] == 1
        assert final_turns.json()["total"] == final_bucket["turns"] == 1

        # Without one cohort edge the message from the respective outside chat
        # legitimately enters the list; the clicked message bucket stays fixed.
        for missing_edge in ("conversation_start", "conversation_end"):
            one_sided = await client.get(
                "/api/messages",
                params={key: value for key, value in turn_filter.items() if key != missing_edge},
            )
            assert one_sided.status_code == 200
            assert one_sided.json()["total"] == 5
        for invalid in (
            {"conversation_start": cohort["end"], "conversation_end": cohort["start"]},
            {"start": cohort["end"], "end_before": cohort["start"]},
            {"end": cohort["end"]},  # Inclusive and exclusive ends cannot be combined.
        ):
            response = await client.get("/api/messages", params={**turn_filter, **invalid})
            assert response.status_code == 400

        for prefix in ("", "conversation_"):
            response = await client.get(
                "/api/messages",
                params={
                    f"{prefix}start": "2026-08-01T00:00:00",
                    f"{prefix}end": "2026-08-31T00:00:00Z",
                },
            )
            assert response.status_code == 422

        await replace_user_permission_overrides(
            transactional_session, reviewer, {PermissionKey.ACCESS_MESSAGES: False}
        )
        await transactional_session.commit()
        denied = await client.get("/api/messages", params=turn_filter)
        assert denied.status_code == 403
