"""Read-only-ish chatbot inspection CLI for end-to-end debugging."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.chat.engine import MessageOut, handle_conversation_turn
from app.chat.engine_utils import ModelSettings
from app.core.config import settings
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.models import OtelSpan, User
from app.otel import (
    configure_otel_span_processor,
    otel_export_scope,
    otel_session_factory_scope,
    wait_for_pending_spans,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


class CliError(Exception):
    """Expected CLI failure with a stable exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _add_runtime_flags(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    none_default: str | None = argparse.SUPPRESS if suppress_defaults else None
    bool_default: bool | str = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--json", action="store_true", default=bool_default, help="write JSON")
    parser.add_argument(
        "--db-url", default=none_default, help="database URL; defaults to POSTGRES settings"
    )
    parser.add_argument(
        "--public",
        action="store_true",
        default=bool_default,
        help="use public-chat prompt mode instead of internal staff mode",
    )
    parser.add_argument(
        "--no-guardrails",
        action="store_true",
        default=bool_default,
        help="disable chatbot guardrails for this inspection run",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        default=bool_default,
        help="commit the created debug user/conversation instead of rolling it back",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        default=bool_default,
        help="persist OTel spans for this inspection run; implies --persist",
    )
    parser.add_argument(
        "--show-system-prompt",
        action="store_true",
        default=bool_default,
        help="include the rendered system prompt in human output",
    )
    parser.add_argument(
        "--show-tools",
        action="store_true",
        default=bool_default,
        help="include captured tool-call/result JSON in human output",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.chat.inspect",
        description=(
            "Send one chatbot message through the real backend runtime and inspect the response."
        ),
    )
    parser.add_argument("--version", action="version", version="app.chat.inspect 0.1")
    _add_runtime_flags(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)
    ask = subparsers.add_parser("ask", help="send one message and print the assistant response")
    _add_runtime_flags(ask, suppress_defaults=True)
    ask.add_argument("message", nargs="?", help="message text; reads stdin when omitted")
    return parser


def _read_message(value: str | None) -> str:
    message = value.strip() if value is not None else sys.stdin.read().strip()
    if not message:
        raise CliError("message is required: pass it as an argument or via stdin", exit_code=2)
    return message


def _make_session_factory(db_url: str | None) -> async_sessionmaker[AsyncSession]:
    raw_url = db_url or str(settings.SQLALCHEMY_DATABASE_URI)
    async_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url, echo=False, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _model_settings() -> dict[str, ModelSettings]:
    return {
        "chatbot": ModelSettings(
            model=settings.CHATBOT_MODEL,
            temperature=settings.CHATBOT_MODEL_TEMPERATURE,
            max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS,
        ),
        "guardrail": ModelSettings(
            model=settings.GUARDRAIL_MODEL,
            temperature=settings.GUARDRAIL_MODEL_TEMPERATURE,
            max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS,
        ),
    }


def _find_tool_name(tool_call: dict[str, Any]) -> str:
    for key in ("tool_name", "name"):
        value = tool_call.get(key)
        if isinstance(value, str) and value:
            return value
    tool_calls_value = tool_call.get("tool_calls")
    if isinstance(tool_calls_value, list):
        tool_calls = cast(list[Any], tool_calls_value)
        names: list[str] = []
        for nested_call_value in tool_calls:
            if not isinstance(nested_call_value, dict):
                continue
            nested_call = cast(dict[str, Any], nested_call_value)
            nested_name = _find_tool_name(nested_call)
            if nested_name != "unknown":
                names.append(nested_name)
        if names:
            return ",".join(names)
    function_value = tool_call.get("function")
    if isinstance(function_value, dict):
        function = cast(dict[str, Any], function_value)
        name_value = function.get("name")
        if isinstance(name_value, str) and name_value:
            return name_value
    for key in ("tool_call", "call", "request"):
        nested = tool_call.get(key)
        if isinstance(nested, dict):
            nested_name = _find_tool_name(cast(dict[str, Any], nested))
            if nested_name != "unknown":
                return nested_name
    return "unknown"


def _json_or_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _string_preview(value: Any, *, max_length: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", " ")
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}…"


def _tool_result_summary(value: Any) -> dict[str, Any]:
    parsed = _json_or_text(value)
    if isinstance(parsed, list):
        parsed_list = cast(list[Any], parsed)
        return {
            "kind": "json_list",
            "count": len(parsed_list),
            "preview": _string_preview(parsed_list[:2]),
        }
    if isinstance(parsed, dict):
        parsed_dict = cast(dict[Any, Any], parsed)
        return {
            "kind": "json_object",
            "keys": sorted(str(key) for key in parsed_dict),
            "preview": _string_preview(parsed_dict),
        }
    return {"kind": "text", "preview": _string_preview(parsed)}


def _normalise_tool_invocations(tool_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invocations_by_id: dict[str, dict[str, Any]] = {}
    invocations: list[dict[str, Any]] = []
    for message in tool_messages:
        raw_calls_value = message.get("tool_calls")
        if isinstance(raw_calls_value, list):
            raw_calls = cast(list[Any], raw_calls_value)
            for raw_call_value in raw_calls:
                if not isinstance(raw_call_value, dict):
                    continue
                call = cast(dict[str, Any], raw_call_value)
                call_id = call.get("id")
                if not isinstance(call_id, str) or not call_id:
                    call_id = f"call-{len(invocations) + 1}"
                function_value = call.get("function")
                function_dict = (
                    cast(dict[str, Any], function_value) if isinstance(function_value, dict) else {}
                )
                name = _find_tool_name(call)
                arguments = _json_or_text(function_dict.get("arguments", call.get("arguments")))
                invocation: dict[str, Any] = {"id": call_id, "name": name, "arguments": arguments}
                invocations_by_id[call_id] = invocation
                invocations.append(invocation)
            continue

        if message.get("role") != "tool":
            continue
        call_id_value = message.get("tool_call_id")
        call_id = call_id_value if isinstance(call_id_value, str) and call_id_value else None
        existing_invocation: dict[str, Any] | None = invocations_by_id.get(call_id or "")
        if existing_invocation is None:
            existing_invocation = {
                "id": call_id,
                "name": _find_tool_name(message),
                "arguments": None,
            }
            invocations.append(existing_invocation)
        existing_invocation["result"] = _tool_result_summary(message.get("content"))
    return invocations


def _result_payload(message: MessageOut, user_message_id: uuid.UUID) -> dict[str, Any]:
    metadata = message.metadata
    tool_calls = metadata.tool_calls if metadata and metadata.tool_calls else []
    tool_invocations = _normalise_tool_invocations(tool_calls)
    return {
        "conversation_id": str(message.conversation_id),
        "user_message_id": str(user_message_id),
        "assistant_message_id": str(message.id),
        "response": message.content,
        "guardrails_blocked": message.guardrails_blocked,
        "guardrail_retries": metadata.guardrail_retries if metadata else 0,
        "timing": {
            "total_time": metadata.total_time if metadata else None,
            "chatbot_time": metadata.chatbot_time if metadata else None,
            "guardrail_time": metadata.guardrail_time if metadata else None,
        },
        "models": {
            "chatbot": metadata.chatbot_model_settings.to_dict()
            if metadata and metadata.chatbot_model_settings
            else None,
            "guardrail": metadata.guardrail_model_settings.to_dict()
            if metadata and metadata.guardrail_model_settings
            else None,
        },
        "tools": {
            "count": len(tool_invocations),
            "message_count": len(tool_calls),
            "names": [item["name"] for item in tool_invocations],
            "invocations": tool_invocations,
            "calls": tool_calls,
        },
        "guardrails": metadata.guardrails if metadata else None,
        "system_prompt": metadata.system_prompt_rendered if metadata else None,
    }


def _print_human(
    result: dict[str, Any], *, show_system_prompt: bool, show_tools: bool, persisted: bool
) -> None:
    print("Assistant response:\n")
    print(result["response"])
    print("\n---")
    print(
        f"Conversation: {result['conversation_id']} ({'persisted' if persisted else 'rolled back'})"
    )
    print(f"Assistant message: {result['assistant_message_id']}")
    trace_ids = cast(list[str] | None, result.get("trace_ids"))
    if trace_ids:
        print(f"Trace IDs: {', '.join(trace_ids)}")
    tools = cast(dict[str, Any], result["tools"])
    tool_names = cast(list[str], tools["names"])
    tool_suffix = f" ({', '.join(tool_names)})" if tool_names else ""
    print(f"Tool invocations: {tools['count']}" + tool_suffix)
    print(f"Guardrail retries: {result['guardrail_retries']}")
    timing = cast(dict[str, Any], result["timing"])
    print(
        "Timing: "
        f"total={timing['total_time']} chatbot={timing['chatbot_time']} "
        f"guardrail={timing['guardrail_time']}"
    )
    if show_tools:
        print("\nTool invocations:\n")
        print(json.dumps(tools["invocations"], ensure_ascii=False, indent=2, default=str))
        print("\nRaw tool messages:\n")
        print(json.dumps(tools["calls"], ensure_ascii=False, indent=2, default=str))
    if show_system_prompt:
        print("\nSystem prompt:\n")
        print(result["system_prompt"] or "")


async def _ask(
    args: argparse.Namespace, *, session_factory: async_sessionmaker[AsyncSession] | None = None
) -> dict[str, Any]:
    message = _read_message(cast(str | None, args.message))
    if session_factory is None:
        session_factory = _make_session_factory(cast(str | None, args.db_url))
    models = _model_settings()

    async with session_factory() as session:
        user_id: uuid.UUID | None = None
        if not cast(bool, args.public):
            group = await get_group_for_slug(session, SystemGroupSlug.USER)
            user = User(
                id=uuid.uuid4(),
                email=f"debug-{uuid.uuid4()}@example.com",
                name="Chat Inspect Debug User",
                password_hash="not-a-real-hash",  # noqa: S106
                is_active=True,
                group_id=group.id,
            )
            session.add(user)
            await session.flush()
            user_id = user.id

        user_message_id, assistant_message = await handle_conversation_turn(
            project_name="chat_inspect",
            conversation_id=None,
            parent_message_id=None,
            user_prompt=message,
            is_regeneration=False,
            chatbot_model_settings=models["chatbot"],
            guardrail_model_settings=models["guardrail"],
            user_id=user_id,
            session=session,
            tool_session_factory=session_factory,
            is_internal=not cast(bool, args.public),
            enable_guardrails=not cast(bool, args.no_guardrails),
            max_guardrails_retries=settings.MAX_GUARDRAILS_RETRIES,
        )
        result = _result_payload(assistant_message, user_message_id)
        if cast(bool, args.persist):
            await session.commit()
        else:
            await session.rollback()
        return result


async def _trace_ids_for_conversation(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            select(OtelSpan.trace_id)
            .where(OtelSpan.conversation_id == conversation_id)
            .group_by(OtelSpan.trace_id)
            .order_by(OtelSpan.trace_id)
        )
        return list(rows.scalars())


async def _run_ask(args: argparse.Namespace) -> dict[str, Any]:
    trace_enabled = cast(bool, getattr(args, "trace", False))
    if trace_enabled:
        args.persist = True

    session_factory = _make_session_factory(cast(str | None, args.db_url))
    if not trace_enabled:
        return await _ask(args, session_factory=session_factory)

    configure_otel_span_processor()
    tracer = trace.get_tracer("app.chat.inspect")
    try:
        with (
            otel_session_factory_scope(session_factory),
            otel_export_scope(enabled=True),
            tracer.start_as_current_span("chat_inspect ask"),
        ):
            result = await _ask(args, session_factory=session_factory)
    finally:
        await wait_for_pending_spans()
    result["trace_ids"] = await _trace_ids_for_conversation(
        session_factory, uuid.UUID(cast(str, result["conversation_id"]))
    )
    return result


async def _main_async(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "ask":
        print(f"error: unknown command: {args.command}", file=sys.stderr)
        return 2

    try:
        if cast(bool, args.json):
            with redirect_stdout(sys.stderr):
                result = await _run_ask(args)
        else:
            result = await _run_ask(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if cast(bool, args.json):
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(
            result,
            show_system_prompt=cast(bool, args.show_system_prompt),
            show_tools=cast(bool, args.show_tools),
            persisted=cast(bool, args.persist),
        )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
