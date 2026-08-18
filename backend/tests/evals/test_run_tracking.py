from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from app.core.db import get_session
from app.core.rbac import SystemGroupSlug
from app.core.security import get_password_hash
from app.evals.run_tracking import (
    ActiveEvalRunExistsError,
    create_eval_run,
    get_current_eval_run,
    get_eval_run,
    list_eval_run_events,
    publish_eval_run_event,
    request_eval_run_cancellation,
)
from app.models import EvalRunJob, RbacGroup, User


@pytest.mark.asyncio
async def test_eval_run_state_and_events_survive_outside_the_worker(db_engine: object) -> None:
    del db_engine
    user_id = uuid4()
    run_id = uuid4().hex
    second_run_id = uuid4().hex

    async with get_session() as session:
        group_id = await session.scalar(
            select(RbacGroup.id).where(RbacGroup.slug == SystemGroupSlug.ADMIN)
        )
        assert group_id is not None
        session.add(
            User(
                id=user_id,
                email=f"eval-run-tracking-{user_id}@example.com",
                name="Eval Run Tracking",
                password_hash=get_password_hash(uuid4().hex),
                group_id=group_id,
            )
        )
        await session.commit()

    try:
        snapshot = await create_eval_run(
            run_id=run_id,
            user_id=user_id,
            suite="chatbot",
            initial_payload={"status": "start", "suite": "chatbot", "run_id": run_id},
        )
        assert snapshot.status == "start"

        with pytest.raises(ActiveEvalRunExistsError, match="already running"):
            await create_eval_run(
                run_id=second_run_id,
                user_id=user_id,
                suite="guardrails",
                initial_payload={"status": "start", "suite": "guardrails", "run_id": second_run_id},
            )

        await publish_eval_run_event(run_id, "log", {"message": "case started", "run_id": run_id})
        cancelling = await request_eval_run_cancellation(run_id, user_id)
        assert cancelling is not None
        assert cancelling.status == "cancelling"
        await publish_eval_run_event(run_id, "status", {"status": "cancelled", "run_id": run_id})
        now = datetime.now(UTC)
        async with get_session() as session:
            await session.execute(
                update(EvalRunJob)
                .where(EvalRunJob.run_id == run_id)
                .values(started_at=now - timedelta(hours=7), completed_at=now)
            )
            await session.commit()

        current = await get_current_eval_run(user_id)
        assert current is not None
        assert current.run_id == run_id
        assert current.status == "cancelled"
        assert current.completed_at is not None

        stored = await get_eval_run(run_id, user_id)
        assert stored == current
        events = await list_eval_run_events(run_id, user_id)
        assert events is not None
        assert [event.event for event in events] == ["status", "log", "status", "status"]
        assert [event.sequence for event in events] == sorted(event.sequence for event in events)

        await create_eval_run(
            run_id=second_run_id,
            user_id=user_id,
            suite="guardrails",
            initial_payload={"status": "start", "suite": "guardrails", "run_id": second_run_id},
        )
        async with get_session() as session:
            await session.execute(
                update(EvalRunJob)
                .where(EvalRunJob.run_id == second_run_id)
                .values(heartbeat_at=now - timedelta(minutes=1))
            )
            await session.commit()

        stale = await get_current_eval_run(user_id)
        assert stale is not None
        assert stale.run_id == second_run_id
        assert stale.status == "error"
        assert stale.error_message == "Eval run worker stopped before completion"

        stale_events = await list_eval_run_events(second_run_id, user_id)
        assert stale_events is not None
        await publish_eval_run_event(
            second_run_id, "status", {"status": "complete", "run_id": second_run_id}
        )
        still_stale = await get_eval_run(second_run_id, user_id)
        assert still_stale is not None
        assert still_stale.status == "error"
        assert await list_eval_run_events(second_run_id, user_id) == stale_events
    finally:
        async with get_session() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
