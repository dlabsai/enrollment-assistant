"""Deterministic token-free PydanticAI models for isolated stress environments."""

from __future__ import annotations

import asyncio
import itertools
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from app.core.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_STRESS_MODEL_PREFIX = "stress/"
_PROFILE_PATTERN = re.compile(r"\[stress-profile:(\d+)]")
_PROFILE_PATH = Path(__file__).parent / "profiles" / "synthetic_chat_timings.json"
_PROFILE_MODEL_PARTS = 2
_PROFILE_FIELD_BY_ROLE = {
    "chatbot": "chatbot_ms",
    "guardrail": "guardrail_ms",
    "grounding": "grounding_ms",
}
_TOOL_ARGUMENTS: dict[str, dict[str, object]] = {
    "retrieve_documents": {"website_page_ids": [1006]},
    "list_website_programs": {},
    "list_catalog_courses_for_program": {"program_id": 1},
}
_fallback_profile_counter = itertools.count()


def _load_profiles() -> tuple[dict[str, object], ...]:
    payload: object = json.loads(_PROFILE_PATH.read_text())
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("stress timing profile must be a non-empty JSON array")
    profiles: list[dict[str, object]] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise TypeError("stress timing profile entries must be JSON objects")
        profiles.append(cast(dict[str, object], item))
    return tuple(profiles)


_PROFILES = _load_profiles()


def _profile_index(messages: list[ModelMessage]) -> int:
    match = _PROFILE_PATTERN.search(repr(messages))
    if match is not None:
        return int(match.group(1)) % len(_PROFILES)
    return next(_fallback_profile_counter) % len(_PROFILES)


def _profile_number(profile: dict[str, object], field: str) -> float:
    value = profile.get(field, 0)
    return float(value) if isinstance(value, int | float) else 0.0


def _profile_tool_names(profile: dict[str, object]) -> tuple[str, ...]:
    value = profile.get("tool_names", [])
    if not isinstance(value, list):
        return ()
    return tuple(item for item in cast(list[object], value) if isinstance(item, str))


def _tool_arguments(tool_name: str, profile_index: int) -> dict[str, object]:
    query = f"admissions stress profile {profile_index}"
    if tool_name == "find_document_chunks":
        return {"content_search_query": query}
    if tool_name == "find_document_titles":
        return {"title_search_query": query}
    return _TOOL_ARGUMENTS[tool_name]


class _ProfiledTestModel(TestModel):
    def __init__(
        self,
        *,
        role: str,
        fixed_profile_index: int | None,
        custom_output_text: str | None = None,
        custom_output_args: Any | None = None,
    ) -> None:
        super().__init__(
            call_tools=[],
            custom_output_text=custom_output_text,
            custom_output_args=custom_output_args,
            model_name=f"stress-{role}",
        )
        self._stress_role = role
        self._fixed_profile_index = fixed_profile_index

    def _stress_profile_index(self, messages: list[ModelMessage]) -> int:
        profile_index = (
            self._fixed_profile_index
            if self._fixed_profile_index is not None
            else _profile_index(messages)
        )
        return profile_index % len(_PROFILES)

    def _stress_profile(self, messages: list[ModelMessage]) -> dict[str, object]:
        return _PROFILES[self._stress_profile_index(messages)]

    async def _apply_profile_delay(self, messages: list[ModelMessage]) -> None:
        profile_index = self._stress_profile_index(messages)
        profile = _PROFILES[profile_index]
        field = _PROFILE_FIELD_BY_ROLE.get(self._stress_role)
        delay_ms = _profile_number(profile, field) if field is not None else 0.0
        if self._stress_role == "chatbot" and settings.STRESS_FAKE_TOOLS:
            delay_ms /= len(_profile_tool_names(profile)) + 1
        delay_ms *= max(0.0, settings.STRESS_FAKE_LATENCY_SCALE)

        if settings.STRESS_FAKE_LLM_URL:
            from app.stress.http_client import request_fake_llm_round  # noqa: PLC0415

            await request_fake_llm_round(
                role=self._stress_role, profile_index=profile_index, delay_ms=delay_ms
            )
        elif delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)

    def _request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        if self._stress_role == "chatbot" and settings.STRESS_FAKE_TOOLS:
            profile_tools = _profile_tool_names(self._stress_profile(messages))
            completed_tools = sum(
                isinstance(part, ToolReturnPart)
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
            )
            if completed_tools < len(profile_tools):
                available_tools = {tool.name for tool in model_request_parameters.function_tools}
                requested_name = profile_tools[completed_tools]
                tool_name = (
                    requested_name if requested_name in available_tools else "find_document_chunks"
                )
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name,
                            _tool_arguments(tool_name, self._stress_profile_index(messages)),
                            tool_call_id=f"stress_tool_{completed_tools}",
                        )
                    ],
                    model_name=self._model_name,
                )
        return super()._request(messages, model_settings, model_request_parameters)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        await self._apply_profile_delay(messages)
        return await super().request(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        await self._apply_profile_delay(messages)
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as response:
            yield response


def create_stress_model(model_name: str) -> Model:
    """Create a role-specific fake model, refusing activation in production."""
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("stress fake models are forbidden when ENVIRONMENT=production")
    if not model_name.startswith(_STRESS_MODEL_PREFIX):
        raise ValueError(f"not a stress model name: {model_name}")

    role_parts = model_name.removeprefix(_STRESS_MODEL_PREFIX).split("/")
    role = role_parts[0]
    try:
        fixed_profile_index = (
            int(role_parts[1]) if len(role_parts) == _PROFILE_MODEL_PARTS else None
        )
    except ValueError as exc:
        raise ValueError(f"invalid stress profile index in model name: {model_name}") from exc
    if len(role_parts) > _PROFILE_MODEL_PARTS:
        raise ValueError(f"invalid stress model name: {model_name}")

    if role == "chatbot":
        return _ProfiledTestModel(
            role=role,
            fixed_profile_index=fixed_profile_index,
            custom_output_text="Hello! How can I help you today?",
        )
    if role == "guardrail":
        return _ProfiledTestModel(
            role=role,
            fixed_profile_index=fixed_profile_index,
            custom_output_args={"is_valid": True, "feedback": None},
        )
    if role == "grounding":
        return _ProfiledTestModel(
            role=role,
            fixed_profile_index=fixed_profile_index,
            custom_output_args={"grounding_source_keys": [], "canned_response_groundings": []},
        )
    if role == "extractor":
        return _ProfiledTestModel(
            role=role,
            fixed_profile_index=fixed_profile_index,
            custom_output_args={
                "user_degree_program_of_interest": None,
                "user_is_military_affiliated": None,
                "user_wants_to_study_on_campus": None,
                "program_type": None,
            },
        )
    if role == "summary":
        return _ProfiledTestModel(
            role=role,
            fixed_profile_index=fixed_profile_index,
            custom_output_text="Stress test conversation",
        )
    raise ValueError(f"unknown stress model role: {role}")
