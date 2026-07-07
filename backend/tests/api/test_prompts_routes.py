from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import TEMPLATES_DIR
from app.chat.template_utils import clear_deployed_templates_cache
from app.core.config import settings
from app.core.rbac import (
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
    replace_user_permission_overrides,
)
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models import PromptSetTemplate, PromptSetVersion, User
from app.prompt_sets import PromptSetScope, read_disk_templates
from tests.api.auth_helpers import authenticate_client


async def _create_admin(session: AsyncSession, *, email_prefix: str) -> User:
    group = await get_group_for_slug(session, SystemGroupSlug.ADMIN)
    admin = User(
        email=f"{email_prefix}-{uuid4()}@example.com",
        name="Admin User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return admin


async def _create_user(
    session: AsyncSession, *, group_slug: SystemGroupSlug, email_prefix: str
) -> User:
    group = await get_group_for_slug(session, group_slug)
    user = User(
        email=f"{email_prefix}-{uuid4()}@example.com",
        name=f"{group_slug.value.title()} User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_prompts_routes_list_and_detail_scope_specific_versions(
    transactional_session: AsyncSession,
) -> None:
    clear_deployed_templates_cache()
    admin = await _create_admin(transactional_session, email_prefix="prompts-list")
    disk_templates = read_disk_templates(TEMPLATES_DIR)

    assistant_version = PromptSetVersion(
        version_number=1,
        name="Internal assistant v1",
        description="Assistant prompt set",
        created_by_id=admin.id,
        is_deployed=False,
        is_internal=True,
        scope=PromptSetScope.ASSISTANT,
    )
    summary_version = PromptSetVersion(
        version_number=1,
        name="Internal summary v1",
        description="Summary prompt set",
        created_by_id=admin.id,
        is_deployed=False,
        is_internal=True,
        scope=PromptSetScope.SUMMARY,
    )
    public_version = PromptSetVersion(
        version_number=1,
        name="Public assistant v1",
        description="Public prompt set",
        created_by_id=admin.id,
        is_deployed=False,
        is_internal=False,
        scope=PromptSetScope.ASSISTANT,
    )
    transactional_session.add_all([assistant_version, summary_version, public_version])
    await transactional_session.flush()

    transactional_session.add_all(
        [
            PromptSetTemplate(
                prompt_set_version_id=assistant_version.id,
                filename="chatbot_agent_internal.j2",
                content=disk_templates["chatbot_agent_internal.j2"] + "\n{# assistant override #}",
            ),
            PromptSetTemplate(
                prompt_set_version_id=assistant_version.id,
                filename="guardrails_agent_internal.j2",
                content=disk_templates["guardrails_agent_internal.j2"],
            ),
            PromptSetTemplate(
                prompt_set_version_id=summary_version.id,
                filename="summary_agent_internal.j2",
                content=disk_templates["summary_agent_internal.j2"],
            ),
            PromptSetTemplate(
                prompt_set_version_id=public_version.id,
                filename="chatbot_agent.j2",
                content=disk_templates["chatbot_agent.j2"],
            ),
            PromptSetTemplate(
                prompt_set_version_id=public_version.id,
                filename="guardrails_agent.j2",
                content=disk_templates["guardrails_agent.j2"],
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        assistant_response = await client.get(
            "/api/prompts/versions",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )
        summary_response = await client.get(
            "/api/prompts/versions",
            params={"is_internal": "true", "scope": PromptSetScope.SUMMARY.value},
        )
        detail_response = await client.get(f"/api/prompts/versions/{assistant_version.id}")
        deployed_response = await client.get(
            "/api/prompts/versions/deployed",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )

    assert assistant_response.status_code == 200
    assistant_body = assistant_response.json()
    assert [item["id"] for item in assistant_body] == [str(assistant_version.id)]
    assert assistant_body[0]["scope"] == PromptSetScope.ASSISTANT.value
    assert assistant_body[0]["is_internal"] is True
    assert assistant_body[0]["modified_prompt_count"] == 1

    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    assert [item["id"] for item in summary_body] == [str(summary_version.id)]
    assert summary_body[0]["scope"] == PromptSetScope.SUMMARY.value

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["id"] == str(assistant_version.id)
    assert detail_body["scope"] == PromptSetScope.ASSISTANT.value
    assert detail_body["is_internal"] is True
    assert {prompt["filename"] for prompt in detail_body["prompts"]} == {
        "chatbot_agent_internal.j2",
        "guardrails_agent_internal.j2",
    }

    assert deployed_response.status_code == 200
    assert deployed_response.json() == {"id": None, "version_number": None, "name": None}


@pytest.mark.asyncio
async def test_prompts_routes_create_deploy_undeploy_and_runtime_templates(
    transactional_session: AsyncSession,
) -> None:
    clear_deployed_templates_cache()
    admin = await _create_admin(transactional_session, email_prefix="prompts-create")
    disk_templates = read_disk_templates(TEMPLATES_DIR)

    assistant_payload = {
        "name": "Assistant draft",
        "description": "Internal assistant version",
        "is_internal": True,
        "scope": PromptSetScope.ASSISTANT.value,
        "prompts": [
            {
                "filename": "chatbot_agent_internal.j2",
                "content": disk_templates["chatbot_agent_internal.j2"]
                + "\n{# deployed assistant #}",
            },
            {
                "filename": "guardrails_agent_internal.j2",
                "content": disk_templates["guardrails_agent_internal.j2"],
            },
        ],
    }
    summary_payload = {
        "name": "Summary draft",
        "description": "Internal summary version",
        "is_internal": True,
        "scope": PromptSetScope.SUMMARY.value,
        "prompts": [
            {
                "filename": "summary_agent_internal.j2",
                "content": "CUSTOM INTERNAL SUMMARY {{ transcript }}",
            }
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        create_assistant_response = await client.post(
            "/api/prompts/versions", json=assistant_payload
        )
        create_summary_response = await client.post("/api/prompts/versions", json=summary_payload)

        assert create_assistant_response.status_code == 201
        assert create_summary_response.status_code == 201

        assistant_version_id = create_assistant_response.json()["id"]
        summary_version_id = create_summary_response.json()["id"]

        deploy_assistant_response = await client.post(
            f"/api/prompts/versions/{assistant_version_id}/deploy", json={}
        )
        deploy_summary_response = await client.post(
            f"/api/prompts/versions/{summary_version_id}/deploy", json={}
        )

        assert deploy_assistant_response.status_code == 200
        assert deploy_summary_response.status_code == 200

        deployed_assistant_response = await client.get(
            "/api/prompts/versions/deployed",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )
        deployed_summary_response = await client.get(
            "/api/prompts/versions/deployed",
            params={"is_internal": "true", "scope": PromptSetScope.SUMMARY.value},
        )

        assert deployed_assistant_response.status_code == 200
        assert deployed_summary_response.status_code == 200
        assert deployed_assistant_response.json()["id"] == assistant_version_id
        assert deployed_summary_response.json()["id"] == summary_version_id

        undeploy_assistant_response = await client.post(
            "/api/prompts/versions/undeploy",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
            json={},
        )
        assert undeploy_assistant_response.status_code == 200

        deployed_assistant_after_undeploy = await client.get(
            "/api/prompts/versions/deployed",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )
        deployed_summary_after_undeploy = await client.get(
            "/api/prompts/versions/deployed",
            params={"is_internal": "true", "scope": PromptSetScope.SUMMARY.value},
        )

        assert deployed_assistant_after_undeploy.json() == {
            "id": None,
            "version_number": None,
            "name": None,
        }
        assert deployed_summary_after_undeploy.json()["id"] == summary_version_id

        delete_assistant_response = await client.delete(
            f"/api/prompts/versions/{assistant_version_id}"
        )
        assert delete_assistant_response.status_code == 204

    summary_templates = (
        (
            await transactional_session.execute(
                select(PromptSetTemplate).where(
                    PromptSetTemplate.prompt_set_version_id == summary_version_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {template.filename: template.content for template in summary_templates} == {
        "summary_agent_internal.j2": "CUSTOM INTERNAL SUMMARY {{ transcript }}"
    }

    assistant_version = await transactional_session.get(PromptSetVersion, assistant_version_id)
    assert assistant_version is None

    clear_deployed_templates_cache()


@pytest.mark.asyncio
async def test_prompt_undeploy_rejects_untrusted_origin_for_cookie_auth(
    transactional_session: AsyncSession,
) -> None:
    clear_deployed_templates_cache()
    admin = await _create_admin(transactional_session, email_prefix="prompts-csrf")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        client.cookies.set(settings.ACCESS_TOKEN_COOKIE_NAME, create_access_token(str(admin.id)))

        response = await client.post(
            "/api/prompts/versions/undeploy",
            headers={"Origin": "https://evil.example"},
            json={},
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )

        trusted_response = await client.post(
            "/api/prompts/versions/undeploy",
            headers={"Origin": "http://testserver"},
            json={},
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Untrusted Origin for cookie-authenticated request"}
    assert trusted_response.status_code == 200
    assert trusted_response.json() == {"id": None, "version_number": None, "name": None}


@pytest.mark.asyncio
async def test_prompt_reads_and_mutations_allow_instructions_access(
    transactional_session: AsyncSession,
) -> None:
    clear_deployed_templates_cache()
    admin = await _create_admin(transactional_session, email_prefix="prompts-admin-only-admin")
    reader = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.USER,
        email_prefix="prompts-admin-only-reader",
    )
    await replace_user_permission_overrides(
        transactional_session, reader, {PermissionKey.ACCESS_INSTRUCTIONS: True}
    )
    await transactional_session.commit()

    disk_templates = read_disk_templates(TEMPLATES_DIR)
    version = PromptSetVersion(
        version_number=1,
        name="Internal assistant v1",
        description="Assistant prompt set",
        created_by_id=admin.id,
        is_deployed=False,
        is_internal=True,
        scope=PromptSetScope.ASSISTANT,
    )
    transactional_session.add(version)
    await transactional_session.flush()
    transactional_session.add_all(
        [
            PromptSetTemplate(
                prompt_set_version_id=version.id,
                filename="chatbot_agent_internal.j2",
                content=disk_templates["chatbot_agent_internal.j2"],
            ),
            PromptSetTemplate(
                prompt_set_version_id=version.id,
                filename="guardrails_agent_internal.j2",
                content=disk_templates["guardrails_agent_internal.j2"],
            ),
        ]
    )
    await transactional_session.commit()

    create_payload = {
        "name": "Assistant draft",
        "description": "Internal assistant version",
        "is_internal": True,
        "scope": PromptSetScope.ASSISTANT.value,
        "prompts": [
            {
                "filename": "chatbot_agent_internal.j2",
                "content": disk_templates["chatbot_agent_internal.j2"],
            },
            {
                "filename": "guardrails_agent_internal.j2",
                "content": disk_templates["guardrails_agent_internal.j2"],
            },
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, reader.id)
        list_response = await client.get(
            "/api/prompts/versions",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
        )
        create_response = await client.post("/api/prompts/versions", json=create_payload)
        deploy_response = await client.post(f"/api/prompts/versions/{version.id}/deploy", json={})
        undeploy_response = await client.post(
            "/api/prompts/versions/undeploy",
            params={"is_internal": "true", "scope": PromptSetScope.ASSISTANT.value},
            json={},
        )
        delete_response = await client.delete(f"/api/prompts/versions/{version.id}")

    assert list_response.status_code == 200
    assert create_response.status_code == 201
    assert deploy_response.status_code == 200
    assert undeploy_response.status_code == 200
    assert delete_response.status_code == 204
