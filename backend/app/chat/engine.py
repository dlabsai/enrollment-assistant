import copy
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from devtools import debug
from fastapi.encoders import jsonable_encoder
from jinja2 import Template
from opentelemetry.trace import get_current_span
from pydantic import TypeAdapter
from pydantic_ai import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    ThinkingPart,
    ThinkingPartDelta,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import telemetry
from app.chat.agents import (
    GuardrailsDeps,
    create_chatbot_agent,
    create_guardrails_agent,
    render_guardrails_system_prompt,
)
from app.chat.config import TEMPLATES_DIR
from app.chat.engine_utils import (
    MessageDict,
    ModelSettings,
    get_assistant_message_content,
    get_current_date_gmt_minus_4,
    normalize_whitespace,
    run_agent,
)
from app.chat.template_utils import get_runtime_jinja_environment
from app.chat.tools import Deps, get_deps_with_jinja_env
from app.chat.tree_utils import get_conversation_path
from app.chat.url_guardrails import (
    build_blog_url_feedback,
    build_unknown_url_feedback,
    find_blog_urls,
    find_unknown_urls,
    get_allowed_url_registry_for_va,
)
from app.core.config import settings
from app.models import AssistantMessageMetadata as AssistantMessageMetadataRecord
from app.models import Conversation, Message, PromptSetScope, Rating
from app.otel_genai import start_genai_tool_span

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass
class MessageMetadataOut:
    id: UUID
    message_id: UUID
    system_prompt_rendered: str
    conversation_turn: int
    chatbot_model_settings: ModelSettings
    created_at: datetime
    updated_at: datetime
    chatbot_time: float | None
    tool_calls: list[dict[str, Any]] | None = None
    guardrails: list[dict[str, Any]] | None = None
    guardrail_retries: int = 0
    total_time: float | None = None
    guardrail_model_settings: ModelSettings | None = None
    guardrail_time: float | None = None
    chatbot_times: list[float] | None = None
    guardrail_times: list[float] | None = None


@dataclass
class Feedback:
    id: UUID
    rating: Rating
    user_id: UUID
    user_name: str
    is_current_user: bool
    created_at: datetime
    updated_at: datetime
    text: str | None = None


@dataclass
class MessageOut:
    id: UUID
    role: str
    content: str
    created_at: datetime
    parent_id: UUID | None
    conversation_id: UUID | None = None
    guardrails_blocked: bool = False
    guardrails_blocked_message: str | None = None
    feedback: list[Feedback] = field(default_factory=lambda: cast(list[Feedback], []))
    metadata: MessageMetadataOut | None = None


EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


def _content_for_llm_history(
    *, role: str, content: str, guardrails_blocked: bool, guardrails_blocked_message: str | None
) -> str:
    if role == "assistant" and guardrails_blocked:
        blocked_message = guardrails_blocked_message or settings.GUARDRAILS_BLOCKED_MESSAGE
        return (
            "[This assistant response was blocked by guardrails. "
            f"The user was shown this message instead: {blocked_message}]"
        )
    return content


def _message_content_for_llm_history(message: Message) -> str:
    return _content_for_llm_history(
        role=message.role,
        content=message.content,
        guardrails_blocked=message.guardrails_blocked,
        guardrails_blocked_message=message.guardrails_blocked_message,
    )


async def _emit_agent_stage(
    event_emitter: EventEmitter | None,
    *,
    stage: str,
    status: str,
    duration: float | None = None,
    iteration: int | None = None,
) -> None:
    if event_emitter is None:
        return

    payload: dict[str, Any] = {"stage": stage, "status": status}
    if duration is not None:
        payload["duration_ms"] = int(duration * 1000)
    if iteration is not None:
        payload["iteration"] = iteration

    await event_emitter("agent_stage", payload)


def _serialize_tool_args(args: str | dict[str, Any] | None) -> Any | None:
    if args is None:
        return None
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return args
    return jsonable_encoder(args)


def _serialize_tool_output(output: Any) -> Any:
    return jsonable_encoder(output)


def _serialize_error_text(error: Any) -> str:
    if isinstance(error, str):
        return error
    try:
        return json.dumps(jsonable_encoder(error), indent=2)
    except TypeError:
        return str(error)


def _create_tool_event_handler(
    event_emitter: EventEmitter | None, *, stage: str, iteration: int | None = None
) -> Callable[[AgentStreamEvent], Awaitable[None]] | None:
    if event_emitter is None:
        return None

    tool_lookup: dict[str, str] = {}
    thinking_content: dict[int, str] = {}
    thinking_ids: dict[int, str] = {}

    async def handle_event(event: AgentStreamEvent) -> None:
        if isinstance(event, FunctionToolCallEvent):
            tool_call_id = event.tool_call_id
            tool_name = event.part.tool_name
            tool_lookup[tool_call_id] = tool_name

            payload: dict[str, Any] = {
                "stage": stage,
                "status": "start",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
            }
            tool_input = _serialize_tool_args(event.part.args)
            if tool_input is not None:
                payload["tool_input"] = tool_input
            if iteration is not None:
                payload["iteration"] = iteration

            await event_emitter("tool_call", payload)
            return

        if isinstance(event, FunctionToolResultEvent):
            tool_call_id = event.tool_call_id
            tool_name = tool_lookup.get(tool_call_id)
            status = "end"
            tool_output: Any | None = None
            tool_error_text: str | None = None

            result_part = event.part
            if isinstance(result_part, RetryPromptPart):
                status = "error"
                tool_error_text = _serialize_error_text(result_part.content)
                if result_part.tool_name is not None:
                    tool_name = result_part.tool_name
            elif isinstance(result_part, ToolReturnPart):
                tool_output = _serialize_tool_output(result_part.content)
                tool_name = result_part.tool_name

            payload: dict[str, Any] = {
                "stage": stage,
                "status": status,
                "tool_call_id": tool_call_id,
            }
            if tool_name is not None:
                payload["tool_name"] = tool_name
            if tool_output is not None:
                payload["tool_output"] = tool_output
            if tool_error_text is not None:
                payload["tool_error_text"] = tool_error_text
            if iteration is not None:
                payload["iteration"] = iteration

            await event_emitter("tool_call", payload)
            return

        if isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
            thinking_id = event.part.id or f"{stage}:{iteration or 0}:{event.index}"
            thinking_ids[event.index] = thinking_id
            thinking_content[event.index] = event.part.content
            payload: dict[str, Any] = {
                "stage": stage,
                "status": "start",
                "thinking_id": thinking_id,
            }
            if event.part.content:
                payload["content"] = event.part.content
            if iteration is not None:
                payload["iteration"] = iteration
            await event_emitter("thinking", payload)
            return

        if isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
            thinking_id = thinking_ids.get(event.index) or f"{stage}:{iteration or 0}:{event.index}"
            thinking_ids[event.index] = thinking_id
            current = thinking_content.get(event.index, "")
            if event.delta.content_delta:
                current += event.delta.content_delta
                thinking_content[event.index] = current
            payload: dict[str, Any] = {
                "stage": stage,
                "status": "delta",
                "thinking_id": thinking_id,
            }
            if current:
                payload["content"] = current
            if iteration is not None:
                payload["iteration"] = iteration
            await event_emitter("thinking", payload)
            return

        if isinstance(event, PartEndEvent) and isinstance(event.part, ThinkingPart):
            thinking_id = (
                thinking_ids.get(event.index)
                or event.part.id
                or f"{stage}:{iteration or 0}:{event.index}"
            )
            thinking_ids[event.index] = thinking_id
            thinking_content[event.index] = event.part.content
            payload: dict[str, Any] = {
                "stage": stage,
                "status": "end",
                "thinking_id": thinking_id,
                "content": event.part.content,
            }
            if iteration is not None:
                payload["iteration"] = iteration
            await event_emitter("thinking", payload)

    return handle_event


def _get_transcript(messages: list[MessageDict], limit_to_n_last: int | None = None) -> str:
    recent_messages = messages[-limit_to_n_last:] if limit_to_n_last is not None else messages
    formatted_messages: list[str] = []
    for message in recent_messages:
        role_display = "User" if message["role"] == "user" else "Assistant"
        formatted_messages.append(f"{role_display}: {message['content']}")

    return "\n\n".join(formatted_messages)


def _extract_tool_call_messages(
    result: Any, *, mirror_tool_spans_type: str | None = None
) -> list[MessageDict]:
    tool_call_messages: list[MessageDict] = []
    tool_arguments_by_id: dict[str, str | None] = {}

    for msg in result.all_messages():
        if not hasattr(msg, "parts"):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                args = json.dumps(part.args) if isinstance(part.args, dict) else part.args
                tool_call_id = part.tool_call_id or f"{part.tool_name}:{len(tool_arguments_by_id)}"
                tool_arguments_by_id[tool_call_id] = args
                tool_call_messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": part.tool_call_id,
                                "function": {"name": part.tool_name, "arguments": args},
                            }
                        ],
                    }
                )
            elif isinstance(part, ToolReturnPart):
                content = TypeAdapter(object).dump_json(part.content).decode()
                tool_call_id = part.tool_call_id
                tool_call_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": part.tool_call_id,
                        "name": part.tool_name,
                        "content": content,
                    }
                )
                if mirror_tool_spans_type is not None:
                    with start_genai_tool_span(
                        part.tool_name, tool_type=mirror_tool_spans_type
                    ) as span:
                        span.set_attribute("gen_ai.tool.call.id", tool_call_id)
                        if tool_call_id in tool_arguments_by_id:
                            arguments = tool_arguments_by_id[tool_call_id]
                            if arguments is not None:
                                span.set_attribute("gen_ai.tool.call.arguments", arguments)
                        span.set_attribute("gen_ai.tool.call.result", content)

    return tool_call_messages


def _build_guardrails_feedback_message(feedback: str) -> ModelRequest:
    return ModelRequest(
        parts=[
            SystemPromptPart(
                content=(
                    "Guardrails Agent rejected your previous response. Revise your next "
                    "response to satisfy this feedback. Do not mention guardrails or this "
                    f"internal feedback to the user.\n\n{feedback}"
                )
            )
        ]
    )


def _guardrail_retry_count_from_attempts(guardrail_attempt_count: int) -> int:
    """Return chatbot retry count from total guardrail checks.

    The first guardrail check validates the initial chatbot attempt. Only later
    checks validate retried chatbot attempts, so retries are checks minus one.
    """
    return max(guardrail_attempt_count - 1, 0)


async def _run_guardrails(
    guardrail_model_settings: ModelSettings,
    guardrails_log: list[dict[str, str]],
    response: str,
    *,
    current_user_message: str = "",
    template: Template,
    allowed_url_registry: frozenset[str] | None = None,
    trace_metadata: dict[str, Any] | None = None,
    event_emitter: EventEmitter | None = None,
    iteration: int | None = None,
) -> tuple[bool, str, list[dict[str, str]], float]:
    """Run guardrails check using PydanticAI Agent.

    Returns:
        Tuple of (is_valid, feedback_message, guardrails_log, duration)
    """
    guardrails_log = copy.deepcopy(guardrails_log)

    agent = create_guardrails_agent(guardrail_model_settings.model, template=template)
    deps = GuardrailsDeps(
        response_to_check=response,
        current_user_message=current_user_message,
        previous_rejected_attempts=guardrails_log,
    )
    system_prompt = render_guardrails_system_prompt(template, deps)

    await _emit_agent_stage(event_emitter, stage="guardrails", status="start", iteration=iteration)

    result, duration = await run_agent(
        agent,
        "Check the chatbot message.",
        guardrail_model_settings,
        deps=deps,
        metadata=trace_metadata,
        agent_name="guardrails",
        system_prompt=system_prompt,
    )

    await _emit_agent_stage(
        event_emitter, stage="guardrails", status="end", duration=duration, iteration=iteration
    )

    guardrails_result = result.output

    if settings.DEBUG:
        print("\nGuardrails result:")
        debug(guardrails_result)

    feedback_parts: list[str] = []
    llm_guardrails_feedback = guardrails_result.feedback or ""
    if llm_guardrails_feedback:
        feedback_parts.append(llm_guardrails_feedback)

    url_feedback_ok = True
    if allowed_url_registry is not None:
        with telemetry.span("url_guardrails") as span:
            disallowed_blog_urls = find_blog_urls(response)
            unknown_urls = [
                url
                for url in find_unknown_urls(response, allowed_urls=allowed_url_registry)
                if url not in disallowed_blog_urls
            ]
            url_feedback_ok = not disallowed_blog_urls and not unknown_urls
            span.set_attribute("app.guardrails.url.blog_urls", json.dumps(disallowed_blog_urls))
            span.set_attribute("app.guardrails.url.unknown_urls", json.dumps(unknown_urls))
            span.set_attribute("app.guardrails.url.is_valid", url_feedback_ok)

        if disallowed_blog_urls:
            feedback_parts.append(build_blog_url_feedback(disallowed_blog_urls))
        if unknown_urls:
            feedback_parts.append(build_unknown_url_feedback(unknown_urls))

    guardrails_feedback_ok = guardrails_result.is_valid and url_feedback_ok
    guardrails_feedback_message = "\n\n".join(feedback_parts)

    if not guardrails_feedback_ok:
        guardrails_log.append(
            {"assistant_message": response, "guardrails_message": guardrails_feedback_message}
        )

    return guardrails_feedback_ok, guardrails_feedback_message, guardrails_log, duration


async def _handle_investigation_iteration(
    *,
    branch_messages: list[MessageDict],
    chatbot_model_settings: ModelSettings,
    deps: Deps,
    system_prompt: str,
    trace_metadata: dict[str, Any] | None,
    event_emitter: EventEmitter | None = None,
) -> tuple[MessageDict, str, list[MessageDict], float]:
    normalized_system_prompt = normalize_whitespace(system_prompt)
    agent = create_chatbot_agent(chatbot_model_settings.model, deps.tools, normalized_system_prompt)
    transcript = _get_transcript(branch_messages)

    await _emit_agent_stage(event_emitter, stage="investigation", status="start")
    tool_event_handler = _create_tool_event_handler(event_emitter, stage="investigation")
    tool_call_messages: list[MessageDict] = []

    def capture_tool_call_messages(result: Any) -> None:
        nonlocal tool_call_messages
        tool_call_messages = _extract_tool_call_messages(
            result, mirror_tool_spans_type="investigation"
        )

    result, duration = await run_agent(
        agent,
        transcript,
        chatbot_model_settings,
        deps=deps,
        metadata=trace_metadata,
        agent_name="investigation",
        system_prompt=normalized_system_prompt,
        event_handler=tool_event_handler,
        result_handler=capture_tool_call_messages,
    )
    await _emit_agent_stage(event_emitter, stage="investigation", status="end", duration=duration)

    return (
        {"role": "assistant", "content": result.output, "tool_calls": None},
        normalized_system_prompt,
        tool_call_messages,
        duration,
    )


async def _run_chatbot_guardrails_iteration(
    *,
    chatbot_template: Template,
    guardrails_template: Template,
    branch_messages: list[MessageDict],
    chatbot_model_settings: ModelSettings,
    guardrail_model_settings: ModelSettings,
    deps: Deps,
    allowed_url_registry: frozenset[str] | None,
    current_user_message: str,
    chatbot_message_history: list[ModelMessage] | None,
    guardrails_log: list[dict[str, str]],
    enable_guardrails: bool = True,
    trace_metadata: dict[str, Any] | None = None,
    event_emitter: EventEmitter | None = None,
    iteration: int | None = None,
) -> tuple[
    MessageDict,
    bool,
    str,
    list[dict[str, str]],
    str,
    list[ModelMessage],
    list[MessageDict],
    float | None,  # guardrail_time
    float,  # chatbot_duration
]:
    guardrail_time: float | None = None

    main_system_prompt = chatbot_template.render(current_date=get_current_date_gmt_minus_4())
    main_system_prompt = normalize_whitespace(main_system_prompt)

    # Create and run the chatbot agent using PydanticAI
    chatbot_agent = create_chatbot_agent(
        chatbot_model_settings.model, deps.tools, main_system_prompt
    )

    # Build user prompt from conversation history
    transcript = _get_transcript(branch_messages)

    await _emit_agent_stage(event_emitter, stage="chatbot", status="start", iteration=iteration)

    tool_event_handler = _create_tool_event_handler(
        event_emitter, stage="chatbot", iteration=iteration
    )

    result, chatbot_duration = await run_agent(
        chatbot_agent,
        None if chatbot_message_history is not None else transcript,
        chatbot_model_settings,
        deps=deps,
        metadata=trace_metadata,
        agent_name="chatbot",
        system_prompt=main_system_prompt,
        message_history=chatbot_message_history,
        event_handler=tool_event_handler,
    )
    chatbot_messages = list(result.all_messages())

    await _emit_agent_stage(
        event_emitter, stage="chatbot", status="end", duration=chatbot_duration, iteration=iteration
    )

    response = result.output
    if settings.DEBUG:
        debug(response)

    # Extract tool call messages and results for frontend
    tool_call_messages = _extract_tool_call_messages(result)

    guardrails_log = copy.deepcopy(guardrails_log)

    # Build assistant message dict for downstream persistence and guardrails handling.
    assistant_message: MessageDict = {"role": "assistant", "content": response, "tool_calls": None}

    if enable_guardrails:
        (
            guardrails_feedback_ok,
            guardrails_feedback_message,
            guardrails_log,
            guardrail_time,
        ) = await _run_guardrails(
            guardrail_model_settings,
            guardrails_log,
            response,
            current_user_message=current_user_message,
            template=guardrails_template,
            allowed_url_registry=allowed_url_registry,
            trace_metadata=trace_metadata,
            event_emitter=event_emitter,
            iteration=iteration,
        )
    else:
        guardrails_feedback_ok, guardrails_feedback_message = True, ""

    return (
        assistant_message,
        guardrails_feedback_ok,
        guardrails_feedback_message,
        guardrails_log,
        main_system_prompt,
        chatbot_messages,
        tool_call_messages,
        guardrail_time,
        chatbot_duration,
    )


def _build_trace_metadata(
    *, conversation_id: UUID | None, user_id: UUID | None, is_internal: bool, conversation_turn: int
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"is_internal": is_internal, "conversation_turn": conversation_turn}
    if conversation_id is not None:
        metadata["conversation_id"] = str(conversation_id)
    if user_id is not None:
        metadata["user_id"] = str(user_id)
    return metadata


def _set_current_span_attributes(attributes: dict[str, Any]) -> None:
    span = get_current_span()
    for key, value in attributes.items():
        if value is None:
            continue
        span.set_attribute(key, value)


@telemetry.instrument()
async def handle_investigation_turn(
    *,
    project_name: str,
    conversation_id: UUID,
    parent_message_id: UUID | None = None,
    user_prompt: str,
    is_regeneration: bool = False,
    chatbot_model_settings: ModelSettings,
    user_id: UUID | None,
    session: AsyncSession,
    tool_session_factory: async_sessionmaker[AsyncSession],
    prompt_set_version_id: UUID | None = None,
    event_emitter: EventEmitter | None = None,
) -> tuple[UUID, MessageOut]:
    _ = project_name
    start_timestamp = time.perf_counter()
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation with ID {conversation_id} not found")
    if conversation.kind != "investigation":
        raise ValueError("Investigation turn requires an investigation conversation")

    parent_message: Message | None = None
    branch_messages: list[dict[str, str]] = []
    conversation_turn = 1
    if parent_message_id is not None:
        parent_message = await session.get(Message, parent_message_id)
        if parent_message is None:
            raise ValueError(f"Parent message with ID {parent_message_id} not found")
        branch_message_records = await get_conversation_path(session, parent_message_id)
        branch_messages = [
            {"role": message.role, "content": _message_content_for_llm_history(message)}
            for message in branch_message_records
        ]
        last_assistant = next(
            (
                message
                for message in reversed(branch_message_records)
                if message.role == "assistant"
            ),
            None,
        )
        if last_assistant is not None:
            await session.refresh(last_assistant, attribute_names=["assistant_message_metadata"])
            if last_assistant.assistant_message_metadata is not None:
                conversation_turn = last_assistant.assistant_message_metadata.conversation_turn + 1

    if not is_regeneration:
        branch_messages.append({"role": "user", "content": user_prompt})

    trace_metadata = _build_trace_metadata(
        conversation_id=conversation_id,
        user_id=user_id,
        is_internal=True,
        conversation_turn=conversation_turn,
    )
    _set_current_span_attributes(
        {
            "app.user_id": str(user_id) if user_id is not None else None,
            "app.is_internal": True,
            "app.conversation_id": str(conversation_id),
            "app.conversation_turn": conversation_turn,
            "gen_ai.input.messages": json.dumps(
                [{"role": "user", "content": user_prompt}], separators=(",", ":")
            ),
        }
    )

    jinja_env = await get_runtime_jinja_environment(
        TEMPLATES_DIR,
        is_internal=True,
        scope=PromptSetScope.INVESTIGATION,
        prompt_set_version_id=prompt_set_version_id,
    )
    deps = get_deps_with_jinja_env(
        session_factory=tool_session_factory,
        is_internal=True,
        investigation_conversation_id=conversation_id,
        jinja_env=jinja_env,
        prompt_set_version_id=prompt_set_version_id,
    )
    system_prompt_template = jinja_env.get_template("investigation_agent.j2")
    (
        assistant_message,
        system_prompt,
        tool_calls,
        chatbot_time,
    ) = await _handle_investigation_iteration(
        branch_messages=branch_messages,
        chatbot_model_settings=chatbot_model_settings,
        deps=deps,
        system_prompt=system_prompt_template.render(current_date=get_current_date_gmt_minus_4()),
        trace_metadata=trace_metadata,
        event_emitter=event_emitter,
    )

    response = get_assistant_message_content(assistant_message)
    if is_regeneration:
        if parent_message is None:
            raise ValueError("Parent message required for regeneration")
        assistant_record = Message(
            role="assistant",
            content=response,
            conversation=conversation,
            parent_id=parent_message.id,
        )
        session.add(assistant_record)
        await session.flush()
        parent_message.active_child = assistant_record
        user_message_id = parent_message.id
    else:
        user_record = Message(
            role="user",
            content=user_prompt,
            conversation=conversation,
            parent_id=parent_message.id if parent_message else None,
        )
        session.add(user_record)
        await session.flush()
        assistant_record = Message(
            role="assistant", content=response, conversation=conversation, parent_id=user_record.id
        )
        session.add(assistant_record)
        await session.flush()
        user_record.active_child = assistant_record
        if user_record.parent:
            user_record.parent.active_child_id = user_record.id
        user_message_id = user_record.id

    total_time = time.perf_counter() - start_timestamp
    _set_current_span_attributes(
        {
            "app.conversation_id": str(conversation.id),
            "app.message_id": str(assistant_record.id),
            "app.conversation_turn": conversation_turn,
            "app.guardrails_blocked": False,
            "app.guardrail_retries": 0,
            "app.total_time": total_time,
            "app.guardrail_time": None,
        }
    )

    metadata = AssistantMessageMetadataRecord(
        message_id=assistant_record.id,
        tool_calls=tool_calls or None,
        guardrails=None,
        system_prompt_rendered=system_prompt,
        conversation_turn=conversation_turn,
        total_time=total_time,
    )
    session.add(metadata)
    await session.flush()
    await session.refresh(conversation)
    await session.refresh(assistant_record)
    await session.refresh(metadata)

    return user_message_id, MessageOut(
        id=assistant_record.id,
        role="assistant",
        content=response,
        created_at=assistant_record.created_at,
        parent_id=assistant_record.parent_id,
        conversation_id=conversation.id,
        metadata=MessageMetadataOut(
            id=metadata.id,
            message_id=assistant_record.id,
            system_prompt_rendered=system_prompt,
            conversation_turn=conversation_turn,
            chatbot_model_settings=chatbot_model_settings,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            chatbot_time=chatbot_time,
            tool_calls=tool_calls or None,
            total_time=total_time,
            guardrail_time=None,
        ),
    )


@telemetry.instrument()
async def handle_conversation_turn(
    *,
    project_name: str,
    conversation_id: UUID | None = None,
    parent_message_id: UUID | None = None,
    user_prompt: str,
    is_regeneration: bool = False,
    chatbot_model_settings: ModelSettings,
    guardrail_model_settings: ModelSettings,
    user_id: UUID | None,
    session: AsyncSession,
    tool_session_factory: async_sessionmaker[AsyncSession],
    is_internal: bool = False,
    enable_guardrails: bool = True,
    max_guardrails_retries: int | None = None,
    prompt_set_version_id: UUID | None = None,
    event_emitter: EventEmitter | None = None,
) -> tuple[UUID, MessageOut]:
    """Handle a conversation turn for a given project and template using tree structure.

    Parameters
    ----------
    - conversation_id=None, parent_message_id=None: Start new conversation
    - conversation_id=existing_id, parent_message_id=None: Continue at current branch leaf
    - conversation_id=existing_id, parent_message_id=specific_id: Create branch from specific
        message
    - prompt_set_version_id: Optional specific prompt set version to use for testing.
        If None, uses the deployed prompt set version (if any) or disk templates.

    The system prompt message is generated dynamically at each turn from the active prompt set.
    User/assistant messages are stored in the database as a branchable tree.

    """
    if max_guardrails_retries is None:
        max_guardrails_retries = settings.MAX_GUARDRAILS_RETRIES

    start_timestamp = time.perf_counter()

    conversation_turn = 1
    branch_messages: list[dict[str, str]] = []
    parent_message: Message | None = None

    assistant_message_metadata: AssistantMessageMetadataRecord | None = None

    if settings.DEBUG:
        print("User message:")
        debug(user_prompt)

    if conversation_id is None:
        conversation = Conversation(
            title=user_prompt, project=project_name, user_id=user_id, is_public=not is_internal
        )
    else:
        conversation = await session.get(Conversation, conversation_id)
        if not conversation:
            raise ValueError(f"Conversation with ID {conversation_id} not found")

        if parent_message_id is not None:
            parent_message = await session.get(Message, parent_message_id)
            if not parent_message:
                raise ValueError(f"Parent message with ID {parent_message_id} not found")

            branch_message_records = await get_conversation_path(session, parent_message_id)
            branch_messages = [
                {"role": m.role, "content": _message_content_for_llm_history(m)}
                for m in branch_message_records
            ]

            last_message_record = branch_message_records[-1]
            if not is_regeneration:
                if last_message_record.role == "assistant":
                    # TODO: awaitable_attrs would be better here?
                    await session.refresh(
                        last_message_record, attribute_names=["assistant_message_metadata"]
                    )
                    assistant_message_metadata = last_message_record.assistant_message_metadata
                    assert assistant_message_metadata

                    conversation_turn = assistant_message_metadata.conversation_turn + 1
            else:
                assert last_message_record.role == "user"
                try:
                    last_message_record = branch_message_records[-2]
                    # TODO: awaitable_attrs would be better here?
                    await session.refresh(
                        last_message_record, attribute_names=["assistant_message_metadata"]
                    )
                    assistant_message_metadata = last_message_record.assistant_message_metadata
                    assert assistant_message_metadata

                    conversation_turn = assistant_message_metadata.conversation_turn + 1
                except IndexError:
                    pass

    if not is_regeneration:
        branch_messages.append({"role": "user", "content": user_prompt})

    trace_metadata = _build_trace_metadata(
        conversation_id=conversation_id,
        user_id=user_id,
        is_internal=is_internal,
        conversation_turn=conversation_turn,
    )
    _set_current_span_attributes(
        {
            "app.user_id": str(user_id) if user_id is not None else None,
            "app.is_internal": is_internal,
            "app.conversation_id": str(conversation_id) if conversation_id is not None else None,
            "app.conversation_turn": conversation_turn,
            "gen_ai.input.messages": json.dumps(
                [{"role": "user", "content": user_prompt}], separators=(",", ":")
            ),
        }
    )

    # Run the retrieval-capable chatbot, then validate with guardrails. Guardrails retries reuse
    # same-turn chatbot message history plus feedback; only the final assistant message is
    # persisted.

    assistant_message = None
    system_prompt = None

    guardrails_feedback_ok = False
    guardrails_feedback_message = ""
    guardrail_retry_count = 0
    guardrails_log: list[dict[str, str]] = []

    assistant_jinja_env = await get_runtime_jinja_environment(
        TEMPLATES_DIR,
        is_internal=is_internal,
        scope=PromptSetScope.ASSISTANT,
        prompt_set_version_id=prompt_set_version_id,
    )
    deps = get_deps_with_jinja_env(
        session_factory=tool_session_factory,
        is_internal=is_internal,
        jinja_env=assistant_jinja_env,
        prompt_set_version_id=prompt_set_version_id,
    )

    tool_call_messages = None

    chatbot_template = assistant_jinja_env.get_template("chatbot_agent.j2")
    guardrails_template = assistant_jinja_env.get_template("guardrails_agent.j2")

    allowed_url_registry: frozenset[str] | None = None
    if enable_guardrails:
        allowed_url_registry = await get_allowed_url_registry_for_va(
            session, is_internal=is_internal
        )

    guardrail_time: float | None = None
    total_guardrail_time: float = 0.0
    chatbot_times: list[float] = []
    guardrail_times: list[float] = []
    chatbot_message_history: list[ModelMessage] | None = None

    while not guardrails_feedback_ok:
        if guardrail_retry_count > max_guardrails_retries:
            break

        (
            assistant_message,
            guardrails_feedback_ok,
            guardrails_feedback_message,
            guardrails_log,
            system_prompt,
            iteration_chatbot_messages,
            tool_call_messages,
            iteration_guardrail_time,
            iteration_chatbot_time,
        ) = await _run_chatbot_guardrails_iteration(
            chatbot_template=chatbot_template,
            guardrails_template=guardrails_template,
            branch_messages=branch_messages,
            chatbot_model_settings=chatbot_model_settings,
            guardrail_model_settings=guardrail_model_settings,
            deps=deps,
            allowed_url_registry=allowed_url_registry,
            current_user_message=user_prompt,
            chatbot_message_history=chatbot_message_history,
            guardrails_log=guardrails_log,
            enable_guardrails=enable_guardrails,
            trace_metadata=trace_metadata,
            event_emitter=event_emitter,
            iteration=guardrail_retry_count + 1,
        )

        # Track per-iteration timing
        chatbot_times.append(iteration_chatbot_time)

        # Accumulate guardrail time across retries
        if iteration_guardrail_time is not None:
            total_guardrail_time += iteration_guardrail_time
            guardrail_times.append(iteration_guardrail_time)

        if not guardrails_feedback_ok:
            chatbot_message_history = [
                *iteration_chatbot_messages,
                _build_guardrails_feedback_message(guardrails_feedback_message),
            ]
            guardrail_retry_count += 1

    # Set final guardrail time (None if guardrails weren't run)
    if total_guardrail_time > 0:
        guardrail_time = total_guardrail_time

    assert assistant_message
    assert system_prompt

    # Track if guardrails blocked the response after max retries
    guardrails_blocked = not guardrails_feedback_ok
    guardrails_blocked_message = settings.GUARDRAILS_BLOCKED_MESSAGE if guardrails_blocked else None

    response = get_assistant_message_content(assistant_message)

    branch_messages.append(
        {
            "role": "assistant",
            "content": _content_for_llm_history(
                role="assistant",
                content=response,
                guardrails_blocked=guardrails_blocked,
                guardrails_blocked_message=guardrails_blocked_message,
            ),
        }
    )

    if conversation_id is None:
        session.add(conversation)
        await session.flush()

    if is_regeneration:
        if not parent_message:
            raise ValueError("Parent message required for regeneration")

        assistant_record = Message(
            role="assistant",
            content=response,
            conversation=conversation,
            parent_id=parent_message.id,
            guardrails_blocked=guardrails_blocked,
            guardrails_blocked_message=guardrails_blocked_message,
        )
        session.add(assistant_record)
        await session.flush()
        parent_message.active_child = assistant_record

        user_message_id = parent_message.id
    else:
        user_record = Message(
            role="user",
            content=user_prompt,
            conversation=conversation,
            parent_id=parent_message.id if parent_message else None,
        )
        session.add(user_record)
        await session.flush()

        assistant_record = Message(
            role="assistant",
            content=response,
            conversation=conversation,
            parent_id=user_record.id,
            guardrails_blocked=guardrails_blocked,
            guardrails_blocked_message=guardrails_blocked_message,
        )
        session.add(assistant_record)
        await session.flush()

        user_record.active_child = assistant_record
        if user_record.parent:
            # for user message edit
            # TODO: Configure model to allow setting active_child directly.
            #   Now it would result in circular dependency error
            user_record.parent.active_child_id = user_record.id

        user_message_id = user_record.id

    assistant_message_id = assistant_record.id

    end_timestamp = time.perf_counter()
    total_time = end_timestamp - start_timestamp
    guardrail_retries = _guardrail_retry_count_from_attempts(len(guardrail_times))

    _set_current_span_attributes(
        {
            "app.conversation_id": str(conversation.id),
            "app.message_id": str(assistant_message_id),
            "app.conversation_turn": conversation_turn,
            "app.guardrails_blocked": guardrails_blocked,
            "app.guardrail_retries": guardrail_retries,
            "app.total_time": total_time,
            "app.guardrail_time": guardrail_time,
            "app.chatbot_times": chatbot_times if len(chatbot_times) > 1 else None,
            "app.guardrail_times": guardrail_times if len(guardrail_times) > 1 else None,
        }
    )

    all_tool_calls: list[dict[str, Any]] = []
    if tool_call_messages:
        all_tool_calls.extend(tool_call_messages)

    metadata = AssistantMessageMetadataRecord(
        message_id=assistant_message_id,
        tool_calls=all_tool_calls or None,
        guardrails=guardrails_log or None,
        system_prompt_rendered=system_prompt,
        conversation_turn=conversation_turn,
        total_time=total_time,
        guardrail_model_settings=(
            guardrail_model_settings.to_dict() if guardrail_time is not None else None
        ),
        guardrail_time=guardrail_time,
        # Per-iteration timing arrays (only store if there were retries)
        chatbot_times=chatbot_times if len(chatbot_times) > 1 else None,
        guardrail_times=guardrail_times if len(guardrail_times) > 1 else None,
    )
    session.add(metadata)
    await session.flush()

    await session.refresh(conversation)
    await session.refresh(assistant_record)
    await session.refresh(metadata)

    chatbot_time = sum(chatbot_times) if chatbot_times else None

    assistant_message_metadata_out = MessageMetadataOut(
        id=metadata.id,
        message_id=metadata.message_id,
        conversation_turn=metadata.conversation_turn,
        chatbot_model_settings=chatbot_model_settings,
        chatbot_time=chatbot_time,
        system_prompt_rendered=metadata.system_prompt_rendered,
        tool_calls=metadata.tool_calls,
        guardrails=metadata.guardrails,
        guardrail_retries=guardrail_retries,
        total_time=metadata.total_time,
        guardrail_model_settings=(
            guardrail_model_settings if metadata.guardrail_time is not None else None
        ),
        guardrail_time=metadata.guardrail_time,
        chatbot_times=chatbot_times if len(chatbot_times) > 1 else None,
        guardrail_times=guardrail_times if len(guardrail_times) > 1 else None,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
    )

    return (
        user_message_id,
        MessageOut(
            id=assistant_message_id,
            parent_id=assistant_record.parent_id,
            conversation_id=conversation.id,
            role=assistant_record.role,
            content=assistant_record.content,
            metadata=assistant_message_metadata_out,
            created_at=assistant_record.created_at,
            guardrails_blocked=assistant_record.guardrails_blocked,
            guardrails_blocked_message=assistant_record.guardrails_blocked_message,
        ),
    )
