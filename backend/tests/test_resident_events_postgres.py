from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.services import auth as auth_service
from app.services import app_sessions
from app.services import resident_submission
from app.services.database_context import (
    AUTH_BOUNDARY_INFO_KEY,
    MataSyncSession,
    configure_request_context,
)


DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_phase_c_verify"
_TEST_SESSION_HASH_KEY = "rls-resident-events-test-session-key-32-bytes"


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
            "PostgreSQL resident-event integration tests require the exact named "
            f"local disposable database {DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


async def _issue_resident_session(
    auth_engine: AsyncEngine,
    settings: Settings,
    *,
    resident_id,
    mcr: str,
) -> app_sessions.CreatedSession:
    session_settings = settings.model_copy(
        update={"mata_session_hash_key": _TEST_SESSION_HASH_KEY}
    )
    async with AsyncSession(auth_engine, expire_on_commit=False) as auth_db:
        auth_db.info[AUTH_BOUNDARY_INFO_KEY] = True
        created = await app_sessions.create_session(
            auth_db,
            session_settings,
            "resident",
            resident_id,
            "mata_resident",
            expected_subject_session_generation=0,
            normalized_mcr=mcr,
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


@pytest.mark.asyncio
async def test_resident_event_discovery_merges_active_periods_and_deduplicates_on_postgres() -> None:
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
            "Resident-event RLS verification requires distinct restricted runtime, "
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
    programme_code = f"RV{suffix}".upper()[:20]
    posting_code = f"RVP{suffix}"
    mcr = f"M{suffix.upper()}"
    resident_id = uuid4()
    posting_id = uuid4()
    programme_id = uuid4()
    session_type_id = uuid4()
    first_period_id = uuid4()
    second_period_id = uuid4()
    inactive_period_id = uuid4()
    first_event_id = uuid4()
    second_event_id = uuid4()
    inactive_event_id = uuid4()
    keyword = f"Resident visibility {suffix}"
    original_period_rows: list[dict[str, object]] = []
    runtime_db: AsyncSession | None = None

    try:
        async with AsyncSession(owner_engine, expire_on_commit=False) as owner_db:
            original_period_rows = [
                dict(row)
                for row in (
                    await owner_db.execute(
                        text(
                            """
                            SELECT id, status, activate_on, deactivate_on
                            FROM reporting_periods
                            """
                        )
                    )
                ).mappings()
            ]
            await owner_db.execute(
                    text(
                        """
                        UPDATE reporting_periods
                        SET status = 'inactive', activate_on = NULL, deactivate_on = NULL
                        """
                    )
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO posting_codes (
                            id, code, display_name, institution, supports_secretary_events
                        )
                        VALUES (:id, :code, :display_name, 'TTSH', true)
                        """
                    ),
                    {"id": posting_id, "code": posting_code, "display_name": posting_code},
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO programmes (
                            id, code, name, ay_date_category, r_year_required,
                            native_teaching_posting_code
                        )
                        VALUES (
                            :id, :code, :name, 'non_im_subspec', false, :posting_code
                        )
                        """
                    ),
                    {
                        "id": programme_id,
                        "code": programme_code,
                        "name": f"Resident visibility {suffix}",
                        "posting_code": posting_code,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO residents (id, name, mcr, programme_code, status)
                        VALUES (:id, :name, :mcr, :programme_code, 'active')
                        """
                    ),
                    {
                        "id": resident_id,
                        "name": f"Resident {suffix}",
                        "mcr": mcr,
                        "programme_code": programme_code,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO reporting_periods (
                            id, label, start_date, end_date, status, deactivate_on
                        )
                        VALUES
                            (:first_id, :first_label, '2025-07-01', '2025-12-31', 'active', '2099-01-01'),
                            (:second_id, :second_label, '2026-01-01', '2026-06-30', 'active', '2099-01-01'),
                            (:inactive_id, :inactive_label, '2024-07-01', '2024-12-31', 'inactive', NULL)
                        """
                    ),
                    {
                        "first_id": first_period_id,
                        "first_label": f"RV1 {suffix}",
                        "second_id": second_period_id,
                        "second_label": f"RV2 {suffix}",
                        "inactive_id": inactive_period_id,
                        "inactive_label": f"RVI {suffix}",
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO resident_postings (
                            id, resident_id, posting_code, reporting_period_id,
                            start_date, end_date, r_year, status
                        )
                        VALUES
                            (:first_id, :resident_id, :posting_code, :first_period_id,
                             '2025-07-15', '2025-07-15', 'ALL', 'active'),
                            (:second_id, :resident_id, :posting_code, :second_period_id,
                             '2026-06-01', '2026-06-30', 'ALL', 'loa_working'),
                            (:inactive_id, :resident_id, :posting_code, :inactive_period_id,
                             '2024-07-01', '2024-07-31', 'ALL', 'active')
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "second_id": uuid4(),
                        "inactive_id": uuid4(),
                        "resident_id": resident_id,
                        "posting_code": posting_code,
                        "first_period_id": first_period_id,
                        "second_period_id": second_period_id,
                        "inactive_period_id": inactive_period_id,
                    },
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO session_types (id, name, duration_hours, duration_label)
                        VALUES (:id, :name, 1.0, '1h')
                        """
                    ),
                    {"id": session_type_id, "name": f"Resident type {suffix} [1h]"},
                )
            await owner_db.execute(
                    text(
                        """
                        INSERT INTO teaching_name_catalogue (
                            id, keyword, session_type_id, posting_code, programme_code,
                            r_year, reporting_period_id, duration_hours, is_tracked
                        )
                        VALUES
                            (:first_id, :keyword, :session_type_id, :posting_code,
                             :programme_code, 'ALL', :first_period_id, 1.0, true),
                            (:second_id, :keyword, :session_type_id, :posting_code,
                             :programme_code, 'ALL', :second_period_id, 1.0, true),
                            (:inactive_id, :keyword, :session_type_id, :posting_code,
                             :programme_code, 'ALL', :inactive_period_id, 1.0, true)
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "second_id": uuid4(),
                        "inactive_id": uuid4(),
                        "keyword": keyword,
                        "session_type_id": session_type_id,
                        "posting_code": posting_code,
                        "programme_code": programme_code,
                        "first_period_id": first_period_id,
                        "second_period_id": second_period_id,
                        "inactive_period_id": inactive_period_id,
                    },
                )
            await owner_db.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, created_for_programme_code, teaching_name,
                        event_date, start_time, end_time, duration_hours,
                        session_type_id, created_by_role
                    )
                    VALUES
                        (:first_id, :posting_code, NULL, :keyword, '2025-07-15', '10:00',
                         '11:00', 1.0, :session_type_id, 'secretary'),
                        (:second_id, :posting_code, :programme_code, :keyword, '2026-06-30', '10:00',
                         '11:00', 1.0, :session_type_id, 'programme_pc'),
                        (:inactive_id, :posting_code, NULL, :keyword, '2024-07-15', '10:00',
                         '11:00', 1.0, :session_type_id, 'secretary')
                    """
                ),
                {
                    "first_id": first_event_id,
                    "second_id": second_event_id,
                    "inactive_id": inactive_event_id,
                    "posting_code": posting_code,
                    "programme_code": programme_code,
                    "keyword": keyword,
                    "session_type_id": session_type_id,
                },
            )

            await owner_db.commit()

        created = await _issue_resident_session(
            auth_engine,
            settings,
            resident_id=resident_id,
            mcr=mcr,
        )
        fingerprint = app_sessions.authorization_fingerprint_for_session(
            created.session
        )
        assert fingerprint is not None
        runtime_db = AsyncSession(
            runtime_engine,
            expire_on_commit=False,
            sync_session_class=MataSyncSession,
        )
        configure_request_context(
            runtime_db,
            token_digest=bytes(created.session.token_digest),
            expected_subject_type="resident",
            expected_subject_id=resident_id,
            expected_app_session_id=created.session.id,
            expected_authorization_fingerprint=fingerprint,
        )

        visible_event_ids = set(
            (
                await runtime_db.scalars(
                    text(
                        """
                        SELECT id
                        FROM teaching_events
                        WHERE id IN (:first_id, :second_id, :inactive_id)
                        """
                    ),
                    {
                        "first_id": first_event_id,
                        "second_id": second_event_id,
                        "inactive_id": inactive_event_id,
                    },
                )
            ).all()
        )
        assert visible_event_ids == {
            first_event_id,
            second_event_id,
            inactive_event_id,
        }
        assert await runtime_db.scalar(
            text("SELECT mata_rls.is_native_resident(:resident_id)"),
            {"resident_id": resident_id},
        ) is True
        assert await runtime_db.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM residents AS resident
                    JOIN programmes AS programme
                      ON programme.code = resident.programme_code
                    JOIN resident_postings AS resident_posting
                      ON resident_posting.resident_id = resident.id
                     AND resident_posting.reporting_period_id = :period_id
                    WHERE resident.id = :resident_id
                      AND resident.programme_code = :programme_code
                      AND (
                          resident_posting.posting_code = :posting_code
                          OR programme.native_teaching_posting_code
                              = :posting_code
                      )
                )
                """
            ),
            {
                "period_id": first_period_id,
                "resident_id": resident_id,
                "programme_code": programme_code,
                "posting_code": posting_code,
            },
        ) is True
        assert await runtime_db.scalar(
            text(
                """
                SELECT mata_rls.can_access_teaching_catalogue(
                    :programme_code,
                    :posting_code,
                    :period_id
                )
                """
            ),
            {
                "programme_code": programme_code,
                "posting_code": posting_code,
                "period_id": first_period_id,
            },
        ) is True
        visible_catalogue_periods = set(
            (
                await runtime_db.scalars(
                    text(
                        """
                        SELECT reporting_period_id
                        FROM teaching_name_catalogue
                        WHERE keyword = :keyword
                        """
                    ),
                    {"keyword": keyword},
                )
            ).all()
        )
        assert visible_catalogue_periods == {
            first_period_id,
            second_period_id,
            inactive_period_id,
        }

        payload = await resident_submission.list_available_events(
            runtime_db,
            resident_id=resident_id,
            today=date(2026, 7, 17),
        )

        assert [row["id"] for row in payload["events"]] == [
            first_event_id,
            second_event_id,
        ], payload
        assert len({row["id"] for row in payload["events"]}) == 2
        assert inactive_event_id not in {row["id"] for row in payload["events"]}
        assert {row["reporting_period_id"] for row in payload["events"]} == {
            first_period_id,
            second_period_id,
        }

        filtered = await resident_submission.list_available_events(
            runtime_db,
            resident_id=resident_id,
            today=date(2026, 7, 17),
            date_from=date(2026, 1, 1),
            date_to=date(2026, 6, 30),
        )
        assert [row["id"] for row in filtered["events"]] == [second_event_id]

        identity = await auth_service.get_current_identity(
            runtime_db,
            role="resident",
            subject_id=resident_id,
        )
        assert identity["mcr"] == mcr
        assert identity["programme_code"] == programme_code
        assert "current_posting_code" not in identity
    finally:
        if runtime_db is not None:
            await runtime_db.rollback()
            await runtime_db.close()
        async with AsyncSession(owner_engine, expire_on_commit=False) as owner_db:
            await owner_db.execute(
                text(
                    """
                    DELETE FROM teaching_events
                    WHERE id IN (:first_id, :second_id, :inactive_id)
                    """
                ),
                {
                    "first_id": first_event_id,
                    "second_id": second_event_id,
                    "inactive_id": inactive_event_id,
                },
            )
            await owner_db.execute(
                text(
                    """
                    DELETE FROM teaching_name_catalogue
                    WHERE reporting_period_id IN (
                        :first_id, :second_id, :inactive_id
                    )
                    """
                ),
                {
                    "first_id": first_period_id,
                    "second_id": second_period_id,
                    "inactive_id": inactive_period_id,
                },
            )
            await owner_db.execute(
                text("DELETE FROM resident_postings WHERE resident_id = :resident_id"),
                {"resident_id": resident_id},
            )
            await owner_db.execute(
                text("DELETE FROM app_sessions WHERE subject_id = :resident_id"),
                {"resident_id": resident_id},
            )
            await owner_db.execute(
                text("DELETE FROM residents WHERE id = :resident_id"),
                {"resident_id": resident_id},
            )
            await owner_db.execute(
                text("DELETE FROM session_types WHERE id = :session_type_id"),
                {"session_type_id": session_type_id},
            )
            await owner_db.execute(
                text(
                    """
                    DELETE FROM reporting_periods
                    WHERE id IN (:first_id, :second_id, :inactive_id)
                    """
                ),
                {
                    "first_id": first_period_id,
                    "second_id": second_period_id,
                    "inactive_id": inactive_period_id,
                },
            )
            await owner_db.execute(
                text("DELETE FROM programmes WHERE id = :programme_id"),
                {"programme_id": programme_id},
            )
            await owner_db.execute(
                text("DELETE FROM posting_codes WHERE id = :posting_id"),
                {"posting_id": posting_id},
            )
            if original_period_rows:
                await owner_db.execute(
                    text(
                        """
                        UPDATE reporting_periods
                        SET status = :status,
                            activate_on = :activate_on,
                            deactivate_on = :deactivate_on
                        WHERE id = :id
                        """
                    ),
                    original_period_rows,
                )
            await owner_db.commit()
        await auth_engine.dispose()
        await runtime_engine.dispose()
        await owner_engine.dispose()
