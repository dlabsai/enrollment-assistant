"""PydanticAI model facade for buffered provider responses with live agent events."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import RunContext
from pydantic_ai.models import CompletedStreamedResponse, KnownModelName, Model, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.settings import ModelSettings


class BufferedResponseModel(WrapperModel):
    """Use complete model requests behind PydanticAI's event-stream interface."""

    def __init__(self, wrapped: Model | str) -> None:
        super().__init__(cast("Model | KnownModelName", wrapped))

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        del run_context
        response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        yield CompletedStreamedResponse(
            response, model_request_parameters=model_request_parameters, replay_events=True
        )
