import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.exceptions import ContentFilterError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.routes.conversations import delete_internal_conversation
from app.compliance import worker
from app.compliance.screener import SCREENING_VERSION, ValidatedConcern
from app.compliance.sources import load_transcript
from app.core.config import settings
from app.core.rbac import SystemGroupSlug
from app.main import app
from app.models import (
    ComplianceInstructionsVersion,
    ComplianceItem,
    ComplianceScreening,
    Conversation,
    Message,
    User,
)
from tests.api.auth_helpers import authenticate_client
from tests.api.compliance_helpers import END, RULE, START, make_chat, make_user, period, save_rule


@pytest.mark.asyncio
async def test_executor_retries_failed_items_with_saved_instructions(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = transactional_session
    staff = await make_user(session, SystemGroupSlug.USER)
    reviewer = await make_user(session, SystemGroupSlug.DEV)
    chat, first = await make_chat(session, staff)
    question = Message(
        conversation_id=chat.id,
        parent_id=first.id,
        role="user",
        content="Is that a guarantee?",
        created_at=START + timedelta(hours=2),
    )
    session.add(question)
    await session.flush()
    last = Message(
        conversation_id=chat.id,
        parent_id=question.id,
        role="assistant",
        content="No, admission is not guaranteed.",
        created_at=START + timedelta(hours=3),
    )
    session.add(last)
    await session.commit()
    targets = {first.id, last.id}
    factory = async_sessionmaker(
        bind=await session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    await session.commit()

    calls = 0

    async def failing_screening(**kwargs: Any) -> list[ValidatedConcern]:
        nonlocal calls
        calls += 1
        assert set(kwargs["target_message_ids"]) == targets
        raise RuntimeError("Screening service unavailable")

    monkeypatch.setattr(worker, "screen_conversation", failing_screening)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        version = await save_rule(client)
        screening_id = str(uuid4())
        started = await client.post(
            "/api/compliance/screenings",
            json={**period(), "id": screening_id, "instructions_version_id": version["id"]},
        )
        assert started.status_code == 200, started.text
        assert started.json()["screened_conversations"] == 0
        claim = await worker.claim_next(session)
        assert claim is not None
        await session.commit()
        await worker.execute_claim(factory, claim)
        rows = list(
            (
                await session.scalars(
                    select(ComplianceItem)
                    .where(ComplianceItem.screening_id == claim.screening_id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        assert len(rows) == 2
        assert all(row.status == "error" and row.error_code == "provider_error" for row in rows)
        assert calls == 1
        failed = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert failed["screened_conversations"] == 0
        assert failed["error_conversations"] == 1
        assert failed["failures"] == [
            {
                "chat_id": str(chat.id),
                "chat": chat.title,
                "assistant_messages": 2,
                "reason": "The screening service could not finish this Chat.",
                "retryable": True,
            }
        ]

        # Retrying is explicitly limited to unsuccessful items, with the same instructions.
        await save_rule(client, "Different instructions for future screenings.")

        async def successful_screening(**kwargs: Any) -> list[ValidatedConcern]:
            nonlocal calls
            calls += 1
            assert kwargs["instructions"] == RULE
            assert set(kwargs["target_message_ids"]) == targets
            assert [node.id for node in kwargs["transcript"]] == [
                first.parent_id,
                first.id,
                question.id,
                last.id,
            ]
            return []

        monkeypatch.setattr(worker, "screen_conversation", successful_screening)
        retry = await client.post(f"/api/compliance/screenings/{screening_id}/retry", json={})
        assert retry.json() == {"queued": 2, "conversations": 1}
        claim = await worker.claim_next(session)
        assert claim is not None
        await session.commit()
        await worker.execute_claim(factory, claim)
        completed = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert completed["screened"] == 2
        assert completed["screened_conversations"] == 1
        assert completed["error_conversations"] == 0
        assert calls == 2
        assert (
            await client.post(f"/api/compliance/screenings/{screening_id}/retry", json={})
        ).json()["queued"] == 0

        await session.execute(
            update(ComplianceItem)
            .where(ComplianceItem.screening_id == screening_id)
            .values(status="error", error_code="too_long")
        )
        await session.commit()
        deterministic_failure = (
            await client.get(f"/api/compliance/screenings/{screening_id}")
        ).json()
        assert deterministic_failure["failures"][0]["retryable"] is False
        assert "too long" in deterministic_failure["failures"][0]["reason"]
        assert (
            await client.post(f"/api/compliance/screenings/{screening_id}/retry", json={})
        ).json() == {"queued": 0, "conversations": 0}

        await session.execute(
            update(ComplianceItem)
            .where(ComplianceItem.screening_id == screening_id)
            .values(error_code="provider_error")
        )
        await session.execute(
            update(ComplianceScreening)
            .where(ComplianceScreening.id == screening_id)
            .values(screening_version="1")
        )
        await session.commit()
        unsupported = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert unsupported["failures"][0]["retryable"] is False
        assert "configuration has changed" in unsupported["failures"][0]["reason"]
        assert (
            await client.post(f"/api/compliance/screenings/{screening_id}/retry", json={})
        ).status_code == 409

        await session.execute(
            update(ComplianceItem)
            .where(ComplianceItem.screening_id == screening_id)
            .values(status="queued", error_code=None, attempts=0)
        )
        await session.execute(
            update(ComplianceScreening)
            .where(ComplianceScreening.id == screening_id)
            .values(screening_version=SCREENING_VERSION)
        )
        await session.commit()

        async def jailbreak_blocked_screening(**kwargs: Any) -> list[ValidatedConcern]:
            raise ContentFilterError(
                "Content filter triggered.",
                body=json.dumps(
                    [
                        {
                            "kind": "response",
                            "provider_name": "azure",
                            "finish_reason": "content_filter",
                            "provider_details": {
                                "finish_reason": "content_filter",
                                "content_filter_result": {
                                    "jailbreak": {"detected": True, "filtered": True}
                                },
                            },
                        }
                    ]
                ),
            )

        monkeypatch.setattr(worker, "screen_conversation", jailbreak_blocked_screening)
        claim = await worker.claim_next(session)
        assert claim is not None
        await session.commit()
        await worker.execute_claim(factory, claim)
        blocked = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert blocked["failures"] == [
            {
                "chat_id": str(chat.id),
                "chat": chat.title,
                "assistant_messages": 2,
                "reason": (
                    "Screening stopped because the service thought text in this Chat might "
                    "be an attempt to change the screening instructions. Trying the same "
                    "Chat again is unlikely to help."
                ),
                "retryable": False,
            }
        ]
        assert (
            await client.post(f"/api/compliance/screenings/{screening_id}/retry", json={})
        ).json() == {"queued": 0, "conversations": 0}


@pytest.mark.asyncio
async def test_source_deletion_waits_for_result_persistence_without_resurrecting_data(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    screening_id = instruction_id = chat_id = item_id = staff_id = reviewer_id = None
    claim: worker.Claim | None = None
    work: worker.Work | None = None
    conversation_locked = asyncio.Event()
    continue_persistence = asyncio.Event()
    deletion_pid_ready = asyncio.Event()
    deletion_pid: int | None = None
    completion_task: asyncio.Task[bool] | None = None
    deletion_task: asyncio.Task[None] | None = None

    try:
        async with factory() as setup:
            staff = await make_user(setup, SystemGroupSlug.USER)
            reviewer = await make_user(setup, SystemGroupSlug.DEV)
            chat, target = await make_chat(setup, staff)
            await setup.execute(text("SELECT pg_advisory_xact_lock(74218)"))
            instruction_number = (
                await setup.scalar(select(func.max(ComplianceInstructionsVersion.number))) or 0
            ) + 1
            instructions = ComplianceInstructionsVersion(
                number=instruction_number, content=RULE, created_by_id=reviewer.id
            )
            setup.add(instructions)
            await setup.flush()
            screening_row = ComplianceScreening(
                created_by_id=reviewer.id,
                instructions_version_id=instructions.id,
                start_at=START,
                end_at=END,
                model_name="azure/gpt-5.5",
                screening_version=SCREENING_VERSION,
                model_settings={
                    "max_tokens": 8192,
                    "max_input_characters": 200000,
                    "agent_prompt": "Pinned screening agent prompt.",
                },
                created_at=END,
            )
            setup.add(screening_row)
            await setup.flush()
            token = uuid4()
            item_row = ComplianceItem(
                screening_id=screening_row.id,
                message_id=target.id,
                conversation_id=chat.id,
                owner_id=staff.id,
                requested_by_id=reviewer.id,
                status="running",
                attempts=1,
                lease_token=token,
                leased_until=END + timedelta(days=1),
            )
            setup.add(item_row)
            await setup.flush()
            claim = worker.Claim(screening_row.id, chat.id, token)
            work = await worker.prepare_work(setup, claim)
            assert work is not None
            item_row.input_hash = work.input_hash
            screening_id = screening_row.id
            instruction_id = instructions.id
            chat_id = chat.id
            item_id = item_row.id
            staff_id = staff.id
            reviewer_id = reviewer.id
            await setup.commit()

        async def paused_load_transcript(*args: Any, **kwargs: Any) -> Any:
            conversation_locked.set()
            await continue_persistence.wait()
            return await load_transcript(*args, **kwargs)

        monkeypatch.setattr(worker, "load_transcript", paused_load_transcript)

        async def complete_result() -> bool:
            assert claim is not None
            assert work is not None
            async with factory() as completion_session:
                result = await worker.finish_result(completion_session, claim, work, [])
                await completion_session.commit()
                return result

        async def delete_source() -> None:
            nonlocal deletion_pid
            assert chat_id is not None
            assert staff_id is not None
            async with factory() as deletion_session:
                deletion_pid = await deletion_session.scalar(text("SELECT pg_backend_pid()"))
                deletion_pid_ready.set()
                staff = await deletion_session.get(User, staff_id)
                assert staff is not None
                await delete_internal_conversation(chat_id, deletion_session, staff)

        completion_task = asyncio.create_task(complete_result())
        await conversation_locked.wait()
        deletion_task = asyncio.create_task(delete_source())
        await deletion_pid_ready.wait()
        assert deletion_pid is not None

        blocked = False
        async with factory() as monitor:
            for _ in range(200):
                blocked = bool(
                    await monitor.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": deletion_pid},
                    )
                )
                if blocked:
                    break
                await asyncio.sleep(0.01)
        assert blocked

        continue_persistence.set()
        completed, _ = await asyncio.gather(completion_task, deletion_task)
        assert completed

        async with factory() as verify:
            assert await verify.get(Conversation, chat_id) is None
            deleted_item = await verify.get(ComplianceItem, item_id)
            assert deleted_item is not None
            assert deleted_item.status == "deleted"
            assert deleted_item.message_id is None
    finally:
        continue_persistence.set()
        if completion_task is not None:
            if not completion_task.done():
                completion_task.cancel()
            await asyncio.gather(completion_task, return_exceptions=True)
        if deletion_task is not None:
            if not deletion_task.done():
                deletion_task.cancel()
            await asyncio.gather(deletion_task, return_exceptions=True)
        async with factory() as cleanup:
            if chat_id is not None:
                await cleanup.execute(delete(Conversation).where(Conversation.id == chat_id))
            if screening_id is not None:
                await cleanup.execute(
                    delete(ComplianceScreening).where(ComplianceScreening.id == screening_id)
                )
            if instruction_id is not None:
                await cleanup.execute(
                    delete(ComplianceInstructionsVersion).where(
                        ComplianceInstructionsVersion.id == instruction_id
                    )
                )
            user_ids = [id_ for id_ in (staff_id, reviewer_id) if id_ is not None]
            if user_ids:
                await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_bulk_limit_rejects_instead_of_silently_sampling(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = transactional_session
    reviewer = await make_user(session, SystemGroupSlug.DEV)
    staff = await make_user(session, SystemGroupSlug.USER)
    await make_chat(session, staff)
    await make_chat(session, staff)
    await session.commit()
    monkeypatch.setattr(settings, "COMPLIANCE_MAX_MESSAGES", 1)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        version = await save_rule(client)
        preview = await client.post("/api/compliance/screenings/preview", json=period())
        assert preview.json()["messages"] == 2
        assert preview.json()["max_messages"] == 1
        result = await client.post(
            "/api/compliance/screenings",
            json={**period(), "id": str(uuid4()), "instructions_version_id": version["id"]},
        )
        assert result.status_code == 400
        assert "shorter period" in result.text
        assert (await client.get("/api/compliance/screenings")).json()["total"] == 0
