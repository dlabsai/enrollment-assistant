from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chat.tools import utils


@pytest.mark.asyncio
async def test_embedding_client_is_reused_and_closed_with_shared_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await utils.close_embedding_client()

    first_client = MagicMock()
    first_client.is_closed.return_value = False
    first_client.close = AsyncMock()
    second_client = MagicMock()
    second_client.is_closed.return_value = False
    second_client.close = AsyncMock()
    constructor = MagicMock(side_effect=[first_client, second_client])
    transport = MagicMock()

    monkeypatch.setattr(utils.settings, "STRESS_FAKE_EMBEDDINGS", False)
    monkeypatch.setattr(utils.settings, "AZURE_API_BASE_1", "https://resource-one.example/")
    monkeypatch.setattr(utils.settings, "AZURE_API_VERSION_1", "test-version")
    monkeypatch.setattr(utils.settings, "AZURE_API_KEY_1", "test-key")
    monkeypatch.setattr(utils, "AsyncAzureOpenAI", constructor)
    monkeypatch.setattr(utils, "get_provider_http_client", MagicMock(return_value=transport))

    try:
        first = utils.get_azure_openai_client()
        reused = utils.get_azure_openai_client()

        assert first is first_client
        assert reused is first_client
        constructor.assert_called_once_with(
            azure_endpoint="https://resource-one.example/",
            api_key="test-key",
            api_version="test-version",
            http_client=transport,
        )

        await utils.close_embedding_client()
        first_client.close.assert_awaited_once_with()

        recreated = utils.get_azure_openai_client()
        assert recreated is second_client
        assert constructor.call_count == 2
    finally:
        await utils.close_embedding_client()

    second_client.close.assert_awaited_once_with()
