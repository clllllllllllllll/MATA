"""Deterministic, read-only native teaching-target resolution.

This is intentionally a classification seam, not a compliance engine.  It
uses only persisted event provenance and the resident's assigned phase for the
event date; it does not calculate counts, targets, percentages, or write any
event/attendance evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, TypeAlias
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


TargetResolutionKind: TypeAlias = Literal[
    "global_excluded",
    "fixed_adhoc_target",
    "mapped_target",
    "pending_mapping",
]


class TeachingTargetResolutionUnavailable(RuntimeError):
    """The trusted evidence cannot produce one of the four resolver outcomes.

    ``reason`` is an internal data-quality/unsupported convention.  It is not
    a fifth target-resolution kind and must not become a public API contract.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Teaching target resolution is unavailable: {reason}")


@dataclass(frozen=True, slots=True)
class GlobalExcludedResolution:
    kind: Literal["global_excluded"]
    event_id: UUID
    global_session_type_id: UUID


@dataclass(frozen=True, slots=True)
class FixedAdhocTargetResolution:
    kind: Literal["fixed_adhoc_target"]
    event_id: UUID
    reporting_period_id: UUID
    programme_code: str
    posting_code: str
    r_year: str
    teaching_target_id: UUID
    session_type_id: UUID


@dataclass(frozen=True, slots=True)
class MappedTargetResolution:
    kind: Literal["mapped_target"]
    event_id: UUID
    reporting_period_id: UUID
    programme_code: str
    posting_code: str
    r_year: str
    teaching_name_id: UUID
    mapping_id: UUID
    mapping_revision: int
    teaching_target_id: UUID
    session_type_id: UUID


@dataclass(frozen=True, slots=True)
class PendingMappingResolution:
    kind: Literal["pending_mapping"]
    event_id: UUID
    reporting_period_id: UUID
    programme_code: str
    posting_code: str
    r_year: str
    teaching_name_id: UUID
    mapping_id: UUID
    mapping_revision: int


TeachingTargetResolution: TypeAlias = (
    GlobalExcludedResolution
    | FixedAdhocTargetResolution
    | MappedTargetResolution
    | PendingMappingResolution
)


_RESOLVE_NATIVE_TEACHING_TARGET_SQL = text(
    """
    SELECT
        outcome,
        unavailable_reason,
        event_id,
        reporting_period_id,
        programme_code,
        posting_code,
        r_year,
        global_session_type_id,
        teaching_name_id,
        mapping_id,
        mapping_revision,
        teaching_target_id,
        session_type_id
    FROM mata_rls.resolve_native_teaching_target(
        :resident_id,
        :event_id
    )
    """
)


async def resolve_native_teaching_target(
    db: AsyncSession,
    *,
    resident_id: UUID,
    event_id: UUID,
) -> TeachingTargetResolution:
    """Resolve one authorized native event at read time without writing state.

    Callers remain responsible for their route-level Resident/PC/Master scope
    checks.  The database helper repeats the relevant RLS visibility checks and
    derives all source and phase inputs itself, so this service cannot turn
    caller-supplied programme, posting, R-year, text, or session type into a
    target choice.
    """

    result = await db.execute(
        _RESOLVE_NATIVE_TEACHING_TARGET_SQL,
        {"resident_id": str(resident_id), "event_id": str(event_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise TeachingTargetResolutionUnavailable("not_available")
    return _resolution_from_row(row)


def _resolution_from_row(row: Mapping[str, Any]) -> TeachingTargetResolution:
    outcome = row.get("outcome")
    if outcome is None:
        reason = row.get("unavailable_reason")
        raise TeachingTargetResolutionUnavailable(
            str(reason) if isinstance(reason, str) and reason else "invalid_evidence"
        )

    if outcome == "global_excluded":
        return GlobalExcludedResolution(
            kind="global_excluded",
            event_id=_required_uuid(row, "event_id"),
            global_session_type_id=_required_uuid(row, "global_session_type_id"),
        )

    if outcome == "fixed_adhoc_target":
        return FixedAdhocTargetResolution(
            kind="fixed_adhoc_target",
            event_id=_required_uuid(row, "event_id"),
            reporting_period_id=_required_uuid(row, "reporting_period_id"),
            programme_code=_required_str(row, "programme_code"),
            posting_code=_required_str(row, "posting_code"),
            r_year=_required_str(row, "r_year"),
            teaching_target_id=_required_uuid(row, "teaching_target_id"),
            session_type_id=_required_uuid(row, "session_type_id"),
        )

    if outcome == "mapped_target":
        return MappedTargetResolution(
            kind="mapped_target",
            event_id=_required_uuid(row, "event_id"),
            reporting_period_id=_required_uuid(row, "reporting_period_id"),
            programme_code=_required_str(row, "programme_code"),
            posting_code=_required_str(row, "posting_code"),
            r_year=_required_str(row, "r_year"),
            teaching_name_id=_required_uuid(row, "teaching_name_id"),
            mapping_id=_required_uuid(row, "mapping_id"),
            mapping_revision=_required_int(row, "mapping_revision"),
            teaching_target_id=_required_uuid(row, "teaching_target_id"),
            session_type_id=_required_uuid(row, "session_type_id"),
        )

    if outcome == "pending_mapping":
        return PendingMappingResolution(
            kind="pending_mapping",
            event_id=_required_uuid(row, "event_id"),
            reporting_period_id=_required_uuid(row, "reporting_period_id"),
            programme_code=_required_str(row, "programme_code"),
            posting_code=_required_str(row, "posting_code"),
            r_year=_required_str(row, "r_year"),
            teaching_name_id=_required_uuid(row, "teaching_name_id"),
            mapping_id=_required_uuid(row, "mapping_id"),
            mapping_revision=_required_int(row, "mapping_revision"),
        )

    raise TeachingTargetResolutionUnavailable("invalid_helper_outcome")


def _required_uuid(row: Mapping[str, Any], field: str) -> UUID:
    value = row.get(field)
    if isinstance(value, UUID):
        return value
    raise TeachingTargetResolutionUnavailable(f"invalid_{field}")


def _required_str(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, str) and value:
        return value
    raise TeachingTargetResolutionUnavailable(f"invalid_{field}")


def _required_int(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise TeachingTargetResolutionUnavailable(f"invalid_{field}")
