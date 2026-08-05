from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services.teaching_target_resolution import (
    FixedAdhocTargetResolution,
    GlobalExcludedResolution,
    MappedTargetResolution,
    PendingMappingResolution,
    TeachingTargetResolutionUnavailable,
    _resolution_from_row,
    resolve_native_teaching_target,
)


def _scope_row(*, outcome: str | None, unavailable_reason: str | None = None) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "unavailable_reason": unavailable_reason,
        "event_id": uuid4(),
        "reporting_period_id": uuid4(),
        "programme_code": "GERI",
        "posting_code": "TTSHGerMed",
        "r_year": "R2",
        "global_session_type_id": uuid4(),
        "teaching_name_id": uuid4(),
        "mapping_id": uuid4(),
        "mapping_revision": 7,
        "teaching_target_id": uuid4(),
        "session_type_id": uuid4(),
    }


def test_resolution_row_preserves_only_relevant_global_evidence() -> None:
    row = _scope_row(outcome="global_excluded")

    resolution = _resolution_from_row(row)

    assert resolution == GlobalExcludedResolution(
        kind="global_excluded",
        event_id=row["event_id"],
        global_session_type_id=row["global_session_type_id"],
    )


def test_resolution_row_preserves_fixed_adhoc_target_identity() -> None:
    row = _scope_row(outcome="fixed_adhoc_target")

    resolution = _resolution_from_row(row)

    assert resolution == FixedAdhocTargetResolution(
        kind="fixed_adhoc_target",
        event_id=row["event_id"],
        reporting_period_id=row["reporting_period_id"],
        programme_code="GERI",
        posting_code="TTSHGerMed",
        r_year="R2",
        teaching_target_id=row["teaching_target_id"],
        session_type_id=row["session_type_id"],
    )


def test_resolution_row_preserves_exact_mapping_revision_and_target() -> None:
    row = _scope_row(outcome="mapped_target")

    resolution = _resolution_from_row(row)

    assert resolution == MappedTargetResolution(
        kind="mapped_target",
        event_id=row["event_id"],
        reporting_period_id=row["reporting_period_id"],
        programme_code="GERI",
        posting_code="TTSHGerMed",
        r_year="R2",
        teaching_name_id=row["teaching_name_id"],
        mapping_id=row["mapping_id"],
        mapping_revision=7,
        teaching_target_id=row["teaching_target_id"],
        session_type_id=row["session_type_id"],
    )


def test_resolution_row_preserves_pending_mapping_without_target() -> None:
    row = _scope_row(outcome="pending_mapping")
    row["teaching_target_id"] = None
    row["session_type_id"] = None

    resolution = _resolution_from_row(row)

    assert resolution == PendingMappingResolution(
        kind="pending_mapping",
        event_id=row["event_id"],
        reporting_period_id=row["reporting_period_id"],
        programme_code="GERI",
        posting_code="TTSHGerMed",
        r_year="R2",
        teaching_name_id=row["teaching_name_id"],
        mapping_id=row["mapping_id"],
        mapping_revision=7,
    )


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (None, "legacy_source_unsupported"),
        (None, "invalid_source_provenance"),
        (None, "target_scope_mismatch"),
        (None, "fixed_adhoc_target_unavailable"),
        (None, "mapping_unavailable"),
        ("not_a_resolver_outcome", None),
    ],
)
def test_unavailable_or_invalid_helper_rows_raise_internal_unavailable(
    outcome: str | None,
    reason: str | None,
) -> None:
    with pytest.raises(TeachingTargetResolutionUnavailable) as error:
        _resolution_from_row(_scope_row(outcome=outcome, unavailable_reason=reason))

    assert error.value.reason in {
        "legacy_source_unsupported",
        "invalid_source_provenance",
        "target_scope_mismatch",
        "fixed_adhoc_target_unavailable",
        "mapping_unavailable",
        "invalid_helper_outcome",
    }


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._row


class _ReadOnlyDb:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.calls: list[dict[str, str]] = []

    async def execute(self, _statement: Any, parameters: dict[str, str]) -> _Result:
        self.calls.append(parameters)
        return _Result(self.row)

    async def commit(self) -> None:  # pragma: no cover - must never be called
        raise AssertionError("target resolution must not commit")


@pytest.mark.asyncio
async def test_resolution_executes_only_the_read_helper_without_mutating_evidence() -> None:
    resident_id = uuid4()
    event_id = uuid4()
    row = _scope_row(outcome="mapped_target")
    db = _ReadOnlyDb(row)

    resolution = await resolve_native_teaching_target(
        db,  # type: ignore[arg-type]
        resident_id=resident_id,
        event_id=event_id,
    )

    assert isinstance(resolution, MappedTargetResolution)
    assert db.calls == [{"resident_id": str(resident_id), "event_id": str(event_id)}]


@pytest.mark.asyncio
async def test_missing_helper_row_is_not_converted_to_a_fifth_kind() -> None:
    with pytest.raises(TeachingTargetResolutionUnavailable) as error:
        await resolve_native_teaching_target(
            _ReadOnlyDb(None),  # type: ignore[arg-type]
            resident_id=uuid4(),
            event_id=uuid4(),
        )

    assert error.value.reason == "not_available"
