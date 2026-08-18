from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.evals.chatbot import TEST_CASES as CHATBOT_TEST_CASES
from app.chat.evals.guardrails import TEST_CASES as GUARDRAILS_TEST_CASES
from app.evals.case_management import get_disk_eval_cases, list_eval_case_definitions
from app.evals.runtime import EvalSuite
from app.models import EvalTestCaseOverlay


def test_eval_case_verified_metadata_defaults_to_unverified() -> None:
    verified_chatbot_cases = [case.test_case_id for case in CHATBOT_TEST_CASES if case.verified]
    verified_guardrails_cases = [
        case.test_case_id for case in GUARDRAILS_TEST_CASES if case.verified
    ]

    assert verified_chatbot_cases == []
    assert verified_guardrails_cases == []
    assert all(isinstance(case.verified, bool) for case in CHATBOT_TEST_CASES)
    assert all(isinstance(case.verified, bool) for case in GUARDRAILS_TEST_CASES)


def test_disk_eval_cases_include_verified_payload_flag() -> None:
    chatbot_cases = get_disk_eval_cases(EvalSuite.CHATBOT)
    guardrails_cases = get_disk_eval_cases(EvalSuite.GUARDRAILS)

    assert chatbot_cases["public_ai_program_grounded_search"].payload["verified"] is False
    assert chatbot_cases["internal_financial_aid_no_award_promises"].payload["verified"] is False
    assert guardrails_cases["internal_valid_catalog_policy_redirect"].payload["verified"] is False


@pytest.mark.asyncio
async def test_database_case_uses_overlay_verified_column(
    transactional_session: AsyncSession,
) -> None:
    transactional_session.add(
        EvalTestCaseOverlay(
            suite="chatbot",
            case_id="database_verified_case",
            case_data={
                "criteria": "Must stay marked as SME verified.",
                "user_input": "How should I answer this verified scenario?",
                "is_internal": True,
                "test_case_id": "database_verified_case",
            },
            verified=True,
            is_deleted=False,
            base_disk_hash=None,
        )
    )
    await transactional_session.flush()

    definitions = await list_eval_case_definitions(transactional_session, EvalSuite.CHATBOT)
    database_case = next(
        definition for definition in definitions if definition.case_id == "database_verified_case"
    )

    assert database_case.status == "database"
    assert database_case.verified is True
    assert database_case.payload["verified"] is True


@pytest.mark.asyncio
async def test_promoted_database_case_uses_disk_verified_metadata(
    transactional_session: AsyncSession,
) -> None:
    disk_case = get_disk_eval_cases(EvalSuite.CHATBOT)["public_ai_program_grounded_search"]
    case_data = dict(disk_case.payload)
    case_data.pop("verified")
    transactional_session.add(
        EvalTestCaseOverlay(
            suite="chatbot",
            case_id=disk_case.case_id,
            case_data=case_data,
            verified=False,
            is_deleted=False,
            base_disk_hash=None,
        )
    )
    await transactional_session.flush()

    definitions = await list_eval_case_definitions(transactional_session, EvalSuite.CHATBOT)
    promoted_case = next(
        definition for definition in definitions if definition.case_id == disk_case.case_id
    )

    assert promoted_case.status == "disk"
    assert promoted_case.verified is False
    assert promoted_case.payload["verified"] is False
