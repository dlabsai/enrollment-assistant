from typing import Any

import httpx
from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import settings

router = APIRouter(tags=["models"])

_openrouter_models: list[str] = []


@router.get("/models", response_model=list[str])
async def list_models(_current_user: CurrentUser) -> Any:
    available_models: list[str] = []
    use_openrouter = False

    for model in settings.MODELS.split(","):
        model_name = model.strip()
        if model_name == "":
            continue
        if model_name == "openrouter/*":
            use_openrouter = True
        else:
            available_models.append(model_name)

    if use_openrouter and not _openrouter_models:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://openrouter.ai/api/v1/models")
            response.raise_for_status()
            openrouter_models = response.json()
            for model in openrouter_models.get("data", []):
                supported_parameters = model.get("supported_parameters", [])
                supports_tools = any(
                    parameter in supported_parameters for parameter in ("tools", "tool_choice")
                )
                if supports_tools:
                    model_id = model.get("id", "").strip()
                    if model_id != "":
                        _openrouter_models.append("openrouter/" + model_id)

    return list(dict.fromkeys(available_models + _openrouter_models))
