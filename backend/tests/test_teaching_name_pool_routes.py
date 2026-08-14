from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.middleware.errors import install_error_handlers
from app.routers import admin, secretary
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationImpactSummary,
    DataRevalidationOutcome,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.services import teaching_name_pool
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware


class _NoopSession:
    pass


class _HeldTTFScopeLockSession:
    """Fails if a lifecycle mutation reaches SQL after the held shared lock."""

    def __init__(self) -> None:
        self.statements: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ARG002
        self.statements.append(statement)
        raise AssertionError("Held TTF scope lock must prevent lifecycle SQL writes")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _programme_pc_actor(user_id: UUID) -> teaching_name_pool.TeachingNamePoolActor:
    return teaching_name_pool.TeachingNamePoolActor(
        kind="programme_pc",
        user_id=user_id,
        programme_scope=frozenset({"DR"}),
        staff_actor=StaffActorContext(
            actor_user_id=user_id,
            actor_role="admin",
            actor_name="TTF lock regression PC",
            actor_programme="DR",
            raw_scope_metadata={"programme_scope": ["DR"]},
        ),
    )


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app)

    async def override_db():
        yield _NoopSession()

    app.dependency_overrides[admin.get_db_session] = override_db
    app.dependency_overrides[admin.get_exclusive_db_session] = override_db
    app.dependency_overrides[secretary.get_db_session] = override_db
    app.dependency_overrides[secretary.get_exclusive_db_session] = override_db
    app.include_router(admin.router)
    app.include_router(secretary.router)
    return TestClient(app)


def _admin_headers(*, master: bool = False, scope: str = "DR") -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
        "X-User-Programme": scope,
    }
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def _secretary_headers(*, posting_code: str = "TTSHCardio") -> dict[str, str]:
    return {
        "X-User-Role": "secretary",
        "X-User-Id": str(uuid4()),
        "X-User-Site": posting_code,
    }


def _impact(action: DataRevalidationAction) -> DataRevalidationImpactSummary:
    return DataRevalidationImpactSummary(
        outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
        trigger_source=DataRevalidationTriggerSource.PC_CONFIG_CHANGE,
        changed_entity=DataRevalidationChangedEntity.TEACHING_NAME,
        action=action,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        summary="Future compliance impact only",
    )


def _name_payload(
    *,
    teaching_name_id: UUID,
    reporting_period_id: UUID,
    programme_code: str = "DR",
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": teaching_name_id,
        "reporting_period_id": reporting_period_id,
        "programme_code": programme_code,
        "teaching_name": "Journal Club",
        "created_by_role": "secretary",
        "visibility_scope": "department_shared",
        "origin_posting_code": "TTSHCardio",
        "admission_reason": "owner_programme",
        "can_manage_name": True,
        "is_read_only": False,
        "is_active": True,
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "deactivated_at": None,
    }


def test_normalise_teaching_name_uses_nfc_whitespace_casefold_without_punctuation_folding() -> None:
    display_name, normalized_name = teaching_name_pool.normalise_teaching_name(
        "  Cafe\u0301\t/ Case — Review  "
    )

    assert display_name == "Café / Case — Review"
    assert normalized_name == "café / case — review"


def test_normalise_teaching_name_collides_only_for_nfc_equivalents() -> None:
    _, composed = teaching_name_pool.normalise_teaching_name("Café Review")
    _, decomposed = teaching_name_pool.normalise_teaching_name("Cafe\u0301 Review")
    _, em_dash = teaching_name_pool.normalise_teaching_name("Case — Review")
    _, hyphen = teaching_name_pool.normalise_teaching_name("Case - Review")
    _, abbreviation = teaching_name_pool.normalise_teaching_name("Cardio")
    _, expanded = teaching_name_pool.normalise_teaching_name("Cardiology")

    assert composed == decomposed
    assert em_dash != hyphen
    assert abbreviation != expanded


def test_programme_pc_can_manage_only_pc_created_private_names() -> None:
    actor = _programme_pc_actor(uuid4())
    pc_private = {
        "programme_code": "DR",
        "created_by_role": "programme_pc",
        "visibility_scope": "programme_private",
    }

    assert teaching_name_pool._actor_can_manage_name(actor, pc_private) is True
    assert teaching_name_pool._actor_can_manage_name(
        actor,
        {
            **pc_private,
            "created_by_role": "secretary",
            "visibility_scope": "department_shared",
        },
    ) is False
    assert teaching_name_pool._actor_can_manage_name(
        actor,
        {**pc_private, "programme_code": "GERI"},
    ) is False


@pytest.mark.parametrize(
    "value",
    ["\t\n\u00a0", "name\x00with-control", "name\x01with-control", "x" * 201, "ß" * 200],
)
def test_normalise_teaching_name_rejects_blank_control_and_overlong_values(value: str) -> None:
    with pytest.raises(ApiError) as caught:
        teaching_name_pool.normalise_teaching_name(value)

    assert caught.value.status_code == 422


def test_create_teaching_name_uses_shared_ttf_lock_and_held_lock_prevents_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_reporting_period_id = uuid4()
    session = _HeldTTFScopeLockSession()
    actor = _programme_pc_actor(uuid4())
    lock_calls: list[tuple[object, UUID, str]] = []

    async def _scope_exists(_db, *, reporting_period_id, programme_code):  # noqa: ANN001
        assert reporting_period_id == expected_reporting_period_id
        assert programme_code == "DR"

    async def _actor_scope(_db, *, actor, programme_code):  # noqa: ANN001
        assert actor.kind == "programme_pc"
        assert programme_code == "DR"

    async def _held_lock(db, *, reporting_period_id, programme_code):  # noqa: ANN001
        lock_calls.append((db, reporting_period_id, programme_code))
        return False

    monkeypatch.setattr(teaching_name_pool, "_require_scope_exists", _scope_exists)
    monkeypatch.setattr(teaching_name_pool, "_require_actor_scope", _actor_scope)
    monkeypatch.setattr(teaching_name_pool, "acquire_ttf_scope_lock", _held_lock)

    async def _exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_pool.create_teaching_name(
                session,  # type: ignore[arg-type]
                actor=actor,
                reporting_period_id=expected_reporting_period_id,
                programme_code="  dr  ",
                teaching_name="Journal Club",
            )
        assert caught.value.status_code == 409
        assert caught.value.error_code == ErrorCode.CONFLICT.value

    asyncio.run(_exercise())

    assert lock_calls == [(session, expected_reporting_period_id, "DR")]
    assert session.statements == []
    assert session.commits == 0
    assert session.rollbacks == 1


def test_reactivate_teaching_name_uses_shared_ttf_lock_and_held_lock_prevents_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_reporting_period_id = uuid4()
    expected_teaching_name_id = uuid4()
    session = _HeldTTFScopeLockSession()
    actor = _programme_pc_actor(uuid4())
    lock_calls: list[tuple[object, UUID, str]] = []

    async def _locked_name(_db, *, teaching_name_id, actor):  # noqa: ANN001
        assert teaching_name_id == expected_teaching_name_id
        assert actor.kind == "programme_pc"
        return {
            "id": expected_teaching_name_id,
            "reporting_period_id": expected_reporting_period_id,
            "programme_code": "DR",
            "is_active": False,
            "revision": 7,
        }

    async def _held_lock(db, *, reporting_period_id, programme_code):  # noqa: ANN001
        lock_calls.append((db, reporting_period_id, programme_code))
        return False

    monkeypatch.setattr(teaching_name_pool, "_locked_name", _locked_name)
    monkeypatch.setattr(teaching_name_pool, "acquire_ttf_scope_lock", _held_lock)

    async def _exercise() -> None:
        with pytest.raises(ApiError) as caught:
            await teaching_name_pool.reactivate_teaching_name(
                session,  # type: ignore[arg-type]
                actor=actor,
                teaching_name_id=expected_teaching_name_id,
                expected_revision=7,
            )
        assert caught.value.status_code == 409
        assert caught.value.error_code == ErrorCode.CONFLICT.value

    asyncio.run(_exercise())

    assert lock_calls == [(session, expected_reporting_period_id, "DR")]
    assert session.statements == []
    assert session.commits == 0
    assert session.rollbacks == 1


def test_phase_c_routes_are_exposed_at_the_exact_contract_paths() -> None:
    client = _client()
    routes = {
        (route.path, method)
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }

    expected = {
        ("/secretary/teaching-name-programmes", "GET"),
        ("/secretary/teaching-names", "GET"),
        ("/secretary/teaching-names", "POST"),
        ("/secretary/teaching-names/{teaching_name_id}", "PATCH"),
        ("/secretary/teaching-names/{teaching_name_id}/deactivate", "POST"),
        ("/secretary/teaching-names/{teaching_name_id}/reactivate", "POST"),
        ("/secretary/teaching-names/{teaching_name_id}", "DELETE"),
        ("/admin/teaching-names", "GET"),
        ("/admin/teaching-names", "POST"),
        ("/admin/teaching-names/{teaching_name_id}", "PATCH"),
        ("/admin/teaching-names/{teaching_name_id}/deactivate", "POST"),
        ("/admin/teaching-names/{teaching_name_id}/reactivate", "POST"),
        ("/admin/teaching-names/{teaching_name_id}", "DELETE"),
    }
    assert expected <= routes


def test_phase_c_routes_preserve_the_http_error_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    reporting_period_id = uuid4()
    teaching_name_id = uuid4()
    pc_headers = _admin_headers()

    unauthorized = client.get(
        "/admin/teaching-names",
        headers={"X-User-Role": "admin"},
        params={
            "reporting_period_id": str(reporting_period_id),
            "programme_code": "DR",
        },
    )
    assert unauthorized.status_code == 401

    forbidden = client.post(
        "/admin/teaching-names",
        headers=_admin_headers(master=True),
        json={
            "reporting_period_id": str(reporting_period_id),
            "programme_code": "DR",
            "teaching_name": "Journal Club",
        },
    )
    assert forbidden.status_code == 403

    invalid = client.get(
        "/secretary/teaching-names",
        headers=_secretary_headers(),
        params={"reporting_period_id": str(reporting_period_id)},
    )
    assert invalid.status_code == 422

    async def not_found(_db, **_kwargs):  # noqa: ANN001
        raise ApiError(status_code=404, detail="Teaching Name not found")

    monkeypatch.setattr(teaching_name_pool, "delete_teaching_name", not_found)
    missing = client.request(
        "DELETE",
        f"/admin/teaching-names/{teaching_name_id}",
        headers=pc_headers,
        json={"expected_revision": 1},
    )
    assert missing.status_code == 404

    async def conflict(_db, **_kwargs):  # noqa: ANN001
        raise ApiError(status_code=409, detail="Teaching Name has changed; refresh and retry")

    monkeypatch.setattr(teaching_name_pool, "delete_teaching_name", conflict)
    stale = client.request(
        "DELETE",
        f"/admin/teaching-names/{teaching_name_id}",
        headers=pc_headers,
        json={"expected_revision": 1},
    )
    assert stale.status_code == 409


def test_master_admin_is_read_delete_only_while_delete_reaches_shared_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    reporting_period_id = uuid4()
    teaching_name_id = uuid4()
    captured: dict[str, object] = {}

    async def list_names(_db, **kwargs):  # noqa: ANN001
        captured["list_actor"] = kwargs["actor"]
        return {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def delete_name(_db, **kwargs):  # noqa: ANN001
        captured["delete_actor"] = kwargs["actor"]
        return {
            "teaching_name_id": teaching_name_id,
            "deleted": True,
            "used_name": False,
            "event_reference_count": 0,
            "native_attendance_count": 0,
            "non_nhg_attendance_count": 0,
            "data_revalidation": _impact(DataRevalidationAction.DELETE),
        }

    monkeypatch.setattr(teaching_name_pool, "list_teaching_names", list_names)
    monkeypatch.setattr(teaching_name_pool, "delete_teaching_name", delete_name)
    headers = _admin_headers(master=True)

    read_response = client.get(
        "/admin/teaching-names",
        headers=headers,
        params={
            "reporting_period_id": str(reporting_period_id),
            "programme_code": "DR",
        },
    )
    assert read_response.status_code == 200
    assert captured["list_actor"].kind == "master_admin"

    create_response = client.post(
        "/admin/teaching-names",
        headers=headers,
        json={
            "reporting_period_id": str(reporting_period_id),
            "programme_code": "DR",
            "teaching_name": "Journal Club",
        },
    )
    update_response = client.patch(
        f"/admin/teaching-names/{teaching_name_id}",
        headers=headers,
        json={"teaching_name": "Renamed", "expected_revision": 1},
    )
    deactivate_response = client.post(
        f"/admin/teaching-names/{teaching_name_id}/deactivate",
        headers=headers,
        json={"expected_revision": 1},
    )
    reactivate_response = client.post(
        f"/admin/teaching-names/{teaching_name_id}/reactivate",
        headers=headers,
        json={"expected_revision": 1},
    )
    assert [
        create_response.status_code,
        update_response.status_code,
        deactivate_response.status_code,
        reactivate_response.status_code,
    ] == [403, 403, 403, 403]

    delete_response = client.request(
        "DELETE",
        f"/admin/teaching-names/{teaching_name_id}",
        headers=headers,
        json={"expected_revision": 1},
    )
    assert delete_response.status_code == 200
    assert captured["delete_actor"].kind == "master_admin"


def test_secretary_requires_explicit_programme_and_uses_current_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    reporting_period_id = uuid4()
    teaching_name_id = uuid4()
    captured: dict[str, object] = {}

    async def list_programmes(_db, *, posting_code: str):  # noqa: ANN001
        captured["programme_posting_code"] = posting_code
        return [{"programme_code": "DR"}]

    async def list_names(_db, **kwargs):  # noqa: ANN001
        captured["list_actor"] = kwargs["actor"]
        return {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def create_name(_db, **kwargs):  # noqa: ANN001
        captured["create_actor"] = kwargs["actor"]
        captured["create_programme_code"] = kwargs["programme_code"]
        return {
            **_name_payload(
                teaching_name_id=teaching_name_id,
                reporting_period_id=reporting_period_id,
            ),
            "data_revalidation": _impact(DataRevalidationAction.CREATE),
        }

    monkeypatch.setattr(teaching_name_pool, "list_secretary_programmes", list_programmes)
    monkeypatch.setattr(teaching_name_pool, "list_teaching_names", list_names)
    monkeypatch.setattr(teaching_name_pool, "create_teaching_name", create_name)
    headers = _secretary_headers(posting_code="TTSHCardio")

    programmes_response = client.get(
        "/secretary/teaching-name-programmes",
        headers=headers,
    )
    assert programmes_response.status_code == 200
    assert programmes_response.json() == {"items": [{"programme_code": "DR"}]}
    assert captured["programme_posting_code"] == "TTSHCardio"

    missing_programme_response = client.get(
        "/secretary/teaching-names",
        headers=headers,
        params={"reporting_period_id": str(reporting_period_id)},
    )
    assert missing_programme_response.status_code == 422

    list_response = client.get(
        "/secretary/teaching-names",
        headers=headers,
        params={
            "reporting_period_id": str(reporting_period_id),
            "programme_code": "DR",
        },
    )
    assert list_response.status_code == 200
    assert captured["list_actor"].kind == "secretary"
    assert captured["list_actor"].posting_code == "TTSHCardio"

    create_response = client.post(
        "/secretary/teaching-names",
        headers=headers,
        json={
            "reporting_period_id": str(reporting_period_id),
            "programme_code": "DR",
            "teaching_name": "Journal Club",
        },
    )
    assert create_response.status_code == 200
    assert captured["create_actor"].kind == "secretary"
    assert captured["create_programme_code"] == "DR"
