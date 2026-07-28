from __future__ import annotations

from datetime import date
from decimal import Decimal
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


DISPOSABLE_DATABASE_NAME = "mata_phase5b_aud_m04_atomic_attendance_verify"
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
    keyword = f"PG Shared {suffix}"
    period_id = uuid4()
    session_type_one = uuid4()
    session_type_two = uuid4()
    first_posting_id = uuid4()
    second_posting_id = uuid4()
    programme_id = uuid4()
    pool_id = uuid4()
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
                            id, posting_code, programme_code, is_active
                        )
                        VALUES (:id, :posting_code, :programme_code, true)
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
                        INSERT INTO teaching_name_catalogue (
                            id,
                            keyword,
                            session_type_id,
                            posting_code,
                            programme_code,
                            r_year,
                            reporting_period_id,
                            duration_hours,
                            is_tracked
                        )
                        VALUES
                            (
                                :first_id, :keyword, :first_session_type_id,
                                :first_posting, :programme_code, 'ALL',
                                :reporting_period_id, 2.0, true
                            ),
                            (
                                :second_id, :keyword, :second_session_type_id,
                                :second_posting, :programme_code, 'ALL',
                                :reporting_period_id, 1.0, false
                            )
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "second_id": uuid4(),
                        "keyword": keyword,
                        "first_session_type_id": session_type_one,
                        "second_session_type_id": session_type_two,
                        "first_posting": secretary_posting,
                        "second_posting": second_posting,
                        "programme_code": programme_code,
                        "reporting_period_id": period_id,
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

        pc_option = next(row for row in pc_options if row["keyword"] == keyword)
        secretary_option = next(
            row for row in secretary_options if row["keyword"] == keyword
        )
        expected_postings = sorted([secretary_posting, second_posting])
        assert pc_option["posting_codes"] == expected_postings
        assert secretary_option["posting_codes"] == expected_postings
        assert pc_option["session_type_id"] is None
        assert secretary_option["session_type_id"] is None
        assert secretary_option["is_tracked"] is None
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
                text(
                    "DELETE FROM teaching_name_catalogue "
                    "WHERE reporting_period_id = :period_id"
                ),
                {"period_id": period_id},
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
