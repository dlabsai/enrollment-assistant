"""Eval test-case disk/DB overlay management."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select

from app.chat.evals.chatbot import TEST_CASES as CHATBOT_TEST_CASES
from app.chat.evals.guardrails import TEST_CASES as GUARDRAILS_TEST_CASES
from app.evals.case_payloads import EvalCasePayloadError
from app.evals.case_payloads import validate_eval_case_payload as _validate_eval_case_payload
from app.evals.runtime import EvalSuite
from app.models import EvalTestCaseOverlay

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

EvalCaseStatus = Literal["disk", "overridden", "deleted", "database"]


class EvalCaseManagementError(ValueError):
    """Base error for eval case management."""


class EvalCaseValidationError(EvalCaseManagementError):
    """Raised when a case payload is invalid for its suite."""


class EvalCaseConflictError(EvalCaseManagementError):
    """Raised when creating a case would collide with an existing case."""


class EvalCaseNotFoundError(EvalCaseManagementError):
    """Raised when a requested case does not exist."""


@dataclass(frozen=True)
class DiskEvalCase:
    """Canonical case loaded from the suite source on disk."""

    case_id: str
    payload: dict[str, Any]
    payload_hash: str


@dataclass(frozen=True)
class EvalCaseDefinition:
    """Merged disk/DB representation shown in the UI and used by API runs."""

    suite: EvalSuite
    case_id: str
    status: EvalCaseStatus
    active: bool
    payload: dict[str, Any]
    payload_hash: str
    canonical_payload: dict[str, Any] | None
    disk_hash: str | None
    overlay_base_disk_hash: str | None
    has_disk_changes: bool
    created_at: datetime | None
    updated_at: datetime | None


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_eval_case_payload(
    suite: EvalSuite, payload: dict[str, Any], *, expected_case_id: str | None = None
) -> dict[str, Any]:
    """Validate and normalize editable case JSON for a suite."""
    try:
        return _validate_eval_case_payload(suite, payload, expected_case_id=expected_case_id)
    except EvalCasePayloadError as error:
        raise EvalCaseValidationError(str(error)) from error


def _disk_case_payloads(suite: EvalSuite) -> list[dict[str, Any]]:
    if suite is EvalSuite.CHATBOT:
        return [asdict(test_case) for test_case in CHATBOT_TEST_CASES]
    if suite is EvalSuite.GUARDRAILS:
        return [asdict(test_case) for test_case in GUARDRAILS_TEST_CASES]
    raise EvalCaseValidationError(f"Unsupported eval suite: {suite.value}")


def get_disk_eval_cases(suite: EvalSuite) -> dict[str, DiskEvalCase]:
    """Return canonical disk cases keyed by stable test_case_id."""
    cases: dict[str, DiskEvalCase] = {}
    for raw_payload in _disk_case_payloads(suite):
        payload = validate_eval_case_payload(suite, raw_payload)
        case_id = str(payload["test_case_id"])
        cases[case_id] = DiskEvalCase(
            case_id=case_id, payload=payload, payload_hash=_payload_hash(payload)
        )
    return cases


async def _load_overlays(session: AsyncSession, suite: EvalSuite) -> dict[str, EvalTestCaseOverlay]:
    rows = await session.scalars(
        select(EvalTestCaseOverlay)
        .where(EvalTestCaseOverlay.suite == suite.value)
        .order_by(EvalTestCaseOverlay.case_id.asc())
    )
    return {row.case_id: row for row in rows}


def _definition_from_parts(
    *,
    suite: EvalSuite,
    case_id: str,
    disk_case: DiskEvalCase | None,
    row: EvalTestCaseOverlay | None,
) -> EvalCaseDefinition | None:
    if disk_case is None and row is None:
        return None

    if row is None:
        if disk_case is None:
            return None
        return EvalCaseDefinition(
            suite=suite,
            case_id=case_id,
            status="disk",
            active=True,
            payload=disk_case.payload,
            payload_hash=disk_case.payload_hash,
            canonical_payload=disk_case.payload,
            disk_hash=disk_case.payload_hash,
            overlay_base_disk_hash=None,
            has_disk_changes=False,
            created_at=None,
            updated_at=None,
        )

    base_disk_hash = row.base_disk_hash
    disk_hash = disk_case.payload_hash if disk_case is not None else None
    has_disk_changes = base_disk_hash is not None and disk_hash != base_disk_hash

    if disk_case is not None and row.is_deleted:
        return EvalCaseDefinition(
            suite=suite,
            case_id=case_id,
            status="deleted",
            active=False,
            payload=disk_case.payload,
            payload_hash=disk_case.payload_hash,
            canonical_payload=disk_case.payload,
            disk_hash=disk_hash,
            overlay_base_disk_hash=base_disk_hash,
            has_disk_changes=has_disk_changes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    if row.case_data is None:
        if disk_case is None:
            return None
        return EvalCaseDefinition(
            suite=suite,
            case_id=case_id,
            status="disk",
            active=True,
            payload=disk_case.payload,
            payload_hash=disk_case.payload_hash,
            canonical_payload=disk_case.payload,
            disk_hash=disk_hash,
            overlay_base_disk_hash=base_disk_hash,
            has_disk_changes=has_disk_changes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    payload = validate_eval_case_payload(suite, row.case_data, expected_case_id=case_id)
    return EvalCaseDefinition(
        suite=suite,
        case_id=case_id,
        status="overridden" if base_disk_hash is not None else "database",
        active=True,
        payload=payload,
        payload_hash=_payload_hash(payload),
        canonical_payload=disk_case.payload if disk_case is not None else None,
        disk_hash=disk_hash,
        overlay_base_disk_hash=base_disk_hash,
        has_disk_changes=has_disk_changes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _merge_case_order(disk_order: Iterable[str], overlay_keys: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for case_id in disk_order:
        if case_id not in seen:
            seen.add(case_id)
            ordered.append(case_id)
    extra_keys = sorted((case_id for case_id in overlay_keys if case_id not in seen), key=str.lower)
    return [*ordered, *extra_keys]


async def list_eval_case_definitions(
    session: AsyncSession, suite: EvalSuite
) -> list[EvalCaseDefinition]:
    """List disk cases with DB overrides, tombstones, and DB-only cases applied."""
    disk_cases = get_disk_eval_cases(suite)
    overlays = await _load_overlays(session, suite)
    definitions: list[EvalCaseDefinition] = []
    for case_id in _merge_case_order(disk_cases, overlays):
        definition = _definition_from_parts(
            suite=suite,
            case_id=case_id,
            disk_case=disk_cases.get(case_id),
            row=overlays.get(case_id),
        )
        if definition is not None:
            definitions.append(definition)
    return definitions


async def list_active_eval_case_ids(session: AsyncSession, suite: EvalSuite) -> list[str]:
    """List active effective test-case IDs for the run selector."""
    definitions = await list_eval_case_definitions(session, suite)
    return [definition.case_id for definition in definitions if definition.active]


async def resolve_eval_case_payloads_for_run(
    session: AsyncSession, suite: EvalSuite, selected_case_ids: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    """Resolve effective case payloads for one API-started run."""
    definitions = [
        definition
        for definition in await list_eval_case_definitions(session, suite)
        if definition.active
    ]
    if not definitions:
        raise EvalCaseNotFoundError(f"No active {suite.value} eval test cases found")
    if selected_case_ids:
        selected = set(selected_case_ids)
        known = {definition.case_id for definition in definitions}
        unknown = sorted(selected - known)
        if unknown:
            raise EvalCaseNotFoundError(
                f"No matching active test cases found for: {', '.join(unknown)}"
            )
        definitions = [definition for definition in definitions if definition.case_id in selected]
    return tuple(definition.payload for definition in definitions)


async def create_eval_case_overlay(
    session: AsyncSession, *, suite: EvalSuite, payload: dict[str, Any], user_id: UUID
) -> EvalCaseDefinition:
    """Create a DB-only eval case. Disk case IDs cannot be created here."""
    normalized = validate_eval_case_payload(suite, payload)
    case_id = str(normalized["test_case_id"])
    if case_id in get_disk_eval_cases(suite):
        raise EvalCaseConflictError("A disk-backed case already uses this test_case_id")

    existing = await session.scalar(
        select(EvalTestCaseOverlay).where(
            EvalTestCaseOverlay.suite == suite.value, EvalTestCaseOverlay.case_id == case_id
        )
    )
    if existing is not None and not existing.is_deleted and existing.case_data is not None:
        raise EvalCaseConflictError("A DB-backed case already uses this test_case_id")

    row = existing or EvalTestCaseOverlay(suite=suite.value, case_id=case_id)
    row.case_data = normalized
    row.is_deleted = False
    row.base_disk_hash = None
    row.updated_by_user_id = user_id
    if existing is None:
        row.created_by_user_id = user_id
        session.add(row)
    await session.commit()
    await session.refresh(row)
    definition = _definition_from_parts(suite=suite, case_id=case_id, disk_case=None, row=row)
    if definition is None:
        raise RuntimeError("Saved eval test case could not be loaded")
    return definition


async def update_eval_case_overlay(
    session: AsyncSession, *, suite: EvalSuite, case_id: str, payload: dict[str, Any], user_id: UUID
) -> EvalCaseDefinition:
    """Update a DB-only case or create an override for a disk case."""
    normalized = validate_eval_case_payload(suite, payload, expected_case_id=case_id)
    disk_case = get_disk_eval_cases(suite).get(case_id)
    existing = await session.scalar(
        select(EvalTestCaseOverlay).where(
            EvalTestCaseOverlay.suite == suite.value, EvalTestCaseOverlay.case_id == case_id
        )
    )
    if disk_case is None and existing is None:
        raise EvalCaseNotFoundError("Eval test case not found")

    row = existing or EvalTestCaseOverlay(suite=suite.value, case_id=case_id)
    row.case_data = normalized
    row.is_deleted = False
    row.base_disk_hash = disk_case.payload_hash if disk_case is not None else None
    row.updated_by_user_id = user_id
    if existing is None:
        row.created_by_user_id = user_id
        session.add(row)
    await session.commit()
    await session.refresh(row)
    definition = _definition_from_parts(suite=suite, case_id=case_id, disk_case=disk_case, row=row)
    if definition is None:
        raise RuntimeError("Saved eval test case could not be loaded")
    return definition


async def delete_eval_case_overlay(
    session: AsyncSession, *, suite: EvalSuite, case_id: str, user_id: UUID
) -> None:
    """Delete a DB-only case or tombstone a disk case without touching disk."""
    disk_case = get_disk_eval_cases(suite).get(case_id)
    existing = await session.scalar(
        select(EvalTestCaseOverlay).where(
            EvalTestCaseOverlay.suite == suite.value, EvalTestCaseOverlay.case_id == case_id
        )
    )

    if disk_case is None:
        if existing is None or existing.case_data is None:
            raise EvalCaseNotFoundError("Eval test case not found")
        await session.delete(existing)
        await session.commit()
        return

    row = existing or EvalTestCaseOverlay(suite=suite.value, case_id=case_id)
    row.case_data = None
    row.is_deleted = True
    row.base_disk_hash = disk_case.payload_hash
    row.updated_by_user_id = user_id
    if existing is None:
        row.created_by_user_id = user_id
        session.add(row)
    await session.commit()


async def restore_disk_eval_case_overlay(
    session: AsyncSession, *, suite: EvalSuite, case_id: str
) -> EvalCaseDefinition:
    """Remove the DB overlay/tombstone for a disk case."""
    disk_case = get_disk_eval_cases(suite).get(case_id)
    if disk_case is None:
        raise EvalCaseNotFoundError("Only disk-backed eval test cases can be restored")

    existing = await session.scalar(
        select(EvalTestCaseOverlay).where(
            EvalTestCaseOverlay.suite == suite.value, EvalTestCaseOverlay.case_id == case_id
        )
    )
    if existing is not None:
        await session.delete(existing)
        await session.commit()

    definition = _definition_from_parts(suite=suite, case_id=case_id, disk_case=disk_case, row=None)
    if definition is None:
        raise RuntimeError("Restored eval test case could not be loaded")
    return definition
