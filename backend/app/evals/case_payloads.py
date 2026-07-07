"""Suite-specific eval test-case payload validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.evals.runtime import EvalSuite

_FORBIDDEN_CASE_ID_CHARS = (",", "/", "\\")


class EvalCasePayloadError(ValueError):
    """Raised when a case payload is invalid for its suite."""


class _CasePayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_case_id: str = Field(min_length=1, max_length=255)
    criteria: str = Field(min_length=1)

    @field_validator("test_case_id")
    @classmethod
    def _case_id_is_safe(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("test_case_id is required")
        invalid_chars = [char for char in _FORBIDDEN_CASE_ID_CHARS if char in stripped]
        if invalid_chars:
            chars = " ".join(repr(char) for char in invalid_chars)
            raise ValueError(f"test_case_id cannot contain {chars}")
        return stripped

    @field_validator("criteria")
    @classmethod
    def _criteria_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("criteria is required")
        return stripped


class ChatbotEvalCasePayload(_CasePayloadBase):
    """Editable payload for one chatbot eval case."""

    user_input: str = Field(min_length=1)
    is_internal: bool = True

    @field_validator("user_input")
    @classmethod
    def _user_input_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("user_input is required")
        return stripped


class GuardrailsEvalCasePayload(_CasePayloadBase):
    """Editable payload for one guardrails eval case."""

    chatbot_response: str = Field(min_length=1)
    expected_valid: bool

    @field_validator("chatbot_response")
    @classmethod
    def _chatbot_response_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("chatbot_response is required")
        return stripped


def validate_eval_case_payload(
    suite: EvalSuite, payload: dict[str, Any], *, expected_case_id: str | None = None
) -> dict[str, Any]:
    """Validate and normalize editable case JSON for a suite."""
    model_type: type[BaseModel]
    if suite is EvalSuite.CHATBOT:
        model_type = ChatbotEvalCasePayload
    elif suite is EvalSuite.GUARDRAILS:
        model_type = GuardrailsEvalCasePayload
    else:
        raise EvalCasePayloadError(f"Unsupported eval suite: {suite.value}")

    try:
        model = model_type.model_validate(payload)
    except ValidationError as error:
        raise EvalCasePayloadError(str(error)) from error

    normalized = model.model_dump(mode="json")
    if expected_case_id is not None and normalized["test_case_id"] != expected_case_id:
        raise EvalCasePayloadError("Payload test_case_id must match the selected case id")
    return normalized
