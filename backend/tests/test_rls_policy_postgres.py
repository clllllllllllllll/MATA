from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
import json
import secrets
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError
from app.schemas.data_revalidation import (
    DataRevalidationChangedEntity,
    DataRevalidationOutcome,
)
from app.schemas.teaching_name_mappings import TeachingNameMappingBulkItemRequest
from app.services import (
    programme_teaching_events,
    resident_submission,
    secretary_events,
    teaching_name_mappings,
    teaching_name_pool,
)
from app.services.database_context import configure_request_context
from app.services.ttf_scope_lock import acquire_ttf_scope_lock
from tests.rls_postgres_harness import (
    RUNTIME_GROUP,
    RlsPostgresHarness,
    rls_postgres_harness,
)


APPLICATION_TABLES = (
    "academic_month_boundaries",
    "app_sessions",
    "attendance_records",
    "audit_logs",
    "clawback_records",
    "event_series",
    "external_attendance_records",
    "external_resident_postings",
    "external_residents",
    "form_f1_records",
    "global_session_types",
    "loa_types",
    "multi_posting_rules",
    "period_snapshots",
    "posting_codes",
    "posting_groups",
    "programme_institution_posting_map",
    "programmes",
    "public_holidays",
    "rate_limit_buckets",
    "reporting_periods",
    "resident_postings",
    "residents",
    "secretary_programme_pools",
    "session_types",
    "surplus_ledger",
    "teaching_events",
    "teaching_name_mappings",
    "teaching_names",
    "teaching_name_catalogue",
    "teaching_targets",
    "upload_logs",
    "upload_warnings",
    "users",
    "warning_issues",
    "weekend_exceptions",
)

HELPER_ONLY_TABLES = (
    "app_sessions",
    "clawback_records",
    "period_snapshots",
    "programme_institution_posting_map",
    "rate_limit_buckets",
    "surplus_ledger",
)

DIRECT_TABLES = tuple(
    table_name
    for table_name in APPLICATION_TABLES
    if table_name not in HELPER_ONLY_TABLES
)

_INSTALL_CONTEXT_SQL = text(
    """
    SELECT
        subject_type,
        subject_id,
        app_role,
        admin_level,
        programme_scope,
        posting_code,
        app_session_id,
        authorization_fingerprint
    FROM mata_rls.install_request_context(
        CAST(:token_digest AS bytea),
        'shared',
        CAST(:expected_subject_type AS text),
        CAST(:expected_subject_id AS uuid),
        CAST(:expected_app_session_id AS uuid),
        CAST(:expected_authorization_fingerprint AS text)
    )
    """
)


@dataclass(frozen=True, slots=True)
class PolicyContext:
    token_digest: bytes
    subject_type: str
    subject_id: UUID
    app_session_id: UUID
    authorization_fingerprint: str

    def installer_parameters(self) -> dict[str, object]:
        return {
            "token_digest": self.token_digest,
            "expected_subject_type": self.subject_type,
            "expected_subject_id": self.subject_id,
            "expected_app_session_id": self.app_session_id,
            "expected_authorization_fingerprint": (
                self.authorization_fingerprint
            ),
        }


@dataclass(frozen=True, slots=True)
class PolicyMatrixSeed:
    contexts: Mapping[str, PolicyContext]
    values: Mapping[str, Any]


def _sqlstate(error: DBAPIError) -> str | None:
    original = error.orig
    return getattr(original, "sqlstate", None) or getattr(
        original,
        "pgcode",
        None,
    )


async def _assert_permission_denied(
    db: AsyncSession,
    statement: str,
    parameters: Mapping[str, object] | None = None,
) -> None:
    with pytest.raises(DBAPIError) as caught:
        async with db.begin_nested():
            await db.execute(text(statement), dict(parameters or {}))
    assert _sqlstate(caught.value) == "42501"


async def _scalar_set(
    db: AsyncSession,
    statement: str,
    parameters: Mapping[str, object] | None = None,
) -> set[Any]:
    result = await db.scalars(text(statement), dict(parameters or {}))
    return set(result.all())


async def _wait_for_matching_advisory_lock(
    harness: RlsPostgresHarness,
    *,
    holder_pid: int,
    waiter_pid: int,
    blocked_task: asyncio.Task[Any],
) -> None:
    async def _poll() -> None:
        async with harness.owner_session() as db:
            while True:
                matching_lock = await db.scalar(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_catalog.pg_locks AS holder
                            JOIN pg_catalog.pg_locks AS waiter
                              ON waiter.locktype = holder.locktype
                             AND waiter.database
                                 IS NOT DISTINCT FROM holder.database
                             AND waiter.classid
                                 IS NOT DISTINCT FROM holder.classid
                             AND waiter.objid
                                 IS NOT DISTINCT FROM holder.objid
                             AND waiter.objsubid
                                 IS NOT DISTINCT FROM holder.objsubid
                            WHERE holder.pid = :holder_pid
                              AND waiter.pid = :waiter_pid
                              AND holder.locktype = 'advisory'
                              AND holder.granted
                              AND NOT waiter.granted
                        )
                        """
                    ),
                    {
                        "holder_pid": holder_pid,
                        "waiter_pid": waiter_pid,
                    },
                )
                if matching_lock:
                    return
                if blocked_task.done():
                    await blocked_task
                    pytest.fail(
                        "Scheduled submission did not wait on the "
                        "ad-hoc helper's advisory lock",
                        pytrace=False,
                    )

    await asyncio.wait_for(_poll(), timeout=10)


async def _wait_for_database_lock_wait(
    harness: RlsPostgresHarness,
    *,
    waiter_pid: int,
    blocked_task: asyncio.Task[Any],
) -> None:
    async def _poll() -> None:
        async with harness.owner_session() as db:
            while True:
                waiting = await db.scalar(
                    text(
                        """
                        SELECT wait_event_type = 'Lock'
                        FROM pg_catalog.pg_stat_activity
                        WHERE pid = :waiter_pid
                        """
                    ),
                    {"waiter_pid": waiter_pid},
                )
                if waiting is True:
                    return
                if blocked_task.done():
                    await blocked_task
                    pytest.fail(
                        "Scheduled event reference did not wait on the "
                        "Master Teaching Name delete lock",
                        pytrace=False,
                    )
                await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=10)


@asynccontextmanager
async def _runtime_context(
    harness: RlsPostgresHarness,
    context: PolicyContext,
) -> AsyncIterator[AsyncSession]:
    async with harness.runtime_session() as db:
        installed = (
            await db.execute(
                _INSTALL_CONTEXT_SQL,
                context.installer_parameters(),
            )
        ).mappings().one_or_none()
        assert installed is not None
        assert installed["subject_type"] == context.subject_type
        assert installed["subject_id"] == context.subject_id
        assert installed["app_session_id"] == context.app_session_id
        assert (
            installed["authorization_fingerprint"]
            == context.authorization_fingerprint
        )
        try:
            yield db
        finally:
            await db.rollback()


@asynccontextmanager
async def _service_runtime_context(
    harness: RlsPostgresHarness,
    context: PolicyContext,
) -> AsyncIterator[AsyncSession]:
    """Use the production context hook so service commits re-install RLS safely."""

    async with harness.runtime_context_session() as db:
        configure_request_context(
            db,
            token_digest=context.token_digest,
            expected_subject_type="staff",
            expected_subject_id=context.subject_id,
            expected_app_session_id=context.app_session_id,
            expected_authorization_fingerprint=context.authorization_fingerprint,
            lock_mode="exclusive",
        )
        try:
            yield db
        finally:
            await db.rollback()


def _pc_teaching_name_actor(
    values: Mapping[str, Any],
    *,
    programme_scope: frozenset[str] | None = None,
) -> teaching_name_pool.TeachingNamePoolActor:
    scope = programme_scope or frozenset({str(values["programme_a"])})
    return teaching_name_pool.TeachingNamePoolActor(
        kind="programme_pc",
        user_id=values["pc_id"],
        programme_scope=scope,
        staff_actor=StaffActorContext(
            actor_user_id=values["pc_id"],
            actor_role="admin",
            actor_name="RLS PC",
            actor_programme=",".join(sorted(scope)),
            raw_scope_metadata={"programme_scope": sorted(scope)},
        ),
    )


def _secretary_teaching_name_actor(
    values: Mapping[str, Any],
) -> teaching_name_pool.TeachingNamePoolActor:
    return teaching_name_pool.TeachingNamePoolActor(
        kind="secretary",
        user_id=values["secretary_id"],
        posting_code=str(values["posting_a"]),
        staff_actor=StaffActorContext(
            actor_user_id=values["secretary_id"],
            actor_role="secretary",
            actor_name="RLS Secretary",
            actor_site=str(values["posting_a"]),
            actor_programme=str(values["programme_a"]),
            raw_scope_metadata={"site": str(values["posting_a"])},
        ),
    )


def _master_teaching_name_actor(
    values: Mapping[str, Any],
) -> teaching_name_pool.TeachingNamePoolActor:
    return teaching_name_pool.TeachingNamePoolActor(
        kind="master_admin",
        user_id=values["master_id"],
        staff_actor=StaffActorContext(
            actor_user_id=values["master_id"],
            actor_role="admin",
            actor_name="RLS Master",
            actor_admin_level="master",
            raw_scope_metadata={"admin_level": "master"},
        ),
    )


async def _cleanup_teaching_name_service_rows(
    harness: RlsPostgresHarness,
    *,
    teaching_name_ids: list[UUID],
    teaching_target_ids: list[UUID] | None = None,
    programme_ids: list[UUID] | None = None,
) -> None:
    if not teaching_name_ids and not teaching_target_ids and not programme_ids:
        return
    async with harness.owner_session() as db:
        if teaching_name_ids:
            name_ids = [str(value) for value in teaching_name_ids]
            await db.execute(
                text(
                    """
                    DELETE FROM audit_logs
                    WHERE entity_type = 'teaching_name'
                      AND entity_id = ANY(CAST(:name_ids AS text[]))
                    """
                ),
                {"name_ids": name_ids},
            )
            await db.execute(
                text(
                    "DELETE FROM teaching_names WHERE id = ANY(CAST(:name_ids AS uuid[]))"
                ),
                {"name_ids": name_ids},
            )
        if teaching_target_ids:
            await db.execute(
                text("DELETE FROM teaching_targets WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": teaching_target_ids},
            )
        if programme_ids:
            await db.execute(
                text("DELETE FROM programmes WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": programme_ids},
            )
        await db.commit()


async def _issue_context(
    harness: RlsPostgresHarness,
    *,
    subject_type: str,
    subject_id: UUID,
    session_generation: int,
    supabase_user_id: UUID | None = None,
    normalized_mcr: str | None = None,
) -> PolicyContext:
    app_session_id = uuid4()
    token_digest = secrets.token_bytes(32)
    csrf_digest = secrets.token_bytes(32)

    if subject_type == "staff":
        assert supabase_user_id is not None
        issue_sql = text(
            """
            SELECT id
            FROM mata_rls.issue_staff_app_session_lifecycle(
                CAST(:subject_id AS uuid),
                CAST(:supabase_user_id AS uuid),
                CAST(:session_generation AS bigint),
                CAST(:app_session_id AS uuid),
                CAST(:token_digest AS bytea),
                CAST(:csrf_digest AS bytea),
                3600,
                28800,
                NULL
            )
            """
        )
        parameters: dict[str, object] = {
            "subject_id": subject_id,
            "supabase_user_id": supabase_user_id,
            "session_generation": session_generation,
            "app_session_id": app_session_id,
            "token_digest": token_digest,
            "csrf_digest": csrf_digest,
        }
    else:
        assert subject_type in {"resident", "external_resident"}
        assert normalized_mcr is not None
        function_name = (
            "issue_resident_app_session_lifecycle"
            if subject_type == "resident"
            else "issue_external_resident_app_session_lifecycle"
        )
        issue_sql = text(
            f"""
            SELECT id
            FROM mata_rls.{function_name}(
                CAST(:normalized_mcr AS text),
                CAST(:subject_type AS text),
                CAST(:subject_id AS uuid),
                CAST(:session_generation AS bigint),
                CAST(:app_session_id AS uuid),
                CAST(:token_digest AS bytea),
                CAST(:csrf_digest AS bytea),
                3600,
                43200,
                NULL
            )
            """
        )
        parameters = {
            "normalized_mcr": normalized_mcr,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "session_generation": session_generation,
            "app_session_id": app_session_id,
            "token_digest": token_digest,
            "csrf_digest": csrf_digest,
        }

    async with harness.auth_session() as db:
        issued_id = await db.scalar(issue_sql, parameters)
        assert issued_id == app_session_id
        resolved = (
            await db.execute(
                text(
                    """
                    SELECT id, subject_type, subject_id,
                           authorization_fingerprint
                    FROM mata_rls.resolve_app_session_lifecycle(
                        CAST(:token_digest AS bytea),
                        3600
                    )
                    """
                ),
                {"token_digest": token_digest},
            )
        ).mappings().one()
        assert resolved["id"] == app_session_id
        assert resolved["subject_type"] == subject_type
        assert resolved["subject_id"] == subject_id
        authorization_fingerprint = resolved["authorization_fingerprint"]
        assert isinstance(authorization_fingerprint, str)
        assert len(authorization_fingerprint) == 64
        await db.commit()

    return PolicyContext(
        token_digest=token_digest,
        subject_type=subject_type,
        subject_id=subject_id,
        app_session_id=app_session_id,
        authorization_fingerprint=authorization_fingerprint,
    )


@pytest_asyncio.fixture
async def policy_harness(
    rls_postgres_harness: RlsPostgresHarness,
) -> AsyncIterator[RlsPostgresHarness]:
    assert rls_postgres_harness.revision == "20260804_000034"
    yield rls_postgres_harness


@pytest_asyncio.fixture
async def policy_seed(
    policy_harness: RlsPostgresHarness,
) -> AsyncIterator[PolicyMatrixSeed]:
    suffix = secrets.token_hex(4).upper()
    values: dict[str, Any] = {
        "programme_a": f"RA{suffix}",
        "programme_b": f"RB{suffix}",
        "posting_a": f"RLSA{suffix}",
        "posting_b": f"RLSB{suffix}",
        "keyword": f"RLS Policy Teaching {suffix}",
        "session_name": f"RLS Session {suffix}",
        "holiday_date": date(2199, 1, 1)
        + timedelta(days=int(suffix, 16) % 365),
    }
    for key in (
        "posting_a_id",
        "posting_b_id",
        "programme_a_id",
        "programme_b_id",
        "period_id",
        "session_type_id",
        "master_id",
        "pc_id",
        "pc_null_id",
        "pc_empty_id",
        "secretary_id",
        "master_supabase_id",
        "pc_supabase_id",
        "pc_null_supabase_id",
        "pc_empty_supabase_id",
        "secretary_supabase_id",
        "resident_a_id",
        "resident_b_id",
        "resident_peer_id",
        "external_a_id",
        "external_b_id",
        "external_peer_id",
        "resident_posting_a_id",
        "resident_posting_b_id",
        "resident_posting_peer_id",
        "external_posting_a_id",
        "external_posting_b_id",
        "external_posting_peer_id",
        "catalogue_a_id",
        "catalogue_b_id",
        "catalogue_cross_id",
        "target_a_id",
        "target_b_id",
        "teaching_name_a_id",
        "teaching_name_b_id",
        "mapping_a_id",
        "mapping_b_id",
        "pc_teaching_name_id",
        "pc_mapping_id",
        "secretary_teaching_name_id",
        "pool_a_id",
        "rule_a_id",
        "rule_b_id",
        "series_a_id",
        "series_b_id",
        "event_seed_a_id",
        "event_action_a_id",
        "event_b_id",
        "attendance_a_id",
        "attendance_b_id",
        "external_attendance_a_id",
        "external_attendance_b_id",
    ):
        values[key] = uuid4()
    values["resident_a_mcr"] = f"RLNA{suffix}"
    values["resident_b_mcr"] = f"RLNB{suffix}"
    values["resident_peer_mcr"] = f"RLNP{suffix}"
    values["external_a_mcr"] = f"RLEA{suffix}"
    values["external_b_mcr"] = f"RLEB{suffix}"
    values["external_peer_mcr"] = f"RLEP{suffix}"

    async with policy_harness.owner_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO posting_codes (
                    id, code, display_name, institution, department,
                    supports_secretary_events
                )
                VALUES
                    (
                        :posting_a_id, :posting_a, :posting_a,
                        'RLS Test', 'A', true
                    ),
                    (
                        :posting_b_id, :posting_b, :posting_b,
                        'RLS Test', 'B', true
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO programmes (
                    id, code, name, ay_date_category, r_year_required,
                    is_subspecialty
                )
                VALUES
                    (
                        :programme_a_id, :programme_a, :programme_a,
                        'non_im_subspec', true, false
                    ),
                    (
                        :programme_b_id, :programme_b, :programme_b,
                        'non_im_subspec', true, false
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO reporting_periods (
                    id, label, start_date, end_date, status
                )
                VALUES (
                    :period_id,
                    :label,
                    DATE '2035-01-01',
                    DATE '2035-12-31',
                    'active'
                )
                """
            ),
            {**values, "label": f"RLS 000026 {suffix}"},
        )
        await db.execute(
            text(
                """
                INSERT INTO session_types (
                    id, name, duration_hours, duration_label
                )
                VALUES (:session_type_id, :name, 1.00, '1h')
                """
            ),
            {**values, "name": values["session_name"]},
        )
        await db.execute(
            text(
                """
                INSERT INTO users (
                    id, email, supabase_user_id, password_hash, role, name,
                    posting_code, programme_scope, admin_level, is_active,
                    session_generation, session_issuance_blocked
                )
                VALUES
                    (
                        :master_id, :master_email, :master_supabase_id,
                        'rls-policy-owner-seed', 'admin', 'RLS Master',
                        NULL, ARRAY[]::text[], 'master', true, 0, false
                    ),
                    (
                        :pc_id, :pc_email, :pc_supabase_id,
                        'rls-policy-owner-seed', 'admin', 'RLS PC',
                        NULL, ARRAY[:programme_a]::text[], 'programme',
                        true, 0, false
                    ),
                    (
                        :pc_null_id, :pc_null_email, :pc_null_supabase_id,
                        'rls-policy-owner-seed', 'admin', 'RLS Null PC',
                        NULL, NULL, 'programme', true, 0, false
                    ),
                    (
                        :pc_empty_id, :pc_empty_email, :pc_empty_supabase_id,
                        'rls-policy-owner-seed', 'admin', 'RLS Empty PC',
                        NULL, ARRAY[]::text[], 'programme', true, 0, false
                    ),
                    (
                        :secretary_id, :secretary_email,
                        :secretary_supabase_id, 'rls-policy-owner-seed',
                        'secretary', 'RLS Secretary', :posting_a,
                        NULL, 'programme', true, 0, false
                    )
                """
            ),
            {
                **values,
                "master_email": f"master-{suffix}@example.invalid",
                "pc_email": f"pc-{suffix}@example.invalid",
                "pc_null_email": f"pc-null-{suffix}@example.invalid",
                "pc_empty_email": f"pc-empty-{suffix}@example.invalid",
                "secretary_email": f"secretary-{suffix}@example.invalid",
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO residents (
                    id, name, mcr, programme_code, r_year, status,
                    session_generation
                )
                VALUES
                    (
                        :resident_a_id, 'RLS Native A', :resident_a_mcr,
                        :programme_a, 'R1', 'active', 0
                    ),
                    (
                        :resident_b_id, 'RLS Native B', :resident_b_mcr,
                        :programme_b, 'R1', 'active', 0
                    ),
                    (
                        :resident_peer_id, 'RLS Native Peer',
                        :resident_peer_mcr, :programme_a, 'R1', 'active', 0
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO external_residents (
                    id, name, mcr, home_cluster, current_nhg_posting_code,
                    status, session_generation
                )
                VALUES
                    (
                        :external_a_id, 'RLS External A', :external_a_mcr,
                        'NUH', :posting_a, 'active', 0
                    ),
                    (
                        :external_b_id, 'RLS External B', :external_b_mcr,
                        'SingHealth', :posting_b, 'active', 0
                    ),
                    (
                        :external_peer_id, 'RLS External Peer',
                        :external_peer_mcr, 'NUH', :posting_a, 'active', 0
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO resident_postings (
                    id, resident_id, posting_code, reporting_period_id,
                    start_date, end_date, r_year, status
                )
                VALUES
                    (
                        :resident_posting_a_id, :resident_a_id, :posting_a,
                        :period_id, DATE '2035-01-01', DATE '2035-12-31',
                        'R1', 'active'
                    ),
                    (
                        :resident_posting_b_id, :resident_b_id, :posting_b,
                        :period_id, DATE '2035-01-01', DATE '2035-12-31',
                        'R1', 'active'
                    ),
                    (
                        :resident_posting_peer_id, :resident_peer_id,
                        :posting_a, :period_id, DATE '2035-01-01',
                        DATE '2035-12-31', 'R1', 'active'
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO external_resident_postings (
                    id, external_resident_id, posting_code, programme_code,
                    start_date, end_date, is_current
                )
                VALUES
                    (
                        :external_posting_a_id, :external_a_id, :posting_a,
                        :programme_a, DATE '2035-01-01', DATE '2035-12-31',
                        true
                    ),
                    (
                        :external_posting_b_id, :external_b_id, :posting_b,
                        :programme_b, DATE '2035-01-01', DATE '2035-12-31',
                        true
                    ),
                    (
                        :external_posting_peer_id, :external_peer_id,
                        :posting_a, :programme_a, DATE '2035-01-01',
                        DATE '2035-12-31', true
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO teaching_name_catalogue (
                    id, keyword, session_type_id, posting_code,
                    programme_code, r_year, reporting_period_id,
                    duration_hours, is_tracked
                )
                VALUES
                    (
                        :catalogue_a_id, :keyword, :session_type_id,
                        :posting_a, :programme_a, 'R1', :period_id,
                        1.00, true
                    ),
                    (
                        :catalogue_b_id, :keyword, :session_type_id,
                        :posting_b, :programme_b, 'R1', :period_id,
                        1.00, true
                    ),
                    (
                        :catalogue_cross_id, :keyword, :session_type_id,
                        :posting_b, :programme_a, 'R1', :period_id,
                        1.00, true
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO teaching_targets (
                    id, reporting_period_id, programme_code, r_year,
                    posting_code, session_type_id, monthly_target,
                    is_tracked
                )
                VALUES
                    (
                        :target_a_id, :period_id, :programme_a, 'R1',
                        :posting_a, :session_type_id, 1, true
                    ),
                    (
                        :target_b_id, :period_id, :programme_b, 'R1',
                        :posting_b, :session_type_id, 1, true
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO secretary_programme_pools (
                    id, posting_code, programme_code, is_active
                )
                VALUES (:pool_a_id, :posting_a, :programme_a, true)
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO teaching_names (
                    id, reporting_period_id, programme_code, display_name,
                    normalized_name, is_active
                )
                VALUES
                    (
                        :teaching_name_a_id, :period_id, :programme_a,
                        'RLS Teaching Name A', 'rls teaching name a', false
                    ),
                    (
                        :teaching_name_b_id, :period_id, :programme_b,
                        'RLS Teaching Name B', 'rls teaching name b', false
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO teaching_name_mappings (
                    id, teaching_name_id, reporting_period_id, programme_code,
                    posting_code, r_year, teaching_target_id
                )
                VALUES
                    (
                        :mapping_a_id, :teaching_name_a_id, :period_id,
                        :programme_a, :posting_a, 'R1', :target_a_id
                    ),
                    (
                        :mapping_b_id, :teaching_name_b_id, :period_id,
                        :programme_b, :posting_b, 'R1', :target_b_id
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO multi_posting_rules (
                    id, programme_code, posting_code_1, posting_code_2,
                    rule_type, combined_label
                )
                VALUES
                    (
                        :rule_a_id, :programme_a, :posting_a, :posting_b,
                        'combine', 'RLS A'
                    ),
                    (
                        :rule_b_id, :programme_b, :posting_a, :posting_b,
                        'combine', 'RLS B'
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO event_series (
                    id, posting_code, recurrence_pattern,
                    recurrence_interval
                )
                VALUES
                    (:series_a_id, :posting_a, 'weekly', 1),
                    (:series_b_id, :posting_b, 'weekly', 1)
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO teaching_events (
                    id, posting_code, teaching_name, event_date, start_time,
                    end_time, duration_hours, session_type_id, series_id,
                    is_adhoc, created_by_role, teaching_name_id
                )
                VALUES
                    (
                        :event_seed_a_id, :posting_a, :keyword,
                        DATE '2035-03-05', TIME '09:00', TIME '10:00',
                        1.00, :session_type_id, :series_a_id, false,
                        'secretary', :teaching_name_a_id
                    ),
                    (
                        :event_action_a_id, :posting_a, :keyword,
                        DATE '2035-03-06', TIME '09:00', TIME '10:00',
                        1.00, :session_type_id, :series_a_id, false,
                        'secretary', NULL
                    ),
                    (
                        :event_b_id, :posting_b, :keyword,
                        DATE '2035-03-05', TIME '09:00', TIME '10:00',
                        1.00, :session_type_id, :series_b_id, false,
                        'secretary', NULL
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO attendance_records (
                    id, resident_id, teaching_event_id, status, posting_code
                )
                VALUES
                    (
                        :attendance_a_id, :resident_a_id, :event_seed_a_id,
                        'submitted', :posting_a
                    ),
                    (
                        :attendance_b_id, :resident_b_id, :event_b_id,
                        'submitted', :posting_b
                    )
                """
            ),
            values,
        )
        await db.execute(
            text(
                """
                INSERT INTO external_attendance_records (
                    id, external_resident_id, teaching_event_id, status,
                    posting_code
                )
                VALUES
                    (
                        :external_attendance_a_id, :external_a_id,
                        :event_seed_a_id, 'submitted', :posting_a
                    ),
                    (
                        :external_attendance_b_id, :external_b_id,
                        :event_b_id, 'submitted', :posting_b
                    )
                """
            ),
            values,
        )
        await db.commit()

    contexts: dict[str, PolicyContext] = {}
    try:
        staff_contexts = (
            ("master", "master_id", "master_supabase_id"),
            ("pc", "pc_id", "pc_supabase_id"),
            ("pc_null", "pc_null_id", "pc_null_supabase_id"),
            ("pc_empty", "pc_empty_id", "pc_empty_supabase_id"),
            ("secretary", "secretary_id", "secretary_supabase_id"),
        )
        for label, id_key, supabase_key in staff_contexts:
            contexts[label] = await _issue_context(
                policy_harness,
                subject_type="staff",
                subject_id=values[id_key],
                supabase_user_id=values[supabase_key],
                session_generation=0,
            )
        contexts["resident"] = await _issue_context(
            policy_harness,
            subject_type="resident",
            subject_id=values["resident_a_id"],
            normalized_mcr=values["resident_a_mcr"],
            session_generation=0,
        )
        contexts["resident_peer"] = await _issue_context(
            policy_harness,
            subject_type="resident",
            subject_id=values["resident_peer_id"],
            normalized_mcr=values["resident_peer_mcr"],
            session_generation=0,
        )
        contexts["external"] = await _issue_context(
            policy_harness,
            subject_type="external_resident",
            subject_id=values["external_a_id"],
            normalized_mcr=values["external_a_mcr"],
            session_generation=0,
        )
        contexts["external_peer"] = await _issue_context(
            policy_harness,
            subject_type="external_resident",
            subject_id=values["external_peer_id"],
            normalized_mcr=values["external_peer_mcr"],
            session_generation=0,
        )
        yield PolicyMatrixSeed(contexts=contexts, values=values)
    finally:
        async with policy_harness.owner_session() as db:
            subject_ids = [
                values[key]
                for key in (
                    "master_id",
                    "pc_id",
                    "pc_null_id",
                    "pc_empty_id",
                    "secretary_id",
                    "resident_a_id",
                    "resident_b_id",
                    "resident_peer_id",
                    "external_a_id",
                    "external_b_id",
                    "external_peer_id",
                )
            ]
            await db.execute(
                text(
                    """
                    DELETE FROM app_sessions
                    WHERE subject_id = ANY(CAST(:subject_ids AS uuid[]))
                    """
                ),
                {"subject_ids": subject_ids},
            )
            for table_name, id_keys in (
                (
                    "external_attendance_records",
                    ("external_attendance_a_id", "external_attendance_b_id"),
                ),
                (
                    "attendance_records",
                    ("attendance_a_id", "attendance_b_id"),
                ),
                (
                    "teaching_events",
                    ("event_seed_a_id", "event_action_a_id", "event_b_id"),
                ),
                ("event_series", ("series_a_id", "series_b_id")),
                (
                    "teaching_name_mappings",
                    ("mapping_a_id", "mapping_b_id", "pc_mapping_id"),
                ),
                (
                    "teaching_name_catalogue",
                    ("catalogue_a_id", "catalogue_b_id", "catalogue_cross_id"),
                ),
                (
                    "teaching_names",
                    (
                        "teaching_name_a_id",
                        "teaching_name_b_id",
                        "pc_teaching_name_id",
                        "secretary_teaching_name_id",
                    ),
                ),
                ("teaching_targets", ("target_a_id", "target_b_id")),
                ("secretary_programme_pools", ("pool_a_id",)),
                ("multi_posting_rules", ("rule_a_id", "rule_b_id")),
                (
                    "external_resident_postings",
                    (
                        "external_posting_a_id",
                        "external_posting_b_id",
                        "external_posting_peer_id",
                    ),
                ),
                (
                    "resident_postings",
                    (
                        "resident_posting_a_id",
                        "resident_posting_b_id",
                        "resident_posting_peer_id",
                    ),
                ),
                (
                    "external_residents",
                    ("external_a_id", "external_b_id", "external_peer_id"),
                ),
                (
                    "residents",
                    ("resident_a_id", "resident_b_id", "resident_peer_id"),
                ),
                (
                    "users",
                    (
                        "master_id",
                        "pc_id",
                        "pc_null_id",
                        "pc_empty_id",
                        "secretary_id",
                    ),
                ),
                ("session_types", ("session_type_id",)),
                ("reporting_periods", ("period_id",)),
                ("programmes", ("programme_a_id", "programme_b_id")),
                ("posting_codes", ("posting_a_id", "posting_b_id")),
            ):
                await db.execute(
                    text(
                        f"""
                        DELETE FROM {table_name}
                        WHERE id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {"ids": [values[key] for key in id_keys]},
                )
            await db.commit()


@pytest.mark.asyncio
async def test_policy_catalogue_covers_every_application_table_without_force(
    policy_harness: RlsPostgresHarness,
) -> None:
    async with policy_harness.owner_session() as db:
        table_rows = (
            await db.execute(
                text(
                    """
                    SELECT relation.relname, relation.relrowsecurity,
                           relation.relforcerowsecurity
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname
                          = ANY(CAST(:table_names AS text[]))
                    ORDER BY relation.relname
                    """
                ),
                {"table_names": list(APPLICATION_TABLES)},
            )
        ).mappings().all()
        assert {row["relname"] for row in table_rows} == set(
            APPLICATION_TABLES
        )
        assert all(row["relrowsecurity"] is True for row in table_rows)
        assert all(row["relforcerowsecurity"] is False for row in table_rows)

        runtime_oid = await db.scalar(
            text("SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :role"),
            {"role": RUNTIME_GROUP},
        )
        assert runtime_oid is not None
        policy_rows = (
            await db.execute(
                text(
                    """
                    SELECT relation.relname, policy.polroles
                    FROM pg_catalog.pg_policy AS policy
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.oid = policy.polrelid
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname
                          = ANY(CAST(:table_names AS text[]))
                    ORDER BY relation.relname, policy.polname
                    """
                ),
                {"table_names": list(APPLICATION_TABLES)},
            )
        ).mappings().all()

    assert len(policy_rows) == 92
    assert {row["relname"] for row in policy_rows} == set(DIRECT_TABLES)
    assert all(tuple(row["polroles"]) == (runtime_oid,) for row in policy_rows)


@pytest.mark.asyncio
async def test_no_context_fails_closed_across_the_policy_surface(
    policy_harness: RlsPostgresHarness,
) -> None:
    async with policy_harness.runtime_session() as db:
        assert await db.scalar(text("SELECT current_user")) == (
            policy_harness.runtime_role
        )
        for table_name in DIRECT_TABLES:
            rows = (
                await db.scalars(
                    text(f"SELECT id FROM {table_name} LIMIT 1")
                )
            ).all()
            assert rows == [], table_name

        for table_name in HELPER_ONLY_TABLES:
            await _assert_permission_denied(
                db,
                f"SELECT id FROM {table_name} LIMIT 1",
            )

        await _assert_permission_denied(
            db,
            """
            INSERT INTO public_holidays (
                id, holiday_date, name, day_of_week, year
            )
            VALUES (
                :id, DATE '2198-01-01', 'No context', 'Thursday', 2198
            )
            """,
            {"id": uuid4()},
        )
        await db.rollback()


@pytest.mark.asyncio
async def test_master_admin_reads_global_and_scoped_rows_but_not_helper_tables(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["master"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM programmes WHERE id IN (:a, :b)",
            {
                "a": values["programme_a_id"],
                "b": values["programme_b_id"],
            },
        ) == {values["programme_a_id"], values["programme_b_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM residents WHERE id IN (:a, :b)",
            {"a": values["resident_a_id"], "b": values["resident_b_id"]},
        ) == {values["resident_a_id"], values["resident_b_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM external_residents WHERE id IN (:a, :b)",
            {"a": values["external_a_id"], "b": values["external_b_id"]},
        ) == {values["external_a_id"], values["external_b_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_targets WHERE id IN (:a, :b)",
            {"a": values["target_a_id"], "b": values["target_b_id"]},
        ) == {values["target_a_id"], values["target_b_id"]}

        for table_name in HELPER_ONLY_TABLES:
            await _assert_permission_denied(
                db,
                f"SELECT id FROM {table_name} LIMIT 1",
            )

        action_id = uuid4()
        inserted = await db.scalar(
            text(
                """
                INSERT INTO public_holidays (
                    id, holiday_date, name, day_of_week, year
                )
                VALUES (
                    :id, :holiday_date, 'RLS policy action',
                    'Monday', 2199
                )
                RETURNING id
                """
            ),
            {"id": action_id, "holiday_date": values["holiday_date"]},
        )
        assert inserted == action_id
        updated = await db.scalar(
            text(
                """
                UPDATE public_holidays
                SET name = 'RLS policy action updated'
                WHERE id = :id
                RETURNING name
                """
            ),
            {"id": action_id},
        )
        assert updated == "RLS policy action updated"
        deleted = await db.scalar(
            text(
                """
                DELETE FROM public_holidays
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": action_id},
        )
        assert deleted == action_id


@pytest.mark.asyncio
async def test_programme_coordinator_scope_and_safe_rule_crud(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["pc"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM residents WHERE id IN (:a, :b)",
            {"a": values["resident_a_id"], "b": values["resident_b_id"]},
        ) == {values["resident_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_targets WHERE id IN (:a, :b)",
            {"a": values["target_a_id"], "b": values["target_b_id"]},
        ) == {values["target_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM multi_posting_rules WHERE id IN (:a, :b)",
            {"a": values["rule_a_id"], "b": values["rule_b_id"]},
        ) == {values["rule_a_id"]}
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM external_resident_postings
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["external_posting_a_id"],
                "b": values["external_posting_b_id"],
            },
        ) == {values["external_posting_a_id"]}

        action_id = uuid4()
        inserted = await db.scalar(
            text(
                """
                INSERT INTO multi_posting_rules (
                    id, programme_code, posting_code_1, posting_code_2,
                    rule_type, combined_label
                )
                VALUES (
                    :id, :programme_code, :posting_a, :posting_b,
                    'half_month', 'PC action'
                )
                RETURNING id
                """
            ),
            {
                "id": action_id,
                "programme_code": values["programme_a"],
                "posting_a": values["posting_a"],
                "posting_b": values["posting_b"],
            },
        )
        assert inserted == action_id
        updated = await db.scalar(
            text(
                """
                UPDATE multi_posting_rules
                SET combined_label = 'PC action updated'
                WHERE id = :id
                RETURNING combined_label
                """
            ),
            {"id": action_id},
        )
        assert updated == "PC action updated"
        deleted = await db.scalar(
            text(
                """
                DELETE FROM multi_posting_rules
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": action_id},
        )
        assert deleted == action_id

        await _assert_permission_denied(
            db,
            """
            INSERT INTO multi_posting_rules (
                id, programme_code, posting_code_1, posting_code_2,
                rule_type, combined_label
            )
            VALUES (
                :id, :programme_code, :posting_a, :posting_b,
                'half_month', 'Out of scope'
            )
            """,
            {
                "id": uuid4(),
                "programme_code": values["programme_b"],
                "posting_a": values["posting_a"],
                "posting_b": values["posting_b"],
            },
        )
        hidden_update = await db.execute(
            text(
                """
                UPDATE multi_posting_rules
                SET combined_label = 'Must stay hidden'
                WHERE id = :id
                """
            ),
            {"id": values["rule_b_id"]},
        )
        assert hidden_update.rowcount == 0
        hidden_delete = await db.execute(
            text("DELETE FROM multi_posting_rules WHERE id = :id"),
            {"id": values["rule_b_id"]},
        )
        assert hidden_delete.rowcount == 0


@pytest.mark.asyncio
async def test_evolved_teaching_name_pools_and_mappings_stay_role_scoped(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values

    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["master"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_names WHERE id IN (:a, :b)",
            {
                "a": values["teaching_name_a_id"],
                "b": values["teaching_name_b_id"],
            },
        ) == {values["teaching_name_a_id"], values["teaching_name_b_id"]}
        locked_name = await db.execute(
            text(
                """
                UPDATE teaching_names
                SET revision = revision + 1
                WHERE id = :id
                """
            ),
            {"id": values["teaching_name_a_id"]},
        )
        assert locked_name.rowcount == 0
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_name_mappings WHERE id IN (:a, :b)",
            {"a": values["mapping_a_id"], "b": values["mapping_b_id"]},
        ) == {values["mapping_a_id"], values["mapping_b_id"]}
        locked_mapping = await db.execute(
            text(
                """
                UPDATE teaching_name_mappings
                SET revision = 2
                WHERE id = :id
                """
            ),
            {"id": values["mapping_a_id"]},
        )
        assert locked_mapping.rowcount == 0
        await _assert_permission_denied(
            db,
            """
            INSERT INTO teaching_name_mappings (
                id, teaching_name_id, reporting_period_id, programme_code,
                posting_code, r_year, teaching_target_id
            )
            VALUES (
                :id, :teaching_name_id, :period_id, :programme_code,
                :posting_code, 'R2', NULL
            )
            """,
            {
                "id": uuid4(),
                "teaching_name_id": values["teaching_name_a_id"],
                "period_id": values["period_id"],
                "programme_code": values["programme_a"],
                "posting_code": values["posting_a"],
            },
        )
        locked_mapping_delete = await db.execute(
            text("DELETE FROM teaching_name_mappings WHERE id = :id"),
            {"id": values["mapping_a_id"]},
        )
        assert locked_mapping_delete.rowcount == 0

    pc_name_id = values["pc_teaching_name_id"]
    pc_mapping_id = values["pc_mapping_id"]
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["pc"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_names WHERE id IN (:a, :b)",
            {
                "a": values["teaching_name_a_id"],
                "b": values["teaching_name_b_id"],
            },
        ) == {values["teaching_name_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_name_mappings WHERE id IN (:a, :b)",
            {"a": values["mapping_a_id"], "b": values["mapping_b_id"]},
        ) == {values["mapping_a_id"]}

        assert await db.scalar(
            text(
                """
                INSERT INTO teaching_names (
                    id, reporting_period_id, programme_code, display_name,
                    normalized_name, is_active
                )
                VALUES (
                    :id, :period_id, :programme_code, 'PC Teaching Name',
                    'pc teaching name', false
                )
                RETURNING id
                """
            ),
            {
                "id": pc_name_id,
                "period_id": values["period_id"],
                "programme_code": values["programme_a"],
            },
        ) == pc_name_id
        assert await db.scalar(
            text(
                """
                UPDATE teaching_names
                SET is_active = false
                WHERE id = :id
                RETURNING is_active
                """
            ),
            {"id": pc_name_id},
        ) is False
        assert await db.scalar(
            text(
                """
                INSERT INTO teaching_name_mappings (
                    id, teaching_name_id, reporting_period_id, programme_code,
                    posting_code, r_year, teaching_target_id
                )
                VALUES (
                    :id, :teaching_name_id, :period_id, :programme_code,
                    :posting_code, 'R1', :teaching_target_id
                )
                RETURNING id
                """
            ),
            {
                "id": pc_mapping_id,
                "teaching_name_id": pc_name_id,
                "period_id": values["period_id"],
                "programme_code": values["programme_a"],
                "posting_code": values["posting_a"],
                "teaching_target_id": values["target_a_id"],
            },
        ) == pc_mapping_id
        assert await db.scalar(
            text(
                """
                UPDATE teaching_name_mappings
                SET revision = 2
                WHERE id = :id
                RETURNING revision
                """
            ),
            {"id": pc_mapping_id},
        ) == 2
        await _assert_permission_denied(
            db,
            """
            INSERT INTO teaching_names (
                id, reporting_period_id, programme_code, display_name,
                normalized_name
            )
            VALUES (
                :id, :period_id, :programme_code, 'Out of scope',
                'out of scope'
            )
            """,
            {
                "id": uuid4(),
                "period_id": values["period_id"],
                "programme_code": values["programme_b"],
            },
        )
        await _assert_permission_denied(
            db,
            """
            INSERT INTO teaching_name_mappings (
                id, teaching_name_id, reporting_period_id, programme_code,
                posting_code, r_year, teaching_target_id
            )
            VALUES (
                :id, :teaching_name_id, :period_id, :programme_code,
                :posting_code, 'R1', :teaching_target_id
            )
            """,
            {
                "id": uuid4(),
                "teaching_name_id": values["teaching_name_b_id"],
                "period_id": values["period_id"],
                "programme_code": values["programme_b"],
                "posting_code": values["posting_b"],
                "teaching_target_id": values["target_b_id"],
            },
        )
        hidden_mapping = await db.execute(
            text(
                """
                UPDATE teaching_name_mappings
                SET revision = 3
                WHERE id = :id
                """
            ),
            {"id": values["mapping_b_id"]},
        )
        assert hidden_mapping.rowcount == 0
        assert await db.scalar(
            text(
                """
                DELETE FROM teaching_names
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": pc_name_id},
        ) == pc_name_id
        assert await db.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM teaching_name_mappings
                WHERE id = :id
                """
            ),
            {"id": pc_mapping_id},
        ) == 0
        try:
            used_delete = await db.execute(
                text("DELETE FROM teaching_names WHERE id = :id"),
                {"id": values["teaching_name_a_id"]},
            )
        except DBAPIError as exc:
            assert getattr(exc.orig, "sqlstate", None) == "42501"
        else:
            assert used_delete.rowcount == 0

    for context_name in ("pc_null", "pc_empty", "resident"):
        async with _runtime_context(
            policy_harness,
            policy_seed.contexts[context_name],
        ) as db:
            assert await _scalar_set(
                db,
                "SELECT id FROM teaching_names WHERE id IN (:a, :b)",
                {
                    "a": values["teaching_name_a_id"],
                    "b": values["teaching_name_b_id"],
                },
            ) == set()
            assert await _scalar_set(
                db,
                "SELECT id FROM teaching_name_mappings WHERE id IN (:a, :b)",
                {"a": values["mapping_a_id"], "b": values["mapping_b_id"]},
            ) == set()

    secretary_name_id = values["secretary_teaching_name_id"]
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["secretary"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_names WHERE id IN (:a, :b)",
            {
                "a": values["teaching_name_a_id"],
                "b": values["teaching_name_b_id"],
            },
        ) == set()
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_name_mappings WHERE id IN (:a, :b)",
            {"a": values["mapping_a_id"], "b": values["mapping_b_id"]},
        ) == set()
        await _assert_permission_denied(
            db,
            """
            INSERT INTO teaching_names (
                id, reporting_period_id, programme_code, display_name,
                normalized_name
            )
            VALUES (
                :id, :period_id, :programme_code, 'Blocked secretary name',
                'blocked secretary name'
            )
            """,
            {
                "id": secretary_name_id,
                "period_id": values["period_id"],
                "programme_code": values["programme_a"],
            },
        )

    async with policy_harness.owner_session() as db:
        assert await db.scalar(
            text(
                """
                UPDATE secretary_programme_pools
                SET can_manage_teaching_names = true
                WHERE id = :id
                RETURNING can_manage_teaching_names
                """
            ),
            {"id": values["pool_a_id"]},
        ) is True
        await db.commit()

    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["secretary"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_names WHERE id IN (:a, :b)",
            {
                "a": values["teaching_name_a_id"],
                "b": values["teaching_name_b_id"],
            },
        ) == {values["teaching_name_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM teaching_name_mappings WHERE id IN (:a, :b)",
            {"a": values["mapping_a_id"], "b": values["mapping_b_id"]},
        ) == set()
        assert await db.scalar(
            text(
                """
                INSERT INTO teaching_names (
                    id, reporting_period_id, programme_code, display_name,
                    normalized_name
                )
                VALUES (
                    :id, :period_id, :programme_code, 'Secretary Teaching Name',
                    'secretary teaching name'
                )
                RETURNING id
                """
            ),
            {
                "id": secretary_name_id,
                "period_id": values["period_id"],
                "programme_code": values["programme_a"],
            },
        ) == secretary_name_id
        await _assert_permission_denied(
            db,
            """
            INSERT INTO teaching_name_mappings (
                id, teaching_name_id, reporting_period_id, programme_code,
                posting_code, r_year, teaching_target_id
            )
            VALUES (
                :id, :teaching_name_id, :period_id, :programme_code,
                :posting_code, 'R2', NULL
            )
            """,
            {
                "id": uuid4(),
                "teaching_name_id": secretary_name_id,
                "period_id": values["period_id"],
                "programme_code": values["programme_a"],
                "posting_code": values["posting_a"],
            },
        )
        secretary_mapping_update = await db.execute(
            text(
                """
                UPDATE teaching_name_mappings
                SET revision = 2
                WHERE id = :id
                """
            ),
            {"id": values["mapping_a_id"]},
        )
        assert secretary_mapping_update.rowcount == 0
        secretary_mapping_delete = await db.execute(
            text("DELETE FROM teaching_name_mappings WHERE id = :id"),
            {"id": values["mapping_a_id"]},
        )
        assert secretary_mapping_delete.rowcount == 0
        assert await db.scalar(
            text(
                """
                DELETE FROM teaching_names
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": secretary_name_id},
        ) == secretary_name_id
        try:
            used_delete = await db.execute(
                text("DELETE FROM teaching_names WHERE id = :id"),
                {"id": values["teaching_name_a_id"]},
            )
        except DBAPIError as exc:
            assert getattr(exc.orig, "sqlstate", None) == "42501"
        else:
            assert used_delete.rowcount == 0


@pytest.mark.asyncio
async def test_programme_coordinator_can_join_in_scope_external_identity_rows(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    """Scoped reporting must not lose an allowed row at the identity join."""

    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["pc"],
    ) as db:
        visible_external_ids = await _scalar_set(
            db,
            """
            SELECT external_resident.id
            FROM external_residents AS external_resident
            JOIN external_resident_postings AS external_posting
              ON external_posting.external_resident_id
                  = external_resident.id
            WHERE external_posting.programme_code = :programme_code
              AND external_resident.id IN (:a, :b)
            """,
            {
                "programme_code": values["programme_a"],
                "a": values["external_a_id"],
                "b": values["external_b_id"],
            },
        )
        assert visible_external_ids == {values["external_a_id"]}


@pytest.mark.asyncio
async def test_null_and_empty_programme_scopes_fail_closed(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    for context_name in ("pc_null", "pc_empty"):
        async with _runtime_context(
            policy_harness,
            policy_seed.contexts[context_name],
        ) as db:
            assert await _scalar_set(
                db,
                "SELECT id FROM residents WHERE id IN (:a, :b)",
                {
                    "a": values["resident_a_id"],
                    "b": values["resident_b_id"],
                },
            ) == set()
            assert await _scalar_set(
                db,
                "SELECT id FROM teaching_targets WHERE id IN (:a, :b)",
                {"a": values["target_a_id"], "b": values["target_b_id"]},
            ) == set()
            assert await _scalar_set(
                db,
                "SELECT id FROM multi_posting_rules WHERE id IN (:a, :b)",
                {"a": values["rule_a_id"], "b": values["rule_b_id"]},
            ) == set()
            assert await _scalar_set(
                db,
                """
                SELECT id
                FROM external_resident_postings
                WHERE id IN (:a, :b)
                """,
                {
                    "a": values["external_posting_a_id"],
                    "b": values["external_posting_b_id"],
                },
            ) == set()
            await _assert_permission_denied(
                db,
                """
                INSERT INTO multi_posting_rules (
                    id, programme_code, posting_code_1, posting_code_2,
                    rule_type
                )
                VALUES (
                    :id, :programme_code, :posting_a, :posting_b,
                    'half_month'
                )
                """,
                {
                    "id": uuid4(),
                    "programme_code": values["programme_a"],
                    "posting_a": values["posting_a"],
                    "posting_b": values["posting_b"],
                },
            )


@pytest.mark.asyncio
async def test_secretary_events_stay_posting_bound_and_catalogue_follows_pool(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["secretary"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM event_series WHERE id IN (:a, :b)",
            {"a": values["series_a_id"], "b": values["series_b_id"]},
        ) == {values["series_a_id"]}
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM teaching_events
            WHERE id IN (:seed_a, :action_a, :b)
            """,
            {
                "seed_a": values["event_seed_a_id"],
                "action_a": values["event_action_a_id"],
                "b": values["event_b_id"],
            },
        ) == {values["event_seed_a_id"], values["event_action_a_id"]}

        action_id = uuid4()
        inserted = await db.scalar(
            text(
                """
                INSERT INTO event_series (
                    id, posting_code, recurrence_pattern,
                    recurrence_interval
                )
                VALUES (:id, :posting_code, 'weekly', 1)
                RETURNING id
                """
            ),
            {"id": action_id, "posting_code": values["posting_a"]},
        )
        assert inserted == action_id
        updated = await db.scalar(
            text(
                """
                UPDATE event_series
                SET recurrence_interval = 2
                WHERE id = :id
                RETURNING recurrence_interval
                """
            ),
            {"id": action_id},
        )
        assert updated == 2
        deleted = await db.scalar(
            text(
                """
                DELETE FROM event_series
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": action_id},
        )
        assert deleted == action_id
        await _assert_permission_denied(
            db,
            """
            INSERT INTO event_series (
                id, posting_code, recurrence_pattern,
                recurrence_interval
            )
            VALUES (:id, :posting_code, 'weekly', 1)
            """,
            {"id": uuid4(), "posting_code": values["posting_b"]},
        )
        hidden_update = await db.execute(
            text(
                """
                UPDATE event_series
                SET recurrence_interval = 3
                WHERE id = :id
                """
            ),
            {"id": values["series_b_id"]},
        )
        assert hidden_update.rowcount == 0
        hidden_delete = await db.execute(
            text("DELETE FROM event_series WHERE id = :id"),
            {"id": values["series_b_id"]},
        )
        assert hidden_delete.rowcount == 0

        visible_catalogue_ids = await _scalar_set(
            db,
            """
            SELECT id
            FROM teaching_name_catalogue
            WHERE id IN (:own_id, :other_programme_id, :cross_posting_id)
            """,
            {
                "own_id": values["catalogue_a_id"],
                "other_programme_id": values["catalogue_b_id"],
                "cross_posting_id": values["catalogue_cross_id"],
            },
        )
        assert visible_catalogue_ids == {
            values["catalogue_a_id"],
            values["catalogue_cross_id"],
        }


@pytest.mark.asyncio
async def test_secretary_own_posting_resident_rows_are_visible(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    """Own-posting resident roster reads must not be filtered out by joins."""

    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["secretary"],
    ) as db:
        resident_ids = await _scalar_set(
            db,
            """
            SELECT id
            FROM residents
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["resident_a_id"],
                "b": values["resident_b_id"],
            },
        )
        assert resident_ids == {values["resident_a_id"]}
        resident_posting_ids = await _scalar_set(
            db,
            """
            SELECT id
            FROM resident_postings
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["resident_posting_a_id"],
                "b": values["resident_posting_b_id"],
            },
        )
        assert resident_posting_ids == {values["resident_posting_a_id"]}


@pytest.mark.asyncio
async def test_secretary_own_posting_attendance_rows_are_visible(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    """Secretary event guards must retain linked Non-NHG attendance visibility."""

    values = policy_seed.values
    external_only_event_id = uuid4()
    external_only_attendance_id = uuid4()
    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        end_time, duration_hours, is_adhoc, created_by_role,
                        teaching_name_id
                    )
                    VALUES (
                        :event_id, :posting_code, :teaching_name,
                        DATE '2035-03-10', TIME '09:00', TIME '10:00',
                        1.00, false, 'secretary', :teaching_name_id
                    )
                    """
                ),
                {
                    "event_id": external_only_event_id,
                    "posting_code": values["posting_a"],
                    "teaching_name": values["keyword"],
                    "teaching_name_id": values["teaching_name_a_id"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO external_attendance_records (
                        id, external_resident_id, teaching_event_id, status,
                        posting_code
                    )
                    VALUES (
                        :attendance_id, :external_resident_id, :event_id,
                        'submitted', :posting_code
                    )
                    """
                ),
                {
                    "attendance_id": external_only_attendance_id,
                    "external_resident_id": values["external_a_id"],
                    "event_id": external_only_event_id,
                    "posting_code": values["posting_a"],
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            attendance_ids = await _scalar_set(
                db,
                """
                SELECT id
                FROM attendance_records
                WHERE id IN (:a, :b)
                """,
                {
                    "a": values["attendance_a_id"],
                    "b": values["attendance_b_id"],
                },
            )
            assert attendance_ids == {values["attendance_a_id"]}
            external_attendance_ids = await _scalar_set(
                db,
                """
                SELECT id
                FROM external_attendance_records
                WHERE id IN (:a, :b, :external_only)
                """,
                {
                    "a": values["external_attendance_a_id"],
                    "b": values["external_attendance_b_id"],
                    "external_only": external_only_attendance_id,
                },
            )
            assert external_attendance_ids == {
                values["external_attendance_a_id"],
                external_only_attendance_id,
            }
            with pytest.raises(ApiError) as attendance_guard:
                await secretary_events.delete_teaching_event(
                    db,
                    posting_code=values["posting_a"],
                    event_id=external_only_event_id,
                )
            assert attendance_guard.value.status_code == 409
            assert "attendance exists" in attendance_guard.value.detail
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM external_attendance_records
                    WHERE id = :attendance_id
                    """
                ),
                {"attendance_id": external_only_attendance_id},
            )
            await db.execute(
                text(
                    "DELETE FROM teaching_events WHERE id = :event_id"),
                {"event_id": external_only_event_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_native_resident_owns_only_native_rows_and_attendance_mutation(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["resident"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM residents WHERE id IN (:a, :b)",
            {"a": values["resident_a_id"], "b": values["resident_b_id"]},
        ) == {values["resident_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM resident_postings WHERE id IN (:a, :b)",
            {
                "a": values["resident_posting_a_id"],
                "b": values["resident_posting_b_id"],
            },
        ) == {values["resident_posting_a_id"]}
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM teaching_name_catalogue
            WHERE id IN (:own, :other, :cross)
            """,
            {
                "own": values["catalogue_a_id"],
                "other": values["catalogue_b_id"],
                "cross": values["catalogue_cross_id"],
            },
        ) == {values["catalogue_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM external_residents WHERE id IN (:a, :b)",
            {"a": values["external_a_id"], "b": values["external_b_id"]},
        ) == set()
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM external_attendance_records
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["external_attendance_a_id"],
                "b": values["external_attendance_b_id"],
            },
        ) == set()
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM teaching_events
            WHERE id IN (:seed_a, :action_a, :b)
            """,
            {
                "seed_a": values["event_seed_a_id"],
                "action_a": values["event_action_a_id"],
                "b": values["event_b_id"],
            },
        ) == {values["event_seed_a_id"], values["event_action_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM attendance_records WHERE id IN (:a, :b)",
            {"a": values["attendance_a_id"], "b": values["attendance_b_id"]},
        ) == {values["attendance_a_id"]}

        action_id = uuid4()
        inserted = await db.scalar(
            text(
                """
                INSERT INTO attendance_records (
                    id, resident_id, teaching_event_id, status, posting_code,
                    submitted_at, created_at, updated_at
                )
                VALUES (
                    :id, :resident_id, :event_id, 'submitted',
                    :posting_code,
                    TIMESTAMPTZ '2000-01-01 00:00:00+00',
                    TIMESTAMPTZ '2000-01-01 00:00:00+00',
                    TIMESTAMPTZ '2000-01-01 00:00:00+00'
                )
                RETURNING id
                """
            ),
            {
                "id": action_id,
                "resident_id": values["resident_a_id"],
                "event_id": values["event_action_a_id"],
                "posting_code": values["posting_a"],
            },
        )
        assert inserted == action_id
        assert await db.scalar(
            text(
                """
                SELECT
                    submitted_at = created_at
                    AND created_at = updated_at
                    AND submitted_at
                        > TIMESTAMPTZ '2000-01-01 00:00:00+00'
                FROM attendance_records
                WHERE id = :id
                """
            ),
            {"id": action_id},
        ) is True
        updated = await db.scalar(
            text(
                """
                UPDATE attendance_records
                SET status = 'removed'
                WHERE id = :id
                RETURNING status
                """
            ),
            {"id": action_id},
        )
        assert updated == "removed"
        await _assert_permission_denied(
            db,
            """
            INSERT INTO attendance_records (
                id, resident_id, teaching_event_id, status, posting_code
            )
            VALUES (
                :id, :resident_id, :event_id, 'submitted', :posting_code
            )
            """,
            {
                "id": uuid4(),
                "resident_id": values["resident_b_id"],
                "event_id": values["event_b_id"],
                "posting_code": values["posting_b"],
            },
        )
        hidden_update = await db.execute(
            text(
                """
                UPDATE attendance_records
                SET status = 'flagged'
                WHERE id = :id
                """
            ),
            {"id": values["attendance_b_id"]},
        )
        assert hidden_update.rowcount == 0
        denied_delete = await db.execute(
            text("DELETE FROM attendance_records WHERE id = :id"),
            {"id": action_id},
        )
        assert denied_delete.rowcount == 0
        assert await db.scalar(
            text("SELECT status FROM attendance_records WHERE id = :id"),
            {"id": action_id},
        ) == "removed"


@pytest.mark.asyncio
async def test_external_resident_owns_only_external_rows_and_attendance_mutation(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    async with _runtime_context(
        policy_harness,
        policy_seed.contexts["external"],
    ) as db:
        assert await _scalar_set(
            db,
            "SELECT id FROM external_residents WHERE id IN (:a, :b)",
            {"a": values["external_a_id"], "b": values["external_b_id"]},
        ) == {values["external_a_id"]}
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM external_resident_postings
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["external_posting_a_id"],
                "b": values["external_posting_b_id"],
            },
        ) == {values["external_posting_a_id"]}
        assert await _scalar_set(
            db,
            "SELECT id FROM residents WHERE id IN (:a, :b)",
            {"a": values["resident_a_id"], "b": values["resident_b_id"]},
        ) == set()
        assert await _scalar_set(
            db,
            "SELECT id FROM attendance_records WHERE id IN (:a, :b)",
            {"a": values["attendance_a_id"], "b": values["attendance_b_id"]},
        ) == set()
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM teaching_events
            WHERE id IN (:seed_a, :action_a, :b)
            """,
            {
                "seed_a": values["event_seed_a_id"],
                "action_a": values["event_action_a_id"],
                "b": values["event_b_id"],
            },
        ) == {values["event_seed_a_id"], values["event_action_a_id"]}
        assert await _scalar_set(
            db,
            """
            SELECT id
            FROM external_attendance_records
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["external_attendance_a_id"],
                "b": values["external_attendance_b_id"],
            },
        ) == {values["external_attendance_a_id"]}

        action_id = uuid4()
        inserted = await db.scalar(
            text(
                """
                INSERT INTO external_attendance_records (
                    id, external_resident_id, teaching_event_id,
                    status, posting_code, submitted_at, created_at, updated_at
                )
                VALUES (
                    :id, :external_resident_id, :event_id,
                    'submitted', :posting_code,
                    TIMESTAMPTZ '2000-01-01 00:00:00+00',
                    TIMESTAMPTZ '2000-01-01 00:00:00+00',
                    TIMESTAMPTZ '2000-01-01 00:00:00+00'
                )
                RETURNING id
                """
            ),
            {
                "id": action_id,
                "external_resident_id": values["external_a_id"],
                "event_id": values["event_action_a_id"],
                "posting_code": values["posting_a"],
            },
        )
        assert inserted == action_id
        assert await db.scalar(
            text(
                """
                SELECT
                    submitted_at = created_at
                    AND created_at = updated_at
                    AND submitted_at
                        > TIMESTAMPTZ '2000-01-01 00:00:00+00'
                FROM external_attendance_records
                WHERE id = :id
                """
            ),
            {"id": action_id},
        ) is True
        updated = await db.scalar(
            text(
                """
                UPDATE external_attendance_records
                SET status = 'removed'
                WHERE id = :id
                RETURNING status
                """
            ),
            {"id": action_id},
        )
        assert updated == "removed"
        await _assert_permission_denied(
            db,
            """
            INSERT INTO external_attendance_records (
                id, external_resident_id, teaching_event_id,
                status, posting_code
            )
            VALUES (
                :id, :external_resident_id, :event_id,
                'submitted', :posting_code
            )
            """,
            {
                "id": uuid4(),
                "external_resident_id": values["external_b_id"],
                "event_id": values["event_b_id"],
                "posting_code": values["posting_b"],
            },
        )
        hidden_update = await db.execute(
            text(
                """
                UPDATE external_attendance_records
                SET status = 'flagged'
                WHERE id = :id
                """
            ),
            {"id": values["external_attendance_b_id"]},
        )
        assert hidden_update.rowcount == 0
        denied_delete = await db.execute(
            text("DELETE FROM external_attendance_records WHERE id = :id"),
            {"id": action_id},
        )
        assert denied_delete.rowcount == 0
        assert await db.scalar(
            text(
                """
                SELECT status
                FROM external_attendance_records
                WHERE id = :id
                """
            ),
            {"id": action_id},
        ) == "removed"


@pytest.mark.asyncio
async def test_phase_g_persisted_source_rls_isolation_and_submission_matrix(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    """Phase G must enforce source identity under restricted runtime roles."""

    values = policy_seed.values
    global_session_type_id = uuid4()
    wrong_pool_event_id = uuid4()
    global_event_id = uuid4()
    wrong_external_attendance_id = uuid4()
    event_parameters = {
        **values,
        "global_session_type_id": global_session_type_id,
        "wrong_pool_event_id": wrong_pool_event_id,
        "global_event_id": global_event_id,
        "wrong_external_attendance_id": wrong_external_attendance_id,
    }
    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO global_session_types (
                        id, name, duration_hours, is_active
                    )
                    VALUES (:global_session_type_id, 'Phase G global source', 1.00, true)
                    """
                ),
                event_parameters,
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        end_time, duration_hours, session_type_id, series_id,
                        is_adhoc, created_by_role, teaching_name_id,
                        global_session_type_id
                    )
                    VALUES
                        (
                            :wrong_pool_event_id, :posting_a, :keyword,
                            DATE '2035-03-07', TIME '09:00', TIME '10:00',
                            1.00, :session_type_id, :series_a_id, false,
                            'secretary', :teaching_name_b_id, NULL
                        ),
                        (
                            :global_event_id, :posting_a, 'Phase G global source',
                            DATE '2035-03-08', TIME '09:00', TIME '10:00',
                            1.00, NULL, :series_a_id, false,
                            'secretary', NULL, :global_session_type_id
                        )
                    """
                ),
                event_parameters,
            )
            await db.execute(
                text(
                    """
                    INSERT INTO external_attendance_records (
                        id, external_resident_id, teaching_event_id, status,
                        posting_code
                    )
                    VALUES (
                        :wrong_external_attendance_id, :external_a_id,
                        :wrong_pool_event_id, 'submitted', :posting_a
                    )
                    """
                ),
                event_parameters,
            )
            with pytest.raises(DBAPIError) as malformed_source:
                async with db.begin_nested():
                    await db.execute(
                        text(
                            """
                            INSERT INTO teaching_events (
                                id, posting_code, teaching_name, event_date,
                                start_time, end_time, duration_hours,
                                session_type_id, is_adhoc, created_by_role,
                                teaching_name_id, global_session_type_id
                            )
                            VALUES (
                                :id, :posting_a, :keyword, DATE '2035-03-09',
                                TIME '09:00', TIME '10:00', 1.00,
                                :session_type_id, false, 'secretary',
                                :teaching_name_a_id, :global_session_type_id
                            )
                            """
                        ),
                        {**event_parameters, "id": uuid4()},
                    )
            assert _sqlstate(malformed_source.value) == "23514"
            await db.commit()

        scoped_event_parameters = {
            "allowed": values["event_seed_a_id"],
            "wrong": wrong_pool_event_id,
            "global": global_event_id,
            "external_allowed": values["external_attendance_a_id"],
            "external_wrong": wrong_external_attendance_id,
        }
        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            assert await _scalar_set(
                db,
                """
                SELECT id
                FROM teaching_events
                WHERE id IN (:allowed, :wrong, :global)
                """,
                scoped_event_parameters,
            ) == {values["event_seed_a_id"], global_event_id}
            assert await _scalar_set(
                db,
                """
                SELECT id
                FROM external_attendance_records
                WHERE id IN (:external_allowed, :external_wrong)
                """,
                scoped_event_parameters,
            ) == {values["external_attendance_a_id"]}
            assert await db.scalar(
                text(
                    """
                    SELECT programme_code
                    FROM mata_rls.scheduled_event_source_scope(:allowed)
                    """
                ),
                {"allowed": values["event_seed_a_id"]},
            ) == values["programme_a"]
            assert await db.scalar(
                text(
                    """
                    SELECT programme_code
                    FROM mata_rls.scheduled_event_source_scope(:wrong)
                    """
                ),
                {"wrong": wrong_pool_event_id},
            ) is None

        for context_name in ("resident", "external"):
            async with _runtime_context(
                policy_harness,
                policy_seed.contexts[context_name],
            ) as db:
                assert await _scalar_set(
                    db,
                    """
                    SELECT id
                    FROM teaching_events
                    WHERE id IN (:allowed, :wrong, :global)
                    """,
                    scoped_event_parameters,
                ) == {values["event_seed_a_id"], global_event_id}
                assert await db.scalar(
                    text(
                        """
                        SELECT programme_code
                        FROM mata_rls.scheduled_event_source_scope(:allowed)
                        """
                    ),
                    {"allowed": values["event_seed_a_id"]},
                ) == values["programme_a"]
                assert await db.scalar(
                    text(
                        """
                        SELECT programme_code
                        FROM mata_rls.scheduled_event_source_scope(:wrong)
                        """
                    ),
                    {"wrong": wrong_pool_event_id},
                ) is None
                assert await db.scalar(
                    text(
                        """
                        SELECT programme_code
                        FROM mata_rls.scheduled_event_source_scope(:global)
                        """
                    ),
                    {"global": global_event_id},
                ) is None
                if context_name == "resident":
                    allowed = await db.scalar(
                        text(
                            """
                            SELECT mata_rls.can_submit_native_attendance(
                                :resident_id, :event_id
                            )
                            """
                        ),
                        {
                            "resident_id": values["resident_a_id"],
                            "event_id": values["event_seed_a_id"],
                        },
                    )
                    wrong = await db.scalar(
                        text(
                            """
                            SELECT mata_rls.can_submit_native_attendance(
                                :resident_id, :event_id
                            )
                            """
                        ),
                        {
                            "resident_id": values["resident_a_id"],
                            "event_id": wrong_pool_event_id,
                        },
                    )
                    global_allowed = await db.scalar(
                        text(
                            """
                            SELECT mata_rls.can_submit_native_attendance(
                                :resident_id, :event_id
                            )
                            """
                        ),
                        {
                            "resident_id": values["resident_a_id"],
                            "event_id": global_event_id,
                        },
                    )
                else:
                    allowed = await db.scalar(
                        text(
                            """
                            SELECT mata_rls.can_submit_external_attendance(
                                :external_resident_id, :event_id
                            )
                            """
                        ),
                        {
                            "external_resident_id": values["external_a_id"],
                            "event_id": values["event_seed_a_id"],
                        },
                    )
                    wrong = await db.scalar(
                        text(
                            """
                            SELECT mata_rls.can_submit_external_attendance(
                                :external_resident_id, :event_id
                            )
                            """
                        ),
                        {
                            "external_resident_id": values["external_a_id"],
                            "event_id": wrong_pool_event_id,
                        },
                    )
                    global_allowed = await db.scalar(
                        text(
                            """
                            SELECT mata_rls.can_submit_external_attendance(
                                :external_resident_id, :event_id
                            )
                            """
                        ),
                        {
                            "external_resident_id": values["external_a_id"],
                            "event_id": global_event_id,
                        },
                    )
                assert allowed is True
                assert wrong is False
                assert global_allowed is True
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM external_attendance_records
                    WHERE id = :wrong_external_attendance_id
                    """
                ),
                {"wrong_external_attendance_id": wrong_external_attendance_id},
            )
            await db.execute(
                text(
                    """
                    DELETE FROM teaching_events
                    WHERE id IN (:wrong_pool_event_id, :global_event_id)
                    """
                ),
                {
                    "wrong_pool_event_id": wrong_pool_event_id,
                    "global_event_id": global_event_id,
                },
            )
            await db.execute(
                text("DELETE FROM global_session_types WHERE id = :id"),
                {"id": global_session_type_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_atomic_adhoc_and_scheduled_submission_share_canonical_lock(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = policy_seed.values
    event_date = date(2035, 3, 6)
    scheduled_task: asyncio.Task[dict[str, Any]] | None = None
    waiter_pid_ready = asyncio.Event()
    waiter_pid: int | None = None
    waiter_engine = create_async_engine(
        policy_harness.runtime_engine.url,
        poolclass=NullPool,
    )
    waiter_harness = RlsPostgresHarness(
        owner_engine=policy_harness.owner_engine,
        runtime_engine=waiter_engine,
        auth_engine=policy_harness.auth_engine,
        runtime_role=policy_harness.runtime_role,
        auth_role=policy_harness.auth_role,
        revision=policy_harness.revision,
    )
    monkeypatch.setattr(
        resident_submission,
        "invalidate_resident_caches",
        lambda **_scope: None,
    )

    async def submit_scheduled() -> dict[str, Any]:
        nonlocal waiter_pid
        async with _runtime_context(
            waiter_harness,
            policy_seed.contexts["resident"],
        ) as scheduled_db:
            waiter_pid = int(
                await scheduled_db.scalar(text("SELECT pg_backend_pid()"))
            )
            waiter_pid_ready.set()
            return await resident_submission.submit_attendance(
                scheduled_db,
                resident_id=values["resident_a_id"],
                event_ids=[values["event_action_a_id"]],
                today=event_date,
            )

    try:
        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as helper_db:
            holder_pid = int(
                await helper_db.scalar(text("SELECT pg_backend_pid()"))
            )
            created = (
                await helper_db.execute(
                    text(
                        """
                        SELECT event_id, attendance_id
                        FROM mata_rls.create_adhoc_attendance(
                            :posting_code,
                            :attended_posting_code,
                            'Department/Programme Teaching [1h]',
                            'Department/Programme Teaching [1h]',
                            NULL,
                            :event_date,
                            TIME '10:00',
                            TIME '11:00',
                            1.00,
                            NULL::uuid
                        )
                        """
                    ),
                    {
                        "posting_code": values["posting_a"],
                        "attended_posting_code": values["posting_a"],
                        "event_date": event_date,
                    },
                )
            ).mappings().one()
            assert created["event_id"] is not None
            assert created["attendance_id"] is not None

            scheduled_task = asyncio.create_task(submit_scheduled())
            await asyncio.wait_for(waiter_pid_ready.wait(), timeout=10)
            assert waiter_pid is not None
            await _wait_for_matching_advisory_lock(
                policy_harness,
                holder_pid=holder_pid,
                waiter_pid=waiter_pid,
                blocked_task=scheduled_task,
            )
            assert not scheduled_task.done()
            await helper_db.rollback()

        outcome = await asyncio.wait_for(scheduled_task, timeout=10)
        assert outcome["submitted"] == 1
        assert len(outcome["submitted_events"]) == 1
        assert str(outcome["submitted_events"][0]["id"]) == str(
            values["event_action_a_id"]
        )
    finally:
        if scheduled_task is not None and not scheduled_task.done():
            scheduled_task.cancel()
            await asyncio.gather(scheduled_task, return_exceptions=True)
        await waiter_engine.dispose()
        async with policy_harness.owner_session() as owner_db:
            await owner_db.execute(
                text(
                    """
                    DELETE FROM attendance_records
                    WHERE resident_id = :resident_id
                      AND teaching_event_id = :event_id
                    """
                ),
                {
                    "resident_id": values["resident_a_id"],
                    "event_id": values["event_action_a_id"],
                },
            )
            await owner_db.commit()


@pytest.mark.asyncio
async def test_adhoc_creator_and_storage_family_are_database_owned(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    native_event_id: UUID | None = None
    native_attendance_id: UUID | None = None
    external_event_id: UUID | None = None
    external_attendance_id: UUID | None = None
    holiday_id = uuid4()
    alternate_catalogue_id = uuid4()
    ambiguous_period_id = uuid4()
    holiday_date = date(2035, 6, 1) + timedelta(
        days=values["resident_a_id"].int % 20
    )
    alternate_keyword = f"{values['keyword']} alternate"
    rollback_constraint = (
        f"ck_rls_adhoc_rollback_{str(values['resident_peer_id']).replace('-', '')}"
    )

    async def assert_write_denied(
        db: AsyncSession,
        statement: str,
        parameters: Mapping[str, object],
        *,
        sqlstates: set[str],
    ) -> None:
        with pytest.raises(DBAPIError) as caught:
            async with db.begin_nested():
                await db.execute(text(statement), dict(parameters))
        assert _sqlstate(caught.value) in sqlstates

    try:
        async with policy_harness.owner_session() as owner_db:
            await owner_db.execute(
                text(
                    """
                    INSERT INTO public_holidays (
                        id, holiday_date, name, day_of_week, year
                    )
                    VALUES (
                        :id, :holiday_date, 'Ad-hoc helper boundary',
                        'Monday', 2035
                    )
                    """
                ),
                {"id": holiday_id, "holiday_date": holiday_date},
            )
            await owner_db.execute(
                text(
                    """
                    INSERT INTO teaching_name_catalogue (
                        id, keyword, session_type_id, posting_code,
                        programme_code, r_year, reporting_period_id,
                        duration_hours, is_tracked
                    )
                    VALUES (
                        :id, :keyword, :session_type_id, :posting_code,
                        :programme_code, 'R1', :period_id, 1.00, true
                    )
                    """
                ),
                {
                    "id": alternate_catalogue_id,
                    "keyword": alternate_keyword,
                    "session_type_id": values["session_type_id"],
                    "posting_code": values["posting_b"],
                    "programme_code": values["programme_b"],
                    "period_id": values["period_id"],
                },
            )
            await owner_db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as db:
            created = (
                await db.execute(
                    text(
                        """
                        SELECT event_id, attendance_id
                        FROM mata_rls.create_adhoc_attendance(
                            CAST(:posting_code AS text),
                            CAST(:attended_posting_code AS text),
                            CAST('Department/Programme Teaching [1h]' AS text),
                            CAST('Department/Programme Teaching [1h]' AS text),
                            CAST(:details AS text),
                            DATE '2035-04-01',
                            TIME '09:00',
                            TIME '10:00',
                            CAST(1.00 AS numeric),
                            NULL::uuid
                        )
                        """
                    ),
                    {
                        "posting_code": values["posting_a"],
                        "attended_posting_code": values["posting_a"],
                        "details": "native creator matrix",
                    },
                )
            ).mappings().one()
            native_event_id = created["event_id"]
            native_attendance_id = created["attendance_id"]
            native_event = (
                await db.execute(
                    text(
                        """
                        SELECT teaching_name, duration_hours, session_type_id,
                               teaching_name_id, global_session_type_id
                        FROM teaching_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": native_event_id},
                )
            ).mappings().one()
            assert dict(native_event) == {
                "teaching_name": "Department/Programme Teaching [1h]",
                "duration_hours": Decimal("1.00"),
                "session_type_id": None,
                "teaching_name_id": None,
                "global_session_type_id": None,
            }
            assert await db.scalar(
                text(
                    """
                    SELECT created_by_resident_id
                    FROM teaching_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": native_event_id},
            ) == values["resident_a_id"]
            assert await db.scalar(
                text(
                    """
                    SELECT resident_id
                    FROM attendance_records
                    WHERE id = :attendance_id
                    """
                ),
                {"attendance_id": native_attendance_id},
            ) == values["resident_a_id"]
            await assert_write_denied(
                db,
                """
                INSERT INTO attendance_records (
                    id, resident_id, teaching_event_id, status, posting_code
                )
                VALUES (
                    :id, :resident_id, :event_id, 'flagged', :posting_code
                )
                """,
                {
                    "id": uuid4(),
                    "resident_id": values["resident_a_id"],
                    "event_id": native_event_id,
                    "posting_code": values["posting_a"],
                },
                sqlstates={"23514", "42501"},
            )
            await assert_write_denied(
                db,
                """
                INSERT INTO attendance_records (
                    id, resident_id, teaching_event_id, status,
                    posting_code, submitted_at, created_at, updated_at
                )
                VALUES (
                    :id, :resident_id, :event_id, 'submitted',
                    :posting_code, TIMESTAMPTZ '2000-01-01 00:00:00+00',
                    TIMESTAMPTZ '2000-01-01 00:00:00+00',
                    TIMESTAMPTZ '2000-01-01 00:00:00+00'
                )
                """,
                {
                    "id": uuid4(),
                    "resident_id": values["resident_a_id"],
                    "event_id": native_event_id,
                    "posting_code": values["posting_b"],
                },
                sqlstates={"23514"},
            )
            await assert_write_denied(
                db,
                """
                UPDATE attendance_records
                SET status = 'flagged'
                WHERE id = :attendance_id
                """,
                {"attendance_id": native_attendance_id},
                sqlstates={"23514"},
            )
            await assert_write_denied(
                db,
                """
                SELECT *
                FROM mata_rls.create_adhoc_attendance(
                    CAST(:posting_code AS text),
                    CAST(:attended_posting_code AS text),
                    'not an allowed attended teaching',
                    CAST('Department/Programme Teaching [1h]' AS text),
                    'invalid native catalogue marker',
                    DATE '2035-04-02',
                    TIME '11:00',
                    TIME '12:00',
                    CAST(1.00 AS numeric),
                    NULL::uuid
                )
                """,
                {
                    "posting_code": values["posting_a"],
                    "attended_posting_code": values["posting_a"],
                },
                sqlstates={"22023"},
            )
            await assert_write_denied(
                db,
                """
                SELECT *
                FROM mata_rls.create_adhoc_attendance(
                    CAST(:posting_code AS text),
                    CAST(:attended_posting_code AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    'public holiday marker',
                    CAST(:event_date AS date),
                    TIME '11:00',
                    TIME '12:00',
                    CAST(1.00 AS numeric),
                    NULL::uuid
                )
                """,
                {
                    "posting_code": values["posting_a"],
                    "attended_posting_code": values["posting_a"],
                    "event_date": holiday_date,
                },
                sqlstates={"22023"},
            )
            await assert_write_denied(
                db,
                """
                SELECT *
                FROM mata_rls.create_adhoc_attendance(
                    CAST(:posting_code AS text),
                    CAST(:attended_posting_code AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    'overlap marker',
                    DATE '2035-04-01',
                    TIME '09:30',
                    TIME '10:30',
                    CAST(1.00 AS numeric),
                    NULL::uuid
                )
                """,
                {
                    "posting_code": values["posting_a"],
                    "attended_posting_code": values["posting_a"],
                },
                sqlstates={"23P01"},
            )
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_events
                    WHERE details_of_session IN (
                        'invalid native catalogue marker',
                        'public holiday marker',
                        'overlap marker'
                    )
                    """
                )
            ) == 0
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident_peer"],
        ) as db:
            assert await db.scalar(
                text(
                    "SELECT id FROM teaching_events WHERE id = :event_id"
                ),
                {"event_id": native_event_id},
            ) is None
            await assert_write_denied(
                db,
                """
                INSERT INTO attendance_records (
                    id, resident_id, teaching_event_id, status, posting_code
                )
                VALUES (
                    :id, :resident_id, :event_id, 'submitted', :posting_code
                )
                """,
                {
                    "id": uuid4(),
                    "resident_id": values["resident_peer_id"],
                    "event_id": native_event_id,
                    "posting_code": values["posting_a"],
                },
                sqlstates={"23514", "42501"},
            )
            await assert_write_denied(
                db,
                """
                INSERT INTO teaching_events (
                    posting_code, teaching_name, event_date, start_time,
                    end_time, duration_hours, session_type_id, is_adhoc,
                    created_by_role, created_by_resident_id
                )
                VALUES (
                    :posting_code, :teaching_name, DATE '2035-04-02',
                    TIME '09:00', TIME '10:00', 1.00, :session_type_id,
                    true, 'resident', :resident_id
                )
                """,
                {
                    "posting_code": values["posting_a"],
                    "teaching_name": values["session_name"],
                    "session_type_id": values["session_type_id"],
                    "resident_id": values["resident_peer_id"],
                },
                sqlstates={"42501"},
            )

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["external"],
        ) as db:
            assert await db.scalar(
                text(
                    "SELECT id FROM teaching_events WHERE id = :event_id"
                ),
                {"event_id": native_event_id},
            ) is None
            await assert_write_denied(
                db,
                """
                INSERT INTO external_attendance_records (
                    id, external_resident_id, teaching_event_id,
                    status, posting_code
                )
                VALUES (
                    :id, :external_resident_id, :event_id,
                    'submitted', :posting_code
                )
                """,
                {
                    "id": uuid4(),
                    "external_resident_id": values["external_a_id"],
                    "event_id": native_event_id,
                    "posting_code": values["posting_a"],
                },
                sqlstates={"23514", "42501"},
            )
            await assert_write_denied(
                db,
                """
                SELECT *
                FROM mata_rls.create_adhoc_attendance(
                    CAST(:posting_code AS text),
                    CAST(:attended_posting_code AS text),
                    CAST(:attended_teaching_name AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    'wrong attended posting marker',
                    DATE '2035-04-02',
                    TIME '11:00',
                    TIME '12:00',
                    CAST(1.00 AS numeric),
                    NULL::uuid
                )
                """,
                {
                    "posting_code": values["posting_a"],
                    "attended_posting_code": values["posting_a"],
                    "attended_teaching_name": alternate_keyword,
                },
                sqlstates={"22023"},
            )

            created = (
                await db.execute(
                    text(
                        """
                        SELECT event_id, attendance_id
                        FROM mata_rls.create_adhoc_attendance(
                            CAST(:posting_code AS text),
                            CAST(:attended_posting_code AS text),
                            CAST('Department/Programme Teaching [1h]' AS text),
                            CAST('Department/Programme Teaching [1h]' AS text),
                            CAST(:details AS text),
                            DATE '2035-04-03',
                            TIME '09:00',
                            TIME '10:00',
                            CAST(1.00 AS numeric),
                            NULL::uuid
                        )
                        """
                    ),
                    {
                        "posting_code": values["posting_a"],
                        "attended_posting_code": values["posting_a"],
                        "details": "external creator matrix",
                    },
                )
            ).mappings().one()
            external_event_id = created["event_id"]
            external_attendance_id = created["attendance_id"]
            assert await db.scalar(
                text(
                    """
                    SELECT created_by_external_resident_id
                    FROM teaching_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": external_event_id},
            ) == values["external_a_id"]
            await assert_write_denied(
                db,
                """
                UPDATE external_attendance_records
                SET status = 'flagged'
                WHERE id = :attendance_id
                """,
                {"attendance_id": external_attendance_id},
                sqlstates={"23514"},
            )
            await assert_write_denied(
                db,
                """
                INSERT INTO external_attendance_records (
                    id, external_resident_id, teaching_event_id,
                    status, posting_code
                )
                VALUES (
                    :id, :external_resident_id, :event_id,
                    'removed', :posting_code
                )
                """,
                {
                    "id": uuid4(),
                    "external_resident_id": values["external_a_id"],
                    "event_id": external_event_id,
                    "posting_code": values["posting_a"],
                },
                sqlstates={"23514", "42501"},
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["external_peer"],
        ) as db:
            assert await db.scalar(
                text(
                    "SELECT id FROM teaching_events WHERE id = :event_id"
                ),
                {"event_id": external_event_id},
            ) is None
            await assert_write_denied(
                db,
                """
                INSERT INTO external_attendance_records (
                    id, external_resident_id, teaching_event_id,
                    status, posting_code
                )
                VALUES (
                    :id, :external_resident_id, :event_id,
                    'submitted', :posting_code
                )
                """,
                {
                    "id": uuid4(),
                    "external_resident_id": values["external_peer_id"],
                    "event_id": external_event_id,
                    "posting_code": values["posting_a"],
                },
                sqlstates={"23514", "42501"},
            )

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as db:
            assert await db.scalar(
                text(
                    "SELECT id FROM teaching_events WHERE id = :event_id"
                ),
                {"event_id": external_event_id},
            ) is None
            await assert_write_denied(
                db,
                """
                INSERT INTO attendance_records (
                    id, resident_id, teaching_event_id, status, posting_code
                )
                VALUES (
                    :id, :resident_id, :event_id, 'submitted', :posting_code
                )
                """,
                {
                    "id": uuid4(),
                    "resident_id": values["resident_a_id"],
                    "event_id": external_event_id,
                    "posting_code": values["posting_a"],
                },
                sqlstates={"23514", "42501"},
            )

        async with policy_harness.owner_session() as owner_db:
            with pytest.raises(DBAPIError) as caught:
                async with owner_db.begin_nested():
                    await owner_db.execute(
                        text(
                            """
                            UPDATE teaching_events
                            SET created_by_resident_id = :resident_id
                            WHERE id = :event_id
                            """
                        ),
                        {
                            "resident_id": values["resident_peer_id"],
                            "event_id": native_event_id,
                        },
                    )
            assert _sqlstate(caught.value) == "23514"

            with pytest.raises(DBAPIError) as caught:
                async with owner_db.begin_nested():
                    await owner_db.execute(
                        text(
                            """
                            UPDATE teaching_events
                            SET created_by_role = 'external_resident'
                            WHERE id = :event_id
                            """
                        ),
                        {"event_id": native_event_id},
                    )
            assert _sqlstate(caught.value) == "23514"

            with pytest.raises(DBAPIError) as caught:
                async with owner_db.begin_nested():
                    await owner_db.execute(
                        text(
                            """
                            UPDATE attendance_records
                            SET resident_id = :resident_id
                            WHERE id = :attendance_id
                            """
                        ),
                        {
                            "resident_id": values["resident_peer_id"],
                            "attendance_id": native_attendance_id,
                        },
                    )
            assert _sqlstate(caught.value) == "23514"

            with pytest.raises(DBAPIError) as caught:
                async with owner_db.begin_nested():
                    await owner_db.execute(
                        text(
                            """
                            INSERT INTO external_attendance_records (
                                external_resident_id, teaching_event_id,
                                status, posting_code
                            )
                            VALUES (
                                :external_resident_id, :event_id,
                                'submitted', :posting_code
                            )
                            """
                        ),
                        {
                            "external_resident_id": values["external_a_id"],
                            "event_id": native_event_id,
                            "posting_code": values["posting_a"],
                        },
                    )
            assert _sqlstate(caught.value) == "23514"

            assert await owner_db.scalar(
                text(
                    """
                    UPDATE attendance_records
                    SET status = 'removed'
                    WHERE id = :attendance_id
                    RETURNING status
                    """
                ),
                {"attendance_id": native_attendance_id},
            ) == "removed"
            with pytest.raises(DBAPIError) as caught:
                async with owner_db.begin_nested():
                    await owner_db.execute(
                        text(
                            """
                            UPDATE attendance_records
                            SET status = 'flagged'
                            WHERE id = :attendance_id
                            """
                        ),
                        {"attendance_id": native_attendance_id},
                    )
            assert _sqlstate(caught.value) == "23514"

            await owner_db.execute(
                text(
                    f"""
                    ALTER TABLE attendance_records
                    ADD CONSTRAINT {rollback_constraint}
                    CHECK (posting_code <> '{values["posting_a"]}')
                    NOT VALID
                    """
                )
            )
            await owner_db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident_peer"],
        ) as db:
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(
                        text(
                            """
                            SELECT *
                            FROM mata_rls.create_adhoc_attendance(
                                CAST(:posting_code AS text),
                                CAST(:attended_posting_code AS text),
                                CAST('Department/Programme Teaching [1h]' AS text),
                                CAST('Department/Programme Teaching [1h]' AS text),
                                'rollback marker',
                                DATE '2035-04-04',
                                TIME '09:00',
                                TIME '10:00',
                                CAST(1.00 AS numeric),
                                NULL::uuid
                            )
                            """
                        ),
                        {
                            "posting_code": values["posting_a"],
                            "attended_posting_code": values["posting_a"],
                        },
                    )
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_events
                    WHERE details_of_session = 'rollback marker'
                    """
                )
            ) == 0

        async with policy_harness.owner_session() as owner_db:
            await owner_db.execute(
                text(
                    """
                    INSERT INTO reporting_periods (
                        id, label, start_date, end_date, status
                    )
                    VALUES (
                        :id, :label, DATE '2035-01-01',
                        DATE '2035-12-31', 'active'
                    )
                    """
                ),
                {
                    "id": ambiguous_period_id,
                    "label": f"AMB{ambiguous_period_id.hex[:20]}",
                },
            )
            await owner_db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as db:
            await assert_write_denied(
                db,
                """
                SELECT *
                FROM mata_rls.create_adhoc_attendance(
                    CAST(:posting_code AS text),
                    CAST(:attended_posting_code AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    CAST('Department/Programme Teaching [1h]' AS text),
                    'ambiguous period marker',
                    DATE '2035-05-01',
                    TIME '11:00',
                    TIME '12:00',
                    CAST(1.00 AS numeric),
                    NULL::uuid
                )
                """,
                {
                    "posting_code": values["posting_a"],
                    "attended_posting_code": values["posting_a"],
                },
                sqlstates={"22023"},
            )
    finally:
        async with policy_harness.owner_session() as owner_db:
            await owner_db.execute(
                text(
                    f"""
                    ALTER TABLE attendance_records
                    DROP CONSTRAINT IF EXISTS {rollback_constraint}
                    """
                )
            )
            await owner_db.execute(
                text("DELETE FROM reporting_periods WHERE id = :id"),
                {"id": ambiguous_period_id},
            )
            await owner_db.execute(
                text("DELETE FROM public_holidays WHERE id = :id"),
                {"id": holiday_id},
            )
            await owner_db.execute(
                text("DELETE FROM teaching_name_catalogue WHERE id = :id"),
                {"id": alternate_catalogue_id},
            )
            event_ids = [
                event_id
                for event_id in (native_event_id, external_event_id)
                if event_id is not None
            ]
            if event_ids:
                await owner_db.execute(
                    text(
                        """
                        DELETE FROM external_attendance_records
                        WHERE teaching_event_id
                            = ANY(CAST(:event_ids AS uuid[]))
                        """
                    ),
                    {"event_ids": event_ids},
                )
                await owner_db.execute(
                    text(
                        """
                        DELETE FROM attendance_records
                        WHERE teaching_event_id
                            = ANY(CAST(:event_ids AS uuid[]))
                        """
                    ),
                    {"event_ids": event_ids},
                )
                await owner_db.execute(
                    text(
                        """
                        DELETE FROM teaching_events
                        WHERE id = ANY(CAST(:event_ids AS uuid[]))
                        """
                    ),
                    {"event_ids": event_ids},
                )
            await owner_db.commit()


@pytest.mark.asyncio
async def test_phase_g_atomic_adhoc_helper_fails_closed_for_overlapping_schedule_rows(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    """The direct helper must not let an ambiguous schedule choose a posting."""

    values = policy_seed.values
    native_overlap_id = uuid4()
    external_overlap_id = uuid4()
    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO resident_postings (
                        id, resident_id, posting_code, reporting_period_id,
                        start_date, end_date, r_year, status
                    )
                    VALUES (
                        :id, :resident_id, :posting_code, :reporting_period_id,
                        DATE '2035-04-05', DATE '2035-04-05', 'R1', 'active'
                    )
                    """
                ),
                {
                    "id": native_overlap_id,
                    "resident_id": values["resident_a_id"],
                    "posting_code": values["posting_b"],
                    "reporting_period_id": values["period_id"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO external_resident_postings (
                        id, external_resident_id, posting_code, programme_code,
                        start_date, end_date, is_current
                    )
                    VALUES (
                        :id, :external_resident_id, :posting_code,
                        :programme_code, DATE '2035-04-06', DATE '2035-04-06',
                        false
                    )
                    """
                ),
                {
                    "id": external_overlap_id,
                    "external_resident_id": values["external_a_id"],
                    "posting_code": values["posting_b"],
                    "programme_code": values["programme_b"],
                },
            )
            await db.commit()

        for context_name, event_date in (
            ("resident", date(2035, 4, 5)),
            ("external", date(2035, 4, 6)),
        ):
            async with _runtime_context(
                policy_harness,
                policy_seed.contexts[context_name],
            ) as db:
                with pytest.raises(DBAPIError) as ambiguous_schedule:
                    async with db.begin_nested():
                        await db.execute(
                            text(
                                """
                                SELECT *
                                FROM mata_rls.create_adhoc_attendance(
                                    CAST(:posting_code AS text),
                                    CAST(:posting_code AS text),
                                    CAST('Department/Programme Teaching [1h]' AS text),
                                    CAST('Department/Programme Teaching [1h]' AS text),
                                    'ambiguous schedule marker',
                                    CAST(:event_date AS date),
                                    TIME '13:00',
                                    TIME '14:00',
                                    CAST(1.00 AS numeric),
                                    NULL::uuid
                                )
                                """
                            ),
                            {
                                "posting_code": values["posting_a"],
                                "event_date": event_date,
                            },
                        )
                assert _sqlstate(ambiguous_schedule.value) == "22023"
                assert await db.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM teaching_events
                        WHERE details_of_session = 'ambiguous schedule marker'
                        """
                    )
                ) == 0
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text("DELETE FROM external_resident_postings WHERE id = :id"),
                {"id": external_overlap_id},
            )
            await db.execute(
                text("DELETE FROM resident_postings WHERE id = :id"),
                {"id": native_overlap_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_teaching_name_pool_shared_service_lifecycle_is_transactional_and_scoped(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = policy_seed.values
    pc_actor = _pc_teaching_name_actor(values)
    master_actor = _master_teaching_name_actor(values)
    teaching_name_ids: list[UUID] = []
    teaching_target_ids: list[UUID] = []
    programme_ids: list[UUID] = []
    cache_calls: list[dict[str, Any]] = []

    def record_cache_change(**kwargs: Any) -> list[object]:
        cache_calls.append(dict(kwargs))
        return []

    monkeypatch.setattr(
        teaching_name_pool.cache_invalidation,
        "invalidate_after_teaching_name_pool_change",
        record_cache_change,
    )

    try:
        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            created = await teaching_name_pool.create_teaching_name(
                db,
                actor=pc_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name="  Service Café\tName  ",
            )
            created_id = created["id"]
            teaching_name_ids.append(created_id)
            assert created["teaching_name"] == "Service Café Name"
            assert created["revision"] == 1
            assert (
                created["data_revalidation"].outcome
                == DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT
            )
            assert (
                created["data_revalidation"].changed_entity
                == DataRevalidationChangedEntity.TEACHING_NAME
            )
            assert created["data_revalidation"].affected_models == ["teaching_names"]

            with pytest.raises(ApiError) as duplicate_active:
                await teaching_name_pool.create_teaching_name(
                    db,
                    actor=pc_actor,
                    reporting_period_id=values["period_id"],
                    programme_code=values["programme_a"],
                    teaching_name="service cafe\u0301 name",
                )
            assert duplicate_active.value.status_code == 409
            assert duplicate_active.value.metadata == {
                "existing_teaching_name_id": str(created_id),
                "may_reactivate": False,
            }

            second = await teaching_name_pool.create_teaching_name(
                db,
                actor=pc_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name="Independent Service Name",
            )
            second_id = second["id"]
            teaching_name_ids.append(second_id)
            with pytest.raises(ApiError) as duplicate_update:
                await teaching_name_pool.update_teaching_name(
                    db,
                    actor=pc_actor,
                    teaching_name_id=second_id,
                    teaching_name="Service Café Name",
                    expected_revision=1,
                )
            assert duplicate_update.value.status_code == 409
            assert duplicate_update.value.metadata == {
                "existing_teaching_name_id": str(created_id),
                "may_reactivate": False,
            }

            renamed = await teaching_name_pool.update_teaching_name(
                db,
                actor=pc_actor,
                teaching_name_id=created_id,
                teaching_name="Renamed Service Name",
                expected_revision=1,
            )
            assert renamed["revision"] == 2
            cache_call_count_before_stale_delete = len(cache_calls)
            with pytest.raises(ApiError) as stale_delete:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=pc_actor,
                    teaching_name_id=created_id,
                    expected_revision=1,
                    force_delete=False,
                    reason=None,
                    confirmation=None,
            )
            assert stale_delete.value.status_code == 409
            assert len(cache_calls) == cache_call_count_before_stale_delete
            async with policy_harness.owner_session() as owner_db:
                assert await owner_db.scalar(
                    text(
                        """
                        SELECT revision
                        FROM teaching_names
                        WHERE id = :teaching_name_id
                        """
                    ),
                    {"teaching_name_id": created_id},
                ) == 2
                assert await owner_db.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM teaching_name_mappings
                        WHERE teaching_name_id = :teaching_name_id
                        """
                    ),
                    {"teaching_name_id": created_id},
                ) == 1
                assert await owner_db.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name'
                          AND entity_id = CAST(:teaching_name_id AS text)
                          AND action = 'programme_pc.teaching_name.delete'
                        """
                    ),
                    {"teaching_name_id": str(created_id)},
                ) == 0
            with pytest.raises(ApiError) as stale_update:
                await teaching_name_pool.update_teaching_name(
                    db,
                    actor=pc_actor,
                    teaching_name_id=created_id,
                    teaching_name="Stale rename",
                    expected_revision=1,
                )
            assert stale_update.value.status_code == 409
            with pytest.raises(ApiError) as create_normalized_too_long:
                await teaching_name_pool.create_teaching_name(
                    db,
                    actor=pc_actor,
                    reporting_period_id=values["period_id"],
                    programme_code=values["programme_a"],
                    teaching_name="ß" * 200,
                )
            assert create_normalized_too_long.value.status_code == 422
            with pytest.raises(ApiError) as update_normalized_too_long:
                await teaching_name_pool.update_teaching_name(
                    db,
                    actor=pc_actor,
                    teaching_name_id=created_id,
                    teaching_name="ß" * 200,
                    expected_revision=2,
                )
            assert update_normalized_too_long.value.status_code == 422

            deactivated = await teaching_name_pool.deactivate_teaching_name(
                db,
                actor=pc_actor,
                teaching_name_id=created_id,
                expected_revision=2,
            )
            assert deactivated["revision"] == 3
            with pytest.raises(ApiError) as duplicate_inactive:
                await teaching_name_pool.create_teaching_name(
                    db,
                    actor=pc_actor,
                    reporting_period_id=values["period_id"],
                    programme_code=values["programme_a"],
                    teaching_name="renamed service name",
                )
            assert duplicate_inactive.value.status_code == 409
            assert duplicate_inactive.value.metadata == {
                "existing_teaching_name_id": str(created_id),
                "may_reactivate": True,
            }

        extra_target_id = uuid4()
        teaching_target_ids.append(extra_target_id)
        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    UPDATE teaching_name_mappings
                    SET teaching_target_id = :target_a_id
                    WHERE teaching_name_id = :teaching_name_id
                      AND r_year = 'R1'
                    RETURNING teaching_target_id
                    """
                ),
                {"target_a_id": values["target_a_id"], "teaching_name_id": created_id},
            ) == values["target_a_id"]
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_targets (
                        id, reporting_period_id, programme_code, r_year,
                        posting_code, session_type_id, monthly_target, is_tracked
                    )
                    VALUES (
                        :id, :period_id, :programme_code, 'R2',
                        :posting_code, :session_type_id, 1, true
                    )
                    """
                ),
                {
                    "id": extra_target_id,
                    "period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "session_type_id": values["session_type_id"],
                },
            )
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            reactivated = await teaching_name_pool.reactivate_teaching_name(
                db,
                actor=pc_actor,
                teaching_name_id=created_id,
                expected_revision=3,
            )
            assert reactivated["revision"] == 4

        async with policy_harness.owner_session() as db:
            mappings = (
                await db.execute(
                    text(
                        """
                        SELECT r_year, teaching_target_id
                        FROM teaching_name_mappings
                        WHERE teaching_name_id = :teaching_name_id
                        ORDER BY r_year
                        """
                    ),
                    {"teaching_name_id": created_id},
                )
            ).all()
            assert mappings == [("R1", values["target_a_id"]), ("R2", None)]

        async with policy_harness.owner_session() as holder:
            assert await teaching_name_pool.acquire_ttf_scope_lock(
                holder,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
            ) is True
            async with _service_runtime_context(
                policy_harness,
                policy_seed.contexts["pc"],
            ) as db:
                with pytest.raises(ApiError) as locked_delete:
                    await teaching_name_pool.delete_teaching_name(
                        db,
                        actor=pc_actor,
                        teaching_name_id=created_id,
                        expected_revision=4,
                        force_delete=False,
                        reason=None,
                        confirmation=None,
                    )
                assert locked_delete.value.status_code == 409
            await holder.rollback()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            deleted = await teaching_name_pool.delete_teaching_name(
                db,
                actor=pc_actor,
                teaching_name_id=created_id,
                expected_revision=4,
                force_delete=False,
                reason=None,
                confirmation=None,
            )
            assert deleted["used_name"] is False
            assert deleted["event_reference_count"] == 0

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            master_visible = await teaching_name_pool.list_teaching_names(
                db,
                actor=master_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                is_active=None,
                search=None,
                limit=20,
                offset=0,
            )
            assert second_id in {row["id"] for row in master_visible["items"]}
            with pytest.raises(ApiError) as master_update:
                await teaching_name_pool.update_teaching_name(
                    db,
                    actor=master_actor,
                    teaching_name_id=second_id,
                    teaching_name="Master Admin Must Not Rename",
                    expected_revision=1,
                )
            assert master_update.value.status_code == 403
            master_unused_delete = await teaching_name_pool.delete_teaching_name(
                db,
                actor=master_actor,
                teaching_name_id=second_id,
                expected_revision=1,
                force_delete=False,
                reason=None,
                confirmation=None,
            )
            assert master_unused_delete["used_name"] is False
            assert master_unused_delete["event_reference_count"] == 0

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": created_id},
            ) == 0
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": second_id},
            ) == 0
            audit_count_before_rollback = await db.scalar(
                text("SELECT COUNT(*) FROM audit_logs WHERE entity_type = 'teaching_name'")
            )

        async def fail_audit(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("test audit failure")

        cache_call_count_before_rollback = len(cache_calls)
        with monkeypatch.context() as rollback_patch:
            rollback_patch.setattr(teaching_name_pool, "write_audit_log", fail_audit)
            async with _service_runtime_context(
                policy_harness,
                policy_seed.contexts["pc"],
            ) as db:
                with pytest.raises(RuntimeError, match="test audit failure"):
                    await teaching_name_pool.create_teaching_name(
                        db,
                        actor=pc_actor,
                        reporting_period_id=values["period_id"],
                        programme_code=values["programme_a"],
                        teaching_name="Rollback Audit Name",
                    )

        no_target_programme_id = uuid4()
        no_target_programme = f"RN{uuid4().hex[:10].upper()}"
        programme_ids.append(no_target_programme_id)
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO programmes (
                        id, code, name, ay_date_category, r_year_required,
                        is_subspecialty
                    )
                    VALUES (
                        :id, :programme_code, :programme_code,
                        'non_im_subspec', true, false
                    )
                    """
                ),
                {"id": no_target_programme_id, "programme_code": no_target_programme},
            )
            await db.execute(
                text(
                    """
                    UPDATE users
                    SET programme_scope = ARRAY[:programme_a, :programme_b]::text[]
                    WHERE id = :pc_id
                    """
                ),
                {
                    "programme_a": values["programme_a"],
                    "programme_b": no_target_programme,
                    "pc_id": values["pc_id"],
                },
            )
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_names
                    WHERE reporting_period_id = :period_id
                      AND programme_code = :programme_code
                      AND normalized_name = 'rollback audit name'
                    """
                ),
                {
                    "period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                },
            ) == 0
            assert await db.scalar(
                text("SELECT COUNT(*) FROM audit_logs WHERE entity_type = 'teaching_name'")
            ) == audit_count_before_rollback
            await db.commit()

        no_target_context = await _issue_context(
            policy_harness,
            subject_type="staff",
            subject_id=values["pc_id"],
            supabase_user_id=values["pc_supabase_id"],
            session_generation=0,
        )
        no_target_actor = _pc_teaching_name_actor(
            values,
            programme_scope=frozenset({no_target_programme}),
        )
        async with _service_runtime_context(policy_harness, no_target_context) as db:
            no_target = await teaching_name_pool.create_teaching_name(
                db,
                actor=no_target_actor,
                reporting_period_id=values["period_id"],
                programme_code=no_target_programme,
                teaching_name="No Target Service Name",
            )
            no_target_id = no_target["id"]
            teaching_name_ids.append(no_target_id)
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": no_target_id},
            ) == 0
            await teaching_name_pool.delete_teaching_name(
                db,
                actor=no_target_actor,
                teaching_name_id=no_target_id,
                expected_revision=1,
                force_delete=False,
                reason=None,
                confirmation=None,
            )

        async with policy_harness.owner_session() as db:
            audit_rows = (
                await db.execute(
                    text(
                        """
                        SELECT entity_id, action, COUNT(*) AS count
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name'
                          AND entity_id = ANY(CAST(:name_ids AS text[]))
                        GROUP BY entity_id, action
                        """
                    ),
                    {"name_ids": [str(value) for value in teaching_name_ids]},
                )
            ).mappings().all()
            audit_counts = {
                (str(row["entity_id"]), str(row["action"])): int(row["count"])
                for row in audit_rows
            }
            expected_actions = {
                (str(created_id), "programme_pc.teaching_name.create"),
                (str(created_id), "programme_pc.teaching_name.rename"),
                (str(created_id), "programme_pc.teaching_name.deactivate"),
                (str(created_id), "programme_pc.teaching_name.reactivate"),
                (str(created_id), "programme_pc.teaching_name.delete"),
                (str(second_id), "programme_pc.teaching_name.create"),
                (str(second_id), "admin.teaching_name.delete"),
                (str(no_target_id), "programme_pc.teaching_name.create"),
                (str(no_target_id), "programme_pc.teaching_name.delete"),
            }
            assert set(audit_counts) == expected_actions
            assert set(audit_counts.values()) == {1}

        assert len(cache_calls) == 9
        assert len(cache_calls) > cache_call_count_before_rollback
        assert {
            call["reporting_period_id"] for call in cache_calls
        } == {values["period_id"]}
        assert {
            call["programme_code"] for call in cache_calls
        } == {values["programme_a"], no_target_programme}
        assert all(call["event_references_cleared"] is False for call in cache_calls)
    finally:
        await _cleanup_teaching_name_service_rows(
            policy_harness,
            teaching_name_ids=teaching_name_ids,
            teaching_target_ids=teaching_target_ids,
            programme_ids=programme_ids,
        )


@pytest.mark.asyncio
async def test_teaching_name_pool_shared_service_used_delete_requires_master_and_preserves_history(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = policy_seed.values
    pc_actor = _pc_teaching_name_actor(values)
    secretary_actor = _secretary_teaching_name_actor(values)
    master_actor = _master_teaching_name_actor(values)
    teaching_name_ids: list[UUID] = []
    cache_calls: list[dict[str, Any]] = []

    def record_cache_change(**kwargs: Any) -> list[object]:
        cache_calls.append(dict(kwargs))
        return []

    monkeypatch.setattr(
        teaching_name_pool.cache_invalidation,
        "invalidate_after_teaching_name_pool_change",
        record_cache_change,
    )

    try:
        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    UPDATE secretary_programme_pools
                    SET can_manage_teaching_names = true
                    WHERE id = :pool_id
                    RETURNING can_manage_teaching_names
                    """
                ),
                {"pool_id": values["pool_a_id"]},
            ) is True
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            unused = await teaching_name_pool.create_teaching_name(
                db,
                actor=secretary_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name="Secretary Unused Name",
            )
            unused_id = unused["id"]
            teaching_name_ids.append(unused_id)

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": unused_id},
            ) == 1

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            unused_delete = await teaching_name_pool.delete_teaching_name(
                db,
                actor=secretary_actor,
                teaching_name_id=unused_id,
                expected_revision=1,
                force_delete=False,
                reason=None,
                confirmation=None,
            )
            assert unused_delete["used_name"] is False
            assert unused_delete["event_reference_count"] == 0

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": unused_id},
            ) == 0
            unused_audits = (
                await db.execute(
                    text(
                        """
                        SELECT action
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name'
                          AND entity_id = CAST(:teaching_name_id AS text)
                        ORDER BY created_at
                        """
                    ),
                    {"teaching_name_id": str(unused_id)},
                )
            ).scalars().all()
            assert unused_audits == [
                "secretary.teaching_name.create",
                "secretary.teaching_name.delete",
            ]

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            created = await teaching_name_pool.create_teaching_name(
                db,
                actor=secretary_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name="Secretary Used Name",
            )
            teaching_name_id = created["id"]
            teaching_name_ids.append(teaching_name_id)
            assert (
                created["data_revalidation"].trigger_source.value
                == "secretary_config_change"
            )

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            with pytest.raises(DBAPIError) as non_master_lock_attempt:
                await db.execute(
                    text(
                        """
                        SELECT mata_rls.lock_master_teaching_name_delete(
                            CAST(:teaching_name_id AS uuid)
                        )
                        """
                    ),
                    {"teaching_name_id": str(teaching_name_id)},
                )
            assert _sqlstate(non_master_lock_attempt.value) == "42501"

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    UPDATE teaching_events
                    SET teaching_name_id = :teaching_name_id
                    WHERE id = :event_id
                    RETURNING teaching_name_id
                    """
                ),
                {
                    "teaching_name_id": teaching_name_id,
                    "event_id": values["event_seed_a_id"],
                },
            ) == teaching_name_id
            event_snapshot = await db.scalar(
                text(
                    """
                    SELECT to_jsonb(event) - 'teaching_name_id'
                    FROM teaching_events AS event
                    WHERE id = :event_id
                    """
                ),
                {"event_id": values["event_seed_a_id"]},
            )
            native_snapshot = await db.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM attendance_records AS attendance
                    WHERE id = :attendance_id
                    """
                ),
                {"attendance_id": values["attendance_a_id"]},
            )
            external_snapshot = await db.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM external_attendance_records AS attendance
                    WHERE id = :attendance_id
                    """
                ),
                {"attendance_id": values["external_attendance_a_id"]},
            )
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            with pytest.raises(ApiError) as pc_used_delete:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=pc_actor,
                    teaching_name_id=teaching_name_id,
                    expected_revision=1,
                    force_delete=False,
                    reason=None,
                    confirmation=None,
                )
            assert pc_used_delete.value.status_code == 409

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            with pytest.raises(ApiError) as secretary_used_delete:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=secretary_actor,
                    teaching_name_id=teaching_name_id,
                    expected_revision=1,
                    force_delete=False,
                    reason=None,
                    confirmation=None,
                )
            assert secretary_used_delete.value.status_code == 409

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            with pytest.raises(ApiError) as missing_force_delete:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=master_actor,
                    teaching_name_id=teaching_name_id,
                    expected_revision=1,
                    force_delete=False,
                    reason="Preserve recorded history",
                    confirmation=None,
                )
            assert missing_force_delete.value.status_code == 409
            with pytest.raises(ApiError) as incorrect_confirmation:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=master_actor,
                    teaching_name_id=teaching_name_id,
                    expected_revision=1,
                    force_delete=True,
                    reason="Preserve recorded history",
                    confirmation="delete",
                )
            assert incorrect_confirmation.value.status_code == 409
            with pytest.raises(ApiError) as missing_reason:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=master_actor,
                    teaching_name_id=teaching_name_id,
                    expected_revision=1,
                    force_delete=True,
                    reason="  ",
                    confirmation="DELETE",
                )
            assert missing_reason.value.status_code == 422
            deleted = await teaching_name_pool.delete_teaching_name(
                db,
                actor=master_actor,
                teaching_name_id=teaching_name_id,
                expected_revision=1,
                force_delete=True,
                reason="Preserve recorded history",
                confirmation="DELETE",
            )

        assert deleted["used_name"] is True
        assert deleted["event_reference_count"] == 1
        assert deleted["native_attendance_count"] == 1
        assert deleted["non_nhg_attendance_count"] == 1
        assert set(deleted) == {
            "teaching_name_id",
            "deleted",
            "used_name",
            "event_reference_count",
            "native_attendance_count",
            "non_nhg_attendance_count",
            "data_revalidation",
        }

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": teaching_name_id},
            ) == 0
            assert (
                await db.execute(
                    text(
                        """
                        SELECT teaching_name_id, to_jsonb(event) - 'teaching_name_id'
                        FROM teaching_events AS event
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": values["event_seed_a_id"]},
                )
            ).one() == (None, event_snapshot)
            assert await db.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM attendance_records AS attendance
                    WHERE id = :attendance_id
                    """
                ),
                {"attendance_id": values["attendance_a_id"]},
            ) == native_snapshot
            assert await db.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM external_attendance_records AS attendance
                    WHERE id = :attendance_id
                    """
                ),
                {"attendance_id": values["external_attendance_a_id"]},
            ) == external_snapshot
            audit_rows = (
                await db.execute(
                    text(
                        """
                        SELECT action, metadata_json
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name'
                          AND entity_id = CAST(:teaching_name_id AS text)
                        ORDER BY created_at
                        """
                    ),
                    {"teaching_name_id": str(teaching_name_id)},
                )
            ).mappings().all()
            assert [row["action"] for row in audit_rows] == [
                "secretary.teaching_name.create",
                "admin.teaching_name.force_delete",
            ]
            force_delete_metadata = audit_rows[-1]["metadata_json"]
            if isinstance(force_delete_metadata, str):
                force_delete_metadata = json.loads(force_delete_metadata)
            assert force_delete_metadata["event_reference_count"] == 1
            assert force_delete_metadata["native_attendance_count"] == 1
            assert force_delete_metadata["non_nhg_attendance_count"] == 1
            assert force_delete_metadata["event_identifiers_included"] is False
            assert force_delete_metadata["attendance_identifiers_included"] is False
            serialized_metadata = json.dumps(force_delete_metadata, sort_keys=True)
            assert str(values["event_seed_a_id"]) not in serialized_metadata
            assert str(values["attendance_a_id"]) not in serialized_metadata
            assert str(values["external_attendance_a_id"]) not in serialized_metadata

        assert len(cache_calls) == 4
        assert [
            call["event_references_cleared"] for call in cache_calls
        ] == [False, False, False, True]
        assert {
            call["reporting_period_id"] for call in cache_calls
        } == {values["period_id"]}
        assert {call["programme_code"] for call in cache_calls} == {
            values["programme_a"]
        }
    finally:
        await _cleanup_teaching_name_service_rows(
            policy_harness,
            teaching_name_ids=teaching_name_ids,
        )


@pytest.mark.asyncio
async def test_phase_d_mapping_service_uses_exact_identity_and_preserves_evidence(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    new_session_type_id = uuid4()
    new_target_id = uuid4()
    wrong_r_year_target_id = uuid4()
    proposed_target_event_id = uuid4()
    sibling_r_year_mapping_id = uuid4()
    zero_impact_name_id = uuid4()
    zero_impact_mapping_id = uuid4()
    mapping_id = values["mapping_a_id"]
    actor = _pc_teaching_name_actor(values)

    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO session_types (id, name, duration_hours, duration_label)
                    VALUES (:id, :name, 1.00, '1h')
                    """
                ),
                {
                    "id": new_session_type_id,
                    "name": f"Phase D mapping target {new_session_type_id.hex}",
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_targets (
                        id, reporting_period_id, programme_code, r_year,
                        posting_code, session_type_id, monthly_target, is_tracked
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code, 'R1',
                        :posting_code, :session_type_id, 1, true
                    )
                    """
                ),
                {
                    "id": new_target_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "session_type_id": new_session_type_id,
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_targets (
                        id, reporting_period_id, programme_code, r_year,
                        posting_code, session_type_id, monthly_target, is_tracked
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code, 'R2',
                        :posting_code, :session_type_id, 1, true
                    )
                    """
                ),
                {
                    "id": wrong_r_year_target_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "session_type_id": new_session_type_id,
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :id, :teaching_name_id, :reporting_period_id,
                        :programme_code, :posting_code, 'R2', :teaching_target_id
                    )
                    """
                ),
                {
                    "id": sibling_r_year_mapping_id,
                    "teaching_name_id": values["teaching_name_a_id"],
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "teaching_target_id": wrong_r_year_target_id,
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name, is_active
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code,
                        'Phase D zero impact name', 'phase d zero impact name', false
                    )
                    """
                ),
                {
                    "id": zero_impact_name_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :id, :teaching_name_id, :reporting_period_id,
                        :programme_code, :posting_code, 'R1', :teaching_target_id
                    )
                    """
                ),
                {
                    "id": zero_impact_mapping_id,
                    "teaching_name_id": zero_impact_name_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "teaching_target_id": values["target_a_id"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        end_time, duration_hours, session_type_id, series_id,
                        is_adhoc, created_by_role, teaching_name_id
                    )
                    VALUES (
                        :id, :posting_code, 'Phase D proposed target evidence',
                        DATE '2035-03-07', TIME '09:00', TIME '10:00', 1.00,
                        :session_type_id, :series_id, false, 'secretary',
                        :teaching_name_id
                    )
                    """
                ),
                {
                    "id": proposed_target_event_id,
                    "posting_code": values["posting_a"],
                    "session_type_id": new_session_type_id,
                    "series_id": values["series_a_id"],
                    "teaching_name_id": values["teaching_name_a_id"],
                },
            )
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            queue = await teaching_name_mappings.list_mappings(
                db,
                actor=actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
            )
            mapping = next(item for item in queue["items"] if item["id"] == mapping_id)
            option_ids = {option["id"] for option in mapping["available_target_options"]}
            assert option_ids == {values["target_a_id"], new_target_id}

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            with pytest.raises(ApiError) as wrong_r_year:
                await teaching_name_mappings.apply_mapping_change(
                    db,
                    actor=actor,
                    mapping_id=mapping_id,
                    expected_revision=1,
                    teaching_target_id=wrong_r_year_target_id,
                    confirm_impact=True,
            )
            assert wrong_r_year.value.status_code == 422

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            zero_impact_change = await teaching_name_mappings.apply_mapping_change(
                db,
                actor=actor,
                mapping_id=zero_impact_mapping_id,
                expected_revision=1,
                teaching_target_id=new_target_id,
                confirm_impact=False,
            )
            assert zero_impact_change["revision"] == 2
            assert zero_impact_change["impact"] == {
                "affected_event_count": 0,
                "affected_attendance_count": 0,
            }

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            with pytest.raises(ApiError) as confirmation_required:
                await teaching_name_mappings.apply_mapping_change(
                    db,
                    actor=actor,
                    mapping_id=mapping_id,
                    expected_revision=1,
                    teaching_target_id=new_target_id,
                    confirm_impact=False,
                )
            assert confirmation_required.value.status_code == 409
            assert confirmation_required.value.metadata == {
                "impact": {
                    "affected_event_count": 2,
                    "affected_attendance_count": 2,
                },
                "confirmation_required": True,
            }

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            changed = await teaching_name_mappings.apply_mapping_change(
                db,
                actor=actor,
                mapping_id=mapping_id,
                expected_revision=1,
                teaching_target_id=new_target_id,
                confirm_impact=True,
            )
            assert changed["id"] == mapping_id
            assert changed["teaching_target_id"] == new_target_id
            assert changed["revision"] == 2
            assert changed["impact"] == {
                "affected_event_count": 2,
                "affected_attendance_count": 2,
            }
            assert (
                changed["data_revalidation"].changed_entity
                == DataRevalidationChangedEntity.TEACHING_NAME_MAPPING
            )

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            with pytest.raises(ApiError) as stale:
                await teaching_name_mappings.apply_mapping_change(
                    db,
                    actor=actor,
                    mapping_id=mapping_id,
                    expected_revision=1,
                    teaching_target_id=values["target_a_id"],
                    confirm_impact=True,
                )
            assert stale.value.status_code == 409

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    "SELECT teaching_target_id FROM teaching_name_mappings WHERE id = :id"
                ),
                {"id": mapping_id},
            ) == new_target_id
            assert await db.scalar(
                text("SELECT teaching_name_id FROM teaching_events WHERE id = :id"),
                {"id": values["event_seed_a_id"]},
            ) == values["teaching_name_a_id"]
            assert await db.scalar(
                text("SELECT teaching_name_id FROM teaching_events WHERE id = :id"),
                {"id": proposed_target_event_id},
            ) == values["teaching_name_a_id"]
            assert await db.scalar(
                text(
                    "SELECT COUNT(*) FROM attendance_records WHERE teaching_event_id = :id"
                ),
                {"id": values["event_seed_a_id"]},
            ) == 1
            assert await db.scalar(
                text(
                    "SELECT COUNT(*) FROM external_attendance_records WHERE teaching_event_id = :id"
                ),
                {"id": values["event_seed_a_id"]},
            ) == 1
            audit = (
                await db.execute(
                    text(
                        """
                        SELECT before_json, after_json, metadata_json
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name_mapping'
                          AND entity_id = :mapping_id
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"mapping_id": str(mapping_id)},
                )
            ).mappings().one()
            assert audit["before_json"]["revision"] == 1
            assert audit["after_json"]["revision"] == 2
            assert "attendance_id" not in str(audit["metadata_json"])

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            cleared = await teaching_name_mappings.apply_mapping_change(
                db,
                actor=actor,
                mapping_id=mapping_id,
                expected_revision=2,
                teaching_target_id=None,
                confirm_impact=True,
            )
            assert cleared["id"] == mapping_id
            assert cleared["teaching_target_id"] is None
            assert cleared["state"] == "pending"
            assert cleared["revision"] == 3
            assert cleared["impact"] == {
                "affected_event_count": 2,
                "affected_attendance_count": 2,
            }
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM audit_logs
                    WHERE action = 'programme_pc.teaching_name_mapping.update'
                      AND entity_type = 'teaching_name_mapping'
                      AND entity_id = ANY(CAST(:mapping_ids AS text[]))
                    """
                ),
                {
                    "mapping_ids": [
                        str(mapping_id),
                        str(zero_impact_mapping_id),
                    ]
                },
            )
            await db.execute(
                text(
                    """
                    UPDATE teaching_name_mappings
                    SET teaching_target_id = :target_id
                        , revision = 1
                        , updated_by_user_id = NULL
                    WHERE id = :mapping_id
                    """
                ),
                {"target_id": values["target_a_id"], "mapping_id": mapping_id},
            )
            await db.execute(
                text("DELETE FROM teaching_events WHERE id = :id"),
                {"id": proposed_target_event_id},
            )
            await db.execute(
                text("DELETE FROM teaching_names WHERE id = :id"),
                {"id": zero_impact_name_id},
            )
            await db.execute(
                text("DELETE FROM teaching_name_mappings WHERE id = :id"),
                {"id": sibling_r_year_mapping_id},
            )
            await db.execute(
                text("DELETE FROM teaching_targets WHERE id = :id"),
                {"id": new_target_id},
            )
            await db.execute(
                text("DELETE FROM teaching_targets WHERE id = :id"),
                {"id": wrong_r_year_target_id},
            )
            await db.execute(
                text("DELETE FROM session_types WHERE id = :id"),
                {"id": new_session_type_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_phase_d_mapping_shares_ttf_scope_lock_but_other_scopes_proceed(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    other_period_id = uuid4()
    other_target_id = uuid4()
    other_name_id = uuid4()
    other_mapping_id = uuid4()
    actor = _pc_teaching_name_actor(values)

    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO reporting_periods (
                        id, label, start_date, end_date, status
                    )
                    VALUES (
                        :id, :label, DATE '2036-01-01', DATE '2036-12-31', 'active'
                    )
                    """
                ),
                {
                    "id": other_period_id,
            "label": f"DLock{other_period_id.hex[:20]}",
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_targets (
                        id, reporting_period_id, programme_code, r_year,
                        posting_code, session_type_id, monthly_target, is_tracked
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code, 'R1',
                        :posting_code, :session_type_id, 1, true
                    )
                    """
                ),
                {
                    "id": other_target_id,
                    "reporting_period_id": other_period_id,
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "session_type_id": values["session_type_id"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name, is_active
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code,
                        'Phase D lock independence', 'phase d lock independence', false
                    )
                    """
                ),
                {
                    "id": other_name_id,
                    "reporting_period_id": other_period_id,
                    "programme_code": values["programme_a"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :id, :teaching_name_id, :reporting_period_id,
                        :programme_code, :posting_code, 'R1', NULL
                    )
                    """
                ),
                {
                    "id": other_mapping_id,
                    "teaching_name_id": other_name_id,
                    "reporting_period_id": other_period_id,
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                },
            )
            await db.commit()

        async with policy_harness.owner_session() as ttf_holder:
            try:
                assert await acquire_ttf_scope_lock(
                    ttf_holder,
                    reporting_period_id=values["period_id"],
                    programme_code=values["programme_a"],
                )

                async with _service_runtime_context(
                    policy_harness,
                    policy_seed.contexts["pc"],
                ) as db:
                    with pytest.raises(ApiError) as held_scope:
                        await teaching_name_mappings.apply_mapping_change(
                            db,
                            actor=actor,
                            mapping_id=values["mapping_a_id"],
                            expected_revision=1,
                            teaching_target_id=None,
                            confirm_impact=True,
                        )
                    assert held_scope.value.status_code == 409

                async with _service_runtime_context(
                    policy_harness,
                    policy_seed.contexts["pc"],
                ) as db:
                    different_scope = await teaching_name_mappings.apply_mapping_change(
                        db,
                        actor=actor,
                        mapping_id=other_mapping_id,
                        expected_revision=1,
                        teaching_target_id=other_target_id,
                        confirm_impact=False,
                    )
                    assert different_scope["id"] == other_mapping_id
                    assert different_scope["teaching_target_id"] == other_target_id
                    assert different_scope["revision"] == 2
            finally:
                await ttf_holder.rollback()

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT teaching_target_id
                    FROM teaching_name_mappings
                    WHERE id = :mapping_id
                    """
                ),
                {"mapping_id": values["mapping_a_id"]},
            ) == values["target_a_id"]
            assert await db.scalar(
                text(
                    """
                    SELECT teaching_target_id
                    FROM teaching_name_mappings
                    WHERE id = :mapping_id
                    """
                ),
                {"mapping_id": other_mapping_id},
            ) == other_target_id
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM audit_logs
                    WHERE entity_type = 'teaching_name_mapping'
                      AND entity_id = :mapping_id
                    """
                ),
                {"mapping_id": str(other_mapping_id)},
            )
            await db.execute(
                text("DELETE FROM teaching_names WHERE id = :id"),
                {"id": other_name_id},
            )
            await db.execute(
                text("DELETE FROM teaching_targets WHERE id = :id"),
                {"id": other_target_id},
            )
            await db.execute(
                text("DELETE FROM reporting_periods WHERE id = :id"),
                {"id": other_period_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_phase_d_bulk_mapping_service_is_atomic_and_audited(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    extra_name_id = uuid4()
    extra_mapping_id = uuid4()
    mapping_ids = [values["mapping_a_id"], extra_mapping_id]
    actor = _pc_teaching_name_actor(values)

    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name, is_active
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code,
                        'Phase D bulk evidence name', 'phase d bulk evidence name', false
                    )
                    """
                ),
                {
                    "id": extra_name_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :id, :teaching_name_id, :reporting_period_id,
                        :programme_code, :posting_code, 'R1', :teaching_target_id
                    )
                    """
                ),
                {
                    "id": extra_mapping_id,
                    "teaching_name_id": extra_name_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_a"],
                    "teaching_target_id": None,
                },
            )
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            with pytest.raises(ApiError) as stale_batch:
                await teaching_name_mappings.apply_bulk_mapping_changes(
                    db,
                    actor=actor,
                    items=[
                        TeachingNameMappingBulkItemRequest(
                            mapping_id=extra_mapping_id,
                            expected_revision=2,
                            teaching_target_id=values["target_a_id"],
                        ),
                        TeachingNameMappingBulkItemRequest(
                            mapping_id=values["mapping_a_id"],
                            expected_revision=1,
                            teaching_target_id=None,
                            confirm_impact=True,
                        ),
                    ],
                )
            assert stale_batch.value.status_code == 409

        async with policy_harness.owner_session() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, teaching_target_id, revision
                        FROM teaching_name_mappings
                        WHERE id = ANY(CAST(:mapping_ids AS uuid[]))
                        ORDER BY id
                        """
                    ),
                    {"mapping_ids": mapping_ids},
                )
            ).mappings().all()
            row_by_id = {row["id"]: row for row in rows}
            assert row_by_id[values["mapping_a_id"]]["teaching_target_id"] == values[
                "target_a_id"
            ]
            assert row_by_id[values["mapping_a_id"]]["revision"] == 1
            assert row_by_id[extra_mapping_id]["teaching_target_id"] is None
            assert row_by_id[extra_mapping_id]["revision"] == 1
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM audit_logs
                    WHERE entity_type = 'teaching_name_mapping'
                      AND entity_id = ANY(CAST(:mapping_ids AS text[]))
                    """
                ),
                {"mapping_ids": [str(mapping_id) for mapping_id in mapping_ids]},
            ) == 0

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            changed = await teaching_name_mappings.apply_bulk_mapping_changes(
                db,
                actor=actor,
                items=[
                    TeachingNameMappingBulkItemRequest(
                        mapping_id=extra_mapping_id,
                        expected_revision=1,
                        teaching_target_id=values["target_a_id"],
                    ),
                    TeachingNameMappingBulkItemRequest(
                        mapping_id=values["mapping_a_id"],
                        expected_revision=1,
                        teaching_target_id=None,
                        confirm_impact=True,
                    ),
                ],
            )
            assert changed == {
                "requested_count": 2,
                "updated_count": 2,
                "mapped_count": 1,
                "pending_count": 1,
                "affected_event_count": 1,
                "affected_attendance_count": 2,
            }

        async with policy_harness.owner_session() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, teaching_target_id, revision
                        FROM teaching_name_mappings
                        WHERE id = ANY(CAST(:mapping_ids AS uuid[]))
                        ORDER BY id
                        """
                    ),
                    {"mapping_ids": mapping_ids},
                )
            ).mappings().all()
            row_by_id = {row["id"]: row for row in rows}
            assert row_by_id[values["mapping_a_id"]]["teaching_target_id"] is None
            assert row_by_id[values["mapping_a_id"]]["revision"] == 2
            assert row_by_id[extra_mapping_id]["teaching_target_id"] == values[
                "target_a_id"
            ]
            assert row_by_id[extra_mapping_id]["revision"] == 2
            audits = (
                await db.execute(
                    text(
                        """
                        SELECT entity_id, metadata_json
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name_mapping'
                          AND entity_id = ANY(CAST(:mapping_ids AS text[]))
                        ORDER BY entity_id
                        """
                    ),
                    {"mapping_ids": [str(mapping_id) for mapping_id in mapping_ids]},
                )
            ).mappings().all()
            assert {row["entity_id"] for row in audits} == {
                str(mapping_id) for mapping_id in mapping_ids
            }
            bulk_operation_ids = {
                row["metadata_json"]["bulk_operation_id"] for row in audits
            }
            assert len(bulk_operation_ids) == 1
            assert None not in bulk_operation_ids

    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM audit_logs
                    WHERE entity_type = 'teaching_name_mapping'
                      AND entity_id = ANY(CAST(:mapping_ids AS text[]))
                    """
                ),
                {"mapping_ids": [str(mapping_id) for mapping_id in mapping_ids]},
            )
            await db.execute(
                text(
                    """
                    UPDATE teaching_name_mappings
                    SET teaching_target_id = :target_id,
                        revision = 1,
                        updated_by_user_id = NULL
                    WHERE id = :mapping_id
                    """
                ),
                {
                    "target_id": values["target_a_id"],
                    "mapping_id": values["mapping_a_id"],
                },
            )
            await db.execute(
                text("DELETE FROM teaching_names WHERE id = :id"),
                {"id": extra_name_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_master_teaching_name_delete_lock_serializes_new_event_references(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = policy_seed.values
    pc_actor = _pc_teaching_name_actor(values)
    master_actor = _master_teaching_name_actor(values)
    teaching_name_ids: list[UUID] = []
    reference_counted = asyncio.Event()
    release_delete = asyncio.Event()
    reference_waiter_ready = asyncio.Event()
    reference_waiter_pid: int | None = None
    delete_task: asyncio.Task[dict[str, Any]] | None = None
    reference_task: asyncio.Task[None] | None = None
    original_locked_event_ids = teaching_name_pool._locked_event_ids

    async def pause_after_reference_count(
        db: AsyncSession,
        *,
        teaching_name_id: UUID,
    ) -> list[UUID]:
        event_ids = await original_locked_event_ids(
            db,
            teaching_name_id=teaching_name_id,
        )
        assert event_ids == []
        reference_counted.set()
        await release_delete.wait()
        return event_ids

    async def delete_as_master(teaching_name_id: UUID) -> dict[str, Any]:
        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            return await teaching_name_pool.delete_teaching_name(
                db,
                actor=master_actor,
                teaching_name_id=teaching_name_id,
                expected_revision=1,
                force_delete=False,
                reason=None,
                confirmation=None,
            )

    async def attach_reference(teaching_name_id: UUID) -> None:
        nonlocal reference_waiter_pid
        async with policy_harness.owner_session() as db:
            reference_waiter_pid = int(
                await db.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            )
            reference_waiter_ready.set()
            await db.execute(
                text(
                    """
                    UPDATE teaching_events
                    SET teaching_name_id = :teaching_name_id
                    WHERE id = :event_id
                    """
                ),
                {
                    "teaching_name_id": str(teaching_name_id),
                    "event_id": values["event_action_a_id"],
                },
            )
            await db.commit()

    try:
        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            created = await teaching_name_pool.create_teaching_name(
                db,
                actor=pc_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name="Master Delete Reference Fence",
            )
            teaching_name_id = created["id"]
            teaching_name_ids.append(teaching_name_id)

        monkeypatch.setattr(
            teaching_name_pool,
            "_locked_event_ids",
            pause_after_reference_count,
        )
        delete_task = asyncio.create_task(delete_as_master(teaching_name_id))
        await asyncio.wait_for(reference_counted.wait(), timeout=10)

        reference_task = asyncio.create_task(attach_reference(teaching_name_id))
        await asyncio.wait_for(reference_waiter_ready.wait(), timeout=10)
        assert reference_waiter_pid is not None
        await _wait_for_database_lock_wait(
            policy_harness,
            waiter_pid=reference_waiter_pid,
            blocked_task=reference_task,
        )
        assert not reference_task.done()

        release_delete.set()
        deleted = await asyncio.wait_for(delete_task, timeout=10)
        assert deleted["used_name"] is False
        assert deleted["event_reference_count"] == 0
        with pytest.raises(DBAPIError) as rejected_reference:
            await asyncio.wait_for(reference_task, timeout=10)
        assert _sqlstate(rejected_reference.value) == "23503"

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text("SELECT COUNT(*) FROM teaching_names WHERE id = :teaching_name_id"),
                {"teaching_name_id": teaching_name_id},
            ) == 0
            assert await db.scalar(
                text(
                    "SELECT teaching_name_id FROM teaching_events WHERE id = :event_id"
                ),
                {"event_id": values["event_action_a_id"]},
            ) is None
    finally:
        release_delete.set()
        for task in (delete_task, reference_task):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, DBAPIError):
                    await task
        await _cleanup_teaching_name_service_rows(
            policy_harness,
            teaching_name_ids=teaching_name_ids,
        )


@pytest.mark.asyncio
async def test_teaching_name_pool_shared_service_serializes_normalized_duplicate_creates(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    pc_actor = _pc_teaching_name_actor(values)
    teaching_name_ids: list[UUID] = []
    second_pc_context = await _issue_context(
        policy_harness,
        subject_type="staff",
        subject_id=values["pc_id"],
        supabase_user_id=values["pc_supabase_id"],
        session_generation=0,
    )

    async def create_candidate(
        context: PolicyContext,
        teaching_name: str,
    ) -> dict[str, Any]:
        async with _service_runtime_context(policy_harness, context) as db:
            return await teaching_name_pool.create_teaching_name(
                db,
                actor=pc_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name=teaching_name,
            )

    try:
        async with policy_harness.owner_session() as db:
            mapping_count_before = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE reporting_period_id = :period_id
                      AND programme_code = :programme_code
                    """
                ),
                {
                    "period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                },
            )
            audit_count_before = await db.scalar(
                text("SELECT COUNT(*) FROM audit_logs WHERE entity_type = 'teaching_name'")
            )

        outcomes = await asyncio.gather(
            create_candidate(policy_seed.contexts["pc"], "Concurrent ß"),
            create_candidate(second_pc_context, "concurrent ss"),
            return_exceptions=True,
        )
        created_rows = [outcome for outcome in outcomes if isinstance(outcome, dict)]
        failed_rows = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        assert len(created_rows) == 1
        assert len(failed_rows) == 1
        assert isinstance(failed_rows[0], ApiError)
        assert failed_rows[0].status_code == 409
        created_id = created_rows[0]["id"]
        teaching_name_ids.append(created_id)

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_names
                    WHERE reporting_period_id = :period_id
                      AND programme_code = :programme_code
                      AND normalized_name = 'concurrent ss'
                    """
                ),
                {
                    "period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                },
            ) == 1
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE reporting_period_id = :period_id
                      AND programme_code = :programme_code
                    """
                ),
                {
                    "period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                },
            ) == mapping_count_before + 1
            winner_mappings = (
                await db.execute(
                    text(
                        """
                        SELECT posting_code, r_year, teaching_target_id
                        FROM teaching_name_mappings
                        WHERE teaching_name_id = :teaching_name_id
                        """
                    ),
                    {"teaching_name_id": created_id},
                )
            ).all()
            assert winner_mappings == [(values["posting_a"], "R1", None)]
            audit_rows = (
                await db.execute(
                    text(
                        """
                        SELECT entity_id, action
                        FROM audit_logs
                        WHERE entity_type = 'teaching_name'
                        ORDER BY created_at
                        """
                    )
                )
            ).all()
            assert len(audit_rows) == audit_count_before + 1
            assert audit_rows[-1] == (
                str(created_id),
                "programme_pc.teaching_name.create",
            )

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            await teaching_name_pool.delete_teaching_name(
                db,
                actor=pc_actor,
                teaching_name_id=created_id,
                expected_revision=1,
                force_delete=False,
                reason=None,
                confirmation=None,
            )
    finally:
        await _cleanup_teaching_name_service_rows(
            policy_harness,
            teaching_name_ids=teaching_name_ids,
        )


@pytest.mark.asyncio
async def test_teaching_name_used_delete_guard_sees_hidden_event_references(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    secretary_actor = _secretary_teaching_name_actor(values)
    teaching_name_ids: list[UUID] = []

    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    UPDATE secretary_programme_pools
                    SET can_manage_teaching_names = true
                    WHERE id = :pool_id
                    """
                ),
                {"pool_id": values["pool_a_id"]},
            )
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            created = await teaching_name_pool.create_teaching_name(
                db,
                actor=secretary_actor,
                reporting_period_id=values["period_id"],
                programme_code=values["programme_a"],
                teaching_name="Secretary Hidden Event Guard",
            )
            teaching_name_id = created["id"]
            teaching_name_ids.append(teaching_name_id)

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    UPDATE teaching_events
                    SET teaching_name_id = :teaching_name_id
                    WHERE id = :event_id
                    RETURNING teaching_name_id
                    """
                ),
                {
                    "teaching_name_id": teaching_name_id,
                    "event_id": values["event_b_id"],
                },
            ) == teaching_name_id
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            assert await db.scalar(
                text("SELECT COUNT(*) FROM teaching_events WHERE id = :event_id"),
                {"event_id": values["event_b_id"]},
            ) == 0
            with pytest.raises(DBAPIError) as direct_delete:
                await db.execute(
                    text("DELETE FROM teaching_names WHERE id = :teaching_name_id"),
                    {"teaching_name_id": teaching_name_id},
                )
            assert _sqlstate(direct_delete.value) == "42501"

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            with pytest.raises(ApiError) as guarded_service_delete:
                await teaching_name_pool.delete_teaching_name(
                    db,
                    actor=secretary_actor,
                    teaching_name_id=teaching_name_id,
                    expected_revision=1,
                    force_delete=False,
                    reason=None,
                    confirmation=None,
                )
            assert guarded_service_delete.value.status_code == 409
    finally:
        await _cleanup_teaching_name_service_rows(
            policy_harness,
            teaching_name_ids=teaching_name_ids,
        )


@pytest.mark.asyncio
async def test_scheduled_event_source_policy_accepts_pending_ids_and_enforces_scope(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    """Exercise the F policy through real restricted runtime sessions."""

    values = policy_seed.values
    pending_name_id = uuid4()
    cross_programme_name_id = uuid4()
    global_session_type_id = uuid4()
    created_event_ids: list[UUID] = []
    original_capability: bool | None = None
    pc_actor = _pc_teaching_name_actor(values)
    secretary_actor = _secretary_teaching_name_actor(values)

    try:
        async with policy_harness.owner_session() as db:
            original_capability = await db.scalar(
                text(
                    """
                    SELECT can_manage_teaching_names
                    FROM secretary_programme_pools
                    WHERE id = :pool_id
                    """
                ),
                {"pool_id": values["pool_a_id"]},
            )
            await db.execute(
                text(
                    """
                    UPDATE secretary_programme_pools
                    SET can_manage_teaching_names = true
                    WHERE id = :pool_id
                    """
                ),
                {"pool_id": values["pool_a_id"]},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name, is_active
                    )
                    VALUES
                        (
                            :pending_name_id, :period_id, :programme_a,
                            'F pending source', 'f pending source', true
                        ),
                        (
                            :cross_programme_name_id, :period_id, :programme_b,
                            'F cross source', 'f cross source', true
                        )
                    """
                ),
                {
                    "pending_name_id": pending_name_id,
                    "cross_programme_name_id": cross_programme_name_id,
                    "period_id": values["period_id"],
                    "programme_a": values["programme_a"],
                    "programme_b": values["programme_b"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO global_session_types (
                        id, name, duration_hours, is_active
                    )
                    VALUES (:id, 'F global source', 1.50, true)
                    """
                ),
                {"id": global_session_type_id},
            )
            await db.commit()

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            pending_event = await programme_teaching_events.create_teaching_event(
                db,
                source_actor=pc_actor,
                audit_actor=pc_actor.staff_actor,
                programme_code=values["programme_a"],
                posting_code=values["posting_a"],
                teaching_name_id=pending_name_id,
                global_session_type_id=None,
                event_date=date(2035, 4, 2),
                start_time=time(23, 0),
                cme_points_awarded=False,
                smc_event_code=None,
            )
            created_event_ids.append(pending_event["id"])
            assert pending_event["teaching_name_id"] == pending_name_id
            assert pending_event["global_session_type_id"] is None
            assert pending_event["teaching_name"] == "F pending source"
            assert pending_event["duration_hours"] == Decimal("1.00")
            assert pending_event["end_time"] == time(0, 0)

            global_event = await programme_teaching_events.create_teaching_event(
                db,
                source_actor=pc_actor,
                audit_actor=pc_actor.staff_actor,
                programme_code=values["programme_a"],
                posting_code=values["posting_a"],
                teaching_name_id=None,
                global_session_type_id=global_session_type_id,
                event_date=date(2035, 4, 3),
                start_time=time(10, 0),
                cme_points_awarded=False,
                smc_event_code=None,
            )
            created_event_ids.append(global_event["id"])
            assert global_event["teaching_name_id"] is None
            assert global_event["global_session_type_id"] == global_session_type_id
            assert global_event["teaching_name"] == "F global source"
            assert global_event["end_time"] == time(11, 30)

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                {"teaching_name_id": pending_name_id},
            ) == 0
            persisted = (
                await db.execute(
                    text(
                        """
                        SELECT teaching_name, teaching_name_id, global_session_type_id,
                               duration_hours, end_time
                        FROM teaching_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": pending_event["id"]},
                )
            ).mappings().one()
            assert dict(persisted) == {
                "teaching_name": "F pending source",
                "teaching_name_id": pending_name_id,
                "global_session_type_id": None,
                "duration_hours": Decimal("1.00"),
                "end_time": time(0, 0),
            }

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            secretary_event = await secretary_events.create_teaching_event(
                db,
                source_actor=secretary_actor,
                posting_code=values["posting_a"],
                teaching_name_id=pending_name_id,
                global_session_type_id=None,
                event_date=date(2035, 4, 4),
                start_time=time(10, 0),
                cme_points_awarded=False,
                smc_event_code=None,
            )
            created_event_ids.append(secretary_event["id"])
            assert secretary_event["teaching_name_id"] == pending_name_id
            assert secretary_event["created_for_programme_code"] is None

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            pc_updated_secretary_event = (
                await programme_teaching_events.update_teaching_event(
                    db,
                    source_actor=pc_actor,
                    audit_actor=pc_actor.staff_actor,
                    event_id=secretary_event["id"],
                    programme_code=values["programme_a"],
                    posting_code=values["posting_a"],
                    teaching_name_id=pending_name_id,
                    global_session_type_id=None,
                    event_date=date(2035, 4, 4),
                    start_time=time(11, 0),
                    cme_points_awarded=False,
                    smc_event_code=None,
                )
            )
            assert pc_updated_secretary_event["start_time"] == time(11, 0)

        async with _service_runtime_context(
            policy_harness,
            policy_seed.contexts["secretary"],
        ) as db:
            secretary_updated_pc_event = await secretary_events.update_teaching_event(
                db,
                source_actor=secretary_actor,
                posting_code=values["posting_a"],
                event_id=pending_event["id"],
                teaching_name_id=pending_name_id,
                global_session_type_id=None,
                event_date=date(2035, 4, 2),
                start_time=time(22, 0),
                cme_points_awarded=False,
                smc_event_code=None,
            )
            assert secretary_updated_pc_event["start_time"] == time(22, 0)

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["pc"],
        ) as db:
            with pytest.raises(DBAPIError) as denied_cross_programme:
                async with db.begin_nested():
                    await db.execute(
                        text(
                            """
                            INSERT INTO teaching_events (
                                posting_code, created_for_programme_code,
                                teaching_name, event_date, start_time, end_time,
                                duration_hours, is_adhoc, created_by_role,
                                teaching_name_id, global_session_type_id
                            )
                            VALUES (
                                :posting_code, :programme_a, 'F forbidden cross source',
                                DATE '2035-04-05', TIME '10:00', TIME '11:00',
                                1.00, false, 'programme_pc',
                                :cross_programme_name_id, NULL
                            )
                            """
                        ),
                        {
                            "posting_code": values["posting_a"],
                            "programme_a": values["programme_a"],
                            "cross_programme_name_id": cross_programme_name_id,
                        },
                    )
            assert _sqlstate(denied_cross_programme.value) == "42501"

            with pytest.raises(DBAPIError) as denied_source_update:
                async with db.begin_nested():
                    await db.execute(
                        text(
                            """
                            UPDATE teaching_events
                            SET teaching_name_id = :cross_programme_name_id,
                                global_session_type_id = NULL
                            WHERE id = :event_id
                            """
                        ),
                        {
                            "cross_programme_name_id": cross_programme_name_id,
                            "event_id": pending_event["id"],
                        },
                    )
            assert _sqlstate(denied_source_update.value) == "42501"
    finally:
        async with policy_harness.owner_session() as db:
            if created_event_ids:
                event_ids = [str(event_id) for event_id in created_event_ids]
                await db.execute(
                    text(
                        """
                        DELETE FROM audit_logs
                        WHERE entity_type = 'teaching_event'
                          AND entity_id = ANY(CAST(:event_ids AS text[]))
                        """
                    ),
                    {"event_ids": event_ids},
                )
                await db.execute(
                    text("DELETE FROM teaching_events WHERE id = ANY(CAST(:event_ids AS uuid[]))"),
                    {"event_ids": event_ids},
                )
            await db.execute(
                text(
                    """
                    DELETE FROM teaching_names
                    WHERE id IN (:pending_name_id, :cross_programme_name_id)
                    """
                ),
                {
                    "pending_name_id": pending_name_id,
                    "cross_programme_name_id": cross_programme_name_id,
                },
            )
            await db.execute(
                text("DELETE FROM global_session_types WHERE id = :id"),
                {"id": global_session_type_id},
            )
            if original_capability is not None:
                await db.execute(
                    text(
                        """
                        UPDATE secretary_programme_pools
                        SET can_manage_teaching_names = :can_manage_teaching_names
                        WHERE id = :pool_id
                        """
                    ),
                    {
                        "can_manage_teaching_names": original_capability,
                        "pool_id": values["pool_a_id"],
                    },
                )
            await db.commit()
