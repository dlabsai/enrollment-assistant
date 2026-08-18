from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.main import app
from app.models import Conversation, Message, OtelSpan, User
from tests.api.auth_helpers import authenticate_client


def _span(
    *,
    trace_id: str,
    span_id: str,
    conversation_id: UUID,
    message_id: UUID,
    started_at: datetime,
    attributes: dict[str, object] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_cost: float | None = None,
    is_ai: bool = False,
) -> OtelSpan:
    return OtelSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        name="test span",
        kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=started_at,
        end_time=started_at,
        attributes=attributes,
        events=None,
        links=None,
        resource=None,
        scope=None,
        span_time=started_at,
        duration_ms=1,
        request_model=None,
        provider_name=None,
        server_address=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        is_ai=is_ai,
        is_embedding=False,
        is_internal=True,
        conversation_id=conversation_id,
        message_id=message_id,
        total_time=None,
    )


@pytest.mark.asyncio
async def test_message_list_returns_latest_trace_diagnostics(
    transactional_session: AsyncSession,
) -> None:
    group = await get_group_for_slug(transactional_session, SystemGroupSlug.DEV)
    reviewer = User(
        email=f"message-list-{uuid4()}@example.com",
        name="Message reviewer",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    transactional_session.add(reviewer)
    await transactional_session.flush()
    conversation = Conversation(
        title="Trace diagnostics", user=False, project="demo", user_id=reviewer.id, is_public=False
    )
    transactional_session.add(conversation)
    await transactional_session.flush()

    now = datetime.now(UTC)
    message_without_trace = Message(
        role="assistant",
        content="No trace",
        conversation=conversation,
        created_at=now - timedelta(seconds=1),
    )
    message = Message(
        role="assistant", content="Latest trace", conversation=conversation, created_at=now
    )
    transactional_session.add_all([message_without_trace, message])
    await transactional_session.flush()

    transactional_session.add_all(
        [
            _span(
                trace_id="older-trace",
                span_id="older-span",
                conversation_id=conversation.id,
                message_id=message.id,
                started_at=now,
                input_tokens=999,
                output_tokens=999,
                total_cost=999,
                is_ai=True,
            ),
            _span(
                trace_id="latest-trace",
                span_id="chatbot-span",
                conversation_id=conversation.id,
                message_id=message.id,
                started_at=now + timedelta(seconds=1),
                attributes={"gen_ai.usage.cache_read.input_tokens": 4},
                input_tokens=11,
                output_tokens=2,
                total_cost=0.12,
                is_ai=True,
            ),
            _span(
                trace_id="latest-trace",
                span_id="guardrail-model-span",
                conversation_id=conversation.id,
                message_id=message.id,
                started_at=now + timedelta(seconds=2),
                attributes={
                    "gen_ai.agent.name": "guardrails",
                    "gen_ai.usage.cache_read.input_tokens": 1,
                },
                input_tokens=5,
                output_tokens=1,
                total_cost=0.03,
                is_ai=True,
            ),
            _span(
                trace_id="latest-trace",
                span_id="grounding-span",
                conversation_id=conversation.id,
                message_id=message.id,
                started_at=now + timedelta(seconds=3),
                attributes={"gen_ai.agent.name": "grounding"},
                input_tokens=100,
                output_tokens=100,
                total_cost=100,
                is_ai=True,
            ),
            _span(
                trace_id="latest-trace",
                span_id="failed-guardrail-span",
                conversation_id=conversation.id,
                message_id=message.id,
                started_at=now + timedelta(seconds=4),
                attributes={"app.guardrails.result.is_valid": False},
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        default_response = await client.get("/api/messages", params={"limit": 1})
        cost_sorted_response = await client.get(
            "/api/messages", params={"sort_by": "response_cost", "descending": True}
        )

    assert default_response.status_code == 200
    assert default_response.json()["total"] == 2
    assert [item["id"] for item in default_response.json()["items"]] == [str(message.id)]
    item = default_response.json()["items"][0]
    assert item["trace_id"] == "latest-trace"
    assert item["span_id"] == "failed-guardrail-span"
    assert item["input_tokens"] == 16
    assert item["cache_read_input_tokens"] == 5
    assert item["uncached_input_tokens"] == 11
    assert item["output_tokens"] == 3
    assert item["response_cost"] == pytest.approx(0.15)
    assert item["guardrail_failure_count"] == 1

    assert cost_sorted_response.status_code == 200
    assert [item["id"] for item in cost_sorted_response.json()["items"]] == [
        str(message.id),
        str(message_without_trace.id),
    ]
