from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID  # noqa: TC003 - Pydantic resolves runtime annotations.

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewState(StrEnum):
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class DecisionState(StrEnum):
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class FindingCategory(StrEnum):
    INAPPROPRIATE = "inappropriate"
    MISINFORMATION = "misinformation"
    REGULATORY_COMPLIANCE = "regulatory_compliance"
    REPUTATION_RISK = "reputation_risk"
    CONFIDENTIALITY = "confidentiality"


class InstructionsSummary(BaseModel):
    id: UUID
    number: int
    created_at: datetime
    author: str


class InstructionsDetail(InstructionsSummary):
    content: str


class InstructionsPage(BaseModel):
    current: InstructionsDetail | None
    versions: list[InstructionsSummary]
    total: int


class SaveInstructions(BaseModel):
    base_version_id: UUID | None = None
    content: str | None = Field(default=None, min_length=1, max_length=30000)
    restore_from_id: UUID | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.content is None) == (self.restore_from_id is None):
            raise ValueError("Supply new instructions or select a version to restore, not both.")
        if self.content is not None and not self.content.strip():
            raise ValueError("Write the screening instructions before saving.")
        return self


class ScreeningPeriod(BaseModel):
    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.start > self.end:
            raise ValueError("The end of the period must be after its start.")
        return self


class StartScreening(ScreeningPeriod):
    id: UUID
    instructions_version_id: UUID
    acknowledge_overlap: bool = False


class Overlap(BaseModel):
    id: UUID
    created_at: datetime


class Preview(BaseModel):
    messages: int
    conversations: int
    max_messages: int
    instructions: InstructionsSummary | None
    overlaps: list[Overlap]
    worker_enabled: bool


class ScreeningSummary(BaseModel):
    id: UUID
    created_at: datetime
    author: str
    start: datetime
    end: datetime
    instructions_version_id: UUID
    admission_error: str | None
    messages: int
    conversations: int
    screened: int
    screened_conversations: int
    pending: int
    errors: int
    error_conversations: int
    deleted: int
    findings: int
    needs_review: int


class ScreeningsPage(BaseModel):
    items: list[ScreeningSummary]
    total: int


class ScreeningFailure(BaseModel):
    chat_id: UUID
    chat: str
    assistant_messages: int
    reason: str
    retryable: bool


class ScreeningDetail(ScreeningSummary):
    instructions: InstructionsDetail
    failures: list[ScreeningFailure]


class FlagSummary(BaseModel):
    id: UUID
    title: str
    categories: list[FindingCategory] | None = Field(min_length=1, max_length=5)
    chat: str
    message_at: datetime
    state: ReviewState


class FlagsPage(BaseModel):
    items: list[FlagSummary]
    total: int


class DecisionOut(BaseModel):
    state: DecisionState
    comment: str | None
    reviewer: str
    created_at: datetime
    revision: int


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: DecisionState
    comment: str | None = Field(default=None, max_length=4000)
    expected_revision: int = Field(ge=0)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class FindingOut(BaseModel):
    id: UUID
    title: str
    categories: list[FindingCategory] | None = Field(min_length=1, max_length=5)
    explanation: str
    evidence: str
    state: ReviewState
    revision: int
    decisions: list[DecisionOut]


class TranscriptMessage(BaseModel):
    id: UUID
    parent_id: UUID | None
    role: str
    content: str
    created_at: datetime


class FlagDetail(BaseModel):
    chat: str
    message_id: UUID
    message_at: datetime
    error: str | None
    transcript: list[TranscriptMessage]
    flag: FindingOut | None
