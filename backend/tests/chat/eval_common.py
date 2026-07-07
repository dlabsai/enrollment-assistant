"""Common evaluation utilities for LLM agent tests.

This module provides shared infrastructure for running LLM-based evaluations
with the evaluation framework. It includes:
- Common input/output dataclasses
- LLM judge evaluator for assessing agent responses
- Test runner utilities
"""

# ruff: noqa: E501

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.chat.agents import get_pydantic_ai_model_name
from app.chat.engine_utils import ModelSettings, run_agent
from app.core.config import settings
from app.evals import EvaluationReason, Evaluator, EvaluatorContext

# ============================================================================
# Common Models
# ============================================================================


class JudgeResult(BaseModel):
    """Structured output from the LLM judge."""

    reasoning: str = Field(description="Explanation of the evaluation.")
    follows_guidelines: bool = Field(description="True if response follows all criteria.")
    is_grounded: bool = Field(description="True if response is grounded in context.")
    passed: bool = Field(description="True if response follows guidelines AND is grounded.")


# ============================================================================
# Common Inputs/Outputs
# ============================================================================


@dataclass
class AgentInput:
    """Common input for agent evaluation."""

    user_input: str
    criteria: str
    test_case_id: str


@dataclass
class AgentOutput:
    """Common output from agent evaluation."""

    agent_response: str
    system_prompt: str


# ============================================================================
# LLM Judge Evaluator
# ============================================================================


JUDGE_SYSTEM_PROMPT = """You are an expert evaluator for a university chatbot system.

You will receive:
- <user_input>: The user's message to the agent
- <agent_response>: The agent's final response to evaluate
- <agent_system_prompt>: The system prompt that was used to generate the response (contains rules, context, etc.)
- <evaluation_criteria>: Specific criteria to check

## follows_guidelines
- Check EACH numbered criterion explicitly against the ACTUAL text in <agent_response>
- Be literal and strict about requirements
- Check rules defined in <agent_system_prompt>
- IMPORTANT: Only evaluate the literal content of <agent_response>

## is_grounded
The response should only contain information from:
- The rules and instructions in <agent_system_prompt>
- Any context or data provided within <agent_system_prompt>
- The user's own message

## passed
True ONLY if both follows_guidelines AND is_grounded are True."""


def create_judge_agent() -> Agent[None, JudgeResult]:
    """Create the LLM judge agent for evaluating responses."""
    return Agent(
        get_pydantic_ai_model_name(settings.EVALUATION_MODEL),
        output_type=JudgeResult,
        system_prompt=JUDGE_SYSTEM_PROMPT,
    )


# Create judge agent once at module level to avoid httpx client cleanup issues
_judge_agent: Agent[None, JudgeResult] = create_judge_agent()


@dataclass
class LLMJudgeEvaluator(Evaluator[AgentInput, AgentOutput, Any]):
    """LLM judge evaluator for agent responses.

    This evaluator uses an LLM to assess whether agent responses:
    1. Follow the specified guidelines/criteria
    2. Are grounded in the provided context

    Attributes:
        model: The model to use for evaluation (default: settings.EVALUATION_MODEL)

    """

    model: str = settings.EVALUATION_MODEL

    async def evaluate(self, ctx: EvaluatorContext[AgentInput, AgentOutput, Any]) -> dict[str, Any]:
        prompt = f"""<user_input>{ctx.inputs.user_input}</user_input>
<agent_response>{ctx.output.agent_response}</agent_response>
<agent_system_prompt>{ctx.output.system_prompt}</agent_system_prompt>
<evaluation_criteria>{ctx.inputs.criteria}</evaluation_criteria>"""

        result, _ = await run_agent(
            agent=_judge_agent,
            prompt=prompt,
            model_settings=ModelSettings(
                model=self.model,
                temperature=settings.EVALUATION_MODEL_TEMPERATURE,
                max_tokens=settings.EVALUATION_MODEL_MAX_TOKENS,
            ),
            system_prompt=JUDGE_SYSTEM_PROMPT,
        )

        return {
            "passed": EvaluationReason(result.output.passed, result.output.reasoning),
            "follows_guidelines": result.output.follows_guidelines,
            "is_grounded": result.output.is_grounded,
        }


# ============================================================================
# Model Config Builder
# ============================================================================


def get_evaluation_model_configs() -> dict[str, Any]:
    """Get common model configs for evaluations."""
    from app.evals import ModelConfig

    return {
        "judge": ModelConfig(
            model=settings.EVALUATION_MODEL,
            temperature=settings.EVALUATION_MODEL_TEMPERATURE,
            max_tokens=settings.EVALUATION_MODEL_MAX_TOKENS,
        )
    }
