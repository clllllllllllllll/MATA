from __future__ import annotations

import sys

import pytest
from sqlalchemy.engine import URL, make_url

from tests.run_rls_restricted_pytest import (
    AUTH_GROUP,
    AUTH_DATABASE_URL_ENV,
    DATABASE_URL_ENV,
    DISPOSABLE_DATABASE_NAME,
    MATA_AUTH_DATABASE_URL_ENV,
    RUNTIME_GROUP,
    SYNC_DATABASE_URL_ENV,
    RestrictedRlsRunnerError,
    _capability_role_is_hardened,
    _child_environment,
    _owner_sync_url,
    _pytest_command,
)


OWNER_URL = URL.create(
    "postgresql+psycopg2",
    username="migration_owner",
    password="test",
    host="localhost",
    port=5432,
    database=DISPOSABLE_DATABASE_NAME,
).render_as_string(hide_password=False)
RUNTIME_ROLE = "mata_test_runtime_0123456789abcdef"
AUTH_ROLE = "mata_test_auth_fedcba9876543210"
RUNTIME_PASSWORD = "a" * 64
AUTH_PASSWORD = "b" * 64


def _capability_role_row(*, inherits: bool) -> dict[str, bool]:
    return {
        "rolcanlogin": False,
        "rolinherit": inherits,
        "rolsuper": False,
        "rolcreatedb": False,
        "rolcreaterole": False,
        "rolreplication": False,
        "rolbypassrls": False,
    }


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "not-a-database-url",
        "postgresql+asyncpg://owner:test@localhost:5432/"
        f"{DISPOSABLE_DATABASE_NAME}",
        "postgresql://owner:test@db.example.invalid:5432/"
        f"{DISPOSABLE_DATABASE_NAME}",
        "postgresql://owner:test@localhost:5432/mata_db",
        "postgresql://owner:test@localhost:5432/mata_phase5b_wrong_review",
        "postgresql://owner:test@localhost:5432/"
        f"{DISPOSABLE_DATABASE_NAME}?host=db.example.invalid",
    ],
)
def test_owner_url_guard_rejects_non_exact_targets(raw_url: str) -> None:
    with pytest.raises(RestrictedRlsRunnerError):
        _owner_sync_url({SYNC_DATABASE_URL_ENV: raw_url})


def test_owner_url_guard_accepts_only_named_local_sync_database() -> None:
    parsed = _owner_sync_url({SYNC_DATABASE_URL_ENV: OWNER_URL})

    assert parsed.drivername == "postgresql+psycopg2"
    assert parsed.host == "localhost"
    assert parsed.database == DISPOSABLE_DATABASE_NAME
    assert parsed.username == "migration_owner"


def test_capability_groups_must_remain_noinherit() -> None:
    assert _capability_role_is_hardened(
        _capability_role_row(inherits=False)
    )
    assert not _capability_role_is_hardened(
        _capability_role_row(inherits=True)
    )


def test_child_environment_installs_restricted_roles_before_collection() -> None:
    environment = _child_environment(
        {"UNRELATED_TEST_SETTING": "preserved"},
        owner_sync_url=make_url(OWNER_URL),
        runtime_role=RUNTIME_ROLE,
        runtime_password=RUNTIME_PASSWORD,
        auth_role=AUTH_ROLE,
        auth_password=AUTH_PASSWORD,
    )

    runtime_url = make_url(environment[DATABASE_URL_ENV])
    auth_url = make_url(environment[AUTH_DATABASE_URL_ENV])
    owner_url = make_url(environment[SYNC_DATABASE_URL_ENV])
    assert environment["UNRELATED_TEST_SETTING"] == "preserved"
    assert runtime_url.username == RUNTIME_ROLE
    assert runtime_url.password == RUNTIME_PASSWORD
    assert auth_url.username == AUTH_ROLE
    assert auth_url.password == AUTH_PASSWORD
    assert owner_url.username == "migration_owner"
    assert {
        (runtime_url.host, runtime_url.port, runtime_url.database),
        (auth_url.host, auth_url.port, auth_url.database),
        (owner_url.host, owner_url.port, owner_url.database),
    } == {("localhost", 5432, DISPOSABLE_DATABASE_NAME)}
    assert (
        environment[MATA_AUTH_DATABASE_URL_ENV]
        == environment[AUTH_DATABASE_URL_ENV]
    )
    assert environment["DATABASE_RLS_ENABLED"] == "true"
    assert environment["MATA_DATABASE_RLS_ENABLED"] == "true"
    assert environment["DATABASE_RUNTIME_ROLE"] == RUNTIME_GROUP
    assert environment["MATA_DATABASE_RUNTIME_ROLE"] == RUNTIME_GROUP
    assert environment["DATABASE_AUTH_ROLE"] == AUTH_GROUP
    assert environment["MATA_DATABASE_AUTH_ROLE"] == AUTH_GROUP
    assert environment["ENVIRONMENT"] == "test"
    assert environment["ENV"] == "test"
    assert environment["AUTH_MODE"] == "stub"
    assert environment["AUTH_TRANSPORT"] == "cookie"


def test_pytest_command_is_pre_collection_and_preserves_arguments() -> None:
    assert _pytest_command(["-q", "tests/test_auth.py"]) == [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        "tests/test_auth.py",
    ]
    assert _pytest_command([]) == [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "tests",
    ]
