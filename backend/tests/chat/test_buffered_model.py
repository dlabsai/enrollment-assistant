from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic_ai import Agent, AgentRunResult, ModelRetry, RunContext
from pydantic_ai.capabilities import Hooks, ValidatedToolArgs
from pydantic_ai.messages import (
    AgentStreamEvent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    SystemPromptPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from app.chat.buffered_model import BufferedResponseModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterable


class _CountingTestModel(TestModel):
    def __init__(self, *, include_thinking: bool = False) -> None:
        super().__init__(call_tools="all", custom_output_text="done", model_name="counting-test")
        self.include_thinking = include_thinking
        self.request_calls = 0
        self.request_stream_calls = 0

    def _request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = super()._request(messages, model_settings, model_request_parameters)
        if not self.include_thinking:
            return response
        return replace(
            response,
            parts=[ThinkingPart(content="completed reasoning", id="reasoning-1"), *response.parts],
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.request_calls += 1
        return await super().request(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        self.request_stream_calls += 1
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as response:
            yield response


async def _run_with_events[D, T](
    agent: Agent[D, T], prompt: str, events: list[AgentStreamEvent], *, deps: D | None = None
) -> AgentRunResult[T]:
    async def handle_event_stream(
        _ctx: RunContext[D], event_stream: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for event in event_stream:
            events.append(event)

    return await agent.run(
        prompt,
        deps=deps,  # type: ignore[arg-type]
        event_stream_handler=handle_event_stream,
    )


@pytest.mark.asyncio
async def test_buffered_model_uses_complete_responses_and_keeps_tool_events_live() -> None:
    timeline: list[str] = []
    events: list[AgentStreamEvent] = []

    async def lookup() -> str:
        timeline.append("tool-body")
        return "tool-result"

    async def handle_event_stream(
        _ctx: RunContext[object], event_stream: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for event in event_stream:
            events.append(event)
            if isinstance(event, FunctionToolCallEvent):
                timeline.append("tool-start")
            elif isinstance(event, FunctionToolResultEvent):
                timeline.append("tool-end")

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[lookup])

    result = await agent.run("Use the tool", event_stream_handler=handle_event_stream)

    assert result.output == "done"
    assert model.request_calls == 2
    assert model.request_stream_calls == 0
    assert timeline == ["tool-start", "tool-body", "tool-end"]
    assert any(isinstance(event, FinalResultEvent) for event in events)


@pytest.mark.asyncio
async def test_unwrapped_model_preserves_full_provider_streaming_rollback() -> None:
    events: list[AgentStreamEvent] = []

    async def lookup() -> str:
        return "tool-result"

    model = _CountingTestModel()
    agent = Agent(model, tools=[lookup])

    result = await _run_with_events(agent, "Use the tool", events)

    assert result.output == "done"
    assert model.request_calls == 0
    assert model.request_stream_calls == 2
    assert any(isinstance(event, PartDeltaEvent) for event in events)
    assert any(isinstance(event, FunctionToolCallEvent) for event in events)
    assert any(isinstance(event, FunctionToolResultEvent) for event in events)


@pytest.mark.asyncio
async def test_buffered_model_preserves_explicit_model_overrides() -> None:
    events: list[AgentStreamEvent] = []

    async def lookup() -> str:
        return "tool-result"

    base_model = _CountingTestModel()
    override_model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(base_model), tools=[lookup])

    with agent.override(model=BufferedResponseModel(override_model)):
        result = await _run_with_events(agent, "Use the tool", events)

    assert result.output == "done"
    assert base_model.request_calls == 0
    assert base_model.request_stream_calls == 0
    assert override_model.request_calls == 2
    assert override_model.request_stream_calls == 0


@pytest.mark.asyncio
async def test_buffered_model_replays_complete_parts_without_delta_events() -> None:
    events: list[AgentStreamEvent] = []

    async def lookup() -> str:
        return "tool-result"

    model = _CountingTestModel(include_thinking=True)
    agent = Agent(BufferedResponseModel(model), tools=[lookup])

    await _run_with_events(agent, "Use the tool", events)

    thinking_start_contents = [
        event.part.content
        for event in events
        if isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart)
    ]
    thinking_end_contents = [
        event.part.content
        for event in events
        if isinstance(event, PartEndEvent) and isinstance(event.part, ThinkingPart)
    ]

    assert thinking_start_contents == ["completed reasoning", "completed reasoning"]
    assert thinking_end_contents == ["completed reasoning", "completed reasoning"]
    assert not any(isinstance(event, PartDeltaEvent) for event in events)
    assert any(isinstance(event, FunctionToolCallEvent) for event in events)
    assert any(isinstance(event, FunctionToolResultEvent) for event in events)


@pytest.mark.asyncio
async def test_buffered_model_preserves_tool_retries() -> None:
    attempts = 0
    events: list[AgentStreamEvent] = []

    async def lookup() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ModelRetry("try again")
        return "tool-result"

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[lookup])

    result = await _run_with_events(agent, "Use the tool", events)

    assert result.output == "done"
    assert attempts == 2
    assert model.request_calls == 3
    assert model.request_stream_calls == 0
    assert sum(isinstance(event, FunctionToolCallEvent) for event in events) == 2
    assert sum(isinstance(event, FunctionToolResultEvent) for event in events) == 2


@pytest.mark.asyncio
async def test_buffered_model_preserves_complete_tool_history_across_runs() -> None:
    first_events: list[AgentStreamEvent] = []
    second_events: list[AgentStreamEvent] = []

    async def lookup() -> str:
        return "tool-result"

    async def handle_second_event_stream(
        _ctx: RunContext[object], event_stream: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for event in event_stream:
            second_events.append(event)

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[lookup])
    first_result = await _run_with_events(agent, "Use the tool", first_events)
    retry_history = [
        *first_result.all_messages(),
        ModelRequest(parts=[SystemPromptPart("Revise the previous response")]),
    ]

    second_result = await agent.run(
        None, message_history=retry_history, event_stream_handler=handle_second_event_stream
    )

    tool_calls = [
        part
        for message in second_result.all_messages()
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    tool_returns = [
        part
        for message in second_result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert second_result.output == "done"
    assert [part.tool_call_id for part in tool_calls] == [
        part.tool_call_id for part in tool_returns
    ]
    for part in tool_returns:
        metadata = cast("dict[str, Any]", part.metadata or {})
        assert not metadata.get("pydantic_ai_synthesized_tool_return")
    assert model.request_calls == 3
    assert model.request_stream_calls == 0
    assert any(isinstance(event, FinalResultEvent) for event in second_events)


@pytest.mark.asyncio
async def test_buffered_model_preserves_parallel_tool_execution() -> None:
    entered: set[str] = set()
    both_entered = asyncio.Event()
    release_tools = asyncio.Event()
    events: list[AgentStreamEvent] = []

    async def wait_for_release(name: str) -> str:
        entered.add(name)
        if len(entered) == 2:
            both_entered.set()
        await release_tools.wait()
        return name

    async def first() -> str:
        return await wait_for_release("first")

    async def second() -> str:
        return await wait_for_release("second")

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[first, second])
    run_task = asyncio.create_task(_run_with_events(agent, "Use both tools", events))

    await both_entered.wait()
    assert entered == {"first", "second"}
    release_tools.set()
    result = await run_task

    assert result.output == "done"
    assert model.request_calls == 2
    assert model.request_stream_calls == 0


@pytest.mark.asyncio
async def test_buffered_model_cancellation_cleans_up_running_tools() -> None:
    entered = asyncio.Event()
    cleaned_up = asyncio.Event()
    events: list[AgentStreamEvent] = []

    async def wait_forever() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()
        return "unreachable"

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[wait_forever])
    run_task = asyncio.create_task(_run_with_events(agent, "Use the tool", events))

    await entered.wait()
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert cleaned_up.is_set()
    assert model.request_calls == 1
    assert model.request_stream_calls == 0


@pytest.mark.asyncio
async def test_buffered_model_propagates_event_handler_failures_without_starting_tools() -> None:
    class EventHandlerError(RuntimeError):
        pass

    tool_started = False

    async def lookup() -> str:
        nonlocal tool_started
        tool_started = True
        return "tool-result"

    async def fail_on_tool_call(
        _ctx: RunContext[object], event_stream: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for event in event_stream:
            if isinstance(event, FunctionToolCallEvent):
                raise EventHandlerError

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[lookup])

    with pytest.raises(EventHandlerError):
        await agent.run("Use the tool", event_stream_handler=fail_on_tool_call)

    assert tool_started is False
    assert model.request_calls == 1
    assert model.request_stream_calls == 0


@pytest.mark.asyncio
async def test_buffered_model_preserves_capability_hooks() -> None:
    counts: Counter[str] = Counter()
    hooks = Hooks()

    @hooks.on.before_model_request
    async def before_model_request(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        counts["before_model_request"] += 1
        return request_context

    @hooks.on.after_model_request
    async def after_model_request(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        del request_context
        counts["after_model_request"] += 1
        return response

    @hooks.on.before_tool_execute
    async def before_tool_execute(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        del call, tool_def
        counts["before_tool_execute"] += 1
        return args

    @hooks.on.after_tool_execute
    async def after_tool_execute(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: Any,
    ) -> Any:
        del call, tool_def, args
        counts["after_tool_execute"] += 1
        return result

    @hooks.on.event
    async def on_event(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[Any], event: AgentStreamEvent
    ) -> AgentStreamEvent:
        counts[f"event:{type(event).__name__}"] += 1
        return event

    async def lookup() -> str:
        return "tool-result"

    model = _CountingTestModel()
    agent = Agent(BufferedResponseModel(model), tools=[lookup], capabilities=[hooks])
    events: list[AgentStreamEvent] = []

    result = await _run_with_events(agent, "Use the tool", events)

    assert result.output == "done"
    assert counts["before_model_request"] == 2
    assert counts["after_model_request"] == 2
    assert counts["before_tool_execute"] == 1
    assert counts["after_tool_execute"] == 1
    assert counts["event:FunctionToolCallEvent"] == 1
    assert counts["event:FunctionToolResultEvent"] == 1
