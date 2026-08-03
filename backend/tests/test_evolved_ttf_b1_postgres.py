from __future__ import annotations

import importlib.util
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.models import TeachingName, TeachingNameMapping, TeachingTarget
from app.models.posting import SecretaryProgrammePool
from app.models.teaching import TeachingEvent
from tests.test_external_registration_migrations_postgres import (
    BACKEND_ROOT,
    MigrationHarness,
    _revision,
    clean_migration_database,
)


PREVIOUS_REVISION = "20260728_000028"
B1_REVISION = "20260802_000029"
B1_1_REVISION = "20260803_000030"
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260802_000029_evolved_ttf_teaching_name_foundation.py"
)
B1_1_MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260803_000030_preserve_events_when_teaching_names_deleted.py"
)


def _load_b1_migration() -> object:
    spec = importlib.util.spec_from_file_location("evolved_ttf_b1_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_b1_1_migration() -> object:
    spec = importlib.util.spec_from_file_location(
        "evolved_ttf_b1_1_migration",
        B1_1_MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_integrity_violation(
    connection: Connection,
    statement: str,
    parameters: dict[str, object],
    *,
    constraint_name: str | None,
) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(IntegrityError) as caught:
            connection.execute(text(statement), parameters)
    finally:
        if savepoint.is_active:
            savepoint.rollback()

    diagnostic = getattr(caught.value.orig, "diag", None)
    assert getattr(diagnostic, "constraint_name", None) == constraint_name


def _insert_legacy_fixture_rows(connection: Connection) -> dict[str, object]:
    suffix = uuid4().hex[:12].upper()
    values: dict[str, object] = {
        "period_id": uuid4(),
        "period_b_id": uuid4(),
        "programme_a_id": uuid4(),
        "programme_b_id": uuid4(),
        "posting_a_id": uuid4(),
        "posting_b_id": uuid4(),
        "session_a_id": uuid4(),
        "session_b_id": uuid4(),
        "target_a_id": uuid4(),
        "target_a_second_session_id": uuid4(),
        "target_b_id": uuid4(),
        "legacy_catalogue_id": uuid4(),
        "pool_a_id": uuid4(),
        "legacy_resident_id": uuid4(),
        "legacy_event_id": uuid4(),
        "legacy_attendance_id": uuid4(),
    }
    values["programme_a"] = f"B1A{suffix}"
    values["programme_b"] = f"B1B{suffix}"
    values["posting_a"] = f"B1PA{suffix}"
    values["posting_b"] = f"B1PB{suffix}"
    values["r_year"] = "R1"
    values["legacy_keyword"] = f"Legacy B1 {suffix}"

    connection.execute(
        text(
            """
            INSERT INTO posting_codes (
                id, code, display_name, institution, department,
                supports_secretary_events
            )
            VALUES
                (:posting_a_id, :posting_a, :posting_a, 'B1 test', 'A', true),
                (:posting_b_id, :posting_b, :posting_b, 'B1 test', 'B', true)
            """
        ),
        values,
    )
    connection.execute(
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
    connection.execute(
        text(
            """
            INSERT INTO reporting_periods (
                id, label, start_date, end_date, status
            )
            VALUES (
                :period_id, :label, DATE '2045-01-01', DATE '2045-12-31',
                'active'
            ), (
                :period_b_id, :label_b, DATE '2046-01-01', DATE '2046-12-31',
                'active'
            )
            """
        ),
        {
            **values,
            "label": f"B1 migration {suffix}",
            "label_b": f"B1 other pool {suffix}",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO session_types (id, name, duration_hours, duration_label)
            VALUES
                (:session_a_id, :session_a_name, 1.00, '1h'),
                (:session_b_id, :session_b_name, 2.00, '2h')
            """
        ),
        {
            **values,
            "session_a_name": f"B1 A {suffix}",
            "session_b_name": f"B1 B {suffix}",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO teaching_targets (
                id, reporting_period_id, programme_code, r_year, posting_code,
                session_type_id, monthly_target, is_tracked, details_of_training
            )
            VALUES
                (
                    :target_a_id, :period_id, :programme_a, :r_year, :posting_a,
                    :session_a_id, 2, true, 'Legacy details remain untouched'
                ),
                (
                    :target_a_second_session_id, :period_id, :programme_a,
                    :r_year, :posting_a, :session_b_id, 3, true,
                    'Second retained legacy session type'
                ),
                (
                    :target_b_id, :period_id, :programme_b, :r_year, :posting_b,
                    :session_a_id, 1, true, NULL
                )
            """
        ),
        values,
    )
    connection.execute(
        text(
            """
            INSERT INTO teaching_name_catalogue (
                id, keyword, session_type_id, posting_code, programme_code,
                r_year, reporting_period_id, duration_hours, is_tracked
            )
            VALUES (
                :legacy_catalogue_id, :legacy_keyword, :session_a_id,
                :posting_a, :programme_a, :r_year, :period_id, 1.00, true
            )
            """
        ),
        values,
    )
    connection.execute(
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
    connection.execute(
        text(
            """
            INSERT INTO residents (id, name, mcr, programme_code, r_year)
            VALUES (
                :legacy_resident_id, :legacy_resident_name,
                :legacy_resident_mcr, :programme_a, :r_year
            )
            """
        ),
        {
            **values,
            "legacy_resident_name": f"Legacy B1 Resident {suffix}",
            "legacy_resident_mcr": f"B1{suffix}",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO teaching_events (
                id, posting_code, teaching_name, event_date, start_time,
                end_time, duration_hours, session_type_id, is_adhoc
            )
            VALUES (
                :legacy_event_id, :posting_a, :legacy_event_name,
                DATE '2045-01-15', TIME '09:00', TIME '10:00', 1.00,
                :session_a_id, false
            )
            """
        ),
        {**values, "legacy_event_name": f"Legacy B1 Event {suffix}"},
    )
    connection.execute(
        text(
            """
            INSERT INTO attendance_records (
                id, resident_id, teaching_event_id, submitted_at, status,
                posting_code
            )
            VALUES (
                :legacy_attendance_id, :legacy_resident_id, :legacy_event_id,
                TIMESTAMPTZ '2045-01-15 10:30:00+00', 'submitted', :posting_a
            )
            """
        ),
        values,
    )
    values["global_session_type_id"] = connection.scalar(
        text("SELECT id FROM global_session_types ORDER BY id LIMIT 1")
    )
    assert values["global_session_type_id"] is not None
    return values


def _legacy_snapshot(
    connection: Connection,
    values: dict[str, object],
) -> tuple[
    tuple[object, ...],
    tuple[object, ...],
    tuple[object, ...],
    tuple[object, ...],
]:
    targets = tuple(
        connection.execute(
            text(
                """
                SELECT id, reporting_period_id, programme_code, r_year,
                       posting_code, session_type_id, monthly_target,
                       details_of_training
                FROM teaching_targets
                WHERE id IN (
                    :target_a_id, :target_a_second_session_id, :target_b_id
                )
                ORDER BY id
                """
            ),
            values,
        )
    )
    catalogue = tuple(
        connection.execute(
            text(
                """
                SELECT id, keyword, session_type_id, posting_code,
                       programme_code, r_year, reporting_period_id,
                       duration_hours, is_tracked
                FROM teaching_name_catalogue
                WHERE id = :legacy_catalogue_id
                """
            ),
            values,
        )
    )
    legacy_events = tuple(
        connection.scalars(
            text(
                """
                SELECT to_jsonb(event) - ARRAY[
                    'teaching_name_id', 'global_session_type_id'
                ]::text[]
                FROM teaching_events AS event
                WHERE id = :legacy_event_id
                ORDER BY id
                """
            ),
            values,
        )
    )
    legacy_attendance = tuple(
        connection.scalars(
            text(
                """
                SELECT to_jsonb(attendance)
                FROM attendance_records AS attendance
                WHERE id = :legacy_attendance_id
                ORDER BY id
                """
            ),
            values,
        )
    )
    return targets, catalogue, legacy_events, legacy_attendance


def _assert_b1_schema_catalogue(connection: Connection) -> None:
    expected_constraints = {
        (
            "teaching_names",
            "uq_teaching_names_pool_normalized_name",
        ): (
            "u",
            ("reporting_period_id", "programme_code", "normalized_name"),
            None,
            (),
            None,
            "UNIQUE (reporting_period_id, programme_code, normalized_name)",
        ),
        ("teaching_names", "uq_teaching_names_id_pool"): (
            "u",
            ("id", "reporting_period_id", "programme_code"),
            None,
            (),
            None,
            "UNIQUE (id, reporting_period_id, programme_code)",
        ),
        ("teaching_targets", "uq_teaching_targets_id_mapping_scope"): (
            "u",
            (
                "id",
                "reporting_period_id",
                "programme_code",
                "posting_code",
                "r_year",
            ),
            None,
            (),
            None,
            (
                "UNIQUE (id, reporting_period_id, programme_code, posting_code, "
                "r_year)"
            ),
        ),
        ("teaching_name_mappings", "uq_teaching_name_mappings_identity"): (
            "u",
            ("teaching_name_id", "posting_code", "r_year"),
            None,
            (),
            None,
            "UNIQUE (teaching_name_id, posting_code, r_year)",
        ),
        ("teaching_name_mappings", "fk_teaching_name_mappings_name_pool"): (
            "f",
            ("teaching_name_id", "reporting_period_id", "programme_code"),
            "teaching_names",
            ("id", "reporting_period_id", "programme_code"),
            "RESTRICT",
            (
                "FOREIGN KEY (teaching_name_id, reporting_period_id, programme_code) "
                "REFERENCES teaching_names(id, reporting_period_id, programme_code) "
                "ON DELETE RESTRICT"
            ),
        ),
        ("teaching_name_mappings", "fk_teaching_name_mappings_target_scope"): (
            "f",
            (
                "teaching_target_id",
                "reporting_period_id",
                "programme_code",
                "posting_code",
                "r_year",
            ),
            "teaching_targets",
            (
                "id",
                "reporting_period_id",
                "programme_code",
                "posting_code",
                "r_year",
            ),
            "RESTRICT",
            (
                "FOREIGN KEY (teaching_target_id, reporting_period_id, programme_code, "
                "posting_code, r_year) REFERENCES teaching_targets(id, "
                "reporting_period_id, programme_code, posting_code, r_year) "
                "ON DELETE RESTRICT"
            ),
        ),
        ("teaching_events", "fk_teaching_events_teaching_name"): (
            "f",
            ("teaching_name_id",),
            "teaching_names",
            ("id",),
            "SET NULL",
            (
                "FOREIGN KEY (teaching_name_id) REFERENCES teaching_names(id) "
                "ON DELETE SET NULL"
            ),
        ),
    }
    constraint_rows = {
        (str(row["table_name"]), str(row["constraint_name"])): (
            str(row["constraint_type"]),
            tuple(str(column) for column in row["local_columns"]),
            str(row["foreign_table"]) if row["foreign_table"] is not None else None,
            tuple(str(column) for column in row["foreign_columns"]),
            str(row["delete_action"]) if row["delete_action"] is not None else None,
            str(row["definition"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT relation.relname AS table_name,
                       constraint_row.conname AS constraint_name,
                       constraint_row.contype AS constraint_type,
                       ARRAY(
                           SELECT attribute.attname
                           FROM unnest(constraint_row.conkey)
                                WITH ORDINALITY AS key_column(attnum, ordinality)
                           JOIN pg_catalog.pg_attribute AS attribute
                             ON attribute.attrelid = relation.oid
                            AND attribute.attnum = key_column.attnum
                           ORDER BY key_column.ordinality
                       ) AS local_columns,
                       foreign_relation.relname AS foreign_table,
                       ARRAY(
                           SELECT attribute.attname
                           FROM unnest(constraint_row.confkey)
                                WITH ORDINALITY AS key_column(attnum, ordinality)
                           JOIN pg_catalog.pg_attribute AS attribute
                             ON attribute.attrelid = foreign_relation.oid
                            AND attribute.attnum = key_column.attnum
                           ORDER BY key_column.ordinality
                       ) AS foreign_columns,
                       CASE constraint_row.confdeltype
                           WHEN 'r' THEN 'RESTRICT'
                           WHEN 'a' THEN 'NO ACTION'
                           WHEN 'c' THEN 'CASCADE'
                           WHEN 'n' THEN 'SET NULL'
                           WHEN 'd' THEN 'SET DEFAULT'
                           ELSE NULL
                       END AS delete_action,
                       pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
                           AS definition
                FROM pg_catalog.pg_constraint AS constraint_row
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = constraint_row.conrelid
                LEFT JOIN pg_catalog.pg_class AS foreign_relation
                  ON foreign_relation.oid = constraint_row.confrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND (relation.relname, constraint_row.conname) IN (
                      ('teaching_names', 'uq_teaching_names_pool_normalized_name'),
                      ('teaching_names', 'uq_teaching_names_id_pool'),
                       ('teaching_targets', 'uq_teaching_targets_id_mapping_scope'),
                       ('teaching_name_mappings', 'uq_teaching_name_mappings_identity'),
                       ('teaching_name_mappings', 'fk_teaching_name_mappings_name_pool'),
                       ('teaching_name_mappings', 'fk_teaching_name_mappings_target_scope'),
                       ('teaching_events', 'fk_teaching_events_teaching_name')
                  )
                """
            )
        ).mappings()
    }
    assert constraint_rows == expected_constraints

    expected_indexes = {
        ("teaching_names", "idx_teaching_names_active_pool"): (
            ("reporting_period_id", "programme_code", "display_name"),
            "(is_active = true)",
        ),
        ("teaching_names", "idx_teaching_names_normalized_lookup"): (
            ("reporting_period_id", "programme_code", "normalized_name"),
            None,
        ),
        ("teaching_name_mappings", "idx_teaching_name_mappings_pending_scope"): (
            ("reporting_period_id", "programme_code", "posting_code", "r_year"),
            "(teaching_target_id IS NULL)",
        ),
        ("teaching_name_mappings", "idx_teaching_name_mappings_mapped_scope"): (
            (
                "reporting_period_id",
                "programme_code",
                "posting_code",
                "r_year",
                "teaching_target_id",
            ),
            "(teaching_target_id IS NOT NULL)",
        ),
        ("teaching_name_mappings", "idx_teaching_name_mappings_target_reverse"): (
            ("teaching_target_id",),
            "(teaching_target_id IS NOT NULL)",
        ),
        ("teaching_name_mappings", "idx_teaching_name_mappings_name"): (
            ("teaching_name_id",),
            None,
        ),
        ("teaching_events", "idx_teaching_events_teaching_name"): (
            ("teaching_name_id",),
            "(teaching_name_id IS NOT NULL)",
        ),
        ("teaching_events", "idx_teaching_events_global_session_type"): (
            ("global_session_type_id",),
            "(global_session_type_id IS NOT NULL)",
        ),
    }
    index_rows = {
        (str(row["table_name"]), str(row["index_name"])): (
            tuple(str(column) for column in row["columns"]),
            str(row["predicate"]) if row["predicate"] is not None else None,
        )
        for row in connection.execute(
            text(
                """
                SELECT relation.relname AS table_name,
                       index_relation.relname AS index_name,
                       ARRAY(
                           SELECT pg_catalog.pg_get_indexdef(
                               index_row.indexrelid,
                               key_column.ordinality::integer,
                               true
                           )
                           FROM unnest(index_row.indkey)
                                WITH ORDINALITY AS key_column(attnum, ordinality)
                           WHERE key_column.ordinality <= index_row.indnkeyatts
                           ORDER BY key_column.ordinality
                       ) AS columns,
                       pg_catalog.pg_get_expr(index_row.indpred, index_row.indrelid)
                           AS predicate
                FROM pg_catalog.pg_index AS index_row
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = index_row.indrelid
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_row.indexrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND index_relation.relname IN (
                      'idx_teaching_names_active_pool',
                      'idx_teaching_names_normalized_lookup',
                      'idx_teaching_name_mappings_pending_scope',
                      'idx_teaching_name_mappings_mapped_scope',
                      'idx_teaching_name_mappings_target_reverse',
                      'idx_teaching_name_mappings_name',
                      'idx_teaching_events_teaching_name',
                      'idx_teaching_events_global_session_type'
                  )
                """
            )
        ).mappings()
    }
    assert index_rows == expected_indexes


def _teaching_event_name_fk_delete_action(connection: Connection) -> str | None:
    return connection.scalar(
        text(
            """
            SELECT constraint_row.confdeltype
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'teaching_events'
              AND constraint_row.conname = 'fk_teaching_events_teaching_name'
            """
        )
    )


def _assert_b1_catalogue(connection: Connection) -> None:
    _assert_b1_schema_catalogue(connection)
    table_rows = connection.execute(
        text(
            """
            SELECT relation.relname, relation.relrowsecurity,
                   relation.relforcerowsecurity
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname IN ('teaching_names', 'teaching_name_mappings')
            ORDER BY relation.relname
            """
        )
    ).all()
    assert table_rows == [
        ("teaching_name_mappings", True, False),
        ("teaching_names", True, False),
    ]

    policies = {
        (str(row["table_name"]), str(row["policy_name"]), str(row["action"]))
        for row in connection.execute(
            text(
                """
                SELECT relation.relname AS table_name,
                       policy.polname AS policy_name,
                       CASE policy.polcmd
                           WHEN 'r' THEN 'SELECT'
                           WHEN 'a' THEN 'INSERT'
                           WHEN 'w' THEN 'UPDATE'
                           WHEN 'd' THEN 'DELETE'
                       END AS action
                FROM pg_catalog.pg_policy AS policy
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = policy.polrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname IN ('teaching_names', 'teaching_name_mappings')
                """
            )
        ).mappings()
    }
    assert policies == {
        ("teaching_names", "mata_rls_teaching_names_select", "SELECT"),
        ("teaching_names", "mata_rls_teaching_names_insert", "INSERT"),
        ("teaching_names", "mata_rls_teaching_names_update", "UPDATE"),
        ("teaching_names", "mata_rls_teaching_names_delete", "DELETE"),
        (
            "teaching_name_mappings",
            "mata_rls_teaching_name_mappings_select",
            "SELECT",
        ),
        (
            "teaching_name_mappings",
            "mata_rls_teaching_name_mappings_insert",
            "INSERT",
        ),
        (
            "teaching_name_mappings",
            "mata_rls_teaching_name_mappings_update",
            "UPDATE",
        ),
        (
            "teaching_name_mappings",
            "mata_rls_teaching_name_mappings_delete",
            "DELETE",
        ),
    }


def _cleanup_b1_fixture_rows(
    connection: Connection,
    values: dict[str, object],
) -> None:
    for table_name, ids in (
        (
            "attendance_records",
            [
                values["legacy_attendance_id"],
                values["preservation_native_attendance_id"],
            ],
        ),
        (
            "external_attendance_records",
            [values["preservation_external_attendance_id"]],
        ),
        (
            "teaching_events",
            [
                values["legacy_event_id"],
                values["null_identity_event_id"],
                values["name_event_id"],
                values["global_event_id"],
                values["preservation_event_id"],
            ],
        ),
        (
            "teaching_name_mappings",
            [values["mapped_mapping_id"], values["pending_mapping_id"]],
        ),
        ("teaching_name_catalogue", [values["legacy_catalogue_id"]]),
        (
            "teaching_names",
            [
                values["teaching_name_a_id"],
                values["teaching_name_a_cross_id"],
                values["teaching_name_b_id"],
                values["teaching_name_other_pool_id"],
            ],
        ),
        (
            "teaching_targets",
            [
                values["target_a_id"],
                values["target_a_second_session_id"],
                values["target_b_id"],
            ],
        ),
        ("secretary_programme_pools", [values["pool_a_id"]]),
        ("session_types", [values["session_a_id"], values["session_b_id"]]),
        ("residents", [values["legacy_resident_id"]]),
        ("external_residents", [values["preservation_external_resident_id"]]),
        ("reporting_periods", [values["period_id"], values["period_b_id"]]),
        ("programmes", [values["programme_a_id"], values["programme_b_id"]]),
        ("posting_codes", [values["posting_a_id"], values["posting_b_id"]]),
    ):
        connection.execute(
            text(
                f'DELETE FROM public."{table_name}" '
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": ids},
        )


def test_b1_migration_is_additive_and_linear() -> None:
    migration = _load_b1_migration()
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration.revision == B1_REVISION
    assert migration.down_revision == PREVIOUS_REVISION
    assert "op.drop_table(\"teaching_name_catalogue\")" not in source
    assert "op.drop_column(\"teaching_targets\"" not in source
    assert "can_manage_teaching_names" in source
    assert "TTSHGerMed" in source
    assert "GERI" in source


def test_b1_1_migration_changes_only_event_identity_delete_action() -> None:
    migration = _load_b1_1_migration()
    source = B1_1_MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration.revision == B1_1_REVISION
    assert migration.down_revision == B1_REVISION
    assert source.count('"fk_teaching_events_teaching_name"') == 4
    assert 'ondelete="SET NULL"' in source
    assert 'ondelete="RESTRICT"' in source
    assert "teaching_name_catalogue" not in source
    assert "attendance_records" not in source


def test_b1_models_expose_the_database_foundation() -> None:
    assert {
        "reporting_period_id",
        "programme_code",
        "display_name",
        "normalized_name",
        "is_active",
        "revision",
        "created_by_user_id",
        "updated_by_user_id",
        "deactivated_by_user_id",
        "deactivated_at",
    } <= set(TeachingName.__table__.columns.keys())
    assert {
        "teaching_name_id",
        "reporting_period_id",
        "programme_code",
        "posting_code",
        "r_year",
        "teaching_target_id",
        "revision",
    } <= set(TeachingNameMapping.__table__.columns.keys())
    assert "uq_teaching_targets_id_mapping_scope" in {
        constraint.name for constraint in TeachingTarget.__table__.constraints
    }
    assert "can_manage_teaching_names" in SecretaryProgrammePool.__table__.columns.keys()
    assert {
        "teaching_name_id",
        "global_session_type_id",
    } <= set(TeachingEvent.__table__.columns.keys())
    teaching_name_fk = next(
        foreign_key
        for foreign_key in TeachingEvent.__table__.c.teaching_name_id.foreign_keys
        if foreign_key.target_fullname == "teaching_names.id"
    )
    assert teaching_name_fk.ondelete == "SET NULL"


@pytest.mark.migration_mutation
def test_b1_1_migration_preserves_legacy_ttf_and_enforces_foundation_constraints(
    clean_migration_database: MigrationHarness,
) -> None:
    harness = clean_migration_database
    assert harness.alembic("upgrade", PREVIOUS_REVISION).returncode == 0

    with harness.engine.begin() as connection:
        values = _insert_legacy_fixture_rows(connection)
        before_snapshot = _legacy_snapshot(connection, values)
        connection.execute(
            text(
                """
                UPDATE secretary_programme_pools
                SET is_active = false
                WHERE posting_code = 'TTSHGerMed' AND programme_code = 'GERI'
                """
            )
        )

    rejected = harness.alembic("upgrade", B1_1_REVISION)
    assert rejected.returncode != 0
    assert "Expected exactly one active approved Teaching Name pilot pool" in (
        rejected.stdout + rejected.stderr
    )
    with harness.engine.connect() as connection:
        assert _revision(connection) == PREVIOUS_REVISION
        assert connection.scalar(
            text("SELECT pg_catalog.to_regclass('public.teaching_names')")
        ) is None

    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE secretary_programme_pools
                SET is_active = true
                WHERE posting_code = 'TTSHGerMed' AND programme_code = 'GERI'
                """
            )
        )

    upgraded = harness.alembic("upgrade", B1_1_REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with harness.engine.connect() as connection:
        assert _revision(connection) == B1_1_REVISION
        assert _teaching_event_name_fk_delete_action(connection) == "n"

    downgraded_to_b1 = harness.alembic("downgrade", B1_REVISION)
    assert downgraded_to_b1.returncode == 0, downgraded_to_b1.stdout + downgraded_to_b1.stderr
    with harness.engine.connect() as connection:
        assert _revision(connection) == B1_REVISION
        assert _teaching_event_name_fk_delete_action(connection) == "r"

    restored_b1_1 = harness.alembic("upgrade", B1_1_REVISION)
    assert restored_b1_1.returncode == 0, restored_b1_1.stdout + restored_b1_1.stderr

    values.update(
        {
            "teaching_name_a_id": uuid4(),
            "teaching_name_a_cross_id": uuid4(),
            "teaching_name_b_id": uuid4(),
            "teaching_name_other_pool_id": uuid4(),
            "mapped_mapping_id": uuid4(),
            "pending_mapping_id": uuid4(),
            "null_identity_event_id": uuid4(),
            "name_event_id": uuid4(),
            "global_event_id": uuid4(),
            "preservation_name_id": uuid4(),
            "preservation_event_id": uuid4(),
            "preservation_native_attendance_id": uuid4(),
            "preservation_external_resident_id": uuid4(),
            "preservation_external_attendance_id": uuid4(),
        }
    )
    try:
        with harness.engine.begin() as connection:
            assert _revision(connection) == B1_1_REVISION
            assert _legacy_snapshot(connection, values) == before_snapshot
            assert connection.execute(
                text(
                    """
                    SELECT teaching_name_id, global_session_type_id
                    FROM teaching_events
                    WHERE id = :legacy_event_id
                    """
                ),
                values,
            ).one() == (None, None)
            _assert_b1_catalogue(connection)
            assert connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM teaching_targets
                    WHERE reporting_period_id = :period_id
                      AND programme_code = :programme_a
                      AND posting_code = :posting_a
                      AND r_year = :r_year
                    """
                ),
                values,
            ) == 2
            assert connection.scalar(
                text(
                    """
                    SELECT can_manage_teaching_names
                    FROM secretary_programme_pools
                    WHERE id = :pool_a_id
                    """
                ),
                values,
            ) is False
            assert connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM secretary_programme_pools
                    WHERE can_manage_teaching_names
                    """
                )
            ) == 1
            assert connection.scalar(
                text(
                    """
                    SELECT can_manage_teaching_names
                    FROM secretary_programme_pools
                    WHERE posting_code = 'TTSHGerMed' AND programme_code = 'GERI'
                    """
                )
            ) is True

            connection.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name
                    )
                    VALUES (
                        :teaching_name_a_id, :period_id, :programme_a,
                        'B1 Teaching Name A', 'b1 teaching name a'
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
                        :preservation_name_id, :period_id, :programme_a,
                        'Deleted name snapshot', 'deleted name snapshot'
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
                        :teaching_name_other_pool_id, :period_b_id, :programme_b,
                        'B1 Teaching Name A Other Pool', 'b1 teaching name a'
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, created_for_programme_code, teaching_name,
                        details_of_session, event_date, start_time, end_time,
                        duration_hours, session_type_id, cme_points_awarded,
                        smc_event_code, is_adhoc, created_by_role, teaching_name_id
                    )
                    VALUES (
                        :preservation_event_id, :posting_a, :programme_a,
                        'Deleted name snapshot', 'preserved event metadata',
                        DATE '2045-02-05', TIME '11:00', TIME '12:00', 1.00,
                        :session_a_id, true, 'B1-PRESERVE', false, 'programme_pc',
                        :preservation_name_id
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO attendance_records (
                        id, resident_id, teaching_event_id, submitted_at, status,
                        posting_code
                    )
                    VALUES (
                        :preservation_native_attendance_id, :legacy_resident_id,
                        :preservation_event_id, TIMESTAMPTZ '2045-02-05 12:30:00+00',
                        'submitted', :posting_a
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
                        :preservation_external_resident_id, 'B1 preservation external',
                        :preservation_external_mcr, 'NUH', :posting_a, 'active'
                    )
                    """
                ),
                {
                    **values,
                    "preservation_external_mcr": f"B1E{uuid4().hex[:16].upper()}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO external_attendance_records (
                        id, external_resident_id, teaching_event_id, submitted_at,
                        status, posting_code
                    )
                    VALUES (
                        :preservation_external_attendance_id,
                        :preservation_external_resident_id, :preservation_event_id,
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
                    WHERE id = :preservation_event_id
                    """
                ),
                values,
            )
            native_attendance_snapshot = connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM attendance_records AS attendance
                    WHERE id = :preservation_native_attendance_id
                    """
                ),
                values,
            )
            external_attendance_snapshot = connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM external_attendance_records AS attendance
                    WHERE id = :preservation_external_attendance_id
                    """
                ),
                values,
            )
            connection.execute(
                text("DELETE FROM teaching_names WHERE id = :preservation_name_id"),
                values,
            )
            preserved_event = connection.execute(
                text(
                    """
                    SELECT teaching_name_id, to_jsonb(event) - 'teaching_name_id'
                    FROM teaching_events AS event
                    WHERE id = :preservation_event_id
                    """
                ),
                values,
            ).one()
            assert preserved_event == (None, event_snapshot)
            assert connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM attendance_records AS attendance
                    WHERE id = :preservation_native_attendance_id
                    """
                ),
                values,
            ) == native_attendance_snapshot
            assert connection.scalar(
                text(
                    """
                    SELECT to_jsonb(attendance)
                    FROM external_attendance_records AS attendance
                    WHERE id = :preservation_external_attendance_id
                    """
                ),
                values,
            ) == external_attendance_snapshot
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_names (
                        id, reporting_period_id, programme_code, display_name,
                        normalized_name
                    )
                    VALUES (
                        :teaching_name_a_cross_id, :period_id, :programme_a,
                        'B1 Teaching Name A Cross', 'b1 teaching name a cross'
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
                        :teaching_name_b_id, :period_id, :programme_b,
                        'B1 Teaching Name B', 'b1 teaching name b'
                    )
                    """
                ),
                values,
            )
            _assert_integrity_violation(
                connection,
                """
                INSERT INTO teaching_names (
                    reporting_period_id, programme_code, display_name,
                    normalized_name, is_active
                )
                VALUES (
                    :period_id, :programme_a, 'Inactive duplicate',
                    'b1 teaching name a', false
                )
                """,
                values,
                constraint_name="uq_teaching_names_pool_normalized_name",
            )
            _assert_integrity_violation(
                connection,
                """
                INSERT INTO teaching_names (
                    reporting_period_id, programme_code, display_name,
                    normalized_name
                )
                VALUES (:period_id, :programme_a, '   ', 'nonblank normalized')
                """,
                values,
                constraint_name="ck_teaching_names_display_name_nonblank",
            )
            _assert_integrity_violation(
                connection,
                """
                UPDATE teaching_names
                SET programme_code = :programme_b
                WHERE id = :teaching_name_a_id
                """,
                values,
                constraint_name=None,
            )

            connection.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :mapped_mapping_id, :teaching_name_a_id, :period_id,
                        :programme_a, :posting_a, :r_year, :target_a_id
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :pending_mapping_id, :teaching_name_b_id, :period_id,
                        :programme_b, :posting_b, :r_year, NULL
                    )
                    """
                ),
                values,
            )
            _assert_integrity_violation(
                connection,
                """
                INSERT INTO teaching_name_mappings (
                    teaching_name_id, reporting_period_id, programme_code,
                    posting_code, r_year, teaching_target_id
                )
                VALUES (
                    :teaching_name_a_id, :period_id, :programme_a,
                    :posting_a, :r_year, :target_a_id
                )
                """,
                values,
                constraint_name="uq_teaching_name_mappings_identity",
            )
            _assert_integrity_violation(
                connection,
                """
                INSERT INTO teaching_name_mappings (
                    teaching_name_id, reporting_period_id, programme_code,
                    posting_code, r_year, teaching_target_id
                )
                VALUES (
                    :teaching_name_b_id, :period_id, :programme_a,
                    :posting_a, :r_year, :target_a_id
                )
                """,
                values,
                constraint_name="fk_teaching_name_mappings_name_pool",
            )
            _assert_integrity_violation(
                connection,
                """
                INSERT INTO teaching_name_mappings (
                    teaching_name_id, reporting_period_id, programme_code,
                    posting_code, r_year, teaching_target_id
                )
                VALUES (
                    :teaching_name_a_cross_id, :period_id, :programme_a,
                    :posting_a, :r_year, :target_b_id
                )
                """,
                values,
                constraint_name="fk_teaching_name_mappings_target_scope",
            )
            _assert_integrity_violation(
                connection,
                "DELETE FROM teaching_targets WHERE id = :target_a_id",
                values,
                constraint_name="fk_teaching_name_mappings_target_scope",
            )

            connection.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        is_adhoc
                    )
                    VALUES (
                        :null_identity_event_id, :posting_a, 'Legacy event',
                        DATE '2045-02-01', TIME '09:00', false
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        is_adhoc, teaching_name_id
                    )
                    VALUES (
                        :name_event_id, :posting_a, 'Named event',
                        DATE '2045-02-02', TIME '09:00', false,
                        :teaching_name_a_id
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        is_adhoc, global_session_type_id
                    )
                    VALUES (
                        :global_event_id, :posting_a, 'Global event',
                        DATE '2045-02-03', TIME '09:00', false,
                        :global_session_type_id
                    )
                    """
                ),
                values,
            )
            _assert_integrity_violation(
                connection,
                """
                INSERT INTO teaching_events (
                    posting_code, teaching_name, event_date, start_time, is_adhoc,
                    teaching_name_id, global_session_type_id
                )
                VALUES (
                    :posting_a, 'Ambiguous source', DATE '2045-02-04',
                    TIME '09:00', false, :teaching_name_a_id,
                    :global_session_type_id
                )
                """,
                values,
                constraint_name="ck_teaching_events_source_identity_exclusive",
            )
    finally:
        with harness.engine.begin() as connection:
            _cleanup_b1_fixture_rows(connection, values)

    downgraded = harness.alembic("downgrade", PREVIOUS_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with harness.engine.connect() as connection:
        assert _revision(connection) == PREVIOUS_REVISION
        assert connection.scalar(
            text("SELECT pg_catalog.to_regclass('public.teaching_names')")
        ) is None
        assert connection.scalar(
            text(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'teaching_events'
                  AND column_name IN ('teaching_name_id', 'global_session_type_id')
                """
            )
        ) == 0

    reupgraded = harness.alembic("upgrade", B1_1_REVISION)
    assert reupgraded.returncode == 0, reupgraded.stdout + reupgraded.stderr
    with harness.engine.connect() as connection:
        assert _revision(connection) == B1_1_REVISION
        assert _teaching_event_name_fk_delete_action(connection) == "n"
        _assert_b1_catalogue(connection)
