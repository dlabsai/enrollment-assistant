from __future__ import annotations

from datetime import datetime  # noqa: TC003 - FastAPI resolves runtime annotations.
from typing import Annotated
from uuid import UUID  # noqa: TC003 - FastAPI resolves runtime annotations.

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, require_all_permissions, require_permission
from app.api.routes.time_filters import AwareTimestamp, validate_time_range
from app.chat_insights.reporting import build_summary
from app.chat_insights.service import (
    CategoryConflictError,
    CategoryNotEditableError,
    admit_run,
    create_category,
    list_categories,
    update_category,
)
from app.chat_insights.taxonomy import category_key
from app.core.config import settings
from app.core.rbac import PermissionKey
from app.models import ChatInsightCategory, ChatInsightRun, ChatInsightTaxonomyRevision
from app.utils import current_time_utc


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/chat-insights", tags=["chat-insights"], dependencies=[Depends(no_store)]
)

InsightsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_CHAT_INSIGHTS))
]
RunAccessUser = Annotated[
    CurrentUser,
    Depends(
        require_all_permissions(
            PermissionKey.ACCESS_CHAT_INSIGHTS, PermissionKey.RUN_CHAT_INSIGHTS
        ),
        scope="function",
    ),
]
ManageAccessUser = Annotated[
    CurrentUser,
    Depends(
        require_all_permissions(
            PermissionKey.ACCESS_CHAT_INSIGHTS, PermissionKey.MANAGE_CHAT_INSIGHT_CATEGORIES
        ),
        scope="function",
    ),
]


CATEGORY_KEY_MAX_LENGTH = 96
CategoryExample = Annotated[str, Field(min_length=1, max_length=500)]


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=CATEGORY_KEY_MAX_LENGTH)
    description: str = Field(min_length=10, max_length=4000)
    include_examples: list[CategoryExample] = Field(default_factory=list, max_length=12)
    exclude_examples: list[CategoryExample] = Field(default_factory=list, max_length=12)

    @field_validator("name", "description")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("name")
    @classmethod
    def validate_key_length(cls, value: str) -> str:
        key = category_key(value)
        if len(key) > CATEGORY_KEY_MAX_LENGTH:
            raise ValueError(
                f"Category name produces a key longer than {CATEGORY_KEY_MAX_LENGTH} characters"
            )
        return value

    @field_validator("include_examples", "exclude_examples")
    @classmethod
    def normalize_examples(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class CategoryUpdateIn(CategoryIn):
    active: bool = True


class RunOut(BaseModel):
    id: str
    trigger: str
    status: str
    cutoff_at: str
    full_backfill: bool
    created: bool = False


class CategoryOut(BaseModel):
    key: str
    name: str
    description: str
    include_examples: list[str]
    exclude_examples: list[str]
    origin: str
    active: bool


class CategoryListOut(BaseModel):
    published_revision: int
    pending_revision: int | None
    categories: list[CategoryOut]


class RunSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    error_count: int
    error_code: str | None


class CoverageOut(BaseModel):
    analyzed_chats: int
    classification_gaps: int
    document_grounded_answers: int
    referenced_documents: int
    classified_documents: int


class NamedCountOut(BaseModel):
    key: str
    name: str
    answers: int


class TopicMetricOut(BaseModel):
    key: str
    name: str
    description: str
    primary_chats: int
    mention_chats: int
    top_document_subjects: list[NamedCountOut]
    top_document_functions: list[NamedCountOut]


class RequestTypeMetricOut(BaseModel):
    key: str
    name: str
    chats: int


class TopicPairMetricOut(BaseModel):
    first_key: str
    first_name: str
    second_key: str
    second_name: str
    chats: int


class SourceMetricOut(BaseModel):
    key: str
    name: str
    chats: int
    answers: int
    current_documents: int
    current_documents_used: int
    utilization: float | None


class GroundedDocumentMetricOut(BaseModel):
    source_key: str
    title: str
    url: str
    document_type: str
    chats: int
    answers: int
    last_used_at: datetime
    primary_subject: str | None
    secondary_subjects: list[str]
    document_function: str | None
    confidence: str | None


class TrendPointOut(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    chats: int
    answers: int


class TrendRowOut(BaseModel):
    key: str
    name: str
    points: list[TrendPointOut]


class ChatInsightSummaryOut(BaseModel):
    data_through: datetime | None
    taxonomy_revision: int
    latest_run: RunSummaryOut | None
    coverage: CoverageOut
    topics: list[TopicMetricOut]
    request_types: list[RequestTypeMetricOut]
    topic_pairs: list[TopicPairMetricOut]
    sources: list[SourceMetricOut]
    top_documents: list[GroundedDocumentMetricOut]
    time_granularity: str
    topic_trends: list[TrendRowOut]
    source_trends: list[TrendRowOut]
    document_trends: list[TrendRowOut]


def _run_out(run: ChatInsightRun, *, created: bool = False) -> RunOut:
    return RunOut(
        id=str(run.id),
        trigger=run.trigger,
        status=run.status,
        cutoff_at=run.cutoff_at.isoformat(),
        full_backfill=run.full_backfill,
        created=created,
    )


def _category_out(category: ChatInsightCategory) -> CategoryOut:
    return CategoryOut(
        key=category.key,
        name=category.name,
        description=category.description,
        include_examples=list(category.include_examples),
        exclude_examples=list(category.exclude_examples),
        origin=category.origin,
        active=category.active,
    )


@router.get("/summary", response_model=ChatInsightSummaryOut)
async def chat_insight_summary(
    session: SessionDep,
    _current_user: InsightsAccessUser,
    start: Annotated[AwareTimestamp | None, Query()] = None,
    end: Annotated[AwareTimestamp | None, Query()] = None,
) -> ChatInsightSummaryOut:
    validate_time_range(start, end, detail="Start must not be after end")
    summary = await build_summary(session, start=start, end=end)
    return ChatInsightSummaryOut.model_validate(summary)


@router.get("/runs/latest", response_model=RunSummaryOut | None)
async def latest_chat_insight_run(
    session: SessionDep, _current_user: InsightsAccessUser
) -> RunSummaryOut | None:
    run = await session.scalar(
        select(ChatInsightRun).order_by(ChatInsightRun.created_at.desc()).limit(1)
    )
    return RunSummaryOut.model_validate(run) if run is not None else None


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_chat_insight_run(session: SessionDep, current_user: RunAccessUser) -> RunOut:
    if not settings.CHAT_INSIGHTS_WORKER_ENABLED:
        raise HTTPException(status_code=503, detail="Chat-insight worker is disabled")
    admission = await admit_run(
        session,
        trigger="manual",
        requested_by_user_id=current_user.id,
        cutoff_at=current_time_utc(),
    )
    return _run_out(admission.run, created=admission.created)


@router.get("/categories", response_model=CategoryListOut)
async def get_chat_insight_categories(
    session: SessionDep, _current_user: InsightsAccessUser
) -> CategoryListOut:
    categories = await list_categories(session)
    published_revision = await session.scalar(
        select(ChatInsightTaxonomyRevision.number)
        .where(ChatInsightTaxonomyRevision.status == "published")
        .order_by(ChatInsightTaxonomyRevision.number.desc())
        .limit(1)
    )
    pending_revision = await session.scalar(
        select(ChatInsightTaxonomyRevision.number)
        .where(ChatInsightTaxonomyRevision.status == "pending")
        .order_by(ChatInsightTaxonomyRevision.number.desc())
        .limit(1)
    )
    if published_revision is None:
        raise HTTPException(status_code=503, detail="Chat-insight taxonomy is unavailable")
    return CategoryListOut(
        published_revision=published_revision,
        pending_revision=pending_revision,
        categories=[_category_out(category) for category in categories],
    )


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def add_chat_insight_category(
    payload: CategoryIn, session: SessionDep, current_user: ManageAccessUser
) -> CategoryOut:
    if not settings.CHAT_INSIGHTS_WORKER_ENABLED:
        raise HTTPException(status_code=503, detail="Chat-insight worker is disabled")
    try:
        category, _run = await create_category(
            session,
            name=payload.name,
            description=payload.description,
            include_examples=payload.include_examples,
            exclude_examples=payload.exclude_examples,
            requested_by_user_id=current_user.id,
        )
    except CategoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _category_out(category)


@router.put("/categories/{category_key}", response_model=CategoryOut)
async def edit_chat_insight_category(
    category_key: str,
    payload: CategoryUpdateIn,
    session: SessionDep,
    current_user: ManageAccessUser,
) -> CategoryOut:
    if not settings.CHAT_INSIGHTS_WORKER_ENABLED:
        raise HTTPException(status_code=503, detail="Chat-insight worker is disabled")
    try:
        category, _run = await update_category(
            session,
            category_key_value=category_key,
            name=payload.name,
            description=payload.description,
            include_examples=payload.include_examples,
            exclude_examples=payload.exclude_examples,
            active=payload.active,
            requested_by_user_id=current_user.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Category not found") from exc
    except CategoryNotEditableError as exc:
        raise HTTPException(status_code=409, detail="System categories are not editable") from exc
    except CategoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _category_out(category)
