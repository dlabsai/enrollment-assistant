from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import compliance as compliance_routes
from app.compliance.schemas import FindingCategory
from app.compliance.screener import Concern, ScreeningResult, validate_result
from app.compliance.sources import ScreeningUnavailableError
from app.compliance.worker import claim_next, finish_error, finish_result, prepare_work
from app.core.rbac import PermissionKey, SystemGroupSlug, replace_user_permission_overrides
from app.main import app
from app.models import (
    ComplianceDecision,
    ComplianceFinding,
    ComplianceItem,
    ComplianceScreening,
    Message,
)
from tests.api.auth_helpers import authenticate_client
from tests.api.compliance_helpers import (
    END,
    MESSAGE,
    RULE,
    START,
    make_chat,
    make_user,
    period,
    save_rule,
    start_screening,
)


@pytest.mark.asyncio
async def test_conversation_screening_uses_complete_snapshot_and_selected_targets(
    transactional_session: AsyncSession,
) -> None:
    session = transactional_session
    staff = await make_user(session, SystemGroupSlug.USER)
    owner = await make_user(session, SystemGroupSlug.DEV)
    chat, message = await make_chat(session, staff)
    alternative = Message(
        conversation_id=chat.id,
        parent_id=message.parent_id,
        role="assistant",
        content="Admission is not guaranteed.",
        created_at=START + timedelta(hours=2),
    )
    future = Message(
        conversation_id=chat.id,
        parent_id=message.id,
        role="assistant",
        content="A later message.",
        created_at=END + timedelta(hours=1),
    )
    session.add_all([alternative, future])
    await make_chat(session, staff, public=True)
    await make_chat(session, staff, draft=True)
    await make_chat(session, owner)
    await make_chat(session, staff, kind="investigation")
    await session.commit()
    targets = {message.id, alternative.id}
    context = [
        (message.parent_id, None),
        (message.id, message.parent_id),
        (alternative.id, alternative.parent_id),
        (future.id, message.id),
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        version = await save_rule(client)
        preview = await client.post("/api/compliance/screenings/preview", json=period())
        assert preview.status_code == 200, preview.text
        assert preview.json()["messages"] == 2
        assert preview.json()["conversations"] == 1
        screening_id = await start_screening(client, version["id"])
        replay = await client.post(
            "/api/compliance/screenings",
            json={**period(), "id": screening_id, "instructions_version_id": version["id"]},
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == screening_id
        # The screening's conversation cutoff remains stable as the live chat continues.
        session.add(
            Message(
                conversation_id=chat.id,
                parent_id=future.id,
                role="user",
                content="A new question after the screening was requested.",
            )
        )
        await session.commit()
        claim = await claim_next(session)
        assert claim is not None
        assert claim.conversation_id == chat.id
        await session.commit()
        work = await prepare_work(session, claim)
        assert work is not None
        assert set(work.target_message_ids) == targets
        assert [(node.id, node.parent_id) for node in work.transcript] == context
        await session.commit()
        assert await claim_next(session) is None
        assert await finish_result(session, claim, work, [])
        await session.commit()
        persisted = list(
            (
                await session.scalars(
                    select(ComplianceItem).where(ComplianceItem.screening_id == screening_id)
                )
            ).all()
        )
        assert {item.message_id for item in persisted} == targets
        assert {item.status for item in persisted} == {"screened"}
        assert (await client.get(f"/api/compliance/screenings/{screening_id}/flags")).json() == {
            "items": [],
            "total": 0,
        }


@pytest.mark.asyncio
async def test_screening_uses_one_request_cutoff_and_rejects_manifest_drift(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = transactional_session
    staff = await make_user(session, SystemGroupSlug.USER)
    reviewer = await make_user(session, SystemGroupSlug.DEV)
    chat, target = await make_chat(session, staff)
    cutoff = START + timedelta(hours=4)
    session.add(
        Message(
            conversation_id=chat.id,
            parent_id=target.id,
            role="assistant",
            content="Created after the request cutoff.",
            created_at=cutoff + timedelta(hours=1),
        )
    )
    await session.commit()
    monkeypatch.setattr(compliance_routes, "current_time_utc", lambda: cutoff)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        version = await save_rule(client)
        screening_id = await start_screening(client, version["id"])
        detail = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert datetime.fromisoformat(detail["created_at"]) == cutoff
        assert detail["messages"] == 1

        # Simulate a transaction that was invisible during admission but commits with
        # a source timestamp inside the persisted request snapshot.
        session.add(
            Message(
                conversation_id=chat.id,
                parent_id=target.id,
                role="assistant",
                content="Committed after target selection.",
                created_at=cutoff - timedelta(hours=1),
            )
        )
        await session.commit()
        claim = await claim_next(session)
        assert claim is not None
        with pytest.raises(ScreeningUnavailableError, match="invalid_context"):
            await prepare_work(session, claim)


@pytest.mark.asyncio
async def test_instruction_layers_create_versions_and_keep_screenings_pinned(
    transactional_session: AsyncSession,
) -> None:
    session = transactional_session
    staff = await make_user(session, SystemGroupSlug.USER)
    owner = await make_user(session, SystemGroupSlug.DEV)
    reviewer = await make_user(session, SystemGroupSlug.ADMIN)
    await replace_user_permission_overrides(
        session, reviewer, {PermissionKey.ACCESS_COMPLIANCE: True}
    )
    await make_chat(session, staff)
    await session.commit()

    async def deploy_agent_prompt(client: AsyncClient, name: str, content: str) -> None:
        created = await client.post(
            "/api/prompts/versions",
            json={
                "name": name,
                "is_internal": True,
                "scope": "compliance",
                "prompts": [
                    {"filename": "compliance_screening_agent_internal.j2", "content": content}
                ],
            },
        )
        assert created.status_code == 201, created.text
        deployed = await client.post(
            f"/api/prompts/versions/{created.json()['id']}/deploy", json={}
        )
        assert deployed.status_code == 200, deployed.text

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner.id)
        await deploy_agent_prompt(
            client, "Pinned screening prompt", "Pinned screening agent prompt {{ 1 + 1 }}."
        )
        version = await save_rule(client)
        screening_id = await start_screening(client, version["id"])
        await deploy_agent_prompt(client, "Later screening prompt", "Later screening agent prompt.")
        revised = await save_rule(client, RULE + " Flag missing qualifications.")
        restored = await client.post(
            "/api/compliance/instructions",
            json={"base_version_id": revised["id"], "restore_from_id": version["id"]},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["number"] == revised["number"] + 1
        assert restored.json()["content"] == RULE
        stale = await client.post(
            "/api/compliance/instructions",
            json={"content": "Stale", "base_version_id": revised["id"]},
        )
        assert stale.status_code == 409
        assert (await client.get("/api/compliance/instructions")).json()[
            "current"
        ] == restored.json()
        original = await client.get(f"/api/compliance/screenings/{screening_id}")
        assert original.json()["instructions"] == version
        claim = await claim_next(session)
        assert claim is not None
        work = await prepare_work(session, claim)
        assert work is not None
        assert work.instructions == RULE
        assert work.agent_prompt == "Pinned screening agent prompt 2."
        await session.commit()
        authenticate_client(client, reviewer.id)
        assert (await client.get("/api/compliance/instructions")).status_code == 200
        forbidden = await client.post(
            "/api/compliance/instructions", json={"content": "Not allowed"}
        )
        assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_shared_decisions_separate_rescreenings_and_source_deletion(
    transactional_session: AsyncSession,
) -> None:
    session = transactional_session
    staff = await make_user(session, SystemGroupSlug.USER)
    owner = await make_user(session, SystemGroupSlug.DEV)
    reviewer = await make_user(session, SystemGroupSlug.ADMIN)
    await replace_user_permission_overrides(
        session, reviewer, {PermissionKey.ACCESS_COMPLIANCE: True}
    )
    chat, target = await make_chat(session, staff)
    session.add(
        Message(
            conversation_id=chat.id,
            parent_id=target.id,
            role="user",
            content="What do you mean by guaranteed?",
            created_at=END + timedelta(hours=1),
        )
    )
    await session.commit()
    chat_id, staff_id, owner_id, reviewer_id = chat.id, staff.id, owner.id, reviewer.id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, owner_id)
        version = await save_rule(client)
        screening_id = await start_screening(client, version["id"])
        claim = await claim_next(session)
        assert claim is not None
        work = await prepare_work(session, claim)
        assert work is not None
        await session.commit()
        concerns = validate_result(
            ScreeningResult(
                complete=True,
                findings=[
                    Concern(
                        message_id=target.id,
                        title="Possible admission promise",
                        categories=[
                            FindingCategory.MISINFORMATION,
                            FindingCategory.REGULATORY_COMPLIANCE,
                        ],
                        explanation=(
                            "The admission guarantee conflicts with the requirement not to promise "
                            "admission."
                        ),
                        message_quote=MESSAGE,
                        instruction_quote=RULE,
                    )
                ],
            ),
            instructions=work.instructions,
            target_messages={
                node.id: node.content
                for node in work.transcript
                if node.id in work.target_message_ids
            },
        )
        assert await finish_result(session, claim, work, concerns)
        await session.flush()
        assert not await finish_result(session, claim, work, concerns)
        await session.execute(
            update(ComplianceScreening)
            .where(ComplianceScreening.id == screening_id)
            .values(screening_version="1")
        )
        await session.commit()
        summary = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert summary["screened"] == 1
        assert summary["pending"] == 0
        assert summary["findings"] == 1
        assert summary["needs_review"] == 1
        flags = await client.get(f"/api/compliance/screenings/{screening_id}/flags")
        assert flags.status_code == 200, flags.text
        flag_row = flags.json()["items"][0]
        assert {key: flag_row[key] for key in ("title", "categories", "chat", "state")} == {
            "title": "Possible admission promise",
            "categories": ["misinformation", "regulatory_compliance"],
            "chat": chat.title,
            "state": "needs_review",
        }
        assert flag_row["message_at"] is not None
        flag_id = flag_row["id"]
        flag_detail = await client.get(f"/api/compliance/screenings/{screening_id}/flags/{flag_id}")
        assert flag_detail.status_code == 200, flag_detail.text
        detail = flag_detail.json()
        assert detail["chat"] == chat.title
        assert detail["message_id"] == str(target.id)
        assert [node["id"] for node in detail["transcript"]] == [
            str(node.id) for node in work.transcript
        ]
        assert detail["flag"]["id"] == flag_id
        assert detail["flag"]["categories"] == ["misinformation", "regulatory_compliance"]
        assert detail["flag"]["evidence"] == MESSAGE

        authenticate_client(client, reviewer_id)
        invalid_state = await client.post(
            f"/api/compliance/flags/{flag_id}/decision",
            json={"state": "needs_review", "expected_revision": 0},
        )
        assert invalid_state.status_code == 422
        too_long_comment = await client.post(
            f"/api/compliance/flags/{flag_id}/decision",
            json={"state": "dismissed", "comment": "x" * 4001, "expected_revision": 0},
        )
        assert too_long_comment.status_code == 422
        decision = await client.post(
            f"/api/compliance/flags/{flag_id}/decision",
            json={
                "state": "dismissed",
                "comment": "  Needs official confirmation.  ",
                "expected_revision": 0,
            },
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["comment"] == "Needs official confirmation."
        conflict = await client.post(
            f"/api/compliance/flags/{flag_id}/decision",
            json={"state": "confirmed", "expected_revision": 0},
        )
        assert conflict.status_code == 412
        assert (await client.get(f"/api/compliance/screenings/{screening_id}")).json()[
            "needs_review"
        ] == 0
        decided_flags = (
            await client.get(f"/api/compliance/screenings/{screening_id}/flags")
        ).json()
        assert decided_flags["items"][0]["state"] == "dismissed"
        changed_decision = await client.post(
            f"/api/compliance/flags/{flag_id}/decision",
            json={
                "state": "confirmed",
                "comment": "Authoritative source verified.",
                "expected_revision": 1,
            },
        )
        assert changed_decision.status_code == 200, changed_decision.text
        history = (
            await client.get(f"/api/compliance/screenings/{screening_id}/flags/{flag_id}")
        ).json()
        assert history["flag"]["decisions"] == [changed_decision.json(), decision.json()]

        await session.execute(
            update(Message).where(Message.id == target.id).values(content="Changed source text.")
        )
        await session.commit()
        changed = (
            await client.get(f"/api/compliance/screenings/{screening_id}/flags/{flag_id}")
        ).json()
        assert changed["flag"] is None
        assert "source text has changed" in changed["error"]
        blocked = await client.post(
            f"/api/compliance/flags/{flag_id}/decision",
            json={"state": "confirmed", "expected_revision": 2},
        )
        assert blocked.status_code == 409
        await session.execute(
            update(Message).where(Message.id == target.id).values(content=MESSAGE)
        )
        await session.commit()

        authenticate_client(client, owner_id)
        repeat_request = {**period(), "id": str(uuid4()), "instructions_version_id": version["id"]}
        assert (
            await client.post("/api/compliance/screenings", json=repeat_request)
        ).status_code == 409
        repeated = await client.post(
            "/api/compliance/screenings", json={**repeat_request, "acknowledge_overlap": True}
        )
        assert repeated.status_code == 200, repeated.text
        assert (await client.get(f"/api/compliance/screenings/{screening_id}")).json()[
            "needs_review"
        ] == 0
        in_flight = await claim_next(session)
        assert in_flight is not None
        work = await prepare_work(session, in_flight)
        assert work is not None
        await session.commit()

        authenticate_client(client, staff_id)
        assert (await client.get("/api/compliance/screenings")).status_code == 403
        deleted = await client.delete(f"/api/conversations/{chat_id}")
        assert deleted.status_code == 204, deleted.text
        assert not await finish_result(session, in_flight, work, [])
        await session.commit()
        session.expire_all()
        assert await session.scalar(select(func.count()).select_from(ComplianceFinding)) == 0
        assert await session.scalar(select(func.count()).select_from(ComplianceDecision)) == 0
        authenticate_client(client, owner_id)
        summary = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert summary["deleted"] == 1
        assert summary["findings"] == 0
        item = await session.scalar(
            select(ComplianceItem).where(ComplianceItem.screening_id == screening_id)
        )
        assert item is not None
        assert item.status == "deleted"
        assert item.message_id is None
        assert (await client.get(f"/api/compliance/screenings/{screening_id}/flags")).json()[
            "total"
        ] == 0


@pytest.mark.asyncio
async def test_compliance_permissions_recovery_and_failures(
    transactional_session: AsyncSession,
) -> None:
    session = transactional_session
    staff = await make_user(session, SystemGroupSlug.USER)
    reviewer = await make_user(session, SystemGroupSlug.DEV)
    await make_chat(session, staff)
    await session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reviewer.id)
        version = await save_rule(client)
        screening_id = await start_screening(client, version["id"])
        claim = await claim_next(session)
        assert claim is not None
        await session.commit()
        await session.execute(
            update(ComplianceItem)
            .where(ComplianceItem.lease_token == claim.token)
            .values(leased_until=START)
        )
        newer = await claim_next(session)
        assert newer is not None
        assert newer.token != claim.token
        work = await prepare_work(session, newer)
        assert work is not None
        assert not await finish_result(session, claim, work, [])
        await finish_error(session, newer, "provider_error")
        await session.commit()
        result = (await client.get(f"/api/compliance/screenings/{screening_id}")).json()
        assert result["screened"] == 0
        assert result["errors"] == 1
        assert result["failures"] == [
            {
                "chat_id": str(claim.conversation_id),
                "chat": "Admission question",
                "assistant_messages": 1,
                "reason": "The screening service could not finish this Chat.",
                "retryable": True,
            }
        ]
        item = await session.scalar(
            select(ComplianceItem).where(ComplianceItem.screening_id == screening_id)
        )
        assert item is not None
        assert item.status == "error"
        assert (
            await client.post(f"/api/compliance/screenings/{screening_id}/retry", json={})
        ).json()["queued"] == 1
        recovered = await claim_next(session)
        assert recovered is not None
        await session.commit()
        await replace_user_permission_overrides(
            session, reviewer, {PermissionKey.CHATS_VIEW_USERS: False}
        )
        await session.commit()
        assert (await client.get(f"/api/compliance/screenings/{screening_id}")).json()[
            "messages"
        ] == 0
        assert not await finish_result(session, recovered, work, [])
        await session.commit()
