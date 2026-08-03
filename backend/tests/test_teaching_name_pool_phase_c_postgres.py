from __future__ import annotations

import importlib.util
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.models import TeachingNameMapping
from tests.test_evolved_ttf_b1_postgres import (
    B1_1_REVISION,
    _insert_legacy_fixture_rows,
)
from tests.test_external_registration_migrations_postgres import (
    BACKEND_ROOT,
    MigrationHarness,
    _revision,
    clean_migration_database,
)


PHASE_C_REVISION = "20260803_000031"
PHASE_C_MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260803_000031_add_shared_teaching_name_pool.py"
)


def _load_phase_c_migration() -> object:
    spec = importlib.util.spec_from_file_location(
        "evolved_ttf_phase_c_migration",
        PHASE_C_MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_c_migration_is_linear_and_models_match_pool_cascade() -> None:
    migration = _load_phase_c_migration()
    source = PHASE_C_MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration.revision == PHASE_C_REVISION
    assert migration.down_revision == B1_1_REVISION
    assert 'ondelete="CASCADE"' in source
    assert "reconcile_teaching_name_pending_mappings" in source
    assert "guard_used_teaching_name_delete" in source
    assert "lock_master_teaching_name_delete" in source
    assert "SECURITY DEFINER" in source
    assert "teaching_name_catalogue" not in source

    pool_fk = next(
        constraint
        for constraint in TeachingNameMapping.__table__.foreign_key_constraints
        if constraint.name == "fk_teaching_name_mappings_name_pool"
    )
    assert pool_fk.ondelete == "CASCADE"


def _assert_phase_c_catalogue(connection) -> None:  # noqa: ANN001
    assert connection.scalar(
        text(
            """
            SELECT constraint_row.confdeltype = 'c'
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'teaching_name_mappings'
              AND constraint_row.conname = 'fk_teaching_name_mappings_name_pool'
            """
        )
    ) is True

    function_rows = {
        str(row["proname"]): dict(row)
        for row in connection.execute(
            text(
                """
                SELECT procedure.proname,
                       procedure.prosecdef,
                       procedure.proconfig,
                       NOT EXISTS (
                           SELECT 1
                           FROM pg_catalog.aclexplode(
                               COALESCE(
                                   procedure.proacl,
                                   pg_catalog.acldefault('f', procedure.proowner)
                               )
                           ) AS privilege
                           WHERE privilege.grantee = 0
                             AND privilege.privilege_type = 'EXECUTE'
                       ) AS public_execute_denied,
                       has_function_privilege(
                           'mata_app_runtime', procedure.oid, 'EXECUTE'
                       ) AS runtime_execute,
                       has_function_privilege(
                           'mata_auth_internal', procedure.oid, 'EXECUTE'
                       ) AS auth_execute
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'mata_private'
                  AND procedure.proname IN (
                      'reconcile_teaching_name_pending_mappings',
                      'guard_used_teaching_name_delete'
                  )
                """
            )
        ).mappings()
    }
    assert set(function_rows) == {
        "reconcile_teaching_name_pending_mappings",
        "guard_used_teaching_name_delete",
    }
    for row in function_rows.values():
        assert row["prosecdef"] is True
        assert row["proconfig"] == ["search_path=pg_catalog, pg_temp"]
        assert row["public_execute_denied"] is True
        assert row["runtime_execute"] is False
        assert row["auth_execute"] is False

    master_lock_helper = (
        connection.execute(
            text(
                """
                SELECT procedure.prosecdef,
                       procedure.proconfig,
                       pg_catalog.pg_get_function_result(procedure.oid) AS result_type,
                       NOT EXISTS (
                           SELECT 1
                           FROM pg_catalog.aclexplode(
                               COALESCE(
                                   procedure.proacl,
                                   pg_catalog.acldefault('f', procedure.proowner)
                               )
                           ) AS privilege
                           WHERE privilege.grantee = 0
                             AND privilege.privilege_type = 'EXECUTE'
                       ) AS public_execute_denied,
                       has_function_privilege(
                           'mata_app_runtime', procedure.oid, 'EXECUTE'
                       ) AS runtime_execute,
                       has_function_privilege(
                           'mata_auth_internal', procedure.oid, 'EXECUTE'
                       ) AS auth_execute
                FROM pg_catalog.pg_proc AS procedure
                WHERE procedure.oid = pg_catalog.to_regprocedure(
                    'mata_rls.lock_master_teaching_name_delete(uuid)'
                )
                """
            )
        )
        .mappings()
        .one()
    )
    assert dict(master_lock_helper) == {
        "prosecdef": True,
        "proconfig": ["search_path=pg_catalog, pg_temp"],
        "result_type": "void",
        "public_execute_denied": True,
        "runtime_execute": True,
        "auth_execute": False,
    }

    trigger_names = set(
        connection.scalars(
            text(
                """
                SELECT trigger_row.tgname
                FROM pg_catalog.pg_trigger AS trigger_row
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = trigger_row.tgrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = 'teaching_names'
                  AND trigger_row.tgname IN (
                      'mata_reconcile_teaching_name_pending_mappings',
                      'mata_guard_used_teaching_name_delete'
                  )
                  AND NOT trigger_row.tgisinternal
                """
            )
        )
    )
    assert trigger_names == {
        "mata_reconcile_teaching_name_pending_mappings",
        "mata_guard_used_teaching_name_delete",
    }


@pytest.mark.migration_mutation
def test_phase_c_reconciles_pending_mappings_and_preserves_used_name_history(
    clean_migration_database: MigrationHarness,
) -> None:
    harness = clean_migration_database
    assert harness.alembic("upgrade", B1_1_REVISION).returncode == 0

    with harness.engine.begin() as connection:
        values = _insert_legacy_fixture_rows(connection)

    upgraded = harness.alembic("upgrade", PHASE_C_REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    values.update(
        {
            "extra_target_id": uuid4(),
            "teaching_name_id": uuid4(),
            "other_period_teaching_name_id": uuid4(),
            "external_resident_id": uuid4(),
            "event_id": uuid4(),
            "native_attendance_id": uuid4(),
            "external_attendance_id": uuid4(),
        }
    )
    try:
        with harness.engine.begin() as connection:
            assert _revision(connection) == PHASE_C_REVISION
            _assert_phase_c_catalogue(connection)

            connection.execute(
                text(
                    """
                    INSERT INTO teaching_targets (
                        id, reporting_period_id, programme_code, r_year,
                        posting_code, session_type_id, monthly_target, is_tracked
                    )
                    VALUES (
                        :extra_target_id, :period_id, :programme_a, 'R2',
                        :posting_a, :session_a_id, 1, true
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name
                    )
                    VALUES (
                        :teaching_name_id, :period_id, :programme_a,
                        'Phase C Teaching Name', 'phase c teaching name'
                    )
                    """
                ),
                values,
            )
            created_mappings = connection.execute(
                text(
                    """
                    SELECT id, r_year, teaching_target_id
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    ORDER BY r_year
                    """
                ),
                values,
            ).mappings().all()
            assert [(row["r_year"], row["teaching_target_id"]) for row in created_mappings] == [
                ("R1", None),
                ("R2", None),
            ]
            assert connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_targets
                    WHERE reporting_period_id = :period_id
                      AND programme_code = :programme_a
                      AND posting_code = :posting_a
                      AND r_year = :r_year
                    """
                ),
                values,
            ) == 2
            mapped_r1_id = created_mappings[0]["id"]
            missing_r2_id = created_mappings[1]["id"]
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name
                    )
                    VALUES (
                        :other_period_teaching_name_id, :period_b_id, :programme_a,
                        'Phase C Teaching Name', 'phase c teaching name'
                    )
                    """
                ),
                values,
            )
            assert connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :other_period_teaching_name_id
                    """
                ),
                values,
            ) == 0
            connection.execute(
                text(
                    """
                    UPDATE teaching_name_mappings
                    SET teaching_target_id = :target_a_id
                    WHERE id = :mapped_r1_id
                    """
                ),
                {**values, "mapped_r1_id": mapped_r1_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE teaching_names
                    SET is_active = false
                    WHERE id = :teaching_name_id
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    DELETE FROM teaching_name_mappings
                    WHERE id = :missing_r2_id
                    """
                ),
                {"missing_r2_id": missing_r2_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE teaching_names
                    SET is_active = true
                    WHERE id = :teaching_name_id
                    """
                ),
                values,
            )
            reconciled_mappings = connection.execute(
                text(
                    """
                    SELECT id, r_year, teaching_target_id
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    ORDER BY r_year
                    """
                ),
                values,
            ).mappings().all()
            assert reconciled_mappings[0]["id"] == mapped_r1_id
            assert reconciled_mappings[0]["teaching_target_id"] == values["target_a_id"]
            assert reconciled_mappings[1]["id"] != missing_r2_id
            assert reconciled_mappings[1]["teaching_target_id"] is None

            connection.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, created_for_programme_code, teaching_name,
                        details_of_session, event_date, start_time, end_time,
                        duration_hours, session_type_id, is_adhoc, created_by_role,
                        teaching_name_id
                    )
                    VALUES (
                        :event_id, :posting_a, :programme_a, 'Phase C Teaching Name',
                        'event snapshot is retained', DATE '2045-02-05',
                        TIME '11:00', TIME '12:00', 1.00, :session_a_id,
                        false, 'secretary', :teaching_name_id
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO external_residents (
                        id, name, mcr, home_cluster, current_nhg_posting_code, status
                    )
                    VALUES (
                        :external_resident_id, 'Phase C external resident',
                        :external_mcr, 'NUH', :posting_a, 'active'
                    )
                    """
                ),
                {
                    **values,
                    "external_mcr": f"PC{uuid4().hex[:16].upper()}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO attendance_records (
                        id, resident_id, teaching_event_id, submitted_at, status,
                        posting_code
                    )
                    VALUES (
                        :native_attendance_id, :legacy_resident_id, :event_id,
                        TIMESTAMPTZ '2045-02-05 12:30:00+00', 'submitted', :posting_a
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO external_attendance_records (
                        id, external_resident_id, teaching_event_id, submitted_at,
                        status, posting_code
                    )
                    VALUES (
                        :external_attendance_id, :external_resident_id, :event_id,
                        TIMESTAMPTZ '2045-02-05 12:35:00+00', 'submitted', :posting_a
                    )
                    """
                ),
                values,
            )
            event_snapshot = connection.scalar(
                text(
                    """
                    SELECT to_jsonb(event) - 'teaching_name_id'
                    FROM teaching_events AS event
                    WHERE id = :event_id
                    """
                ),
                values,
            )
            native_snapshot = connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM attendance_records AS attendance
                    WHERE id = :native_attendance_id
                    """
                ),
                values,
            )
            external_snapshot = connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM external_attendance_records AS attendance
                    WHERE id = :external_attendance_id
                    """
                ),
                values,
            )

            connection.execute(
                text("DELETE FROM teaching_names WHERE id = :teaching_name_id"),
                values,
            )
            assert connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM teaching_name_mappings
                    WHERE teaching_name_id = :teaching_name_id
                    """
                ),
                values,
            ) == 0
            assert connection.execute(
                text(
                    """
                    SELECT teaching_name_id, to_jsonb(event) - 'teaching_name_id'
                    FROM teaching_events AS event
                    WHERE id = :event_id
                    """
                ),
                values,
            ).one() == (None, event_snapshot)
            assert connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM attendance_records AS attendance
                    WHERE id = :native_attendance_id
                    """
                ),
                values,
            ) == native_snapshot
            assert connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM external_attendance_records AS attendance
                    WHERE id = :external_attendance_id
                    """
                ),
                values,
            ) == external_snapshot
    finally:
        with harness.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM teaching_names
                    WHERE id = ANY(CAST(:teaching_name_ids AS uuid[]))
                    """
                ),
                {
                    "teaching_name_ids": [
                        values["teaching_name_id"],
                        values["other_period_teaching_name_id"],
                    ]
                },
            )
