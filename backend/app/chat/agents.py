from dataclasses import dataclass, field
from typing import Any

import httpx
from jinja2 import Template
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.chat.tools import Deps
from app.core.config import settings


def _get_azure_resource(deployment_name: str) -> tuple[str, str, str]:
    """Get Azure resource credentials for a deployment.

    Returns (api_base, api_version, api_key) for the appropriate resource.
    Uses AZURE_MODEL_RESOURCE_MAP to determine which resource to use.
    Models not in the map default to resource 1.
    """
    # Parse the model-to-resource mapping
    resource_map: dict[str, str] = {}
    if settings.AZURE_MODEL_RESOURCE_MAP:
        for mapping in settings.AZURE_MODEL_RESOURCE_MAP.split(","):
            if ":" in mapping:
                model, resource = mapping.strip().split(":", 1)
                resource_map[model.strip()] = resource.strip()

    # Determine which resource to use (default to 1)
    resource_num = resource_map.get(deployment_name, "1")

    if resource_num == "2":
        return (settings.AZURE_API_BASE_2, settings.AZURE_API_VERSION_2, settings.AZURE_API_KEY_2)
    # Default to resource 1
    return (settings.AZURE_API_BASE_1, settings.AZURE_API_VERSION_1, settings.AZURE_API_KEY_1)


def _get_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.LLM_REQUEST_TIMEOUT)


def get_pydantic_ai_model_name(model_name: str) -> Model | str:
    """Convert litellm-style model names to PydanticAI models.

    Supports:
    - azure/deployment-name -> OpenAIResponsesModel with AzureProvider
    - openrouter/model-name -> OpenAIResponsesModel with OpenAIProvider (openrouter base URL)
    - Standard PydanticAI format (provider:model) is passed through
    """
    if model_name.startswith("azure/"):
        # Azure OpenAI - use the Responses API with AzureProvider
        deployment_name = model_name.split("azure/")[1]
        api_base, api_version, api_key = _get_azure_resource(deployment_name)

        return OpenAIResponsesModel(
            deployment_name,
            provider=AzureProvider(
                azure_endpoint=api_base,
                api_version=api_version,
                api_key=api_key,
                http_client=_get_http_client(),
            ),
        )
    if model_name.startswith("openrouter/"):
        # OpenRouter - use OpenAI-compatible API
        actual_model = model_name.split("openrouter/")[1]
        openrouter_base = "https://openrouter.ai/api/v1"

        return OpenAIResponsesModel(
            actual_model,
            provider=OpenAIProvider(
                base_url=openrouter_base,
                api_key=settings.OPENROUTER_API_KEY,
                http_client=_get_http_client(),
            ),
        )
    if "/" in model_name and ":" not in model_name:
        # Other litellm format like "provider/model" -> try as openai-compatible
        return f"openai:{model_name.rsplit('/', maxsplit=1)[-1]}"

    # Already in PydanticAI format or plain model name
    return model_name


def create_chatbot_agent(
    model: str, tools: list[Any] | None = None, system_prompt: str = ""
) -> Agent[Deps, str]:
    pydantic_model = get_pydantic_ai_model_name(model)

    return Agent(
        pydantic_model,
        output_type=str,
        deps_type=Deps,
        tools=tools or [],
        system_prompt=system_prompt,
    )


def _empty_rejected_attempts() -> list[dict[str, str]]:
    return []


@dataclass
class GuardrailsDeps:
    response_to_check: str = ""
    current_user_message: str = ""
    previous_rejected_attempts: list[dict[str, str]] = field(
        default_factory=_empty_rejected_attempts
    )


class GuardrailsResult(BaseModel):
    """Structured output for the guardrails agent."""  # TODO: check if its passed to prompt

    is_valid: bool = Field(
        description="True if the chatbot response is valid and follows all rules, "
        "False if it requires revision."
    )
    feedback: str | None = Field(
        default=None,
        description="If is_valid is False, provide the reason and instructions for the "
        "necessary changes. If is_valid is True, this should be None.",
    )


class GroundingAgentCannedResponseGrounding(BaseModel):
    """Grounding explanation for prompt/canned wording used in the final answer."""

    title: str = Field(
        description=(
            "Short user-facing label for the prompt/canned rule that grounded part of the answer."
        )
    )
    explanation: str = Field(
        description=(
            "One concise sentence explaining which part of the answer came from approved "
            "assistant instructions or canned wording."
        )
    )


def _empty_canned_response_groundings() -> list[GroundingAgentCannedResponseGrounding]:
    return []


class GroundingAgentResult(BaseModel):
    """Structured output for selecting sources that ground the final answer."""

    grounding_source_keys: list[str] = Field(
        default_factory=list,
        description=(
            "Keys of candidate sources that directly ground claims in the answer, "
            "sorted by relevance with the strongest source first."
        ),
    )
    canned_response_groundings: list[GroundingAgentCannedResponseGrounding] = Field(
        default_factory=_empty_canned_response_groundings,
        description=(
            "One item for each distinct approved assistant instruction or canned-response "
            "rule that grounds part of the answer. Leave empty when no answer text is grounded "
            "by prompt instructions or canned wording."
        ),
    )


def create_guardrails_agent(
    model: str, *, template: Template
) -> Agent[GuardrailsDeps, GuardrailsResult]:
    agent: Agent[GuardrailsDeps, GuardrailsResult] = Agent(
        model=get_pydantic_ai_model_name(model),
        output_type=GuardrailsResult,
        deps_type=GuardrailsDeps,
    )

    @agent.system_prompt
    def _get_system_prompt(ctx: RunContext[GuardrailsDeps]) -> str:  # pyright: ignore[reportUnusedFunction]
        return render_guardrails_system_prompt(template, ctx.deps)

    return agent


def render_guardrails_system_prompt(template: Template, deps: GuardrailsDeps) -> str:
    return template.render(
        chatbot_agent_response=deps.response_to_check,
        current_user_message=deps.current_user_message,
        previous_rejected_attempts=deps.previous_rejected_attempts,
    )


def create_grounding_agent(model: str, system_prompt: str) -> Agent[None, GroundingAgentResult]:
    return Agent(
        model=get_pydantic_ai_model_name(model),
        output_type=GroundingAgentResult,
        system_prompt=system_prompt,
    )
