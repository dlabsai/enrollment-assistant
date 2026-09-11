import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.compliance import screener
from app.compliance.schemas import ScreeningPeriod, TranscriptMessage
from app.compliance.screener import Concern, ScreeningResult, validate_result
from app.compliance.sources import ScreeningUnavailableError, display_content
from app.models import Message

RULE = "Do not promise admission."
MESSAGE = "🎓 Admission is guaranteed."
MESSAGE_ID = uuid4()


def concern(message_id: UUID = MESSAGE_ID) -> Concern:
    return Concern(
        message_id=message_id,
        title="Possible promise",
        explanation=(
            "The admission guarantee conflicts with the instruction not to promise admission."
        ),
        message_quote="Admission is guaranteed.",
        instruction_quote=RULE,
    )


def test_screener_requires_complete_exact_target_and_instruction_evidence() -> None:
    other_id = uuid4()
    result = validate_result(
        ScreeningResult(complete=True, findings=[concern(), concern(), concern(other_id)]),
        instructions=RULE,
        target_messages={MESSAGE_ID: MESSAGE, other_id: MESSAGE},
    )
    assert [finding.message_id for finding in result] == [MESSAGE_ID, other_id]
    assert MESSAGE[result[0].evidence_start : result[0].evidence_end] == "Admission is guaranteed."
    with pytest.raises(ScreeningUnavailableError, match="incomplete"):
        validate_result(
            ScreeningResult(complete=False, findings=[]),
            instructions=RULE,
            target_messages={MESSAGE_ID: MESSAGE},
        )
    with pytest.raises(ScreeningUnavailableError, match="invalid_evidence"):
        validate_result(
            ScreeningResult(complete=True, findings=[concern()]),
            instructions=RULE,
            target_messages={MESSAGE_ID: "Admission is NOT guaranteed."},
        )
    with pytest.raises(ScreeningUnavailableError, match="invalid_evidence"):
        validate_result(
            ScreeningResult(complete=True, findings=[concern()]),
            instructions="A different rule.",
            target_messages={MESSAGE_ID: MESSAGE},
        )
    with pytest.raises(ScreeningUnavailableError, match="invalid_evidence"):
        validate_result(
            ScreeningResult(complete=True, findings=[concern()]),
            instructions=RULE,
            target_messages={MESSAGE_ID: MESSAGE + MESSAGE},
        )
    with pytest.raises(ScreeningUnavailableError, match="invalid_evidence"):
        validate_result(
            ScreeningResult(complete=True, findings=[concern(other_id)]),
            instructions=RULE,
            target_messages={MESSAGE_ID: MESSAGE},
        )


def test_blocked_screening_use_only_historical_visible_content() -> None:
    blocked = Message(
        role="assistant",
        content="RAW UNSAFE RESPONSE",
        guardrails_blocked=True,
        guardrails_blocked_message="I cannot help with that.",
    )
    assert display_content(blocked) == "I cannot help with that."
    blocked.guardrails_blocked_message = None
    with pytest.raises(ScreeningUnavailableError, match="missing_display"):
        display_content(blocked)


@pytest.mark.asyncio
async def test_screener_sends_complete_tree_and_attributes_findings_to_selected_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_id, original_id, alternative_id, clarification_id = (uuid4() for _ in range(4))
    transcript = [
        TranscriptMessage(
            id=question_id,
            parent_id=None,
            role="user",
            content="Can admission be promised?",
            created_at=datetime.now(UTC),
        ),
        TranscriptMessage(
            id=original_id,
            parent_id=question_id,
            role="assistant",
            content=MESSAGE,
            created_at=datetime.now(UTC),
        ),
        TranscriptMessage(
            id=alternative_id,
            parent_id=question_id,
            role="assistant",
            content=MESSAGE,
            created_at=datetime.now(UTC),
        ),
        TranscriptMessage(
            id=clarification_id,
            parent_id=original_id,
            role="assistant",
            content="Correction: admission is not guaranteed.",
            created_at=datetime.now(UTC),
        ),
    ]
    targets = [original_id, alternative_id]

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        inputs = [
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        assert len(inputs) == 1
        assert isinstance(inputs[0], str)
        assert json.loads(inputs[0]) == {
            "screening_instructions": RULE,
            "target_message_ids": [str(id_) for id_ in targets],
            "conversation_context": [message.model_dump(mode="json") for message in transcript],
        }
        # A controlled result verifies attribution, not the model's legal interpretation.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "complete": True,
                        "findings": [concern(alternative_id).model_dump(mode="json")],
                    },
                )
            ]
        )

    def get_model(_name: str) -> FunctionModel:
        return FunctionModel(respond)

    monkeypatch.setattr(screener, "get_pydantic_ai_model_name", get_model)
    result = await screener.screen_conversation(
        instructions=RULE,
        transcript=transcript,
        target_message_ids=targets,
        model_name="azure/gpt-5.5",
        max_tokens=4096,
        max_input_characters=10000,
    )
    assert len(result) == 1
    assert result[0].message_id == alternative_id
    with pytest.raises(ScreeningUnavailableError, match="too_long"):
        await screener.screen_conversation(
            instructions=RULE,
            transcript=transcript,
            target_message_ids=targets,
            model_name="azure/gpt-5.5",
            max_tokens=4096,
            max_input_characters=10,
        )


def test_period_requires_unambiguous_ordered_dates() -> None:
    normalized = ScreeningPeriod.model_validate(
        {"start": "2026-09-01T00:00:00-04:00", "end": "2026-09-02T00:00:00-04:00"}
    )
    assert normalized.start == datetime(2026, 9, 1, 4, tzinfo=UTC)
    assert normalized.end == datetime(2026, 9, 2, 4, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone"):
        ScreeningPeriod.model_validate(
            {"start": "2026-09-01T00:00:00", "end": "2026-09-02T00:00:00"}
        )
    with pytest.raises(ValueError, match="end of the period"):
        ScreeningPeriod(
            start=datetime(2026, 9, 2, tzinfo=UTC), end=datetime(2026, 9, 1, tzinfo=UTC)
        )
