from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.services.audit import write_audit_log
from app.services.mata_resident_token import (
    MataResidentTokenError,
    sign_mata_external_resident_token,
    sign_mata_resident_token,
)


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


def _auth_config_failure() -> ApiError:
    return ApiError(
        status_code=500,
        detail="Resident session configuration is missing",
        error_code=ErrorCode.INTERNAL_ERROR.value,
    )


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


def _staff_actor_name_required(row: dict[str, Any]) -> bool:
    value = row.get("current_staff_actor_name")
    return not (isinstance(value, str) and value.strip())


def _normalise_programme_scope(raw_scope: Any) -> list[str]:
    if not raw_scope:
        return []
    if not isinstance(raw_scope, list):
        return []
    return [
        value.strip()
        for value in raw_scope
        if isinstance(value, str) and value.strip()
    ]


def _staff_actor_context_from_user_row(
    row: dict[str, Any],
    *,
    actor_name_fallback: str,
) -> StaffActorContext:
    role = row["role"]
    programme_scope = _normalise_programme_scope(row.get("programme_scope"))
    posting_code = row.get("posting_code") if role == "secretary" else None
    admin_level = row.get("admin_level") if role == "admin" else None
    actor_admin_level = "master" if admin_level == "master" else None
    current_actor_name = row.get("current_staff_actor_name")

    raw_scope_metadata: dict[str, Any] = {}
    if programme_scope:
        raw_scope_metadata["programme_scope"] = programme_scope
    if posting_code:
        raw_scope_metadata["site"] = posting_code
    if actor_admin_level:
        raw_scope_metadata["admin_level"] = actor_admin_level

    return StaffActorContext(
        actor_user_id=UUID(str(row["id"])),
        actor_role=role,
        actor_name=(
            current_actor_name.strip()
            if isinstance(current_actor_name, str) and current_actor_name.strip()
            else actor_name_fallback
        ),
        actor_site=posting_code,
        actor_programme=",".join(programme_scope) if programme_scope else None,
        actor_admin_level=actor_admin_level,
        raw_scope_metadata=raw_scope_metadata,
    )


def _user_identity(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "role": row["role"],
        "name": row["name"],
        "email": row["email"],
    }
    if row["role"] in {"admin", "secretary"}:
        current_actor_name = row.get("current_staff_actor_name")
        payload["current_staff_actor_name"] = (
            current_actor_name if isinstance(current_actor_name, str) else None
        )
        payload["staff_actor_name_required"] = _staff_actor_name_required(row)
        payload["staff_actor_name_updated_at"] = row.get("staff_actor_name_updated_at")
        payload["staff_actor_name_updated_by_user_id"] = row.get(
            "staff_actor_name_updated_by_user_id",
        )
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


async def _lookup_resident_login_rows(
    db: AsyncSession,
    normalised_mcr: str,
) -> tuple[Any | None, Any | None]:
    resident_result = await db.execute(
        text(
            """
            SELECT *
            FROM residents
            WHERE mcr = :mcr
            """
        ),
        {"mcr": normalised_mcr},
    )
    external_result = await db.execute(
        text(
            """
            SELECT *
            FROM external_residents
            WHERE mcr = :mcr
            """
        ),
        {"mcr": normalised_mcr},
    )
    return (
        resident_result.mappings().one_or_none(),
        external_result.mappings().one_or_none(),
    )


async def login(
    db: AsyncSession,
    *,
    role: str,
    email: str | None,
    password: str | None,
    mcr: str | None,
    auth_mode: str = "stub",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if role in {"resident", "external_resident"}:
        if not _stub_login_allowed(auth_mode=auth_mode) and not (
            auth_mode == "supabase" and role in {"resident", "external_resident"}
        ):
            raise _auth_failure()

        normalised_mcr = _normalise_mcr(mcr)
        if not normalised_mcr:
            raise _auth_failure()
        resident_row, external_resident_row = await _lookup_resident_login_rows(
            db,
            normalised_mcr,
        )
        if resident_row is not None and external_resident_row is not None:
            # Defensive guard for a violated global MCR uniqueness invariant.
            raise _auth_failure()
        identity_row = resident_row if role == "resident" else external_resident_row
        if identity_row is None or identity_row.get("status") == "inactive":
            raise _auth_failure()
        user = (
            _resident_user(dict(identity_row))
            if role == "resident"
            else _external_resident_user(dict(identity_row))
        )
        if auth_mode == "supabase":
            try:
                signer = (
                    sign_mata_resident_token
                    if role == "resident"
                    else sign_mata_external_resident_token
                )
                access_token = signer(
                    dict(identity_row),
                    settings=settings or Settings(auth_mode=auth_mode),
                )
            except MataResidentTokenError as exc:
                raise _auth_config_failure() from exc
        else:
            access_token = _stub_access_token(role=role, subject_id=user["id"])
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user,
        }

    if not _stub_login_allowed(auth_mode=auth_mode):
        raise _auth_failure()

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
                is_active,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id
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
                is_active,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id
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


async def update_staff_actor_name(
    db: AsyncSession,
    *,
    user_id: UUID,
    role: str,
    full_name: str,
) -> dict[str, Any]:
    if role not in {"admin", "secretary"}:
        raise ApiError(
            status_code=403,
            detail="Forbidden - staff role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )

    actor_name = full_name.strip()
    if not actor_name:
        raise ApiError(
            status_code=422,
            detail="full_name is required",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    before_result = await db.execute(
        text(
            """
            SELECT
                id,
                role,
                posting_code,
                programme_scope,
                admin_level,
                current_staff_actor_name
            FROM users
            WHERE id = :user_id
              AND role = :role
              AND is_active = true
            """
        ),
        {"user_id": str(user_id), "role": role},
    )
    before_user = before_result.mappings().one_or_none()
    if before_user is None:
        raise _auth_failure()
    before_row = dict(before_user)

    result = await db.execute(
        text(
            """
            UPDATE users
            SET
                current_staff_actor_name = :actor_name,
                staff_actor_name_updated_at = now(),
                staff_actor_name_updated_by_user_id = :updated_by_user_id,
                updated_at = now()
            WHERE id = :user_id
              AND role = :role
              AND is_active = true
            RETURNING
                id,
                email,
                password_hash,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id
            """
        ),
        {
            "user_id": str(user_id),
            "role": role,
            "actor_name": actor_name,
            "updated_by_user_id": str(user_id),
        },
    )
    user = result.mappings().one_or_none()
    if user is None:
        raise _auth_failure()
    after_row = dict(user)
    previous_actor_name = before_row.get("current_staff_actor_name")
    await write_audit_log(
        db,
        actor=_staff_actor_context_from_user_row(
            before_row,
            actor_name_fallback=actor_name,
        ),
        action="auth.staff_actor_name.update",
        entity_type="user",
        entity_id=user_id,
        before={
            "current_staff_actor_name": (
                previous_actor_name.strip()
                if isinstance(previous_actor_name, str) and previous_actor_name.strip()
                else None
            )
        },
        after={"current_staff_actor_name": actor_name},
        metadata={
            "source": "self_declared_saved_staff_actor_name",
            "authorization_metadata": False,
        },
    )
    await db.commit()
    return _user_identity(after_row)
