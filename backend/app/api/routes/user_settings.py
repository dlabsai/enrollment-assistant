from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import CurrentUser, SessionDep
from app.chat.personalization import MAX_PERSONAL_INSTRUCTIONS_LENGTH

router = APIRouter(prefix="/user-settings", tags=["user-settings"])


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal_instructions: str = Field(max_length=MAX_PERSONAL_INSTRUCTIONS_LENGTH)

    @field_validator("personal_instructions")
    @classmethod
    def normalize_empty_context(cls, value: str) -> str:
        return value if value.strip() else ""


@router.get("", response_model=UserSettings)
async def get_user_settings(current_user: CurrentUser) -> UserSettings:
    return UserSettings(personal_instructions=current_user.personal_instructions)


@router.put("", response_model=UserSettings)
async def update_user_settings(
    body: UserSettings, current_user: CurrentUser, session: SessionDep
) -> UserSettings:
    current_user.personal_instructions = body.personal_instructions
    await session.commit()
    return UserSettings(personal_instructions=current_user.personal_instructions)
