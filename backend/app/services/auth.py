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


def _stub_access_token(*, role: str, subject_id: Any) -> str:
    return f"stub.{role}.{subject_id}"


def _password_matches(stored_hash: str, supplied_password: str) -> bool:
    return stored_hash == supplied_password or stored_hash == f"plain:{supplied_password}"


def _resident_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": "resident",
        "name": row["name"],
        "programme_code": row.get("programme_code"),
        "mcr": row["mcr"],
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
    if row["role"] == "secretary":
        payload["posting_code"] = row.get("posting_code")
    return payload


async def login(
    db: AsyncSession,
    *,
    role: str,
    email: str | None,
    password: str | None,
    mcr: str | None,
) -> dict[str, Any]:
    if role == "resident":
        if not mcr:
            raise _auth_failure()
        result = await db.execute(
            text(
                """
                SELECT id, name, mcr, programme_code, status
                FROM residents
                WHERE mcr = :mcr
                """
            ),
            {"mcr": mcr},
        )
        resident = result.mappings().one_or_none()
        if resident is None or resident.get("status") == "inactive":
            raise _auth_failure()
        user = _resident_user(dict(resident))
        return {
            "access_token": _stub_access_token(role="resident", subject_id=user["id"]),
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
                is_active
            FROM users
            WHERE lower(email) = lower(:email)
              AND role = :role
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
        "access_token": _stub_access_token(role=role, subject_id=user["id"]),
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
