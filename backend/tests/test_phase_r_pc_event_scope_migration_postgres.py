from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from app.config import Settings
from tests.postgres_disposable_database import configured_disposable_database_name


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TARGET_DATABASE_NAME = configured_disposable_database_name()
PREVIOUS_REVISION = "20260805_000037"
HEAD_REVISION = "20260806_000038"
LIFECYCLE_CEILING_REVISION = os.environ.get(
    "MATA_MIGRATION_LIFECYCLE_CEILING_REVISION",
    HEAD_REVISION,
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_INSERT_SIGNATURE = (
    "mata_rls.can_insert_scheduled_event_source("
    "text,text,uuid,uuid,text,uuid,date,boolean,text)"
)
_MANAGE_SIGNATURE = (
    "mata_rls.can_manage_teaching_event_row("
    "text,text,date,boolean,text,uuid,uuid,text,uuid)"
)


def _target_engine() -> Engine:
    settings = Settings(_env_file=None)
    owner_url = make_url(settings.sync_database_url)
    assert owner_url.host in _LOCAL_HOSTS
    assert owner_url.database == TARGET_DATABASE_NAME
    assert owner_url.username
    assert not owner_url.query
    return create_engine(owner_url, poolclass=NullPool)


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        # The URL preflight above proves the client target is local and disposable.
        # PostgreSQL may report its Docker bridge address from inside a CI service.
        identity = connection.execute(
            text(
                """
                SELECT current_database(), current_user, session_user
                """
            )
        ).one()
        assert identity[0] == TARGET_DATABASE_NAME
        assert identity[1] == identity[2]
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _alembic(*arguments: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _helper_definition(engine: Engine, signature: str) -> str:
    with engine.connect() as connection:
        definition = connection.scalar(
            text(
                "SELECT pg_catalog.pg_get_functiondef("
                "pg_catalog.to_regprocedure(:signature))"
            ),
            {"signature": signature},
        )
    assert isinstance(definition, str)
    return definition


def _assert_helper_acl(engine: Engine, signature: str) -> None:
    with engine.connect() as connection:
        helper = connection.execute(
            text(
                """
                SELECT procedure.prosecdef,
                       procedure.proconfig,
                       pg_catalog.has_function_privilege(
                           'mata_app_runtime', procedure.oid, 'EXECUTE'
                       ),
                       pg_catalog.has_function_privilege(
                           'mata_auth_internal', procedure.oid, 'EXECUTE'
                       ),
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
                       )
                FROM pg_catalog.pg_proc AS procedure
                WHERE procedure.oid = pg_catalog.to_regprocedure(:signature)
                """
            ),
            {"signature": signature},
        ).one()
    assert helper[0] is True
    assert list(helper[1] or []) == ["search_path=pg_catalog, pg_temp"]
    assert helper[2:] == (True, False, True)


@pytest.fixture
def clean_migration_database() -> Iterator[Engine]:
    """Marked direct-owner mutation seam for the runner-owned Phase R target."""

    engine = _target_engine()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.migration_mutation
def test_phase_r_pc_pool_event_scope_migration_rolls_back_and_reupgrades(
    clean_migration_database: Engine,
) -> None:
    engine = clean_migration_database
    try:
        assert _revision(engine) == LIFECYCLE_CEILING_REVISION
        _alembic("downgrade", HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        for signature in (_INSERT_SIGNATURE, _MANAGE_SIGNATURE):
            definition = _helper_definition(engine, signature)
            assert "teaching_name_mappings AS mapping" in definition
            assert "mapping.teaching_name_id = p_teaching_name_id" in definition
            assert "mapping.reporting_period_id" in definition
            assert "mapping.programme_code = p_source_programme_code" in definition
            assert "mapping.posting_code = p_posting_code" in definition
            assert "SECURITY DEFINER" in definition
            assert "SET search_path TO 'pg_catalog', 'pg_temp'" in definition
            _assert_helper_acl(engine, signature)

        _alembic("downgrade", PREVIOUS_REVISION)
        assert _revision(engine) == PREVIOUS_REVISION
        for signature in (_INSERT_SIGNATURE, _MANAGE_SIGNATURE):
            assert "teaching_name_mappings AS mapping" not in _helper_definition(
                engine, signature
            )

        _alembic("upgrade", HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
    finally:
        if _revision(engine) != LIFECYCLE_CEILING_REVISION:
            _alembic("upgrade", LIFECYCLE_CEILING_REVISION)
