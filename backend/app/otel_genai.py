from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.baggage import set_baggage
from opentelemetry.trace import Span, SpanKind

_TRACER = trace.get_tracer("demo-va")
_AZURE_OPENAI_PROVIDER = "azure.ai.openai"
_GEN_AI_AGENT_NAME_ATTRIBUTE = "gen_ai.agent.name"


@contextmanager
def genai_agent_name_scope(agent_name: str) -> Generator[None]:
    """Attach a GenAI agent name to instrumented direct model requests in this context."""
    token = otel_context.attach(set_baggage(_GEN_AI_AGENT_NAME_ATTRIBUTE, agent_name))
    try:
        yield
    finally:
        otel_context.detach(token)


@contextmanager
def start_span(
    name: str, *, kind: SpanKind = SpanKind.INTERNAL, attributes: Mapping[str, Any] | None = None
) -> Generator[Span]:
    """Start a native OTel span with application-owned attributes."""
    with _TRACER.start_as_current_span(name, kind=kind, attributes=attributes) as span:
        yield span


@contextmanager
def genai_helper_trace_scope(
    agent_name: str,
    *,
    model: str | None = None,
    conversation_id: str | None = None,
    trigger_message_id: str | None = None,
    is_internal: bool | None = None,
) -> Generator[Span]:
    """Correlate one directly instrumented helper-model request trace."""
    attributes: dict[str, Any] = {"gen_ai.agent.name": agent_name}
    if model is not None:
        attributes["app.is_ai"] = True
        attributes["gen_ai.request.model"] = model
    if conversation_id is not None:
        attributes["app.conversation_id"] = conversation_id
    if trigger_message_id is not None:
        attributes["app.trigger_message_id"] = trigger_message_id
    if is_internal is not None:
        attributes["app.is_internal"] = is_internal

    with (
        start_span(f"invoke_agent {agent_name}", attributes=attributes) as span,
        genai_agent_name_scope(agent_name),
    ):
        yield span


@contextmanager
def start_genai_tool_span(name: str, *, tool_type: str) -> Generator[Span]:
    with start_span(
        f"execute_tool {name}",
        kind=SpanKind.INTERNAL,
        attributes={
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
            "gen_ai.tool.type": tool_type,
        },
    ) as span:
        yield span


@contextmanager
def start_genai_retrieval_span(
    *, data_source_id: str, query: str, top_k: int | None
) -> Generator[Span]:
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "retrieval",
        "gen_ai.data_source.id": data_source_id,
        "gen_ai.retrieval.query.text": query,
    }
    if top_k is not None:
        attributes["gen_ai.request.top_k"] = top_k

    with start_span(
        f"retrieval {data_source_id}", kind=SpanKind.CLIENT, attributes=attributes
    ) as span:
        yield span


@contextmanager
def start_genai_embeddings_span(model: str) -> Generator[Span]:
    with start_span(
        f"embeddings {model}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": "embeddings",
            "gen_ai.provider.name": _AZURE_OPENAI_PROVIDER,
            "gen_ai.request.model": model,
        },
    ) as span:
        yield span


def set_embedding_response_attributes(span: Span, response: Any, *, model: str) -> None:
    span.set_attribute("gen_ai.response.model", model)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None)
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
