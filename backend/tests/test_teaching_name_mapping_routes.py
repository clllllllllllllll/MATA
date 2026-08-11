from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError
from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationImpactSummary,
    DataRevalidationOutcome,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.schemas.teaching_name_mappings import (
    TeachingNameMappingBulkItemRequest,
    TeachingNameMappingBulkMutationRequest,
)
from app.services import teaching_name_mappings, teaching_name_pool
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware


class _NoopSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app)

    async def override_db():
        yield _NoopSession()

    app.dependency_overrides[admin.get_db_session] = override_db
    app.dependency_overrides[admin.get_exclusive_db_session] = override_db
    app.include_router(admin.router)
    return TestClient(app)


def _admin_headers(*, master: bool = False, scope: str = "DR") -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def _mapping_actor(*, scope: frozenset[str] = frozenset({"DR"})) -> teaching_name_pool.TeachingNamePoolActor:
    user_id = uuid4()
    return teaching_name_pool.TeachingNamePoolActor(
        kind="programme_pc",
        user_id=user_id,
        programme_scope=scope,
        staff_actor=StaffActorContext(
            actor_user_id=user_id,
            actor_role="admin",
            actor_name="Phase D test PC",
            actor_programme="DR",
            raw_scope_metadata={"programme_scope": sorted(scope)},
        ),
    )


def _mapping_row(
    *,
    mapping_id: UUID | None = None,
    teaching_target_id: UUID | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": mapping_id or uuid4(),
        "teaching_name_id": uuid4(),
        "teaching_name": "Journal Club",
        "teaching_name_is_active": True,
        "teaching_name_revision": 2,
        "reporting_period_id": uuid4(),
        "programme_code": "DR",
        "posting_code": "TTSHCardio",
        "r_year": "R1",
        "teaching_target_id": teaching_target_id,
        "revision": 3,
        "created_at": now,
        "updated_at": now,
        "target_id": teaching_target_id,
        "target_session_type_id": uuid4() if teaching_target_id else None,
        "target_session_type_name": "Department/Programme Teaching [1h]" if teaching_target_id else None,
        "target_duration_hours": 1 if teaching_target_id else None,
        "target_monthly_target": 2 if teaching_target_id else None,
        "target_is_tracked": True if teaching_target_id else None,
        "target_is_reallocatable": False if teaching_target_id else None,
        "target_tag": None,
    }


def _queue_payload() -> dict:
    mapping = _mapping_row()
    return {
        "items": [teaching_name_mappings._mapping_response(mapping, options=[])],
        "total": 1,
        "limit": 50,
        "offset": 0,
    }


def _revalidation() -> DataRevalidationImpactSummary:
    return DataRevalidationImpactSummary(
        outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
        trigger_source=DataRevalidationTriggerSource.PC_CONFIG_CHANGE,
        changed_entity=DataRevalidationChangedEntity.TEACHING_NAME_MAPPING,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        summary="Mapping affects only later JIT compliance reads.",
    )


def test_queue_allows_master_oversight_and_in_scope_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    calls: list[str] = []

    async def list_mappings(_db, *, actor, **_kwargs):  # noqa: ANN001
        calls.append(actor.kind)
        return _queue_payload()

    monkeypatch.setattr(teaching_name_mappings, "list_mappings", list_mappings)
    period_id = uuid4()
    pc_response = client.get(
        "/admin/teaching-name-mappings",
        params={"reporting_period_id": str(period_id), "programme_code": "DR"},
        headers=_admin_headers(),
    )
    master_response = client.get(
        "/admin/teaching-name-mappings",
        params={"reporting_period_id": str(period_id)},
        headers=_admin_headers(master=True),
    )

    assert pc_response.status_code == 200
    assert master_response.status_code == 200
    assert calls == ["programme_pc", "master_admin"]
    assert master_response.json()["items"][0]["state"] == "pending"


def test_mapping_mutations_reject_master_empty_scope_secretary_and_resident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    mapping_id = uuid4()

    async def unexpected(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("forbidden request reached the mapping service")

    monkeypatch.setattr(teaching_name_mappings, "apply_mapping_change", unexpected)
    payload = {"expected_revision": 1, "teaching_target_id": str(uuid4())}
    responses = [
        client.patch(
            f"/admin/teaching-name-mappings/{mapping_id}",
            json=payload,
            headers=_admin_headers(master=True),
        ),
        client.patch(
            f"/admin/teaching-name-mappings/{mapping_id}",
            json=payload,
            headers=_admin_headers(scope=""),
        ),
        client.patch(
            f"/admin/teaching-name-mappings/{mapping_id}",
            json=payload,
            headers={"X-User-Role": "secretary", "X-User-Id": str(uuid4())},
        ),
        client.patch(
            f"/admin/teaching-name-mappings/{mapping_id}",
            json=payload,
            headers={"X-User-Role": "resident", "X-User-Id": str(uuid4())},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


def test_mapping_mutation_passes_revision_and_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    mapping_id = uuid4()
    target_id = uuid4()
    called: dict[str, object] = {}
    response_row = _mapping_row(mapping_id=mapping_id, teaching_target_id=target_id)

    async def apply_mapping_change(_db, **kwargs):  # noqa: ANN001
        called.update(kwargs)
        return {
            **teaching_name_mappings._mapping_response(response_row, options=[]),
            "impact": {"affected_event_count": 2, "affected_attendance_count": 3},
            "data_revalidation": _revalidation(),
        }

    monkeypatch.setattr(teaching_name_mappings, "apply_mapping_change", apply_mapping_change)
    response = client.patch(
        f"/admin/teaching-name-mappings/{mapping_id}",
        json={
            "expected_revision": 3,
            "teaching_target_id": str(target_id),
            "confirm_impact": True,
        },
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert called["expected_revision"] == 3
    assert called["teaching_target_id"] == target_id
    assert called["confirm_impact"] is True
    assert response.json()["impact"] == {
        "affected_event_count": 2,
        "affected_attendance_count": 3,
    }


def test_impact_and_bulk_responses_are_aggregate_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    mapping_id = uuid4()

    async def get_impact(_db, **_kwargs):  # noqa: ANN001
        return {"affected_event_count": 4, "affected_attendance_count": 5}

    async def apply_bulk(_db, **_kwargs):  # noqa: ANN001
        return {
            "requested_count": 2,
            "updated_count": 2,
            "mapped_count": 1,
            "pending_count": 1,
            "affected_event_count": 4,
            "affected_attendance_count": 5,
        }

    monkeypatch.setattr(teaching_name_mappings, "get_mapping_impact", get_impact)
    monkeypatch.setattr(teaching_name_mappings, "apply_bulk_mapping_changes", apply_bulk)
    impact = client.get(
        f"/admin/teaching-name-mappings/{mapping_id}/impact",
        params={"expected_revision": 1},
        headers=_admin_headers(),
    )
    bulk = client.post(
        "/admin/teaching-name-mappings/bulk",
        json={
            "items": [
                {"mapping_id": str(uuid4()), "expected_revision": 1, "teaching_target_id": str(uuid4())},
                {"mapping_id": str(uuid4()), "expected_revision": 2, "teaching_target_id": None},
            ]
        },
        headers=_admin_headers(),
    )

    assert impact.status_code == 200
    assert set(impact.json()) == {"affected_event_count", "affected_attendance_count"}
    assert bulk.status_code == 200
    assert set(bulk.json()) == {
        "requested_count",
        "updated_count",
        "mapped_count",
        "pending_count",
        "affected_event_count",
        "affected_attendance_count",
    }


def test_bulk_schema_rejects_duplicate_mapping_ids() -> None:
    mapping_id = uuid4()
    with pytest.raises(ValidationError):
        TeachingNameMappingBulkMutationRequest.model_validate(
            {
                "items": [
                    {
                        "mapping_id": mapping_id,
                        "expected_revision": 1,
                        "teaching_target_id": None,
                    },
                    {
                        "mapping_id": mapping_id,
                        "expected_revision": 1,
                        "teaching_target_id": None,
                    },
                ]
            }
        )


def test_mapping_request_requires_an_explicit_target_or_clear() -> None:
    with pytest.raises(ValidationError):
        TeachingNameMappingBulkMutationRequest.model_validate(
            {
                "items": [
                    {
                        "mapping_id": uuid4(),
                        "expected_revision": 1,
                    }
                ]
            }
        )


def test_mapping_change_rejects_a_stale_revision() -> None:
    mapping = _mapping_row(teaching_target_id=None)

    async def exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_mappings._prepare_locked_change(
                _NoopSession(),  # type: ignore[arg-type]
                actor=_mapping_actor(),
                mapping=mapping,
                expected_revision=2,
                teaching_target_id=uuid4(),
                confirm_impact=False,
            )
        assert caught.value.status_code == 409

    asyncio.run(exercise())


def test_mapping_change_stops_when_the_shared_ttf_scope_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _mapping_row()
    session = _NoopSession()
    lock_calls: list[tuple[UUID, str]] = []

    async def mapping_row(_db, *, mapping_id, **_kwargs):  # noqa: ANN001
        assert mapping_id == mapping["id"]
        return mapping

    async def held_lock(_db, *, reporting_period_id, programme_code):  # noqa: ANN001
        lock_calls.append((reporting_period_id, programme_code))
        return False

    monkeypatch.setattr(teaching_name_mappings, "_mapping_row", mapping_row)
    monkeypatch.setattr(teaching_name_mappings, "acquire_ttf_scope_lock", held_lock)

    async def exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_mappings.apply_mapping_change(
                session,  # type: ignore[arg-type]
                actor=_mapping_actor(),
                mapping_id=mapping["id"],
                expected_revision=mapping["revision"],
                teaching_target_id=uuid4(),
                confirm_impact=False,
            )
        assert caught.value.status_code == 409

    asyncio.run(exercise())
    assert lock_calls == [(mapping["reporting_period_id"], "DR")]
    assert session.commit_count == 0
    assert session.rollback_count == 1


def test_bulk_mapping_prevalidates_every_item_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping_ids = sorted((uuid4(), uuid4()), key=str)
    first = _mapping_row(mapping_id=mapping_ids[0], teaching_target_id=uuid4())
    second = _mapping_row(mapping_id=mapping_ids[1], teaching_target_id=uuid4())
    second["reporting_period_id"] = first["reporting_period_id"]
    second["programme_code"] = first["programme_code"]
    rows = {first["id"]: first, second["id"]: second}
    session = _NoopSession()
    persisted: list[UUID] = []
    lock_calls: list[tuple[str, str]] = []

    async def mapping_row(_db, *, mapping_id, **_kwargs):  # noqa: ANN001
        return rows[mapping_id]

    async def acquire_scope_lock(_db, *, reporting_period_id, programme_code):  # noqa: ANN001
        lock_calls.append((str(reporting_period_id), programme_code))

    async def locked_mappings(_db, *, mapping_ids):  # noqa: ANN001
        assert mapping_ids == sorted(mapping_ids, key=str)
        return [rows[mapping_id] for mapping_id in mapping_ids]

    async def locked_targets(_db, *, target_ids):  # noqa: ANN001
        assert target_ids == []
        return {}

    async def prepare(_db, *, mapping, **_kwargs):  # noqa: ANN001
        if mapping["id"] == second["id"]:
            raise ApiError(status_code=409, detail="stale", error_code="conflict")
        return {"affected_event_count": 0, "affected_attendance_count": 0}, False

    async def persist(_db, *, mapping, **_kwargs):  # noqa: ANN001
        persisted.append(mapping["id"])
        raise AssertionError("writes must wait until every bulk item validates")

    monkeypatch.setattr(teaching_name_mappings, "_mapping_row", mapping_row)
    monkeypatch.setattr(teaching_name_mappings, "_acquire_scope_lock", acquire_scope_lock)
    monkeypatch.setattr(teaching_name_mappings, "_locked_mappings_for_bulk", locked_mappings)
    monkeypatch.setattr(teaching_name_mappings, "_locked_targets_for_bulk", locked_targets)
    monkeypatch.setattr(teaching_name_mappings, "_prepare_locked_change", prepare)
    monkeypatch.setattr(teaching_name_mappings, "_persist_prepared_change", persist)

    items = [
        TeachingNameMappingBulkItemRequest(
            mapping_id=mapping_id,
            expected_revision=3,
            teaching_target_id=None,
        )
        for mapping_id in reversed(mapping_ids)
    ]

    async def exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_mappings.apply_bulk_mapping_changes(
                session,  # type: ignore[arg-type]
                actor=_mapping_actor(),
                items=items,
            )
        assert caught.value.status_code == 409

    asyncio.run(exercise())
    assert lock_calls == [(str(first["reporting_period_id"]), "DR")]
    assert persisted == []
    assert session.commit_count == 0
    assert session.rollback_count == 1


def test_bulk_mapping_locks_and_invalidates_only_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping_ids = sorted((uuid4(), uuid4()), key=str)
    first = _mapping_row(mapping_id=mapping_ids[0], teaching_target_id=uuid4())
    second = _mapping_row(mapping_id=mapping_ids[1], teaching_target_id=None)
    second["reporting_period_id"] = first["reporting_period_id"]
    second["programme_code"] = first["programme_code"]
    second["posting_code"] = first["posting_code"]
    second["r_year"] = first["r_year"]
    rows = {first["id"]: first, second["id"]: second}
    assigned_target_id = uuid4()
    session = _NoopSession()
    operation_steps: list[str] = []
    persisted: list[UUID] = []

    async def mapping_row(_db, *, mapping_id, **_kwargs):  # noqa: ANN001
        return rows[mapping_id]

    async def acquire_scope_lock(_db, **_kwargs):  # noqa: ANN001
        operation_steps.append("scope")

    async def locked_mappings(_db, *, mapping_ids):  # noqa: ANN001
        operation_steps.append("mappings")
        assert mapping_ids == sorted(mapping_ids, key=str)
        return [rows[mapping_id] for mapping_id in mapping_ids]

    async def locked_targets(_db, *, target_ids):  # noqa: ANN001
        operation_steps.append("targets")
        assert target_ids == [assigned_target_id]
        return {
            assigned_target_id: {
                "id": assigned_target_id,
                "reporting_period_id": first["reporting_period_id"],
                "programme_code": first["programme_code"],
                "posting_code": first["posting_code"],
                "r_year": first["r_year"],
            }
        }

    async def prepare(_db, **_kwargs):  # noqa: ANN001
        operation_steps.append("prepare")
        return {"affected_event_count": 0, "affected_attendance_count": 0}, False

    async def persist(_db, *, mapping, teaching_target_id, **_kwargs):  # noqa: ANN001
        operation_steps.append("persist")
        persisted.append(mapping["id"])
        return {
            **mapping,
            "teaching_target_id": teaching_target_id,
            "revision": mapping["revision"] + 1,
        }, _revalidation()

    async def sync(_db, *, scopes):  # noqa: ANN001
        operation_steps.append("sync")
        assert len(list(scopes)) == 2
        return 0

    def invalidate(updated):  # noqa: ANN001
        operation_steps.append("invalidate")
        assert session.commit_count == 1
        assert [row["id"] for row in updated] == mapping_ids

    monkeypatch.setattr(teaching_name_mappings, "_mapping_row", mapping_row)
    monkeypatch.setattr(teaching_name_mappings, "_acquire_scope_lock", acquire_scope_lock)
    monkeypatch.setattr(teaching_name_mappings, "_locked_mappings_for_bulk", locked_mappings)
    monkeypatch.setattr(teaching_name_mappings, "_locked_targets_for_bulk", locked_targets)
    monkeypatch.setattr(teaching_name_mappings, "_prepare_locked_change", prepare)
    monkeypatch.setattr(teaching_name_mappings, "_persist_prepared_change", persist)
    monkeypatch.setattr(teaching_name_mappings, "sync_pool_event_timings", sync)
    monkeypatch.setattr(teaching_name_mappings, "_invalidate_after_commit", invalidate)

    items = [
        TeachingNameMappingBulkItemRequest(
            mapping_id=mapping_ids[1],
            expected_revision=3,
            teaching_target_id=assigned_target_id,
        ),
        TeachingNameMappingBulkItemRequest(
            mapping_id=mapping_ids[0],
            expected_revision=3,
            teaching_target_id=None,
        ),
    ]

    payload = asyncio.run(
        teaching_name_mappings.apply_bulk_mapping_changes(
            session,  # type: ignore[arg-type]
            actor=_mapping_actor(),
            items=items,
        )
    )

    assert persisted == mapping_ids
    assert operation_steps == [
        "scope",
        "mappings",
        "targets",
        "prepare",
        "prepare",
        "persist",
        "persist",
        "sync",
        "invalidate",
    ]
    assert payload == {
        "requested_count": 2,
        "updated_count": 2,
        "mapped_count": 1,
        "pending_count": 1,
        "affected_event_count": 0,
        "affected_attendance_count": 0,
    }
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_bulk_target_scope_mismatch_is_rejected() -> None:
    mapping = _mapping_row()
    target = {
        "reporting_period_id": mapping["reporting_period_id"],
        "programme_code": mapping["programme_code"],
        "posting_code": mapping["posting_code"],
        "r_year": "R2",
    }

    with pytest.raises(ApiError) as caught:
        teaching_name_mappings._require_exact_locked_target(
            mapping=mapping,
            target=target,
        )

    assert caught.value.status_code == 422


def test_nonzero_mapped_impact_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _mapping_row(teaching_target_id=uuid4())

    async def impact(_db, *, mapping):  # noqa: ANN001
        return {"affected_event_count": 1, "affected_attendance_count": 2}

    monkeypatch.setattr(teaching_name_mappings, "_mapping_impact_counts", impact)

    async def exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_mappings._prepare_locked_change(
                _NoopSession(),  # type: ignore[arg-type]
                actor=_mapping_actor(),
                mapping=mapping,
                expected_revision=3,
                teaching_target_id=None,
                confirm_impact=False,
            )
        assert caught.value.status_code == 409
        assert caught.value.metadata == {
            "impact": {"affected_event_count": 1, "affected_attendance_count": 2},
            "confirmation_required": True,
        }

    asyncio.run(exercise())


def test_zero_impact_pending_assignment_requires_no_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _mapping_row(teaching_target_id=None)

    async def lock_target(_db, **_kwargs):  # noqa: ANN001
        return {}

    monkeypatch.setattr(teaching_name_mappings, "_locked_target", lock_target)

    async def impact(_db, *, mapping):  # noqa: ANN001
        return {"affected_event_count": 0, "affected_attendance_count": 0}

    monkeypatch.setattr(teaching_name_mappings, "_mapping_impact_counts", impact)

    async def exercise() -> None:
        impact, confirmation_required = await teaching_name_mappings._prepare_locked_change(
            _NoopSession(),  # type: ignore[arg-type]
            actor=_mapping_actor(),
            mapping=mapping,
            expected_revision=3,
            teaching_target_id=uuid4(),
            confirm_impact=False,
        )
        assert impact == {"affected_event_count": 0, "affected_attendance_count": 0}
        assert confirmation_required is False

    asyncio.run(exercise())


def test_nonzero_pending_assignment_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _mapping_row(teaching_target_id=None)

    async def lock_target(_db, **_kwargs):  # noqa: ANN001
        return {}

    async def impact(_db, *, mapping):  # noqa: ANN001
        return {"affected_event_count": 1, "affected_attendance_count": 0}

    monkeypatch.setattr(teaching_name_mappings, "_locked_target", lock_target)
    monkeypatch.setattr(teaching_name_mappings, "_mapping_impact_counts", impact)

    async def exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_mappings._prepare_locked_change(
                _NoopSession(),  # type: ignore[arg-type]
                actor=_mapping_actor(),
                mapping=mapping,
                expected_revision=3,
                teaching_target_id=uuid4(),
                confirm_impact=False,
            )
        assert caught.value.status_code == 409
        assert caught.value.metadata == {
            "impact": {"affected_event_count": 1, "affected_attendance_count": 0},
            "confirmation_required": True,
        }

    asyncio.run(exercise())
