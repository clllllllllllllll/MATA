from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.errors import ApiError
from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.models import Base
from app.routers import admin


def test_audit_log_model_is_registered_with_required_columns_and_indexes() -> None:
    table = Base.metadata.tables["audit_logs"]

    assert set(table.columns.keys()) == {
        "id",
        "actor_user_id",
        "actor_role",
        "actor_name",
        "actor_site",
        "actor_programme",
        "actor_admin_level",
        "action",
        "entity_type",
        "entity_id",
        "before_json",
        "after_json",
        "metadata_json",
        "created_at",
    }
    assert table.c.actor_user_id.nullable is True
    assert table.c.actor_role.nullable is False
    assert table.c.actor_name.nullable is False
    assert table.c.action.nullable is False
    assert table.c.entity_type.nullable is False
    assert table.c.actor_name.type.length == 120
    assert table.c.metadata_json.type.__class__ is postgresql.JSONB

    index_names = {index.name for index in table.indexes}
    assert {
        "idx_audit_logs_created_at",
        "idx_audit_logs_actor_user_created",
        "idx_audit_logs_entity_created",
        "idx_audit_logs_action_created",
        "idx_audit_logs_actor_role_created",
    }.issubset(index_names)


def test_audit_logs_migration_declares_required_table_and_indexes() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260610_000005_audit_logs.py"
    )
    spec = importlib.util.spec_from_file_location("audit_logs_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260610_000005"
    assert module.down_revision == "20260520_000004"
    source = migration_path.read_text(encoding="utf-8")
    assert 'op.create_table(\n        "audit_logs"' in source
    for index_name in [
        "idx_audit_logs_created_at",
        "idx_audit_logs_actor_user_created",
        "idx_audit_logs_entity_created",
        "idx_audit_logs_action_created",
        "idx_audit_logs_actor_role_created",
    ]:
        assert index_name in source


def test_write_audit_log_persists_actor_action_entity_and_json_payloads() -> None:
    from app.dependencies.staff_actor import StaffActorContext
    from app.services.audit import write_audit_log

    class _FakeResult:
        def __init__(self, row: dict) -> None:
            self._row = row

        def mappings(self):
            return self

        def one(self):
            return self._row

    class _FakeAsyncSession:
        def __init__(self) -> None:
            self.statements: list[tuple[str, dict]] = []
            self.committed = False

        async def execute(self, statement, params):
            payload = dict(params)
            self.statements.append((str(statement), payload))
            return _FakeResult({"id": payload["id"], **payload})

        async def commit(self):
            self.committed = True

    actor_user_id = uuid4()

    async def _exercise() -> None:
        session = _FakeAsyncSession()
        row = await write_audit_log(
            session,
            actor=StaffActorContext(
                actor_user_id=actor_user_id,
                actor_role="admin",
                actor_name="Dr Lee",
                actor_site=None,
                actor_programme="DR",
                actor_admin_level="master",
                raw_scope_metadata={"programme_scope": ["DR", "GRM"]},
            ),
            action="admin.config.update",
            entity_type="programmes",
            entity_id=uuid4(),
            before={"r_year_required": False},
            after={"r_year_required": True},
            metadata={"source": "unit-test"},
        )

        assert session.committed is False
        assert len(session.statements) == 1
        sql, params = session.statements[0]
        assert "INSERT INTO audit_logs" in sql
        assert "metadata_json" in sql
        assert UUID(str(row["id"]))
        assert params["actor_user_id"] == str(actor_user_id)
        assert params["actor_role"] == "admin"
        assert params["actor_name"] == "Dr Lee"
        assert params["actor_programme"] == "DR"
        assert params["actor_admin_level"] == "master"
        assert params["action"] == "admin.config.update"
        assert params["entity_type"] == "programmes"
        assert json.loads(params["before_json"]) == {"r_year_required": False}
        assert json.loads(params["after_json"]) == {"r_year_required": True}
        assert json.loads(params["metadata_json"]) == {
            "source": "unit-test",
            "programme_scope": ["DR", "GRM"],
        }

    asyncio.run(_exercise())


def test_write_audit_log_rejects_blank_action_and_entity_type() -> None:
    from app.dependencies.staff_actor import StaffActorContext
    from app.services.audit import write_audit_log

    class _FakeAsyncSession:
        async def execute(self, statement, params):  # pragma: no cover - should not execute
            raise AssertionError("write_audit_log should validate before executing SQL")

    actor = StaffActorContext(
        actor_user_id=uuid4(),
        actor_role="admin",
        actor_name="Dr Lee",
    )

    async def _exercise() -> None:
        for action, entity_type in [("", "programmes"), ("admin.update", " ")]:
            try:
                await write_audit_log(
                    _FakeAsyncSession(),
                    actor=actor,
                    action=action,
                    entity_type=entity_type,
                )
            except ApiError as exc:
                assert exc.status_code == 422
            else:  # pragma: no cover
                raise AssertionError("Expected ApiError")

    asyncio.run(_exercise())


def _staff_actor_client(identity: AuthIdentity | None = None) -> TestClient:
    from app.dependencies.staff_actor import require_staff_actor

    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):
        if identity is not None:
            request.state.identity = identity
        return await call_next(request)

    @app.post("/test/staff-actor")
    async def test_route(actor=Depends(require_staff_actor)):
        return {
            "actor_user_id": str(actor.actor_user_id) if actor.actor_user_id else None,
            "actor_role": actor.actor_role,
            "actor_name": actor.actor_name,
            "actor_site": actor.actor_site,
            "actor_programme": actor.actor_programme,
            "actor_admin_level": actor.actor_admin_level,
            "raw_scope_metadata": actor.raw_scope_metadata,
        }

    return TestClient(app)


def _staff_headers(
    *,
    role: str = "admin",
) -> dict[str, str]:
    return {
        "X-User-Role": role,
        "X-User-Id": str(uuid4()),
        "X-User-Programme": "DR,GRM",
        "X-User-Site": "TTSHCardio",
        "X-Admin-Level": "master",
    }


def test_staff_actor_dependency_uses_authenticated_scope_and_fallback_actor_name() -> None:
    client = _staff_actor_client()

    response = client.post("/test/staff-actor", headers=_staff_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["actor_name"] == "Unknown actor"
    assert payload["actor_role"] == "admin"
    assert payload["actor_programme"] == "DR,GRM"
    assert payload["actor_site"] == "TTSHCardio"
    assert payload["actor_admin_level"] == "master"
    assert payload["raw_scope_metadata"]["programme_scope"] == ["DR", "GRM"]


def test_staff_actor_dependency_prefers_verified_identity_for_master_admin() -> None:
    subject_id = uuid4()
    client = _staff_actor_client(
        AuthIdentity(
            role="admin",
            subject_id=str(subject_id),
            programme_scope=[],
            admin_level="master",
        ),
    )

    response = client.post("/test/staff-actor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["actor_user_id"] == str(subject_id)
    assert payload["actor_role"] == "admin"
    assert payload["actor_admin_level"] == "master"
    assert payload["raw_scope_metadata"]["admin_level"] == "master"


def test_staff_actor_dependency_ignores_legacy_actor_name_header() -> None:
    client = _staff_actor_client()
    legacy_actor_header = "-".join(["X", "Actor", "Name"])

    headers = _staff_headers()
    headers[legacy_actor_header] = "A" * 121
    long_header_response = client.post("/test/staff-actor", headers=headers)

    headers = _staff_headers()
    headers[legacy_actor_header] = "Dr Lee"
    named_header_response = client.post("/test/staff-actor", headers=headers)

    assert [long_header_response.status_code, named_header_response.status_code] == [200, 200]
    assert [
        long_header_response.json()["actor_name"],
        named_header_response.json()["actor_name"],
    ] == [
        "Unknown actor",
        "Unknown actor",
    ]


def test_staff_actor_dependency_rejects_resident_and_external_resident_roles() -> None:
    client = _staff_actor_client()

    resident_response = client.post(
        "/test/staff-actor",
        headers=_staff_headers(role="resident"),
    )
    external_response = client.post(
        "/test/staff-actor",
        headers=_staff_headers(role="external_resident"),
    )

    assert resident_response.status_code == 403
    assert external_response.status_code == 403


def test_existing_read_only_admin_endpoint_does_not_require_actor_name() -> None:
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield None

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.include_router(admin.router)
    client = TestClient(app)

    response = client.get(
        "/admin/reporting-periods",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR",
            "X-Admin-Level": "master",
        },
    )

    assert response.status_code == 200
    assert response.json() == []
