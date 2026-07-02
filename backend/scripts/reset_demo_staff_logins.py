"""
Reset local-only demo staff credentials for 5B-C smoke testing.

Run from the backend directory:
    python scripts/reset_demo_staff_logins.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import String, bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import Connection, Engine, make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings, get_settings
from app.services.auth import local_demo_password_hash


DEMO_STAFF_PASSWORD = "demo123"
DEMO_SECRETARY_POSTING_CODE = "TTSHGerMed"
LOCAL_SYNC_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "host.docker.internal"}


@dataclass(frozen=True)
class DemoStaffAccount:
    email: str
    password: str
    role: str
    name: str
    admin_level: str
    programme_scope: list[str] | None
    posting_code: str | None


DEMO_STAFF_ACCOUNTS = (
    DemoStaffAccount(
        email="demo.master@example.com",
        password=DEMO_STAFF_PASSWORD,
        role="admin",
        name="Demo Master Admin",
        admin_level="master",
        programme_scope=[],
        posting_code=None,
    ),
    DemoStaffAccount(
        email="demo.admin@example.com",
        password=DEMO_STAFF_PASSWORD,
        role="admin",
        name="Demo Programme PC",
        admin_level="programme",
        programme_scope=["DR", "GERI"],
        posting_code=None,
    ),
    DemoStaffAccount(
        email="demo.secretary@example.com",
        password=DEMO_STAFF_PASSWORD,
        role="secretary",
        name="Demo Secretary",
        admin_level="programme",
        programme_scope=None,
        posting_code=DEMO_SECRETARY_POSTING_CODE,
    ),
)


UPSERT_DEMO_STAFF_SQL = text(
    """
    INSERT INTO users (
        email,
        password_hash,
        role,
        name,
        posting_code,
        programme_scope,
        admin_level,
        is_active
    )
    VALUES (
        :email,
        :password_hash,
        :role,
        :name,
        :posting_code,
        :programme_scope,
        :admin_level,
        true
    )
    ON CONFLICT (email)
    DO UPDATE SET
        password_hash = EXCLUDED.password_hash,
        role = EXCLUDED.role,
        name = EXCLUDED.name,
        posting_code = EXCLUDED.posting_code,
        programme_scope = EXCLUDED.programme_scope,
        admin_level = EXCLUDED.admin_level,
        is_active = true,
        updated_at = now()
    RETURNING
        id,
        email,
        role,
        admin_level,
        programme_scope,
        posting_code,
        is_active
    """
).bindparams(bindparam("programme_scope", type_=ARRAY(String())))


def ensure_local_demo_reset_allowed(settings: Settings) -> None:
    if settings.environment == "production":
        raise RuntimeError(
            "Refusing to reset demo staff accounts outside local development/test mode.",
        )
    if settings.auth_mode == "supabase":
        raise RuntimeError(
            "Refusing to reset demo staff accounts when AUTH_MODE=supabase.",
        )
    sync_database_host = (make_url(settings.sync_database_url).host or "").lower()
    if sync_database_host not in LOCAL_SYNC_DATABASE_HOSTS:
        raise RuntimeError(
            "Refusing to reset demo staff accounts unless SYNC_DATABASE_URL points "
            f"at local PostgreSQL. Host was: {sync_database_host or '<none>'}.",
        )


def ensure_required_posting_code(conn: Connection) -> None:
    exists = conn.execute(
        text(
            """
            SELECT 1
            FROM posting_codes
            WHERE code = :posting_code
            LIMIT 1
            """,
        ),
        {"posting_code": DEMO_SECRETARY_POSTING_CODE},
    ).scalar_one_or_none()
    if exists is None:
        raise RuntimeError(
            f"Required posting_code {DEMO_SECRETARY_POSTING_CODE} does not exist. "
            "Run migrations/seed posting_codes before resetting demo staff logins.",
        )


def upsert_demo_staff_account(
    conn: Connection,
    account: DemoStaffAccount,
) -> dict[str, Any]:
    row = conn.execute(
        UPSERT_DEMO_STAFF_SQL,
        {
            "email": account.email,
            "password_hash": local_demo_password_hash(account.password),
            "role": account.role,
            "name": account.name,
            "posting_code": account.posting_code,
            "programme_scope": account.programme_scope,
            "admin_level": account.admin_level,
        },
    ).mappings().one()
    return dict(row)


def reset_demo_staff_logins(conn: Connection) -> list[dict[str, Any]]:
    ensure_required_posting_code(conn)
    return [upsert_demo_staff_account(conn, account) for account in DEMO_STAFF_ACCOUNTS]


def main() -> int:
    settings = get_settings()
    ensure_local_demo_reset_allowed(settings)

    engine: Engine = create_engine(settings.sync_database_url)
    try:
        with engine.begin() as conn:
            rows = reset_demo_staff_logins(conn)
    finally:
        engine.dispose()

    print("Reset local demo staff login credentials:")
    for row in rows:
        scope = row["programme_scope"] or []
        posting = row["posting_code"] or "-"
        print(
            f"- {row['email']} role={row['role']} "
            f"admin_level={row['admin_level']} "
            f"programme_scope={scope} posting_code={posting}",
        )
    print(f"Password for all demo staff accounts: {DEMO_STAFF_PASSWORD}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
