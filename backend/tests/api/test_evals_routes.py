from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import evals as evals_routes
from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
from app.core.security import get_password_hash
from app.evals import rag_data, test_db
from app.evals.run_tracking import EvalRunSnapshot, PersistedEvalRunEvent
from app.evals.runtime import EvalRunRequestConfig, EvalSuite
from app.evals.service import EvalRunJob, EvalRunPaths
from app.main import app
from app.models import (
    EvalCaseResult,
    EvalCaseRunResult,
    EvalRunRecord,
    OtelSpan,
    PromptSetScope,
    PromptSetVersion,
    User,
)
from tests.api.auth_helpers import authenticate_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


def _format_test_sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


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


def _eval_trace_span(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    started_at: datetime,
    parent_span_id: str | None = None,
    kind: str = "INTERNAL",
    duration_ms: float = 1000,
    attributes: dict[str, object] | None = None,
    request_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_cost: float | None = None,
    is_ai: bool = False,
) -> OtelSpan:
    return OtelSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        kind=kind,
        status_code="OK",
        status_message=None,
        start_time=started_at,
        end_time=started_at + timedelta(milliseconds=duration_ms),
        span_time=started_at,
        duration_ms=duration_ms,
        attributes=attributes or {},
        events=None,
        links=None,
        resource=None,
        scope=None,
        request_model=request_model,
        provider_name=None,
        server_address=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        is_ai=is_ai,
        is_embedding=False,
        is_internal=True,
        conversation_id=None,
        message_id=None,
        total_time=None,
    )


@pytest.mark.asyncio
async def test_evals_requires_access_permission(transactional_session: AsyncSession) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="eval"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/evals/test-cases", params={"suite": "chatbot"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_evals_test_cases_available_for_admin(transactional_session: AsyncSession) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/evals/test-cases", params={"suite": "chatbot"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["suite"] == "chatbot"
    assert "public_ai_program_grounded_search" in payload["cases"]
    assert "internal_academic_policies_catalog_source" in payload["cases"]


@pytest.mark.asyncio
async def test_evals_cases_include_public_chatbot_payloads(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/evals/cases", params={"suite": "chatbot"})

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()}
    assert cases["public_ai_program_grounded_search"]["payload"]["is_internal"] is False
    assert cases["internal_academic_policies_catalog_source"]["payload"]["is_internal"] is True


@pytest.mark.asyncio
async def test_evals_lists_internal_assistant_instruction_versions_for_eval_only_user(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )
    eval_user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="eval-only"
    )
    await replace_user_permission_overrides(
        transactional_session, eval_user, {PermissionKey.ACCESS_EVALS: True}
    )
    await transactional_session.commit()
    internal_version = PromptSetVersion(
        version_number=2,
        name="Internal candidate",
        created_by_id=admin.id,
        is_deployed=True,
        is_internal=True,
        scope=PromptSetScope.ASSISTANT,
    )
    older_internal_version = PromptSetVersion(
        version_number=1,
        name="Older internal candidate",
        created_by_id=admin.id,
        is_deployed=False,
        is_internal=True,
        scope=PromptSetScope.ASSISTANT,
    )
    transactional_session.add_all(
        [
            internal_version,
            older_internal_version,
            PromptSetVersion(
                version_number=1,
                name="Public candidate",
                created_by_id=admin.id,
                is_deployed=False,
                is_internal=False,
                scope=PromptSetScope.ASSISTANT,
            ),
            PromptSetVersion(
                version_number=1,
                name="Summary candidate",
                created_by_id=admin.id,
                is_deployed=False,
                is_internal=True,
                scope=PromptSetScope.SUMMARY,
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, eval_user.id)
        response = await client.get("/api/evals/instruction-versions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(internal_version.id),
            "version_number": 2,
            "name": "Internal candidate",
            "is_deployed": True,
        },
        {
            "id": str(older_internal_version.id),
            "version_number": 1,
            "name": "Older internal candidate",
            "is_deployed": False,
        },
    ]


@pytest.mark.asyncio
async def test_evals_can_create_public_chatbot_case(transactional_session: AsyncSession) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post(
            "/api/evals/cases",
            json={
                "suite": "chatbot",
                "payload": {
                    "test_case_id": "public_custom_case",
                    "user_input": "Do you have scholarships?",
                    "criteria": "1. Must answer as the public assistant",
                    "is_internal": False,
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "public_custom_case"
    assert payload["payload"]["is_internal"] is False


@pytest.mark.asyncio
async def test_evals_reports_list_and_detail(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )

    report = EvalRunRecord(
        report_id="eval-backendpagination-chatbot-20260417-120000-000000",
        suite="chatbot",
        name="chatbot",
        generated_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
        repeats=5,
        max_concurrency=10,
        pass_threshold=0.9,
        status="complete",
        log_id=None,
        config={},
        model_configs={"chatbot": {"model": "gpt-test", "temperature": 0.1}},
        additional_settings={},
    )
    case = EvalCaseResult(
        position=0,
        name="case_a",
        inputs={"user_input": "hi", "is_internal": True},
        expected_output=None,
        metadata_json=None,
        stats={
            "runs": 1,
            "assertion_pass_rates": {"passed": 0.0},
            "pass_rate": 0.0,
            "runtime_error_rate": 0.0,
            "duration_median": 0.25,
        },
    )
    case.runs.append(
        EvalCaseRunResult(
            run_index=1,
            output={"chatbot_response": "Hello"},
            duration=0.1,
            error=None,
            otel_trace_id="1234567890abcdef1234567890abcdef",
            otel_span_id="1234567890abcdef",
            assertions={"passed": {"name": "passed", "value": False, "reason": "nope"}},
            scores={},
            labels={},
        )
    )
    report.cases.append(case)
    older_report = EvalRunRecord(
        report_id="eval-backendpagination-guardrails-20260416-120000-000000",
        suite="guardrails",
        name="guardrails_eval",
        generated_at=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
        repeats=1,
        max_concurrency=5,
        pass_threshold=0.9,
        status="complete",
        log_id=None,
        config={},
        model_configs={},
        additional_settings={},
    )
    transactional_session.add(report)
    transactional_session.add(older_report)
    await transactional_session.flush()

    @asynccontextmanager
    async def fake_eval_report_session() -> AsyncGenerator[AsyncSession]:
        yield transactional_session

    monkeypatch.setattr(evals_routes, "eval_report_session", fake_eval_report_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        list_response = await client.get("/api/evals/reports", params={"search": report.report_id})
        paged_response = await client.get(
            "/api/evals/reports",
            params={
                "descending": "false",
                "limit": 1,
                "offset": 0,
                "search": "backendpagination",
                "sort_by": "title",
            },
        )
        detail_response = await client.get(f"/api/evals/reports/{report.report_id}")

    assert list_response.status_code == 200
    report_page = list_response.json()
    assert report_page["total"] == 1
    reports = report_page["items"]
    assert len(reports) == 1
    assert reports[0]["id"] == report.report_id
    assert reports[0]["title"] == "Chatbot"
    assert reports[0]["suite"] == "chatbot"
    assert reports[0]["repeats"] == 5
    assert reports[0]["concurrency"] == 10
    assert reports[0]["case_count"] == 1
    assert reports[0]["run_count"] == 1
    assert reports[0]["is_internal"] is True
    assert reports[0]["model_configs"] == {"chatbot": {"model": "gpt-test", "temperature": 0.1}}
    assert reports[0]["pass_rate_average"] == 0.0
    assert reports[0]["duration_median_average"] == 0.25

    assert paged_response.status_code == 200
    paged_payload = paged_response.json()
    assert paged_payload["total"] == 2
    assert len(paged_payload["items"]) == 1
    assert paged_payload["items"][0]["title"] == "Chatbot"

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == report.report_id
    assert detail["title"] == "Chatbot"
    assert detail["is_internal"] is True
    assert detail["cases"][0]["name"] == "case_a"
    assert detail["cases"][0]["runs"][0]["otel_trace_id"] == "1234567890abcdef1234567890abcdef"
    assert detail["cases"][0]["runs"][0]["assertions"]["passed"] == {
        "name": "passed",
        "value": False,
        "reason": "nope",
    }


@pytest.mark.asyncio
async def test_eval_trace_routes_read_test_database(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-trace-admin"
    )
    trace_id = "abcdef1234567890abcdef1234567890"
    started_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    transactional_session.add_all(
        [
            _eval_trace_span(
                trace_id=trace_id,
                span_id="1111111111111111",
                name="Evaluation: guardrails_eval",
                started_at=started_at,
                total_cost=0.01,
            ),
            _eval_trace_span(
                trace_id=trace_id,
                span_id="3333333333333333",
                parent_span_id="1111111111111111",
                name="eval_run case_a #1",
                started_at=started_at,
                attributes={"app.eval.case_name": "case_a", "app.eval.run_index": 1},
            ),
            _eval_trace_span(
                trace_id=trace_id,
                span_id="4444444444444444",
                parent_span_id="3333333333333333",
                name="gen_ai.evaluation.result",
                started_at=started_at + timedelta(seconds=1),
                duration_ms=1,
                attributes={
                    "gen_ai.evaluation.name": "passed",
                    "gen_ai.evaluation.score.label": "fail",
                    "gen_ai.evaluation.score.value": 0.0,
                    "app.eval.case_name": "case_a",
                    "app.eval.run_index": 1,
                    "app.eval.evaluator.name": "judge",
                    "app.eval.result.kind": "assertion",
                },
            ),
            _eval_trace_span(
                trace_id=trace_id,
                span_id="2222222222222222",
                parent_span_id="3333333333333333",
                name="Chat Completion with 'gpt-test'",
                started_at=started_at,
                kind="CLIENT",
                duration_ms=500,
                request_model="gpt-test",
                input_tokens=10,
                output_tokens=20,
                total_cost=0.02,
                is_ai=True,
            ),
            _eval_trace_span(
                trace_id="00000000000000000000000000000000",
                span_id="5555555555555555",
                name="Chat Completion with 'gpt-older'",
                started_at=started_at - timedelta(seconds=30),
                kind="CLIENT",
                duration_ms=250,
                request_model="gpt-older",
                is_ai=True,
            ),
            _eval_trace_span(
                trace_id="ffffffffffffffffffffffffffffffff",
                span_id="6666666666666666",
                name="Non-AI setup",
                started_at=started_at + timedelta(seconds=30),
            ),
        ]
    )
    await transactional_session.flush()

    @asynccontextmanager
    async def fake_eval_report_session() -> AsyncGenerator[AsyncSession]:
        yield transactional_session

    monkeypatch.setattr(evals_routes, "eval_report_session", fake_eval_report_session)
    index_params = {
        "ai_only": "true",
        "start": "2026-04-17T11:59:00Z",
        "end": "2026-04-17T12:01:00Z",
        "limit": 1,
        "sort_by": "latest_start",
        "descending": "true",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        index_response = await client.get(
            "/api/evals/trace-index", params={**index_params, "offset": 0}
        )
        older_index_response = await client.get(
            "/api/evals/trace-index", params={**index_params, "offset": 1}
        )
        empty_index_response = await client.get(
            "/api/evals/trace-index", params={**index_params, "offset": 2}
        )
        detail_response = await client.get(f"/api/evals/trace/{trace_id}")

    assert index_response.status_code == 200
    index_payload = index_response.json()
    assert index_payload["total"] == 2
    assert index_payload["items"][0]["trace_id"] == trace_id
    assert index_payload["items"][0]["model"] == "gpt-test"
    assert index_payload["items"][0]["is_error"] is False
    assert index_payload["items"][0]["failed_result_count"] == 1
    assert older_index_response.status_code == 200
    assert older_index_response.json()["total"] == 2
    assert older_index_response.json()["items"][0]["trace_id"] == (
        "00000000000000000000000000000000"
    )
    assert empty_index_response.status_code == 200
    assert empty_index_response.json() == {"items": [], "total": 2}

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["trace_id"] == trace_id
    assert detail_payload["span_count"] == 4
    assert abs(detail_payload["total_cost"] - 0.03) < 0.000001
    overview_by_span_id = {item["span_id"]: item for item in detail_payload["overview"]}
    assert overview_by_span_id["1111111111111111"]["outcome"] == "fail"
    assert overview_by_span_id["1111111111111111"]["failed_result_count"] == 1
    assert overview_by_span_id["3333333333333333"]["outcome"] == "fail"
    assert overview_by_span_id["4444444444444444"]["outcome"] == "fail"
    assert overview_by_span_id["2222222222222222"]["type"] == "llm"
    assert overview_by_span_id["2222222222222222"]["outcome"] is None
    assert overview_by_span_id["2222222222222222"]["data"]["model"] == "gpt-test"


@pytest.mark.asyncio
async def test_stream_resolves_request_and_starts_background_run(
    transactional_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )

    captured: dict[str, object] = {}

    class FakeJob:
        run_id = "fake-run"

    class FakeManager:
        async def start_run(self, config: object, *, paths: object, user_id: object) -> FakeJob:
            assert paths == EvalRunPaths(logs_dir=tmp_path / "reports" / "logs")
            captured["config"] = config
            captured["user_id"] = user_id
            return FakeJob()

    async def fake_stream(run_id: str, user_id: object, _request: object) -> AsyncGenerator[str]:
        assert run_id == "fake-run"
        assert user_id == admin.id
        yield _format_test_sse("status", {"status": "start", "suite": "chatbot", "run_id": run_id})
        yield _format_test_sse("log", {"message": "background run started", "run_id": run_id})
        yield _format_test_sse("status", {"status": "complete", "run_id": run_id})

    async def fake_resolve_eval_case_payloads_for_run(
        _session: object, suite: EvalSuite, selected_case_ids: tuple[str, ...]
    ) -> tuple[dict[str, object], ...]:
        assert suite == EvalSuite.CHATBOT
        assert selected_case_ids == ("case_a", "case_b")
        return ({"test_case_id": "case_a"}, {"test_case_id": "case_b"})

    monkeypatch.setattr(evals_routes, "LOGS_DIR", tmp_path / "reports" / "logs")
    monkeypatch.setattr(evals_routes, "EVAL_RUN_MANAGER", FakeManager())
    monkeypatch.setattr(evals_routes, "_stream_persisted_eval_run", fake_stream)
    monkeypatch.setattr(
        evals_routes, "resolve_eval_case_payloads_for_run", fake_resolve_eval_case_payloads_for_run
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post(
            "/api/evals/runs/stream",
            json={
                "suite": "chatbot",
                "repeat": 2,
                "max_concurrency": 3,
                "pass_threshold": 0.8,
                "test_cases": "case_a,case_b",
                "instructions_source": "draft",
                "draft_prompt_templates": [
                    {
                        "filename": "chatbot_agent_internal.j2",
                        "content": "Draft chatbot instructions",
                    }
                ],
                "chatbot_model": "azure/chatbot",
                "guardrail_model": "azure/guardrail",
                "evaluation_model": "azure/judge",
                "rebuild_rag": True,
            },
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert any(event == "log" for event, _payload in events)
    assert any(
        event == "status" and payload.get("status") == "complete" for event, payload in events
    )

    config = cast(EvalRunRequestConfig, captured["config"])
    assert config.suite == EvalSuite.CHATBOT
    assert config.repeat == 2
    assert config.max_concurrency == 3
    assert config.pass_threshold == 0.8
    assert config.test_cases == ("case_a", "case_b")
    assert config.instructions is not None
    assert config.instructions.source == "draft"
    assert config.instructions.template_overrides["chatbot_agent_internal.j2"] == (
        "Draft chatbot instructions"
    )
    assert "guardrails_agent_internal.j2" in config.instructions.template_overrides
    assert config.chatbot_model == "azure/chatbot"
    assert config.guardrail_model == "azure/guardrail"
    assert config.evaluation_model == "azure/judge"
    assert config.rebuild_rag is True
    assert captured["user_id"] == admin.id


@pytest.mark.asyncio
async def test_current_run_stream_and_cancel_use_user_scoped_background_job(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )
    started_at = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    cancelled = False

    def snapshot() -> EvalRunSnapshot:
        return EvalRunSnapshot(
            run_id="active-run",
            user_id=admin.id,
            suite="chatbot",
            status="cancelled" if cancelled else "start",
            report_id=None,
            error_message=None,
            started_at=started_at,
            completed_at=started_at if cancelled else None,
        )

    async def fake_current(user_id: object) -> EvalRunSnapshot:
        assert user_id == admin.id
        return snapshot()

    async def fake_get(run_id: str, user_id: object) -> EvalRunSnapshot:
        assert run_id == "active-run"
        assert user_id == admin.id
        return snapshot()

    async def fake_stream(run_id: str, user_id: object, _request: object) -> AsyncGenerator[str]:
        assert run_id == "active-run"
        assert user_id == admin.id
        yield _format_test_sse("status", {"status": "start", "run_id": run_id})
        yield _format_test_sse("log", {"message": "still running", "run_id": run_id})

    async def fake_cancel(run_id: str, user_id: object) -> EvalRunSnapshot:
        nonlocal cancelled
        assert run_id == "active-run"
        assert user_id == admin.id
        cancelled = True
        return snapshot()

    class FakeManager:
        def get_run(self, _run_id: str, *, user_id: object) -> object:
            del user_id
            raise evals_routes.EvalRunNotFoundError

    monkeypatch.setattr(evals_routes, "EVAL_RUN_MANAGER", FakeManager())
    monkeypatch.setattr(evals_routes, "get_current_eval_run", fake_current)
    monkeypatch.setattr(evals_routes, "get_eval_run", fake_get)
    monkeypatch.setattr(evals_routes, "_stream_persisted_eval_run", fake_stream)
    monkeypatch.setattr(evals_routes, "request_eval_run_cancellation", fake_cancel)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        current_response = await client.get("/api/evals/runs/current")
        stream_response = await client.post("/api/evals/runs/active-run/stream", json={})
        cancel_response = await client.post("/api/evals/runs/active-run/cancel", json={})

    assert current_response.status_code == 200
    assert current_response.json()["run_id"] == "active-run"
    assert current_response.json()["status"] == "start"

    assert stream_response.status_code == 200
    events = _parse_sse_events(stream_response.text)
    assert ("log", {"message": "still running", "run_id": "active-run"}) in events

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_persisted_eval_stream_replays_then_follows_cross_worker_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    calls = 0

    @asynccontextmanager
    async def fake_listener() -> AsyncGenerator[AsyncGenerator[str]]:
        async def notifications() -> AsyncGenerator[str]:
            yield "another-run"
            yield "active-run"

        yield notifications()

    async def fake_list(
        run_id: str, requested_user_id: object, *, after_sequence: int = 0
    ) -> list[PersistedEvalRunEvent]:
        nonlocal calls
        assert run_id == "active-run"
        assert requested_user_id == user_id
        calls += 1
        if after_sequence == 0:
            return [
                PersistedEvalRunEvent(1, "status", {"status": "start", "run_id": run_id}),
                PersistedEvalRunEvent(2, "log", {"message": "before navigation", "run_id": run_id}),
            ]
        return [
            PersistedEvalRunEvent(3, "log", {"message": "after navigation", "run_id": run_id}),
            PersistedEvalRunEvent(4, "status", {"status": "complete", "run_id": run_id}),
        ]

    class FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    monkeypatch.setattr(evals_routes, "listen_eval_run_notifications", fake_listener)
    monkeypatch.setattr(evals_routes, "list_eval_run_events", fake_list)

    payload = "".join(
        [
            event
            async for event in evals_routes._stream_persisted_eval_run(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
                "active-run", user_id, cast(Any, FakeRequest())
            )
        ]
    )
    events = _parse_sse_events(payload)

    assert calls == 2
    assert [event for event, _payload in events] == ["status", "log", "log", "status"]
    assert [payload["message"] for event, payload in events if event == "log"] == [
        "before navigation",
        "after navigation",
    ]


def test_load_eval_database_url_does_not_mutate_runtime_db_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_SERVER", "localhost")
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_PORT", 5432)
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_USER", "postgres")
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_PASSWORD", "password")
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_DB", "demo_test")
    monkeypatch.setattr(test_db.settings, "POSTGRES_DB", "demo")
    monkeypatch.setenv("POSTGRES_DB", "demo")

    database_url = test_db.load_eval_database_url()

    assert database_url == "postgresql+psycopg://postgres:password@localhost:5432/demo_test"
    assert os.environ["POSTGRES_DB"] == "demo"


def test_load_eval_database_url_rejects_runtime_db_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_SERVER", "localhost")
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_PORT", 5432)
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_USER", "postgres")
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_PASSWORD", "password")
    monkeypatch.setattr(test_db.settings, "PYTEST_POSTGRES_DB", "demo_test")
    monkeypatch.setattr(test_db.settings, "POSTGRES_DB", "demo_test")

    with pytest.raises(test_db.EvalDatabaseConfigError):
        test_db.load_eval_database_url()


@pytest.mark.asyncio
async def test_populate_rag_data_uses_supplied_eval_engine(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    used_session_markers: list[str] = []

    class FakeSession:
        marker = "eval-session"

    class FakeSessionFactory:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *_args: object) -> None:
            return None

    def fake_session_factory() -> FakeSessionFactory:
        return FakeSessionFactory()

    def fake_create_session_factory(engine: object) -> object:
        assert engine == "guarded-engine"
        return fake_session_factory

    async def fake_build_search_db(
        _openai: object, session: object, *, force_rebuild: bool, dry_run: bool
    ) -> None:
        assert force_rebuild is True
        assert dry_run is False
        assert isinstance(session, FakeSession)
        used_session_markers.append(session.marker)

    monkeypatch.setattr(rag_data, "create_session_factory", fake_create_session_factory)

    def fake_get_azure_openai_client() -> object:
        return object()

    monkeypatch.setattr(
        "app.chat.tools.utils.get_azure_openai_client", fake_get_azure_openai_client
    )
    monkeypatch.setattr("app.rag.build.build_search_db", fake_build_search_db)

    await rag_data.populate_rag_data(cast(Any, "guarded-engine"))

    assert used_session_markers == ["eval-session"]


@pytest.mark.asyncio
async def test_guardrails_background_run_skips_rag_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeReport:
        name = "guardrails_eval"
        repeats = 1
        max_concurrency = 5
        cases: tuple[object, ...] = ()

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    class FakeRecord:
        report_id = "eval-guardrails-20260417-120000-000000"
        name = "guardrails_eval"
        generated_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
        repeats = 1
        max_concurrency = 5

    eval_session_factory = object()
    initialized_engines: list[object] = []

    def fake_load_and_migrate_eval_database() -> str:
        return "postgresql+psycopg://postgres:password@localhost:5432/demo_test"

    def fake_create_test_db_engine(database_url: str) -> FakeEngine:
        assert database_url.endswith("demo_test")
        return FakeEngine()

    async def fake_initialize_test_db_schema(engine: object) -> None:
        initialized_engines.append(engine)

    async def fail_prepare_test_db_engine(*, rebuild_rag: bool, database_url: str) -> object:
        del rebuild_rag, database_url
        raise AssertionError("guardrails evals should not prepare RAG data")

    def fake_create_session_factory(engine: object) -> object:
        assert initialized_engines == [engine]
        return eval_session_factory

    async def fake_run_guardrails_evaluation(config: object) -> FakeReport:
        assert getattr(config, "session_factory") is eval_session_factory
        return FakeReport()

    async def fake_save_eval_report(*args: object, **kwargs: object) -> FakeRecord:
        assert args[0] is eval_session_factory
        assert kwargs["suite"] == "guardrails"
        return FakeRecord()

    monkeypatch.setattr(
        "app.evals.service.load_and_migrate_eval_database", fake_load_and_migrate_eval_database
    )
    monkeypatch.setattr("app.evals.service.create_test_db_engine", fake_create_test_db_engine)
    monkeypatch.setattr(
        "app.evals.service.initialize_test_db_schema", fake_initialize_test_db_schema
    )
    monkeypatch.setattr("app.evals.service.prepare_test_db_engine", fail_prepare_test_db_engine)
    monkeypatch.setattr("app.evals.service.create_session_factory", fake_create_session_factory)
    monkeypatch.setattr(
        "app.evals.service.run_guardrails_evaluation", fake_run_guardrails_evaluation
    )
    monkeypatch.setattr("app.evals.service.save_eval_report", fake_save_eval_report)

    job = EvalRunJob(
        EvalRunRequestConfig(suite=EvalSuite.GUARDRAILS),
        paths=EvalRunPaths(logs_dir=tmp_path / "reports" / "logs"),
        user_id=None,
    )
    job.start()
    await job.wait()

    assert "guardrails evals do not use RAG" in job.log_path.read_text(encoding="utf-8")
    assert job.status == "complete"


@pytest.mark.asyncio
async def test_stream_rejects_unknown_suite(transactional_session: AsyncSession) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="eval-admin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post(
            "/api/evals/runs/stream", json={"suite": "missing", "repeat": 1, "max_concurrency": 1}
        )

    assert response.status_code == 400
