"""Shared eval runtime models and helpers for CLI pytest and API callers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class EvalSuite(StrEnum):
    """Supported chat eval suites."""

    CHATBOT = "chatbot"
    GUARDRAILS = "guardrails"


EvalProgressHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class EvalRunRequestConfig:
    """Eval run request options before a guarded database session is prepared."""

    suite: EvalSuite
    repeat: int = 1
    max_concurrency: int = 5
    test_cases: tuple[str, ...] = ()
    case_payloads: tuple[dict[str, Any], ...] | None = None
    pass_threshold: float = 0.9
    rebuild_rag: bool = False
    chatbot_model: str | None = None
    guardrail_model: str | None = None
    evaluation_model: str | None = None


@dataclass(frozen=True)
class EvalRunConfig:
    """Configuration for one eval run with an explicit guarded database session factory."""

    session_factory: async_sessionmaker[AsyncSession]
    suite: EvalSuite
    repeat: int = 1
    max_concurrency: int = 5
    test_cases: tuple[str, ...] = ()
    case_payloads: tuple[dict[str, Any], ...] | None = None
    pass_threshold: float = 0.9
    rebuild_rag: bool = False
    chatbot_model: str | None = None
    guardrail_model: str | None = None
    evaluation_model: str | None = None
    progress_handler: EvalProgressHandler | None = None

    @property
    def model_overrides(self) -> dict[str, str]:
        """Resolved role->model mapping for eval execution and reports."""
        return {
            "chatbot": self.chatbot_model or settings.CHATBOT_MODEL,
            "guardrail": self.guardrail_model or settings.GUARDRAIL_MODEL,
            "evaluation": self.evaluation_model or settings.EVALUATION_MODEL,
        }


def parse_test_cases_filter(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated test-case filter."""
    if value is None or value.strip() == "":
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip() != "")
