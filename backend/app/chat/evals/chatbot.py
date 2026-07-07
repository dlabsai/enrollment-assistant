"""Chatbot eval suite for full internal VA response quality."""

# ruff: noqa: E501

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.chat.agents import get_pydantic_ai_model_name
from app.chat.engine import MessageMetadataOut, MessageOut, handle_conversation_turn
from app.chat.engine_utils import ModelSettings, run_agent
from app.core.config import settings
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.evals import (
    Case,
    Dataset,
    EvaluationReason,
    EvaluationReport,
    Evaluator,
    EvaluatorContext,
    ModelConfig,
    evaluate,
)
from app.evals.case_payloads import validate_eval_case_payload
from app.evals.runtime import EvalRunConfig, EvalSuite
from app.models import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ============================================================================
# Models
# ============================================================================


@dataclass
class ChatbotInput:
    """Input for chatbot evaluation."""

    user_input: str
    criteria: str
    test_case_id: str
    is_internal: bool = True


@dataclass
class ChatbotOutput:
    """Output from chatbot evaluation."""

    chatbot_response: str
    system_prompt: str
    retrieved_tool_context: str = ""
    guardrail_retries: int = 0


class ChatbotJudgeResult(BaseModel):
    """Structured output from the chatbot LLM judge."""

    reasoning: str = Field(description="Explanation of the evaluation.")
    follows_guidelines: bool = Field(description="True if response follows all criteria.")
    is_grounded: bool = Field(description="True if response is grounded in context.")
    passed: bool = Field(description="True if response follows guidelines AND is grounded.")


def format_retrieved_tool_context(tool_calls: list[dict[str, Any]] | None) -> str:
    """Format captured tool calls/results as judge-visible grounding context."""
    if not tool_calls:
        return ""
    return json.dumps(tool_calls, ensure_ascii=False, indent=2)


# ============================================================================
# LLM Judge Evaluator
# ============================================================================


CHATBOT_JUDGE_SYSTEM_PROMPT = """Evaluate a university chatbot response.

You will receive:
- <user_input>: The user's message to the chatbot
- <chatbot_response>: The chatbot's final response to evaluate
- <chatbot_system_prompt>: The system prompt that was used to generate the response (contains rules and canned responses)
- <retrieved_tool_context>: Tool call arguments and tool return data captured during the chatbot run
- <evaluation_criteria>: Specific criteria to check

## CRITICAL: Understanding the System Prompt Structure

The <chatbot_system_prompt> may contain a section called <guardrails_agent_feedback>.
This feedback describes issues with a PREVIOUS response that was already corrected.
The <chatbot_response> you are evaluating is the FINAL response AFTER any corrections were made.

DO NOT attribute content from <guardrails_agent_feedback> to <chatbot_response>.
Only evaluate what is ACTUALLY written in <chatbot_response>.

## follows_guidelines
- Check EACH numbered criterion explicitly against the ACTUAL text in <chatbot_response>
- Be literal and strict about requirements
- Also check canned response rules defined in <chatbot_system_prompt>
- IMPORTANT: Only evaluate the literal content of <chatbot_response>, not content mentioned in guardrails feedback

## is_grounded
The response should only contain information from:
- The rules and canned responses in <chatbot_system_prompt>
- The tool results and retrieved document data in <retrieved_tool_context>
- The user's own message

## passed
True ONLY if both follows_guidelines AND is_grounded are True."""


@lru_cache(maxsize=16)
def _get_chatbot_judge_agent(model: str) -> Agent[None, ChatbotJudgeResult]:
    return Agent(
        get_pydantic_ai_model_name(model),
        output_type=ChatbotJudgeResult,
        system_prompt=CHATBOT_JUDGE_SYSTEM_PROMPT,
    )


@dataclass
class ChatbotJudge(Evaluator[ChatbotInput, ChatbotOutput, Any]):
    """LLM judge evaluator for chatbot responses.

    Evaluates the full chatbot pipeline output including:
    - Whether the response follows the specified guidelines
    - Whether the response is grounded in the system prompt context
    """

    model: str = settings.EVALUATION_MODEL

    async def evaluate(
        self, ctx: EvaluatorContext[ChatbotInput, ChatbotOutput, Any]
    ) -> dict[str, Any]:
        prompt = f"""<user_input>{ctx.inputs.user_input}</user_input>
<chatbot_response>{ctx.output.chatbot_response}</chatbot_response>
<chatbot_system_prompt>{ctx.output.system_prompt}</chatbot_system_prompt>
<retrieved_tool_context>{ctx.output.retrieved_tool_context}</retrieved_tool_context>
<evaluation_criteria>{ctx.inputs.criteria}</evaluation_criteria>"""

        judge_agent = _get_chatbot_judge_agent(self.model)

        result, _ = await run_agent(
            agent=judge_agent,
            prompt=prompt,
            model_settings=ModelSettings(
                model=self.model,
                temperature=settings.EVALUATION_MODEL_TEMPERATURE,
                max_tokens=settings.EVALUATION_MODEL_MAX_TOKENS,
            ),
            system_prompt=CHATBOT_JUDGE_SYSTEM_PROMPT,
        )

        return {
            "passed": EvaluationReason(result.output.passed, result.output.reasoning),
            "follows_guidelines": result.output.follows_guidelines,
            "is_grounded": result.output.is_grounded,
        }


@dataclass
class MetricsEvaluator(Evaluator[ChatbotInput, ChatbotOutput, Any]):
    """Converts chatbot output metrics into eval scores."""

    async def evaluate(
        self, ctx: EvaluatorContext[ChatbotInput, ChatbotOutput, Any]
    ) -> dict[str, Any]:
        return {"guardrail_retries": float(ctx.output.guardrail_retries)}


# ============================================================================
# Test Cases
# ============================================================================


TEST_CASES = [
    ChatbotInput(
        test_case_id="public_ai_program_grounded_search",
        user_input="Do you have a bachelor's degree in artificial intelligence?",
        is_internal=False,
        criteria="""1. MUST answer as a public prospective-student assistant
2. MUST mention Artificial Intelligence, BS when source context supports it
3. MUST ground the answer in retrieved Demo University website or catalog context
4. SHOULD mention related technology options only when retrieved
5. MUST NOT expose training-material content or internal source mechanics""",
    ),
    ChatbotInput(
        test_case_id="public_transfer_credit_no_promise",
        user_input="I have credits from another college. Can you tell me if they all transfer?",
        is_internal=False,
        criteria="""1. MUST explain that official transfer-credit decisions require official transcript review
2. MAY say unofficial transcripts can support early advising
3. MUST NOT promise that all credits will transfer
4. MUST mention transcripts@demo-university.example.edu if giving transcript submission guidance
5. MUST NOT claim chat transcripts are sent to Admissions""",
    ),
    ChatbotInput(
        test_case_id="public_academic_policy_catalog_redirect",
        user_input="What is the withdrawal policy if I need to drop a course?",
        is_internal=False,
        criteria="""1. MUST direct the student to https://catalog.demo-university.example.edu/ as the source of truth for academic policies/procedures
2. MUST NOT summarize or interpret withdrawal-policy details
3. SHOULD be concise and helpful""",
    ),
    ChatbotInput(
        test_case_id="public_career_support_no_guarantee",
        user_input="Will Demo University guarantee me a job after the business degree?",
        is_internal=False,
        criteria="""1. MUST clearly state Demo University does not guarantee employment or job placement
2. SHOULD mention career preparation or Career Services support when grounded or prompt-supported
3. MUST NOT provide salary figures or guarantees
4. SHOULD ask which program/goal the student wants to discuss if more detail is needed""",
    ),
    ChatbotInput(
        test_case_id="internal_transfer_credit_training_priority",
        user_input="What should I tell a transfer student who only has unofficial transcripts right now?",
        criteria="""1. MUST treat the user as a staff member, not a prospective student
2. MUST use internal training-material guidance when available
3. MUST explain unofficial transcripts can support early advising but official transcripts are required for final transfer-credit evaluation
4. MUST mention transcripts@demo-university.example.edu if transcript submission is discussed
5. MUST NOT promise a transfer-credit outcome or completion date""",
    ),
    ChatbotInput(
        test_case_id="internal_financial_aid_no_award_promises",
        user_input="How should I answer a student who asks when they'll know their financial aid amount?",
        criteria="""1. MUST route exact eligibility, award amounts, documents, disbursement, or refund timing to Financial Aid
2. MUST NOT provide specific aid amounts or eligibility promises
3. SHOULD explain process/timing ownership using staff-facing language
4. SHOULD ground in the Financial Aid Conversation Guide when retrieved""",
    ),
    ChatbotInput(
        test_case_id="internal_academic_policies_catalog_source",
        user_input="Where should I direct a student for academic policies and appeal procedures?",
        criteria="""1. MUST direct staff to https://catalog.demo-university.example.edu/ as the source of truth
2. MUST NOT summarize, paraphrase, or interpret academic policy/procedure details
3. If returned as a complete staff-facing approved wording block, MUST quote it""",
    ),
    ChatbotInput(
        test_case_id="internal_mba_catalog_courses_with_urls",
        user_input="What courses are in the MBA catalog program?",
        criteria="""1. MUST use catalog program/course context
2. MUST mention Business Administration, MBA
3. MUST include core course codes such as BUS 520 and BUS 690 when retrieved
4. SHOULD include catalog course URLs or clearly cite catalog course/program sources
5. MUST avoid unsupported tuition or admission-requirement details""",
    ),
    ChatbotInput(
        test_case_id="internal_counseling_timeline_source_priority",
        user_input="Why is the Clinical Mental Health Counseling MS longer than a short certificate?",
        criteria="""1. MUST treat the user as staff
2. MUST mention the 60-credit curriculum when retrieved
3. MUST explain stable timeline factors such as graduate pacing, structured sequence, and field-experience readiness
4. SHOULD prefer current admissions guidance over public overview when both are available
5. MUST include licensure/state caution without unsupported state-specific conclusions""",
    ),
    ChatbotInput(
        test_case_id="internal_counseling_conflict_escalation",
        user_input="I see one counseling sheet says 180 practicum hours and another says 100. What should I tell staff?",
        criteria="""1. MUST acknowledge that internal documents conflict on the practicum-hour detail
2. MUST NOT present either 100 or 180 as the single settled answer without acknowledging conflict
3. MUST identify current admissions guidance as higher priority for talking points when retrieved
4. MUST include a Documents to verify section or equivalent
5. MUST advise verification/escalation with admissions operations or the program owner""",
    ),
    ChatbotInput(
        test_case_id="internal_laptop_and_accessibility_routing",
        user_input="A prospect says they don't have a reliable laptop and may need accommodations. What should I say?",
        criteria="""1. MUST tell staff to ask whether the student has regular access to a laptop or desktop and reliable internet
2. MUST distinguish technology planning from Accessibility Services accommodation review
3. MUST NOT promise a specific accommodation
4. SHOULD route login/platform issues to Help Desk if relevant""",
    ),
    ChatbotInput(
        test_case_id="internal_state_licensure_caution",
        user_input="Can I tell a counseling prospect this program meets licensure requirements in their state?",
        criteria="""1. MUST say licensure requirements vary by state
2. MUST direct staff to published state authorization/licensure disclosures or program-team verification
3. MUST NOT make an unsupported state-specific licensure conclusion
4. SHOULD mention Admissions can discuss the student's intended state and goals""",
    ),
]


# ============================================================================
# Task Function
# ============================================================================


async def run_chatbot(
    inputs: ChatbotInput, models: dict[str, str], session_factory: async_sessionmaker[AsyncSession]
) -> ChatbotOutput:
    """Call the chatbot and return response with context.

    Each run creates its own user, runs the chatbot, then rolls back.
    RAG data stays intact since it was committed separately.
    """
    chatbot_settings = ModelSettings(
        model=models["chatbot"],
        temperature=settings.CHATBOT_MODEL_TEMPERATURE,
        max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS,
    )
    guardrail_settings = ModelSettings(
        model=models["guardrail"],
        temperature=settings.GUARDRAIL_MODEL_TEMPERATURE,
        max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS,
    )

    async with session_factory() as session:
        # Create a unique test user for this run
        group = await get_group_for_slug(session, SystemGroupSlug.USER)
        test_user = User(
            id=uuid.uuid4(),
            email=f"test-{uuid.uuid4()}@example.com",
            name="Test User",
            password_hash="not-a-real-hash",  # noqa: S106
            is_active=True,
            group_id=group.id,
        )
        session.add(test_user)
        await session.flush()

        _, assistant_message = await handle_conversation_turn(
            project_name="test_project",
            conversation_id=None,
            parent_message_id=None,
            user_prompt=inputs.user_input,
            is_regeneration=False,
            chatbot_model_settings=chatbot_settings,
            guardrail_model_settings=guardrail_settings,
            user_id=test_user.id,
            session=session,
            tool_session_factory=session_factory,
            is_internal=inputs.is_internal,
            enable_guardrails=settings.ENABLE_GUARDRAILS,
            max_guardrails_retries=settings.MAX_GUARDRAILS_RETRIES,
        )

        assert isinstance(assistant_message, MessageOut)
        metadata: MessageMetadataOut | None = assistant_message.metadata

        output = ChatbotOutput(
            chatbot_response=assistant_message.content,
            system_prompt=metadata.system_prompt_rendered if metadata else "",
            retrieved_tool_context=format_retrieved_tool_context(
                metadata.tool_calls if metadata else None
            ),
            guardrail_retries=metadata.guardrail_retries if metadata else 0,
        )

        # Rollback - don't persist user/conversation data
        await session.rollback()

    return output


def _cases_from_config(config: EvalRunConfig) -> list[ChatbotInput]:
    if config.case_payloads is None:
        return list(TEST_CASES)
    return [
        ChatbotInput(**validate_eval_case_payload(EvalSuite.CHATBOT, payload))
        for payload in config.case_payloads
    ]


async def run_chatbot_evaluation(
    config: EvalRunConfig,
) -> EvaluationReport[ChatbotInput, ChatbotOutput, None]:
    """Run chatbot evals from shared config for pytest/API callers."""
    session_factory = config.session_factory
    model_overrides = config.model_overrides

    cases_to_run = _cases_from_config(config)
    if config.test_cases:
        selected_ids = set(config.test_cases)
        cases_to_run = [tc for tc in cases_to_run if tc.test_case_id in selected_ids]
        if not cases_to_run:
            raise ValueError(f"No matching test cases found for: {', '.join(config.test_cases)}")

    dataset: Dataset[ChatbotInput, ChatbotOutput, None] = Dataset(
        name="demo_va_chatbot_eval",
        cases=[Case(name=tc.test_case_id, inputs=tc) for tc in cases_to_run],
    )

    # Build model configs for reporting
    model_configs = {
        "chatbot": ModelConfig(
            model=model_overrides["chatbot"],
            temperature=settings.CHATBOT_MODEL_TEMPERATURE,
            max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS,
        ),
        "guardrail": ModelConfig(
            model=model_overrides["guardrail"],
            temperature=settings.GUARDRAIL_MODEL_TEMPERATURE,
            max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS,
        ),
        "judge": ModelConfig(
            model=model_overrides["evaluation"],
            temperature=settings.EVALUATION_MODEL_TEMPERATURE,
            max_tokens=settings.EVALUATION_MODEL_MAX_TOKENS,
        ),
    }

    additional_settings = {
        "enable_guardrails": settings.ENABLE_GUARDRAILS,
        "max_guardrails_retries": settings.MAX_GUARDRAILS_RETRIES,
    }

    return await evaluate(
        dataset,
        lambda inputs: run_chatbot(inputs, model_overrides, session_factory),
        evaluators=[ChatbotJudge(model=model_overrides["evaluation"]), MetricsEvaluator()],
        repeats=config.repeat,
        max_concurrency=config.max_concurrency,
        model_configs=model_configs,
        additional_settings=additional_settings,
        progress_handler=config.progress_handler,
    )


def assert_report_meets_threshold(
    report: EvaluationReport[ChatbotInput, ChatbotOutput, None], pass_threshold: float
) -> None:
    """Assert each case meets the configured pass threshold."""
    failed = [
        c for c in report.cases if c.stats.assertion_pass_rates.get("passed", 0) < pass_threshold
    ]
    if failed:
        summary = "\n".join(
            f"  {c.name}: {c.stats.assertion_pass_rates.get('passed', 0):.0%} "
            f"(threshold: {pass_threshold:.0%})"
            for c in failed
        )
        raise AssertionError(
            f"Failed {len(failed)}/{len(report.cases)} cases "
            f"(threshold: {pass_threshold:.0%}):\n{summary}"
        )
