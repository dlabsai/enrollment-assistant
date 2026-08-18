from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.agents import GuardrailsResult
from app.chat.config import TEMPLATES_DIR
from app.chat.engine_utils import prompt_context_trace_attributes
from app.chat.evals import chatbot as chatbot_eval
from app.chat.evals import guardrails as guardrails_eval
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.evals import EvaluationReport
from app.evals.instructions import (
    EvalInstructionsNotFoundError,
    EvalInstructionsSnapshot,
    EvalInstructionsValidationError,
    resolve_eval_instructions,
)
from app.evals.runtime import EvalRunConfig, EvalRunRequestConfig, EvalSuite
from app.evals.storage import eval_run_config_payload
from app.models import PromptSetScope, PromptSetTemplate, PromptSetVersion, User
from app.prompt_sets import hash_prompt_templates, read_disk_templates


def test_prompt_context_maps_to_canonical_trace_attributes() -> None:
    assert prompt_context_trace_attributes(
        {
            "source": "saved",
            "scope": "assistant",
            "hash": "a" * 64,
            "prompt_set_version_id": "version-id",
            "template_filenames": ["chatbot_agent_internal.j2"],
        }
    ) == {
        "app.prompt.source": "saved",
        "app.prompt.scope": "assistant",
        "app.prompt.hash": "a" * 64,
        "app.prompt.set.version_id": "version-id",
    }


def test_prompt_template_hash_is_stable_and_content_sensitive() -> None:
    expected_hash = "64512d70ec4505827d8cfc40cb4dcec37955cca25a4c654993f74341dd0800e5"

    assert hash_prompt_templates({"a.j2": "A", "b.j2": "B"}) == expected_hash
    assert hash_prompt_templates({"b.j2": "B", "a.j2": "A"}) == expected_hash
    assert hash_prompt_templates({"a.j2": "A"}) != hash_prompt_templates({"a.j2": "changed"})


async def _create_saved_assistant_version(
    session: AsyncSession,
    *,
    chatbot_content: str,
    guardrails_content: str,
    is_internal: bool = True,
    is_deployed: bool = False,
) -> PromptSetVersion:
    group = await get_group_for_slug(session, SystemGroupSlug.ADMIN)
    owner = User(
        email=f"eval-instructions-{uuid4()}@example.com",
        name="Eval Instructions Owner",
        password_hash="not-a-real-hash",  # noqa: S106
        is_active=True,
        group_id=group.id,
    )
    session.add(owner)
    await session.flush()

    version = PromptSetVersion(
        version_number=1,
        is_internal=is_internal,
        scope=PromptSetScope.ASSISTANT,
        name="Candidate instructions",
        is_deployed=is_deployed,
        created_by_id=owner.id,
    )
    session.add(version)
    await session.flush()
    suffix = "_internal" if is_internal else ""
    session.add_all(
        [
            PromptSetTemplate(
                prompt_set_version_id=version.id,
                filename=f"chatbot_agent{suffix}.j2",
                content=chatbot_content,
            ),
            PromptSetTemplate(
                prompt_set_version_id=version.id,
                filename=f"guardrails_agent{suffix}.j2",
                content=guardrails_content,
            ),
        ]
    )
    await session.flush()
    return version


@pytest.mark.asyncio
async def test_default_based_snapshots_complete_and_hash_assistant_templates(
    transactional_session: AsyncSession,
) -> None:
    disk_templates = read_disk_templates(TEMPLATES_DIR)

    live_snapshot = await resolve_eval_instructions(
        transactional_session,
        source="live",
        prompt_set_version_id=None,
        draft_base_prompt_set_version_id=None,
        draft_templates=None,
    )
    snapshot = await resolve_eval_instructions(
        transactional_session,
        source="draft",
        prompt_set_version_id=None,
        draft_base_prompt_set_version_id=None,
        draft_templates=(("chatbot_agent_internal.j2", "Draft chatbot instructions"),),
    )

    assert live_snapshot.template_overrides == {
        filename: disk_templates[filename]
        for filename in ("chatbot_agent_internal.j2", "guardrails_agent_internal.j2")
    }
    assert live_snapshot.report_metadata() == {"source": "live", "hash": live_snapshot.content_hash}
    expected_templates = {
        "chatbot_agent_internal.j2": "Draft chatbot instructions",
        "guardrails_agent_internal.j2": disk_templates["guardrails_agent_internal.j2"],
    }
    assert snapshot.template_overrides == expected_templates
    assert snapshot.content_hash == hash_prompt_templates(expected_templates)
    assert snapshot.report_metadata() == {
        "source": "draft",
        "hash": snapshot.content_hash,
        "base": "default",
    }
    assert snapshot.prompt_context() == {
        "source": "draft",
        "scope": "assistant",
        "is_internal": True,
        "hash": snapshot.content_hash,
        "template_filenames": sorted(expected_templates),
    }
    assert (
        eval_run_config_payload(
            EvalRunRequestConfig(suite=EvalSuite.CHATBOT, instructions=snapshot)
        )["instructions"]
        == snapshot.report_metadata()
    )


@pytest.mark.asyncio
async def test_live_saved_and_saved_based_draft_snapshots_keep_version_identity(
    transactional_session: AsyncSession,
) -> None:
    version = await _create_saved_assistant_version(
        transactional_session,
        chatbot_content="Saved chatbot instructions",
        guardrails_content="Saved guardrails instructions",
        is_deployed=True,
    )

    live_snapshot = await resolve_eval_instructions(
        transactional_session,
        source="live",
        prompt_set_version_id=None,
        draft_base_prompt_set_version_id=None,
        draft_templates=None,
    )
    saved_snapshot = await resolve_eval_instructions(
        transactional_session,
        source="saved",
        prompt_set_version_id=version.id,
        draft_base_prompt_set_version_id=None,
        draft_templates=None,
    )
    draft_snapshot = await resolve_eval_instructions(
        transactional_session,
        source="draft",
        prompt_set_version_id=None,
        draft_base_prompt_set_version_id=version.id,
        draft_templates=(("guardrails_agent_internal.j2", "Draft guardrails instructions"),),
    )

    assert live_snapshot.template_overrides == saved_snapshot.template_overrides
    assert live_snapshot.report_metadata() == {
        "source": "live",
        "hash": live_snapshot.content_hash,
        "version_id": str(version.id),
        "version_number": 1,
        "version_name": "Candidate instructions",
    }
    assert saved_snapshot.report_metadata() == {
        "source": "saved",
        "hash": saved_snapshot.content_hash,
        "version_id": str(version.id),
        "version_number": 1,
        "version_name": "Candidate instructions",
    }
    assert draft_snapshot.report_metadata() == {
        "source": "draft",
        "hash": draft_snapshot.content_hash,
        "base": "saved",
        "base_version_id": str(version.id),
        "base_version_number": 1,
        "base_version_name": "Candidate instructions",
    }
    assert draft_snapshot.template_overrides == {
        "chatbot_agent_internal.j2": "Saved chatbot instructions",
        "guardrails_agent_internal.j2": "Draft guardrails instructions",
    }
    assert draft_snapshot.prompt_context() == {
        "source": "draft",
        "scope": "assistant",
        "is_internal": True,
        "hash": draft_snapshot.content_hash,
        "template_filenames": ["chatbot_agent_internal.j2", "guardrails_agent_internal.j2"],
        "prompt_set_version_id": str(version.id),
    }


@pytest.mark.asyncio
async def test_chatbot_eval_applies_selected_instructions_only_to_internal_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = EvalInstructionsSnapshot(
        source="draft",
        templates=(
            ("chatbot_agent_internal.j2", "Chatbot instructions"),
            ("guardrails_agent_internal.j2", "Guardrails instructions"),
        ),
        content_hash="a" * 64,
    )
    instructions_by_case: dict[str, EvalInstructionsSnapshot | None] = {}

    async def fake_run_chatbot(
        inputs: chatbot_eval.ChatbotInput,
        _models: dict[str, str],
        _session_factory: object,
        instructions: EvalInstructionsSnapshot | None = None,
    ) -> chatbot_eval.ChatbotOutput:
        instructions_by_case[inputs.test_case_id] = instructions
        return chatbot_eval.ChatbotOutput(chatbot_response="Response", system_prompt="Instructions")

    async def fake_evaluate(
        dataset: Any, task: Any, **kwargs: Any
    ) -> EvaluationReport[Any, Any, Any]:
        assert kwargs["additional_settings"]["instructions"] == snapshot.report_metadata()
        for case in dataset.cases:
            await task(case.inputs)
        return EvaluationReport(name=dataset.name)

    monkeypatch.setattr(chatbot_eval, "run_chatbot", fake_run_chatbot)
    monkeypatch.setattr(chatbot_eval, "evaluate", fake_evaluate)
    config = EvalRunConfig(
        session_factory=cast(Any, object()),
        suite=EvalSuite.CHATBOT,
        case_payloads=(
            {
                "test_case_id": "internal_case",
                "user_input": "Internal question",
                "criteria": "Internal criteria",
                "is_internal": True,
                "verified": True,
            },
            {
                "test_case_id": "public_case",
                "user_input": "Public question",
                "criteria": "Public criteria",
                "is_internal": False,
                "verified": True,
            },
        ),
        instructions=snapshot,
    )

    await chatbot_eval.run_chatbot_evaluation(config)

    assert instructions_by_case == {"internal_case": snapshot, "public_case": None}


@pytest.mark.asyncio
async def test_guardrails_eval_uses_selected_instruction_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_guardrails_agent(_model: str, *, template: object) -> object:
        return template

    async def fake_run_agent(
        _agent: object, _prompt: str, _model_settings: object, **kwargs: object
    ) -> tuple[SimpleNamespace, float]:
        assert kwargs["system_prompt"] == "Selected guardrails: Candidate response"
        assert kwargs["agent_name"] == "guardrails"
        assert kwargs["metadata"] == {
            "is_internal": True,
            "app.prompt.source": "draft",
            "app.prompt.scope": "assistant",
            "app.prompt.hash": "a" * 64,
        }
        return SimpleNamespace(output=GuardrailsResult(is_valid=True)), 0.0

    monkeypatch.setattr(guardrails_eval, "create_guardrails_agent", fake_create_guardrails_agent)
    monkeypatch.setattr(guardrails_eval, "run_agent", fake_run_agent)
    snapshot = EvalInstructionsSnapshot(
        source="draft",
        templates=(
            ("chatbot_agent_internal.j2", "Chatbot instructions"),
            ("guardrails_agent_internal.j2", "Selected guardrails: {{ chatbot_agent_response }}"),
        ),
        content_hash="a" * 64,
    )

    output = await guardrails_eval.run_guardrails(
        guardrails_eval.GuardrailsInput(
            chatbot_response="Candidate response",
            criteria="Must be valid",
            test_case_id="selected_instructions",
            expected_valid=True,
        ),
        "test-model",
        snapshot,
    )

    assert output.is_valid is True
    assert output.system_prompt == "Selected guardrails: Candidate response"


@pytest.mark.asyncio
async def test_live_and_saved_sources_reject_conflicting_fields(
    transactional_session: AsyncSession,
) -> None:
    with pytest.raises(EvalInstructionsValidationError) as live_error:
        await resolve_eval_instructions(
            transactional_session,
            source="live",
            prompt_set_version_id=uuid4(),
            draft_base_prompt_set_version_id=None,
            draft_templates=None,
        )
    assert str(live_error.value) == (
        "Live instructions cannot include a saved version or draft data"
    )

    with pytest.raises(EvalInstructionsValidationError) as saved_error:
        await resolve_eval_instructions(
            transactional_session,
            source="saved",
            prompt_set_version_id=uuid4(),
            draft_base_prompt_set_version_id=None,
            draft_templates=(("chatbot_agent_internal.j2", "Draft"),),
        )
    assert str(saved_error.value) == "Saved instructions cannot include draft data"


@pytest.mark.asyncio
async def test_draft_rejects_invalid_templates_and_non_internal_base_versions(
    transactional_session: AsyncSession,
) -> None:
    public_version = await _create_saved_assistant_version(
        transactional_session,
        chatbot_content="Public chatbot instructions",
        guardrails_content="Public guardrails instructions",
        is_internal=False,
    )

    with pytest.raises(EvalInstructionsValidationError, match="Duplicate draft"):
        await resolve_eval_instructions(
            transactional_session,
            source="draft",
            prompt_set_version_id=None,
            draft_base_prompt_set_version_id=None,
            draft_templates=(
                ("chatbot_agent_internal.j2", "First"),
                ("chatbot_agent_internal.j2", "Second"),
            ),
        )

    with pytest.raises(EvalInstructionsValidationError, match="Unexpected draft"):
        await resolve_eval_instructions(
            transactional_session,
            source="draft",
            prompt_set_version_id=None,
            draft_base_prompt_set_version_id=None,
            draft_templates=(("summary_agent_internal.j2", "Summary draft"),),
        )

    with pytest.raises(EvalInstructionsNotFoundError, match="not found"):
        await resolve_eval_instructions(
            transactional_session,
            source="draft",
            prompt_set_version_id=None,
            draft_base_prompt_set_version_id=public_version.id,
            draft_templates=(("chatbot_agent_internal.j2", "Draft"),),
        )
