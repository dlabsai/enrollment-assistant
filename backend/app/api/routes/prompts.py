"""API routes for prompt template management and prompt set versioning."""

from typing import Annotated, Any
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.chat.config import TEMPLATES_DIR
from app.chat.template_utils import clear_deployed_templates_cache
from app.core.rbac import PermissionKey
from app.models import PromptSetScope, PromptSetTemplate, PromptSetVersion, User
from app.prompt_sets import get_template_filenames_for_scope, read_disk_templates

router = APIRouter(prefix="/prompts", tags=["prompts"])

InstructionsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_INSTRUCTIONS))
]


class PromptFileOut(BaseModel):
    filename: str
    content: str


class PromptTemplateOut(BaseModel):
    id: UUID
    filename: str
    content: str


class PromptTemplateIn(BaseModel):
    filename: str
    content: str


class PromptSetVersionBase(BaseModel):
    name: str
    description: str | None = None
    is_internal: bool = False
    scope: PromptSetScope = PromptSetScope.ASSISTANT


class PromptSetVersionCreate(PromptSetVersionBase):
    prompts: list[PromptTemplateIn]


class PromptSetVersionOut(PromptSetVersionBase):
    id: UUID
    version_number: int
    is_deployed: bool
    created_by_id: UUID
    created_by_name: str
    created_at: str
    prompts: list[PromptTemplateOut]


class PromptSetVersionListOut(PromptSetVersionBase):
    id: UUID
    version_number: int
    is_deployed: bool
    created_by_id: UUID
    created_by_name: str
    created_at: str
    modified_prompt_count: int


class ActiveVersionOut(BaseModel):
    id: UUID | None
    version_number: int | None
    name: str | None


@router.get("/disk-templates", response_model=list[PromptFileOut])
async def list_disk_templates(_current_user: InstructionsAccessUser) -> Any:
    templates = [
        PromptFileOut(filename=filename, content=content)
        for filename, content in read_disk_templates(TEMPLATES_DIR).items()
    ]
    templates.sort(key=lambda template: template.filename)
    return templates


@router.get("/versions", response_model=list[PromptSetVersionListOut])
async def list_versions(
    session: SessionDep,
    _current_user: InstructionsAccessUser,
    *,
    is_internal: bool | None = None,
    scope: PromptSetScope = PromptSetScope.ASSISTANT,
) -> Any:
    stmt = (
        select(PromptSetVersion, User.name.label("created_by_name"))
        .join(User, PromptSetVersion.created_by_id == User.id)
        .order_by(desc(PromptSetVersion.version_number), desc(PromptSetVersion.created_at))
    )
    if is_internal is not None:
        stmt = stmt.where(PromptSetVersion.is_internal == is_internal)
    stmt = stmt.where(PromptSetVersion.scope == scope)

    rows = (await session.execute(stmt)).all()
    version_ids = [row.PromptSetVersion.id for row in rows]

    prompts_by_version: dict[UUID, list[PromptSetTemplate]] = {}
    if version_ids:
        prompts_stmt = select(PromptSetTemplate).where(
            PromptSetTemplate.prompt_set_version_id.in_(version_ids)
        )
        prompts = (await session.execute(prompts_stmt)).scalars().all()
        for prompt in prompts:
            prompts_by_version.setdefault(prompt.prompt_set_version_id, []).append(prompt)

    disk_templates = read_disk_templates(TEMPLATES_DIR)

    return [
        PromptSetVersionListOut(
            id=version.id,
            version_number=version.version_number,
            name=version.name,
            description=version.description,
            is_internal=version.is_internal,
            scope=version.scope,
            is_deployed=version.is_deployed,
            created_by_id=version.created_by_id,
            created_by_name=row.created_by_name,
            created_at=version.created_at.isoformat(),
            modified_prompt_count=sum(
                1
                for prompt in prompts_by_version.get(version.id, [])
                if disk_templates.get(prompt.filename) != prompt.content
            ),
        )
        for row in rows
        for version in [row.PromptSetVersion]
    ]


@router.get("/versions/deployed", response_model=ActiveVersionOut)
async def get_deployed_version(
    session: SessionDep,
    _current_user: InstructionsAccessUser,
    *,
    is_internal: bool = False,
    scope: PromptSetScope = PromptSetScope.ASSISTANT,
) -> Any:
    stmt = (
        select(PromptSetVersion)
        .where(PromptSetVersion.is_deployed == True)  # noqa: E712
        .where(PromptSetVersion.is_internal == is_internal)
        .where(PromptSetVersion.scope == scope)
        .limit(1)
    )
    version = (await session.execute(stmt)).scalar_one_or_none()
    if version is None:
        return ActiveVersionOut(id=None, version_number=None, name=None)

    return ActiveVersionOut(id=version.id, version_number=version.version_number, name=version.name)


@router.get("/versions/{version_id}", response_model=PromptSetVersionOut)
async def get_version(
    version_id: UUID, session: SessionDep, _current_user: InstructionsAccessUser
) -> Any:
    stmt = (
        select(PromptSetVersion, User.name.label("created_by_name"))
        .join(User, PromptSetVersion.created_by_id == User.id)
        .where(PromptSetVersion.id == version_id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")

    version = row.PromptSetVersion
    prompts_stmt = select(PromptSetTemplate).where(
        PromptSetTemplate.prompt_set_version_id == version_id
    )
    prompts = (await session.execute(prompts_stmt)).scalars().all()

    return PromptSetVersionOut(
        id=version.id,
        version_number=version.version_number,
        name=version.name,
        description=version.description,
        is_internal=version.is_internal,
        scope=version.scope,
        is_deployed=version.is_deployed,
        created_by_id=version.created_by_id,
        created_by_name=row.created_by_name,
        created_at=version.created_at.isoformat(),
        prompts=[
            PromptTemplateOut(id=prompt.id, filename=prompt.filename, content=prompt.content)
            for prompt in prompts
        ],
    )


@router.post("/versions", response_model=PromptSetVersionOut, status_code=status.HTTP_201_CREATED)
async def create_version(
    version_in: PromptSetVersionCreate, session: SessionDep, current_user: InstructionsAccessUser
) -> Any:
    disk_templates = read_disk_templates(TEMPLATES_DIR)
    expected_templates = set(
        get_template_filenames_for_scope(version_in.scope, is_internal=version_in.is_internal)
    )
    missing_on_disk = sorted(expected_templates - set(disk_templates))
    if missing_on_disk:
        raise HTTPException(
            status_code=400, detail=f"Missing templates on disk: {', '.join(missing_on_disk)}"
        )

    submitted_templates = {prompt.filename for prompt in version_in.prompts}
    if len(submitted_templates) != len(version_in.prompts):
        raise HTTPException(status_code=400, detail="Duplicate templates provided.")

    missing = sorted(expected_templates - submitted_templates)
    extra = sorted(submitted_templates - expected_templates)
    if missing:
        raise HTTPException(
            status_code=400, detail=f"Missing templates for version: {', '.join(missing)}"
        )
    if extra:
        raise HTTPException(
            status_code=400, detail=f"Unexpected templates for version: {', '.join(extra)}"
        )

    next_version_stmt = select(func.coalesce(func.max(PromptSetVersion.version_number), 0)).where(
        PromptSetVersion.is_internal == version_in.is_internal,
        PromptSetVersion.scope == version_in.scope,
    )
    max_version = (await session.execute(next_version_stmt)).scalar() or 0

    version = PromptSetVersion(
        version_number=max_version + 1,
        is_internal=version_in.is_internal,
        scope=version_in.scope,
        name=version_in.name,
        description=version_in.description,
        is_deployed=False,
        created_by_id=current_user.id,
    )
    session.add(version)
    await session.flush()

    for prompt in version_in.prompts:
        session.add(
            PromptSetTemplate(
                prompt_set_version_id=version.id, filename=prompt.filename, content=prompt.content
            )
        )

    await session.commit()
    await session.refresh(version)

    prompts_stmt = select(PromptSetTemplate).where(
        PromptSetTemplate.prompt_set_version_id == version.id
    )
    prompts = (await session.execute(prompts_stmt)).scalars().all()

    return PromptSetVersionOut(
        id=version.id,
        version_number=version.version_number,
        name=version.name,
        description=version.description,
        is_internal=version.is_internal,
        scope=version.scope,
        is_deployed=version.is_deployed,
        created_by_id=version.created_by_id,
        created_by_name=current_user.name,
        created_at=version.created_at.isoformat(),
        prompts=[
            PromptTemplateOut(id=prompt.id, filename=prompt.filename, content=prompt.content)
            for prompt in prompts
        ],
    )


@router.post("/versions/{version_id}/deploy", response_model=PromptSetVersionOut)
async def deploy_version(
    version_id: UUID, session: SessionDep, _current_user: InstructionsAccessUser
) -> Any:
    stmt = (
        select(PromptSetVersion, User.name.label("created_by_name"))
        .join(User, PromptSetVersion.created_by_id == User.id)
        .where(PromptSetVersion.id == version_id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")

    version = row.PromptSetVersion

    undeploy_stmt = (
        select(PromptSetVersion)
        .where(PromptSetVersion.is_deployed == True)  # noqa: E712
        .where(PromptSetVersion.id != version_id)
        .where(PromptSetVersion.is_internal == version.is_internal)
        .where(PromptSetVersion.scope == version.scope)
    )
    for other in (await session.execute(undeploy_stmt)).scalars().all():
        other.is_deployed = False

    version.is_deployed = True
    await session.commit()
    await session.refresh(version)
    clear_deployed_templates_cache()

    prompts_stmt = select(PromptSetTemplate).where(
        PromptSetTemplate.prompt_set_version_id == version.id
    )
    prompts = (await session.execute(prompts_stmt)).scalars().all()

    return PromptSetVersionOut(
        id=version.id,
        version_number=version.version_number,
        name=version.name,
        description=version.description,
        is_internal=version.is_internal,
        scope=version.scope,
        is_deployed=version.is_deployed,
        created_by_id=version.created_by_id,
        created_by_name=row.created_by_name,
        created_at=version.created_at.isoformat(),
        prompts=[
            PromptTemplateOut(id=prompt.id, filename=prompt.filename, content=prompt.content)
            for prompt in prompts
        ],
    )


@router.post("/versions/undeploy", response_model=ActiveVersionOut)
async def undeploy_version(
    session: SessionDep,
    _current_user: InstructionsAccessUser,
    *,
    is_internal: bool = False,
    scope: PromptSetScope = PromptSetScope.ASSISTANT,
) -> Any:
    stmt = (
        select(PromptSetVersion)
        .where(PromptSetVersion.is_deployed == True)  # noqa: E712
        .where(PromptSetVersion.is_internal == is_internal)
        .where(PromptSetVersion.scope == scope)
    )
    versions = (await session.execute(stmt)).scalars().all()
    for version in versions:
        version.is_deployed = False

    if versions:
        await session.commit()
        clear_deployed_templates_cache()

    return ActiveVersionOut(id=None, version_number=None, name=None)


@router.delete("/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(
    version_id: UUID, session: SessionDep, _current_user: InstructionsAccessUser
) -> None:
    version = await session.get(PromptSetVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.is_deployed:
        raise HTTPException(
            status_code=400, detail="Cannot delete deployed version. Undeploy first."
        )

    await session.delete(version)
    await session.commit()
