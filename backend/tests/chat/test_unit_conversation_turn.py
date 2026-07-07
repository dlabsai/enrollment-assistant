"""Tests for the handle_conversation_turn function in engine.py."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, SystemPromptPart
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import engine as chat_engine
from app.chat.engine import MessageOut, ModelSettings, handle_conversation_turn
from app.core.config import settings
from app.core.db import async_session_factory
from app.models import AssistantMessageMetadata, Conversation, Message, User


@pytest.fixture
def model_settings() -> ModelSettings:
    """Create default model settings for tests."""
    return ModelSettings(
        model=settings.CHATBOT_MODEL,
        temperature=settings.CHATBOT_MODEL_TEMPERATURE,
        max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS,
    )


@pytest.fixture
def mock_chatbot_result():
    """Create a mock result for chatbot agent."""
    mock_result = MagicMock()
    mock_result.output = "Hello! How can I help you today?"
    mock_usage = MagicMock()
    mock_usage.input_tokens = 200
    mock_usage.output_tokens = 100
    mock_result.usage.return_value = mock_usage
    mock_result.all_messages.return_value = []
    return mock_result


def setup_mock_agents(
    mock_create_chatbot: MagicMock,
    mock_get_runtime_jinja_environment: AsyncMock,
    mock_get_deps_with_jinja_env: MagicMock,
    mock_chatbot_result: MagicMock,
    *,
    chatbot_template: MagicMock | None = None,
) -> AsyncMock:
    """Set up mock agents for tests."""
    # Chatbot agent
    mock_chatbot_agent = AsyncMock()
    mock_chatbot_agent.run = AsyncMock(return_value=mock_chatbot_result)
    mock_create_chatbot.return_value = mock_chatbot_agent

    # Runtime jinja env + deps
    if chatbot_template is None:
        chatbot_template = MagicMock()
        chatbot_template.render.return_value = "Mock chatbot system prompt"
    guardrails_template = MagicMock()
    guardrails_template.render.return_value = "Mock guardrails prompt"

    mock_jinja_env = MagicMock()

    def get_template(name: str) -> MagicMock:
        templates = {
            "chatbot_agent.j2": chatbot_template,
            "guardrails_agent.j2": guardrails_template,
        }
        return templates[name]

    mock_jinja_env.get_template.side_effect = get_template
    mock_get_runtime_jinja_environment.return_value = mock_jinja_env

    mock_deps = MagicMock()
    mock_get_deps_with_jinja_env.return_value = mock_deps

    return mock_chatbot_agent


class TestHandleConversationTurnNewConversation:
    """Tests for starting a new conversation."""

    @pytest.mark.asyncio
    async def test_renders_chatbot_prompt_without_guardrails_feedback_context(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Test that guardrails feedback is not rendered into the main prompt."""
        chatbot_template = MagicMock()
        chatbot_template.render.return_value = "Mock chatbot system prompt"

        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            mock_chatbot_agent = AsyncMock()
            mock_chatbot_agent.run = AsyncMock(return_value=mock_chatbot_result)
            mock_create_chatbot.return_value = mock_chatbot_agent

            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
                chatbot_template=chatbot_template,
            )

            await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="Hello, I need help",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
                is_internal=True,
            )

        assert set(chatbot_template.render.call_args.kwargs) == {"current_date"}

    def test_build_guardrails_feedback_message_uses_system_message(self):
        """Guardrails retry feedback is appended as a separate system message."""
        feedback_message = getattr(chat_engine, "_build_guardrails_feedback_message")(
            "Remove the dollar amount."
        )

        assert isinstance(feedback_message, ModelRequest)
        assert len(feedback_message.parts) == 1
        feedback_part = feedback_message.parts[0]
        assert isinstance(feedback_part, SystemPromptPart)
        assert "Guardrails Agent rejected your previous response" in feedback_part.content
        assert "Remove the dollar amount." in feedback_part.content

    def test_guardrail_retry_count_excludes_initial_attempt(self):
        """Retry telemetry counts chatbot retries, not all guardrail checks."""
        retry_count = getattr(chat_engine, "_guardrail_retry_count_from_attempts")

        assert retry_count(0) == 0
        assert retry_count(1) == 0
        assert retry_count(2) == 1
        assert retry_count(3) == 2

    @pytest.mark.asyncio
    async def test_demo_turn_uses_retrieval_capable_chatbot_prompt(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Demo mode uses the retrieval-capable chatbot prompt."""
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
            )

            _user_message_id, assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="Tell me about business programs",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
                is_internal=True,
            )

        assert mock_create_chatbot.call_args.args[2] == "Mock chatbot system prompt"
        assert assistant_message.metadata is not None

        metadata = await session.scalar(
            select(AssistantMessageMetadata).filter_by(message_id=assistant_message.id)
        )
        assert metadata is not None
        assert metadata.system_prompt_rendered == "Mock chatbot system prompt"

    @pytest.mark.asyncio
    async def test_creates_new_conversation(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Test that handle_conversation_turn creates a new conversation."""
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
            )

            _user_message_id, assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="Hello, I need help",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            # Verify response
            assert isinstance(assistant_message, MessageOut)
            assert assistant_message.role == "assistant"
            assert assistant_message.content == "Hello! How can I help you today?"
            assert assistant_message.conversation_id is not None

            # Verify conversation was created
            conversation = await session.get(Conversation, assistant_message.conversation_id)
            assert conversation is not None
            assert conversation.title == "Hello, I need help"
            assert conversation.project == "test_project"

            # Verify messages were created
            stmt = select(Message).filter_by(conversation_id=conversation.id)
            result = await session.execute(stmt)
            messages = result.scalars().all()
            assert len(messages) == 2  # user + assistant

            # Verify metadata was created
            stmt = select(AssistantMessageMetadata).filter_by(message_id=assistant_message.id)
            result = await session.execute(stmt)
            metadata = result.scalar_one_or_none()
            assert metadata is not None
            assert metadata.conversation_turn == 1

    @pytest.mark.asyncio
    async def test_returns_correct_user_message_id(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Test that the returned user_message_id is correct."""
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
            )

            user_message_id, _assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="Test message",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            # Verify user message exists
            user_message = await session.get(Message, user_message_id)
            assert user_message is not None
            assert user_message.role == "user"
            assert user_message.content == "Test message"


class TestHandleConversationTurnContinuation:
    """Tests for continuing an existing conversation."""

    @pytest.mark.asyncio
    async def test_continues_existing_conversation(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Test that handle_conversation_turn can continue an existing conversation."""
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
            )

            # First turn: create a new conversation
            _, first_assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="First message",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            conversation_id = first_assistant_message.conversation_id
            first_assistant_id = first_assistant_message.id

        # Second turn needs fresh mocks
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            # Update mock response for second turn
            mock_chatbot_result_2 = MagicMock()
            mock_chatbot_result_2.output = "Here's more help for you!"
            mock_chatbot_result_2.usage.return_value = mock_chatbot_result.usage()
            mock_chatbot_result_2.all_messages.return_value = []

            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result_2,
            )

            # Second turn: continue the conversation
            _, second_assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=conversation_id,
                parent_message_id=first_assistant_id,
                user_prompt="Second message",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            # Verify same conversation
            assert second_assistant_message.conversation_id == conversation_id

            # Verify messages count
            stmt = select(Message).filter_by(conversation_id=conversation_id)
            result = await session.execute(stmt)
            messages = result.scalars().all()
            assert len(messages) == 4  # 2 user + 2 assistant


class TestHandleConversationTurnRegeneration:
    """Tests for message regeneration."""

    @pytest.mark.asyncio
    async def test_regenerates_response(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Test that handle_conversation_turn can regenerate a response."""
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
            )

            # First turn: create initial conversation
            user_message_id, first_assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="Help me",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            conversation_id = first_assistant_message.conversation_id
            original_content = first_assistant_message.content

        # Regeneration needs fresh mocks
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            # Update mock for regeneration
            mock_chatbot_result_regen = MagicMock()
            mock_chatbot_result_regen.output = "A better response!"
            mock_chatbot_result_regen.usage.return_value = mock_chatbot_result.usage()
            mock_chatbot_result_regen.all_messages.return_value = []

            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result_regen,
            )

            # Regenerate from the user message
            regen_user_id, regenerated_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=conversation_id,
                parent_message_id=user_message_id,
                user_prompt="Help me",  # Same prompt
                is_regeneration=True,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            # Verify regenerated response is different
            assert regenerated_message.content == "A better response!"
            assert regenerated_message.content != original_content

            # Verify the user_message_id is the same (parent for regeneration)
            assert regen_user_id == user_message_id

            # Verify conversation still has correct number of messages
            # (original user + original assistant + regenerated assistant)
            stmt = select(Message).filter_by(conversation_id=conversation_id)
            result = await session.execute(stmt)
            messages = result.scalars().all()
            assert len(messages) == 3


class TestHandleConversationTurnErrors:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_raises_error_for_nonexistent_conversation(
        self, session: AsyncSession, test_user: User, model_settings: ModelSettings
    ):
        """Test that an error is raised for non-existent conversation."""
        fake_conversation_id = uuid4()
        fake_message_id = uuid4()

        with pytest.raises(ValueError, match=r"Conversation with ID .* not found"):
            await handle_conversation_turn(
                project_name="test_project",
                conversation_id=fake_conversation_id,
                parent_message_id=fake_message_id,
                user_prompt="Test",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
            )

    @pytest.mark.asyncio
    async def test_raises_error_for_nonexistent_parent_message(
        self,
        session: AsyncSession,
        test_user: User,
        model_settings: ModelSettings,
        mock_chatbot_result: MagicMock,
    ):
        """Test that an error is raised for non-existent parent message."""
        # First create a conversation
        with (
            patch("app.chat.engine.create_chatbot_agent") as mock_create_chatbot,
            patch(
                "app.chat.engine.get_runtime_jinja_environment", new_callable=AsyncMock
            ) as mock_get_runtime_jinja_environment,
            patch("app.chat.engine.get_deps_with_jinja_env") as mock_get_deps_with_jinja_env,
        ):
            setup_mock_agents(
                mock_create_chatbot,
                mock_get_runtime_jinja_environment,
                mock_get_deps_with_jinja_env,
                mock_chatbot_result,
            )

            _, assistant_message = await handle_conversation_turn(
                project_name="test_project",
                conversation_id=None,
                parent_message_id=None,
                user_prompt="Test",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
                enable_guardrails=False,
            )

            conversation_id = assistant_message.conversation_id

        # Now try to continue with a fake parent message
        fake_message_id = uuid4()

        with pytest.raises(ValueError, match=r"Parent message with ID .* not found"):
            await handle_conversation_turn(
                project_name="test_project",
                conversation_id=conversation_id,
                parent_message_id=fake_message_id,
                user_prompt="Continue",
                is_regeneration=False,
                chatbot_model_settings=model_settings,
                guardrail_model_settings=model_settings,
                user_id=test_user.id,
                session=session,
                tool_session_factory=async_session_factory,
            )
