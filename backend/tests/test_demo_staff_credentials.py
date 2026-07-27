from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import auth as auth_service
from scripts import reset_demo_staff_logins


def _account(email: str) -> reset_demo_staff_logins.DemoStaffAccount:
    return next(
        account
        for account in reset_demo_staff_logins.DEMO_STAFF_ACCOUNTS
        if account.email == email
    )


def test_demo_staff_accounts_match_5bc_smoke_contract() -> None:
    master = _account("demo.master@example.com")
    pc = _account("demo.admin@example.com")
    secretary = _account("demo.secretary@example.com")

    assert master.role == "admin"
    assert master.admin_level == "master"
    assert master.programme_scope == []
    assert master.posting_code is None

    assert pc.role == "admin"
    assert pc.admin_level == "programme"
    assert pc.programme_scope == ["DR", "GERI"]
    assert pc.posting_code is None

    assert secretary.role == "secretary"
    assert secretary.admin_level == "programme"
    assert secretary.programme_scope is None
    assert secretary.posting_code == "TTSHGerMed"


def test_demo_password_hash_matches_auth_login_verifier() -> None:
    password_hash = auth_service.local_demo_password_hash(
        reset_demo_staff_logins.DEMO_STAFF_PASSWORD,
    )

    assert auth_service._password_matches(  # noqa: SLF001
        password_hash,
        reset_demo_staff_logins.DEMO_STAFF_PASSWORD,
    )
    assert not auth_service._password_matches(password_hash, "wrong")  # noqa: SLF001


def test_demo_staff_reset_refuses_non_local_modes() -> None:
    allowed = Settings(environment="development", auth_mode="stub")

    reset_demo_staff_logins.ensure_local_demo_reset_allowed(allowed)

    with pytest.raises(RuntimeError, match="local development/test"):
        reset_demo_staff_logins.ensure_local_demo_reset_allowed(
            SimpleNamespace(
                environment="production",
                auth_mode="stub",
                sync_database_url="postgresql://postgres:postgres@localhost:5432/mata_db",
            ),
        )

    with pytest.raises(RuntimeError, match="AUTH_MODE=supabase"):
        reset_demo_staff_logins.ensure_local_demo_reset_allowed(
            Settings(environment="development", auth_mode="supabase"),
        )

    with pytest.raises(RuntimeError, match="local PostgreSQL"):
        reset_demo_staff_logins.ensure_local_demo_reset_allowed(
            Settings(
                environment="development",
                auth_mode="stub",
                database_rls_enabled=False,
                sync_database_url="postgresql://postgres:postgres@prod-db.example.com:5432/mata_db",
                _env_file=None,
            ),
        )
