from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.response_costs import price_usage
from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
from app.core.security import get_password_hash
from app.main import app
from app.models import Conversation, Message, OtelSpan, User
from app.rag.constants import EMBEDDING_MODEL
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


def _usage_span(
    *,
    trace_id: str,
    span_id: str,
    started_at: datetime,
    conversation_id: UUID,
    request_model: str,
    provider_name: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    total_cost: float | None,
    duration_ms: float,
    is_embedding: bool,
    is_internal: bool,
    status_code: str = "OK",
    server_address: str | None = None,
) -> OtelSpan:
    return OtelSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        name=f"invoke_agent {span_id}",
        kind="INTERNAL",
        status_code=status_code,
        status_message=None,
        start_time=started_at,
        end_time=started_at + timedelta(milliseconds=duration_ms),
        span_time=started_at,
        duration_ms=duration_ms,
        attributes={
            "app.conversation_id": str(conversation_id),
            "app.is_internal": is_internal,
            "gen_ai.request.model": request_model,
        },
        events=None,
        links=None,
        resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
        scope={"name": "demo-va", "version": "test", "schema_url": None},
        request_model=request_model,
        provider_name=provider_name,
        server_address=server_address,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        is_ai=True,
        is_embedding=is_embedding,
        is_internal=is_internal,
        conversation_id=conversation_id,
        message_id=None,
        total_time=None,
    )


@pytest.mark.asyncio
async def test_usage_summary_requires_usage_permission(transactional_session: AsyncSession) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="usage-summary-user"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/usage/summary")

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_usage_summary_aggregates_otel_spans(transactional_session: AsyncSession) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="usage-summary-admin"
    )

    internal_conversation = Conversation(
        title="Internal usage", user=False, project="demo", user_id=admin.id, is_public=False
    )
    public_conversation = Conversation(
        title="Public usage", user=False, project="demo", user_id=None, is_public=True
    )
    transactional_session.add_all([internal_conversation, public_conversation])
    await transactional_session.flush()

    started_at = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    transactional_session.add_all(
        [
            _usage_span(
                trace_id="usage-internal",
                span_id="chatbot",
                started_at=started_at,
                conversation_id=internal_conversation.id,
                request_model="azure/gpt-5.5",
                provider_name="azure",
                input_tokens=100,
                output_tokens=50,
                total_cost=0.03,
                duration_ms=1200.0,
                is_embedding=False,
                is_internal=True,
            ),
            _usage_span(
                trace_id="usage-public",
                span_id="public-chatbot",
                started_at=started_at + timedelta(hours=1),
                conversation_id=public_conversation.id,
                request_model="openrouter/deepseek-chat",
                provider_name=None,
                input_tokens=20,
                output_tokens=10,
                total_cost=0.005,
                duration_ms=600.0,
                is_embedding=False,
                is_internal=False,
                status_code="ERROR",
            ),
            _usage_span(
                trace_id="usage-embedding",
                span_id="embedding",
                started_at=started_at + timedelta(hours=2),
                conversation_id=internal_conversation.id,
                request_model=EMBEDDING_MODEL,
                provider_name="azure.ai.openai",
                input_tokens=200,
                output_tokens=None,
                total_cost=0.0002,
                duration_ms=100.0,
                is_embedding=True,
                is_internal=True,
            ),
        ]
    )
    await transactional_session.commit()

    params = {
        "start": (started_at - timedelta(days=1)).isoformat(),
        "end": (started_at + timedelta(days=1)).isoformat(),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/usage/summary", params=params)
        public_response = await client.get(
            "/api/usage/summary", params={**params, "platform": "public"}
        )
        azure_response = await client.get(
            "/api/usage/summary", params={**params, "models": "azure"}
        )

    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]
    assert summary["total_requests"] == 2
    assert summary["total_tokens"] == 180
    assert abs(summary["total_cost"] - 0.035) < 0.000001
    assert summary["total_embedding_requests"] == 1
    assert summary["total_embedding_tokens"] == 200
    assert abs(summary["total_embedding_cost"] - 0.0002) < 0.000001
    assert abs(summary["total_embedding_avg_duration"] - 0.1) < 0.000001
    assert summary["total_errors"] == 1
    assert abs(summary["avg_duration"] - 0.9) < 0.000001
    expected_embedding_model = f"azure:{EMBEDDING_MODEL}"
    assert {entry["model"] for entry in body["models"]} == {
        "azure:gpt-5.5",
        "openrouter:deepseek-chat",
        expected_embedding_model,
    }
    assert [trace["model"] for trace in body["latest_traces"]] == [
        expected_embedding_model,
        "openrouter:deepseek-chat",
        "azure:gpt-5.5",
    ]
    assert [trace["is_public"] for trace in body["latest_traces"]] == [False, True, False]

    assert public_response.status_code == 200
    assert public_response.json()["summary"]["total_requests"] == 1
    assert public_response.json()["summary"]["total_errors"] == 1
    assert [trace["is_public"] for trace in public_response.json()["latest_traces"]] == [True]

    assert azure_response.status_code == 200
    assert azure_response.json()["summary"]["total_requests"] == 1
    assert azure_response.json()["summary"]["total_embedding_requests"] == 1


@pytest.mark.asyncio
async def test_usage_summary_estimates_missing_embedding_cost_only(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="usage-embedding-cost-admin",
    )
    conversation = Conversation(
        title="Embedding usage", user=False, project="demo", user_id=admin.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    started_at = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    transactional_session.add_all(
        [
            _usage_span(
                trace_id="usage-llm-null-cost",
                span_id="chatbot",
                started_at=started_at,
                conversation_id=conversation.id,
                request_model="azure/gpt-5.5",
                provider_name="azure",
                input_tokens=100,
                output_tokens=50,
                total_cost=None,
                duration_ms=1000.0,
                is_embedding=False,
                is_internal=True,
            ),
            _usage_span(
                trace_id="usage-embedding-estimated-cost",
                span_id="embedding-estimated",
                started_at=started_at + timedelta(minutes=1),
                conversation_id=conversation.id,
                request_model=EMBEDDING_MODEL,
                provider_name="azure.ai.openai",
                input_tokens=1000,
                output_tokens=None,
                total_cost=None,
                duration_ms=100.0,
                is_embedding=True,
                is_internal=True,
            ),
            _usage_span(
                trace_id="usage-embedding-stored-cost",
                span_id="embedding-stored",
                started_at=started_at + timedelta(minutes=2),
                conversation_id=conversation.id,
                request_model=EMBEDDING_MODEL,
                provider_name="azure.ai.openai",
                input_tokens=200,
                output_tokens=None,
                total_cost=0.0002,
                duration_ms=100.0,
                is_embedding=True,
                is_internal=True,
            ),
        ]
    )
    await transactional_session.commit()

    params = {
        "start": (started_at - timedelta(hours=1)).isoformat(),
        "end": (started_at + timedelta(hours=1)).isoformat(),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/usage/summary", params=params)

    assert response.status_code == 200
    body = response.json()
    expected_estimated_embedding_cost = price_usage(
        model=EMBEDDING_MODEL, provider_id="azure", genai_request_timestamp=None, input_tokens=1000
    )
    assert expected_estimated_embedding_cost is not None
    expected_embedding_cost = expected_estimated_embedding_cost + 0.0002

    assert body["summary"]["total_requests"] == 1
    assert body["summary"]["total_cost"] == 0
    assert body["summary"]["total_embedding_requests"] == 2
    assert body["summary"]["total_embedding_tokens"] == 1200
    assert abs(body["summary"]["total_embedding_cost"] - expected_embedding_cost) < 0.000001

    expected_embedding_model = f"azure:{EMBEDDING_MODEL}"
    embedding_model = next(
        entry for entry in body["models"] if entry["model"] == expected_embedding_model
    )
    assert embedding_model["requests"] == 2
    assert embedding_model["tokens"] == 1200
    assert abs(embedding_model["cost"] - expected_embedding_cost) < 0.000001

    estimated_trace = next(
        trace
        for trace in body["latest_traces"]
        if trace["model"] == expected_embedding_model and trace["prompt_tokens"] == 1000
    )
    assert abs(estimated_trace["cost"] - expected_estimated_embedding_cost) < 0.000001


@pytest.mark.asyncio
async def test_usage_trace_routes_read_persisted_otel_spans(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="trace-owner"
    )
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="trace-admin"
    )
    other_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="trace-other"
    )

    conversation = Conversation(
        title="Trace test", user=False, project="demo", user_id=owner.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    user_message = Message(role="user", content="Need help", conversation=conversation)
    transactional_session.add(user_message)
    await transactional_session.flush()

    assistant_message = Message(
        role="assistant",
        content="Here is some help",
        conversation=conversation,
        parent_id=user_message.id,
    )
    transactional_session.add(assistant_message)
    await transactional_session.flush()
    user_message.active_child = assistant_message

    trace_id = str(uuid4())
    started_at = datetime.now(tz=UTC) - timedelta(seconds=5)
    transactional_session.add_all(
        [
            OtelSpan(
                trace_id=trace_id,
                span_id="turn",
                parent_span_id=None,
                name="handle_conversation_turn",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=started_at,
                end_time=started_at + timedelta(seconds=2),
                span_time=started_at,
                duration_ms=2000.0,
                attributes={
                    "app.conversation_id": str(conversation.id),
                    "app.message_id": str(assistant_message.id),
                    "app.is_internal": True,
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
                is_internal=True,
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                total_time=2.0,
            ),
            OtelSpan(
                trace_id=trace_id,
                span_id="tool-1",
                parent_span_id="chatbot",
                name="execute_tool find_document_chunks",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=started_at + timedelta(milliseconds=700),
                end_time=started_at + timedelta(milliseconds=800),
                span_time=started_at + timedelta(milliseconds=700),
                duration_ms=100.0,
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "find_document_chunks",
                    "gen_ai.tool.type": "datastore",
                    "gen_ai.tool.call.id": "call-1",
                    "gen_ai.tool.call.arguments": {"content_search_query": "help"},
                    "gen_ai.tool.call.result": [
                        {"content": "Help content", "sources": {"website_page": [[1, [1], "Help"]]}}
                    ],
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
                message_id=None,
                total_time=None,
            ),
            OtelSpan(
                trace_id=trace_id,
                span_id="chatbot",
                parent_span_id="turn",
                name="invoke_agent chatbot",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=started_at + timedelta(milliseconds=600),
                end_time=started_at + timedelta(milliseconds=1500),
                span_time=started_at + timedelta(milliseconds=600),
                duration_ms=900.0,
                attributes={
                    "app.conversation_id": str(conversation.id),
                    "app.is_internal": True,
                    "gen_ai.agent.name": "chatbot",
                    "gen_ai.request.model": "azure/gpt-4o",
                    "gen_ai.usage.input_tokens": 10,
                    "gen_ai.usage.output_tokens": 20,
                    "gen_ai.output.messages": [
                        {
                            "role": "assistant",
                            "content": "Use Demo University sources for financial aid.",
                        }
                    ],
                },
                events=None,
                links=None,
                resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                request_model="azure/gpt-4o",
                provider_name="azure",
                server_address=None,
                input_tokens=10,
                output_tokens=20,
                total_cost=None,
                is_ai=True,
                is_embedding=False,
                is_internal=True,
                conversation_id=conversation.id,
                message_id=None,
                total_time=None,
            ),
            OtelSpan(
                trace_id=trace_id,
                span_id="guardrails",
                parent_span_id="turn",
                name="invoke_agent guardrails",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=started_at + timedelta(milliseconds=1600),
                end_time=started_at + timedelta(milliseconds=1800),
                span_time=started_at + timedelta(milliseconds=1600),
                duration_ms=200.0,
                attributes={
                    "app.conversation_id": str(conversation.id),
                    "app.is_internal": True,
                    "gen_ai.agent.name": "guardrails",
                    "gen_ai.request.model": "azure/gpt-4o-mini",
                },
                events=None,
                links=None,
                resource={"attributes": {"service.name": "demo-va"}, "schema_url": None},
                scope={"name": "pydantic-ai", "version": "test", "schema_url": None},
                request_model="azure/gpt-4o-mini",
                provider_name="azure",
                server_address=None,
                input_tokens=None,
                output_tokens=None,
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
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as owner_client:
        authenticate_client(owner_client, owner.id)
        trace_by_message_response = await owner_client.get(
            f"/api/usage/trace-by-message/{assistant_message.id}", params={"source": "chat_trace"}
        )
        trace_index_response = await owner_client.get(
            "/api/usage/trace-index",
            params={"limit": 20, "offset": 0, "sort_by": "latest_start", "descending": "true"},
        )

    assert trace_by_message_response.status_code == 200
    trace_detail = trace_by_message_response.json()
    assert trace_detail["trace_id"] == trace_id
    assert trace_detail["conversation_id"] == str(conversation.id)
    span_names = {span["name"] for span in trace_detail["spans"]}
    assert {"handle_conversation_turn", "execute_tool find_document_chunks"}.issubset(span_names)
    chatbot_span = next(
        span
        for span in trace_detail["spans"]
        if span["attributes"] is not None
        and span["attributes"].get("gen_ai.agent.name") == "chatbot"
    )
    assert chatbot_span["attributes"]["gen_ai.request.model"] == "azure/gpt-4o"
    tool_span = next(
        span
        for span in trace_detail["spans"]
        if span["attributes"] is not None
        and span["attributes"].get("gen_ai.tool.name") == "find_document_chunks"
    )
    assert tool_span["attributes"]["gen_ai.tool.call.result"] == [
        {"content": "Help content", "sources": {"website_page": [[1, [1], "Help"]]}}
    ]
    tool_overview = next(item for item in trace_detail["overview"] if item["type"] == "tool")
    assert tool_overview["data"]["result"] == [
        {"content": "Help content", "sources": {"website_page": [[1, [1], "Help"]]}}
    ]
    assert tool_overview["data"]["arguments"] == {"content_search_query": "help"}
    chatbot_overview = next(
        item
        for item in trace_detail["overview"]
        if item["type"] == "agent" and item["title"] == "Agent: chatbot"
    )
    assert (
        chatbot_overview["data"]["output_text"] == "Use Demo University sources for financial aid."
    )
    assert (
        len([item for item in trace_detail["overview"] if item["type"] == "conversation_turn"]) == 1
    )
    conversation_turn_overview = next(
        item for item in trace_detail["overview"] if item["type"] == "conversation_turn"
    )
    assert conversation_turn_overview["data"]["message_id"] == str(assistant_message.id)

    assert trace_index_response.status_code == 403

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as admin_client:
        authenticate_client(admin_client, admin.id)
        trace_detail_response = await admin_client.get(f"/api/usage/trace/{trace_id}")

    assert trace_detail_response.status_code == 200
    assert trace_detail_response.json()["trace_id"] == trace_id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as other_client:
        authenticate_client(other_client, other_user.id)
        forbidden_response = await other_client.get(
            f"/api/usage/trace-by-message/{assistant_message.id}", params={"source": "chat_trace"}
        )

    assert forbidden_response.status_code == 403


@pytest.mark.asyncio
async def test_chats_trace_allows_non_admin_reviewers_with_explicit_permissions(
    transactional_session: AsyncSession,
) -> None:
    owner = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="trace-owner"
    )
    reviewer = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="trace-reviewer"
    )
    await replace_user_permission_overrides(
        transactional_session,
        reviewer,
        {
            PermissionKey.ACCESS_CHATS: True,
            PermissionKey.CHATS_VIEW_USERS: True,
            PermissionKey.CHATS_VIEW_TRACE: True,
        },
    )

    conversation = Conversation(
        title="Trace review test", user=False, project="demo", user_id=owner.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    user_message = Message(role="user", content="Need help", conversation=conversation)
    transactional_session.add(user_message)
    await transactional_session.flush()

    assistant_message = Message(
        role="assistant",
        content="Here is some help",
        conversation=conversation,
        parent_id=user_message.id,
    )
    transactional_session.add(assistant_message)
    await transactional_session.flush()
    user_message.active_child = assistant_message

    trace_id = str(uuid4())
    started_at = datetime.now(tz=UTC) - timedelta(seconds=3)
    transactional_session.add_all(
        [
            OtelSpan(
                trace_id=trace_id,
                span_id="turn",
                parent_span_id=None,
                name="handle_conversation_turn",
                kind="INTERNAL",
                status_code="OK",
                status_message=None,
                start_time=started_at,
                end_time=started_at + timedelta(seconds=1),
                span_time=started_at,
                duration_ms=1000.0,
                attributes={
                    "app.conversation_id": str(conversation.id),
                    "app.message_id": str(assistant_message.id),
                    "app.is_internal": True,
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
                is_internal=True,
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                total_time=1.0,
            )
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as reviewer_client:
        authenticate_client(reviewer_client, reviewer.id)
        response = await reviewer_client.get(
            f"/api/usage/trace-by-message/{assistant_message.id}", params={"source": "chats_trace"}
        )

    assert response.status_code == 200
    assert response.json()["trace_id"] == trace_id
