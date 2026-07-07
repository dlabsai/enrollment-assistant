from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.message_sources import MessageSourceUsed, build_canned_response_source
from app.api.routes import chat as chat_routes
from app.api.routes import rag as rag_routes
from app.chat import internal_summary
from app.chat.engine import MessageMetadataOut, MessageOut, ModelSettings
from app.core.config import settings
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
    Conversation,
    DocumentType,
    Message,
    MessageFeedback,
    OtelSpan,
    User,
)
from app.models import Rating as MessageRating
from app.rag.pipeline import RagPipelineProgressSnapshot, RagPipelineStepSnapshot
from tests.api.auth_helpers import authenticate_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable


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


def _parse_sse_events(payload: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for raw_event in payload.strip().split("\n\n"):
        if raw_event.strip() == "":
            continue
        event_name = "message"
        data_chunks: list[str] = []
        for line in raw_event.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_chunks.append(line.removeprefix("data:").strip())
        if data_chunks:
            events.append((event_name, json.loads("\n".join(data_chunks))))
    return events


@pytest.mark.asyncio
async def test_public_message_ignores_staff_access_cookie(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="public-cookie"
    )
    observed_user_ids: list[UUID | None] = []

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        del conversation_id
        observed_user_ids.append(user_id)

        conversation = Conversation(
            title=user_prompt, user=False, project="demo", user_id=None, is_public=True
        )
        session.add(conversation)
        await session.flush()

        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        session.add(user_message)
        await session.flush()

        assistant_message = Message(
            role="assistant",
            content="Public reply",
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    monkeypatch.setattr(chat_routes, "handle_conversation_turn", fake_handle_conversation_turn)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login_response = await client.post(
            f"{settings.API_STR}/auth/login",
            json={"email": user.email, "password": "StrongPassword123"},
        )

        assert login_response.status_code == 200
        assert client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)

        public_response = await client.post(
            f"{settings.API_STR}/chat/public/message",
            headers={"Origin": "http://testserver"},
            json={"user_prompt": "Hello from the public site"},
        )

    assert public_response.status_code == 200
    assert observed_user_ids == [None]


@pytest.mark.asyncio
async def test_public_message_ignores_authorization_header(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_user_ids: list[UUID | None] = []

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        del conversation_id
        observed_user_ids.append(user_id)

        conversation = Conversation(
            title=user_prompt, user=False, project="demo", user_id=user_id, is_public=True
        )
        session.add(conversation)
        await session.flush()

        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        session.add(user_message)
        await session.flush()

        assistant_message = Message(
            role="assistant",
            content="Public reply",
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    monkeypatch.setattr(chat_routes, "handle_conversation_turn", fake_handle_conversation_turn)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        public_response = await client.post(
            f"{settings.API_STR}/chat/public/message",
            headers={"Authorization": "ignored-token"},
            json={"user_prompt": "Hello from the public site"},
        )

    assert public_response.status_code == 200
    assert observed_user_ids == [None]


@pytest.mark.asyncio
async def test_internal_message_stream_returns_expected_events(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="stream"
    )

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        event_emitter: Callable[[str, dict[str, object]], Awaitable[None]] | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        if conversation_id is None:
            conversation = Conversation(
                title=user_prompt, user=False, project="demo", user_id=user_id, is_public=False
            )
            session.add(conversation)
            await session.flush()
        else:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None

        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        session.add(user_message)
        await session.flush()

        assistant_message = Message(
            role="assistant",
            content="Hello from the fake assistant",
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()
        user_message.active_child = assistant_message
        session.add(
            AssistantMessageMetadata(
                message_id=assistant_message.id,
                system_prompt_rendered="system",
                conversation_turn=1,
            )
        )
        await session.flush()

        if event_emitter is not None:
            await event_emitter(
                "tool_call",
                {
                    "stage": "chatbot",
                    "status": "start",
                    "tool_call_id": "tool-1",
                    "tool_name": "find_document_titles",
                    "tool_input": {"content_search_query": user_prompt},
                    "iteration": 1,
                },
            )
            await event_emitter(
                "thinking",
                {
                    "stage": "chatbot",
                    "status": "start",
                    "thinking_id": "thinking-1",
                    "content": "Thinking...",
                    "iteration": 1,
                },
            )
            await event_emitter(
                "thinking",
                {
                    "stage": "chatbot",
                    "status": "end",
                    "thinking_id": "thinking-1",
                    "content": "Thinking...",
                    "iteration": 1,
                },
            )
            await event_emitter(
                "tool_call",
                {
                    "stage": "chatbot",
                    "status": "end",
                    "tool_call_id": "tool-1",
                    "tool_name": "find_document_titles",
                    "tool_output": {"results": 1},
                    "iteration": 1,
                },
            )
            await event_emitter(
                "agent_stage", {"stage": "chatbot", "status": "start", "iteration": 1}
            )
            await event_emitter(
                "agent_stage",
                {"stage": "chatbot", "status": "end", "duration_ms": 34, "iteration": 1},
            )

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=MessageMetadataOut(
                id=uuid4(),
                message_id=assistant_message.id,
                system_prompt_rendered="system",
                conversation_turn=1,
                chatbot_model_settings=ModelSettings(model="azure/gpt-4o"),
                created_at=assistant_message.created_at,
                updated_at=assistant_message.created_at,
                chatbot_time=0.25,
                guardrail_model_settings=ModelSettings(model="azure/gpt-4o-guardrails"),
                guardrail_time=0.75,
                total_time=1.234,
            ),
            guardrails_blocked=False,
        )

    async def noop_summary(_: UUID) -> None:
        return None

    async def noop_initial_title_update(
        conversation_id: UUID,
        user_prompt: str,
        *,
        is_internal: bool,
        on_title: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        del user_prompt, is_internal
        if on_title is not None:
            await on_title(f"Initial {conversation_id}")

    async def noop_transcript_title_update(
        conversation_id: UUID,
        user_prompt: str,
        assistant_message: str,
        *,
        is_internal: bool,
        on_title: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        del user_prompt, assistant_message, is_internal
        if on_title is not None:
            await on_title(f"Updated {conversation_id}")

    async def fake_select_and_store_grounding_sources_in_background(
        *,
        assistant_message_id: UUID,
        user_message_id: UUID,
        assistant_answer: str,
        sources: list[MessageSourceUsed],
    ) -> tuple[list[MessageSourceUsed], str]:
        del assistant_message_id, user_message_id, assistant_answer
        assert sources == [build_canned_response_source()]
        return [], "no_selection"

    monkeypatch.setattr(
        "app.api.routes.messages.handle_conversation_turn", fake_handle_conversation_turn
    )
    monkeypatch.setattr("app.api.routes.messages.summarize_internal_conversation", noop_summary)
    monkeypatch.setattr(
        "app.api.routes.messages._generate_initial_title", noop_initial_title_update
    )
    monkeypatch.setattr(
        "app.api.routes.messages._generate_transcript_title", noop_transcript_title_update
    )
    monkeypatch.setattr(
        "app.api.routes.messages._select_and_store_grounding_sources_in_background",
        fake_select_and_store_grounding_sources_in_background,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream", json={"user_prompt": "Hello there"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(response.text)
    event_names = [name for name, _ in events]
    assert event_names[0] == "conversation"
    assert event_names.count("title_update") == 2
    assert "agent_stage" in event_names
    assert "tool_call" in event_names
    assert "thinking" in event_names
    assert "assistant_message" in event_names

    conversation_event = next(payload for name, payload in events if name == "conversation")
    assistant_event = next(payload for name, payload in events if name == "assistant_message")
    title_updates = [payload for name, payload in events if name == "title_update"]
    agent_stage_event = next(payload for name, payload in events if name == "agent_stage")
    tool_call_event = next(payload for name, payload in events if name == "tool_call")
    thinking_event = next(payload for name, payload in events if name == "thinking")

    assert conversation_event["conversation_title"] == "Hello there"
    assert assistant_event["assistant_message"] == "Hello from the fake assistant"
    assert assistant_event["generation_time_ms"] == 1234
    assert assistant_event["generation_timing"] == {
        "total_time_ms": 1234,
        "chatbot_time_ms": 250,
        "guardrail_time_ms": 750,
        "chatbot_model": "azure/gpt-4o",
        "guardrail_model": "azure/gpt-4o-guardrails",
    }
    assert agent_stage_event["conversation_id"] == conversation_event["conversation_id"]
    assert tool_call_event["conversation_id"] == conversation_event["conversation_id"]
    assert thinking_event["conversation_id"] == conversation_event["conversation_id"]
    assert title_updates[0]["stage"] == "initial"
    assert title_updates[0]["title"] == f"Initial {conversation_event['conversation_id']}"
    assert title_updates[1]["stage"] == "post_assistant"
    assert title_updates[1]["title"] == f"Updated {conversation_event['conversation_id']}"


@pytest.mark.asyncio
async def test_internal_message_stream_rejects_invalid_reasoning_effort(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="stream-reasoning"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream",
            json={"user_prompt": "Hello", "chatbot_reasoning_effort": "unsupported"},
        )

    assert response.status_code == 422
    assert "chatbot_reasoning_effort" in response.text


@pytest.mark.asyncio
async def test_internal_message_stream_emits_assistant_before_grounding_sources(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="stream-grounding"
    )
    await replace_user_permission_overrides(
        transactional_session, user, {PermissionKey.CHAT_VIEW_SOURCES: True}
    )
    await transactional_session.commit()

    source = MessageSourceUsed(
        key="tool-1:website_page:42:search:0",
        type=DocumentType.WEBSITE_PAGE,
        id=42,
        title="Tuition and Fees",
        url="https://demo-university.example.edu/tuition",
        usage="search",
        tool_call_id="tool-1",
        tool_name="find_document_chunks",
    )
    canned_source = build_canned_response_source()

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        if conversation_id is None:
            conversation = Conversation(
                title=user_prompt, user=False, project="demo", user_id=user_id, is_public=False
            )
            session.add(conversation)
            await session.flush()
        else:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None

        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        session.add(user_message)
        await session.flush()

        assistant_message = Message(
            role="assistant",
            content="Tuition is listed online.",
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()
        user_message.active_child = assistant_message
        session.add(
            AssistantMessageMetadata(
                message_id=assistant_message.id,
                system_prompt_rendered="system",
                conversation_turn=1,
            )
        )
        await session.flush()

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    async def fake_get_tool_sources_used_for_message(
        session: AsyncSession, message_id: UUID
    ) -> list[MessageSourceUsed]:
        del session, message_id
        return [source]

    async def fake_select_and_store_grounding_sources_in_background(
        *,
        assistant_message_id: UUID,
        user_message_id: UUID,
        assistant_answer: str,
        sources: list[MessageSourceUsed],
    ) -> tuple[list[MessageSourceUsed], str]:
        del assistant_message_id, user_message_id, assistant_answer
        assert sources == [source, canned_source]
        return [source, canned_source], "selected"

    async def noop_summary(_: UUID) -> None:
        return None

    async def noop_title(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(
        "app.api.routes.messages.handle_conversation_turn", fake_handle_conversation_turn
    )
    monkeypatch.setattr(
        "app.api.routes.messages.get_tool_sources_used_for_message",
        fake_get_tool_sources_used_for_message,
    )
    monkeypatch.setattr(
        "app.api.routes.messages._select_and_store_grounding_sources_in_background",
        fake_select_and_store_grounding_sources_in_background,
    )
    monkeypatch.setattr("app.api.routes.messages.summarize_internal_conversation", noop_summary)
    monkeypatch.setattr("app.api.routes.messages._generate_initial_title", noop_title)
    monkeypatch.setattr("app.api.routes.messages._generate_transcript_title", noop_title)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream", json={"user_prompt": "Where is tuition listed?"}
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    event_names = [name for name, _payload in events]
    assert "grounding_sources" in event_names, response.text
    assert event_names.index("assistant_message") < event_names.index("grounding_sources")

    assistant_event = next(payload for name, payload in events if name == "assistant_message")
    grounding_event = next(payload for name, payload in events if name == "grounding_sources")

    assert assistant_event["assistant_message"] == "Tuition is listed online."
    assert assistant_event["grounding_source_status"] == "pending"
    assert assistant_event["grounding_sources_used"] == []
    assert grounding_event["assistant_message_id"] == assistant_event["assistant_message_id"]
    assert grounding_event["grounding_source_status"] == "selected"
    assert grounding_event["grounding_sources_used"] == [
        source.model_dump(mode="json"),
        canned_source.model_dump(mode="json"),
    ]


@pytest.mark.asyncio
async def test_internal_message_stream_passes_canned_candidate_when_no_tool_sources(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="stream-canned-source"
    )
    await replace_user_permission_overrides(
        transactional_session, user, {PermissionKey.CHAT_VIEW_SOURCES: True}
    )
    await transactional_session.commit()

    canned_source = build_canned_response_source()

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        if conversation_id is None:
            conversation = Conversation(
                title=user_prompt, user=False, project="demo", user_id=user_id, is_public=False
            )
            session.add(conversation)
            await session.flush()
        else:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None

        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        session.add(user_message)
        await session.flush()

        assistant_answer = (
            "You can tell the prospective student: "
            '"Yes, Demo University is an accredited university."'
        )
        assistant_message = Message(
            role="assistant",
            content=assistant_answer,
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()
        user_message.active_child = assistant_message
        session.add(
            AssistantMessageMetadata(
                message_id=assistant_message.id,
                system_prompt_rendered="system",
                conversation_turn=1,
            )
        )
        await session.flush()

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    async def fake_get_tool_sources_used_for_message(
        session: AsyncSession, message_id: UUID
    ) -> list[MessageSourceUsed]:
        del session, message_id
        return []

    async def fake_select_and_store_grounding_sources_in_background(
        *,
        assistant_message_id: UUID,
        user_message_id: UUID,
        assistant_answer: str,
        sources: list[MessageSourceUsed],
    ) -> tuple[list[MessageSourceUsed], str]:
        del assistant_message_id, user_message_id, assistant_answer
        assert sources == [canned_source]
        return [canned_source], "selected"

    async def noop_summary(_: UUID) -> None:
        return None

    async def noop_title(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(
        "app.api.routes.messages.handle_conversation_turn", fake_handle_conversation_turn
    )
    monkeypatch.setattr(
        "app.api.routes.messages.get_tool_sources_used_for_message",
        fake_get_tool_sources_used_for_message,
    )
    monkeypatch.setattr(
        "app.api.routes.messages._select_and_store_grounding_sources_in_background",
        fake_select_and_store_grounding_sources_in_background,
    )
    monkeypatch.setattr("app.api.routes.messages.summarize_internal_conversation", noop_summary)
    monkeypatch.setattr("app.api.routes.messages._generate_initial_title", noop_title)
    monkeypatch.setattr("app.api.routes.messages._generate_transcript_title", noop_title)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream", json={"user_prompt": "Are we accredited?"}
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    event_names = [name for name, _payload in events]
    assert "grounding_sources" in event_names
    assert event_names.index("assistant_message") < event_names.index("grounding_sources")

    assistant_event = next(payload for name, payload in events if name == "assistant_message")
    grounding_event = next(payload for name, payload in events if name == "grounding_sources")
    assert assistant_event["grounding_source_status"] == "pending"
    assert assistant_event["grounding_sources_used"] == []
    assert grounding_event["assistant_message_id"] == assistant_event["assistant_message_id"]
    assert grounding_event["grounding_source_status"] == "selected"
    assert grounding_event["grounding_sources_used"] == [canned_source.model_dump(mode="json")]


@pytest.mark.asyncio
async def test_internal_message_stream_allows_response_without_chat_view_activity_permission(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="stream-no-activity"
    )
    await replace_user_permission_overrides(
        transactional_session, user, {PermissionKey.CHAT_VIEW_ACTIVITY: False}
    )
    await transactional_session.commit()

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        event_emitter: Callable[[str, dict[str, object]], Awaitable[None]] | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        del event_emitter
        if conversation_id is None:
            conversation = Conversation(
                title=user_prompt, user=False, project="demo", user_id=user_id, is_public=False
            )
            session.add(conversation)
            await session.flush()
        else:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None

        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        session.add(user_message)
        await session.flush()

        assistant_message = Message(
            role="assistant",
            content="Hello from the fake assistant",
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()
        user_message.active_child = assistant_message
        session.add(
            AssistantMessageMetadata(
                message_id=assistant_message.id,
                system_prompt_rendered="system",
                conversation_turn=1,
            )
        )
        await session.flush()

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    async def fake_select_and_store_grounding_sources_in_background(
        *,
        assistant_message_id: UUID,
        user_message_id: UUID,
        assistant_answer: str,
        sources: list[MessageSourceUsed],
    ) -> tuple[list[MessageSourceUsed], str]:
        del assistant_message_id, user_message_id, assistant_answer
        assert sources == [build_canned_response_source()]
        return [], "no_selection"

    async def noop_summary(_: UUID) -> None:
        return None

    async def noop_title(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(
        "app.api.routes.messages.handle_conversation_turn", fake_handle_conversation_turn
    )
    monkeypatch.setattr(
        "app.api.routes.messages._select_and_store_grounding_sources_in_background",
        fake_select_and_store_grounding_sources_in_background,
    )
    monkeypatch.setattr("app.api.routes.messages.summarize_internal_conversation", noop_summary)
    monkeypatch.setattr("app.api.routes.messages._generate_initial_title", noop_title)
    monkeypatch.setattr("app.api.routes.messages._generate_transcript_title", noop_title)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream", json={"user_prompt": "Hello there"}
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert "assistant_message" in {name for name, _payload in events}


@pytest.mark.asyncio
async def test_rag_build_stream_returns_progress_logs_and_status(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-build"
    )

    async def fake_run_rag_sync_pipeline(
        *,
        job_name: str,
        progress_callback: Callable[[RagPipelineProgressSnapshot], Awaitable[None]],
        force_rebuild: bool = False,
        job_trigger: str = "manual",
        started_by_user_id: UUID | None = None,
        job_started_callback: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> UUID:
        assert job_name == "api_rag_build"
        assert callable(progress_callback)
        assert force_rebuild is False
        assert job_trigger == "manual"
        assert started_by_user_id == admin.id
        if job_started_callback is not None:
            await job_started_callback(admin.id)

        await progress_callback(
            RagPipelineProgressSnapshot(
                steps=[
                    RagPipelineStepSnapshot(
                        key="demo_corpus_ingest", label="Demo corpus ingest", status="running"
                    ),
                    RagPipelineStepSnapshot(
                        key="build_search_db", label="Build search DB", status="pending"
                    ),
                ],
                current_step="demo_corpus_ingest",
                finished_steps=0,
                total_steps=2,
            )
        )
        logger = logging.getLogger("app.tests.rag-build")
        logger.info("Writing Demo University corpus")
        logger.error("Building embeddings")
        await progress_callback(
            RagPipelineProgressSnapshot(
                steps=[
                    RagPipelineStepSnapshot(
                        key="demo_corpus_ingest", label="Demo corpus ingest", status="completed"
                    ),
                    RagPipelineStepSnapshot(
                        key="build_search_db", label="Build search DB", status="completed"
                    ),
                ],
                current_step=None,
                finished_steps=2,
                total_steps=2,
            )
        )
        return admin.id

    monkeypatch.setattr("app.api.routes.rag.run_rag_sync_pipeline", fake_run_rag_sync_pipeline)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/build/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(response.text)
    event_names = [name for name, _payload in events]
    logs = [payload for name, payload in events if name == "log"]
    progress_updates = [
        {key: value for key, value in payload.items() if key != "job_id"}
        for name, payload in events
        if name == "progress"
    ]
    statuses = [
        {key: value for key, value in payload.items() if key != "job_id"}
        for name, payload in events
        if name == "status"
    ]

    assert any(
        payload.get("stream") == "stdout"
        and payload.get("message") == "Writing Demo University corpus"
        for payload in logs
    )
    assert any(
        payload.get("stream") == "stderr" and payload.get("message") == "Building embeddings"
        for payload in logs
    )
    final_complete_index = max(
        index
        for index, (name, payload) in enumerate(events)
        if name == "status" and payload.get("status") == "complete"
    )
    assert all(
        index < final_complete_index for index, name in enumerate(event_names) if name == "log"
    )
    assert progress_updates == [
        {
            "steps": [
                {"key": "demo_corpus_ingest", "label": "Demo corpus ingest", "status": "running"},
                {"key": "build_search_db", "label": "Build search DB", "status": "pending"},
            ],
            "current_step": "demo_corpus_ingest",
            "finished_steps": 0,
            "total_steps": 2,
        },
        {
            "steps": [
                {"key": "demo_corpus_ingest", "label": "Demo corpus ingest", "status": "completed"},
                {"key": "build_search_db", "label": "Build search DB", "status": "completed"},
            ],
            "current_step": None,
            "finished_steps": 2,
            "total_steps": 2,
        },
    ]
    assert statuses == [{"status": "start"}, {"status": "complete", "exit_code": 0}]


@pytest.mark.asyncio
async def test_rag_build_stream_sends_error_details_before_terminal_status(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-error-order"
    )
    job_id = uuid4()

    async def fake_run_rag_sync_pipeline(
        *, job_started_callback: Callable[[UUID], Awaitable[None]] | None = None, **_: object
    ) -> UUID:
        if job_started_callback is not None:
            await job_started_callback(job_id)
        raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr("app.api.routes.rag.run_rag_sync_pipeline", fake_run_rag_sync_pipeline)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/build/stream")

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    error_index = next(index for index, (name, _payload) in enumerate(events) if name == "error")
    terminal_index = next(
        index
        for index, (name, payload) in enumerate(events)
        if name == "status" and payload.get("status") == "error"
    )
    error_payload = events[error_index][1]
    terminal_payload = events[terminal_index][1]

    assert error_index < terminal_index
    assert error_payload["job_id"] == str(job_id)
    assert error_payload["message"] == "Failed to run RAG build: embedding provider unavailable"
    assert terminal_payload["job_id"] == str(job_id)
    assert terminal_payload["exit_code"] == 1


@pytest.mark.asyncio
async def test_rag_build_stream_resume_existing_replays_active_job_snapshot(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-resume"
    )
    active_job_id = uuid4()
    pipeline_calls = 0

    async def fake_run_rag_sync_pipeline(**_: object) -> UUID:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return active_job_id

    async def fake_notifications() -> AsyncGenerator[tuple[str, dict[str, object]]]:
        yield ("status", {"job_id": str(active_job_id), "status": "complete", "exit_code": 0})

    @asynccontextmanager
    async def fake_listen() -> AsyncGenerator[AsyncGenerator[tuple[str, dict[str, object]]]]:
        yield fake_notifications()

    async def fake_snapshot_events() -> tuple[UUID, list[tuple[str, dict[str, object]]]]:
        return active_job_id, [
            ("status", {"job_id": str(active_job_id), "status": "start"}),
            (
                "progress",
                {
                    "job_id": str(active_job_id),
                    "steps": [
                        {
                            "key": "demo_corpus_ingest",
                            "label": "Demo corpus ingest",
                            "status": "running",
                        }
                    ],
                    "current_step": None,
                    "finished_steps": 0,
                    "total_steps": 1,
                },
            ),
        ]

    monkeypatch.setattr(rag_routes, "run_rag_sync_pipeline", fake_run_rag_sync_pipeline)
    monkeypatch.setattr(rag_routes, "listen_rag_build_notifications", fake_listen)
    monkeypatch.setattr(rag_routes, "active_manual_rag_build_snapshot_events", fake_snapshot_events)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/build/stream", json={"resume_existing": True})

    assert response.status_code == 200
    assert pipeline_calls == 0

    events = [
        (name, {key: value for key, value in payload.items() if key != "job_id"})
        for name, payload in _parse_sse_events(response.text)
    ]
    assert events == [
        ("status", {"status": "start"}),
        (
            "progress",
            {
                "steps": [
                    {
                        "key": "demo_corpus_ingest",
                        "label": "Demo corpus ingest",
                        "status": "running",
                    }
                ],
                "current_step": None,
                "finished_steps": 0,
                "total_steps": 1,
            },
        ),
        ("status", {"status": "complete", "exit_code": 0}),
    ]


@pytest.mark.asyncio
async def test_rag_build_stream_supports_force_rebuild(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-rebuild"
    )
    seen_force_rebuild: bool | None = None

    async def fake_run_rag_sync_pipeline(
        *,
        job_name: str,
        progress_callback: Callable[[RagPipelineProgressSnapshot], Awaitable[None]],
        force_rebuild: bool = False,
        job_trigger: str = "manual",
        started_by_user_id: UUID | None = None,
        job_started_callback: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> UUID:
        nonlocal seen_force_rebuild
        assert job_name == "api_rag_build"
        assert callable(progress_callback)
        assert job_trigger == "manual"
        assert started_by_user_id == admin.id
        seen_force_rebuild = force_rebuild
        if job_started_callback is not None:
            await job_started_callback(admin.id)
        return admin.id

    monkeypatch.setattr("app.api.routes.rag.run_rag_sync_pipeline", fake_run_rag_sync_pipeline)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/build/stream", json={"force_rebuild": True})

    assert response.status_code == 200
    assert seen_force_rebuild is True
    last_event_name, last_event_payload = _parse_sse_events(response.text)[-1]
    assert last_event_name == "status"
    assert {key: value for key, value in last_event_payload.items() if key != "job_id"} == {
        "status": "complete",
        "exit_code": 0,
    }


@pytest.mark.asyncio
async def test_conversation_routes_cover_internal_and_public_views(
    transactional_session: AsyncSession,
) -> None:
    internal_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="internal"
    )
    admin_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="admin"
    )
    dev_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="dev"
    )
    peer_admin_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="peer-admin"
    )
    await replace_user_permission_overrides(
        transactional_session, admin_user, {PermissionKey.ACCESS_MESSAGES: False}
    )

    internal_conversation = Conversation(
        title="Need help with admissions",
        summary="Internal summary",
        user=False,
        project="demo",
        user_id=internal_user.id,
        is_public=False,
    )
    transactional_session.add(internal_conversation)
    await transactional_session.flush()

    first_user_message = Message(
        role="user", content="I need help with admissions", conversation=internal_conversation
    )
    transactional_session.add(first_user_message)
    await transactional_session.flush()

    first_assistant_message = Message(
        role="assistant",
        content="Sure, I can help with admissions",
        conversation=internal_conversation,
        parent_id=first_user_message.id,
    )
    transactional_session.add(first_assistant_message)
    await transactional_session.flush()
    first_user_message.active_child = first_assistant_message

    chatbot_trace_id = uuid4().hex
    transactional_session.add_all(
        [
            OtelSpan(
                trace_id=chatbot_trace_id,
                span_id="root-span",
                parent_span_id=None,
                name="Calling app.chat.engine.handle_conversation_turn",
                message_id=first_assistant_message.id,
                conversation_id=internal_conversation.id,
                is_ai=False,
                attributes={"app.message_id": str(first_assistant_message.id)},
            ),
            OtelSpan(
                trace_id=chatbot_trace_id,
                span_id="chatbot-span",
                parent_span_id="root-span",
                name="invoke_agent chatbot",
                request_model="azure/gpt-4o",
                duration_ms=750.0,
                is_ai=True,
                attributes={"gen_ai.agent.name": "chatbot", "gen_ai.request.model": "azure/gpt-4o"},
            ),
        ]
    )

    internal_feedback = MessageFeedback(
        message_id=first_assistant_message.id,
        user_id=admin_user.id,
        rating=MessageRating.THUMBS_UP,
        text="Helpful",
    )
    transactional_session.add(internal_feedback)
    transactional_session.add(
        AssistantMessageMetadata(
            message_id=first_assistant_message.id,
            tool_calls=[
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "find_document_chunks",
                                "arguments": '{"content_search_query":"admissions"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "name": "find_document_chunks",
                    "content": json.dumps(
                        [
                            {
                                "content": "Admissions context",
                                "sources": {"website_page": [[1, [1], "Admissions"]]},
                            }
                        ]
                    ),
                },
            ],
            guardrails=None,
            system_prompt_rendered="system",
            conversation_turn=1,
            total_time=1.0,
            guardrail_model_settings={"model": "azure/gpt-4o-mini"},
            guardrail_time=0.3,
            chatbot_times=[0.25, 0.5],
            guardrail_times=[0.1, 0.2],
        )
    )

    public_conversation = Conversation(
        title="Public widget chat",
        summary="Public summary",
        user=False,
        project="demo",
        user_id=None,
        is_public=True,
    )
    transactional_session.add(public_conversation)
    await transactional_session.flush()

    public_user_message = Message(
        role="user", content="Hello from the public site", conversation=public_conversation
    )
    transactional_session.add(public_user_message)
    await transactional_session.flush()

    public_assistant_message = Message(
        role="assistant",
        content="Public answer",
        conversation=public_conversation,
        parent_id=public_user_message.id,
    )
    transactional_session.add(public_assistant_message)
    await transactional_session.flush()
    public_user_message.active_child = public_assistant_message

    peer_admin_conversation = Conversation(
        title="Admin policy notes",
        summary="Admin-only summary",
        user=False,
        project="demo",
        user_id=peer_admin_user.id,
        is_public=False,
    )
    transactional_session.add(peer_admin_conversation)
    await transactional_session.flush()

    peer_admin_user_message = Message(
        role="user", content="Share the admin policy notes", conversation=peer_admin_conversation
    )
    transactional_session.add(peer_admin_user_message)
    await transactional_session.flush()

    peer_admin_assistant_message = Message(
        role="assistant",
        content="Here are the admin policy notes",
        conversation=peer_admin_conversation,
        parent_id=peer_admin_user_message.id,
    )
    transactional_session.add(peer_admin_assistant_message)
    await transactional_session.flush()
    peer_admin_user_message.active_child = peer_admin_assistant_message

    transactional_session.add_all(
        [
            OtelSpan(
                trace_id="internal-trace",
                span_id="internal-span",
                parent_span_id=None,
                name="chat azure/gpt-4o",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=first_assistant_message.created_at,
                end_time=first_assistant_message.created_at,
                span_time=first_assistant_message.created_at,
                duration_ms=100.0,
                attributes={"app.conversation_id": str(internal_conversation.id)},
                events=None,
                links=None,
                resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                request_model="azure/gpt-4o",
                provider_name="azure",
                server_address=None,
                input_tokens=1,
                output_tokens=1,
                total_cost=0.1234,
                is_ai=True,
                is_embedding=False,
                is_internal=True,
                conversation_id=internal_conversation.id,
                message_id=first_assistant_message.id,
                total_time=None,
            ),
            OtelSpan(
                trace_id="public-trace",
                span_id="public-span",
                parent_span_id=None,
                name="chat azure/gpt-4o",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=public_assistant_message.created_at,
                end_time=public_assistant_message.created_at,
                span_time=public_assistant_message.created_at,
                duration_ms=100.0,
                attributes={"app.conversation_id": str(public_conversation.id)},
                events=None,
                links=None,
                resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                request_model="azure/gpt-4o",
                provider_name="azure",
                server_address=None,
                input_tokens=1,
                output_tokens=1,
                total_cost=0.0567,
                is_ai=True,
                is_embedding=False,
                is_internal=False,
                conversation_id=public_conversation.id,
                message_id=public_assistant_message.id,
                total_time=None,
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as internal_client:
        authenticate_client(internal_client, internal_user.id)
        list_response = await internal_client.get("/api/conversations")
        detail_response = await internal_client.get(
            f"/api/conversations/{internal_conversation.id}"
        )
        conversation_lookup_response = await internal_client.get(
            "/api/conversations/search", params={"search": "admissions"}
        )
        tree_response = await internal_client.get(
            f"/api/conversations/{internal_conversation.id}/tree"
        )
        feedback_response = await internal_client.get(
            f"/api/conversations/messages/{first_assistant_message.id}/feedback"
        )

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == str(internal_conversation.id)

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert [message["role"] for message in detail_body["messages"]] == ["user", "assistant"]
    assert detail_body["messages"][1]["feedback"][0]["rating"] == "thumbs_up"
    assert detail_body["messages"][1]["assistant_tool_calls"][0]["tool_calls"][0]["function"] == {
        "name": "find_document_chunks",
        "arguments": '{"content_search_query":"admissions"}',
    }
    assert detail_body["messages"][1]["generation_time_ms"] == 1000
    assert detail_body["messages"][1]["generation_timing"] == {
        "total_time_ms": 1000,
        "chatbot_time_ms": 750,
        "guardrail_time_ms": 300,
        "chatbot_times_ms": [250, 500],
        "guardrail_times_ms": [100, 200],
        "chatbot_model": "azure/gpt-4o",
        "guardrail_model": "azure/gpt-4o-mini",
    }

    assert conversation_lookup_response.status_code == 200
    assert conversation_lookup_response.json()[0]["id"] == str(internal_conversation.id)

    assert tree_response.status_code == 200
    tree_body = tree_response.json()
    assert tree_body["conversation_tree"]["current_branch_path"] == [
        str(first_user_message.id),
        str(first_assistant_message.id),
    ]

    assert feedback_response.status_code == 200
    assert feedback_response.json()[0]["text"] == "Helpful"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as admin_client:
        authenticate_client(admin_client, admin_user.id)
        admin_list_response = await admin_client.get("/api/conversations")
        admin_conversation_lookup_response = await admin_client.get(
            "/api/conversations/search", params={"search": "policy"}
        )
        paginated_response = await admin_client.get(
            "/api/conversations/paginated", params={"limit": 20, "offset": 0}
        )
        admin_messages_response = await admin_client.get(
            "/api/messages", params={"limit": 20, "offset": 0}
        )
        users_response = await admin_client.get("/api/conversations/users")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as dev_client:
        authenticate_client(dev_client, dev_user.id)
        messages_response = await dev_client.get("/api/messages", params={"limit": 20, "offset": 0})

    assert admin_list_response.status_code == 200
    assert admin_list_response.json() == []

    assert admin_conversation_lookup_response.status_code == 200
    assert admin_conversation_lookup_response.json() == []

    assert paginated_response.status_code == 200
    paginated_items = paginated_response.json()["items"]
    returned_ids = {item["id"] for item in paginated_items}
    assert returned_ids == {
        str(internal_conversation.id),
        str(public_conversation.id),
        str(peer_admin_conversation.id),
    }

    internal_item = next(
        item for item in paginated_items if item["id"] == str(internal_conversation.id)
    )
    public_item = next(
        item for item in paginated_items if item["id"] == str(public_conversation.id)
    )
    assert internal_item["feedback_up"] == 1
    assert internal_item["total_cost"] == 0.1234
    assert public_item["user_email"] is None
    assert public_item["is_public"] is True
    assert public_item["total_cost"] == 0.0567

    assert admin_messages_response.status_code == 403

    assert messages_response.status_code == 200
    message_items = messages_response.json()["items"]
    returned_message_ids = {item["id"] for item in message_items}
    assert str(first_assistant_message.id) in returned_message_ids
    assert str(public_assistant_message.id) in returned_message_ids
    internal_message_item = next(
        item for item in message_items if item["id"] == str(first_assistant_message.id)
    )
    assert internal_message_item["conversation_id"] == str(internal_conversation.id)
    assert internal_message_item["role"] == "assistant"
    assert internal_message_item["content"] == "Sure, I can help with admissions"
    assert internal_message_item["content_length"] == len("Sure, I can help with admissions")
    assert internal_message_item["generation_time_ms"] == 1000
    assert internal_message_item["trace_id"] == "internal-trace"
    assert internal_message_item["span_id"] == "internal-span"

    assert users_response.status_code == 200
    user_options = users_response.json()
    assert any(
        option["platform"] == "internal" and option["email"] == internal_user.email
        for option in user_options
    )
    assert any(
        option["platform"] == "internal" and option["email"] == peer_admin_user.email
        for option in user_options
    )
    assert all(option["platform"] != "public" for option in user_options)


@pytest.mark.asyncio
async def test_chats_page_visibility_respects_owner_group_permissions(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="reviewer"
    )
    peer_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="peer-user"
    )
    peer_admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="peer-admin"
    )
    peer_dev = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="peer-dev"
    )

    await replace_user_permission_overrides(
        transactional_session,
        reviewer,
        {
            PermissionKey.ACCESS_CHATS: True,
            PermissionKey.CHATS_VIEW_OWN: True,
            PermissionKey.CHATS_VIEW_ADMINS: True,
        },
    )

    reviewer_conversation = Conversation(
        title="Reviewer chat", user=False, project="demo", user_id=reviewer.id, is_public=False
    )
    peer_user_conversation = Conversation(
        title="Peer user chat", user=False, project="demo", user_id=peer_user.id, is_public=False
    )
    peer_admin_conversation = Conversation(
        title="Peer admin chat", user=False, project="demo", user_id=peer_admin.id, is_public=False
    )
    peer_dev_conversation = Conversation(
        title="Peer dev chat", user=False, project="demo", user_id=peer_dev.id, is_public=False
    )
    transactional_session.add_all(
        [
            reviewer_conversation,
            peer_user_conversation,
            peer_admin_conversation,
            peer_dev_conversation,
        ]
    )
    await transactional_session.flush()
    reviewer_message = Message(
        role="assistant", content="Reviewer answer", conversation=reviewer_conversation
    )
    peer_user_message = Message(
        role="assistant", content="Peer user answer", conversation=peer_user_conversation
    )
    peer_admin_message = Message(
        role="assistant", content="Peer admin answer", conversation=peer_admin_conversation
    )
    peer_dev_message = Message(
        role="assistant", content="Peer dev answer", conversation=peer_dev_conversation
    )
    transactional_session.add_all(
        [reviewer_message, peer_user_message, peer_admin_message, peer_dev_message]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as reviewer_client:
        authenticate_client(reviewer_client, reviewer.id)
        paginated_response = await reviewer_client.get(
            "/api/conversations/paginated", params={"limit": 20, "offset": 0}
        )
        messages_response = await reviewer_client.get(
            "/api/messages", params={"limit": 20, "offset": 0}
        )
        users_response = await reviewer_client.get("/api/conversations/users")
        own_detail_response = await reviewer_client.get(
            f"/api/conversations/{reviewer_conversation.id}", params={"source": "chats"}
        )
        admin_detail_response = await reviewer_client.get(
            f"/api/conversations/{peer_admin_conversation.id}", params={"source": "chats"}
        )
        user_detail_response = await reviewer_client.get(
            f"/api/conversations/{peer_user_conversation.id}", params={"source": "chats"}
        )
        dev_detail_response = await reviewer_client.get(
            f"/api/conversations/{peer_dev_conversation.id}", params={"source": "chats"}
        )

    assert paginated_response.status_code == 200
    assert {item["id"] for item in paginated_response.json()["items"]} == {
        str(reviewer_conversation.id),
        str(peer_admin_conversation.id),
    }

    assert messages_response.status_code == 403

    assert own_detail_response.status_code == 200
    assert admin_detail_response.status_code == 200
    assert user_detail_response.status_code == 403
    assert dev_detail_response.status_code == 403

    assert users_response.status_code == 200
    assert {(item["platform"], item["email"]) for item in users_response.json()} == {
        ("internal", reviewer.email),
        ("internal", peer_admin.email),
    }


@pytest.mark.asyncio
async def test_conversation_and_message_list_endpoints_filter_by_owner_group_shortcuts(
    transactional_session: AsyncSession,
) -> None:
    viewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="owner-group-viewer"
    )
    peer_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="owner-group-user"
    )
    peer_admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="owner-group-admin"
    )
    peer_dev = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="owner-group-dev"
    )

    await replace_user_permission_overrides(
        transactional_session,
        viewer,
        {
            PermissionKey.ACCESS_CHATS: True,
            PermissionKey.CHATS_VIEW_OWN: True,
            PermissionKey.CHATS_VIEW_USERS: True,
            PermissionKey.CHATS_VIEW_ADMINS: True,
            PermissionKey.CHATS_VIEW_DEVS: True,
        },
    )

    peer_user_conversation = Conversation(
        title="Peer user chat", user=False, project="demo", user_id=peer_user.id, is_public=False
    )
    peer_admin_conversation = Conversation(
        title="Peer admin chat", user=False, project="demo", user_id=peer_admin.id, is_public=False
    )
    peer_dev_conversation = Conversation(
        title="Peer dev chat", user=False, project="demo", user_id=peer_dev.id, is_public=False
    )
    transactional_session.add_all(
        [peer_user_conversation, peer_admin_conversation, peer_dev_conversation]
    )
    await transactional_session.flush()

    user_message = Message(role="user", content="User prompt", conversation=peer_user_conversation)
    admin_message = Message(
        role="user", content="Admin prompt", conversation=peer_admin_conversation
    )
    dev_message = Message(role="user", content="Dev prompt", conversation=peer_dev_conversation)
    transactional_session.add_all([user_message, admin_message, dev_message])
    await transactional_session.flush()

    peer_user_assistant = Message(
        role="assistant",
        content="User answer",
        parent_id=user_message.id,
        conversation=peer_user_conversation,
    )
    peer_admin_assistant = Message(
        role="assistant",
        content="Admin answer",
        parent_id=admin_message.id,
        conversation=peer_admin_conversation,
    )
    peer_dev_assistant = Message(
        role="assistant",
        content="Dev answer",
        parent_id=dev_message.id,
        conversation=peer_dev_conversation,
    )
    transactional_session.add_all([peer_user_assistant, peer_admin_assistant, peer_dev_assistant])
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as viewer_client:
        authenticate_client(viewer_client, viewer.id)
        staff_conversations_response = await viewer_client.get(
            "/api/conversations/paginated", params={"limit": 20, "offset": 0, "user_group": "staff"}
        )
        dev_conversations_response = await viewer_client.get(
            "/api/conversations/paginated", params={"limit": 20, "offset": 0, "user_group": "devs"}
        )
        staff_messages_response = await viewer_client.get(
            "/api/messages",
            params={"limit": 20, "offset": 0, "user_group": "staff", "role": "assistant"},
        )
        dev_messages_response = await viewer_client.get(
            "/api/messages",
            params={"limit": 20, "offset": 0, "user_group": "devs", "role": "assistant"},
        )
        conflict_response = await viewer_client.get(
            "/api/messages",
            params={
                "limit": 20,
                "offset": 0,
                "user_group": "staff",
                "user_email": peer_admin.email,
                "role": "assistant",
            },
        )

    assert staff_conversations_response.status_code == 200
    assert {item["id"] for item in staff_conversations_response.json()["items"]} == {
        str(peer_user_conversation.id),
        str(peer_admin_conversation.id),
    }

    assert dev_conversations_response.status_code == 200
    assert {item["id"] for item in dev_conversations_response.json()["items"]} == {
        str(peer_dev_conversation.id)
    }

    assert staff_messages_response.status_code == 200
    assert {item["conversation_id"] for item in staff_messages_response.json()["items"]} == {
        str(peer_user_conversation.id),
        str(peer_admin_conversation.id),
    }

    assert dev_messages_response.status_code == 200
    assert {item["conversation_id"] for item in dev_messages_response.json()["items"]} == {
        str(peer_dev_conversation.id)
    }

    assert conflict_response.status_code == 400


@pytest.mark.asyncio
async def test_owner_group_shortcuts_return_no_rows_when_group_scope_is_not_visible(
    transactional_session: AsyncSession,
) -> None:
    viewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="owner-group-no-scope-viewer",
    )
    peer_user = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="owner-group-no-scope-user",
    )
    peer_admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="owner-group-no-scope-admin",
    )
    peer_dev = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="owner-group-no-scope-dev",
    )

    await replace_user_permission_overrides(
        transactional_session,
        viewer,
        {
            PermissionKey.ACCESS_CHATS: True,
            PermissionKey.ACCESS_MESSAGES: True,
            PermissionKey.CHATS_VIEW_OWN: False,
            PermissionKey.CHATS_VIEW_USERS: False,
            PermissionKey.CHATS_VIEW_ADMINS: False,
            PermissionKey.CHATS_VIEW_DEVS: False,
        },
    )

    peer_user_conversation = Conversation(
        title="Peer user chat", user=False, project="demo", user_id=peer_user.id, is_public=False
    )
    peer_admin_conversation = Conversation(
        title="Peer admin chat", user=False, project="demo", user_id=peer_admin.id, is_public=False
    )
    peer_dev_conversation = Conversation(
        title="Peer dev chat", user=False, project="demo", user_id=peer_dev.id, is_public=False
    )
    transactional_session.add_all(
        [peer_user_conversation, peer_admin_conversation, peer_dev_conversation]
    )
    await transactional_session.flush()

    user_message = Message(role="user", content="User prompt", conversation=peer_user_conversation)
    admin_message = Message(
        role="user", content="Admin prompt", conversation=peer_admin_conversation
    )
    dev_message = Message(role="user", content="Dev prompt", conversation=peer_dev_conversation)
    transactional_session.add_all([user_message, admin_message, dev_message])
    await transactional_session.flush()

    transactional_session.add_all(
        [
            Message(
                role="assistant",
                content="User answer",
                parent_id=user_message.id,
                conversation=peer_user_conversation,
            ),
            Message(
                role="assistant",
                content="Admin answer",
                parent_id=admin_message.id,
                conversation=peer_admin_conversation,
            ),
            Message(
                role="assistant",
                content="Dev answer",
                parent_id=dev_message.id,
                conversation=peer_dev_conversation,
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as viewer_client:
        authenticate_client(viewer_client, viewer.id)
        staff_conversations_response = await viewer_client.get(
            "/api/conversations/paginated", params={"limit": 20, "offset": 0, "user_group": "staff"}
        )
        devs_conversations_response = await viewer_client.get(
            "/api/conversations/paginated", params={"limit": 20, "offset": 0, "user_group": "devs"}
        )
        staff_messages_response = await viewer_client.get(
            "/api/messages",
            params={"limit": 20, "offset": 0, "user_group": "staff", "role": "assistant"},
        )
        devs_messages_response = await viewer_client.get(
            "/api/messages",
            params={"limit": 20, "offset": 0, "user_group": "devs", "role": "assistant"},
        )

    assert staff_conversations_response.status_code == 200
    assert staff_conversations_response.json()["items"] == []

    assert devs_conversations_response.status_code == 200
    assert devs_conversations_response.json()["items"] == []

    assert staff_messages_response.status_code == 200
    assert staff_messages_response.json()["items"] == []

    assert devs_messages_response.status_code == 200
    assert devs_messages_response.json()["items"] == []


@pytest.mark.asyncio
async def test_investigation_list_endpoints_reject_public_platform(
    transactional_session: AsyncSession,
) -> None:
    dev = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="investigation-public"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, dev.id)
        paginated_response = await client.get(
            "/api/conversations/paginated",
            params={"kind": "investigation", "platform": "public", "limit": 20},
        )
        users_response = await client.get(
            "/api/conversations/users", params={"kind": "investigation", "platform": "public"}
        )

    assert paginated_response.status_code == 400
    assert users_response.status_code == 400


@pytest.mark.asyncio
async def test_investigation_workbench_list_only_returns_current_users_investigations(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="investigation-list"
    )
    peer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="investigation-peer-list",
    )
    owner_investigation = Conversation(
        title="Owner investigation",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=False,
        kind="investigation",
    )
    peer_investigation = Conversation(
        title="Peer investigation",
        user=False,
        project="demo",
        user_id=peer.id,
        is_public=False,
        kind="investigation",
    )
    owner_chat = Conversation(
        title="Owner normal chat",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=False,
        kind="chat",
    )
    transactional_session.add_all([owner_investigation, peer_investigation, owner_chat])
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as owner_client:
        authenticate_client(owner_client, owner.id)
        owner_response = await owner_client.get(
            "/api/conversations", params={"kind": "investigation"}
        )
        owner_review_response = await owner_client.get(
            "/api/conversations/paginated",
            params={"kind": "investigation", "platform": "internal", "limit": 20, "offset": 0},
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as peer_client:
        authenticate_client(peer_client, peer.id)
        peer_response = await peer_client.get(
            "/api/conversations", params={"kind": "investigation"}
        )

    assert owner_response.status_code == 200
    assert [item["id"] for item in owner_response.json()] == [str(owner_investigation.id)]

    assert owner_review_response.status_code == 200
    assert {item["id"] for item in owner_review_response.json()["items"]} == {
        str(owner_investigation.id),
        str(peer_investigation.id),
    }

    assert peer_response.status_code == 200
    assert [item["id"] for item in peer_response.json()] == [str(peer_investigation.id)]


@pytest.mark.asyncio
async def test_investigation_detail_splits_workbench_and_review_sources(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="investigation-owner"
    )
    peer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="investigation-peer"
    )
    investigation = Conversation(
        title="Investigation",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=False,
        kind="investigation",
    )
    transactional_session.add(investigation)
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as owner_client:
        authenticate_client(owner_client, owner.id)
        owner_workbench_response = await owner_client.get(
            f"/api/conversations/{investigation.id}", params={"source": "investigate"}
        )
        owner_review_response = await owner_client.get(
            f"/api/conversations/{investigation.id}", params={"source": "investigations"}
        )
        default_response = await owner_client.get(f"/api/conversations/{investigation.id}")
        chats_response = await owner_client.get(
            f"/api/conversations/{investigation.id}", params={"source": "chats"}
        )
        messages_response = await owner_client.get(
            f"/api/conversations/{investigation.id}", params={"source": "messages"}
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as peer_client:
        authenticate_client(peer_client, peer.id)
        peer_workbench_response = await peer_client.get(
            f"/api/conversations/{investigation.id}", params={"source": "investigate"}
        )
        peer_review_response = await peer_client.get(
            f"/api/conversations/{investigation.id}", params={"source": "investigations"}
        )

    assert owner_workbench_response.status_code == 200
    assert owner_review_response.status_code == 200
    assert default_response.status_code == 403
    assert chats_response.status_code == 403
    assert messages_response.status_code == 403
    assert peer_workbench_response.status_code == 403
    assert peer_review_response.status_code == 200


@pytest.mark.asyncio
async def test_investigation_stream_write_requires_owner(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="investigation-owner"
    )
    peer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="investigation-peer"
    )
    investigation = Conversation(
        title="Peer investigation",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=False,
        kind="investigation",
    )
    transactional_session.add(investigation)
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, peer.id)
        response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Can I add to this investigation?",
                "conversation_id": str(investigation.id),
                "conversation_kind": "investigation",
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_conversation_preview_and_search_use_guardrails_blocked_message(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="blocked-preview"
    )
    await replace_user_permission_overrides(
        transactional_session,
        user,
        {PermissionKey.ACCESS_CHATS: True, PermissionKey.CHATS_VIEW_OWN: True},
    )
    canned_message = "I'm not able to help with that, but an advisor can assist."
    raw_blocked_content = "Raw blocked answer that should not appear in previews"

    conversation = Conversation(
        title="Blocked answer chat", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    user_message = Message(role="user", content="Can you answer this?", conversation=conversation)
    transactional_session.add(user_message)
    await transactional_session.flush()

    assistant_message = Message(
        role="assistant",
        content=raw_blocked_content,
        conversation=conversation,
        parent_id=user_message.id,
        guardrails_blocked=True,
        guardrails_blocked_message=canned_message,
    )
    transactional_session.add(assistant_message)
    await transactional_session.flush()
    user_message.active_child = assistant_message
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/conversations/paginated", params={"limit": 20})
        conversation_lookup_response = await client.get(
            "/api/conversations/search", params={"search": "Raw blocked answer"}
        )

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == str(conversation.id))
    assert item["last_message_preview"] == canned_message
    assert raw_blocked_content not in item["last_message_preview"]

    assert conversation_lookup_response.status_code == 200
    search_item = next(
        item for item in conversation_lookup_response.json() if item["id"] == str(conversation.id)
    )
    assert search_item["snippet"] == canned_message
    assert raw_blocked_content not in search_item["snippet"]


@pytest.mark.asyncio
async def test_conversation_detail_target_message_extends_to_branch_leaf(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="target-path"
    )
    conversation = Conversation(
        title="Target path chat", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    first_user_message = Message(role="user", content="First", conversation=conversation)
    transactional_session.add(first_user_message)
    await transactional_session.flush()
    first_assistant_message = Message(
        role="assistant",
        content="First answer",
        conversation=conversation,
        parent_id=first_user_message.id,
    )
    transactional_session.add(first_assistant_message)
    await transactional_session.flush()
    first_user_message.active_child = first_assistant_message

    second_user_message = Message(
        role="user",
        content="Second",
        conversation=conversation,
        parent_id=first_assistant_message.id,
    )
    transactional_session.add(second_user_message)
    await transactional_session.flush()
    first_assistant_message.active_child = second_user_message
    second_assistant_message = Message(
        role="assistant",
        content="Second answer",
        conversation=conversation,
        parent_id=second_user_message.id,
    )
    transactional_session.add(second_assistant_message)
    await transactional_session.flush()
    second_user_message.active_child = second_assistant_message
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get(
            f"/api/conversations/{conversation.id}",
            params={"target_message_id": str(first_assistant_message.id)},
        )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()["messages"]] == [
        "First",
        "First answer",
        "Second",
        "Second answer",
    ]


@pytest.mark.asyncio
async def test_internal_summary_uses_guardrails_blocked_message(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="blocked-summary"
    )
    canned_message = "I'm not able to help with that, but an advisor can assist."
    raw_blocked_content = "Raw blocked answer that should not be summarized"

    conversation = Conversation(
        title="Blocked summary chat", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    user_message = Message(role="user", content="Can you answer this?", conversation=conversation)
    transactional_session.add(user_message)
    await transactional_session.flush()

    assistant_message = Message(
        role="assistant",
        content=raw_blocked_content,
        conversation=conversation,
        parent_id=user_message.id,
        guardrails_blocked=True,
        guardrails_blocked_message=canned_message,
    )
    transactional_session.add(assistant_message)
    await transactional_session.flush()
    user_message.active_child = assistant_message
    await transactional_session.commit()

    captured_transcript: dict[str, str] = {}

    async def fake_generate_summary(transcript: str) -> str:
        captured_transcript["value"] = transcript
        return "Safe summary"

    @asynccontextmanager
    async def fake_get_session() -> AsyncGenerator[AsyncSession]:
        try:
            yield transactional_session
            await transactional_session.commit()
        except Exception:
            await transactional_session.rollback()
            raise

    monkeypatch.setattr(internal_summary, "get_session", fake_get_session)
    monkeypatch.setattr(internal_summary, "_generate_internal_summary", fake_generate_summary)

    await internal_summary.summarize_internal_conversation(conversation.id)

    assert "value" in captured_transcript
    assert raw_blocked_content not in captured_transcript["value"]
    assert canned_message in captured_transcript["value"]
    assert "blocked by guardrails" in captured_transcript["value"]
    await transactional_session.refresh(conversation)
    assert conversation.summary == "Safe summary"


@pytest.mark.asyncio
async def test_update_message_active_child_returns_enrolment_agent_shape(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="branch"
    )

    conversation = Conversation(
        title="Branching chat", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    parent_message = Message(role="user", content="Question", conversation=conversation)
    transactional_session.add(parent_message)
    await transactional_session.flush()

    first_child = Message(
        role="assistant",
        content="First answer",
        conversation=conversation,
        parent_id=parent_message.id,
    )
    second_child = Message(
        role="assistant",
        content="Second answer",
        conversation=conversation,
        parent_id=parent_message.id,
    )
    transactional_session.add_all([first_child, second_child])
    await transactional_session.flush()
    parent_message.active_child = first_child
    parent_message_id = parent_message.id
    second_child_id = second_child.id
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.put(
            f"/api/conversations/messages/{parent_message_id}/active-child",
            json={"active_child_id": str(second_child_id)},
        )

    assert response.status_code == 200
    assert response.json() is None

    transactional_session.expire_all()
    reloaded_parent = await transactional_session.get(Message, parent_message_id)
    assert reloaded_parent is not None
    assert reloaded_parent.active_child_id == second_child_id
