"""End-to-end integration tests for the chat runtime.

These tests call real LLMs and communicate with a real database.
They require proper environment variables to be set:
- AZURE_API_KEY
- AZURE_API_BASE
- AZURE_API_VERSION

Note: These tests are marked as 'integration' and can be run separately with:
    pytest -m integration -v -s
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.engine import MessageOut, handle_conversation_turn
from app.chat.engine_utils import ModelSettings
from app.core.config import settings
from app.core.db import async_session_factory
from app.models import AssistantMessageMetadata, Conversation, Message, User

# Mark all tests in this module as slow, e2e, and llm tests
# Mark all tests in this module as slow and llm tests
pytestmark = [pytest.mark.slow, pytest.mark.llm]


@pytest.fixture
def integration_model_settings() -> ModelSettings:
    """Model settings for integration tests using real LLMs."""
    return ModelSettings(
        model=settings.CHATBOT_MODEL,
        temperature=settings.CHATBOT_MODEL_TEMPERATURE,
        max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS,
    )


class TestE2EConversation:
    """End-to-end tests that call real LLMs and use real DB."""

    @pytest.mark.asyncio
    async def test_simple_hi_message_new_conversation(
        self, session: AsyncSession, test_user: User, integration_model_settings: ModelSettings
    ):
        """Test a simple 'hi' message creates a new conversation with real LLM response."""
        user_message_id, assistant_message = await handle_conversation_turn(
            project_name="test_project",
            conversation_id=None,
            parent_message_id=None,
            user_prompt="hi",
            is_regeneration=False,
            chatbot_model_settings=integration_model_settings,
            guardrail_model_settings=integration_model_settings,
            user_id=test_user.id,
            session=session,
            tool_session_factory=async_session_factory,
        )

        # Verify response structure
        assert isinstance(assistant_message, MessageOut)
        assert assistant_message.role == "assistant"
        assert assistant_message.content  # Should have some content
        assert len(assistant_message.content) > 0
        assert assistant_message.conversation_id is not None

        # Verify conversation was created in DB
        conversation = await session.get(Conversation, assistant_message.conversation_id)
        assert conversation is not None
        assert conversation.title == "hi"
        assert conversation.project == "test_project"
        assert conversation.user_id == test_user.id

        # Verify user message was created
        user_message = await session.get(Message, user_message_id)
        assert user_message is not None
        assert user_message.role == "user"
        assert user_message.content == "hi"
        assert user_message.conversation_id == conversation.id

        # Verify assistant message was created
        assistant_msg_db = await session.get(Message, assistant_message.id)
        assert assistant_msg_db is not None
        assert assistant_msg_db.role == "assistant"
        assert assistant_msg_db.content == assistant_message.content
        assert assistant_msg_db.parent_id == user_message_id

        # Verify metadata was created
        stmt = select(AssistantMessageMetadata).filter_by(message_id=assistant_message.id)
        result = await session.execute(stmt)
        metadata = result.scalar_one_or_none()
        assert metadata is not None
        assert metadata.conversation_turn == 1
        assert metadata.system_prompt_rendered  # Should have rendered system prompt
        assert assistant_message.metadata is not None
        assert assistant_message.metadata.chatbot_time is not None

        # Print the response for manual inspection
        print(f"\n\nLLM Response to 'hi': {assistant_message.content}\n")

    @pytest.mark.asyncio
    async def test_conversation_continuation(
        self, session: AsyncSession, test_user: User, integration_model_settings: ModelSettings
    ):
        """Test continuing a conversation with a second message."""
        # First turn - start conversation
        _user_message_id_1, assistant_message_1 = await handle_conversation_turn(
            project_name="test_project",
            conversation_id=None,
            parent_message_id=None,
            user_prompt="hi",
            is_regeneration=False,
            chatbot_model_settings=integration_model_settings,
            guardrail_model_settings=integration_model_settings,
            user_id=test_user.id,
            session=session,
            tool_session_factory=async_session_factory,
        )

        conversation_id = assistant_message_1.conversation_id
        assert conversation_id is not None

        # Second turn - continue conversation
        user_message_id_2, assistant_message_2 = await handle_conversation_turn(
            project_name="test_project",
            conversation_id=conversation_id,
            parent_message_id=assistant_message_1.id,
            user_prompt="what programs do you offer?",
            is_regeneration=False,
            chatbot_model_settings=integration_model_settings,
            guardrail_model_settings=integration_model_settings,
            user_id=test_user.id,
            session=session,
            tool_session_factory=async_session_factory,
        )

        # Verify second response
        assert isinstance(assistant_message_2, MessageOut)
        assert assistant_message_2.role == "assistant"
        assert assistant_message_2.content
        assert assistant_message_2.conversation_id == conversation_id

        # Verify conversation turn incremented
        stmt = select(AssistantMessageMetadata).filter_by(message_id=assistant_message_2.id)
        result = await session.execute(stmt)
        metadata = result.scalar_one_or_none()
        assert metadata is not None
        assert metadata.conversation_turn == 2

        # Verify message tree structure
        user_message_2 = await session.get(Message, user_message_id_2)
        assert user_message_2 is not None
        assert user_message_2.parent_id == assistant_message_1.id

        assistant_msg_2_db = await session.get(Message, assistant_message_2.id)
        assert assistant_msg_2_db is not None
        assert assistant_msg_2_db.parent_id == user_message_id_2

        # Count all messages in conversation
        stmt = select(Message).filter_by(conversation_id=conversation_id)
        result = await session.execute(stmt)
        messages = result.scalars().all()
        assert len(messages) == 4  # 2 user + 2 assistant

        print(f"\n\nFirst response: {assistant_message_1.content[:200]}...")
        print(f"\n\nSecond response: {assistant_message_2.content[:200]}...")
