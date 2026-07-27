from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.schemas.admin import (
    StaffAccountCreateRequest,
    StaffAccountResetPasswordRequest,
    StaffAccountUpdateRequest,
)
from app.services.audit import write_audit_log
from app.services.app_sessions import revoke_subject_sessions
from app.services.auth import local_demo_password_hash
from app.services.supabase_admin import SupabaseAdminClient

SUPABASE_MANAGED_PASSWORD_HASH_PREFIX = "supabase-managed:"
_STAFF_ACCOUNT_UPDATE_INVARIANT_LOCK = "mata.staff_account_update_invariant"


def _validation_error(detail: str) -> ApiError:
    return ApiError(
        status_code=422,
        detail=detail,
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


def _not_found() -> ApiError:
    return ApiError(
        status_code=404,
        detail="Staff account not found",
        error_code=ErrorCode.NOT_FOUND.value,
    )


def _conflict(detail: str) -> ApiError:
    return ApiError(
        status_code=409,
        detail=detail,
        error_code=ErrorCode.CONFLICT.value,
    )


def _display_name_from_payload(
    account_display_name: str | None,
    name: str | None,
) -> str:
    display_name = (account_display_name or name or "").strip()
    if not display_name:
        raise _validation_error("account_display_name is required")
    return display_name


def _normalise_scope(scope: list[str] | None) -> list[str]:
    if not scope:
        return []
    seen: set[str] = set()
    values: list[str] = []
    for item in scope:
        value = item.strip() if isinstance(item, str) else ""
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _normalise_posting_code(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _account_type_for_row(row: dict[str, Any]) -> str:
    if row["role"] == "secretary":
        return "secretary"
    if row["role"] == "admin" and row.get("admin_level") == "master":
        return "master_admin"
    return "programme_pc"


def _staff_account_response(row: dict[str, Any]) -> dict[str, Any]:
    account_type = _account_type_for_row(row)
    return {
        "id": row["id"],
        "account_display_name": row["name"],
        "email": row["email"],
        "account_type": account_type,
        "role": row["role"],
        "name": row["name"],
        "admin_level": row.get("admin_level") or "programme",
        "programme_scope": row.get("programme_scope") or [],
        "posting_code": row.get("posting_code"),
        "is_active": bool(row["is_active"]),
        "supabase_user_id": row.get("supabase_user_id"),
        "current_staff_actor_name": row.get("current_staff_actor_name"),
        "staff_actor_name_updated_at": row.get("staff_actor_name_updated_at"),
        "staff_actor_name_updated_by_user_id": row.get(
            "staff_actor_name_updated_by_user_id",
        ),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _fields_for_account_type(
    *,
    account_type: str,
    programme_scope: list[str] | None,
    posting_code: str | None,
) -> dict[str, Any]:
    scope = _normalise_scope(programme_scope)
    site = _normalise_posting_code(posting_code)

    if account_type == "master_admin":
        return {
            "role": "admin",
            "admin_level": "master",
            "programme_scope": None,
            "posting_code": None,
        }

    if account_type == "programme_pc":
        if not scope:
            raise _validation_error("programme_scope is required for Programme PC accounts")
        return {
            "role": "admin",
            "admin_level": "programme",
            "programme_scope": scope,
            "posting_code": None,
        }

    if account_type == "secretary":
        if not site:
            raise _validation_error("posting_code is required for Secretary accounts")
        return {
            "role": "secretary",
            "admin_level": "programme",
            "programme_scope": None,
            "posting_code": site,
        }

    raise _validation_error("account_type is invalid")


async def _email_exists(
    db: AsyncSession,
    *,
    email: str,
    exclude_user_id: UUID | None = None,
) -> bool:
    if exclude_user_id is None:
        result = await db.execute(
            text(
                """
                SELECT 1
                FROM users
                WHERE lower(email) = lower(:email)
                LIMIT 1
                """
            ),
            {"email": email},
        )
        return result.scalar_one_or_none() is not None

    result = await db.execute(
        text(
            """
            SELECT 1
            FROM users
            WHERE lower(email) = lower(:email)
              AND id != :exclude_user_id
            LIMIT 1
            """
        ),
        {
            "email": email,
            "exclude_user_id": str(exclude_user_id),
        },
    )
    return result.scalar_one_or_none() is not None


async def _lock_staff_account_update_invariant(db: AsyncSession) -> None:
    """Serialize PATCH invariants that span more than one staff account."""

    await db.execute(
        text(
            """
            SELECT pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtext(
                    CAST(pg_catalog.current_database() AS text)
                ),
                pg_catalog.hashtext(:lock_name)
            )
            """
        ),
        {"lock_name": _STAFF_ACCOUNT_UPDATE_INVARIANT_LOCK},
    )


async def _get_staff_account_row(
    db: AsyncSession,
    *,
    user_id: UUID,
    for_update: bool = False,
) -> dict[str, Any]:
    statement = """
        SELECT
            id,
            email,
            supabase_user_id,
            role,
            name,
            posting_code,
            programme_scope,
            admin_level,
            is_active,
            session_generation,
            session_issuance_blocked,
            current_staff_actor_name,
            staff_actor_name_updated_at,
            staff_actor_name_updated_by_user_id,
            created_at,
            updated_at
        FROM users
        WHERE id = :user_id
          AND role IN ('admin', 'secretary')
    """
    if for_update:
        statement += "\nFOR UPDATE"
    result = await db.execute(
        text(statement),
        {"user_id": str(user_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise _not_found()
    return dict(row)


async def _active_master_count(db: AsyncSession) -> int:
    result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role = 'admin'
              AND admin_level = 'master'
              AND is_active = true
            """
        ),
    )
    return int(result.scalar_one() or 0)


async def _ensure_not_last_active_master_change(
    db: AsyncSession,
    *,
    before: dict[str, Any],
    next_role: str,
    next_admin_level: str,
    next_is_active: bool,
) -> None:
    was_active_master = (
        before["role"] == "admin"
        and before.get("admin_level") == "master"
        and bool(before["is_active"])
    )
    remains_active_master = (
        next_role == "admin"
        and next_admin_level == "master"
        and next_is_active
    )
    if not was_active_master or remains_active_master:
        return
    if await _active_master_count(db) <= 1:
        raise _validation_error("Cannot deactivate or demote the last active Master Admin")


def _safe_audit_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = _staff_account_response(row)
    snapshot.pop("supabase_user_id", None)
    return snapshot


def _password_hash_for_auth_mode(
    *,
    settings: Settings,
    supplied_password: str,
) -> str:
    if settings.auth_mode == "supabase":
        return f"{SUPABASE_MANAGED_PASSWORD_HASH_PREFIX}{uuid4()}"
    return local_demo_password_hash(supplied_password)


async def list_staff_accounts(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    result = await db.execute(
        text(
            """
            SELECT
                id,
                email,
                supabase_user_id,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id,
                created_at,
                updated_at
            FROM users
            WHERE role IN ('admin', 'secretary')
            ORDER BY lower(email)
            """
        ),
    )
    return {"items": [_staff_account_response(dict(row)) for row in result.mappings().all()]}


async def create_staff_account(
    db: AsyncSession,
    *,
    payload: StaffAccountCreateRequest,
    actor: StaffActorContext,
    settings: Settings,
) -> dict[str, Any]:
    display_name = _display_name_from_payload(payload.account_display_name, payload.name)
    email = payload.email.strip()
    if await _email_exists(db, email=email):
        raise _conflict("A staff account with this email already exists")

    account_fields = _fields_for_account_type(
        account_type=payload.account_type,
        programme_scope=payload.programme_scope,
        posting_code=payload.posting_code,
    )

    supabase_user_id: UUID | None = None
    if settings.auth_mode == "supabase":
        supabase_user_id = await SupabaseAdminClient(settings).create_user(
            email=email,
            password=payload.password,
        )

    result = await db.execute(
        text(
            """
            INSERT INTO users (
                email,
                supabase_user_id,
                password_hash,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                current_staff_actor_name
            )
            VALUES (
                :email,
                :supabase_user_id,
                :password_hash,
                :role,
                :name,
                :posting_code,
                :programme_scope,
                :admin_level,
                :is_active,
                NULL
            )
            RETURNING
                id,
                email,
                supabase_user_id,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id,
                created_at,
                updated_at
            """
        ),
        {
            "email": email,
            "supabase_user_id": str(supabase_user_id) if supabase_user_id else None,
            "password_hash": _password_hash_for_auth_mode(
                settings=settings,
                supplied_password=payload.password,
            ),
            "name": display_name,
            "is_active": payload.is_active,
            **account_fields,
        },
    )
    row = dict(result.mappings().one())
    response = _staff_account_response(row)
    await write_audit_log(
        db,
        actor=actor,
        action="admin.staff_account.create",
        entity_type="staff_account",
        entity_id=row["id"],
        after=_safe_audit_snapshot(row),
        metadata={"account_type": response["account_type"]},
    )
    await db.commit()
    return response


async def update_staff_account(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: StaffAccountUpdateRequest,
    actor: StaffActorContext,
) -> dict[str, Any]:
    await _lock_staff_account_update_invariant(db)
    before = await _get_staff_account_row(
        db,
        user_id=user_id,
        for_update=True,
    )

    if payload.email and payload.email.lower() != before["email"].lower():
        raise _validation_error("Email changes are not supported for staff accounts")

    account_type = payload.account_type or _account_type_for_row(before)
    display_name = _display_name_from_payload(
        payload.account_display_name,
        payload.name,
    ) if (payload.account_display_name or payload.name) else before["name"]
    next_is_active = before["is_active"] if payload.is_active is None else payload.is_active
    account_fields = _fields_for_account_type(
        account_type=account_type,
        programme_scope=(
            payload.programme_scope
            if payload.programme_scope is not None
            else before.get("programme_scope")
        ),
        posting_code=(
            payload.posting_code
            if payload.posting_code is not None
            else before.get("posting_code")
        ),
    )
    await _ensure_not_last_active_master_change(
        db,
        before=before,
        next_role=account_fields["role"],
        next_admin_level=account_fields["admin_level"],
        next_is_active=next_is_active,
    )
    authorization_after = {
        **account_fields,
        "is_active": next_is_active,
    }
    authorization_changed = any(
        before.get(field_name) != authorization_after[field_name]
        for field_name in authorization_after
    )
    self_authorization_change = (
        authorization_changed and actor.actor_user_id == user_id
    )
    if self_authorization_change:
        planned_after = {
            field_name: before.get(field_name)
            for field_name in (
                "id",
                "email",
                "supabase_user_id",
                "role",
                "name",
                "posting_code",
                "programme_scope",
                "admin_level",
                "is_active",
                "current_staff_actor_name",
                "staff_actor_name_updated_at",
                "staff_actor_name_updated_by_user_id",
                "created_at",
            )
        }
        planned_after.update(
            {
                "name": display_name,
                **authorization_after,
            }
        )
        planned_after_snapshot = _safe_audit_snapshot(planned_after)
        planned_after_snapshot.pop("updated_at", None)
        # Audit while the request-start staff identity is still available to
        # the restricted audit helper. A role change or deactivation can make
        # that identity unavailable even before its session is revoked.
        await write_audit_log(
            db,
            actor=actor,
            action="admin.staff_account.update",
            entity_type="staff_account",
            entity_id=user_id,
            before=_safe_audit_snapshot(before),
            after=planned_after_snapshot,
            metadata={
                "account_type": account_type,
                "authorization_changed": True,
                "self_authorization_change": True,
                "revoked_session_count": None,
                "revoked_session_count_is_exact": False,
                "session_revocation_scope": "all_subject_sessions",
                "session_revocation_timing": (
                    "final_protected_action_same_transaction"
                ),
            },
        )

    result = await db.execute(
        text(
            """
            UPDATE users
            SET
                name = :name,
                role = :role,
                posting_code = :posting_code,
                programme_scope = :programme_scope,
                admin_level = :admin_level,
                is_active = :is_active,
                updated_at = now()
            WHERE id = :user_id
              AND role IN ('admin', 'secretary')
            RETURNING
                id,
                email,
                supabase_user_id,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id,
                created_at,
                updated_at
            """
        ),
        {
            "user_id": str(user_id),
            "name": display_name,
            "is_active": next_is_active,
            **account_fields,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise _not_found()
    after = dict(row)
    response = _staff_account_response(after)
    if self_authorization_change:
        # This must remain the final protected statement before commit: it
        # invalidates the signed context used by every subsequent statement.
        await revoke_subject_sessions(
            db,
            subject_type="staff",
            subject_id=user_id,
            reason="staff_authorization_changed",
        )
    else:
        revoked_session_count = 0
        if authorization_changed:
            revoked_session_count = await revoke_subject_sessions(
                db,
                subject_type="staff",
                subject_id=user_id,
                reason="staff_authorization_changed",
            )
        await write_audit_log(
            db,
            actor=actor,
            action="admin.staff_account.update",
            entity_type="staff_account",
            entity_id=user_id,
            before=_safe_audit_snapshot(before),
            after=_safe_audit_snapshot(after),
            metadata={
                "account_type": response["account_type"],
                "authorization_changed": authorization_changed,
                "revoked_session_count": revoked_session_count,
            },
        )
    await db.commit()
    return response


async def reset_staff_account_password(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: StaffAccountResetPasswordRequest,
    actor: StaffActorContext,
    settings: Settings,
) -> dict[str, Any]:
    if actor.actor_user_id == user_id:
        raise _validation_error(
            "Master Admins cannot reset their own password through staff "
            "account management"
        )

    before = await _get_staff_account_row(db, user_id=user_id)
    raw_supabase_user_id = before.get("supabase_user_id")

    if settings.auth_mode == "supabase":
        if not raw_supabase_user_id:
            raise _validation_error("Staff account is missing a Supabase user id")

    revoked_session_count = await revoke_subject_sessions(
        db,
        subject_type="staff",
        subject_id=user_id,
        reason="staff_password_reset",
        block_session_issuance=True,
    )
    fenced = await _get_staff_account_row(db, user_id=user_id)
    reset_generation = int(fenced["session_generation"])
    # Commit the fail-closed fence before calling the external identity provider.
    # A failed or interrupted upstream reset therefore leaves issuance blocked
    # and all existing MATA sessions invalid rather than reviving stale access.
    await db.commit()

    # Reacquire the subject row in a new transaction and retain this lock across
    # the bounded upstream call. A concurrent reset either supersedes this
    # operation in the commit-to-relock gap (controlled conflict) or waits until
    # this operation completes before installing its own generation fence.
    ownership_result = await db.execute(
        text(
            """
            SELECT session_generation, session_issuance_blocked
            FROM users
            WHERE id = :user_id
              AND role IN ('admin', 'secretary')
            FOR UPDATE
            """
        ),
        {"user_id": str(user_id)},
    )
    ownership = ownership_result.mappings().one_or_none()
    if (
        ownership is None
        or not ownership["session_issuance_blocked"]
        or int(ownership["session_generation"]) != reset_generation
    ):
        await db.rollback()
        raise _conflict("Password reset was superseded by another request")

    try:
        if settings.auth_mode == "supabase":
            await SupabaseAdminClient(settings).update_user_password(
                supabase_user_id=UUID(str(raw_supabase_user_id)),
                password=payload.password,
            )
    except Exception:
        # The already-committed issuance block remains fail-closed; this rollback
        # only releases the post-fence ownership lock for an authorized retry.
        await db.rollback()
        raise

    result = await db.execute(
        text(
            """
            UPDATE users
            SET
                password_hash = :password_hash,
                session_generation = session_generation + 1,
                session_issuance_blocked = false,
                current_staff_actor_name = NULL,
                staff_actor_name_updated_at = NULL,
                staff_actor_name_updated_by_user_id = NULL,
                updated_at = now()
            WHERE id = :user_id
              AND role IN ('admin', 'secretary')
              AND session_issuance_blocked = true
              AND session_generation = :reset_generation
            RETURNING
                id,
                email,
                supabase_user_id,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                session_generation,
                session_issuance_blocked,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id,
                created_at,
                updated_at
            """
        ),
        {
            "user_id": str(user_id),
            "reset_generation": reset_generation,
            "password_hash": _password_hash_for_auth_mode(
                settings=settings,
                supplied_password=payload.password,
            ),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        await db.rollback()
        raise _conflict("Password reset could not be finalized")
    after = dict(row)
    response = _staff_account_response(after)
    await write_audit_log(
        db,
        actor=actor,
        action="admin.staff_account.reset_password",
        entity_type="staff_account",
        entity_id=user_id,
        before=_safe_audit_snapshot(before),
        after=_safe_audit_snapshot(after),
        metadata={
            "account_type": response["account_type"],
            "cleared_staff_actor_name": True,
            "revoked_session_count": revoked_session_count,
        },
    )
    await db.commit()
    return response
