import json
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import TEMPLATES_DIR
from app.chat.engine import MessageMetadataOut, MessageOut, ModelSettings
from app.chat.template_utils import clear_deployed_templates_cache
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import AssistantMessageMetadata, Conversation, Message, OtelSpan, User
from app.prompt_sets import read_disk_templates
from tests.api.auth_helpers import authenticate_client

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def _create_admin(session: AsyncSession) -> User:
    group = await get_group_for_slug(session, SystemGroupSlug.ADMIN)
    user = User(
        email=f"smoke-{uuid4()}@example.com",
        name="Smoke Admin",
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
async def test_internal_app_backend_contract_smoke(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_deployed_templates_cache()
    admin = await _create_admin(transactional_session)
    disk_templates = read_disk_templates(TEMPLATES_DIR)

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
            content="Smoke response",
            conversation=conversation,
            parent_id=user_message.id,
        )
        session.add(assistant_message)
        await session.flush()
        user_message.active_child = assistant_message
        metadata_row = AssistantMessageMetadata(
            message_id=assistant_message.id,
            system_prompt_rendered="system",
            conversation_turn=1,
            total_time=1.4,
            chatbot_times=[1.0],
        )
        session.add(metadata_row)
        await session.flush()

        if event_emitter is not None:
            await event_emitter(
                "agent_stage", {"stage": "chatbot", "status": "start", "iteration": 1}
            )
            await event_emitter(
                "agent_stage",
                {"stage": "chatbot", "status": "end", "duration_ms": 50, "iteration": 1},
            )

        trace_id = str(assistant_message.id)
        turn_start = assistant_message.created_at - timedelta(seconds=2)
        chatbot_start = assistant_message.created_at - timedelta(seconds=1)

        session.add_all(
            [
                OtelSpan(
                    trace_id=trace_id,
                    span_id="turn",
                    parent_span_id=None,
                    name="handle_conversation_turn",
                    kind="INTERNAL",
                    status_code="OK",
                    status_message=None,
                    start_time=turn_start,
                    end_time=assistant_message.created_at,
                    span_time=turn_start,
                    duration_ms=2000.0,
                    attributes={
                        "app.conversation_id": str(conversation.id),
                        "app.message_id": str(assistant_message.id),
                        "app.is_internal": True,
                        "app.user_id": str(user_id) if user_id is not None else None,
                        "app.total_time": 1.4,
                    },
                    events=None,
                    links=None,
                    resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                    scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                    request_model=None,
                    provider_name=None,
                    server_address=None,
                    input_tokens=None,
                    output_tokens=None,
                    total_cost=None,
                    is_ai=False,
                    is_embedding=False,
                    is_internal=True,
                    conversation_id=conversation.id,
                    message_id=assistant_message.id,
                    total_time=1.4,
                ),
                OtelSpan(
                    trace_id=trace_id,
                    span_id="chatbot",
                    parent_span_id="turn",
                    name="invoke_agent chatbot",
                    kind="INTERNAL",
                    status_code="OK",
                    status_message=None,
                    start_time=chatbot_start,
                    end_time=assistant_message.created_at - timedelta(milliseconds=200),
                    span_time=chatbot_start,
                    duration_ms=800.0,
                    attributes={
                        "app.conversation_id": str(conversation.id),
                        "app.is_internal": True,
                        "gen_ai.agent.name": "chatbot",
                        "gen_ai.request.model": "azure/gpt-4o",
                        "gen_ai.usage.input_tokens": 11,
                        "gen_ai.usage.output_tokens": 22,
                    },
                    events=None,
                    links=None,
                    resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                    scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                    request_model="azure/gpt-4o",
                    provider_name="azure",
                    server_address=None,
                    input_tokens=11,
                    output_tokens=22,
                    total_cost=None,
                    is_ai=True,
                    is_embedding=False,
                    is_internal=True,
                    conversation_id=conversation.id,
                    message_id=None,
                    total_time=None,
                ),
            ]
        )
        await session.flush()

        return user_message.id, MessageOut(
            id=assistant_message.id,
            role="assistant",
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            parent_id=assistant_message.parent_id,
            conversation_id=conversation.id,
            metadata=MessageMetadataOut(
                id=metadata_row.id,
                message_id=assistant_message.id,
                system_prompt_rendered="system",
                conversation_turn=1,
                chatbot_model_settings=ModelSettings(model="azure/gpt-4o"),
                created_at=assistant_message.created_at,
                updated_at=assistant_message.created_at,
                chatbot_time=1.0,
                total_time=1.4,
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
    monkeypatch.setattr("app.api.routes.models.settings.MODELS", "azure/gpt-4o")
    monkeypatch.setattr("app.api.routes.models._openrouter_models", [])

    prompt_payload = {
        "name": "Smoke assistant version",
        "description": "Integration smoke",
        "is_internal": True,
        "scope": "assistant",
        "prompts": [
            {
                "filename": "chatbot_agent_internal.j2",
                "content": disk_templates["chatbot_agent_internal.j2"],
            },
            {
                "filename": "guardrails_agent_internal.j2",
                "content": disk_templates["guardrails_agent_internal.j2"],
            },
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        models_response = await client.get("/api/models")
        disk_templates_response = await client.get("/api/prompts/disk-templates")
        create_prompt_response = await client.post("/api/prompts/versions", json=prompt_payload)
        deploy_prompt_response = await client.post(
            f"/api/prompts/versions/{create_prompt_response.json()['id']}/deploy", json={}
        )
        stream_response = await client.post(
            "/api/messages/internal/stream", json={"user_prompt": "Hello smoke test"}
        )

    assert models_response.status_code == 200
    assert models_response.json() == ["azure/gpt-4o"]

    assert disk_templates_response.status_code == 200
    assert any(
        item["filename"] == "chatbot_agent_internal.j2" for item in disk_templates_response.json()
    )

    assert create_prompt_response.status_code == 201
    assert deploy_prompt_response.status_code == 200

    assert stream_response.status_code == 200
    events = _parse_sse_events(stream_response.text)
    conversation_event = next(payload for name, payload in events if name == "conversation")
    agent_stage_event = next(payload for name, payload in events if name == "agent_stage")
    assistant_event = next(payload for name, payload in events if name == "assistant_message")
    conversation_id = conversation_event["conversation_id"]
    assistant_message_id = assistant_event["assistant_message_id"]
    assert agent_stage_event["conversation_id"] == conversation_id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        conversation_detail_response = await client.get(f"/api/conversations/{conversation_id}")
        feedback_response = await client.post(
            f"/api/conversations/messages/{assistant_message_id}/feedback",
            json={"rating": "thumbs_up", "text": "Looks good"},
        )
        trace_response = await client.get(f"/api/usage/trace-by-message/{assistant_message_id}")

    assert conversation_detail_response.status_code == 200
    assert [message["role"] for message in conversation_detail_response.json()["messages"]] == [
        "user",
        "assistant",
    ]

    assert feedback_response.status_code == 200
    assert feedback_response.json()["is_current_user"] is True

    assert trace_response.status_code == 200
    trace_body = trace_response.json()
    assert trace_body["conversation_id"] == conversation_id
    assert any(
        span["attributes"].get("gen_ai.agent.name") == "chatbot"
        for span in trace_body["spans"]
        if span["attributes"] is not None
    )
