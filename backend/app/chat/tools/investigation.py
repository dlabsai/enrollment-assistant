from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.message_sources import (
    MessageSourceUsed,
    filter_sources_by_keys,
    get_tool_sources_used_for_message,
    with_canned_response_source_candidate,
)
from app.chat.tools.deps import Deps
from app.chat.tree_utils import get_conversation_path, get_current_branch_path
from app.models import AssistantMessageMetadata, Conversation, Message, MessageFeedback, OtelSpan

if TYPE_CHECKING:
    from uuid import UUID


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _format_json_section(title: str, value: Any) -> str:
    return f"## {title}\n```json\n{_json(value)}\n```"


def _format_message(message: Message, *, focused: bool = False) -> str:
    marker = " focused source response" if focused else ""
    return (
        f"### {message.role.title()} message{marker}\n"
        f"id: `{message.id}`\n"
        f"created_at: `{message.created_at.isoformat()}`\n\n"
        f"{message.content}"
    )


async def _get_investigation_source(ctx: RunContext[Deps]) -> tuple[Conversation, Message | None]:
    investigation_id = ctx.deps.investigation_conversation_id
    if investigation_id is None:
        raise ValueError("This tool is only available in investigation chats.")

    async with ctx.deps.open_tool_session() as session:
        investigation = await session.get(Conversation, investigation_id)
        if investigation is None or investigation.kind != "investigation":
            raise ValueError("Investigation conversation not found.")
        if investigation.investigation_source_conversation_id is None:
            raise ValueError("This investigation is not linked to a source chat.")

        source = await session.get(Conversation, investigation.investigation_source_conversation_id)
        if source is None:
            raise ValueError("Source chat not found.")

        focused_message = None
        if investigation.investigation_source_message_id is not None:
            focused_message = await session.get(
                Message, investigation.investigation_source_message_id
            )

        return source, focused_message


async def _get_focused_assistant_message(ctx: RunContext[Deps]) -> tuple[Conversation, Message]:
    source, focused_message = await _get_investigation_source(ctx)
    if focused_message is None:
        raise ValueError("This investigation has no focused source message.")
    if focused_message.role != "assistant":
        raise ValueError("The focused source message is not an assistant response.")
    return source, focused_message


async def _get_trace_ids(ctx: RunContext[Deps], message_id: UUID) -> list[str]:
    async with ctx.deps.open_tool_session() as session:
        rows = (
            (
                await session.execute(
                    select(OtelSpan.trace_id)
                    .where(OtelSpan.message_id == message_id)
                    .where(OtelSpan.trace_id.is_not(None))
                    .group_by(OtelSpan.trace_id)
                    .order_by(func.max(OtelSpan.start_time).desc().nullslast())
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


def _metadata_payload(metadata: AssistantMessageMetadata | None) -> dict[str, Any] | None:
    if metadata is None:
        return None

    return {
        "id": str(metadata.id),
        "message_id": str(metadata.message_id),
        "conversation_turn": metadata.conversation_turn,
        "created_at": metadata.created_at.isoformat(),
        "updated_at": metadata.updated_at.isoformat(),
        "total_time_seconds": metadata.total_time,
        "guardrail_time_seconds": metadata.guardrail_time,
        "chatbot_times_seconds": metadata.chatbot_times,
        "guardrail_times_seconds": metadata.guardrail_times,
        "guardrail_model_settings": _diagnostic_model_settings(metadata.guardrail_model_settings),
        "guardrails": metadata.guardrails,
        "tool_calls": metadata.tool_calls,
        "grounding_source_keys": metadata.grounding_source_keys,
        "grounding_source_status": metadata.grounding_source_status,
        "system_prompt_rendered": metadata.system_prompt_rendered,
    }


def _diagnostic_model_settings(settings: dict[str, Any] | None) -> dict[str, Any] | None:
    if settings is None:
        return None
    return {
        key: value for key, value in settings.items() if key not in {"temperature", "max_tokens"}
    }


def _source_payload(source: MessageSourceUsed) -> dict[str, Any]:
    return source.model_dump(mode="json")


def _empty_sources_diagnosis(
    *,
    metadata: AssistantMessageMetadata | None,
    tool_sources_count: int,
    selected_sources_count: int,
    trace_count: int,
) -> list[str]:
    findings: list[str] = []
    if metadata is None:
        findings.append("assistant metadata is missing, so source persistence cannot be assessed")
        return findings
    if trace_count == 0:
        findings.append("no exported trace was found for the focused assistant response")
    if not metadata.tool_calls:
        findings.append("metadata.tool_calls is empty; the response may not have used RAG/tools")
    if tool_sources_count == 0:
        findings.append(
            "no source-producing tool outputs were reconstructed from the response trace"
        )
    if metadata.grounding_source_status is None:
        findings.append("grounding source selection has no stored status")
    elif metadata.grounding_source_status == "no_selection":
        findings.append("grounding source selection ran but selected no display sources")
    if metadata.grounding_source_keys == []:
        findings.append("grounding_source_keys is an empty list")
    if tool_sources_count > 0 and selected_sources_count == 0:
        findings.append(
            "candidate tool sources exist, but none are selected for display as grounding sources"
        )
    if not findings:
        findings.append("sources are present; inspect selected and candidate source arrays below")
    return findings


_TRACE_ATTRIBUTE_PREFIXES = (
    "app.",
    "gen_ai.agent.",
    "gen_ai.data_source.",
    "gen_ai.evaluation.",
    "gen_ai.input.",
    "gen_ai.operation.",
    "gen_ai.output.",
    "gen_ai.provider.",
    "gen_ai.request.",
    "gen_ai.response.",
    "gen_ai.retrieval.",
    "gen_ai.system_instructions",
    "gen_ai.tool.",
    "gen_ai.usage.",
)

_TRACE_ATTRIBUTE_EXCLUDED_KEYS = {
    # Provider/logging raw payloads duplicate structured GenAI attributes and are often huge.
    "request_data",
    "response_data",
    # Tool schemas add a lot of context noise; tool names, arguments, and results are retained.
    "gen_ai.tool.definitions",
    # Logfire/FastAPI internals are execution plumbing, not response-forensic evidence.
    "fastapi.arguments.values",
    "logfire.json_schema",
    "logfire.msg",
    "logfire.msg_template",
    # Current GPT models ignore these app-level knobs, and cost is not diagnostic here.
    "gen_ai.request.temperature",
    "gen_ai.request.max_tokens",
    "gen_ai.response.cost",
    "operation.cost",
}


def _is_forensic_trace_attribute(key: str) -> bool:
    if key in _TRACE_ATTRIBUTE_EXCLUDED_KEYS:
        return False
    return key.startswith(_TRACE_ATTRIBUTE_PREFIXES)


async def inspect_investigated_response(ctx: RunContext[Deps]) -> str:
    """Return the focused assistant response and its immediate user context."""
    source, focused_message = await _get_investigation_source(ctx)
    if focused_message is None:
        return "This investigation has no focused source message. Use inspect_investigated_chat()."

    async with ctx.deps.open_tool_session() as session:
        path = await get_conversation_path(session, focused_message.id)

    previous_user = next(
        (message for message in reversed(path[:-1]) if message.role == "user"), None
    )
    sections = [
        "# Investigated response\n"
        f"source_conversation_id: `{source.id}`\n"
        f"source_title: {source.title or 'Untitled'}"
    ]
    if previous_user is not None:
        sections.append(_format_message(previous_user))
    sections.append(_format_message(focused_message, focused=True))
    return "\n\n".join(sections)


async def inspect_investigated_chat(ctx: RunContext[Deps]) -> str:
    """Return the current branch transcript for the source chat under investigation."""
    source, focused_message = await _get_investigation_source(ctx)
    async with ctx.deps.open_tool_session() as session:
        if focused_message is not None:
            messages = await get_conversation_path(session, focused_message.id)
        else:
            path_ids = await get_current_branch_path(session, source.id)
            if not path_ids:
                messages = []
            else:
                result = await session.execute(select(Message).where(Message.id.in_(path_ids)))
                messages_by_id = {message.id: message for message in result.scalars().all()}
                messages = [
                    messages_by_id[message_id]
                    for message_id in path_ids
                    if message_id in messages_by_id
                ]

    sections = [
        "# Investigated chat\n"
        f"source_conversation_id: `{source.id}`\n"
        f"source_title: {source.title or 'Untitled'}"
    ]
    focused_id = focused_message.id if focused_message is not None else None
    sections.extend(
        _format_message(message, focused=message.id == focused_id) for message in messages
    )
    return "\n\n---\n\n".join(sections)


async def inspect_investigated_response_metadata(ctx: RunContext[Deps]) -> str:
    """Return generation metadata, prompt, timings, model settings, guardrails, and tool calls."""
    source, focused_message = await _get_focused_assistant_message(ctx)
    trace_ids = await _get_trace_ids(ctx, focused_message.id)

    async with ctx.deps.open_tool_session() as session:
        message = await session.scalar(
            select(Message)
            .where(Message.id == focused_message.id)
            .options(
                selectinload(Message.assistant_message_metadata),
                selectinload(Message.feedback).selectinload(MessageFeedback.user),
            )
        )
        if message is None:
            raise ValueError("Focused source message not found.")
        metadata = message.assistant_message_metadata
        feedback_payload = [
            {
                "id": str(feedback.id),
                "rating": feedback.rating.value,
                "text": feedback.text,
                "user_id": str(feedback.user_id),
                "user_name": feedback.user.name,
                "created_at": feedback.created_at.isoformat(),
            }
            for feedback in message.feedback
        ]

    payload = {
        "source_conversation_id": str(source.id),
        "source_title": source.title,
        "focused_message": {
            "id": str(focused_message.id),
            "role": focused_message.role,
            "created_at": focused_message.created_at.isoformat(),
            "guardrails_blocked": focused_message.guardrails_blocked,
            "guardrails_blocked_message": focused_message.guardrails_blocked_message,
        },
        "trace_ids": trace_ids,
        "feedback": feedback_payload,
        "assistant_metadata": _metadata_payload(metadata),
    }
    return "\n\n".join(
        ["# Investigated response metadata", _format_json_section("Payload", payload)]
    )


async def inspect_investigated_response_sources(ctx: RunContext[Deps]) -> str:
    """Return candidate tool sources, selected grounding sources, and empty-source diagnostics."""
    source, focused_message = await _get_focused_assistant_message(ctx)
    trace_ids = await _get_trace_ids(ctx, focused_message.id)

    async with ctx.deps.open_tool_session() as session:
        message = await session.scalar(
            select(Message)
            .where(Message.id == focused_message.id)
            .options(selectinload(Message.assistant_message_metadata))
        )
        if message is None:
            raise ValueError("Focused source message not found.")
        metadata = message.assistant_message_metadata
        source_reconstruction_error = None
        try:
            tool_sources = await get_tool_sources_used_for_message(session, focused_message.id)
        except (TypeError, ValueError) as error:
            tool_sources = []
            source_reconstruction_error = str(error)
        grounding_source_candidates = with_canned_response_source_candidate(tool_sources)
        selected_sources = filter_sources_by_keys(
            grounding_source_candidates,
            metadata.grounding_source_keys if metadata is not None else None,
        )

    findings = _empty_sources_diagnosis(
        metadata=metadata,
        tool_sources_count=len(tool_sources),
        selected_sources_count=len(selected_sources),
        trace_count=len(trace_ids),
    )
    if source_reconstruction_error is not None:
        findings.append(
            "candidate source reconstruction failed; inspect source_reconstruction_error"
        )
    payload = {
        "source_conversation_id": str(source.id),
        "source_title": source.title,
        "focused_message_id": str(focused_message.id),
        "trace_ids": trace_ids,
        "grounding_source_status": metadata.grounding_source_status if metadata else None,
        "grounding_source_keys": metadata.grounding_source_keys if metadata else None,
        "diagnostic_findings": findings,
        "source_reconstruction_error": source_reconstruction_error,
        "selected_grounding_sources": [_source_payload(source) for source in selected_sources],
        "candidate_tool_sources": [_source_payload(source) for source in tool_sources],
        "candidate_grounding_sources": [
            _source_payload(source) for source in grounding_source_candidates
        ],
    }
    return "\n\n".join(
        ["# Investigated response sources", _format_json_section("Payload", payload)]
    )


def _span_payload(span: OtelSpan) -> dict[str, Any]:
    attributes = span.attributes or {}
    forensic_attributes = {
        key: value for key, value in attributes.items() if _is_forensic_trace_attribute(key)
    }
    omitted_attribute_keys = sorted(set(attributes) - set(forensic_attributes))
    return {
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "name": span.name,
        "status_code": span.status_code,
        "status_message": span.status_message,
        "start_time": span.start_time.isoformat() if span.start_time else None,
        "duration_ms": span.duration_ms,
        "request_model": span.request_model,
        "provider_name": span.provider_name,
        "input_tokens": span.input_tokens,
        "output_tokens": span.output_tokens,
        "is_ai": span.is_ai,
        "attributes": forensic_attributes,
        "omitted_non_forensic_attribute_keys": omitted_attribute_keys,
    }


async def inspect_investigated_response_trace(ctx: RunContext[Deps]) -> str:
    """Return trace span summaries for the focused assistant response."""
    source, focused_message = await _get_focused_assistant_message(ctx)
    trace_ids = await _get_trace_ids(ctx, focused_message.id)
    if not trace_ids:
        return "No exported traces were found for the focused assistant response."

    async with ctx.deps.open_tool_session() as session:
        spans = (
            (
                await session.execute(
                    select(OtelSpan)
                    .where(OtelSpan.trace_id.in_(trace_ids))
                    .order_by(
                        OtelSpan.trace_id.asc(),
                        OtelSpan.start_time.asc().nullslast(),
                        OtelSpan.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    payload = {
        "source_conversation_id": str(source.id),
        "source_title": source.title,
        "focused_message_id": str(focused_message.id),
        "trace_ids": trace_ids,
        "span_count": len(spans),
        "agent_span_count": sum(
            1 for span in spans if (span.attributes or {}).get("gen_ai.agent.name")
        ),
        "tool_span_count": sum(
            1 for span in spans if (span.attributes or {}).get("gen_ai.tool.name")
        ),
        "spans": [_span_payload(span) for span in spans],
    }
    return "\n\n".join(["# Investigated response trace", _format_json_section("Payload", payload)])


async def inspect_investigated_conversation_branches(ctx: RunContext[Deps]) -> str:
    """Return parent/child branch structure around the investigated source conversation."""
    source, focused_message = await _get_investigation_source(ctx)
    focused_id = focused_message.id if focused_message is not None else None

    async with ctx.deps.open_tool_session() as session:
        rows = (
            await session.execute(
                select(
                    Message.id,
                    Message.parent_id,
                    Message.active_child_id,
                    Message.role,
                    Message.content,
                    Message.created_at,
                )
                .where(Message.conversation_id == source.id)
                .order_by(Message.created_at.asc())
            )
        ).all()

    payload = {
        "source_conversation_id": str(source.id),
        "source_title": source.title,
        "focused_message_id": str(focused_id) if focused_id is not None else None,
        "messages": [
            {
                "id": str(message_id),
                "parent_id": str(parent_id) if parent_id is not None else None,
                "active_child_id": str(active_child_id) if active_child_id is not None else None,
                "role": role,
                "focused": message_id == focused_id,
                "created_at": created_at.isoformat(),
                "content": content,
            }
            for message_id, parent_id, active_child_id, role, content, created_at in rows
        ],
    }
    return "\n\n".join(
        ["# Investigated conversation branches", _format_json_section("Payload", payload)]
    )
