from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.services.audit import write_audit_log
from app.services.current_posting import (
    NATIVE_CURRENT_POSTING_JOIN_SQL,
    current_reporting_period_params,
)
from app.services.database_context import (
    session_uses_auth_boundary,
    session_uses_rls,
)
from app.services.mata_resident_token import (
    MataResidentTokenError,
    sign_mata_external_resident_token,
    sign_mata_resident_token,
)
from app.services.supabase_password_auth import (
    SupabasePasswordAuthError,
    authenticate_supabase_password,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthenticatedSubject:
    subject_type: Literal["staff", "resident", "external_resident"]
    subject_id: UUID
    auth_source: Literal["supabase_staff", "mata_resident"]
    session_generation: int
    user: dict[str, Any]
    normalized_mcr: str | None = None
    upstream_subject_id: UUID | None = None


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


def _resident_identity_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        detail="Conflict",
        error_code=ErrorCode.CONFLICT.value,
    )


def local_demo_password_hash(supplied_password: str) -> str:
    return f"plain:{supplied_password}"


def _password_matches(stored_hash: str, supplied_password: str) -> bool:
    return (
        stored_hash == supplied_password
        or stored_hash == local_demo_password_hash(supplied_password)
    )


def _resident_user(row: dict[str, Any]) -> dict[str, Any]:
    current_posting_code = row.get("current_posting_code")
    current_posting_label = row.get("current_posting_label") or current_posting_code
    payload = {
        "id": row["id"],
        "role": "resident",
        "name": row["name"],
        "programme_code": row.get("programme_code"),
        "mcr": row["mcr"],
    }
    if current_posting_code:
        payload["current_posting_code"] = current_posting_code
    if current_posting_label:
        payload["current_posting_label"] = current_posting_label
    return payload


def _external_resident_user(row: dict[str, Any]) -> dict[str, Any]:
    current_posting_code = row.get("current_posting_code")
    current_posting_label = row.get("current_posting_label") or current_posting_code
    payload = {
        "id": row["id"],
        "role": "external_resident",
        "name": row["name"],
        "mcr": row["mcr"],
        "home_cluster": row["home_cluster"],
    }
    if current_posting_code:
        payload["current_posting_code"] = current_posting_code
    if current_posting_label:
        payload["current_posting_label"] = current_posting_label
    return payload


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


def _session_generation(row: Any) -> int:
    try:
        generation = int(row["session_generation"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _auth_failure() from exc
    if generation < 0:
        raise _auth_failure()
    return generation


async def _current_reporting_period_params(db: AsyncSession) -> dict[str, Any]:
    return await current_reporting_period_params(db)


async def _lookup_resident_login_rows(
    db: AsyncSession,
    normalised_mcr: str,
) -> tuple[Any | None, Any | None]:
    period_params = await _current_reporting_period_params(db)
    resident_result = await db.execute(
        text(
            f"""
            SELECT r.id,
                   r.name,
                   r.mcr,
                   r.programme_code,
                   r.status,
                   r.session_generation,
                   current_posting.posting_code AS current_posting_code,
                   COALESCE(pc.display_name, current_posting.posting_code) AS current_posting_label
            FROM residents r
            {NATIVE_CURRENT_POSTING_JOIN_SQL}
            WHERE r.mcr = :mcr
            """
        ),
        {"mcr": normalised_mcr, **period_params},
    )
    external_result = await db.execute(
        text(
            """
            SELECT er.id,
                   er.name,
                   er.mcr,
                   er.home_cluster,
                   er.status,
                   er.session_generation,
                   current_posting.posting_code AS current_posting_code,
                   COALESCE(pc.display_name, current_posting.posting_code) AS current_posting_label
            FROM external_residents er
            LEFT JOIN LATERAL (
                SELECT erp.posting_code
                FROM external_resident_postings erp
                WHERE erp.external_resident_id = er.id
                  AND CAST(:has_reporting_period AS BOOLEAN) IS TRUE
                  AND erp.start_date <= :reporting_period_end
                  AND (
                    erp.end_date IS NULL
                    OR erp.end_date >= :reporting_period_start
                  )
                ORDER BY
                  CASE
                    WHEN erp.start_date <= CURRENT_DATE
                     AND (erp.end_date IS NULL OR erp.end_date >= CURRENT_DATE)
                      THEN 0
                    WHEN erp.start_date > CURRENT_DATE
                      THEN 1
                    ELSE 2
                  END,
                  CASE
                    WHEN erp.start_date > CURRENT_DATE
                      THEN erp.start_date - CURRENT_DATE
                    ELSE CURRENT_DATE - COALESCE(erp.end_date, erp.start_date)
                  END,
                  erp.start_date DESC,
                  erp.posting_code
                LIMIT 1
            ) current_posting ON true
            LEFT JOIN posting_codes pc
              ON pc.code = current_posting.posting_code
            WHERE er.mcr = :mcr
            """
        ),
        {"mcr": normalised_mcr, **period_params},
    )
    return (
        resident_result.mappings().one_or_none(),
        external_result.mappings().one_or_none(),
    )


async def _authenticate_with_rls_helpers(
    db: AsyncSession,
    *,
    role: str,
    email: str | None,
    password: str | None,
    mcr: str | None,
    settings: Settings,
) -> AuthenticatedSubject:
    if role in {"resident", "external_resident"}:
        normalised_mcr = _normalise_mcr(mcr)
        if not normalised_mcr:
            raise _auth_failure()
        result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.resident_login_candidate(
                    CAST(:normalized_mcr AS text)
                )
                """
            ),
            {"normalized_mcr": normalised_mcr},
        )
        candidate = result.mappings().one_or_none()
        # The candidate helper takes the global-MCR read lock. Release it
        # before the exact issuer starts the canonical subject -> MCR order.
        await db.rollback()
        if candidate is None:
            raise _auth_failure()
        row = dict(candidate)
        resolved_role = str(row.get("subject_type") or "")
        if resolved_role not in {"resident", "external_resident"}:
            raise _auth_failure()
        if role == "external_resident" and resolved_role != role:
            raise _auth_failure()
        row["id"] = row["subject_id"]
        return AuthenticatedSubject(
            subject_type=resolved_role,
            subject_id=UUID(str(row["subject_id"])),
            auth_source="mata_resident",
            session_generation=_session_generation(row),
            normalized_mcr=normalised_mcr,
            user=(
                _resident_user(row)
                if resolved_role == "resident"
                else _external_resident_user(row)
            ),
        )

    if not email or not password or role not in {"staff", "admin", "secretary"}:
        raise _auth_failure()

    if settings.auth_mode == "supabase":
        snapshot_result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.staff_login_snapshot(
                    CAST(:normalized_email AS text)
                )
                """
            ),
            {"normalized_email": email.strip().lower()},
        )
        authentication_snapshot = snapshot_result.mappings().one_or_none()
        # Do not retain an auth-boundary transaction or subject lock across the
        # bounded upstream password exchange.
        await db.rollback()
        try:
            claims = await authenticate_supabase_password(
                email=email,
                password=password,
                settings=settings,
            )
        except SupabasePasswordAuthError as exc:
            raise _auth_failure() from exc
        raw_supabase_subject = claims.get("sub")
        if not isinstance(raw_supabase_subject, str):
            raise _auth_failure()
        try:
            upstream_subject_id = UUID(raw_supabase_subject)
        except ValueError as exc:
            raise _auth_failure() from exc
        if authentication_snapshot is None:
            raise _auth_failure()
        snapshot = dict(authentication_snapshot)
        local_subject_id = UUID(str(snapshot["id"]))
        expected_generation = _session_generation(snapshot)
        identity_result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.staff_login_identity(
                    CAST(:local_subject_id AS uuid),
                    CAST(:upstream_subject_id AS uuid),
                    CAST(:expected_generation AS bigint)
                )
                """
            ),
            {
                "local_subject_id": local_subject_id,
                "upstream_subject_id": upstream_subject_id,
                "expected_generation": expected_generation,
            },
        )
        user_row = identity_result.mappings().one_or_none()
    else:
        candidate_result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.staff_login_candidate(
                    CAST(:normalized_email AS text)
                )
                """
            ),
            {"normalized_email": email.strip().lower()},
        )
        user_row = candidate_result.mappings().one_or_none()
        await db.rollback()
        if user_row is None or not _password_matches(
            str(user_row["password_hash"]),
            password,
        ):
            raise _auth_failure()
        raw_upstream_subject_id = user_row.get("supabase_user_id")
        if raw_upstream_subject_id is None:
            raise _auth_failure()
        upstream_subject_id = UUID(str(raw_upstream_subject_id))
        expected_generation = _session_generation(user_row)

    if (
        user_row is None
        or user_row["role"] not in {"admin", "secretary"}
        or bool(user_row.get("session_issuance_blocked"))
    ):
        raise _auth_failure()
    if role in {"admin", "secretary"} and user_row["role"] != role:
        raise _auth_failure()

    row = dict(user_row)
    return AuthenticatedSubject(
        subject_type="staff",
        subject_id=UUID(str(row["id"])),
        auth_source="supabase_staff",
        session_generation=expected_generation,
        upstream_subject_id=upstream_subject_id,
        user=_user_identity(row),
    )


async def authenticate_for_app_session(
    db: AsyncSession,
    *,
    role: str,
    email: str | None,
    password: str | None,
    mcr: str | None,
    settings: Settings,
) -> AuthenticatedSubject:
    """Authenticate credentials without returning or persisting an upstream token."""

    if session_uses_auth_boundary(db):
        return await _authenticate_with_rls_helpers(
            db,
            role=role,
            email=email,
            password=password,
            mcr=mcr,
            settings=settings,
        )

    if role in {"resident", "external_resident"}:
        normalised_mcr = _normalise_mcr(mcr)
        if not normalised_mcr:
            raise _auth_failure()
        resident_row, external_resident_row = await _lookup_resident_login_rows(
            db,
            normalised_mcr,
        )
        if resident_row is not None and external_resident_row is not None:
            logger.error(
                "Resident login rejected because the global identity uniqueness invariant failed"
            )
            raise _auth_failure()

        if role == "external_resident":
            resolved_role = "external_resident"
            identity_row = external_resident_row
        elif resident_row is not None:
            resolved_role = "resident"
            identity_row = resident_row
        else:
            resolved_role = "external_resident"
            identity_row = external_resident_row

        if identity_row is None or identity_row.get("status") != "active":
            raise _auth_failure()
        row = dict(identity_row)
        return AuthenticatedSubject(
            subject_type=resolved_role,
            subject_id=UUID(str(row["id"])),
            auth_source="mata_resident",
            session_generation=_session_generation(row),
            user=(
                _resident_user(row)
                if resolved_role == "resident"
                else _external_resident_user(row)
            ),
        )

    if not email or not password:
        raise _auth_failure()

    if settings.auth_mode == "supabase":
        snapshot_result = await db.execute(
            text(
                """
                SELECT
                    id,
                    supabase_user_id,
                    session_generation
                FROM users
                WHERE lower(email) = lower(:email)
                """
            ),
            {"email": email},
        )
        authentication_snapshot = snapshot_result.mappings().one_or_none()
        # Release the local snapshot transaction before the upstream password
        # exchange; the fenced lookup below revalidates the subject afterward.
        await db.rollback()
        try:
            claims = await authenticate_supabase_password(
                email=email,
                password=password,
                settings=settings,
            )
        except SupabasePasswordAuthError as exc:
            raise _auth_failure() from exc
        raw_supabase_subject = claims.get("sub")
        if not isinstance(raw_supabase_subject, str):
            raise _auth_failure()
        try:
            supabase_user_id = UUID(raw_supabase_subject)
        except ValueError as exc:
            raise _auth_failure() from exc

        result = await db.execute(
            text(
                """
                SELECT
                    id,
                    email,
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
                    staff_actor_name_updated_by_user_id
                FROM users
                WHERE supabase_user_id = :supabase_user_id
                  AND is_active = true
                """
            ),
            {"supabase_user_id": str(supabase_user_id)},
        )
        user_row = result.mappings().one_or_none()
        if authentication_snapshot is None or user_row is None:
            raise _auth_failure()
        snapshot = dict(authentication_snapshot)
        current = dict(user_row)
        if (
            UUID(str(snapshot["id"])) != UUID(str(current["id"]))
            or snapshot.get("supabase_user_id") != current.get("supabase_user_id")
            or _session_generation(snapshot) != _session_generation(current)
        ):
            raise _auth_failure()
    else:
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
                    session_generation,
                    session_issuance_blocked,
                    current_staff_actor_name,
                    staff_actor_name_updated_at,
                    staff_actor_name_updated_by_user_id
                FROM users
                WHERE lower(email) = lower(:email)
                  AND is_active = true
                """
            ),
            {"email": email},
        )
        user_row = result.mappings().one_or_none()
        if user_row is None or not _password_matches(user_row["password_hash"], password):
            raise _auth_failure()

    if (
        user_row is None
        or user_row["role"] not in {"admin", "secretary"}
        or bool(user_row.get("session_issuance_blocked"))
    ):
        raise _auth_failure()
    if role in {"admin", "secretary"} and user_row["role"] != role:
        raise _auth_failure()

    row = dict(user_row)
    return AuthenticatedSubject(
        subject_type="staff",
        subject_id=UUID(str(row["id"])),
        auth_source="supabase_staff",
        session_generation=_session_generation(row),
        user=_user_identity(row),
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
            logger.error(
                "Resident login rejected because the global MCR uniqueness invariant was violated",
            )
            raise _resident_identity_conflict()

        if role == "external_resident":
            # Retained compatibility path: an explicit external request never
            # authenticates or falls back to a native resident row.
            resolved_role = "external_resident"
            identity_row = external_resident_row
        elif resident_row is not None:
            resolved_role = "resident"
            identity_row = resident_row
        else:
            # The neutral resident request is the shared MCR login path.
            resolved_role = "external_resident"
            identity_row = external_resident_row

        if identity_row is None or identity_row.get("status") != "active":
            raise _auth_failure()
        user = (
            _resident_user(dict(identity_row))
            if resolved_role == "resident"
            else _external_resident_user(dict(identity_row))
        )
        if auth_mode == "supabase":
            try:
                signer = (
                    sign_mata_resident_token
                    if resolved_role == "resident"
                    else sign_mata_external_resident_token
                )
                access_token = signer(
                    dict(identity_row),
                    settings=settings or Settings(auth_mode=auth_mode),
                )
            except MataResidentTokenError as exc:
                raise _auth_config_failure() from exc
        else:
            access_token = _stub_access_token(role=resolved_role, subject_id=user["id"])
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
                session_issuance_blocked,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id
            FROM users
            WHERE lower(email) = lower(:email)
              AND (:role = 'staff' OR role = :role)
              AND is_active = true
              AND session_issuance_blocked = false
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
        period_params = await _current_reporting_period_params(db)
        result = await db.execute(
            text(
                f"""
                SELECT r.id,
                       r.name,
                       r.mcr,
                       r.programme_code,
                       r.status,
                       current_posting.posting_code AS current_posting_code,
                       COALESCE(pc.display_name, current_posting.posting_code) AS current_posting_label
                FROM residents r
                {NATIVE_CURRENT_POSTING_JOIN_SQL}
                WHERE r.id = :resident_id
                """
            ),
            {"resident_id": str(subject_id), **period_params},
        )
        resident = result.mappings().one_or_none()
        if resident is None or resident.get("status") != "active":
            raise _auth_failure()
        return _resident_user(dict(resident))

    if role == "external_resident":
        period_params = await _current_reporting_period_params(db)
        result = await db.execute(
            text(
                """
                SELECT er.id,
                       er.name,
                       er.mcr,
                       er.home_cluster,
                       er.status,
                       current_posting.posting_code AS current_posting_code,
                       COALESCE(pc.display_name, current_posting.posting_code) AS current_posting_label
                FROM external_residents er
                LEFT JOIN LATERAL (
                    SELECT erp.posting_code
                    FROM external_resident_postings erp
                    WHERE erp.external_resident_id = er.id
                      AND CAST(:has_reporting_period AS BOOLEAN) IS TRUE
                      AND erp.start_date <= :reporting_period_end
                      AND (
                        erp.end_date IS NULL
                        OR erp.end_date >= :reporting_period_start
                      )
                    ORDER BY
                      CASE
                        WHEN erp.start_date <= CURRENT_DATE
                         AND (erp.end_date IS NULL OR erp.end_date >= CURRENT_DATE)
                          THEN 0
                        WHEN erp.start_date > CURRENT_DATE
                          THEN 1
                        ELSE 2
                      END,
                      CASE
                        WHEN erp.start_date > CURRENT_DATE
                          THEN erp.start_date - CURRENT_DATE
                        ELSE CURRENT_DATE - COALESCE(erp.end_date, erp.start_date)
                      END,
                      erp.start_date DESC,
                      erp.posting_code
                    LIMIT 1
                ) current_posting ON true
                LEFT JOIN posting_codes pc
                  ON pc.code = current_posting.posting_code
                WHERE er.id = :external_resident_id
                """
            ),
            {"external_resident_id": str(subject_id), **period_params},
        )
        resident = result.mappings().one_or_none()
        if resident is None or resident.get("status") != "active":
            raise _auth_failure()
        return _external_resident_user(dict(resident))

    result = await db.execute(
        text(
            """
            SELECT
                id,
                email,
                role,
                name,
                posting_code,
                programme_scope,
                admin_level,
                is_active,
                session_issuance_blocked,
                current_staff_actor_name,
                staff_actor_name_updated_at,
                staff_actor_name_updated_by_user_id
            FROM users
            WHERE id = :user_id
              AND is_active = true
              AND session_issuance_blocked = false
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

    if session_uses_rls(db):
        result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.update_own_staff_actor_name(
                    CAST(:actor_name AS text)
                )
                """
            ),
            {"actor_name": actor_name},
        )
    else:
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
    if (
        user is None
        or UUID(str(user["id"])) != user_id
        or str(user["role"]) != role
    ):
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
