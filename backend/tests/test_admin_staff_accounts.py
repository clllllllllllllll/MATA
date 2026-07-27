from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.services import staff_accounts
from app.services.supabase_admin import SupabaseAdminError


class _FakeResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar: object | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected one row, got {len(self._rows)}")
        return self._rows[0]

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError(f"Expected at most one row, got {len(self._rows)}")
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _FakeStaffAccountSession:
    def __init__(self) -> None:
        self.master_id = str(uuid4())
        self.pc_id = str(uuid4())
        self.secretary_id = str(uuid4())
        self.users = [
            self._user(
                user_id=self.master_id,
                email="master@nhg.com.sg",
                name="Master Admin",
                role="admin",
                admin_level="master",
                programme_scope=None,
                posting_code=None,
                is_active=True,
                current_staff_actor_name="Dr Master",
            ),
            self._user(
                user_id=self.pc_id,
                email="pc@nhg.com.sg",
                name="Programme PC",
                role="admin",
                admin_level="programme",
                programme_scope=["DR"],
                posting_code=None,
                is_active=True,
                current_staff_actor_name="Dr PC",
            ),
            self._user(
                user_id=self.secretary_id,
                email="sec@nhg.com.sg",
                name="Secretary",
                role="secretary",
                admin_level="programme",
                programme_scope=None,
                posting_code="TTSHCardio",
                is_active=True,
                current_staff_actor_name="Dr Sec",
            ),
        ]
        self.audit_logs: list[dict] = []
        self.commits = 0
        self.session_revocations = 0

    @staticmethod
    def _user(
        *,
        user_id: str,
        email: str,
        name: str,
        role: str,
        admin_level: str,
        programme_scope: list[str] | None,
        posting_code: str | None,
        is_active: bool,
        current_staff_actor_name: str | None,
        supabase_user_id: str | None = None,
        password_hash: str = "password",
    ) -> dict:
        return {
            "id": user_id,
            "email": email,
            "supabase_user_id": supabase_user_id,
            "password_hash": password_hash,
            "role": role,
            "name": name,
            "posting_code": posting_code,
            "programme_scope": programme_scope,
            "admin_level": admin_level,
            "is_active": is_active,
            "session_generation": 0,
            "session_issuance_blocked": False,
            "current_staff_actor_name": current_staff_actor_name,
            "staff_actor_name_updated_at": None,
            "staff_actor_name_updated_by_user_id": None,
            "created_at": "2026-07-03T00:00:00+00:00",
            "updated_at": "2026-07-03T00:00:00+00:00",
        }

    async def execute(self, statement, params=None):  # noqa: ANN001, C901, PLR0912
        sql = str(statement)
        payload = dict(params or {})

        if "INSERT INTO audit_logs" in sql:
            self.audit_logs.append(payload)
            return _FakeResult([{"id": payload["id"], **payload}])

        if "SELECT COUNT" in sql and "FROM users" in sql and "admin_level = 'master'" in sql:
            count = sum(
                1
                for row in self.users
                if row["role"] == "admin"
                and row["admin_level"] == "master"
                and row["is_active"]
            )
            return _FakeResult(scalar=count)

        if "SELECT 1" in sql and "FROM users" in sql and "lower(email)" in sql:
            if ":exclude_user_id IS NULL" in sql and payload.get("exclude_user_id") is None:
                raise AssertionError("nullable exclude_user_id SQL path used")
            exclude_id = payload.get("exclude_user_id")
            exists = any(
                row
                for row in self.users
                if row["email"].lower() == payload["email"].lower()
                and (exclude_id is None or row["id"] != str(exclude_id))
            )
            return _FakeResult(scalar=1 if exists else None)

        if "FROM users" in sql and "WHERE id = :user_id" in sql:
            rows = [row for row in self.users if row["id"] == str(payload["user_id"])]
            return _FakeResult(rows)

        if "FROM users" in sql and "ORDER BY" in sql:
            return _FakeResult(sorted(self.users, key=lambda row: row["email"]))

        if "INSERT INTO users" in sql:
            row = self._user(
                user_id=str(uuid4()),
                email=payload["email"],
                name=payload["name"],
                role=payload["role"],
                admin_level=payload["admin_level"],
                programme_scope=payload.get("programme_scope"),
                posting_code=payload.get("posting_code"),
                is_active=payload.get("is_active", True),
                current_staff_actor_name=None,
                supabase_user_id=str(payload["supabase_user_id"]) if payload.get("supabase_user_id") else None,
                password_hash=payload["password_hash"],
            )
            self.users.append(row)
            return _FakeResult([row])

        if (
            "UPDATE users" in sql
            and "session_generation = session_generation + 1" in sql
            and "password_hash = :password_hash" not in sql
        ):
            for row in self.users:
                if row["id"] == str(payload["subject_id"]):
                    row["session_generation"] += 1
                    if payload.get("block_session_issuance"):
                        row["session_issuance_blocked"] = True
                    return _FakeResult(scalar=row["session_generation"])
            return _FakeResult(scalar=None)

        if "UPDATE users" in sql and "staff_actor_name_updated_at = NULL" in sql:
            rows: list[dict] = []
            for row in self.users:
                if (
                    row["id"] == str(payload["user_id"])
                    and row["session_issuance_blocked"]
                    and row["session_generation"] == payload["reset_generation"]
                ):
                    row["password_hash"] = payload["password_hash"]
                    row["session_generation"] += 1
                    row["session_issuance_blocked"] = False
                    row["current_staff_actor_name"] = None
                    row["staff_actor_name_updated_at"] = None
                    row["staff_actor_name_updated_by_user_id"] = None
                    rows.append(row)
            return _FakeResult(rows)

        if "UPDATE users" in sql:
            rows = []
            for row in self.users:
                if row["id"] == str(payload["user_id"]):
                    row["name"] = payload["name"]
                    row["role"] = payload["role"]
                    row["admin_level"] = payload["admin_level"]
                    row["programme_scope"] = payload.get("programme_scope")
                    row["posting_code"] = payload.get("posting_code")
                    row["is_active"] = payload["is_active"]
                    rows.append(row)
            return _FakeResult(rows)

        if "UPDATE app_sessions" in sql:
            self.session_revocations += 1
            return _FakeResult(rowcount=2)

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _FakeSupabaseAdmin:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated_passwords: list[dict] = []
        self.next_user_id = uuid4()

    async def create_user(self, *, email: str, password: str) -> UUID:
        self.created.append({"email": email, "password": password})
        return self.next_user_id

    async def update_user_password(self, *, supabase_user_id: UUID, password: str) -> None:
        self.updated_passwords.append(
            {"supabase_user_id": str(supabase_user_id), "password": password}
        )


def _client(
    *,
    identity: AuthIdentity,
    session: _FakeStaffAccountSession,
    settings: Settings | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):  # noqa: ANN001
        request.state.identity = identity
        return await call_next(request)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_exclusive_db_session] = _db_override
    if settings is not None:
        app.dependency_overrides[admin.get_settings] = lambda: settings
    app.include_router(admin.router, prefix="/api/v1")
    return TestClient(app)


def _master_identity(session: _FakeStaffAccountSession) -> AuthIdentity:
    return AuthIdentity(
        role="admin",
        subject_id=session.master_id,
        programme_scope=[],
        admin_level="master",
        current_staff_actor_name="Dr Master",
    )


def test_master_admin_lists_staff_accounts() -> None:
    session = _FakeStaffAccountSession()

    response = _client(identity=_master_identity(session), session=session).get(
        "/api/v1/admin/staff-accounts",
    )

    assert response.status_code == 200
    payload = response.json()
    assert [row["email"] for row in payload["items"]] == [
        "master@nhg.com.sg",
        "pc@nhg.com.sg",
        "sec@nhg.com.sg",
    ]
    assert payload["items"][0]["account_type"] == "master_admin"
    assert payload["items"][1]["account_type"] == "programme_pc"
    assert payload["items"][2]["account_type"] == "secretary"


def test_create_programme_pc_uses_mocked_supabase_admin_and_local_user_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeStaffAccountSession()
    fake_supabase = _FakeSupabaseAdmin()

    monkeypatch.setattr(
        "app.services.staff_accounts.SupabaseAdminClient",
        lambda settings: fake_supabase,
    )
    settings = Settings(
        auth_mode="supabase",
        supabase_url="https://mata-test.supabase.co",
        supabase_service_role_key="server-only-placeholder",
    )
    response = _client(
        identity=_master_identity(session),
        session=session,
        settings=settings,
    ).post(
        "/api/v1/admin/staff-accounts",
        json={
            "account_display_name": "Programme PC - DR",
            "email": "new-pc@nhg.com.sg",
            "account_type": "programme_pc",
            "password": "temporary-password-123",
            "is_active": True,
            "programme_scope": ["DR", "GRM"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "new-pc@nhg.com.sg"
    assert payload["account_type"] == "programme_pc"
    assert payload["programme_scope"] == ["DR", "GRM"]
    assert payload["posting_code"] is None
    assert payload["current_staff_actor_name"] is None
    assert "password" not in payload
    assert session.users[-1]["supabase_user_id"] == str(fake_supabase.next_user_id)
    stored_hash = session.users[-1]["password_hash"]
    assert stored_hash
    assert "temporary-password-123" not in stored_hash
    assert stored_hash != "plain:temporary-password-123"
    assert stored_hash != "plain:None"
    assert fake_supabase.created == [
        {"email": "new-pc@nhg.com.sg", "password": "temporary-password-123"}
    ]
    serialized_audit = json.dumps(session.audit_logs, default=str).lower()
    assert "temporary-password-123" not in serialized_audit
    assert "password" not in serialized_audit


def test_create_staff_account_rejects_blank_required_fields_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeStaffAccountSession()
    fake_supabase = _FakeSupabaseAdmin()
    monkeypatch.setattr(
        "app.services.staff_accounts.SupabaseAdminClient",
        lambda settings: fake_supabase,
    )
    settings = Settings(
        auth_mode="supabase",
        supabase_url="https://mata-test.supabase.co",
        supabase_service_role_key="server-only-placeholder",
    )
    client = _client(
        identity=_master_identity(session),
        session=session,
        settings=settings,
    )
    initial_user_count = len(session.users)

    invalid_payloads = [
        {
            "account_display_name": "Programme PC",
            "email": "   ",
            "account_type": "programme_pc",
            "password": "temporary-password-123",
            "programme_scope": ["DR"],
        },
        {
            "account_display_name": "Programme PC",
            "email": "blank-password@nhg.com.sg",
            "account_type": "programme_pc",
            "password": "        ",
            "programme_scope": ["DR"],
        },
        {
            "account_display_name": "Programme PC",
            "email": "   ",
            "account_type": "programme_pc",
            "password": "        ",
            "programme_scope": ["DR"],
        },
    ]

    for payload in invalid_payloads:
        response = client.post("/api/v1/admin/staff-accounts", json=payload)

        assert response.status_code == 422
        assert len(session.users) == initial_user_count
        assert fake_supabase.created == []
        assert session.audit_logs == []


def test_create_staff_account_in_stub_mode_keeps_local_password_hash() -> None:
    session = _FakeStaffAccountSession()

    response = _client(identity=_master_identity(session), session=session).post(
        "/api/v1/admin/staff-accounts",
        json={
            "account_display_name": "Programme PC - DR",
            "email": "stub-pc@nhg.com.sg",
            "account_type": "programme_pc",
            "password": "temporary-password-123",
            "is_active": True,
            "programme_scope": ["DR"],
        },
    )

    assert response.status_code == 200
    assert session.users[-1]["password_hash"] == "plain:temporary-password-123"


def test_create_staff_account_validates_scope_shape() -> None:
    session = _FakeStaffAccountSession()
    client = _client(identity=_master_identity(session), session=session)

    pc_response = client.post(
        "/api/v1/admin/staff-accounts",
        json={
            "account_display_name": "Programme PC",
            "email": "empty-scope@nhg.com.sg",
            "account_type": "programme_pc",
            "password": "temporary-password-123",
            "programme_scope": [],
        },
    )
    secretary_response = client.post(
        "/api/v1/admin/staff-accounts",
        json={
            "account_display_name": "Secretary",
            "email": "no-site@nhg.com.sg",
            "account_type": "secretary",
            "password": "temporary-password-123",
        },
    )

    assert pc_response.status_code == 422
    assert secretary_response.status_code == 422


@pytest.mark.anyio
async def test_email_exists_excludes_current_user_when_exclude_user_id_is_supplied() -> None:
    session = _FakeStaffAccountSession()

    same_user_exists = await staff_accounts._email_exists(
        session,
        email="pc@nhg.com.sg",
        exclude_user_id=UUID(session.pc_id),
    )
    other_user_exists = await staff_accounts._email_exists(
        session,
        email="pc@nhg.com.sg",
        exclude_user_id=UUID(session.master_id),
    )

    assert same_user_exists is False
    assert other_user_exists is True


def test_non_master_staff_cannot_manage_staff_accounts() -> None:
    session = _FakeStaffAccountSession()
    pc_identity = AuthIdentity(
        role="admin",
        subject_id=session.pc_id,
        programme_scope=["DR"],
        admin_level="programme",
    )
    secretary_identity = AuthIdentity(
        role="secretary",
        subject_id=session.secretary_id,
        posting_code="TTSHCardio",
    )

    pc_response = _client(identity=pc_identity, session=session).get(
        "/api/v1/admin/staff-accounts",
    )
    secretary_response = _client(identity=secretary_identity, session=session).get(
        "/api/v1/admin/staff-accounts",
    )

    assert pc_response.status_code == 403
    assert secretary_response.status_code == 403


def test_cannot_deactivate_or_demote_last_active_master_admin() -> None:
    session = _FakeStaffAccountSession()
    client = _client(identity=_master_identity(session), session=session)

    deactivate_response = client.patch(
        f"/api/v1/admin/staff-accounts/{session.master_id}",
        json={
            "account_display_name": "Master Admin",
            "account_type": "master_admin",
            "is_active": False,
        },
    )
    demote_response = client.patch(
        f"/api/v1/admin/staff-accounts/{session.master_id}",
        json={
            "account_display_name": "Master Admin",
            "account_type": "programme_pc",
            "is_active": True,
            "programme_scope": ["DR"],
        },
    )

    assert deactivate_response.status_code == 422
    assert demote_response.status_code == 422
    assert session.users[0]["admin_level"] == "master"
    assert session.users[0]["is_active"] is True


def test_reset_password_updates_supabase_and_clears_saved_actor_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeStaffAccountSession()
    supabase_user_id = uuid4()
    session.users[1]["supabase_user_id"] = str(supabase_user_id)
    fake_supabase = _FakeSupabaseAdmin()
    monkeypatch.setattr(
        "app.services.staff_accounts.SupabaseAdminClient",
        lambda settings: fake_supabase,
    )
    settings = Settings(
        auth_mode="supabase",
        supabase_url="https://mata-test.supabase.co",
        supabase_service_role_key="server-only-placeholder",
    )

    response = _client(
        identity=_master_identity(session),
        session=session,
        settings=settings,
    ).post(
        f"/api/v1/admin/staff-accounts/{session.pc_id}/reset-password",
        json={"password": "new-working-password-123"},
    )

    assert response.status_code == 200
    assert response.json()["current_staff_actor_name"] is None
    assert session.users[1]["current_staff_actor_name"] is None
    stored_hash = session.users[1]["password_hash"]
    assert stored_hash
    assert "new-working-password-123" not in stored_hash
    assert stored_hash != "plain:new-working-password-123"
    assert stored_hash != "plain:None"
    assert fake_supabase.updated_passwords == [
        {
            "supabase_user_id": str(supabase_user_id),
            "password": "new-working-password-123",
        }
    ]
    assert session.session_revocations == 1
    assert session.users[1]["session_generation"] == 2
    assert session.users[1]["session_issuance_blocked"] is False
    assert session.commits == 2
    serialized_audit = json.dumps(session.audit_logs, default=str).lower()
    assert "new-working-password-123" not in serialized_audit
    audit_log = session.audit_logs[0]
    for field in ("before_json", "after_json", "metadata_json"):
        assert "password" not in str(audit_log[field]).lower()


def test_master_admin_cannot_reset_own_password() -> None:
    session = _FakeStaffAccountSession()
    original_hash = session.users[0]["password_hash"]
    original_actor_name = session.users[0]["current_staff_actor_name"]

    response = _client(identity=_master_identity(session), session=session).post(
        f"/api/v1/admin/staff-accounts/{session.master_id}/reset-password",
        json={"password": "self-reset-password-must-not-be-used"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Master Admins cannot reset their own password through staff "
        "account management"
    )
    assert session.users[0]["password_hash"] == original_hash
    assert session.users[0]["current_staff_actor_name"] == original_actor_name
    assert session.users[0]["session_generation"] == 0
    assert session.users[0]["session_issuance_blocked"] is False
    assert session.session_revocations == 0
    assert session.commits == 0
    assert session.audit_logs == []


def test_reset_password_rejects_blank_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeStaffAccountSession()
    supabase_user_id = uuid4()
    session.users[1]["supabase_user_id"] = str(supabase_user_id)
    original_hash = session.users[1]["password_hash"]
    original_actor_name = session.users[1]["current_staff_actor_name"]
    fake_supabase = _FakeSupabaseAdmin()
    monkeypatch.setattr(
        "app.services.staff_accounts.SupabaseAdminClient",
        lambda settings: fake_supabase,
    )
    settings = Settings(
        auth_mode="supabase",
        supabase_url="https://mata-test.supabase.co",
        supabase_service_role_key="server-only-placeholder",
    )

    response = _client(
        identity=_master_identity(session),
        session=session,
        settings=settings,
    ).post(
        f"/api/v1/admin/staff-accounts/{session.pc_id}/reset-password",
        json={"password": "        "},
    )

    assert response.status_code == 422
    assert session.users[1]["password_hash"] == original_hash
    assert session.users[1]["current_staff_actor_name"] == original_actor_name
    assert fake_supabase.updated_passwords == []
    assert session.audit_logs == []


def test_reset_password_in_stub_mode_keeps_local_password_hash() -> None:
    session = _FakeStaffAccountSession()

    response = _client(identity=_master_identity(session), session=session).post(
        f"/api/v1/admin/staff-accounts/{session.pc_id}/reset-password",
        json={"password": "new-working-password-123"},
    )

    assert response.status_code == 200
    assert session.users[1]["password_hash"] == "plain:new-working-password-123"
    assert session.users[1]["current_staff_actor_name"] is None
    assert session.session_revocations == 1
    assert session.users[1]["session_generation"] == 2
    assert session.users[1]["session_issuance_blocked"] is False
    assert session.commits == 2


def test_failed_supabase_password_reset_leaves_session_issuance_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeStaffAccountSession()
    supabase_user_id = uuid4()
    session.users[1]["supabase_user_id"] = str(supabase_user_id)
    original_hash = session.users[1]["password_hash"]
    original_actor_name = session.users[1]["current_staff_actor_name"]

    class _FailingSupabaseAdmin:
        async def update_user_password(self, **_kwargs) -> None:
            raise SupabaseAdminError(
                status_code=502,
                detail="Supabase Admin request failed",
                error_code="INTERNAL_ERROR",
            )

    monkeypatch.setattr(
        "app.services.staff_accounts.SupabaseAdminClient",
        lambda settings: _FailingSupabaseAdmin(),
    )
    settings = Settings(
        auth_mode="supabase",
        supabase_url="https://mata-test.supabase.co",
        supabase_service_role_key="server-only-placeholder",
    )

    response = _client(
        identity=_master_identity(session),
        session=session,
        settings=settings,
    ).post(
        f"/api/v1/admin/staff-accounts/{session.pc_id}/reset-password",
        json={"password": "replacement-password-never-logged"},
    )

    assert response.status_code == 502
    assert "replacement-password-never-logged" not in response.text
    assert session.users[1]["password_hash"] == original_hash
    assert session.users[1]["current_staff_actor_name"] == original_actor_name
    assert session.users[1]["session_generation"] == 1
    assert session.users[1]["session_issuance_blocked"] is True
    assert session.session_revocations == 1
    assert session.commits == 1
    assert session.audit_logs == []


def test_staff_scope_or_active_state_change_revokes_existing_sessions() -> None:
    session = _FakeStaffAccountSession()

    response = _client(identity=_master_identity(session), session=session).patch(
        f"/api/v1/admin/staff-accounts/{session.secretary_id}",
        json={
            "account_display_name": "Secretary",
            "account_type": "secretary",
            "is_active": False,
            "posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert session.session_revocations == 1
    assert session.users[2]["session_generation"] == 1
    audit_metadata = json.loads(session.audit_logs[-1]["metadata_json"])
    assert audit_metadata["authorization_changed"] is True
    assert audit_metadata["revoked_session_count"] == 2
