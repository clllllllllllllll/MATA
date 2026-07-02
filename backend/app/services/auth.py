from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


def _auth_failure() -> ApiError:
    return ApiError(
        status_code=401,
        detail="Unauthorized",
        error_code=ErrorCode.UNAUTHORIZED.value,
    )


def _stub_login_allowed(*, auth_mode: str) -> bool:
    return auth_mode in {"stub", "demo"}


def _stub_access_token(*, role: str, subject_id: Any) -> str:
    return f"stub.{role}.{subject_id}"


def local_demo_password_hash(supplied_password: str) -> str:
    return f"plain:{supplied_password}"


def _password_matches(stored_hash: str, supplied_password: str) -> bool:
    return (
        stored_hash == supplied_password
        or stored_hash == local_demo_password_hash(supplied_password)
    )


def _resident_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": "resident",
        "name": row["name"],
        "programme_code": row.get("programme_code"),
        "mcr": row["mcr"],
    }


def _external_resident_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": "external_resident",
        "name": row["name"],
        "mcr": row["mcr"],
        "home_cluster": row["home_cluster"],
    }


def _user_identity(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "role": row["role"],
        "name": row["name"],
        "email": row["email"],
    }
    if row["role"] == "admin":
        payload["programme_scope"] = row.get("programme_scope") or []
        payload["admin_level"] = row.get("admin_level") or "programme"
    if row["role"] == "secretary":
        payload["posting_code"] = row.get("posting_code")
    return payload


def _normalise_mcr(raw_mcr: str | None) -> str | None:
    if raw_mcr is None:
        return None
    cleaned = raw_mcr.strip().upper()
    return cleaned or None


async def login(
    db: AsyncSession,
    *,
    role: str,
    email: str | None,
    password: str | None,
    mcr: str | None,
    auth_mode: str = "stub",
) -> dict[str, Any]:
    if not _stub_login_allowed(auth_mode=auth_mode):
        raise _auth_failure()

    if role in {"resident", "external_resident"}:
        normalised_mcr = _normalise_mcr(mcr)
        if not normalised_mcr:
            raise _auth_failure()
        table_name = "residents" if role == "resident" else "external_residents"
        result = await db.execute(
            text(
                """
                SELECT *
                FROM """
                + table_name
                + """
                WHERE mcr = :mcr
                """
            ),
            {"mcr": normalised_mcr},
        )
        identity_row = result.mappings().one_or_none()
        if identity_row is None or identity_row.get("status") == "inactive":
            raise _auth_failure()
        user = (
            _resident_user(dict(identity_row))
            if role == "resident"
            else _external_resident_user(dict(identity_row))
        )
        return {
            "access_token": _stub_access_token(role=role, subject_id=user["id"]),
            "token_type": "bearer",
            "user": user,
        }

    if not email or not password:
        raise _auth_failure()

    result = await db.execute(
        text(
            """
            SELECT
                id,
                email,
                password_hash,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active
            FROM users
            WHERE lower(email) = lower(:email)
              AND (:role = 'staff' OR role = :role)
              AND is_active = true
            """
        ),
        {"email": email, "role": role},
    )
    user_row = result.mappings().one_or_none()
    if user_row is None or not _password_matches(user_row["password_hash"], password):
        raise _auth_failure()

    user = _user_identity(dict(user_row))
    return {
        "access_token": _stub_access_token(role=user["role"], subject_id=user["id"]),
        "token_type": "bearer",
        "user": user,
    }


async def get_current_identity(
    db: AsyncSession,
    *,
    role: str,
    subject_id: UUID,
) -> dict[str, Any]:
    if role == "resident":
        result = await db.execute(
            text(
                """
                SELECT id, name, mcr, programme_code, status
                FROM residents
                WHERE id = :resident_id
                """
            ),
            {"resident_id": str(subject_id)},
        )
        resident = result.mappings().one_or_none()
        if resident is None or resident.get("status") == "inactive":
            raise _auth_failure()
        return _resident_user(dict(resident))

    if role == "external_resident":
        result = await db.execute(
            text(
                """
                SELECT id, name, mcr, home_cluster, status
                FROM external_residents
                WHERE id = :external_resident_id
                """
            ),
            {"external_resident_id": str(subject_id)},
        )
        resident = result.mappings().one_or_none()
        if resident is None or resident.get("status") == "inactive":
            raise _auth_failure()
        return _external_resident_user(dict(resident))

    result = await db.execute(
        text(
            """
            SELECT
                id,
                email,
                password_hash,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active
            FROM users
            WHERE id = :user_id
              AND is_active = true
            """
        ),
        {"user_id": str(subject_id)},
    )
    user = result.mappings().one_or_none()
    if user is None or user["role"] != role:
        raise _auth_failure()
    return _user_identity(dict(user))
