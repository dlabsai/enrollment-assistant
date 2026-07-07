from openai import AsyncAzureOpenAI

from app.core.config import settings


def get_azure_openai_client() -> AsyncAzureOpenAI:
    """Get an AsyncAzureOpenAI client configured from settings (uses resource 1)."""
    if not settings.AZURE_API_KEY_1:
        raise ValueError("AZURE_API_KEY_1 is required but not set.")
    if not settings.AZURE_API_BASE_1:
        raise ValueError("AZURE_API_BASE_1 is required but not set.")
    if not settings.AZURE_API_VERSION_1:
        raise ValueError("AZURE_API_VERSION_1 is required but not set.")

    return AsyncAzureOpenAI(
        azure_endpoint=settings.AZURE_API_BASE_1,
        api_key=settings.AZURE_API_KEY_1,
        api_version=settings.AZURE_API_VERSION_1,
    )
