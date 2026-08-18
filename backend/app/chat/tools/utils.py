from openai import AsyncAzureOpenAI

from app.chat.provider_http import get_provider_http_client
from app.core.config import settings

_embedding_client: AsyncAzureOpenAI | None = None


def get_azure_openai_client() -> AsyncAzureOpenAI:
    """Return the process-local embedding client configured for resource 1."""
    global _embedding_client  # noqa: PLW0603

    if _embedding_client is not None and not _embedding_client.is_closed():
        return _embedding_client

    if settings.STRESS_FAKE_EMBEDDINGS:
        from app.stress.fake_embedding import create_stress_embedding_client  # noqa: PLC0415

        _embedding_client = create_stress_embedding_client()
        return _embedding_client
    if not settings.AZURE_API_KEY_1:
        raise ValueError("AZURE_API_KEY_1 is required but not set.")
    if not settings.AZURE_API_BASE_1:
        raise ValueError("AZURE_API_BASE_1 is required but not set.")
    if not settings.AZURE_API_VERSION_1:
        raise ValueError("AZURE_API_VERSION_1 is required but not set.")

    _embedding_client = AsyncAzureOpenAI(
        azure_endpoint=settings.AZURE_API_BASE_1,
        api_key=settings.AZURE_API_KEY_1,
        api_version=settings.AZURE_API_VERSION_1,
        http_client=get_provider_http_client(settings.AZURE_API_BASE_1),
    )
    return _embedding_client


async def close_embedding_client() -> None:
    """Close and clear the process-local embedding client during shutdown."""
    global _embedding_client  # noqa: PLW0603

    client = _embedding_client
    _embedding_client = None
    if client is not None and not client.is_closed():
        await client.close()
