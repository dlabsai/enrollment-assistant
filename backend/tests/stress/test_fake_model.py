from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.core.config import settings
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.stress.fake_embedding import create_stress_embedding_client
from app.stress.fake_model import create_stress_model


def test_stress_models_are_role_specific() -> None:
    chatbot = create_stress_model("stress/chatbot")
    guardrail = create_stress_model("stress/guardrail")
    grounding = create_stress_model("stress/grounding")

    assert isinstance(chatbot, TestModel)
    assert chatbot.custom_output_text == "Hello! How can I help you today?"
    assert isinstance(guardrail, TestModel)
    assert guardrail.custom_output_args == {"is_valid": True, "feedback": None}
    assert isinstance(grounding, TestModel)
    assert grounding.custom_output_args == {
        "grounding_source_keys": [],
        "canned_response_groundings": [],
    }


def test_stress_models_are_forbidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="forbidden"):
        create_stress_model("stress/chatbot")


def test_unknown_stress_role_fails() -> None:
    with pytest.raises(ValueError, match="unknown stress model role"):
        create_stress_model("stress/unknown")


@pytest.mark.asyncio
async def test_chatbot_replays_profile_tools_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def find_document_chunks(content_search_query: str) -> str:
        calls.append(f"chunks:{content_search_query}")
        return "chunk"

    async def retrieve_documents(website_page_ids: list[int]) -> str:
        calls.append(f"documents:{website_page_ids}")
        return "document"

    monkeypatch.setattr(settings, "STRESS_FAKE_TOOLS", True)
    monkeypatch.setattr(settings, "STRESS_FAKE_LATENCY_SCALE", 0)
    agent = Agent(
        create_stress_model("stress/chatbot/0"), tools=[find_document_chunks, retrieve_documents]
    )

    result = await agent.run("hi")

    assert result.output == "Hello! How can I help you today?"
    assert calls == ["chunks:admissions stress profile 0", "documents:[1006]"]


@pytest.mark.asyncio
async def test_fake_embedding_client_returns_deterministic_manifold_vector() -> None:
    first = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    second = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    first[0] = 1.0
    second[1] = 1.0
    client = create_stress_embedding_client(embedding_bank=[first, second])
    try:
        first_response = await client.embeddings.create(model="text-embedding-3-large", input="hi")
        second_response = await client.embeddings.create(model="text-embedding-3-large", input="hi")
    finally:
        await client.close()

    embedding = first_response.data[0].embedding
    assert len(embedding) == EMBEDDING_VECTOR_DIMENSIONS
    assert embedding == second_response.data[0].embedding
    assert sum(value * value for value in embedding) == pytest.approx(1.0)
    assert sum(value != 0 for value in embedding) == 2


def test_fake_embeddings_are_forbidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="forbidden"):
        create_stress_embedding_client()
