from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.message_sources import (
    CANNED_RESPONSE_SOURCE_TYPE,
    GroundingSourceSelection,
    MessageSourceUsed,
    build_canned_response_source,
    grounding_selection_key,
    is_canned_response_source,
    message_source_type_value,
)
from app.chat.agents import GroundingAgentResult, create_grounding_agent
from app.chat.config import TEMPLATES_DIR
from app.chat.engine_utils import ModelSettings, run_agent
from app.chat.template_utils import get_runtime_jinja_environment
from app.core.config import settings
from app.models import AssistantMessageMetadata, Message, PromptSetScope

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

GROUNDING_SOURCE_STATUS_PENDING = "pending"
GROUNDING_SOURCE_STATUS_SELECTED = "selected"
GROUNDING_SOURCE_STATUS_NO_SELECTION = "no_selection"


def _source_prompt_payload(sources: Sequence[MessageSourceUsed]) -> list[dict[str, Any]]:
    return [
        {
            "key": source.key,
            "title": source.title,
            "url": source.url,
            "type": message_source_type_value(source.type),
            "tool_name": source.tool_name,
            "search_query": source.search_query,
            "snippet": source.chunk,
        }
        for source in sources
    ]


def _canned_response_selection(
    *, index: int, title: str | None = None, explanation: str | None = None
) -> dict[str, Any]:
    source = build_canned_response_source(index=index, title=title, explanation=explanation)
    return {
        "key": source.key,
        "type": CANNED_RESPONSE_SOURCE_TYPE,
        "id": source.id,
        "title": source.title,
        "explanation": source.explanation,
    }


def _canned_response_selections_from_result(
    result: GroundingAgentResult, *, canned_candidate_selected: bool
) -> list[dict[str, Any]]:
    selections: list[dict[str, Any]] = []
    for index, grounding in enumerate(result.canned_response_groundings):
        title = grounding.title.strip()
        explanation = grounding.explanation.strip()
        selections.append(
            _canned_response_selection(
                index=index, title=title or None, explanation=explanation or None
            )
        )
    if not selections and canned_candidate_selected:
        selections.append(_canned_response_selection(index=0))
    return selections


def _tool_calls_prompt_payload(tool_calls: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(tool_calls or [])


def _build_selection_prompt(
    *,
    user_question: str,
    assistant_answer: str,
    chatbot_system_prompt: str | None,
    sources: Sequence[MessageSourceUsed],
    tool_calls: Sequence[dict[str, Any]] | None,
    required_grounding_source_keys: Sequence[str],
) -> str:
    sources_json = json.dumps(_source_prompt_payload(sources), ensure_ascii=False, indent=2)
    required_keys_json = json.dumps(
        list(required_grounding_source_keys), ensure_ascii=False, indent=2
    )
    tool_calls_json = json.dumps(
        _tool_calls_prompt_payload(tool_calls), ensure_ascii=False, indent=2
    )
    return "\n".join(
        [
            "User question:",
            user_question,
            "",
            "Assistant answer:",
            assistant_answer,
            "",
            "Chatbot system prompt:",
            chatbot_system_prompt or "",
            "",
            "Candidate sources JSON:",
            sources_json,
            "",
            "Required grounding source keys JSON:",
            required_keys_json,
            "",
            "All tool calls and tool results JSON:",
            tool_calls_json,
        ]
    )


def _exact_answer_url_source_keys(
    *, assistant_answer: str, sources: Sequence[MessageSourceUsed]
) -> list[str]:
    source_by_deduplication_key: dict[tuple[str, int, str], MessageSourceUsed] = {}
    positions_by_deduplication_key: dict[tuple[str, int, str], int] = {}
    for source in sources:
        if source.url.strip() == "":
            continue
        position = assistant_answer.find(source.url)
        if position >= 0:
            deduplication_key = (message_source_type_value(source.type), source.id, source.url)
            current = source_by_deduplication_key.get(deduplication_key)
            if current is None or (
                current.usage != "retrieved_by_id" and source.usage == "retrieved_by_id"
            ):
                source_by_deduplication_key[deduplication_key] = source
            positions_by_deduplication_key[deduplication_key] = min(
                positions_by_deduplication_key.get(deduplication_key, position), position
            )

    return [
        source_by_deduplication_key[deduplication_key].key
        for deduplication_key, _ in sorted(
            positions_by_deduplication_key.items(), key=lambda item: item[1]
        )
    ]


async def select_grounding_source_keys(
    *,
    user_question: str,
    assistant_answer: str,
    sources: Sequence[MessageSourceUsed],
    chatbot_system_prompt: str | None = None,
    tool_calls: Sequence[dict[str, Any]] | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> list[GroundingSourceSelection]:
    if not sources:
        return []

    exact_url_keys = _exact_answer_url_source_keys(
        assistant_answer=assistant_answer, sources=sources
    )
    prompt = _build_selection_prompt(
        user_question=user_question,
        assistant_answer=assistant_answer,
        chatbot_system_prompt=chatbot_system_prompt,
        sources=sources,
        tool_calls=tool_calls,
        required_grounding_source_keys=exact_url_keys,
    )
    model_settings = ModelSettings(
        model=settings.GROUNDING_MODEL,
        temperature=0.0,
        max_tokens=0,
        reasoning_effort=settings.GROUNDING_REASONING_EFFORT,
    )
    jinja_env = await get_runtime_jinja_environment(
        TEMPLATES_DIR, is_internal=True, scope=PromptSetScope.GROUNDING
    )
    system_prompt = jinja_env.get_template("grounding_agent.j2").render()
    result, _ = await run_agent(
        create_grounding_agent(model_settings.model, system_prompt),
        prompt,
        model_settings,
        metadata=trace_metadata,
        agent_name="grounding",
        system_prompt=system_prompt,
    )
    valid_source_by_key = {source.key: source for source in sources}
    selected: list[GroundingSourceSelection] = []
    seen: set[str] = set()
    has_canned_candidate = any(is_canned_response_source(source) for source in sources)
    canned_candidate_selected = has_canned_candidate and any(
        key in valid_source_by_key and is_canned_response_source(valid_source_by_key[key])
        for key in result.output.grounding_source_keys
    )
    canned_selections = (
        _canned_response_selections_from_result(
            result.output, canned_candidate_selected=canned_candidate_selected
        )
        if has_canned_candidate
        else []
    )
    canned_selections_inserted = False

    def append_selection(selection: GroundingSourceSelection) -> None:
        key = grounding_selection_key(selection)
        if key is not None and key in seen:
            return
        selected.append(selection)
        if key is not None:
            seen.add(key)

    for key in result.output.grounding_source_keys:
        source = valid_source_by_key.get(key)
        if source is None:
            continue
        if is_canned_response_source(source):
            if not canned_selections_inserted:
                for selection in canned_selections:
                    append_selection(selection)
                canned_selections_inserted = True
            continue
        append_selection(key)
    if canned_selections and not canned_selections_inserted:
        for selection in canned_selections:
            append_selection(selection)
    for key in exact_url_keys:
        append_selection(key)
    return selected


async def mark_grounding_sources_pending(
    session: AsyncSession, *, assistant_message_id: UUID
) -> None:
    metadata = await session.scalar(
        select(AssistantMessageMetadata).where(
            AssistantMessageMetadata.message_id == assistant_message_id
        )
    )
    if metadata is None:
        msg = f"Assistant message metadata not found for grounding: {assistant_message_id}"
        raise ValueError(msg)
    metadata.grounding_source_keys = None
    metadata.grounding_source_status = GROUNDING_SOURCE_STATUS_PENDING


async def select_and_store_grounding_sources(
    session: AsyncSession,
    *,
    assistant_message_id: UUID,
    user_message_id: UUID,
    assistant_answer: str,
    sources: Sequence[MessageSourceUsed],
) -> tuple[list[GroundingSourceSelection], str]:
    metadata = await session.scalar(
        select(AssistantMessageMetadata).where(
            AssistantMessageMetadata.message_id == assistant_message_id
        )
    )
    if metadata is None:
        msg = f"Assistant message metadata not found for grounding: {assistant_message_id}"
        raise ValueError(msg)

    user_message = await session.get(Message, user_message_id)
    if user_message is None:
        msg = f"User message not found for grounding: {user_message_id}"
        raise ValueError(msg)

    selected_keys = await select_grounding_source_keys(
        user_question=user_message.content,
        assistant_answer=assistant_answer,
        sources=sources,
        chatbot_system_prompt=metadata.system_prompt_rendered,
        tool_calls=metadata.tool_calls,
        trace_metadata={
            "conversation_id": str(user_message.conversation_id),
            "message_id": str(assistant_message_id),
            "is_internal": True,
        },
    )
    status = (
        GROUNDING_SOURCE_STATUS_SELECTED if selected_keys else GROUNDING_SOURCE_STATUS_NO_SELECTION
    )
    metadata.grounding_source_keys = selected_keys
    metadata.grounding_source_status = status
    return selected_keys, status
