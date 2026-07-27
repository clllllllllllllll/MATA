from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import auth


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> "_FakeResult":
        return self

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected one row, got {len(self._rows)}")
        return self._rows[0]

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError(f"Expected at most one row, got {len(self._rows)}")
        return self._rows[0] if self._rows else None


class _FakeAuthSession:
    def __init__(self) -> None:
        self.user_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.users = [
            {
                "id": self.user_id,
                "email": "pc@nhg.com.sg",
                "password_hash": "password",
                "role": "admin",
                "name": "Generic Programme PC",
                "posting_code": None,
                "programme_scope": ["DR"],
                "admin_level": "programme",
                "is_active": True,
                "current_staff_actor_name": None,
                "staff_actor_name_updated_at": None,
                "staff_actor_name_updated_by_user_id": None,
            }
        ]
        self.residents = [
            {
                "id": self.resident_id,
                "name": "Resident One",
                "mcr": "M12345A",
                "programme_code": "DR",
                "status": "active",
            }
        ]
        self.audit_logs: list[dict] = []
        self.commits = 0

    async def execute(self, statement, params=None):  # noqa: ANN001
        sql = str(statement)
        payload = dict(params or {})

        if "FROM users" in sql and "WHERE id = :user_id" in sql:
            rows = [
                row
                for row in self.users
                if row["id"] == str(payload["user_id"]) and row["is_active"]
            ]
            return _FakeResult(rows)

        if "UPDATE users" in sql and "current_staff_actor_name" in sql:
            rows: list[dict] = []
            for row in self.users:
                if row["id"] == str(payload["user_id"]) and row["is_active"]:
                    row["current_staff_actor_name"] = payload["actor_name"]
                    row["staff_actor_name_updated_by_user_id"] = str(
                        payload["updated_by_user_id"]
                    )
                    rows.append(row)
            return _FakeResult(rows)

        if "FROM residents" in sql and "WHERE id" in sql:
            rows = [
                row
                for row in self.residents
                if row["id"] == str(payload["resident_id"])
            ]
            return _FakeResult(rows)

        if "INSERT INTO audit_logs" in sql:
            self.audit_logs.append(payload)
            return _FakeResult([{"id": payload["id"], **payload}])

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")

    async def commit(self) -> None:
        self.commits += 1


def _client(identity: AuthIdentity, session: _FakeAuthSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):  # noqa: ANN001
        request.state.identity = identity
        return await call_next(request)

    async def _db_override():
        yield session

    app.dependency_overrides[auth.get_db_session] = _db_override
    app.dependency_overrides[auth.get_exclusive_db_session] = _db_override
    app.include_router(auth.router, prefix="/api/v1")
    return TestClient(app)


def test_auth_me_returns_saved_staff_actor_fields_for_staff() -> None:
    session = _FakeAuthSession()
    session.users[0]["current_staff_actor_name"] = "Dr Priya Tan"
    identity = AuthIdentity(
        role="admin",
        subject_id=session.user_id,
        programme_scope=["DR"],
        admin_level="programme",
    )

    response = _client(identity, session).get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_staff_actor_name"] == "Dr Priya Tan"
    assert payload["staff_actor_name_required"] is False


def test_auth_me_marks_staff_actor_name_required_when_blank() -> None:
    session = _FakeAuthSession()
    session.users[0]["current_staff_actor_name"] = " "
    identity = AuthIdentity(
        role="admin",
        subject_id=session.user_id,
        programme_scope=["DR"],
        admin_level="programme",
    )

    response = _client(identity, session).get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["staff_actor_name_required"] is True


def test_update_staff_actor_name_trims_and_persists_name() -> None:
    session = _FakeAuthSession()
    identity = AuthIdentity(
        role="admin",
        subject_id=session.user_id,
        programme_scope=["DR"],
        admin_level="programme",
    )

    response = _client(identity, session).post(
        "/api/v1/auth/staff-actor-name",
        json={"full_name": "  Dr Priya Tan  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_staff_actor_name"] == "Dr Priya Tan"
    assert payload["staff_actor_name_required"] is False
    assert session.users[0]["current_staff_actor_name"] == "Dr Priya Tan"
    assert session.users[0]["staff_actor_name_updated_by_user_id"] == session.user_id
    assert session.commits == 1


def test_update_staff_actor_name_writes_safe_audit_log() -> None:
    session = _FakeAuthSession()
    session.users[0]["current_staff_actor_name"] = "Dr Previous Name"
    identity = AuthIdentity(
        role="admin",
        subject_id=session.user_id,
        programme_scope=["DR"],
        admin_level="programme",
        current_staff_actor_name="Dr Previous Name",
    )

    response = _client(identity, session).post(
        "/api/v1/auth/staff-actor-name",
        json={"full_name": "Dr Priya Tan"},
    )

    assert response.status_code == 200
    assert len(session.audit_logs) == 1
    audit_log = session.audit_logs[0]
    assert audit_log["actor_user_id"] == session.user_id
    assert audit_log["actor_role"] == "admin"
    assert audit_log["actor_admin_level"] is None
    assert audit_log["action"] == "auth.staff_actor_name.update"
    assert audit_log["entity_type"] == "user"
    assert audit_log["entity_id"] == session.user_id
    assert json.loads(audit_log["before_json"]) == {
        "current_staff_actor_name": "Dr Previous Name"
    }
    assert json.loads(audit_log["after_json"]) == {
        "current_staff_actor_name": "Dr Priya Tan"
    }
    assert json.loads(audit_log["metadata_json"]) == {
        "source": "self_declared_saved_staff_actor_name",
        "authorization_metadata": False,
        "programme_scope": ["DR"],
    }
    serialized_audit = json.dumps(audit_log, default=str).lower()
    for forbidden in ("password", "token", "secret", "authorization_header"):
        assert forbidden not in serialized_audit


def test_update_staff_actor_name_rejects_empty_and_resident() -> None:
    session = _FakeAuthSession()
    staff_identity = AuthIdentity(
        role="admin",
        subject_id=session.user_id,
        programme_scope=["DR"],
        admin_level="programme",
    )
    empty_response = _client(staff_identity, session).post(
        "/api/v1/auth/staff-actor-name",
        json={"full_name": "  "},
    )

    resident_identity = AuthIdentity(
        role="resident",
        subject_id=session.resident_id,
        programme_code="DR",
        mcr="M12345A",
    )
    resident_response = _client(resident_identity, session).post(
        "/api/v1/auth/staff-actor-name",
        json={"full_name": "Dr Priya Tan"},
    )

    external_resident_identity = AuthIdentity(
        role="external_resident",
        subject_id=str(uuid4()),
        mcr="X12345A",
    )
    external_resident_response = _client(external_resident_identity, session).post(
        "/api/v1/auth/staff-actor-name",
        json={"full_name": "Dr Priya Tan"},
    )

    assert empty_response.status_code == 422
    assert resident_response.status_code == 403
    assert external_resident_response.status_code == 403
    assert session.users[0]["current_staff_actor_name"] is None
    assert session.audit_logs == []


def test_staff_actor_dependency_uses_saved_identity_name() -> None:
    from app.dependencies.staff_actor import require_staff_actor

    actor_user_id = uuid4()
    identity = AuthIdentity(
        role="secretary",
        subject_id=str(actor_user_id),
        posting_code="TTSHCardio",
        current_staff_actor_name="Dr Lee Jia Min",
    )
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):  # noqa: ANN001
        request.state.identity = identity
        return await call_next(request)

    @app.get("/actor")
    async def actor_route(actor=Depends(require_staff_actor)):  # noqa: ANN001
        return {"actor_name": actor.actor_name}

    response = TestClient(app).get("/actor")

    assert response.status_code == 200
    assert response.json()["actor_name"] == "Dr Lee Jia Min"
