from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.services import app_sessions
from app.services import programme_teaching_events, secretary_events
from app.services.database_context import (
    AUTH_BOUNDARY_INFO_KEY,
    MataSyncSession,
    configure_request_context,
)
from tests.postgres_disposable_database import configured_disposable_database_name


DISPOSABLE_DATABASE_NAME = configured_disposable_database_name()
_TEST_SESSION_HASH_KEY = "rls-event-options-test-session-key-32-bytes"


def _assert_local_postgres(database_url: str, *, async_url: bool) -> None:
    url = make_url(database_url)
    allowed_drivers = (
        {"postgresql+asyncpg"}
        if async_url
        else {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    )
    if (
        url.drivername not in allowed_drivers
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.database != DISPOSABLE_DATABASE_NAME
        or not url.username
        or bool(url.query)
    ):
        pytest.fail(
            "PostgreSQL teaching-event integration tests require the exact named "
            f"local disposable database {DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


async def _issue_staff_session(
    auth_engine: AsyncEngine,
    settings: Settings,
    *,
    user_id,
    supabase_user_id,
) -> app_sessions.CreatedSession:
    session_settings = settings.model_copy(
        update={"mata_session_hash_key": _TEST_SESSION_HASH_KEY}
    )
    async with AsyncSession(auth_engine, expire_on_commit=False) as auth_db:
        auth_db.info[AUTH_BOUNDARY_INFO_KEY] = True
        created = await app_sessions.create_session(
            auth_db,
            session_settings,
            "staff",
            user_id,
            "supabase_staff",
            expected_subject_session_generation=0,
            upstream_subject_id=supabase_user_id,
        )
        await auth_db.commit()
        resolved = await app_sessions.resolve_session(
            auth_db,
            session_settings,
            created.session_token,
            touch=False,
        )
        assert resolved is not None
        assert (
            app_sessions.authorization_fingerprint_for_session(resolved)
            is not None
        )
        return app_sessions.CreatedSession(
            session=resolved,
            session_token=created.session_token,
            csrf_token=created.csrf_token,
        )


def _runtime_session(
    runtime_engine: AsyncEngine,
    *,
    user_id,
    created: app_sessions.CreatedSession,
) -> AsyncSession:
    db = AsyncSession(
        runtime_engine,
        expire_on_commit=False,
        sync_session_class=MataSyncSession,
    )
    fingerprint = app_sessions.authorization_fingerprint_for_session(
        created.session
    )
    assert fingerprint is not None
    configure_request_context(
        db,
        token_digest=bytes(created.session.token_digest),
        expected_subject_type="staff",
        expected_subject_id=user_id,
        expected_app_session_id=created.session.id,
        expected_authorization_fingerprint=fingerprint,
    )
    return db


@pytest.mark.asyncio
async def test_programme_and_secretary_options_have_postgres_cardinality_and_scope() -> None:
    settings = Settings(_env_file=None)
    assert settings.auth_database_url is not None
    _assert_local_postgres(settings.database_url, async_url=True)
    _assert_local_postgres(settings.auth_database_url, async_url=True)
    _assert_local_postgres(settings.sync_database_url, async_url=False)
    configured_users = {
        make_url(settings.database_url).username,
        make_url(settings.auth_database_url).username,
        make_url(settings.sync_database_url).username,
    }
    if not settings.database_rls_enabled or len(configured_users) != 3:
        pytest.fail(
            "Teaching-event RLS verification requires distinct restricted runtime, "
            "auth, and owner database logins",
            pytrace=False,
        )
    owner_url = make_url(settings.sync_database_url).set(
        drivername="postgresql+asyncpg"
    )
    owner_engine = create_async_engine(owner_url, poolclass=NullPool)
    runtime_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    auth_engine = create_async_engine(settings.auth_database_url, poolclass=NullPool)

    suffix = uuid4().hex[:10]
    programme_code = f"PG{suffix}".upper()[:20]
    secretary_posting = f"PGSec{suffix}"
    second_posting = f"PGAlt{suffix}"
    pending_keyword = f"PG Pending {suffix}"
    mapped_keyword = f"PG Mapped {suffix}"
    inactive_keyword = f"PG Inactive {suffix}"
    period_id = uuid4()
    session_type_one = uuid4()
    session_type_two = uuid4()
    first_posting_id = uuid4()
    second_posting_id = uuid4()
    programme_id = uuid4()
    pool_id = uuid4()
    pending_name_id = uuid4()
    mapped_name_id = uuid4()
    inactive_name_id = uuid4()
    target_id = uuid4()
    mapping_id = uuid4()
    active_global_id = uuid4()
    inactive_global_id = uuid4()
    pc_user_id = uuid4()
    pc_supabase_user_id = uuid4()
    secretary_user_id = uuid4()
    secretary_supabase_user_id = uuid4()

    try:
        async with AsyncSession(owner_engine, expire_on_commit=False) as owner_db:
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO reporting_periods (
                            id, label, start_date, end_date, status
                        )
                        VALUES (
                            :id, :label, :start_date, :end_date, 'active'
                        )
                        """
                    ),
                    {
                        "id": period_id,
                        "label": f"PG opts {suffix}",
                        "start_date": date(2026, 1, 1),
                        "end_date": date(2026, 12, 31),
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO posting_codes (id, code, institution, department)
                        VALUES
                            (:first_id, :first_code, 'TTSH', NULL),
                            (:second_id, :second_code, NULL, NULL)
                        """
                    ),
                    {
                        "first_id": first_posting_id,
                        "first_code": secretary_posting,
                        "second_id": second_posting_id,
                        "second_code": second_posting,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO programmes (
                            id, code, name, ay_date_category, r_year_required
                        )
                        VALUES (
                            :id, :code, :name, 'non_im_subspec', false
                        )
                        """
                    ),
                    {
                        "id": programme_id,
                        "code": programme_code,
                        "name": f"PostgreSQL options {suffix}",
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO users (
                            id, email, supabase_user_id, password_hash, role,
                            name, posting_code, programme_scope, admin_level,
                            is_active, session_generation,
                            session_issuance_blocked
                        )
                        VALUES
                            (
                                :pc_id, :pc_email, :pc_supabase_id,
                                'not-used', 'admin', 'PostgreSQL options PC',
                                NULL, ARRAY[:programme_code]::text[],
                                'programme', true, 0, false
                            ),
                            (
                                :secretary_id, :secretary_email,
                                :secretary_supabase_id, 'not-used',
                                'secretary', 'PostgreSQL options secretary',
                                :secretary_posting, NULL, 'programme',
                                true, 0, false
                            )
                        """
                    ),
                    {
                        "pc_id": pc_user_id,
                        "pc_email": f"pc-{suffix}@example.test",
                        "pc_supabase_id": pc_supabase_user_id,
                        "programme_code": programme_code,
                        "secretary_id": secretary_user_id,
                        "secretary_email": f"secretary-{suffix}@example.test",
                        "secretary_supabase_id": secretary_supabase_user_id,
                        "secretary_posting": secretary_posting,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO session_types (id, name, duration_hours, duration_label)
                        VALUES
                            (:first_id, :first_name, 2.0, '2h'),
                            (:second_id, :second_name, 1.0, '1h')
                        """
                    ),
                    {
                        "first_id": session_type_one,
                        "first_name": f"PG Type A {suffix} [2h]",
                        "second_id": session_type_two,
                        "second_name": f"PG Type B {suffix} [1h]",
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO secretary_programme_pools (
                            id, posting_code, programme_code, is_active,
                            can_manage_teaching_names
                        )
                        VALUES (:id, :posting_code, :programme_code, true, true)
                        """
                    ),
                    {
                        "id": pool_id,
                        "posting_code": secretary_posting,
                        "programme_code": programme_code,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO teaching_names (
                            id, reporting_period_id, programme_code,
                            display_name, normalized_name, is_active,
                            created_by_role, visibility_scope,
                            origin_posting_code
                        )
                        VALUES
                            (
                                :pending_id, :period_id, :programme_code,
                                :pending_name, :pending_normalized, true,
                                'secretary', 'department_shared', :posting_code
                            ),
                            (
                                :mapped_id, :period_id, :programme_code,
                                :mapped_name, :mapped_normalized, true,
                                'secretary', 'department_shared', :posting_code
                            ),
                            (
                                :inactive_id, :period_id, :programme_code,
                                :inactive_name, :inactive_normalized, false,
                                'secretary', 'department_shared', :posting_code
                            )
                        """
                    ),
                    {
                        "pending_id": pending_name_id,
                        "mapped_id": mapped_name_id,
                        "inactive_id": inactive_name_id,
                        "period_id": period_id,
                        "programme_code": programme_code,
                        "posting_code": secretary_posting,
                        "pending_name": pending_keyword,
                        "pending_normalized": pending_keyword.lower(),
                        "mapped_name": mapped_keyword,
                        "mapped_normalized": mapped_keyword.lower(),
                        "inactive_name": inactive_keyword,
                        "inactive_normalized": inactive_keyword.lower(),
                    },
                )
            await owner_db.execute(
                text(
                    """
                        INSERT INTO teaching_name_programme_scopes (
                            teaching_name_id, reporting_period_id, programme_code,
                            admission_reason, admitted_by_user_id
                        )
                        VALUES
                            (:pending_id, :period_id, :programme_code,
                             'owner_programme', :secretary_id),
                            (:mapped_id, :period_id, :programme_code,
                             'owner_programme', :secretary_id),
                            (:inactive_id, :period_id, :programme_code,
                             'owner_programme', :secretary_id)
                    """
                ),
                {
                    "pending_id": pending_name_id,
                    "mapped_id": mapped_name_id,
                    "inactive_id": inactive_name_id,
                    "period_id": period_id,
                    "programme_code": programme_code,
                    "secretary_id": secretary_user_id,
                },
            )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO teaching_targets (
                            id, reporting_period_id, programme_code, r_year,
                            posting_code, session_type_id, monthly_target,
                            is_tracked
                        )
                        VALUES (
                            :id, :period_id, :programme_code, 'ALL',
                            :posting_code, :session_type_id, 1, true
                        )
                        """
                    ),
                    {
                        "id": target_id,
                        "period_id": period_id,
                        "programme_code": programme_code,
                        "posting_code": secretary_posting,
                        "session_type_id": session_type_one,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO teaching_name_mappings (
                            id, teaching_name_id, reporting_period_id,
                            programme_code, posting_code, r_year,
                            teaching_target_id
                        )
                        VALUES
                            (
                                :id, :teaching_name_id, :period_id,
                                :programme_code, :posting_code, 'ALL', :target_id
                            ),
                            (
                                gen_random_uuid(), :pending_name_id, :period_id,
                                :programme_code, :posting_code, 'ALL', NULL
                            )
                        """
                    ),
                    {
                        "id": mapping_id,
                        "teaching_name_id": mapped_name_id,
                        "pending_name_id": pending_name_id,
                        "period_id": period_id,
                        "programme_code": programme_code,
                        "posting_code": secretary_posting,
                        "target_id": target_id,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO global_session_types (
                            id, name, duration_hours, is_active
                        )
                        VALUES
                            (:active_id, :active_name, 1.0, true),
                            (:inactive_id, :inactive_name, 1.0, false)
                        """
                    ),
                    {
                        "active_id": active_global_id,
                        "active_name": f"PG Global Active {suffix}",
                        "inactive_id": inactive_global_id,
                        "inactive_name": f"PG Global Inactive {suffix}",
                    },
                )
            await owner_db.commit()

        pc_session = await _issue_staff_session(
            auth_engine,
            settings,
            user_id=pc_user_id,
            supabase_user_id=pc_supabase_user_id,
        )
        secretary_session = await _issue_staff_session(
            auth_engine,
            settings,
            user_id=secretary_user_id,
            supabase_user_id=secretary_supabase_user_id,
        )
        async with _runtime_session(
            runtime_engine,
            user_id=pc_user_id,
            created=pc_session,
        ) as pc_db:
            pc_options = await programme_teaching_events.teaching_name_options(
                pc_db,
                programme_code=programme_code,
                reporting_period_id=period_id,
            )
        async with _runtime_session(
            runtime_engine,
            user_id=secretary_user_id,
            created=secretary_session,
        ) as secretary_db:
            secretary_options = await secretary_events.teaching_name_options(
                secretary_db,
                posting_code=secretary_posting,
                reporting_period_id=period_id,
            )

        for options in (pc_options, secretary_options):
            by_keyword = {row["keyword"]: row for row in options}
            assert by_keyword[pending_keyword]["teaching_name_id"] == pending_name_id
            assert by_keyword[mapped_keyword]["teaching_name_id"] == mapped_name_id
            assert by_keyword[pending_keyword]["programme_code"] == programme_code
            assert by_keyword[mapped_keyword]["programme_code"] == programme_code
            assert by_keyword[pending_keyword]["global_session_type_id"] is None
            assert by_keyword[mapped_keyword]["global_session_type_id"] is None
            assert by_keyword[f"PG Global Active {suffix}"][
                "global_session_type_id"
            ] == active_global_id
            assert inactive_keyword not in by_keyword
            assert f"PG Global Inactive {suffix}" not in by_keyword
    finally:
        async with AsyncSession(owner_engine, expire_on_commit=False) as owner_db:
            await owner_db.execute(
                text(
                    """
                    DELETE FROM app_sessions
                    WHERE subject_id IN (:pc_id, :secretary_id)
                    """
                ),
                {"pc_id": pc_user_id, "secretary_id": secretary_user_id},
            )
            await owner_db.execute(
                text("DELETE FROM teaching_name_mappings WHERE id = :id"),
                {"id": mapping_id},
            )
            await owner_db.execute(
                text("DELETE FROM teaching_names WHERE reporting_period_id = :period_id"),
                {"period_id": period_id},
            )
            await owner_db.execute(
                text("DELETE FROM teaching_targets WHERE id = :id"),
                {"id": target_id},
            )
            await owner_db.execute(
                text("DELETE FROM global_session_types WHERE id IN (:active_id, :inactive_id)"),
                {"active_id": active_global_id, "inactive_id": inactive_global_id},
            )
            await owner_db.execute(
                text(
                    "DELETE FROM secretary_programme_pools WHERE id = :pool_id"
                ),
                {"pool_id": pool_id},
            )
            await owner_db.execute(
                text(
                    """
                    DELETE FROM session_types
                    WHERE id IN (:first_id, :second_id)
                    """
                ),
                {"first_id": session_type_one, "second_id": session_type_two},
            )
            await owner_db.execute(
                text("DELETE FROM reporting_periods WHERE id = :period_id"),
                {"period_id": period_id},
            )
            await owner_db.execute(
                text(
                    """
                    DELETE FROM users
                    WHERE id IN (:pc_id, :secretary_id)
                    """
                ),
                {"pc_id": pc_user_id, "secretary_id": secretary_user_id},
            )
            await owner_db.execute(
                text("DELETE FROM programmes WHERE id = :programme_id"),
                {"programme_id": programme_id},
            )
            await owner_db.execute(
                text(
                    """
                    DELETE FROM posting_codes
                    WHERE id IN (:first_id, :second_id)
                    """
                ),
                {"first_id": first_posting_id, "second_id": second_posting_id},
            )
            await owner_db.commit()
        await auth_engine.dispose()
        await runtime_engine.dispose()
        await owner_engine.dispose()
