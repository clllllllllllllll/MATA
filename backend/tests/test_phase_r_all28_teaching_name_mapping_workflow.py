"""Phase R all-28 Teaching Name and exact-mapping workflow evidence.

This is deliberately a focused, test-only layer.  It invokes the current
Teaching Name and mapping services with deterministic synthetic identities and
small in-memory SQL-result fakes; PostgreSQL/RLS behavior remains covered by
the dedicated restricted-role suites.  Production programme configuration is
still sourced from persisted rows -- the Phase R manifest is used here only to
attest that each canonical programme can follow the same workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid5

import pytest
from sqlalchemy.exc import IntegrityError

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError
from app.schemas.teaching_name_mappings import TeachingNameMappingBulkItemRequest
from app.services import teaching_name_mappings, teaching_name_pool
from tests.phase_r_readiness_manifest import PROGRAMME_READINESS_EXPECTATIONS


_PHASE_R_NAMESPACE = UUID("2c9f27bc-e36e-45d3-93b8-3d4486d7ef9b")
_NOW = datetime(2026, 8, 6, tzinfo=timezone.utc)


def _id(*parts: str) -> UUID:
    return uuid5(_PHASE_R_NAMESPACE, "/".join(parts))


def _other_programme(programme_code: str) -> str:
    return next(
        expectation.code
        for expectation in PROGRAMME_READINESS_EXPECTATIONS
        if expectation.code != programme_code
    )


class _Result:
    """Small SQLAlchemy-result analogue used only by this focused test module."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, *, scalar: Any = None) -> None:
        self._rows = [dict(row) for row in rows or []]
        self._scalar = scalar

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows]

    def one(self) -> dict[str, Any]:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected one fake row, got {len(self._rows)}")
        return dict(self._rows[0])

    def one_or_none(self) -> dict[str, Any] | None:
        if len(self._rows) > 1:
            raise AssertionError(f"Expected at most one fake row, got {len(self._rows)}")
        return dict(self._rows[0]) if self._rows else None

    def scalar_one(self) -> Any:
        if self._scalar is None:
            raise AssertionError("Expected one fake scalar")
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _NamedUniqueViolation:
    """Enough PostgreSQL diagnostic shape for the service's duplicate branch."""

    sqlstate = "23505"
    diag = SimpleNamespace(constraint_name="uq_teaching_names_pool_normalized_name")


class _LifecycleSession:
    """Narrow no-I/O fake for the actual Teaching Name lifecycle service."""

    def __init__(
        self,
        *,
        reporting_period_id: UUID,
        next_reporting_period_id: UUID,
        programme_code: str,
    ) -> None:
        self.reporting_period_ids = {reporting_period_id, next_reporting_period_id}
        self.programme_codes = {programme_code}
        self.names: dict[UUID, dict[str, Any]] = {}
        self.commits = 0
        self.rollbacks = 0

    @staticmethod
    def _public_name(row: dict[str, Any], *, locked: bool = False) -> dict[str, Any]:
        response = {
            "id": row["id"],
            "reporting_period_id": row["reporting_period_id"],
            "programme_code": row["programme_code"],
            "teaching_name": row["display_name"],
            "is_active": row["is_active"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deactivated_at": row["deactivated_at"],
        }
        if locked:
            response["normalized_name"] = row["normalized_name"]
        return response

    async def execute(
        self,
        statement: object,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        params = dict(params or {})

        if "SELECT id FROM reporting_periods" in sql:
            reporting_period_id = UUID(str(params["reporting_period_id"]))
            return _Result(scalar=reporting_period_id if reporting_period_id in self.reporting_period_ids else None)

        if "SELECT code FROM programmes" in sql:
            programme_code = str(params["programme_code"])
            return _Result(scalar=programme_code if programme_code in self.programme_codes else None)

        if "SELECT id, is_active" in sql and "FROM teaching_names" in sql:
            reporting_period_id = UUID(str(params["reporting_period_id"]))
            programme_code = str(params["programme_code"])
            normalized_name = str(params["normalized_name"])
            rows = [
                {"id": row["id"], "is_active": row["is_active"]}
                for row in self.names.values()
                if row["reporting_period_id"] == reporting_period_id
                and row["programme_code"] == programme_code
                and row["normalized_name"] == normalized_name
            ]
            return _Result(rows)

        if "INSERT INTO teaching_names" in sql:
            reporting_period_id = UUID(str(params["reporting_period_id"]))
            programme_code = str(params["programme_code"])
            normalized_name = str(params["normalized_name"])
            if any(
                row["reporting_period_id"] == reporting_period_id
                and row["programme_code"] == programme_code
                and row["normalized_name"] == normalized_name
                for row in self.names.values()
            ):
                raise IntegrityError("INSERT teaching_names", params, _NamedUniqueViolation())
            name_id = _id("name", str(reporting_period_id), programme_code, normalized_name)
            row = {
                "id": name_id,
                "reporting_period_id": reporting_period_id,
                "programme_code": programme_code,
                "display_name": str(params["display_name"]),
                "normalized_name": normalized_name,
                "is_active": True,
                "revision": 1,
                "created_at": _NOW,
                "updated_at": _NOW,
                "deactivated_at": None,
            }
            self.names[name_id] = row
            return _Result([self._public_name(row)])

        if "FROM teaching_names" in sql and "WHERE id = :teaching_name_id" in sql:
            name_id = UUID(str(params["teaching_name_id"]))
            row = self.names.get(name_id)
            return _Result([self._public_name(row, locked=True)] if row is not None else [])

        if "UPDATE teaching_names" in sql:
            name_id = UUID(str(params["teaching_name_id"]))
            row = self.names[name_id]
            if row["revision"] != params["expected_revision"]:
                return _Result()
            if "SET display_name" in sql:
                row["display_name"] = str(params["display_name"])
                row["normalized_name"] = str(params["normalized_name"])
            elif "SET is_active = false" in sql:
                row["is_active"] = False
                row["deactivated_at"] = _NOW
            elif "SET is_active = true" in sql:
                row["is_active"] = True
                row["deactivated_at"] = None
            else:
                raise AssertionError(f"Unhandled lifecycle update SQL: {sql}")
            row["revision"] = int(row["revision"]) + 1
            row["updated_at"] = _NOW
            return _Result([self._public_name(row)])

        if "SELECT COUNT(*) FROM teaching_names" in sql:
            return _Result(
                scalar=len(self._filtered_names(params)),
            )

        if "FROM teaching_names" in sql:
            rows = [self._public_name(row) for row in self._filtered_names(params)]
            rows.sort(key=lambda row: (str(row["teaching_name"]), str(row["id"])))
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", len(rows)))
            return _Result(rows[offset : offset + limit])

        raise AssertionError(f"Unhandled Phase R lifecycle SQL: {sql}")

    def _filtered_names(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        reporting_period_id = UUID(str(params["reporting_period_id"]))
        programme_code = str(params["programme_code"])
        rows = [
            row
            for row in self.names.values()
            if row["reporting_period_id"] == reporting_period_id
            and row["programme_code"] == programme_code
        ]
        if "is_active" in params:
            rows = [row for row in rows if row["is_active"] is params["is_active"]]
        return rows

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@dataclass(frozen=True)
class _Revalidation:
    audit_metadata: dict[str, Any]


def _programme_pc_actor(programme_code: str) -> teaching_name_pool.TeachingNamePoolActor:
    actor_id = _id("programme-pc", programme_code)
    return teaching_name_pool.TeachingNamePoolActor(
        kind="programme_pc",
        user_id=actor_id,
        programme_scope=frozenset({f" {programme_code.lower()} "}),
        staff_actor=StaffActorContext(
            actor_user_id=actor_id,
            actor_role="admin",
            actor_name=f"Phase R synthetic {programme_code} PC",
            actor_programme=programme_code,
            raw_scope_metadata={"programme_scope": [programme_code]},
        ),
    )


def _master_actor(programme_code: str) -> teaching_name_pool.TeachingNamePoolActor:
    actor_id = _id("master", programme_code)
    return teaching_name_pool.TeachingNamePoolActor(
        kind="master_admin",
        user_id=actor_id,
        staff_actor=StaffActorContext(
            actor_user_id=actor_id,
            actor_role="admin",
            actor_name="Phase R synthetic Master",
            actor_admin_level="master",
        ),
    )


def _secretary_actor(
    programme_code: str,
    *,
    posting_code: str | None = None,
) -> teaching_name_pool.TeachingNamePoolActor:
    actor_id = _id("secretary", programme_code)
    resolved_posting_code = posting_code or f"PHASE_R_{programme_code}_POSTING"
    return teaching_name_pool.TeachingNamePoolActor(
        kind="secretary",
        user_id=actor_id,
        posting_code=resolved_posting_code,
        staff_actor=StaffActorContext(
            actor_user_id=actor_id,
            actor_role="secretary",
            actor_name=f"Phase R synthetic {programme_code} Secretary",
            actor_site=resolved_posting_code,
        ),
    )


def _install_lifecycle_side_effect_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[UUID]]:
    audit_actions: list[str] = []
    invalidated_name_ids: list[UUID] = []

    async def revalidate(*, context, db_session):  # noqa: ANN001, ARG001
        return _Revalidation({"phase_r": True, "action": context.action.value})

    async def audit(_db, *, action, **_kwargs):  # noqa: ANN001
        audit_actions.append(action)

    async def available_lock(_db, **_kwargs):  # noqa: ANN001
        return True

    def invalidate(*, row, **_kwargs):  # noqa: ANN001
        invalidated_name_ids.append(row["id"])

    monkeypatch.setattr(
        teaching_name_pool.data_revalidation_service,
        "revalidate_after_config_change",
        revalidate,
    )
    monkeypatch.setattr(teaching_name_pool, "_write_lifecycle_audit", audit)
    monkeypatch.setattr(teaching_name_pool, "acquire_ttf_scope_lock", available_lock)
    monkeypatch.setattr(teaching_name_pool, "_invalidate_after_commit", invalidate)
    return audit_actions, invalidated_name_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
async def test_phase_r_all28_teaching_name_lifecycle_is_normalized_revision_fenced_and_period_isolated(
    expectation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the supported lifecycle services once for every canonical pool."""

    reporting_period_id = _id("period", expectation.code)
    next_reporting_period_id = _id("next-period", expectation.code)
    session = _LifecycleSession(
        reporting_period_id=reporting_period_id,
        next_reporting_period_id=next_reporting_period_id,
        programme_code=expectation.code,
    )
    audit_actions, invalidated_name_ids = _install_lifecycle_side_effect_fakes(monkeypatch)
    actor = _programme_pc_actor(expectation.code)

    created = await teaching_name_pool.create_teaching_name(
        session,  # type: ignore[arg-type]
        actor=actor,
        reporting_period_id=reporting_period_id,
        programme_code=f"  {expectation.code.lower()}  ",
        teaching_name=f"  Phase R {expectation.code}\u202fTeaching — Review  ",
    )
    name_id = created["id"]
    assert created["teaching_name"] == f"Phase R {expectation.code} Teaching — Review"
    assert created["is_active"] is True
    assert created["revision"] == 1

    with pytest.raises(ApiError) as duplicate:
        await teaching_name_pool.create_teaching_name(
            session,  # type: ignore[arg-type]
            actor=actor,
            reporting_period_id=reporting_period_id,
            programme_code=expectation.code,
            teaching_name=f"phase r {expectation.code} teaching — review",
        )
    assert duplicate.value.status_code == 409
    assert duplicate.value.metadata == {
        "existing_teaching_name_id": str(name_id),
        "may_reactivate": False,
    }

    with pytest.raises(ApiError) as stale_rename:
        await teaching_name_pool.update_teaching_name(
            session,  # type: ignore[arg-type]
            actor=actor,
            teaching_name_id=name_id,
            teaching_name="Stale rename",
            expected_revision=2,
        )
    assert stale_rename.value.status_code == 409

    renamed = await teaching_name_pool.update_teaching_name(
        session,  # type: ignore[arg-type]
        actor=actor,
        teaching_name_id=name_id,
        teaching_name=f"Phase R {expectation.code} Teaching / Renamed",
        expected_revision=1,
    )
    assert renamed["id"] == name_id
    assert renamed["revision"] == 2

    deactivated = await teaching_name_pool.deactivate_teaching_name(
        session,  # type: ignore[arg-type]
        actor=actor,
        teaching_name_id=name_id,
        expected_revision=2,
    )
    assert deactivated["id"] == name_id
    assert deactivated["is_active"] is False
    assert deactivated["revision"] == 3

    inactive_filtered = await teaching_name_pool.list_teaching_names(
        session,  # type: ignore[arg-type]
        actor=actor,
        reporting_period_id=reporting_period_id,
        programme_code=expectation.code,
        is_active=True,
        search=None,
        limit=50,
        offset=0,
    )
    assert inactive_filtered["items"] == []

    reactivated = await teaching_name_pool.reactivate_teaching_name(
        session,  # type: ignore[arg-type]
        actor=actor,
        teaching_name_id=name_id,
        expected_revision=3,
    )
    assert reactivated["id"] == name_id
    assert reactivated["is_active"] is True
    assert reactivated["revision"] == 4

    new_period_pool = await teaching_name_pool.list_teaching_names(
        session,  # type: ignore[arg-type]
        actor=actor,
        reporting_period_id=next_reporting_period_id,
        programme_code=expectation.code,
        is_active=None,
        search=None,
        limit=50,
        offset=0,
    )
    assert new_period_pool == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert audit_actions == ["create", "rename", "deactivate", "reactivate"]
    assert invalidated_name_ids == [name_id, name_id, name_id, name_id]
    assert session.commits == 4
    assert session.rollbacks == 2


def _mapping_row(
    *,
    programme_code: str,
    reporting_period_id: UUID,
    posting_code: str,
    r_year: str,
    target_id: UUID | None,
    mapping_id: UUID | None = None,
    revision: int = 1,
) -> dict[str, Any]:
    resolved_mapping_id = mapping_id or _id(
        "mapping", str(reporting_period_id), programme_code, posting_code, r_year
    )
    session_type_id = _id("session-type", programme_code, r_year)
    return {
        "id": resolved_mapping_id,
        "teaching_name_id": _id("teaching-name", str(reporting_period_id), programme_code),
        "teaching_name": f"Phase R {programme_code} Pool Teaching",
        "teaching_name_is_active": True,
        "teaching_name_revision": 4,
        "reporting_period_id": reporting_period_id,
        "programme_code": programme_code,
        "posting_code": posting_code,
        "r_year": r_year,
        "teaching_target_id": target_id,
        "revision": revision,
        "created_at": _NOW,
        "updated_at": _NOW,
        "target_id": target_id,
        "target_session_type_id": session_type_id if target_id is not None else None,
        "target_session_type_name": "Phase R Pool Teaching [1h]" if target_id else None,
        "target_duration_hours": 1 if target_id else None,
        "target_monthly_target": 2 if target_id else None,
        "target_is_tracked": True if target_id else None,
        "target_is_reallocatable": False if target_id else None,
        "target_tag": None,
    }


def _target_row(
    *,
    target_id: UUID,
    reporting_period_id: UUID,
    programme_code: str,
    posting_code: str,
    r_year: str,
) -> dict[str, Any]:
    return {
        "id": target_id,
        "reporting_period_id": reporting_period_id,
        "programme_code": programme_code,
        "posting_code": posting_code,
        "r_year": r_year,
        "session_type_id": _id("session-type", programme_code, r_year),
        "session_type_name": "Phase R Pool Teaching [1h]",
        "duration_hours": 1,
        "monthly_target": 2,
        "is_tracked": True,
        "is_reallocatable": False,
        "tag": None,
    }


@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
def test_phase_r_all28_mapping_states_and_target_scope_are_exact(expectation) -> None:
    """Pending/mapped state derives only from an exact period/programme/posting/R-year target."""

    reporting_period_id = _id("mapping-period", expectation.code)
    posting_code = f"PHASE_R_{expectation.code}_POSTING"
    r_year = expectation.expected_fixture_r_years[0]
    target_id = _id("target", expectation.code)
    pending = _mapping_row(
        programme_code=expectation.code,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        r_year=r_year,
        target_id=None,
    )
    exact_target = _target_row(
        target_id=target_id,
        reporting_period_id=reporting_period_id,
        programme_code=expectation.code,
        posting_code=posting_code,
        r_year=r_year,
    )

    teaching_name_mappings._require_exact_locked_target(
        mapping=pending,
        target=exact_target,
    )
    assert teaching_name_mappings._mapping_response(pending, options=[])["state"] == "pending"
    mapped = {**pending, "teaching_target_id": target_id, "target_id": target_id}
    mapped.update(
        {
            "target_session_type_id": exact_target["session_type_id"],
            "target_session_type_name": exact_target["session_type_name"],
            "target_duration_hours": exact_target["duration_hours"],
            "target_monthly_target": exact_target["monthly_target"],
            "target_is_tracked": exact_target["is_tracked"],
            "target_is_reallocatable": exact_target["is_reallocatable"],
            "target_tag": exact_target["tag"],
        }
    )
    mapped_response = teaching_name_mappings._mapping_response(mapped, options=[])
    assert mapped_response["state"] == "mapped"
    assert mapped_response["teaching_target_id"] == target_id

    invalid_scopes = {
        "posting": {**exact_target, "posting_code": f"{posting_code}_OTHER"},
        "r_year": {
            **exact_target,
            "r_year": "R5" if r_year != "R5" else "R4",
        },
        "period": {
            **exact_target,
            "reporting_period_id": _id("other-period", expectation.code),
        },
        "programme": {
            **exact_target,
            "programme_code": _other_programme(expectation.code),
        },
    }
    for altered_target in invalid_scopes.values():
        with pytest.raises(ApiError) as rejected:
            teaching_name_mappings._require_exact_locked_target(
                mapping=pending,
                target=altered_target,
            )
        assert rejected.value.status_code == 422


class _MappingSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@dataclass
class _SingleMappingHarness:
    session: _MappingSession
    row: dict[str, Any]
    targets: dict[UUID, dict[str, Any]]
    impact: dict[str, int]
    persisted_mapping_ids: list[UUID]
    invalidated_mapping_ids: list[UUID]


def _install_single_mapping_harness(
    monkeypatch: pytest.MonkeyPatch,
    harness: _SingleMappingHarness,
) -> None:
    async def mapping_row(_db, *, mapping_id, **_kwargs):  # noqa: ANN001
        assert mapping_id == harness.row["id"]
        return dict(harness.row)

    async def scope_lock(_db, **_kwargs):  # noqa: ANN001
        return None

    async def locked_target(_db, *, target_id, mapping):  # noqa: ANN001
        target = dict(harness.targets[target_id])
        teaching_name_mappings._require_exact_locked_target(mapping=mapping, target=target)
        return target

    async def impact(_db, *, mapping):  # noqa: ANN001
        if mapping.get("teaching_target_id") is None:
            return {"affected_event_count": 0, "affected_attendance_count": 0}
        return dict(harness.impact)

    async def persist(
        _db,
        *,
        mapping,
        teaching_target_id,
        expected_revision,
        **_kwargs,
    ):  # noqa: ANN001
        assert expected_revision == mapping["revision"]
        target = harness.targets.get(teaching_target_id) if teaching_target_id is not None else None
        after = {
            **harness.row,
            "teaching_target_id": teaching_target_id,
            "revision": int(harness.row["revision"]) + 1,
            "updated_at": _NOW,
            "target_id": teaching_target_id,
            "target_session_type_id": target["session_type_id"] if target else None,
            "target_session_type_name": target["session_type_name"] if target else None,
            "target_duration_hours": target["duration_hours"] if target else None,
            "target_monthly_target": target["monthly_target"] if target else None,
            "target_is_tracked": target["is_tracked"] if target else None,
            "target_is_reallocatable": target["is_reallocatable"] if target else None,
            "target_tag": target["tag"] if target else None,
        }
        harness.row = after
        harness.persisted_mapping_ids.append(after["id"])
        return dict(after), _Revalidation({"phase_r": True})

    async def target_options(_db, **_kwargs):  # noqa: ANN001
        return [
            {
                "id": target["id"],
                "session_type_id": target["session_type_id"],
                "session_type_name": target["session_type_name"],
                "duration_hours": target["duration_hours"],
                "monthly_target": target["monthly_target"],
                "is_tracked": target["is_tracked"],
                "is_reallocatable": target["is_reallocatable"],
                "tag": target["tag"],
            }
            for target in harness.targets.values()
        ]

    async def sync_timings(_db, *, scopes):  # noqa: ANN001
        assert all(
            scope.teaching_name_id == harness.row["teaching_name_id"]
            for scope in scopes
        )
        return 0

    def invalidate(rows):  # noqa: ANN001
        assert harness.session.commits > 0
        harness.invalidated_mapping_ids.extend(row["id"] for row in rows)

    monkeypatch.setattr(teaching_name_mappings, "_mapping_row", mapping_row)
    monkeypatch.setattr(teaching_name_mappings, "_acquire_scope_lock", scope_lock)
    monkeypatch.setattr(teaching_name_mappings, "_locked_target", locked_target)
    monkeypatch.setattr(teaching_name_mappings, "_mapping_impact_counts", impact)
    monkeypatch.setattr(teaching_name_mappings, "_persist_prepared_change", persist)
    monkeypatch.setattr(teaching_name_mappings, "_target_options", target_options)
    monkeypatch.setattr(teaching_name_mappings, "sync_pool_event_timings", sync_timings)
    monkeypatch.setattr(teaching_name_mappings, "_invalidate_after_commit", invalidate)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
async def test_phase_r_all28_mapping_assignment_clear_keeps_ids_and_requires_count_only_impact_confirmation(
    expectation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporting_period_id = _id("mapping-lifecycle-period", expectation.code)
    posting_code = f"PHASE_R_{expectation.code}_POSTING"
    r_year = expectation.expected_fixture_r_years[0]
    target_id = _id("mapping-lifecycle-target", expectation.code)
    row = _mapping_row(
        programme_code=expectation.code,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        r_year=r_year,
        target_id=None,
    )
    target = _target_row(
        target_id=target_id,
        reporting_period_id=reporting_period_id,
        programme_code=expectation.code,
        posting_code=posting_code,
        r_year=r_year,
    )
    harness = _SingleMappingHarness(
        session=_MappingSession(),
        row=row,
        targets={target_id: target},
        impact={"affected_event_count": 2, "affected_attendance_count": 3},
        persisted_mapping_ids=[],
        invalidated_mapping_ids=[],
    )
    _install_single_mapping_harness(monkeypatch, harness)
    actor = _programme_pc_actor(expectation.code)
    original_mapping_id = row["id"]

    assigned = await teaching_name_mappings.apply_mapping_change(
        harness.session,  # type: ignore[arg-type]
        actor=actor,
        mapping_id=original_mapping_id,
        expected_revision=1,
        teaching_target_id=target_id,
        confirm_impact=False,
    )
    assert assigned["id"] == original_mapping_id
    assert assigned["state"] == "mapped"
    assert assigned["teaching_target_id"] == target_id
    assert assigned["revision"] == 2
    assert assigned["impact"] == {"affected_event_count": 0, "affected_attendance_count": 0}

    with pytest.raises(ApiError) as confirmation_required:
        await teaching_name_mappings.apply_mapping_change(
            harness.session,  # type: ignore[arg-type]
            actor=actor,
            mapping_id=original_mapping_id,
            expected_revision=2,
            teaching_target_id=None,
            confirm_impact=False,
        )
    assert confirmation_required.value.status_code == 409
    assert confirmation_required.value.metadata == {
        "impact": {"affected_event_count": 2, "affected_attendance_count": 3},
        "confirmation_required": True,
    }
    assert harness.row["teaching_target_id"] == target_id
    assert harness.row["revision"] == 2

    cleared = await teaching_name_mappings.apply_mapping_change(
        harness.session,  # type: ignore[arg-type]
        actor=actor,
        mapping_id=original_mapping_id,
        expected_revision=2,
        teaching_target_id=None,
        confirm_impact=True,
    )
    assert cleared["id"] == original_mapping_id
    assert cleared["state"] == "pending"
    assert cleared["teaching_target_id"] is None
    assert cleared["revision"] == 3
    assert cleared["impact"] == {"affected_event_count": 2, "affected_attendance_count": 3}
    assert target["id"] == target_id
    assert harness.persisted_mapping_ids == [original_mapping_id, original_mapping_id]
    assert harness.invalidated_mapping_ids == [original_mapping_id, original_mapping_id]
    assert harness.session.commits == 2
    assert harness.session.rollbacks == 1


class _SecretaryCapabilitySession:
    def __init__(self, *, active_capabilities: set[tuple[str, str]]) -> None:
        self.active_capabilities = active_capabilities

    async def execute(
        self,
        statement: object,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        params = dict(params or {})
        assert "FROM secretary_programme_pools" in sql
        posting_code = str(params["posting_code"])
        if "SELECT programme_code" in sql:
            return _Result(
                [
                    {"programme_code": programme_code}
                    for capability_posting, programme_code in sorted(self.active_capabilities)
                    if capability_posting == posting_code
                ]
            )
        programme_code = str(params["programme_code"])
        return _Result(scalar=1 if (posting_code, programme_code) in self.active_capabilities else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
async def test_phase_r_all28_secretary_capability_pc_scope_and_master_resident_boundaries(
    expectation,
) -> None:
    programme_code = expectation.code
    posting_code = f"PHASE_R_{programme_code}_POSTING"
    secretary = _secretary_actor(programme_code, posting_code=posting_code)
    active_capability_session = _SecretaryCapabilitySession(
        active_capabilities={(posting_code, programme_code)},
    )

    await teaching_name_pool._require_actor_scope(
        active_capability_session,  # type: ignore[arg-type]
        actor=secretary,
        programme_code=programme_code,
    )
    assert await teaching_name_pool.list_secretary_programmes(
        active_capability_session,  # type: ignore[arg-type]
        posting_code=posting_code,
    ) == [{"programme_code": programme_code}]

    for no_capability_session in (
        _SecretaryCapabilitySession(active_capabilities=set()),
        _SecretaryCapabilitySession(
            # A differently scoped active capability is not authority for this pool.
            active_capabilities={(posting_code, _other_programme(programme_code))}
        ),
    ):
        with pytest.raises(ApiError) as secretary_denied:
            await teaching_name_pool._require_actor_scope(
                no_capability_session,  # type: ignore[arg-type]
                actor=secretary,
                programme_code=programme_code,
            )
        assert secretary_denied.value.status_code == 403

    pc = _programme_pc_actor(programme_code)
    await teaching_name_pool._require_actor_scope(
        _SecretaryCapabilitySession(active_capabilities=set()),  # type: ignore[arg-type]
        actor=pc,
        programme_code=programme_code,
    )
    with pytest.raises(ApiError) as pc_cross_programme:
        teaching_name_mappings._require_actor_scope(
            pc,
            programme_code=_other_programme(programme_code),
            id_lookup=True,
        )
    assert pc_cross_programme.value.status_code == 404

    master = _master_actor(programme_code)
    teaching_name_mappings._require_mapping_read_actor(master)
    with pytest.raises(ApiError) as master_lifecycle:
        teaching_name_pool._require_non_master_lifecycle_actor(master)
    with pytest.raises(ApiError) as master_mapping_mutation:
        teaching_name_mappings._require_mapping_mutation_actor(master)
    assert master_lifecycle.value.status_code == 403
    assert master_mapping_mutation.value.status_code == 403

    empty_scope_pc = teaching_name_pool.TeachingNamePoolActor(
        kind="programme_pc",
        user_id=_id("empty-pc", programme_code),
        programme_scope=frozenset(),
        staff_actor=pc.staff_actor,
    )
    with pytest.raises(ApiError) as empty_scope_denied:
        teaching_name_mappings._require_mapping_mutation_actor(empty_scope_pc)
    assert empty_scope_denied.value.status_code == 403

    resident = SimpleNamespace(kind="resident", programme_scope=frozenset(), posting_code=None)
    with pytest.raises(ApiError) as resident_mapping_denied:
        teaching_name_mappings._require_mapping_mutation_actor(resident)
    assert resident_mapping_denied.value.status_code == 403
    with pytest.raises(ApiError) as secretary_mapping_denied:
        teaching_name_mappings._require_mapping_mutation_actor(secretary)
    assert secretary_mapping_denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("programme_code", ("ANAES", "PALLMED"))
async def test_phase_r_representative_bulk_mapping_is_atomic_and_returns_count_only_impact(
    programme_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use both actual-R-year representatives to drive the real bulk orchestration."""

    expectation = next(
        row for row in PROGRAMME_READINESS_EXPECTATIONS if row.code == programme_code
    )
    reporting_period_id = _id("bulk-period", programme_code)
    posting_code = f"PHASE_R_{programme_code}_POSTING"
    r_year = expectation.expected_fixture_r_years[0]
    first_mapping_id = _id("bulk-mapping-a", programme_code)
    second_mapping_id = _id("bulk-mapping-b", programme_code)
    assigned_target_id = _id("bulk-target", programme_code)
    old_target_id = _id("bulk-old-target", programme_code)
    first = _mapping_row(
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        r_year=r_year,
        target_id=None,
        mapping_id=first_mapping_id,
    )
    second = _mapping_row(
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        r_year=r_year,
        target_id=old_target_id,
        mapping_id=second_mapping_id,
    )
    session = _MappingSession()
    rows = {first_mapping_id: first, second_mapping_id: second}
    target = _target_row(
        target_id=assigned_target_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        r_year=r_year,
    )
    persisted: list[UUID] = []
    invalidated: list[UUID] = []

    async def mapping_row(_db, *, mapping_id, **_kwargs):  # noqa: ANN001
        return dict(rows[mapping_id])

    async def scope_lock(_db, **_kwargs):  # noqa: ANN001
        return None

    async def locked_mappings(_db, *, mapping_ids):  # noqa: ANN001
        return [dict(rows[mapping_id]) for mapping_id in mapping_ids]

    async def locked_targets(_db, *, target_ids):  # noqa: ANN001
        assert target_ids == [assigned_target_id]
        return {assigned_target_id: dict(target)}

    async def impact(_db, *, mapping):  # noqa: ANN001
        if mapping["id"] == second_mapping_id:
            return {"affected_event_count": 2, "affected_attendance_count": 3}
        return {"affected_event_count": 0, "affected_attendance_count": 0}

    async def persist(_db, *, mapping, teaching_target_id, **_kwargs):  # noqa: ANN001
        target_data = target if teaching_target_id is not None else None
        after = {
            **rows[mapping["id"]],
            "teaching_target_id": teaching_target_id,
            "target_id": teaching_target_id,
            "revision": int(rows[mapping["id"]]["revision"]) + 1,
            "target_session_type_id": target_data["session_type_id"] if target_data else None,
            "target_session_type_name": target_data["session_type_name"] if target_data else None,
            "target_duration_hours": target_data["duration_hours"] if target_data else None,
            "target_monthly_target": target_data["monthly_target"] if target_data else None,
            "target_is_tracked": target_data["is_tracked"] if target_data else None,
            "target_is_reallocatable": target_data["is_reallocatable"] if target_data else None,
            "target_tag": target_data["tag"] if target_data else None,
        }
        rows[mapping["id"]] = after
        persisted.append(mapping["id"])
        return dict(after), _Revalidation({"phase_r": True})

    async def sync_timings(_db, *, scopes):  # noqa: ANN001
        assert all(
            scope.teaching_name_id == first["teaching_name_id"] for scope in scopes
        )
        return 0

    def invalidate(updated):  # noqa: ANN001
        assert session.commits == 1
        invalidated.extend(row["id"] for row in updated)

    monkeypatch.setattr(teaching_name_mappings, "_mapping_row", mapping_row)
    monkeypatch.setattr(teaching_name_mappings, "_acquire_scope_lock", scope_lock)
    monkeypatch.setattr(teaching_name_mappings, "_locked_mappings_for_bulk", locked_mappings)
    monkeypatch.setattr(teaching_name_mappings, "_locked_targets_for_bulk", locked_targets)
    monkeypatch.setattr(teaching_name_mappings, "_mapping_impact_counts", impact)
    monkeypatch.setattr(teaching_name_mappings, "_persist_prepared_change", persist)
    monkeypatch.setattr(teaching_name_mappings, "sync_pool_event_timings", sync_timings)
    monkeypatch.setattr(teaching_name_mappings, "_invalidate_after_commit", invalidate)

    payload = await teaching_name_mappings.apply_bulk_mapping_changes(
        session,  # type: ignore[arg-type]
        actor=_programme_pc_actor(programme_code),
        items=[
            TeachingNameMappingBulkItemRequest(
                mapping_id=second_mapping_id,
                expected_revision=1,
                teaching_target_id=None,
                confirm_impact=True,
            ),
            TeachingNameMappingBulkItemRequest(
                mapping_id=first_mapping_id,
                expected_revision=1,
                teaching_target_id=assigned_target_id,
            ),
        ],
    )
    assert payload == {
        "requested_count": 2,
        "updated_count": 2,
        "mapped_count": 1,
        "pending_count": 1,
        "affected_event_count": 2,
        "affected_attendance_count": 3,
    }
    assert persisted == sorted((first_mapping_id, second_mapping_id), key=str)
    assert invalidated == persisted
    assert rows[first_mapping_id]["revision"] == 2
    assert rows[second_mapping_id]["revision"] == 2
    assert rows[first_mapping_id]["teaching_target_id"] == assigned_target_id
    assert rows[second_mapping_id]["teaching_target_id"] is None
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_phase_r_bulk_scope_failure_is_atomic_and_batch_limit_remains_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign target fails before any bulk write; more than 100 rows is rejected."""

    programme_code = "SPORTSMED"
    reporting_period_id = _id("failed-bulk-period", programme_code)
    posting_code = f"PHASE_R_{programme_code}_POSTING"
    first_mapping_id = _id("failed-bulk-a", programme_code)
    second_mapping_id = _id("failed-bulk-b", programme_code)
    first = _mapping_row(
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        r_year="R4",
        target_id=None,
        mapping_id=first_mapping_id,
    )
    second = _mapping_row(
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        r_year="R4",
        target_id=None,
        mapping_id=second_mapping_id,
    )
    foreign_target_id = _id("failed-bulk-foreign-target", programme_code)
    rows = {first_mapping_id: first, second_mapping_id: second}
    foreign_target = _target_row(
        target_id=foreign_target_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=f"{posting_code}_OTHER",
        r_year="R4",
    )
    session = _MappingSession()
    persisted: list[UUID] = []

    async def mapping_row(_db, *, mapping_id, **_kwargs):  # noqa: ANN001
        return dict(rows[mapping_id])

    async def scope_lock(_db, **_kwargs):  # noqa: ANN001
        return None

    async def locked_mappings(_db, *, mapping_ids):  # noqa: ANN001
        return [dict(rows[mapping_id]) for mapping_id in mapping_ids]

    async def locked_targets(_db, *, target_ids):  # noqa: ANN001
        assert target_ids == [foreign_target_id]
        return {foreign_target_id: dict(foreign_target)}

    async def persist(_db, *, mapping, **_kwargs):  # noqa: ANN001
        persisted.append(mapping["id"])
        raise AssertionError("Bulk writes must wait until every exact-scope check passes")

    monkeypatch.setattr(teaching_name_mappings, "_mapping_row", mapping_row)
    monkeypatch.setattr(teaching_name_mappings, "_acquire_scope_lock", scope_lock)
    monkeypatch.setattr(teaching_name_mappings, "_locked_mappings_for_bulk", locked_mappings)
    monkeypatch.setattr(teaching_name_mappings, "_locked_targets_for_bulk", locked_targets)
    monkeypatch.setattr(teaching_name_mappings, "_persist_prepared_change", persist)

    with pytest.raises(ApiError) as scope_failure:
        await teaching_name_mappings.apply_bulk_mapping_changes(
            session,  # type: ignore[arg-type]
            actor=_programme_pc_actor(programme_code),
            items=[
                TeachingNameMappingBulkItemRequest(
                    mapping_id=first_mapping_id,
                    expected_revision=1,
                    teaching_target_id=foreign_target_id,
                ),
                TeachingNameMappingBulkItemRequest(
                    mapping_id=second_mapping_id,
                    expected_revision=1,
                    teaching_target_id=None,
                ),
            ],
        )
    assert scope_failure.value.status_code == 422
    assert persisted == []
    assert session.commits == 0
    assert session.rollbacks == 1

    too_many = [
        TeachingNameMappingBulkItemRequest(
            mapping_id=_id("over-limit", str(index)),
            expected_revision=1,
            teaching_target_id=None,
        )
        for index in range(101)
    ]
    with pytest.raises(ApiError) as over_limit:
        await teaching_name_mappings.apply_bulk_mapping_changes(
            _MappingSession(),  # type: ignore[arg-type]
            actor=_programme_pc_actor(programme_code),
            items=too_many,
        )
    assert over_limit.value.status_code == 422
