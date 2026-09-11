import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.alembic.versions.c6c2acd70ba3_add_guardrail_retry_count import (
    backfill_guardrail_retry_counts,
)
from app.models import AssistantMessageMetadata, Conversation, Message


@pytest.mark.asyncio
async def test_guardrail_retry_backfill_uses_timings_then_failure_records(
    transactional_session: AsyncSession,
) -> None:
    conversation = Conversation(title="Retry backfill", user=False, project="demo", is_public=False)
    cases = [
        (False, None, None, 0),
        (False, [0.1], None, 0),
        (False, [0.1, 0.2, 0.3], None, 2),
        (False, None, [{"message": "rejected"}], 1),
        (
            True,
            None,
            [
                {"message": "first rejection"},
                {"message": "second rejection"},
                {"message": "final rejection"},
            ],
            2,
        ),
    ]
    metadata_rows: list[AssistantMessageMetadata] = []
    for index, (blocked, guardrail_times, guardrails, _expected) in enumerate(cases):
        message = Message(
            role="assistant",
            content=f"Response {index}",
            conversation=conversation,
            guardrails_blocked=blocked,
        )
        metadata_rows.append(
            AssistantMessageMetadata(
                message=message,
                system_prompt_rendered="System prompt",
                conversation_turn=index + 1,
                chatbot_model_settings={"model": "test"},
                guardrail_times=guardrail_times,
                guardrails=guardrails,
                guardrail_retry_count=None,
            )
        )
    unknown_message = Message(
        role="assistant", content="Response without metadata", conversation=conversation
    )
    transactional_session.add_all([conversation, unknown_message, *metadata_rows])
    await transactional_session.flush()
    metadata_ids = [row.id for row in metadata_rows]
    unknown_message_id = unknown_message.id

    def run_backfill(sync_session: Session) -> None:
        backfill_guardrail_retry_counts(sync_session.connection())

    await transactional_session.run_sync(run_backfill)
    transactional_session.expire_all()
    persisted = list(
        (
            await transactional_session.scalars(
                select(AssistantMessageMetadata)
                .where(AssistantMessageMetadata.id.in_(metadata_ids))
                .order_by(AssistantMessageMetadata.conversation_turn)
            )
        ).all()
    )

    assert [row.guardrail_retry_count for row in persisted] == [case[3] for case in cases]
    assert (
        await transactional_session.scalar(
            select(AssistantMessageMetadata).where(
                AssistantMessageMetadata.message_id == unknown_message_id
            )
        )
        is None
    )
