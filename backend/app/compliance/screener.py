from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - Pydantic resolves runtime annotations.

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.usage import UsageLimits

from app.chat.agents import get_pydantic_ai_model_name

from .schemas import FindingCategory
from .sources import ScreeningUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .schemas import TranscriptMessage

SCREENING_VERSION = "5"
OUTPUT_TOKENS = 8192


class Concern(BaseModel):
    message_id: UUID
    title: str = Field(min_length=1, max_length=240)
    categories: list[FindingCategory] = Field(min_length=1, max_length=5)
    explanation: str = Field(min_length=1, max_length=4000)
    message_quote: str = Field(min_length=1, max_length=10000)
    instruction_quote: str = Field(min_length=1, max_length=10000)


class ScreeningResult(BaseModel):
    complete: bool
    findings: list[Concern] = Field(max_length=20)


@dataclass(frozen=True)
class ValidatedConcern:
    message_id: UUID
    title: str
    categories: tuple[FindingCategory, ...]
    explanation: str
    evidence_start: int
    evidence_end: int
    instruction_start: int
    instruction_end: int


def _span(source: str, quote: str) -> tuple[int, int]:
    start = source.find(quote)
    if not quote.strip() or start < 0 or source.find(quote, start + 1) != -1:
        raise ScreeningUnavailableError("invalid_evidence")
    return start, start + len(quote)


def validate_result(
    result: ScreeningResult, *, instructions: str, target_messages: Mapping[UUID, str]
) -> list[ValidatedConcern]:
    if not result.complete:
        raise ScreeningUnavailableError("incomplete")
    concerns: dict[tuple[UUID, int, int, int, int], ValidatedConcern] = {}
    for finding in result.findings:
        if finding.message_id not in target_messages:
            raise ScreeningUnavailableError("invalid_evidence")
        evidence_start, evidence_end = _span(
            target_messages[finding.message_id], finding.message_quote
        )
        instruction_start, instruction_end = _span(instructions, finding.instruction_quote)
        key = (finding.message_id, evidence_start, evidence_end, instruction_start, instruction_end)
        categories = tuple(
            category for category in FindingCategory if category in finding.categories
        )
        existing = concerns.get(key)
        if existing is not None:
            concerns[key] = replace(
                existing,
                categories=tuple(
                    category
                    for category in FindingCategory
                    if category in existing.categories or category in categories
                ),
            )
            continue
        concerns[key] = ValidatedConcern(
            message_id=finding.message_id,
            title=finding.title,
            categories=categories,
            explanation=finding.explanation,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
            instruction_start=instruction_start,
            instruction_end=instruction_end,
        )
    return list(concerns.values())


def _screening_input(
    *, instructions: str, transcript: Sequence[TranscriptMessage], target_message_ids: set[UUID]
) -> str:
    messages: list[str] = []
    for message in transcript:
        messages.append(
            "\n".join(
                [
                    "--- message ---",
                    f"id: {message.id}",
                    f"parent_id: {message.parent_id or 'none'}",
                    f"role: {message.role}",
                    f"created_at: {message.created_at.isoformat()}",
                    f"target: {'true' if message.id in target_message_ids else 'false'}",
                    "text:",
                    message.content,
                ]
            )
        )
    return (
        f"<lawyer_instructions>\n{instructions}\n</lawyer_instructions>\n\n"
        f"<transcript>\n{'\n\n'.join(messages)}\n</transcript>"
    )


async def screen_conversation(
    *,
    instructions: str,
    agent_prompt: str,
    transcript: Sequence[TranscriptMessage],
    target_message_ids: Sequence[UUID],
    model_name: str,
    max_tokens: int,
    max_input_characters: int,
) -> list[ValidatedConcern]:
    target_ids = set(target_message_ids)
    targets = {
        message.id: message.content
        for message in transcript
        if message.id in target_ids and message.role == "assistant"
    }
    if not targets or targets.keys() != target_ids:
        raise ScreeningUnavailableError("invalid_context")
    screening_input = _screening_input(
        instructions=instructions, transcript=transcript, target_message_ids=target_ids
    )
    if len(screening_input) > max_input_characters:
        raise ScreeningUnavailableError("too_long")
    # Call the agent directly: the chat run_agent helper records content-bearing spans.
    model_settings = OpenAIResponsesModelSettings(max_tokens=max_tokens, openai_store=False)
    if "gpt-5" in model_name:
        model_settings["thinking"] = "low"
    else:
        model_settings["temperature"] = 0.0
    agent: Agent[None, ScreeningResult] = Agent(
        get_pydantic_ai_model_name(model_name),
        output_type=ScreeningResult,
        system_prompt=f"{agent_prompt}\n\n{screening_input}",
        retries=1,
        model_settings=model_settings,
    )
    agent.instrument = False
    result = await agent.run(usage_limits=UsageLimits(request_limit=2))
    return validate_result(result.output, instructions=instructions, target_messages=targets)
