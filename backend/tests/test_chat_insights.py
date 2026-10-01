from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Request, Response
from openai import BadRequestError
from pydantic_ai.exceptions import ContentFilterError, ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.grounding_agent import GROUNDING_SOURCE_STATUS_SELECTED
from app.api.message_sources import MessageSourceUsed, build_canned_response_source
from app.api.routes.chat_insights import ChatInsightSummaryOut
from app.chat_insights import classifier as classifier_module
from app.chat_insights import service as service_module
from app.chat_insights.classifier import (
    ChatClassificationInput,
    ClassificationOutputError,
    DocumentClassificationInput,
    build_chat_classification_prompt,
    scrub_chat_text,
    validate_chat_assignment_payload,
    validate_document_assignment_payload,
)
from app.chat_insights.reporting import build_summary
from app.chat_insights.service import (
    CategoryConflictError,
    PreparedRun,
    claim_next_run,
    classifier_fingerprint,
    create_category,
    execute_run,
    finish_run,
    prepare_run,
    reconcile_grounding_references,
    source_group,
    trace_source_key,
    update_category,
)
from app.chat_insights.taxonomy import (
    CLASSIFIER_VERSION,
    REQUEST_TYPES,
    CategoryDefinition,
    category_key,
    document_function_definitions,
    document_subject_definitions,
    topic_definitions,
)
from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
from app.core.security import get_password_hash
from app.main import app
from app.models import (
    AssistantMessageMetadata,
    ChatInsightCategory,
    ChatInsightRun,
    ChatInsightTaxonomyRevision,
    Conversation,
    ConversationTopicClassification,
    Document,
    DocumentType,
    GroundingDocumentClassification,
    GroundingDocumentReference,
    Message,
    RagDocumentExclusion,
    User,
)
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.utils import current_time_utc
from tests.api.auth_helpers import authenticate_client


def test_seed_taxonomies_have_unique_keys_and_explicit_fallbacks() -> None:
    topics = topic_definitions()
    subjects = document_subject_definitions()
    functions = document_function_definitions()

    for definitions in (topics, subjects, functions):
        assert definitions
        assert len({item.key for item in definitions}) == len(definitions)
        assert all(item.description.strip() for item in definitions)
    assert {item.name for item in topics} == {
        "Academic programs and courses",
        "Admissions and applications",
        "Tuition and financial aid",
        "Transfer credit and student records",
        "Academic schedules and policies",
        "Licensure and accreditation",
        "Student support and accessibility",
        "Career development",
        "Technology help",
        "Military and veteran support",
        "Institutional information",
        "Other or unclear",
    }
    assert {item.name for item in subjects} == {
        "Programs and Courses",
        "Admissions and Enrollment",
        "Tuition and Financial Aid",
        "Academic Policy, Records, and Transfer Credit",
        "Licensure and Accreditation",
        "Student Support and Accessibility",
        "Career Services",
        "Institutional Information",
        "General, Mixed, or Other",
    }
    assert {item.name for item in functions} == {
        "Program or Course Description",
        "Policy or Official Reference",
        "Guide or Procedure",
        "FAQ or Overview",
        "Calendar or Schedule",
        "Directory or Contact Information",
        "General, Mixed, or Other Function",
    }
    assert any(item.include and item.exclude for item in subjects)
    assert "other" in REQUEST_TYPES

    taxonomy_text = " ".join(
        value
        for definition in (*topics, *subjects, *functions)
        for value in (
            definition.name,
            definition.description,
            *definition.include,
            *definition.exclude,
        )
    ).casefold()
    for private_inventory_term in (
        "crm",
        "dialer",
        "lead handling",
        "outreach rules",
        "call-transfer",
        "talk track",
        "financial offer review",
        "isir",
        "cancel reason",
        "reject code",
        "re-opening",
        "file completion",
    ):
        assert private_inventory_term not in taxonomy_text


def test_category_key_slugifies_names_and_rejects_blank_names() -> None:
    assert category_key("Tuition, billing, and fees") == "tuition-billing-and-fees"
    with pytest.raises(ValueError, match="letter or number"):
        category_key("---")


def test_scrub_chat_text_removes_structured_identifiers() -> None:
    scrubbed = scrub_chat_text(
        "Email Pat@example.com or call (203) 555-1212. "
        "Open https://example.com/path and use student 123456789."
    )

    assert "Pat@example.com" not in scrubbed
    assert "203" not in scrubbed
    assert "https://" not in scrubbed
    assert "123456789" not in scrubbed
    assert "[email]" in scrubbed
    assert "[phone]" in scrubbed
    assert "[url]" in scrubbed
    assert "[number]" in scrubbed


def _chat_input() -> ChatClassificationInput:
    return ChatClassificationInput(
        conversation_id=uuid4(),
        created_at=datetime.now(UTC),
        branch_hash="branch",
        user_messages=("How much is tuition?",),
    )


def test_chat_prompt_includes_category_boundaries() -> None:
    definition = CategoryDefinition(
        key="billing",
        name="Billing",
        description="Student account charges",
        include=("payment plans",),
        exclude=("financial aid eligibility",),
    )

    prompt = build_chat_classification_prompt([_chat_input()], (definition,))

    assert "Include: payment plans" in prompt
    assert "Exclude: financial aid eligibility" in prompt


@pytest.mark.parametrize(
    ("retry_outcome", "expected_error_count"), [("corrected", 0), ("still-invalid", 1)]
)
@pytest.mark.asyncio
async def test_chat_classifier_retries_invalid_semantic_assignments(
    monkeypatch: pytest.MonkeyPatch, retry_outcome: str, expected_error_count: int
) -> None:
    calls = 0

    async def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        secondary_topics = (
            [] if retry_outcome == "corrected" and calls == 2 else ["drafting-or-script"]
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "assignments": [
                            {
                                "item": 1,
                                "primary_topic": "billing",
                                "secondary_topics": secondary_topics,
                                "request_type": "drafting or script",
                                "confidence": "high",
                            }
                        ]
                    },
                )
            ]
        )

    def get_model(_model_name: str) -> FunctionModel:
        return FunctionModel(respond)

    monkeypatch.setattr(classifier_module, "get_pydantic_ai_model_name", get_model)

    result = await classifier_module.classify_chats(
        [_chat_input()],
        (CategoryDefinition(key="billing", name="Billing", description="Billing questions"),),
        model_name="azure/gpt-5.5",
        run_id=uuid4(),
        stage="primary",
    )

    assert calls == 2
    assert result.error_count == expected_error_count
    assert len(result.classifications) == (0 if expected_error_count else 1)
    if result.classifications:
        assert result.classifications[0].request_type == "drafting or script"
        assert result.classifications[0].secondary_topic_keys == ()


def _chained_model_http_error() -> ModelHTTPError:
    body = {"error": {"message": "provider-debug-marker", "code": "invalid_request"}}
    response = Response(
        400,
        headers={"x-request-id": "req_debug_test"},
        request=Request("POST", "https://example.openai.azure.com/openai/v1/responses"),
    )
    provider_error = BadRequestError("Provider request failed", response=response, body=body)
    error = ModelHTTPError(400, "azure/gpt-5.5", body)
    error.__cause__ = provider_error
    return error


@pytest.mark.parametrize(
    ("error", "expected_metadata", "expected_details"),
    [
        pytest.param(
            ContentFilterError(
                "Content filter triggered. Finish reason: 'content_filter'",
                body=json.dumps(
                    [
                        {
                            "kind": "response",
                            "provider_name": "azure",
                            "finish_reason": "content_filter",
                            "provider_details": {
                                "finish_reason": "content_filter",
                                "content_filter_result": {
                                    "jailbreak": {"detected": True, "filtered": True}
                                },
                            },
                        }
                    ]
                ),
            ),
            "exception=ContentFilterError status=None request_id=None",
            ("content_filter", "jailbreak", '"detected": true', '"filtered": true'),
            id="azure-content-filter",
        ),
        pytest.param(
            _chained_model_http_error(),
            "exception=ModelHTTPError status=400 request_id=req_debug_test",
            ("provider-debug-marker", "invalid_request"),
            id="provider-http-error",
        ),
    ],
)
@pytest.mark.asyncio
async def test_classification_batch_failure_logs_full_provider_exception(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected_metadata: str,
    expected_details: tuple[str, ...],
) -> None:
    async def fail_batch(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(classifier_module, "_classify_chat_batch", fail_batch)
    monkeypatch.setattr(classifier_module.logger, "disabled", False)
    monkeypatch.setattr(classifier_module.logger, "propagate", True)
    caplog.set_level(logging.ERROR, logger="demo-va")
    run_id = uuid4()

    result = await classifier_module.classify_chats(
        [_chat_input()],
        (CategoryDefinition(key="billing", name="Billing", description="Billing questions"),),
        model_name="azure/gpt-5.5",
        run_id=run_id,
        stage="primary",
    )

    assert result.error_count == 1
    assert f"run_id={run_id} kind=chat stage=primary batch=1/1 batch_size=1" in caplog.text
    assert expected_metadata in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert all(detail in caplog.text for detail in expected_details)


@pytest.mark.asyncio
@pytest.mark.usefixtures("db_engine")
async def test_run_failure_logs_full_exception(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_run(_claim: service_module.RunClaim) -> None:
        raise RuntimeError("run-debug-marker")

    monkeypatch.setattr(service_module, "_execute_claim_work", fail_run)
    monkeypatch.setattr(service_module.logger, "disabled", False)
    caplog.set_level(logging.ERROR, logger="demo-va")
    claim = service_module.RunClaim(run_id=uuid4(), token=uuid4())

    await execute_run(claim)

    assert f"Chat-insight run {claim.run_id} failed" in caplog.text
    assert "RuntimeError: run-debug-marker" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text


_INVALID_CHAT_ASSIGNMENTS: list[tuple[list[dict[str, object]], str]] = [
    ([], "Missing item numbers"),
    (
        [
            {
                "item": 1,
                "primary_topic": "billing",
                "secondary_topics": [],
                "request_type": "information lookup",
                "confidence": "high",
            },
            {
                "item": 1,
                "primary_topic": "billing",
                "secondary_topics": [],
                "request_type": "information lookup",
                "confidence": "high",
            },
        ],
        "Duplicate item number",
    ),
    (
        [
            {
                "item": 1,
                "primary_topic": "not-a-category",
                "secondary_topics": [],
                "request_type": "information lookup",
                "confidence": "high",
            }
        ],
        "Invalid primary topic",
    ),
    (
        [
            {
                "item": 1,
                "primary_topic": "billing",
                "secondary_topics": [],
                "request_type": "not-a-request-type",
                "confidence": "high",
            }
        ],
        "Invalid request type",
    ),
]


@pytest.mark.parametrize(("assignments", "message"), _INVALID_CHAT_ASSIGNMENTS)
def test_chat_assignment_validation_fails_closed(
    assignments: list[dict[str, object]], message: str
) -> None:
    definitions = (
        CategoryDefinition(key="billing", name="Billing", description="Billing questions"),
    )

    with pytest.raises(ClassificationOutputError, match=message):
        validate_chat_assignment_payload([_chat_input()], definitions, {"assignments": assignments})


@pytest.mark.parametrize(
    ("primary", "secondary", "message"),
    [
        ("Billing", ["aid"], "Invalid primary topic"),
        ("billing", ["billing"], "duplicates primary key"),
        ("billing", ["aid", "aid"], "Duplicate secondary topic"),
    ],
)
def test_assignment_validation_rejects_names_and_duplicate_topic_keys(
    primary: str, secondary: list[str], message: str
) -> None:
    definitions = (
        CategoryDefinition(key="billing", name="Billing", description="Billing questions"),
        CategoryDefinition(key="aid", name="Financial Aid", description="Aid questions"),
    )

    with pytest.raises(ClassificationOutputError, match=message):
        validate_chat_assignment_payload(
            [_chat_input()],
            definitions,
            {
                "assignments": [
                    {
                        "item": 1,
                        "primary_topic": primary,
                        "secondary_topics": secondary,
                        "request_type": "information lookup",
                        "confidence": "high",
                    }
                ]
            },
        )


def test_document_assignment_validation_rejects_unknown_function() -> None:
    row = DocumentClassificationInput(
        source_key="website_page:1",
        source_type="website_page",
        title="Example",
        url="https://example.com",
        content_hash="content",
        evidence_basis="document content",
        evidence="Example content",
    )

    payload: dict[str, object] = {
        "assignments": [
            {
                "item": 1,
                "primary_subject": document_subject_definitions()[0].key,
                "secondary_subjects": [],
                "document_function": "not-a-function",
                "confidence": "high",
            }
        ]
    }
    with pytest.raises(ClassificationOutputError, match="Invalid document function"):
        validate_document_assignment_payload(
            [row], document_subject_definitions(), document_function_definitions(), payload
        )


def test_document_assignment_validation_rejects_duplicate_secondary_subjects() -> None:
    row = DocumentClassificationInput(
        source_key="website_page:1",
        source_type="website_page",
        title="Example",
        url="https://example.com",
        content_hash="content",
        evidence_basis="document content",
        evidence="Example content",
    )
    subjects = document_subject_definitions()
    payload = {
        "assignments": [
            {
                "item": 1,
                "primary_subject": subjects[0].key,
                "secondary_subjects": [subjects[1].key, subjects[1].key],
                "document_function": document_function_definitions()[0].key,
                "confidence": "high",
            }
        ]
    }

    with pytest.raises(ClassificationOutputError, match="Duplicate secondary subject"):
        validate_document_assignment_payload(
            [row], subjects, document_function_definitions(), payload
        )


def test_classifier_fingerprint_covers_model_and_taxonomy_contract() -> None:
    definitions = (
        CategoryDefinition(key="billing", name="Billing", description="Billing questions"),
    )
    renamed = (
        CategoryDefinition(key="billing", name="Student Billing", description="Billing questions"),
    )

    baseline = classifier_fingerprint(
        kind="chat", model_name="azure/gpt-5.5", classifier_version="2", definitions=definitions
    )

    assert baseline != classifier_fingerprint(
        kind="chat", model_name="azure/gpt-5.6", classifier_version="2", definitions=definitions
    )
    assert baseline != classifier_fingerprint(
        kind="chat", model_name="azure/gpt-5.5", classifier_version="2", definitions=renamed
    )
    assert baseline != classifier_fingerprint(
        kind="chat", model_name="azure/gpt-5.5", classifier_version="3", definitions=definitions
    )


def test_trace_source_keys_use_stable_type_specific_identity() -> None:
    assert (
        trace_source_key(
            source_type=DocumentType.TRAINING_MATERIAL.value,
            source_id=-123,
            title="Policies/Refunds.pdf",
            url="https://files.example/Refunds.pdf",
        )
        == "training_material:Policies/Refunds.pdf"
    )
    assert (
        trace_source_key(
            source_type=DocumentType.WEBSITE_PAGE.value,
            source_id=123,
            title="Admissions",
            url="https://example.com/admissions",
        )
        == "website_page:123"
    )
    assert (
        trace_source_key(
            source_type=DocumentType.WEBSITE_PAGE.value,
            source_id=-123,
            title="Calendar: dynamic",
            url="https://example.com/calendar",
        )
        == "website_page:-123"
    )


@pytest.mark.asyncio
async def test_summary_keeps_default_trend_range_compact(
    transactional_session: AsyncSession,
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    short = ChatInsightSummaryOut.model_validate(
        await build_summary(transactional_session, start=start, end=start + timedelta(days=30))
    )
    default = ChatInsightSummaryOut.model_validate(
        await build_summary(transactional_session, start=start, end=start + timedelta(days=90))
    )

    assert short.time_granularity == "day"
    assert len(short.topic_trends[0].points) == 31
    assert default.time_granularity == "week"
    assert len(default.topic_trends[0].points) <= 15


def test_source_group_hides_implementation_specific_source_types_and_rejects_drift() -> None:
    assert source_group(DocumentType.TRAINING_MATERIAL.value) == "training_materials"
    for document_type in (
        DocumentType.WEBSITE_PAGE,
        DocumentType.WEBSITE_PROGRAM,
        DocumentType.CATALOG_PAGE,
        DocumentType.CATALOG_PROGRAM,
        DocumentType.CATALOG_COURSE,
    ):
        assert source_group(document_type.value) == "website_content"
    with pytest.raises(ValueError, match="Unknown grounding document type"):
        source_group("new-unmapped-source")


async def _new_user(session: AsyncSession, *, group_slug: SystemGroupSlug, prefix: str) -> User:
    group = await get_group_for_slug(session, group_slug)
    user = User(
        email=f"{prefix}-{uuid4()}@example.com",
        name="Chat Insight Test User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_prepare_run_uses_active_branch_and_excludes_ineligible_chats(
    transactional_session: AsyncSession,
) -> None:
    owner = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.USER, prefix="eligible-owner"
    )
    developer = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="excluded-developer"
    )
    now = current_time_utc()

    def conversation(
        title: str,
        *,
        user_id: UUID,
        is_public: bool = False,
        prompt_source: str | None = None,
        kind: str = "chat",
    ) -> Conversation:
        return Conversation(
            title=title,
            user=False,
            project="generic",
            user_id=user_id,
            is_public=is_public,
            prompt_source=prompt_source,
            kind=kind,
            created_at=now,
            updated_at=now,
        )

    eligible = conversation("Eligible", user_id=owner.id)
    public = conversation("Public", user_id=owner.id, is_public=True)
    draft = conversation("Draft", user_id=owner.id, prompt_source="draft")
    investigation = conversation("Investigation", user_id=owner.id, kind="investigation")
    developer_chat = conversation("Developer", user_id=developer.id)
    root = Message(
        role="user", content="Root question", conversation=eligible, created_at=now, updated_at=now
    )
    assistant = Message(
        role="assistant",
        content="Answer",
        conversation=eligible,
        parent=root,
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    active = Message(
        role="user",
        content="Active follow-up",
        conversation=eligible,
        parent=assistant,
        created_at=now + timedelta(seconds=2),
        updated_at=now + timedelta(seconds=2),
    )
    inactive = Message(
        role="user",
        content="Inactive follow-up",
        conversation=eligible,
        parent=assistant,
        created_at=now + timedelta(seconds=3),
        updated_at=now + timedelta(seconds=3),
    )
    transactional_session.add_all(
        [eligible, public, draft, investigation, developer_chat, root, assistant, active, inactive]
    )
    await transactional_session.flush()
    eligible.active_root_message_id = root.id
    root.active_child_id = assistant.id
    assistant.active_child_id = active.id
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="running",
        requested_by_user_id=owner.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=now + timedelta(minutes=1),
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
    )

    prepared = await prepare_run(transactional_session, run)

    assert [chat.conversation_id for chat in prepared.all_chats] == [eligible.id]
    assert prepared.all_chats[0].user_messages == ("Root question", "Active follow-up")

    input_hash = prepared.all_chats[0].branch_hash
    assistant.content = "A regenerated answer that is not classifier input"
    await transactional_session.flush()
    regenerated = await prepare_run(transactional_session, run)

    assert regenerated.all_chats[0].branch_hash == input_hash


@pytest.mark.asyncio
async def test_prepare_run_materializes_selected_documents_but_not_canned_guidance(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.USER, prefix="grounding-owner"
    )
    now = current_time_utc()
    conversation = Conversation(
        title="Grounded chat",
        user=False,
        project="generic",
        user_id=owner.id,
        is_public=False,
        created_at=now,
        updated_at=now,
    )
    user_message = Message(
        role="user",
        content="What is the policy?",
        conversation=conversation,
        created_at=now,
        updated_at=now,
    )
    assistant_message = Message(
        role="assistant",
        content="The policy applies.",
        conversation=conversation,
        parent=user_message,
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    document = Document(
        type=DocumentType.TRAINING_MATERIAL,
        id_=-999,
        source_key="training_material:Policies/Policy.pdf",
        title="Policies/Policy.pdf",
        url="training-materials://Policies/Policy.pdf",
        markdown_content="Policy details.",
        token_count=2,
        character_count=15,
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    transactional_session.add_all([conversation, user_message, assistant_message, document])
    await transactional_session.flush()
    conversation.active_root_message_id = user_message.id
    user_message.active_child_id = assistant_message.id
    document_source = MessageSourceUsed(
        key="tool:training_material:-123:search:0",
        type=DocumentType.TRAINING_MATERIAL,
        id=-123,
        title="Policies/Policy.pdf",
        url="https://sharepoint.example/Policies/Policy.pdf",
        usage="search",
        tool_call_id="tool",
        tool_name="find_document_chunks",
        chunk="Policy details.",
    )
    unverified_source = document_source.model_copy(
        update={
            "key": "legacy:training-material:-999",
            "id": -999,
            "identity_from_current_document": True,
        }
    )
    canned_source = build_canned_response_source()
    metadata = AssistantMessageMetadata(
        message_id=assistant_message.id,
        system_prompt_rendered="System prompt",
        conversation_turn=1,
        chatbot_model_settings={"model": "test"},
        grounding_source_status=GROUNDING_SOURCE_STATUS_SELECTED,
        grounding_source_keys=[document_source.key, unverified_source.key, canned_source.key],
    )
    transactional_session.add(metadata)
    await transactional_session.flush()

    async def fake_tool_sources(
        _session: AsyncSession, message_ids: list[UUID]
    ) -> dict[UUID, list[MessageSourceUsed]]:
        assert message_ids == [assistant_message.id]
        return {assistant_message.id: [document_source, unverified_source, canned_source]}

    monkeypatch.setattr(service_module, "_tool_sources", fake_tool_sources)
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="running",
        requested_by_user_id=owner.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=now + timedelta(minutes=1),
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
    )

    prepared = await prepare_run(transactional_session, run)

    assert prepared.selected_grounding_answers == 1
    assert prepared.references[0].source_key == document.source_key
    unverified_reference = prepared.references[1]
    assert unverified_reference.source_key.startswith("historical-unverified:")
    assert unverified_reference.document_id is None
    assert [item.source_key for item in prepared.all_documents] == [document.source_key]

    content_hash = prepared.all_documents[0].content_hash
    document_source.chunk = "A different selected excerpt from the same document."
    changed_evidence = await prepare_run(transactional_session, run)

    assert changed_evidence.all_documents[0].content_hash != content_hash


@pytest.mark.asyncio
async def test_grounding_reference_reconciliation_retains_unresolved_history(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.USER, prefix="reference-owner"
    )
    created_at = current_time_utc()
    conversation = Conversation(
        title="Reference retention",
        user=False,
        project="generic",
        user_id=user.id,
        is_public=False,
        created_at=created_at,
        updated_at=created_at,
    )
    user_message = Message(
        role="user",
        content="What is the policy?",
        conversation=conversation,
        created_at=created_at,
        updated_at=created_at,
    )
    assistant_message = Message(
        role="assistant",
        content="Answer",
        conversation=conversation,
        parent=user_message,
        created_at=created_at + timedelta(seconds=1),
        updated_at=created_at + timedelta(seconds=1),
    )
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="running",
        requested_by_user_id=user.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=created_at + timedelta(minutes=1),
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
    )
    transactional_session.add_all([conversation, user_message, assistant_message, run])
    await transactional_session.flush()
    conversation.active_root_message_id = user_message.id
    user_message.active_child_id = assistant_message.id
    metadata = AssistantMessageMetadata(
        message_id=assistant_message.id,
        system_prompt_rendered="System prompt",
        conversation_turn=1,
        chatbot_model_settings={"model": "test"},
        grounding_source_status=GROUNDING_SOURCE_STATUS_SELECTED,
        grounding_source_keys=["missing-tool-source"],
    )
    reference = GroundingDocumentReference(
        assistant_message_id=assistant_message.id,
        conversation_id=conversation.id,
        run_id=run.id,
        document_id=None,
        source_key="historical:website_page:1:test",
        source_type=DocumentType.WEBSITE_PAGE.value,
        source_group="website_content",
        title="Historical page",
        url="https://example.com/old",
        usage="search",
        branch_hash="branch",
        selected_at=assistant_message.created_at,
        is_protected=False,
    )
    transactional_session.add_all([metadata, reference])
    await transactional_session.flush()

    async def missing_tool_sources(
        _session: AsyncSession, _message_ids: list[UUID]
    ) -> dict[UUID, list[MessageSourceUsed]]:
        return {}

    monkeypatch.setattr(service_module, "_tool_sources", missing_tool_sources)
    unresolved = await prepare_run(transactional_session, run)

    assert unresolved.stale_reference_ids == ()
    await reconcile_grounding_references(
        transactional_session,
        run_id=run.id,
        eligible_conversation_ids=unresolved.eligible_conversation_ids,
        stale_reference_ids=unresolved.stale_reference_ids,
        references=unresolved.references,
        now=created_at,
    )
    assert await transactional_session.get(GroundingDocumentReference, reference.id) is reference

    metadata.grounding_source_status = "no_selection"
    metadata.grounding_source_keys = []
    authoritative = await prepare_run(transactional_session, run)

    assert authoritative.stale_reference_ids == (reference.id,)
    await reconcile_grounding_references(
        transactional_session,
        run_id=run.id,
        eligible_conversation_ids=authoritative.eligible_conversation_ids,
        stale_reference_ids=authoritative.stale_reference_ids,
        references=authoritative.references,
        now=created_at,
    )
    assert await transactional_session.get(GroundingDocumentReference, reference.id) is None


@pytest.mark.asyncio
async def test_summary_includes_generic_reference_rows_and_counts(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="protected-owner"
    )
    now = current_time_utc()
    conversation = Conversation(
        title="Generic references",
        user=False,
        project="generic",
        user_id=user.id,
        is_public=False,
        created_at=now,
        updated_at=now,
    )
    visible_message = Message(
        role="assistant",
        content="Visible answer",
        conversation=conversation,
        created_at=now,
        updated_at=now,
    )
    protected_message = Message(
        role="assistant",
        content="Protected answer",
        conversation=conversation,
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="completed",
        requested_by_user_id=user.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=now,
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
        finished_at=now,
        document_grounded_answers=2,
        referenced_documents=2,
        classified_documents=2,
    )
    transactional_session.add_all([conversation, visible_message, protected_message, run])
    await transactional_session.flush()
    transactional_session.add_all(
        [
            GroundingDocumentReference(
                assistant_message_id=visible_message.id,
                conversation_id=conversation.id,
                run_id=run.id,
                document_id=None,
                source_key="training_material:Public.pdf",
                source_type=DocumentType.TRAINING_MATERIAL.value,
                source_group="training_materials",
                title="Public.pdf",
                url="https://example.com/public.pdf",
                usage="search",
                branch_hash="branch",
                selected_at=visible_message.created_at,
                is_protected=False,
            ),
            GroundingDocumentReference(
                assistant_message_id=protected_message.id,
                conversation_id=conversation.id,
                run_id=run.id,
                document_id=None,
                source_key="training_material:Protected.pdf",
                source_type=DocumentType.TRAINING_MATERIAL.value,
                source_group="training_materials",
                title="Second.pdf",
                url="https://example.com/second.pdf",
                usage="search",
                branch_hash="branch",
                selected_at=protected_message.created_at,
                is_protected=False,
            ),
        ]
    )
    await transactional_session.flush()

    summary = ChatInsightSummaryOut.model_validate(
        await build_summary(transactional_session, start=None, end=None)
    )

    assert summary.coverage.document_grounded_answers == 2
    assert summary.coverage.referenced_documents == 2
    assert {document.source_key for document in summary.top_documents} == {
        "training_material:Public.pdf",
        "training_material:Protected.pdf",
    }
    assert summary.latest_run is not None
    assert set(summary.latest_run.model_dump()) == {"id", "status", "error_count", "error_code"}


@pytest.mark.asyncio
async def test_topic_document_mix_counts_distinct_grounded_answers(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="topic-document-owner"
    )
    now = current_time_utc()
    conversation = Conversation(
        title="One answer with two documents",
        user=False,
        project="generic",
        user_id=user.id,
        is_public=False,
        created_at=now,
        updated_at=now,
    )
    assistant_message = Message(
        role="assistant",
        content="Grounded answer",
        conversation=conversation,
        created_at=now,
        updated_at=now,
    )
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="completed",
        requested_by_user_id=user.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=now,
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
        finished_at=now,
    )
    transactional_session.add_all([conversation, assistant_message, run])
    await transactional_session.flush()
    topic = topic_definitions()[0]
    subject = document_subject_definitions()[0]
    function = document_function_definitions()[0]
    transactional_session.add(
        ConversationTopicClassification(
            conversation_id=conversation.id,
            taxonomy_revision_id=revision.id,
            run_id=run.id,
            branch_hash="input-hash",
            classifier_fingerprint="fingerprint",
            primary_topic_key=topic.key,
            secondary_topic_keys=[],
            request_type=REQUEST_TYPES[0],
            confidence="high",
            source_created_at=now,
            classified_at=now,
        )
    )
    for index in range(2):
        source_key = f"website_page:distinct-answer-{index}"
        transactional_session.add_all(
            [
                GroundingDocumentReference(
                    assistant_message_id=assistant_message.id,
                    conversation_id=conversation.id,
                    run_id=run.id,
                    document_id=None,
                    source_key=source_key,
                    source_type=DocumentType.WEBSITE_PAGE.value,
                    source_group="website_content",
                    title=f"Source {index}",
                    url=f"https://example.com/source-{index}",
                    usage="search",
                    branch_hash="branch",
                    selected_at=now,
                    is_protected=False,
                ),
                GroundingDocumentClassification(
                    source_key=source_key,
                    run_id=run.id,
                    content_hash=f"content-{index}",
                    classifier_fingerprint="fingerprint",
                    primary_subject_key=subject.key,
                    secondary_subject_keys=[],
                    document_function_key=function.key,
                    confidence="high",
                    evidence_basis="document content",
                    classified_at=now,
                ),
            ]
        )
    await transactional_session.flush()

    summary = ChatInsightSummaryOut.model_validate(
        await build_summary(transactional_session, start=None, end=None)
    )
    topic_metric = next(item for item in summary.topics if item.key == topic.key)

    assert topic_metric.top_document_subjects[0].answers == 1
    assert topic_metric.top_document_functions[0].answers == 1


@pytest.mark.asyncio
async def test_category_rename_reserves_the_normalized_display_name(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="category-rename-owner"
    )
    category = ChatInsightCategory(
        key="original-category-name",
        name="Original category name",
        description="Questions in the original client category.",
        include_examples=[],
        exclude_examples=[],
        origin="client",
        active=True,
        created_by_user_id=user.id,
    )
    transactional_session.add(category)
    await transactional_session.flush()

    renamed, _run = await update_category(
        transactional_session,
        category_key_value=category.key,
        name="Renamed category",
        description=category.description,
        include_examples=[],
        exclude_examples=[],
        active=True,
        requested_by_user_id=user.id,
    )

    assert renamed.key == "original-category-name"
    with pytest.raises(CategoryConflictError, match="this name"):
        await create_category(
            transactional_session,
            name="Renamed category",
            description="A different category with the same normalized display name.",
            include_examples=[],
            exclude_examples=[],
            requested_by_user_id=user.id,
        )


@pytest.mark.asyncio
async def test_unchanged_category_update_does_not_queue_another_backfill(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="category-owner"
    )
    category, run = await create_category(
        transactional_session,
        name="Employer partnerships",
        description="Questions about employer partnership benefits.",
        include_examples=["partner tuition benefit"],
        exclude_examples=["general tuition question"],
        requested_by_user_id=user.id,
    )

    unchanged, queued_run = await update_category(
        transactional_session,
        category_key_value=category.key,
        name=category.name,
        description=category.description,
        include_examples=list(category.include_examples),
        exclude_examples=list(category.exclude_examples),
        active=category.active,
        requested_by_user_id=user.id,
    )

    assert unchanged.id == category.id
    assert queued_run is None
    active_runs = int(
        await transactional_session.scalar(
            select(func.count())
            .select_from(ChatInsightRun)
            .where(ChatInsightRun.status.in_(["queued", "running"]))
        )
        or 0
    )
    assert active_runs == 1
    assert run.status == "queued"


@pytest.mark.asyncio
async def test_failed_pending_backfill_does_not_publish_partial_revision(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="atomic-owner"
    )
    _category, run = await create_category(
        transactional_session,
        name="Employer partnerships",
        description="Questions about employer partnership benefits.",
        include_examples=[],
        exclude_examples=[],
        requested_by_user_id=user.id,
    )
    run.status = "running"
    chat = _chat_input()
    prepared = PreparedRun(
        definitions=topic_definitions(),
        chat_classifier_fingerprint="chat-fingerprint",
        document_classifier_fingerprint="document-fingerprint",
        all_chats=(chat,),
        pending_chats=(chat,),
        references=(),
        stale_reference_ids=(),
        eligible_conversation_ids=(chat.conversation_id,),
        all_documents=(),
        pending_documents=(),
        existing_chats={},
        existing_documents={},
        selected_grounding_answers=0,
    )

    await finish_run(
        transactional_session,
        run,
        prepared,
        (),
        (),
        error_count=1,
        stability_metrics={"warning": False},
    )

    pending = await transactional_session.get(ChatInsightTaxonomyRevision, run.taxonomy_revision_id)
    published_number = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision.number).where(
            ChatInsightTaxonomyRevision.status == "published"
        )
    )
    assert pending is not None
    assert pending.status == "pending"
    assert published_number == 1
    assert run.status == "completed_with_errors"
    assert run.classified_chats == 0


@pytest.mark.asyncio
async def test_failed_changed_inputs_are_removed_instead_of_reported_as_current(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="stale-owner"
    )
    now = current_time_utc()
    conversation = Conversation(
        title="Changed chat",
        user=False,
        project="generic",
        user_id=user.id,
        is_public=False,
        created_at=now,
        updated_at=now,
    )
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="running",
        requested_by_user_id=user.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=now,
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
    )
    transactional_session.add_all([conversation, run])
    await transactional_session.flush()
    stale = ConversationTopicClassification(
        conversation_id=conversation.id,
        taxonomy_revision_id=revision.id,
        run_id=run.id,
        branch_hash="old-branch",
        classifier_fingerprint="old-fingerprint",
        primary_topic_key="other-or-unclear",
        secondary_topic_keys=[],
        request_type="other",
        confidence="low",
        source_created_at=now,
        classified_at=now,
    )
    stale_document = GroundingDocumentClassification(
        source_key="website_page:123",
        run_id=run.id,
        content_hash="old-content",
        classifier_fingerprint="old-fingerprint",
        primary_subject_key="general-mixed-or-other",
        secondary_subject_keys=[],
        document_function_key="general-mixed-or-other-function",
        confidence="low",
        evidence_basis="document content",
        classified_at=now,
    )
    transactional_session.add_all([stale, stale_document])
    await transactional_session.flush()
    chat = ChatClassificationInput(
        conversation_id=conversation.id,
        created_at=now,
        branch_hash="new-branch",
        user_messages=("A changed question",),
    )
    document = DocumentClassificationInput(
        source_key="website_page:123",
        source_type=DocumentType.WEBSITE_PAGE.value,
        title="Changed page",
        url="https://example.com/changed",
        content_hash="new-content",
        evidence_basis="document content",
        evidence="Changed content",
    )
    prepared = PreparedRun(
        definitions=topic_definitions(),
        chat_classifier_fingerprint="new-fingerprint",
        document_classifier_fingerprint="document-fingerprint",
        all_chats=(chat,),
        pending_chats=(chat,),
        references=(),
        stale_reference_ids=(),
        eligible_conversation_ids=(conversation.id,),
        all_documents=(document,),
        pending_documents=(document,),
        existing_chats={conversation.id: stale},
        existing_documents={document.source_key: stale_document},
        selected_grounding_answers=0,
    )

    await finish_run(
        transactional_session,
        run,
        prepared,
        (),
        (),
        error_count=1,
        stability_metrics={"warning": False},
    )

    remaining = int(
        await transactional_session.scalar(
            select(func.count())
            .select_from(ConversationTopicClassification)
            .where(ConversationTopicClassification.id == stale.id)
        )
        or 0
    )
    remaining_document = int(
        await transactional_session.scalar(
            select(func.count())
            .select_from(GroundingDocumentClassification)
            .where(GroundingDocumentClassification.id == stale_document.id)
        )
        or 0
    )
    assert remaining == 0
    assert remaining_document == 0
    assert run.classified_chats == 0
    assert run.eligible_chats == 1
    assert run.status == "completed_with_errors"


@pytest.mark.asyncio
async def test_run_reports_total_current_document_classification_coverage(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="document-coverage-owner"
    )
    now = current_time_utc()
    revision = await transactional_session.scalar(
        select(ChatInsightTaxonomyRevision).where(ChatInsightTaxonomyRevision.status == "published")
    )
    assert revision is not None
    run = ChatInsightRun(
        trigger="manual",
        status="running",
        requested_by_user_id=user.id,
        taxonomy_revision_id=revision.id,
        cutoff_at=now,
        full_backfill=False,
        model_name="azure/gpt-5.5",
        classifier_version="test",
    )
    transactional_session.add(run)
    await transactional_session.flush()
    document = DocumentClassificationInput(
        source_key="website_page:already-classified",
        source_type=DocumentType.WEBSITE_PAGE.value,
        title="Already classified",
        url="https://example.com/already-classified",
        content_hash="current-content",
        evidence_basis="document content",
        evidence="Current content",
    )
    existing = GroundingDocumentClassification(
        source_key=document.source_key,
        run_id=run.id,
        content_hash=document.content_hash,
        classifier_fingerprint="document-fingerprint",
        primary_subject_key=document_subject_definitions()[0].key,
        secondary_subject_keys=[],
        document_function_key=document_function_definitions()[0].key,
        confidence="high",
        evidence_basis=document.evidence_basis,
        classified_at=now,
    )
    transactional_session.add(existing)
    await transactional_session.flush()
    prepared = PreparedRun(
        definitions=topic_definitions(),
        chat_classifier_fingerprint="chat-fingerprint",
        document_classifier_fingerprint="document-fingerprint",
        all_chats=(),
        pending_chats=(),
        references=(),
        stale_reference_ids=(),
        eligible_conversation_ids=(),
        all_documents=(document,),
        pending_documents=(),
        existing_chats={},
        existing_documents={document.source_key: existing},
        selected_grounding_answers=0,
    )

    await finish_run(
        transactional_session,
        run,
        prepared,
        (),
        (),
        error_count=0,
        stability_metrics={"warning": False},
    )

    assert run.classified_documents == 1


@pytest.mark.asyncio
async def test_expired_run_claim_receives_a_new_fencing_token(
    transactional_session: AsyncSession,
) -> None:
    user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="lease-owner"
    )
    _category, run = await create_category(
        transactional_session,
        name="Employer partnerships",
        description="Questions about employer partnership benefits.",
        include_examples=[],
        exclude_examples=[],
        requested_by_user_id=user.id,
    )

    first = await claim_next_run(transactional_session)
    assert first is not None
    assert first.run_id == run.id
    assert run.lease_token == first.token
    assert await claim_next_run(transactional_session) is None

    run.classifier_version = "old-deployment"
    run.leased_until = current_time_utc() - timedelta(seconds=1)
    await transactional_session.flush()
    second = await claim_next_run(transactional_session)

    assert second is not None
    assert second.run_id == run.id
    assert second.token != first.token
    assert run.lease_token == second.token
    assert run.classifier_version == CLASSIFIER_VERSION

    await transactional_session.commit()
    await execute_run(first)
    await transactional_session.refresh(run)

    assert run.status == "running"
    assert run.lease_token == second.token


@pytest.mark.asyncio
async def test_chat_insight_routes_require_access_and_return_typed_summary(
    transactional_session: AsyncSession,
) -> None:
    ordinary_user = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.USER, prefix="insight-user"
    )
    developer = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="insight-dev"
    )
    website_types = (
        DocumentType.WEBSITE_PAGE,
        DocumentType.WEBSITE_PROGRAM,
        DocumentType.CATALOG_PAGE,
        DocumentType.CATALOG_PROGRAM,
        DocumentType.CATALOG_COURSE,
    )
    current_before = int(
        await transactional_session.scalar(
            select(func.count())
            .select_from(Document)
            .outerjoin(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(Document.type.in_(website_types), RagDocumentExclusion.id.is_(None))
        )
        or 0
    )
    visible_document = Document(
        type=DocumentType.WEBSITE_PAGE,
        id_=987654,
        source_key=f"chat-insight-test:{uuid4()}",
        title="Visible analytics document",
        url="https://example.com/analytics-document",
        markdown_content="Analytics document content.",
        token_count=4,
        character_count=27,
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    transactional_session.add(visible_document)
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, ordinary_user.id)
        denied = await client.get("/api/chat-insights/categories")
        assert denied.status_code == 403

        authenticate_client(client, developer.id)
        categories = await client.get("/api/chat-insights/categories")
        assert categories.status_code == 200
        payload = categories.json()
        assert payload["published_revision"] == 1
        assert payload["pending_revision"] is None
        assert {item["key"] for item in payload["categories"]} == {
            definition.key for definition in topic_definitions()
        }

        mixed_time_zones = await client.get(
            "/api/chat-insights/summary",
            params={"start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00Z"},
        )
        assert mixed_time_zones.status_code == 422
        reversed_range = await client.get(
            "/api/chat-insights/summary",
            params={"start": "2026-01-02T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        )
        assert reversed_range.status_code == 400

        summary = await client.get("/api/chat-insights/summary")
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["coverage"] == {
            "analyzed_chats": 0,
            "classification_gaps": 0,
            "document_grounded_answers": 0,
            "referenced_documents": 0,
            "classified_documents": 0,
        }
        assert [source["name"] for source in summary_payload["sources"]] == [
            "Training materials",
            "Website content",
        ]
        website_content = summary_payload["sources"][1]
        assert website_content["current_documents"] == current_before + 1
        assert website_content["current_documents_used"] == 0
        assert website_content["utilization"] == 0.0

        latest = await client.get("/api/chat-insights/runs/latest")
        assert latest.status_code == 200
        assert latest.json() is None


@pytest.mark.asyncio
async def test_category_manager_does_not_need_manual_run_permission(
    transactional_session: AsyncSession,
) -> None:
    manager = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.USER, prefix="category-manager"
    )
    await replace_user_permission_overrides(
        transactional_session,
        manager,
        {
            PermissionKey.ACCESS_CHAT_INSIGHTS: True,
            PermissionKey.MANAGE_CHAT_INSIGHT_CATEGORIES: True,
            PermissionKey.RUN_CHAT_INSIGHTS: False,
        },
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, manager.id)
        response = await client.post(
            "/api/chat-insights/categories",
            json={
                "name": "Employer partnerships",
                "description": "Questions about employer partnership benefits.",
                "include_examples": ["partner tuition benefit"],
                "exclude_examples": ["general tuition question"],
            },
        )

    assert response.status_code == 201
    assert response.json()["key"] == "employer-partnerships"


@pytest.mark.asyncio
async def test_category_input_rejects_unbounded_examples_and_keys(
    transactional_session: AsyncSession,
) -> None:
    developer = await _new_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, prefix="validation-dev"
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, developer.id)
        long_example = await client.post(
            "/api/chat-insights/categories",
            json={
                "name": "Valid category",
                "description": "A sufficiently specific category description.",
                "include_examples": ["x" * 501],
                "exclude_examples": [],
            },
        )
        invalid_key = await client.post(
            "/api/chat-insights/categories",
            json={
                "name": "---",
                "description": "A sufficiently specific category description.",
                "include_examples": [],
                "exclude_examples": [],
            },
        )

    assert long_example.status_code == 422
    assert invalid_key.status_code == 422
