from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import messages as message_routes
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.main import app
from app.models import Conversation, User
from tests.api.auth_helpers import authenticate_client


async def _create_user(session: AsyncSession, slug: SystemGroupSlug) -> User:
    group = await get_group_for_slug(session, slug)
    user = User(
        email=f"settings-{uuid4()}@example.com",
        name="Settings user",
        password_hash=str(uuid4()),
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_settings_are_optional_persisted_and_account_scoped(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(transactional_session, SystemGroupSlug.USER)
    peer = await _create_user(transactional_session, SystemGroupSlug.DEV)
    context = "I work in Public Health.\nUse technical terminology."
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unauthenticated = await client.get("/api/user-settings")
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["Cache-Control"] == "no-store"
        unauthenticated = await client.put(
            "/api/user-settings", json={"personal_instructions": context}
        )
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["Cache-Control"] == "no-store"
        authenticate_client(client, owner.id)
        initial = await client.get("/api/user-settings")
        assert initial.status_code == 200
        assert initial.json() == {"personal_instructions": ""}
        assert initial.headers["Cache-Control"] == "no-store"
        saved = await client.put("/api/user-settings", json={"personal_instructions": context})
        assert saved.status_code == 200
        assert saved.json() == {"personal_instructions": context}
        assert saved.headers["Cache-Control"] == "no-store"
        authenticate_client(client, peer.id)
        assert (await client.get("/api/user-settings")).json() == {"personal_instructions": ""}
        listed = await client.get("/api/auth/users")
        assert listed.status_code == 200
        assert all("personal_instructions" not in user for user in listed.json())
        assert context not in listed.text

    # Another cookie session (browser or Teams) reads the same account preference.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        assert (await client.get("/api/user-settings")).json() == {"personal_instructions": context}
        cleared = await client.put("/api/user-settings", json={"personal_instructions": " \n\t "})
        assert cleared.status_code == 200
        assert cleared.json() == {"personal_instructions": ""}
    await transactional_session.refresh(owner)
    await transactional_session.refresh(peer)
    assert owner.personal_instructions == peer.personal_instructions == ""


@pytest.mark.asyncio
async def test_settings_enforce_length_and_cookie_origin(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(transactional_session, SystemGroupSlug.USER)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        for text in ("a" * 2000, "🩺" * 2000):
            response = await client.put("/api/user-settings", json={"personal_instructions": text})
            assert response.status_code == 200
            assert response.json()["personal_instructions"] == text
        for body in (
            {"personal_instructions": "a" * 2001},
            {"personal_instructions": "🩺" * 2001},
            {"personal_instructions": None},
            {"personal_instructions": "Public Health", "user_id": str(owner.id)},
        ):
            invalid = await client.put("/api/user-settings", json=body)
            assert invalid.status_code == 422
            assert invalid.headers["Cache-Control"] == "no-store"
        rejected = await client.put(
            "/api/user-settings",
            headers={"Origin": "https://untrusted.example"},
            json={"personal_instructions": "Do not save"},
        )
        assert rejected.status_code == 403
        assert rejected.headers["Cache-Control"] == "no-store"
        assert (await client.get("/api/user-settings")).json()[
            "personal_instructions"
        ] == "🩺" * 2000


@pytest.mark.asyncio
async def test_failed_save_remains_uncacheable_and_keeps_the_saved_value(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await _create_user(transactional_session, SystemGroupSlug.USER)
    owner.personal_instructions = "Previously saved context"
    await transactional_session.commit()
    monkeypatch.setattr(
        transactional_session, "commit", AsyncMock(side_effect=RuntimeError("Save failed"))
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        response = await client.put(
            "/api/user-settings", json={"personal_instructions": "Do not persist this draft"}
        )
        assert response.status_code == 500
        assert response.headers["Cache-Control"] == "no-store"
        assert (await client.get("/api/user-settings")).json() == {
            "personal_instructions": "Previously saved context"
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["chat", "draft", "investigation"])
async def test_stream_snapshots_context_and_excludes_diagnostic_chats(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    user = await _create_user(transactional_session, SystemGroupSlug.DEV)
    user.personal_instructions = "I work in Public Health."
    conversation = Conversation(
        title="Context test",
        project="demo",
        user_id=user.id,
        is_public=False,
        kind="investigation" if surface == "investigation" else "chat",
        prompt_source="draft" if surface == "draft" else None,
    )
    transactional_session.add(conversation)
    await transactional_session.commit()
    observed: list[str] = []

    async def record_context(*, personal_instructions: str = "", **_: object) -> None:
        observed.append(personal_instructions)
        raise RuntimeError("Stop before provider execution")

    async def noop(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(message_routes, "handle_conversation_turn", record_context)
    monkeypatch.setattr(message_routes, "handle_investigation_turn", record_context)
    monkeypatch.setattr(message_routes, "_generate_initial_title", noop)
    monkeypatch.setattr(message_routes, "_generate_transcript_title", noop)
    monkeypatch.setattr(message_routes, "summarize_internal_conversation", noop)
    body: dict[str, object] = {
        "conversation_id": str(conversation.id),
        "conversation_kind": "investigation" if surface == "investigation" else "chat",
        "user_prompt": "start date",
        "generation_attempt_id": str(uuid4()),
    }
    if surface == "draft":
        body["draft_prompt_templates"] = [
            {"filename": "chatbot_agent_internal.j2", "content": "Draft chatbot"},
            {"filename": "guardrails_agent_internal.j2", "content": "Draft guardrails"},
        ]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post("/api/messages/internal/stream", json=body)
        assert response.status_code == 200, response.text
        assert "event: error" in response.text
        assert observed == ["I work in Public Health." if surface == "chat" else ""]
        user.personal_instructions = "Updated after admission"
        await transactional_session.commit()
        # Editing account context cannot turn an old execution UUID into a new run.
        replay = await client.post("/api/messages/internal/stream", json=body)
        assert replay.status_code == 409
        assert len(observed) == 1
        body["generation_attempt_id"] = str(uuid4())
        retry = await client.post("/api/messages/internal/stream", json=body)
        assert retry.status_code == 200
        assert observed[-1] == ("Updated after admission" if surface == "chat" else "")
