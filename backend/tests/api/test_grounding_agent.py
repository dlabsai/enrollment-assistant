from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import grounding_agent
from app.api.message_sources import (
    MessageSourceUsed,
    build_canned_response_source,
    filter_sources_by_keys,
)
from app.chat.agents import GroundingAgentCannedResponseGrounding
from app.models import AssistantMessageMetadata, Conversation, DocumentType, Message


@pytest.mark.asyncio
async def test_select_grounding_source_keys_uses_gpt_55_medium_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = MessageSourceUsed(
        key="tool-1:website_page:42:search:0",
        type=DocumentType.WEBSITE_PAGE,
        id=42,
        title="Tuition and Fees",
        url="https://demo-university.example.edu/tuition",
        usage="search",
        tool_call_id="tool-1",
        tool_name="find_document_chunks",
    )
    captured_model_settings: list[grounding_agent.ModelSettings] = []

    class FakeTemplate:
        def render(self) -> str:
            return "system"

    class FakeEnvironment:
        def get_template(self, name: str) -> FakeTemplate:
            assert name == "grounding_agent.j2"
            return FakeTemplate()

    async def fake_get_runtime_jinja_environment(*_: Any, **__: Any) -> FakeEnvironment:
        return FakeEnvironment()

    async def fake_run_agent(*args: Any, **_: Any) -> tuple[Any, float]:
        captured_model_settings.append(args[2])
        return (
            SimpleNamespace(
                output=grounding_agent.GroundingAgentResult(grounding_source_keys=[source.key])
            ),
            0.0,
        )

    def fake_create_grounding_agent(model: str, system_prompt: str) -> object:
        del model, system_prompt
        return object()

    monkeypatch.setattr(grounding_agent, "create_grounding_agent", fake_create_grounding_agent)
    monkeypatch.setattr(
        grounding_agent, "get_runtime_jinja_environment", fake_get_runtime_jinja_environment
    )
    monkeypatch.setattr(grounding_agent, "run_agent", fake_run_agent)

    selected_keys = await grounding_agent.select_grounding_source_keys(
        user_question="Where is tuition listed?",
        assistant_answer="Tuition is listed at https://demo-university.example.edu/tuition.",
        sources=[source],
    )

    assert selected_keys == [source.key]
    assert len(captured_model_settings) == 1
    assert captured_model_settings[0].model == "azure/gpt-5.5"
    assert captured_model_settings[0].reasoning_effort == "medium"


@pytest.mark.asyncio
async def test_select_grounding_source_keys_sends_canned_response_to_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned_source = build_canned_response_source()
    captured_prompts: list[str] = []

    class FakeTemplate:
        def render(self) -> str:
            return "grounding system"

    class FakeEnvironment:
        def get_template(self, name: str) -> FakeTemplate:
            assert name == "grounding_agent.j2"
            return FakeTemplate()

    async def fake_get_runtime_jinja_environment(*_: Any, **__: Any) -> FakeEnvironment:
        return FakeEnvironment()

    async def fake_run_agent(*args: Any, **_: Any) -> tuple[Any, float]:
        captured_prompts.append(args[1])
        return (
            SimpleNamespace(
                output=grounding_agent.GroundingAgentResult(
                    grounding_source_keys=[canned_source.key],
                    canned_response_groundings=[
                        GroundingAgentCannedResponseGrounding(
                            title="Accreditation script",
                            explanation=(
                                "The accreditation wording came from the approved prompt script."
                            ),
                        )
                    ],
                )
            ),
            0.0,
        )

    def fake_create_grounding_agent(model: str, system_prompt: str) -> object:
        del model, system_prompt
        return object()

    monkeypatch.setattr(grounding_agent, "create_grounding_agent", fake_create_grounding_agent)
    monkeypatch.setattr(
        grounding_agent, "get_runtime_jinja_environment", fake_get_runtime_jinja_environment
    )
    monkeypatch.setattr(grounding_agent, "run_agent", fake_run_agent)

    assistant_answer = (
        'You can tell the prospective student: "Yes, Demo University is an accredited university."'
    )
    chatbot_system_prompt = "When asked about accreditation, use the approved canned wording."
    selected_keys = await grounding_agent.select_grounding_source_keys(
        user_question="Are we accredited?",
        assistant_answer=assistant_answer,
        chatbot_system_prompt=chatbot_system_prompt,
        sources=[canned_source],
    )

    assert selected_keys == [
        {
            "key": canned_source.key,
            "type": "canned_response",
            "id": 0,
            "title": "Accreditation script",
            "explanation": "The accreditation wording came from the approved prompt script.",
        }
    ]
    assert len(captured_prompts) == 1
    assert "Chatbot system prompt:" in captured_prompts[0]
    assert chatbot_system_prompt in captured_prompts[0]
    assert canned_source.key in captured_prompts[0]


@pytest.mark.asyncio
async def test_select_grounding_source_keys_does_not_auto_select_canned_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned_source = build_canned_response_source()

    class FakeTemplate:
        def render(self) -> str:
            return "grounding system"

    class FakeEnvironment:
        def get_template(self, name: str) -> FakeTemplate:
            assert name == "grounding_agent.j2"
            return FakeTemplate()

    async def fake_get_runtime_jinja_environment(*_: Any, **__: Any) -> FakeEnvironment:
        return FakeEnvironment()

    async def fake_run_agent(*_: Any, **__: Any) -> tuple[Any, float]:
        return (SimpleNamespace(output=grounding_agent.GroundingAgentResult()), 0.0)

    def fake_create_grounding_agent(model: str, system_prompt: str) -> object:
        del model, system_prompt
        return object()

    monkeypatch.setattr(grounding_agent, "create_grounding_agent", fake_create_grounding_agent)
    monkeypatch.setattr(
        grounding_agent, "get_runtime_jinja_environment", fake_get_runtime_jinja_environment
    )
    monkeypatch.setattr(grounding_agent, "run_agent", fake_run_agent)

    selected_keys = await grounding_agent.select_grounding_source_keys(
        user_question="Are we accredited?",
        assistant_answer="Demo University is accredited.",
        chatbot_system_prompt="Use the approved accreditation canned response when asked.",
        sources=[canned_source],
    )

    assert selected_keys == []


@pytest.mark.asyncio
async def test_select_grounding_source_keys_ignores_canned_groundings_without_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_source = MessageSourceUsed(
        key="tool-1:website_page:42:search:0",
        type=DocumentType.WEBSITE_PAGE,
        id=42,
        title="Accreditation and Consumer Information",
        url="https://demo-university.example.edu/accreditation-and-consumer-information/",
        usage="search",
        tool_call_id="tool-1",
        tool_name="find_document_chunks",
    )

    class FakeTemplate:
        def render(self) -> str:
            return "grounding system"

    class FakeEnvironment:
        def get_template(self, name: str) -> FakeTemplate:
            assert name == "grounding_agent.j2"
            return FakeTemplate()

    async def fake_get_runtime_jinja_environment(*_: Any, **__: Any) -> FakeEnvironment:
        return FakeEnvironment()

    async def fake_run_agent(*_: Any, **__: Any) -> tuple[Any, float]:
        return (
            SimpleNamespace(
                output=grounding_agent.GroundingAgentResult(
                    canned_response_groundings=[
                        GroundingAgentCannedResponseGrounding(
                            title="Accreditation script",
                            explanation="The answer came from approved prompt wording.",
                        )
                    ]
                )
            ),
            0.0,
        )

    def fake_create_grounding_agent(model: str, system_prompt: str) -> object:
        del model, system_prompt
        return object()

    monkeypatch.setattr(grounding_agent, "create_grounding_agent", fake_create_grounding_agent)
    monkeypatch.setattr(
        grounding_agent, "get_runtime_jinja_environment", fake_get_runtime_jinja_environment
    )
    monkeypatch.setattr(grounding_agent, "run_agent", fake_run_agent)

    selected_keys = await grounding_agent.select_grounding_source_keys(
        user_question="Are we accredited?",
        assistant_answer="Demo University is accredited.",
        chatbot_system_prompt="Use the approved accreditation canned response when asked.",
        sources=[document_source],
    )

    assert selected_keys == []


@pytest.mark.asyncio
async def test_select_grounding_source_keys_allows_document_and_canned_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_source = MessageSourceUsed(
        key="tool-1:website_page:42:search:0",
        type=DocumentType.WEBSITE_PAGE,
        id=42,
        title="Accreditation and Consumer Information",
        url="https://demo-university.example.edu/accreditation-and-consumer-information/",
        usage="search",
        tool_call_id="tool-1",
        tool_name="find_document_chunks",
    )
    canned_source = build_canned_response_source()

    class FakeTemplate:
        def render(self) -> str:
            return "grounding system"

    class FakeEnvironment:
        def get_template(self, name: str) -> FakeTemplate:
            assert name == "grounding_agent.j2"
            return FakeTemplate()

    async def fake_get_runtime_jinja_environment(*_: Any, **__: Any) -> FakeEnvironment:
        return FakeEnvironment()

    async def fake_run_agent(*_: Any, **__: Any) -> tuple[Any, float]:
        return (
            SimpleNamespace(
                output=grounding_agent.GroundingAgentResult(
                    grounding_source_keys=[canned_source.key, document_source.key],
                    canned_response_groundings=[
                        GroundingAgentCannedResponseGrounding(
                            title="Accreditation script",
                            explanation=(
                                "The answer's relay wording came from approved canned instructions."
                            ),
                        ),
                        GroundingAgentCannedResponseGrounding(
                            title="Staff-facing framing",
                            explanation=(
                                "The instruction to frame the script for staff came from the "
                                "internal prompt."
                            ),
                        ),
                    ],
                )
            ),
            0.0,
        )

    def fake_create_grounding_agent(model: str, system_prompt: str) -> object:
        del model, system_prompt
        return object()

    monkeypatch.setattr(grounding_agent, "create_grounding_agent", fake_create_grounding_agent)
    monkeypatch.setattr(
        grounding_agent, "get_runtime_jinja_environment", fake_get_runtime_jinja_environment
    )
    monkeypatch.setattr(grounding_agent, "run_agent", fake_run_agent)

    selected_keys = await grounding_agent.select_grounding_source_keys(
        user_question="Are we accredited?",
        assistant_answer=(
            'You can tell the prospective student: "Yes, Demo University is accredited '
            'university. See https://demo-university.example.edu/accreditation-and-consumer-information/."'
        ),
        chatbot_system_prompt="Use the approved accreditation canned response when asked.",
        sources=[document_source, canned_source],
    )

    assert selected_keys == [
        {
            "key": canned_source.key,
            "type": "canned_response",
            "id": 0,
            "title": "Accreditation script",
            "explanation": "The answer's relay wording came from approved canned instructions.",
        },
        {
            "key": "prompt:canned_response:1:prompt:0",
            "type": "canned_response",
            "id": 1,
            "title": "Staff-facing framing",
            "explanation": (
                "The instruction to frame the script for staff came from the internal prompt."
            ),
        },
        document_source.key,
    ]


def test_filter_sources_by_keys_expands_structured_canned_response_selections() -> None:
    document_source = MessageSourceUsed(
        key="tool-1:website_page:42:search:0",
        type=DocumentType.WEBSITE_PAGE,
        id=42,
        title="Accreditation and Consumer Information",
        url="https://demo-university.example.edu/accreditation-and-consumer-information/",
        usage="search",
        tool_call_id="tool-1",
        tool_name="find_document_chunks",
    )
    canned_source = build_canned_response_source()

    selected_sources = filter_sources_by_keys(
        [document_source, canned_source],
        [
            {
                "key": canned_source.key,
                "type": "canned_response",
                "id": 0,
                "title": "Accreditation script",
                "explanation": "The accreditation wording came from the approved script.",
            },
            {
                "key": "prompt:canned_response:1:prompt:0",
                "type": "canned_response",
                "id": 1,
                "title": "Staff-facing framing",
                "explanation": "The answer framing came from internal instructions.",
            },
            document_source.key,
        ],
    )

    assert [source.key for source in selected_sources] == [
        canned_source.key,
        "prompt:canned_response:1:prompt:0",
        document_source.key,
    ]
    assert selected_sources[0].title == "Accreditation script"
    assert (
        selected_sources[0].explanation
        == "The accreditation wording came from the approved script."
    )
    assert selected_sources[1].title == "Staff-facing framing"
    assert selected_sources[1].explanation == "The answer framing came from internal instructions."


@pytest.mark.asyncio
async def test_select_and_store_grounding_sources_propagates_selection_errors(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = Conversation(title="Grounding test", user=False, project="demo")
    transactional_session.add(conversation)
    await transactional_session.flush()

    user_message = Message(
        conversation_id=conversation.id, role="user", content="Where is tuition listed?"
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="Tuition is listed online.",
        parent=user_message,
    )
    transactional_session.add_all([user_message, assistant_message])
    await transactional_session.flush()

    metadata = AssistantMessageMetadata(
        message_id=assistant_message.id, system_prompt_rendered="system", conversation_turn=1
    )
    transactional_session.add(metadata)
    await transactional_session.flush()

    async def fail_selection(**_: Any) -> list[str]:
        raise RuntimeError("grounding model unavailable")

    monkeypatch.setattr(grounding_agent, "select_grounding_source_keys", fail_selection)

    with pytest.raises(RuntimeError, match="grounding model unavailable"):
        await grounding_agent.select_and_store_grounding_sources(
            transactional_session,
            assistant_message_id=assistant_message.id,
            user_message_id=user_message.id,
            assistant_answer=assistant_message.content,
            sources=[
                MessageSourceUsed(
                    key="tool-1:website_page:42:search:0",
                    type=DocumentType.WEBSITE_PAGE,
                    id=42,
                    title="Tuition and Fees",
                    url="https://demo-university.example.edu/tuition",
                    usage="search",
                    tool_call_id="tool-1",
                    tool_name="find_document_chunks",
                )
            ],
        )

    assert metadata.grounding_source_keys is None
    assert metadata.grounding_source_status is None


@pytest.mark.asyncio
async def test_select_and_store_grounding_sources_fails_when_metadata_is_missing(
    transactional_session: AsyncSession,
) -> None:
    conversation = Conversation(title="Grounding test", user=False, project="demo")
    transactional_session.add(conversation)
    await transactional_session.flush()

    user_message = Message(
        conversation_id=conversation.id, role="user", content="Where is tuition listed?"
    )
    transactional_session.add(user_message)
    await transactional_session.flush()

    missing_assistant_message_id = uuid4()
    with pytest.raises(ValueError, match=str(missing_assistant_message_id)):
        await grounding_agent.select_and_store_grounding_sources(
            transactional_session,
            assistant_message_id=missing_assistant_message_id,
            user_message_id=user_message.id,
            assistant_answer="Tuition is listed online.",
            sources=[],
        )
