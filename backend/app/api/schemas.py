from datetime import datetime  # noqa: TC003
from typing import Annotated
from uuid import UUID  # noqa: TC003

from fastapi import Query
from pydantic import BaseModel, ConfigDict

_from_attributes = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    message: str


class PageOut[M](BaseModel):
    items: list[M]
    total: int


class PaginationParams(BaseModel):
    limit: Annotated[int, Query(ge=0)] = 10
    offset: Annotated[int, Query(ge=0)] = 0
    sort_by: Annotated[str, Query()] = "created_at"
    descending: Annotated[bool, Query()] = True


# Authentication schemas
class UserBase(BaseModel):
    email: str
    name: str


class UserGroupOut(BaseModel):
    id: UUID
    slug: str
    name: str


class UserCreate(UserBase):
    password: str
    confirm_password: str
    registration_token: str


class UserOut(UserBase):
    id: UUID
    is_active: bool
    group: UserGroupOut
    permissions: dict[str, bool]
    created_at: datetime
    updated_at: datetime

    model_config = _from_attributes


class UserLogin(BaseModel):
    email: str
    password: str


class TeamsSsoLogin(BaseModel):
    token: str


class AuthSessionOut(BaseModel):
    success: bool = True


class GlobalFeedbackItem(BaseModel):
    id: UUID
    type: str
    rating: str
    text: str | None = None
    user_name: str
    is_current_user: bool
    created_at: datetime
    conversation_id: UUID
    conversation_title: str | None = None
    project_name: str
    message_id: UUID | None = None
    message_preview: str | None = None


class GlobalFeedbackResponse(BaseModel):
    feedback_items: list[GlobalFeedbackItem]
