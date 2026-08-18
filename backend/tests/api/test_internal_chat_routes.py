from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import grounding_agent
from app.api.deps import get_db_session
from app.api.message_sources import MessageSourceUsed, build_canned_response_source
from app.api.routes import chat as chat_routes
from app.api.routes import messages as message_routes
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
    ChatGenerationAttempt,
    Conversation,
    DocumentType,
    Message,
    MessageFeedback,
    OtelSpan,
    RagBuildJob,
    User,
)
from app.models import Rating as MessageRating
from app.rag import job_tracking as rag_job_tracking
from app.rag.pipeline import RagPipelineProgressSnapshot, RagPipelineStepSnapshot
from app.utils import current_time_utc
from tests.api.auth_helpers import authenticate_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator


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


@dataclass(frozen=True)
class _BranchGraph:
    conversation: Conversation
    root: Message
    current_answer: Message
    alternate_answer: Message
    follow_up: Message
    alternate_root: Message
    alternate_root_answer: Message


async def _create_branch_graph(session: AsyncSession, *, user: User, title: str) -> _BranchGraph:
    conversation = Conversation(
        title=title, user=False, project="demo", user_id=user.id, is_public=False
    )
    session.add(conversation)
    await session.flush()

    root = Message(role="user", content="Question", conversation=conversation)
    alternate_root = Message(role="user", content="Edited question", conversation=conversation)
    session.add_all([root, alternate_root])
    await session.flush()

    current_answer = Message(
        role="assistant", content="Current answer", conversation=conversation, parent_id=root.id
    )
    alternate_answer = Message(
        role="assistant", content="Alternate answer", conversation=conversation, parent_id=root.id
    )
    alternate_root_answer = Message(
        role="assistant",
        content="Edited answer",
        conversation=conversation,
        parent_id=alternate_root.id,
    )
    session.add_all([current_answer, alternate_answer, alternate_root_answer])
    await session.flush()

    follow_up = Message(
        role="user", content="Follow up", conversation=conversation, parent_id=alternate_answer.id
    )
    session.add(follow_up)
    await session.flush()

    conversation.active_root_message_id = root.id
    root.active_child_id = current_answer.id
    alternate_answer.active_child_id = follow_up.id
    alternate_root.active_child_id = alternate_root_answer.id
    return _BranchGraph(
        conversation=conversation,
        root=root,
        current_answer=current_answer,
        alternate_answer=alternate_answer,
        follow_up=follow_up,
        alternate_root=alternate_root,
        alternate_root_answer=alternate_root_answer,
    )


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
    observed_model_settings: list[tuple[ModelSettings, ModelSettings]] = []

    async def fake_handle_conversation_turn(
        *,
        user_prompt: str,
        user_id: UUID | None,
        session: AsyncSession,
        chatbot_model_settings: ModelSettings,
        guardrail_model_settings: ModelSettings,
        conversation_id: UUID | None = None,
        **_: object,
    ) -> tuple[UUID, MessageOut]:
        del conversation_id
        observed_user_ids.append(user_id)
        observed_model_settings.append((chatbot_model_settings, guardrail_model_settings))

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
    chatbot_settings, guardrail_settings = observed_model_settings[0]
    assert chatbot_settings.azure_service_tier == settings.CHATBOT_AZURE_SERVICE_TIER
    assert guardrail_settings.azure_service_tier == settings.GUARDRAIL_AZURE_SERVICE_TIER


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
async def test_public_message_route_enforces_continuation_contract(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="chat-parent-contract"
    )
    public_conversation = Conversation(
        title="Public branch", user=False, project="demo", user_id=owner.id, is_public=True
    )
    internal_conversation = Conversation(
        title="Internal branch", user=False, project="demo", user_id=owner.id, is_public=False
    )
    public_investigation = Conversation(
        title="Public investigation",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=True,
        kind="investigation",
    )
    transactional_session.add_all(
        [public_conversation, internal_conversation, public_investigation]
    )
    await transactional_session.flush()

    public_root = Message(role="user", content="Public root", conversation=public_conversation)
    transactional_session.add(public_root)
    await transactional_session.flush()
    public_leaf = Message(
        role="assistant",
        content="Public leaf",
        conversation=public_conversation,
        parent_id=public_root.id,
    )
    transactional_session.add(public_leaf)
    await transactional_session.flush()
    public_conversation.active_root_message_id = public_root.id
    public_root.active_child_id = public_leaf.id
    await transactional_session.commit()

    observed_parents: list[UUID | None] = []

    async def fake_handle_conversation_turn(
        *, conversation_id: UUID, parent_message_id: UUID | None, **_: object
    ) -> tuple[UUID, MessageOut]:
        observed_parents.append(parent_message_id)
        return public_root.id, MessageOut(
            id=public_leaf.id,
            role=public_leaf.role,
            content=public_leaf.content,
            created_at=public_leaf.created_at,
            parent_id=parent_message_id,
            conversation_id=conversation_id,
        )

    monkeypatch.setattr(chat_routes, "handle_conversation_turn", fake_handle_conversation_turn)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        omitted_parent = await client.post(
            f"{settings.API_STR}/chat/public/message",
            json={"user_prompt": "Continue public", "conversation_id": str(public_conversation.id)},
        )
        null_parent = await client.post(
            f"{settings.API_STR}/chat/public/message",
            json={
                "user_prompt": "New public root",
                "conversation_id": str(public_conversation.id),
                "parent_message_id": None,
            },
        )
        internal_conversation_response = await client.post(
            f"{settings.API_STR}/chat/public/message",
            json={
                "user_prompt": "Continue an internal conversation publicly",
                "conversation_id": str(internal_conversation.id),
            },
        )
        investigation_response = await client.post(
            f"{settings.API_STR}/chat/public/message",
            json={
                "user_prompt": "Continue an investigation publicly",
                "conversation_id": str(public_investigation.id),
            },
        )

    assert omitted_parent.status_code == 200
    assert null_parent.status_code == 200
    assert internal_conversation_response.status_code == 403
    assert internal_conversation_response.json()["detail"] == "Access denied"
    assert investigation_response.status_code == 400
    assert investigation_response.json()["detail"] == "Conversation is not a chat"
    assert observed_parents == [public_leaf.id, None]


@pytest.mark.asyncio
async def test_investigation_routes_require_effective_permission(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    developer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.DEV,
        email_prefix="investigation-authoring-permission",
    )
    await replace_user_permission_overrides(
        transactional_session, developer, {PermissionKey.ACCESS_INVESTIGATIONS: False}
    )
    investigation = Conversation(
        title="Protected investigation",
        user=False,
        project="demo",
        user_id=developer.id,
        is_public=False,
        kind="investigation",
    )
    transactional_session.add(investigation)
    await transactional_session.flush()
    root_message = Message(role="user", content="Investigation root", conversation=investigation)
    transactional_session.add(root_message)
    await transactional_session.flush()
    investigation.active_root_message_id = root_message.id
    await transactional_session.commit()

    async def unexpected_turn(**_: object) -> tuple[UUID, MessageOut]:
        raise AssertionError("The route must authorize before starting an investigation turn")

    monkeypatch.setattr("app.api.routes.messages.handle_investigation_turn", unexpected_turn)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, developer.id)
        response = await client.post(
            f"{settings.API_STR}/messages/internal/stream",
            json={
                "user_prompt": "Continue the investigation",
                "conversation_id": str(investigation.id),
                "conversation_kind": "investigation",
            },
        )
        branch_response = await client.put(
            f"{settings.API_STR}/conversations/{investigation.id}/active-branch",
            json={"message_id": str(root_message.id)},
        )
        tree_response = await client.get(
            f"{settings.API_STR}/conversations/{investigation.id}/tree",
            params={"source": "investigate"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    assert branch_response.status_code == 403
    assert branch_response.json()["detail"] == "Access denied"
    assert tree_response.status_code == 403
    assert tree_response.json()["detail"] == "Access denied"


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
        assert not session.in_transaction()
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
        assistant_message_id: UUID,
        is_internal: bool,
        on_title: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        del user_prompt, assistant_message, assistant_message_id, is_internal
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

    response_span_scope: set[object] = set()
    waited_span_scopes: list[set[object] | None] = []

    @contextmanager
    def fake_span_persistence_scope() -> Generator[set[object]]:
        yield response_span_scope

    async def fake_wait_for_pending_spans(
        *, trace_id: int | None = None, scope: set[object] | None = None
    ) -> None:
        assert trace_id is None
        waited_span_scopes.append(scope)

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
    monkeypatch.setattr(
        "app.api.routes.messages.span_persistence_scope", fake_span_persistence_scope
    )
    monkeypatch.setattr(
        "app.api.routes.messages.wait_for_pending_spans", fake_wait_for_pending_spans
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
    assert waited_span_scopes == [response_span_scope]


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


def test_internal_model_settings_apply_role_tiers_and_exclude_investigations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHATBOT_AZURE_SERVICE_TIER", "priority")
    monkeypatch.setattr(settings, "GUARDRAIL_AZURE_SERVICE_TIER", "priority")
    request = message_routes.ChatRequest(user_prompt="Hello")

    chatbot, guardrail = message_routes._get_model_settings(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        request, conversation_kind="chat"
    )
    investigation, unused_guardrail = message_routes._get_model_settings(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        request, conversation_kind="investigation"
    )

    assert chatbot.azure_service_tier == "priority"
    assert guardrail.azure_service_tier == "priority"
    assert investigation.azure_service_tier is None
    assert unused_guardrail.azure_service_tier == "priority"


@pytest.mark.asyncio
async def test_internal_message_stream_enforces_conversation_contract(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="stream-cross-conversation-parent",
    )
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="stream-reviewer"
    )
    first_conversation = Conversation(
        title="First chat", user=False, project="demo", user_id=user.id, is_public=False
    )
    second_conversation = Conversation(
        title="Second chat", user=False, project="demo", user_id=user.id, is_public=False
    )
    public_conversation = Conversation(
        title="Public chat", user=False, project="demo", user_id=reviewer.id, is_public=True
    )
    transactional_session.add_all([first_conversation, second_conversation, public_conversation])
    await transactional_session.flush()
    parent_message = Message(
        role="assistant", content="First chat response", conversation=first_conversation
    )
    second_assistant_message = Message(
        role="assistant", content="Second chat response", conversation=second_conversation
    )
    transactional_session.add_all([parent_message, second_assistant_message])
    await transactional_session.commit()
    observed_parents: list[UUID | None] = []

    async def record_parent(
        *, parent_message_id: UUID | None, **_: object
    ) -> tuple[UUID, MessageOut]:
        observed_parents.append(parent_message_id)
        return second_assistant_message.id, MessageOut(
            id=second_assistant_message.id,
            role=second_assistant_message.role,
            content=second_assistant_message.content,
            created_at=second_assistant_message.created_at,
            parent_id=parent_message_id,
            conversation_id=second_conversation.id,
        )

    monkeypatch.setattr("app.api.routes.messages.handle_conversation_turn", record_parent)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Continue from the wrong chat",
                "conversation_id": str(second_conversation.id),
                "parent_message_id": str(parent_message.id),
            },
        )
        missing_parent_response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Continue from a missing message",
                "conversation_id": str(second_conversation.id),
                "parent_message_id": str(uuid4()),
            },
        )
        new_conversation_response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Start from an existing message",
                "parent_message_id": str(parent_message.id),
            },
        )
        regeneration_without_parent = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Regenerate without a parent",
                "conversation_id": str(second_conversation.id),
                "is_regeneration": True,
            },
        )
        regeneration_with_assistant_parent = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Regenerate from an assistant",
                "conversation_id": str(second_conversation.id),
                "parent_message_id": str(second_assistant_message.id),
                "is_regeneration": True,
            },
        )
        root_response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Start a new root",
                "conversation_id": str(second_conversation.id),
                "parent_message_id": None,
            },
        )

        authenticate_client(client, reviewer.id)
        non_owner_response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Continue someone else's chat",
                "conversation_id": str(second_conversation.id),
            },
        )
        public_response = await client.post(
            "/api/messages/internal/stream",
            json={
                "user_prompt": "Continue a public chat internally",
                "conversation_id": str(public_conversation.id),
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Parent message is not in this conversation"
    assert missing_parent_response.status_code == 404
    assert missing_parent_response.json()["detail"] == "Parent message not found"
    assert new_conversation_response.status_code == 400
    assert (
        new_conversation_response.json()["detail"]
        == "A new conversation cannot have a parent message"
    )
    assert regeneration_without_parent.status_code == 400
    assert regeneration_without_parent.json()["detail"] == (
        "Regeneration requires an explicit parent message"
    )
    assert regeneration_with_assistant_parent.status_code == 400
    assert regeneration_with_assistant_parent.json()["detail"] == (
        "Regeneration parent must be a user message"
    )
    assert root_response.status_code == 200
    assert observed_parents == [None]
    assert non_owner_response.status_code == 403
    assert non_owner_response.json()["detail"] == "Access denied"
    assert public_response.status_code == 403
    assert public_response.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_internal_message_stream_returns_safe_retryable_generation_error(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="generation-error"
    )
    conversation = Conversation(
        title="Generation failure", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.commit()
    generation_attempt_id = uuid4()

    partial_message_ids: list[UUID] = []

    async def fail_conversation_turn(
        *, user_prompt: str, session: AsyncSession, **_: object
    ) -> tuple[UUID, MessageOut]:
        user_message = Message(conversation_id=conversation.id, role="user", content=user_prompt)
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="Partial answer",
            parent=user_message,
        )
        session.add_all([user_message, assistant_message])
        await session.flush()
        partial_message_ids.extend([user_message.id, assistant_message.id])
        raise RuntimeError("secret provider failure")

    monkeypatch.setattr(message_routes, "handle_conversation_turn", fail_conversation_turn)

    connection = await transactional_session.connection()
    original_override = app.dependency_overrides[get_db_session]
    async with AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as route_session:

        async def override_get_db_session() -> AsyncGenerator[AsyncSession]:
            yield route_session

        app.dependency_overrides[get_db_session] = override_get_db_session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                authenticate_client(client, user.id)
                response = await client.post(
                    "/api/messages/internal/stream",
                    json={
                        "generation_attempt_id": str(generation_attempt_id),
                        "user_prompt": "Please answer",
                        "conversation_id": str(conversation.id),
                    },
                )
        finally:
            app.dependency_overrides[get_db_session] = original_override

    events = _parse_sse_events(response.text)
    assert [name for name, _payload in events] == ["conversation", "error"]
    error_payload = events[-1][1]
    assert error_payload == {
        "code": "message_generation_failed",
        "message": "The response could not be completed.",
        "retryable": True,
    }
    assert partial_message_ids
    for message_id in partial_message_ids:
        assert await transactional_session.get(Message, message_id) is None
    attempt = await transactional_session.get(
        ChatGenerationAttempt, generation_attempt_id, populate_existing=True
    )
    assert attempt is not None
    assert attempt.status == "failed"
    assert attempt.user_message_id is None
    assert attempt.assistant_message_id is None


@pytest.mark.asyncio
async def test_internal_message_stream_recovers_committed_response_after_diagnostics_failure(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="delivery-error"
    )
    conversation = Conversation(
        title="Delivery failure", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.commit()

    persisted_user_message_id: UUID | None = None
    persisted_assistant_message_id: UUID | None = None

    async def fake_handle_conversation_turn(
        *, user_prompt: str, session: AsyncSession, **_: object
    ) -> tuple[UUID, MessageOut]:
        nonlocal persisted_user_message_id, persisted_assistant_message_id
        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        assistant_message = Message(
            role="assistant",
            content="Persisted answer",
            conversation=conversation,
            parent=user_message,
        )
        session.add_all([user_message, assistant_message])
        await session.flush()
        user_message.active_child = assistant_message
        conversation.active_root_message_id = user_message.id
        metadata = AssistantMessageMetadata(
            message_id=assistant_message.id, system_prompt_rendered="system", conversation_turn=1
        )
        session.add(metadata)
        await session.flush()
        persisted_user_message_id = user_message.id
        persisted_assistant_message_id = assistant_message.id
        return user_message.id, MessageOut(
            id=assistant_message.id,
            role="assistant",
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=user_message.id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    async def fail_response_diagnostics(*_: object, **__: object) -> dict[str, object]:
        raise RuntimeError("diagnostic projection failed")

    monkeypatch.setattr(message_routes, "handle_conversation_turn", fake_handle_conversation_turn)
    monkeypatch.setattr(
        message_routes, "_get_message_response_diagnostics", fail_response_diagnostics
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            "/api/messages/internal/stream",
            json={"user_prompt": "Please answer", "conversation_id": str(conversation.id)},
        )

    assert persisted_user_message_id is not None
    assert persisted_assistant_message_id is not None
    events = _parse_sse_events(response.text)
    assert [name for name, _payload in events] == ["conversation", "assistant_message"]
    recovered_response = events[-1][1]
    assert recovered_response["conversation_id"] == str(conversation.id)
    assert recovered_response["user_message_id"] == str(persisted_user_message_id)
    assert recovered_response["assistant_message_id"] == str(persisted_assistant_message_id)
    assert recovered_response["assistant_message"] == "Persisted answer"
    assert recovered_response["grounding_source_status"] is None
    assert recovered_response["tool_sources_used"] == []
    assert recovered_response["grounding_sources_used"] == []
    assert await transactional_session.get(Message, persisted_user_message_id) is not None
    assert await transactional_session.get(Message, persisted_assistant_message_id) is not None


@pytest.mark.asyncio
async def test_internal_message_generation_attempt_is_idempotent(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="generation-attempt"
    )
    conversation = Conversation(
        title="Idempotent generation", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.commit()

    generation_attempt_id = uuid4()
    turn_calls = 0

    async def fake_handle_conversation_turn(
        *, user_prompt: str, session: AsyncSession, **_: object
    ) -> tuple[UUID, MessageOut]:
        nonlocal turn_calls
        turn_calls += 1
        user_message = Message(role="user", content=user_prompt, conversation=conversation)
        assistant_message = Message(
            role="assistant",
            content="One durable answer",
            conversation=conversation,
            parent=user_message,
        )
        session.add_all([user_message, assistant_message])
        await session.flush()
        user_message.active_child = assistant_message
        conversation.active_root_message_id = user_message.id
        metadata = AssistantMessageMetadata(
            message_id=assistant_message.id, system_prompt_rendered="system", conversation_turn=1
        )
        session.add(metadata)
        await session.flush()
        return user_message.id, MessageOut(
            id=assistant_message.id,
            role="assistant",
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=user_message.id,
            conversation_id=conversation.id,
            metadata=None,
            guardrails_blocked=False,
        )

    async def finish_grounding(**_: object) -> tuple[list[MessageSourceUsed], str]:
        return [], "no_selection"

    async def noop_summary(_: UUID) -> None:
        return None

    monkeypatch.setattr(message_routes, "handle_conversation_turn", fake_handle_conversation_turn)
    monkeypatch.setattr(
        message_routes, "_select_and_store_grounding_sources_in_background", finish_grounding
    )
    monkeypatch.setattr(message_routes, "summarize_internal_conversation", noop_summary)

    request_payload = {
        "generation_attempt_id": str(generation_attempt_id),
        "user_prompt": "Please answer once",
        "conversation_id": str(conversation.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        first_response = await client.post("/api/messages/internal/stream", json=request_payload)
        duplicate_response = await client.post(
            "/api/messages/internal/stream", json=request_payload
        )
        status_response = await client.get(
            f"/api/messages/internal/generation-attempts/{generation_attempt_id}"
        )
        mismatch_response = await client.post(
            "/api/messages/internal/stream",
            json={**request_payload, "user_prompt": "Different prompt"},
        )

    first_events = _parse_sse_events(first_response.text)
    first_assistant = next(payload for name, payload in first_events if name == "assistant_message")

    assert turn_calls == 1
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Generation attempt is already completed"
    assert status_response.status_code == 200
    assert status_response.json() == {
        "generation_attempt_id": str(generation_attempt_id),
        "status": "completed",
        "conversation_id": str(conversation.id),
        "user_message_id": first_assistant["user_message_id"],
        "assistant_message_id": first_assistant["assistant_message_id"],
    }
    assert mismatch_response.status_code == 409
    assert mismatch_response.json()["detail"] == (
        "Generation attempt payload does not match the original request"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempt_status", "expected_detail"),
    [
        ("pending", "Generation attempt is still pending"),
        ("failed", "Generation attempt has already failed"),
    ],
)
async def test_existing_generation_attempt_never_runs_generation_again(
    transactional_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempt_status: str,
    expected_detail: str,
) -> None:
    user = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix=f"existing-{attempt_status}-attempt",
    )
    conversation = Conversation(
        title="Existing attempt", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()
    generation_attempt_id = uuid4()
    request_payload = {
        "generation_attempt_id": str(generation_attempt_id),
        "user_prompt": "Do not run this twice",
        "conversation_id": str(conversation.id),
    }
    request = message_routes.ChatRequest.model_validate(request_payload)
    attempt = ChatGenerationAttempt(
        id=generation_attempt_id,
        user_id=user.id,
        conversation_id=conversation.id,
        request_fingerprint=message_routes.generation_request_fingerprint(request),
        status=attempt_status,
    )
    transactional_session.add(attempt)
    await transactional_session.commit()

    async def unexpected_turn(**_: object) -> tuple[UUID, MessageOut]:
        raise AssertionError("An existing attempt must not run generation again")

    monkeypatch.setattr(message_routes, "handle_conversation_turn", unexpected_turn)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post("/api/messages/internal/stream", json=request_payload)

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail


@pytest.mark.asyncio
async def test_internal_generation_attempt_status_and_detail_keep_pending_work_non_retryable(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="pending-generation-owner",
    )
    other_user = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="pending-generation-other",
    )
    conversation = Conversation(
        title="Pending generation", user=False, project="demo", user_id=owner.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()
    attempt = ChatGenerationAttempt(
        user_id=owner.id,
        conversation_id=conversation.id,
        request_fingerprint="a" * 64,
        status="pending",
    )
    transactional_session.add(attempt)
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        owner_response = await client.get(
            f"/api/messages/internal/generation-attempts/{attempt.id}"
        )
        owner_detail_response = await client.get(
            f"/api/conversations/{conversation.id}", params={"source": "chat"}
        )
        authenticate_client(client, other_user.id)
        other_response = await client.get(
            f"/api/messages/internal/generation-attempts/{attempt.id}"
        )

    assert owner_response.status_code == 200
    assert owner_response.json()["status"] == "pending"
    assert owner_detail_response.status_code == 200
    assert owner_detail_response.json()["has_pending_generation_attempt"] is True
    assert other_response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("grounding_fails", [False, True], ids=["selected", "failed"])
async def test_internal_message_stream_emits_assistant_before_grounding_result(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, grounding_fails: bool
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
        return ([], "failed") if grounding_fails else ([source, canned_source], "selected")

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
    assert grounding_event["grounding_source_status"] == (
        "failed" if grounding_fails else "selected"
    )
    assert grounding_event["grounding_sources_used"] == (
        []
        if grounding_fails
        else [source.model_dump(mode="json"), canned_source.model_dump(mode="json")]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_status", ["failed", "stale_pending"], ids=["failed", "stale-pending"]
)
async def test_retry_internal_message_grounding_runs_only_for_retryable_status(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, initial_status: str
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="retry-grounding"
    )
    await replace_user_permission_overrides(
        transactional_session, user, {PermissionKey.CHAT_VIEW_SOURCES: True}
    )
    conversation = Conversation(
        title="Retry grounding", user=False, project="demo", user_id=user.id, is_public=False
    )
    user_message = Message(role="user", content="Where is tuition?", conversation=conversation)
    assistant_message = Message(
        role="assistant",
        content="Tuition is listed online.",
        conversation=conversation,
        parent=user_message,
    )
    metadata = AssistantMessageMetadata(
        message=assistant_message,
        system_prompt_rendered="system",
        conversation_turn=1,
        grounding_source_keys=[] if initial_status == "failed" else None,
        grounding_source_status="failed" if initial_status == "failed" else "pending",
        updated_at=(
            current_time_utc()
            - grounding_agent.GROUNDING_PENDING_STALE_AFTER
            - timedelta(seconds=1)
            if initial_status == "stale_pending"
            else current_time_utc()
        ),
    )
    transactional_session.add_all([conversation, user_message, assistant_message, metadata])
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
    retry_calls = 0

    async def fake_get_tool_sources_used_for_message(
        session: AsyncSession, message_id: UUID, **_: object
    ) -> list[MessageSourceUsed]:
        del session
        assert message_id == assistant_message.id
        return [source]

    async def fake_select_and_store_grounding_sources_in_background(
        *,
        assistant_message_id: UUID,
        user_message_id: UUID,
        assistant_answer: str,
        sources: list[MessageSourceUsed],
    ) -> tuple[list[MessageSourceUsed], str]:
        nonlocal retry_calls
        retry_calls += 1
        assert assistant_message_id == assistant_message.id
        assert user_message_id == user_message.id
        assert assistant_answer == assistant_message.content
        assert sources == [source, canned_source]
        assert metadata.grounding_source_status == "pending"
        metadata.grounding_source_keys = [source.key]
        metadata.grounding_source_status = "selected"
        await transactional_session.flush()
        return [source], "selected"

    monkeypatch.setattr(
        message_routes, "get_tool_sources_used_for_message", fake_get_tool_sources_used_for_message
    )
    monkeypatch.setattr(
        message_routes,
        "_select_and_store_grounding_sources_in_background",
        fake_select_and_store_grounding_sources_in_background,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        detail_response = await client.get(
            f"/api/conversations/{conversation.id}", params={"source": "chat"}
        )
        assert detail_response.status_code == 200
        detail_message = next(
            item
            for item in detail_response.json()["messages"]
            if item["id"] == str(assistant_message.id)
        )
        assert detail_message["grounding_source_status"] == "failed"
        assert metadata.grounding_source_status == (
            "failed" if initial_status == "failed" else "pending"
        )

        response = await client.post(
            f"/api/messages/internal/{assistant_message.id}/grounding/retry"
        )
        duplicate_response = await client.post(
            f"/api/messages/internal/{assistant_message.id}/grounding/retry"
        )

    assert response.status_code == 200
    assert response.json() == {
        "assistant_message_id": str(assistant_message.id),
        "grounding_sources_used": [source.model_dump(mode="json")],
        "grounding_source_status": "selected",
    }
    assert metadata.grounding_source_keys == [source.key]
    assert metadata.grounding_source_status == "selected"
    assert retry_calls == 1
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Source grounding is not retryable"


@pytest.mark.asyncio
async def test_retry_internal_message_grounding_terminalizes_background_failure(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="retry-grounding-failure",
    )
    await replace_user_permission_overrides(
        transactional_session, user, {PermissionKey.CHAT_VIEW_SOURCES: True}
    )
    conversation = Conversation(
        title="Retry grounding failure",
        user=False,
        project="demo",
        user_id=user.id,
        is_public=False,
    )
    user_message = Message(role="user", content="Where is tuition?", conversation=conversation)
    assistant_message = Message(
        role="assistant",
        content="Tuition is listed online.",
        conversation=conversation,
        parent=user_message,
    )
    metadata = AssistantMessageMetadata(
        message=assistant_message,
        system_prompt_rendered="system",
        conversation_turn=1,
        grounding_source_keys=[],
        grounding_source_status="failed",
    )
    transactional_session.add_all([conversation, user_message, assistant_message, metadata])
    await transactional_session.commit()

    async def no_tool_sources(*_: object, **__: object) -> list[MessageSourceUsed]:
        return []

    async def fail_before_selection_commit(**_: object) -> None:
        raise RuntimeError("grounding setup failed")

    @asynccontextmanager
    async def use_test_session() -> AsyncGenerator[AsyncSession]:
        try:
            yield transactional_session
            await transactional_session.commit()
        except BaseException:
            await transactional_session.rollback()
            raise

    monkeypatch.setattr(message_routes, "get_tool_sources_used_for_message", no_tool_sources)
    monkeypatch.setattr(
        message_routes, "select_and_store_grounding_sources", fail_before_selection_commit
    )
    monkeypatch.setattr(message_routes, "get_session", use_test_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post(
            f"/api/messages/internal/{assistant_message.id}/grounding/retry"
        )

    assert response.status_code == 200
    assert response.json() == {
        "assistant_message_id": str(assistant_message.id),
        "grounding_sources_used": [],
        "grounding_source_status": "failed",
    }
    await transactional_session.refresh(metadata)
    assert metadata.grounding_source_keys == []
    assert metadata.grounding_source_status == "failed"


@pytest.mark.asyncio
async def test_retry_internal_message_grounding_requires_permission_and_ownership(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="retry-grounding-owner"
    )
    reviewer = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="retry-grounding-reviewer",
    )
    await replace_user_permission_overrides(
        transactional_session, owner, {PermissionKey.CHAT_VIEW_SOURCES: False}
    )
    await replace_user_permission_overrides(
        transactional_session, reviewer, {PermissionKey.CHAT_VIEW_SOURCES: True}
    )
    conversation = Conversation(
        title="Private grounding retry",
        user=False,
        project="demo",
        user_id=owner.id,
        is_public=False,
    )
    user_message = Message(role="user", content="Question", conversation=conversation)
    assistant_message = Message(
        role="assistant", content="Answer", conversation=conversation, parent=user_message
    )
    metadata = AssistantMessageMetadata(
        message=assistant_message,
        system_prompt_rendered="system",
        conversation_turn=1,
        grounding_source_keys=[],
        grounding_source_status="failed",
    )
    transactional_session.add_all([conversation, user_message, assistant_message, metadata])
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        missing_permission_response = await client.post(
            f"/api/messages/internal/{assistant_message.id}/grounding/retry"
        )
        authenticate_client(client, reviewer.id)
        non_owner_response = await client.post(
            f"/api/messages/internal/{assistant_message.id}/grounding/retry"
        )

    assert missing_permission_response.status_code == 403
    assert missing_permission_response.json()["detail"] == "Access denied"
    assert non_owner_response.status_code == 403
    assert non_owner_response.json()["detail"] == "Access denied"


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
@pytest.mark.parametrize(
    ("request_payload", "expected_options"),
    [({}, {"force_rebuild": False}), ({"force_rebuild": True}, {"force_rebuild": True})],
)
async def test_rag_build_stream_forwards_build_options(
    request_payload: dict[str, object],
    expected_options: dict[str, object],
    transactional_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-build-options"
    )
    seen_options: dict[str, object] | None = None

    async def fake_run_rag_sync_pipeline(
        *,
        job_name: str,
        progress_callback: Callable[[RagPipelineProgressSnapshot], Awaitable[None]],
        force_rebuild: bool = False,
        job_trigger: str = "manual",
        started_by_user_id: UUID | None = None,
        job_started_callback: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> UUID:
        nonlocal seen_options
        assert job_name == "api_rag_build"
        assert callable(progress_callback)
        assert job_trigger == "manual"
        assert started_by_user_id == admin.id
        seen_options = {"force_rebuild": force_rebuild}
        if job_started_callback is not None:
            await job_started_callback(admin.id)
        return admin.id

    monkeypatch.setattr("app.api.routes.rag.run_rag_sync_pipeline", fake_run_rag_sync_pipeline)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/build/stream", json=request_payload)

    assert response.status_code == 200
    assert seen_options == expected_options
    last_event_name, last_event_payload = _parse_sse_events(response.text)[-1]
    assert last_event_name == "status"
    assert {key: value for key, value in last_event_payload.items() if key != "job_id"} == {
        "status": "complete",
        "exit_code": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", ["running", "cancelling"])
async def test_rag_build_cancel_clears_stale_manual_job(
    initial_status: str, transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-stale-cancel"
    )
    stale_job = RagBuildJob(
        job_name="api_rag_build",
        trigger="manual",
        status=initial_status,
        force_rebuild=False,
        started_by_user_id=admin.id,
    )
    transactional_session.add(stale_job)
    await transactional_session.commit()
    await transactional_session.refresh(stale_job)
    stale_job_id = stale_job.id

    @asynccontextmanager
    async def fake_get_session() -> AsyncGenerator[AsyncSession]:
        yield transactional_session

    async def fake_rag_pipeline_lock_is_held() -> bool:
        return False

    published_statuses: list[str] = []

    async def fake_publish_rag_build_notification(event: str, payload: dict[str, object]) -> None:
        assert event == "status"
        assert payload["job_id"] == str(stale_job_id)
        status = payload.get("status")
        assert isinstance(status, str)
        published_statuses.append(status)

    monkeypatch.setattr(rag_job_tracking, "get_session", fake_get_session)
    monkeypatch.setattr(rag_routes, "rag_pipeline_lock_is_held", fake_rag_pipeline_lock_is_held)
    monkeypatch.setattr(
        rag_routes, "publish_rag_build_notification", fake_publish_rag_build_notification
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/build/cancel")

    assert response.status_code == 200
    assert response.json() == {"job_id": str(stale_job_id), "status": "cancelled"}
    assert published_statuses == ["cancelling", "cancelled"]
    transactional_session.expire_all()
    reloaded_job = await transactional_session.get(RagBuildJob, stale_job_id)
    assert reloaded_job is not None
    assert reloaded_job.status == "cancelled"
    assert reloaded_job.finished_at is not None
    assert reloaded_job.error_message == "RAG build was cancelled"


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
        transactional_session,
        internal_user,
        {PermissionKey.ACCESS_MESSAGES: True, PermissionKey.CHATS_VIEW_OWN: True},
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
                attributes={
                    "app.conversation_id": str(internal_conversation.id),
                    "gen_ai.usage.cache_read.input_tokens": 4,
                },
                events=None,
                links=None,
                resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                request_model="azure/gpt-4o",
                provider_name="azure",
                server_address=None,
                input_tokens=11,
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
                attributes={
                    "app.conversation_id": str(public_conversation.id),
                    "gen_ai.usage.cache_read.input_tokens": 8,
                },
                events=None,
                links=None,
                resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                request_model="azure/gpt-4o",
                provider_name="azure",
                server_address=None,
                input_tokens=10,
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
        messages_without_cost_response = await internal_client.get(
            "/api/messages", params={"limit": 20, "offset": 0}
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
    assert tree_body["current_branch_path"] == [
        str(first_user_message.id),
        str(first_assistant_message.id),
    ]
    assert [message["id"] for message in tree_body["messages"]] == [
        str(first_user_message.id),
        str(first_assistant_message.id),
    ]

    assert feedback_response.status_code == 200
    assert feedback_response.json()[0]["text"] == "Helpful"

    assert messages_without_cost_response.status_code == 200
    message_without_cost = next(
        item
        for item in messages_without_cost_response.json()["items"]
        if item["id"] == str(first_assistant_message.id)
    )
    assert message_without_cost["response_cost"] is None

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
        diagnostic_sort_responses = [
            await dev_client.get(
                "/api/messages",
                params={"limit": 20, "offset": 0, "sort_by": sort_by, "descending": True},
            )
            for sort_by in ("uncached_input_tokens", "cache_read_input_tokens", "response_cost")
        ]

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
    assert internal_item["message_count"] == 2
    assert internal_item["total_cost"] == 0.1234
    assert public_item["user_message_count"] == 1
    assert public_item["assistant_message_count"] == 1
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
    public_message_item = next(
        item for item in message_items if item["id"] == str(public_assistant_message.id)
    )
    assert internal_message_item["conversation_id"] == str(internal_conversation.id)
    assert internal_message_item["role"] == "assistant"
    assert internal_message_item["content"] == "Sure, I can help with admissions"
    assert internal_message_item["content_length"] == len("Sure, I can help with admissions")
    assert internal_message_item["generation_time_ms"] == 1000
    assert internal_message_item["input_tokens"] == 11
    assert internal_message_item["uncached_input_tokens"] == 7
    assert internal_message_item["cache_read_input_tokens"] == 4
    assert internal_message_item["output_tokens"] == 1
    assert internal_message_item["response_cost"] == 0.1234
    assert internal_message_item["trace_id"] == "internal-trace"
    assert internal_message_item["span_id"] == "internal-span"
    assert public_message_item["uncached_input_tokens"] == 2
    assert public_message_item["cache_read_input_tokens"] == 8
    assert public_message_item["response_cost"] == 0.0567

    assert all(response.status_code == 200 for response in diagnostic_sort_responses)
    assert [response.json()["items"][0]["id"] for response in diagnostic_sort_responses] == [
        str(first_assistant_message.id),
        str(public_assistant_message.id),
        str(first_assistant_message.id),
    ]

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
async def test_paginated_conversations_returns_and_sorts_role_message_counts(
    transactional_session: AsyncSession,
) -> None:
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="message-count-reviewer"
    )
    first_conversation = Conversation(
        title="More user messages", user=False, project="demo", user_id=reviewer.id, is_public=False
    )
    second_conversation = Conversation(
        title="More assistant messages",
        user=False,
        project="demo",
        user_id=reviewer.id,
        is_public=False,
    )
    transactional_session.add_all([first_conversation, second_conversation])
    await transactional_session.flush()
    for conversation, roles in (
        (first_conversation, ("user", "user", "assistant")),
        (second_conversation, ("user", "assistant", "assistant")),
    ):
        transactional_session.add_all(
            Message(role=role, content=f"{role} message", conversation=conversation)
            for role in roles
        )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        user_count_response = await client.get(
            "/api/conversations/paginated",
            params={"limit": 20, "offset": 0, "sort_by": "user_message_count", "descending": True},
        )
        assistant_count_response = await client.get(
            "/api/conversations/paginated",
            params={
                "limit": 20,
                "offset": 0,
                "sort_by": "assistant_message_count",
                "descending": True,
            },
        )

    assert user_count_response.status_code == 200
    assert assistant_count_response.status_code == 200
    user_sorted_items = user_count_response.json()["items"]
    assistant_sorted_items = assistant_count_response.json()["items"]
    assert [
        (
            item["id"],
            item["message_count"],
            item["user_message_count"],
            item["assistant_message_count"],
        )
        for item in user_sorted_items
    ] == [(str(first_conversation.id), 3, 2, 1), (str(second_conversation.id), 3, 1, 2)]
    assert [item["id"] for item in assistant_sorted_items] == [
        str(second_conversation.id),
        str(first_conversation.id),
    ]


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
        owner_workbench_tree_response = await owner_client.get(
            f"/api/conversations/{investigation.id}/tree", params={"source": "investigate"}
        )
        owner_review_tree_response = await owner_client.get(
            f"/api/conversations/{investigation.id}/tree", params={"source": "investigations"}
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
        peer_workbench_tree_response = await peer_client.get(
            f"/api/conversations/{investigation.id}/tree", params={"source": "investigate"}
        )
        peer_review_tree_response = await peer_client.get(
            f"/api/conversations/{investigation.id}/tree", params={"source": "investigations"}
        )

    assert owner_workbench_response.status_code == 200
    assert owner_review_response.status_code == 200
    assert default_response.status_code == 403
    assert chats_response.status_code == 403
    assert messages_response.status_code == 403
    assert owner_workbench_tree_response.status_code == 200
    assert owner_review_tree_response.status_code == 200
    assert peer_workbench_response.status_code == 403
    assert peer_review_response.status_code == 200
    assert peer_workbench_tree_response.status_code == 403
    assert peer_review_tree_response.status_code == 200


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
async def test_review_branch_navigation_is_authorized_and_non_mutating(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="branch-owner"
    )
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="branch-reviewer"
    )
    graph = await _create_branch_graph(transactional_session, user=owner, title="Target path chat")
    public_conversation = Conversation(
        title="Public branch", user=False, project="demo", user_id=None, is_public=True
    )
    transactional_session.add(public_conversation)
    await transactional_session.flush()
    public_root = Message(role="user", content="Public question", conversation=public_conversation)
    transactional_session.add(public_root)
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        response = await client.get(
            f"/api/conversations/{graph.conversation.id}",
            params={"source": "chats", "target_message_id": str(graph.alternate_answer.id)},
        )
        root_response = await client.get(
            f"/api/conversations/{graph.conversation.id}",
            params={"source": "chats", "target_message_id": str(graph.alternate_root.id)},
        )
        review_tree_response = await client.get(
            f"/api/conversations/{graph.conversation.id}/tree", params={"source": "chats"}
        )
        author_tree_response = await client.get(f"/api/conversations/{graph.conversation.id}/tree")
        private_update_response = await client.put(
            f"/api/conversations/{graph.conversation.id}/active-branch",
            json={"message_id": str(graph.root.id)},
        )
        public_update_response = await client.put(
            f"/api/conversations/{public_conversation.id}/active-branch",
            json={"message_id": str(public_root.id)},
        )

    assert response.status_code == 200
    assert [message["id"] for message in response.json()["messages"]] == [
        str(graph.root.id),
        str(graph.alternate_answer.id),
        str(graph.follow_up.id),
    ]
    assert root_response.status_code == 200
    assert [message["id"] for message in root_response.json()["messages"]] == [
        str(graph.alternate_root.id),
        str(graph.alternate_root_answer.id),
    ]
    assert review_tree_response.status_code == 200
    assert author_tree_response.status_code == 403
    assert private_update_response.status_code == 403
    assert private_update_response.json()["detail"] == "Access denied"
    assert public_update_response.status_code == 403
    assert public_update_response.json()["detail"] == "Access denied"
    await transactional_session.refresh(graph.root, attribute_names=["active_child_id"])
    await transactional_session.refresh(
        graph.conversation, attribute_names=["active_root_message_id"]
    )
    assert graph.root.active_child_id == graph.current_answer.id
    assert graph.conversation.active_root_message_id == graph.root.id


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
    captured_metadata: dict[str, object] = {}

    async def fake_generate_summary(transcript: str, **metadata: object) -> str:
        captured_transcript["value"] = transcript
        captured_metadata.update(metadata)
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
    assert captured_metadata == {
        "conversation_id": conversation.id,
        "trigger_message_id": assistant_message.id,
    }
    await transactional_session.refresh(conversation)
    assert conversation.summary == "Safe summary"


@pytest.mark.asyncio
async def test_active_branch_projection_failure_rolls_back_mutation(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="branch-rollback"
    )
    graph = await _create_branch_graph(transactional_session, user=user, title="Atomic branch")
    await transactional_session.commit()
    conversation_id = graph.conversation.id
    root_id = graph.root.id
    current_answer_id = graph.current_answer.id
    alternate_answer_id = graph.alternate_answer.id

    async def fail_detail_projection(*_: object, **__: object) -> None:
        raise RuntimeError("detail projection failed")

    monkeypatch.setattr(
        "app.api.routes.conversations._build_internal_conversation_detail", fail_detail_projection
    )

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.put(
            f"/api/conversations/{conversation_id}/active-branch",
            json={"message_id": str(alternate_answer_id)},
        )

    assert response.status_code == 500
    await transactional_session.refresh(
        graph.conversation, attribute_names=["active_root_message_id"]
    )
    await transactional_session.refresh(graph.root, attribute_names=["active_child_id"])
    assert graph.conversation.active_root_message_id == root_id
    assert graph.root.active_child_id == current_answer_id


@pytest.mark.asyncio
async def test_update_conversation_active_branch_persists_canonical_path(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="branch-path"
    )
    graph = await _create_branch_graph(
        transactional_session, user=user, title="Deep branching chat"
    )
    foreign_conversation = Conversation(
        title="Foreign branch", user=False, project="demo", user_id=user.id, is_public=False
    )
    transactional_session.add(foreign_conversation)
    await transactional_session.flush()
    foreign_root = Message(
        role="user", content="Foreign question", conversation=foreign_conversation
    )
    transactional_session.add(foreign_root)
    await transactional_session.commit()

    branch_path = [str(graph.root.id), str(graph.alternate_answer.id), str(graph.follow_up.id)]
    root_path = [str(graph.alternate_root.id), str(graph.alternate_root_answer.id)]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        foreign_response = await client.put(
            f"/api/conversations/{graph.conversation.id}/active-branch",
            json={"message_id": str(foreign_root.id)},
        )
        update_response = await client.put(
            f"/api/conversations/{graph.conversation.id}/active-branch",
            json={"message_id": str(graph.follow_up.id)},
        )
        root_update_response = await client.put(
            f"/api/conversations/{graph.conversation.id}/active-branch",
            json={"message_id": str(graph.alternate_root.id)},
        )
        root_tree_response = await client.get(f"/api/conversations/{graph.conversation.id}/tree")
        detail_response = await client.get(f"/api/conversations/{graph.conversation.id}")

    assert foreign_response.status_code == 400
    assert foreign_response.json()["detail"] == "Message is not in this conversation"
    assert update_response.status_code == 200
    assert [message["id"] for message in update_response.json()["messages"]] == branch_path
    assert root_update_response.status_code == 200
    assert [message["id"] for message in root_update_response.json()["messages"]] == root_path
    assert root_tree_response.status_code == 200
    assert root_tree_response.json()["current_branch_path"] == root_path
    assert detail_response.status_code == 200
    assert [message["id"] for message in detail_response.json()["messages"]] == root_path

    await transactional_session.refresh(
        graph.conversation, attribute_names=["active_root_message_id"]
    )
    await transactional_session.refresh(graph.root, attribute_names=["active_child_id"])
    await transactional_session.refresh(graph.alternate_answer, attribute_names=["active_child_id"])
    assert graph.conversation.active_root_message_id == graph.alternate_root.id
    assert graph.root.active_child_id == graph.alternate_answer.id
    assert graph.alternate_answer.active_child_id == graph.follow_up.id
