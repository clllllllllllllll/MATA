from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
import secrets
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

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
            FROM mata_rls.issue_staff_app_session(
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
            "issue_resident_app_session"
            if subject_type == "resident"
            else "issue_external_resident_app_session"
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
                    FROM mata_rls.resolve_app_session(
                        CAST(:token_digest AS bytea),
                        false,
                        0
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
    assert rls_postgres_harness.revision == "20260726_000026"
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
        "external_a_id",
        "external_b_id",
        "resident_posting_a_id",
        "resident_posting_b_id",
        "external_posting_a_id",
        "external_posting_b_id",
        "catalogue_a_id",
        "catalogue_b_id",
        "catalogue_cross_id",
        "target_a_id",
        "target_b_id",
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
    values["external_a_mcr"] = f"RLEA{suffix}"
    values["external_b_mcr"] = f"RLEB{suffix}"

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
            {**values, "name": f"RLS Session {suffix}"},
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
                    is_adhoc, created_by_role
                )
                VALUES
                    (
                        :event_seed_a_id, :posting_a, :keyword,
                        DATE '2035-03-05', TIME '09:00', TIME '10:00',
                        1.00, :session_type_id, :series_a_id, false,
                        'secretary'
                    ),
                    (
                        :event_action_a_id, :posting_a, :keyword,
                        DATE '2035-03-06', TIME '09:00', TIME '10:00',
                        1.00, :session_type_id, :series_a_id, false,
                        'secretary'
                    ),
                    (
                        :event_b_id, :posting_b, :keyword,
                        DATE '2035-03-05', TIME '09:00', TIME '10:00',
                        1.00, :session_type_id, :series_b_id, false,
                        'secretary'
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
        contexts["external"] = await _issue_context(
            policy_harness,
            subject_type="external_resident",
            subject_id=values["external_a_id"],
            normalized_mcr=values["external_a_mcr"],
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
                    "external_a_id",
                    "external_b_id",
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
                    "teaching_name_catalogue",
                    ("catalogue_a_id", "catalogue_b_id", "catalogue_cross_id"),
                ),
                ("teaching_targets", ("target_a_id", "target_b_id")),
                ("secretary_programme_pools", ("pool_a_id",)),
                ("multi_posting_rules", ("rule_a_id", "rule_b_id")),
                (
                    "external_resident_postings",
                    ("external_posting_a_id", "external_posting_b_id"),
                ),
                (
                    "resident_postings",
                    ("resident_posting_a_id", "resident_posting_b_id"),
                ),
                (
                    "external_residents",
                    ("external_a_id", "external_b_id"),
                ),
                ("residents", ("resident_a_id", "resident_b_id")),
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

    assert len(policy_rows) == 84
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
    """Own-posting attendance counts must not be filtered out by joins."""

    values = policy_seed.values
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
            WHERE id IN (:a, :b)
            """,
            {
                "a": values["external_attendance_a_id"],
                "b": values["external_attendance_b_id"],
            },
        )
        assert external_attendance_ids == {
            values["external_attendance_a_id"]
        }


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
                    id, resident_id, teaching_event_id, status, posting_code
                )
                VALUES (
                    :id, :resident_id, :event_id, 'submitted',
                    :posting_code
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
        updated = await db.scalar(
            text(
                """
                UPDATE attendance_records
                SET status = 'confirmed'
                WHERE id = :id
                RETURNING status
                """
            ),
            {"id": action_id},
        )
        assert updated == "confirmed"
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
                SET status = 'confirmed'
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
        ) == "confirmed"


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
                    status, posting_code
                )
                VALUES (
                    :id, :external_resident_id, :event_id,
                    'submitted', :posting_code
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
        updated = await db.scalar(
            text(
                """
                UPDATE external_attendance_records
                SET status = 'confirmed'
                WHERE id = :id
                RETURNING status
                """
            ),
            {"id": action_id},
        )
        assert updated == "confirmed"
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
                SET status = 'confirmed'
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
        ) == "confirmed"
