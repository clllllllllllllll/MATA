from __future__ import annotations

import pytest
from sqlalchemy.engine import URL, make_url

import tests.run_phase_r_postgres_verify as phase_r_runner
from tests.run_phase_r_postgres_verify import (
    EXPECTED_OWNER_USERNAME,
    MAINTENANCE_DATABASE_URL_ENV,
    OWNER_DATABASE_URL_ENV,
    REQUIRED_POSTGRES_PORT,
    TARGET_DATABASE_NAME,
    PhaseRPostgresRunnerError,
    PostgresPreflight,
    _assert_preflight,
    _normalise_server_address,
    _owner_environment,
    _phase_r_database_targets,
    _pytest_command,
    _recreate_target_database,
    _restricted_test_environment,
)


OWNER_URL = URL.create(
    "postgresql+psycopg2",
    username=EXPECTED_OWNER_USERNAME,
    password="owner-password",
    host="localhost",
    port=REQUIRED_POSTGRES_PORT,
    database=TARGET_DATABASE_NAME,
).render_as_string(hide_password=False)
MAINTENANCE_URL = URL.create(
    "postgresql+psycopg2",
    username=EXPECTED_OWNER_USERNAME,
    password="maintenance-password",
    host="localhost",
    port=REQUIRED_POSTGRES_PORT,
    database="postgres",
).render_as_string(hide_password=False)
RUNTIME_ROLE = "mata_phase_r_runtime_0123456789abcdef"
AUTH_ROLE = "mata_phase_r_auth_fedcba9876543210"
RUNTIME_PASSWORD = "a" * 64
AUTH_PASSWORD = "b" * 64


def _environment(
    *,
    owner_url: str = OWNER_URL,
    maintenance_url: str = MAINTENANCE_URL,
) -> dict[str, str]:
    return {
        OWNER_DATABASE_URL_ENV: owner_url,
        MAINTENANCE_DATABASE_URL_ENV: maintenance_url,
    }


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "not-a-database-url",
        f"postgresql+asyncpg://owner:test@localhost:5432/{TARGET_DATABASE_NAME}",
        f"postgresql://owner:test@db.example.invalid:5432/{TARGET_DATABASE_NAME}",
        f"postgresql://owner:test@localhost/{TARGET_DATABASE_NAME}",
        f"postgresql://owner@localhost:5432/{TARGET_DATABASE_NAME}",
        "postgresql://owner:test@localhost:5432/mata_db",
        f"postgresql://owner:test@localhost:5432/{TARGET_DATABASE_NAME}?sslmode=disable",
    ],
)
def test_owner_url_requires_the_explicit_local_disposable_target(raw_url: str) -> None:
    with pytest.raises(PhaseRPostgresRunnerError):
        _phase_r_database_targets(_environment(owner_url=raw_url))


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "postgresql://maintenance:test@localhost:5432/"
        f"{TARGET_DATABASE_NAME}",
        "postgresql://maintenance:test@db.example.invalid:5432/postgres",
        "postgresql://maintenance:test@localhost/postgres",
        "postgresql://maintenance@localhost:5432/postgres",
        "postgresql://maintenance:test@localhost:5432/postgres?sslmode=disable",
    ],
)
def test_maintenance_url_must_be_explicit_local_and_separate(raw_url: str) -> None:
    with pytest.raises(PhaseRPostgresRunnerError):
        _phase_r_database_targets(_environment(maintenance_url=raw_url))


def test_owner_and_maintenance_urls_must_use_the_same_declared_server() -> None:
    maintenance_url = URL.create(
        "postgresql",
        username=EXPECTED_OWNER_USERNAME,
        password="maintenance-password",
        host="127.0.0.1",
        port=REQUIRED_POSTGRES_PORT,
        database="postgres",
    ).render_as_string(hide_password=False)

    with pytest.raises(PhaseRPostgresRunnerError):
        _phase_r_database_targets(_environment(maintenance_url=maintenance_url))


def test_targets_accept_only_the_exact_named_owner_database() -> None:
    targets = _phase_r_database_targets(_environment())

    assert targets.owner_url.database == TARGET_DATABASE_NAME
    assert targets.owner_url.username == EXPECTED_OWNER_USERNAME
    assert targets.owner_url.host == "localhost"
    assert targets.owner_url.port == REQUIRED_POSTGRES_PORT
    assert targets.maintenance_url.database == "postgres"
    assert targets.maintenance_url.username == EXPECTED_OWNER_USERNAME
    assert targets.maintenance_url.host == "localhost"
    assert targets.maintenance_url.port == REQUIRED_POSTGRES_PORT


@pytest.mark.parametrize(
    ("owner_url", "maintenance_url"),
    [
        (
            URL.create(
                "postgresql",
                username="different_owner",
                password="owner-password",
                host="localhost",
                port=REQUIRED_POSTGRES_PORT,
                database=TARGET_DATABASE_NAME,
            ).render_as_string(hide_password=False),
            MAINTENANCE_URL,
        ),
        (
            OWNER_URL,
            URL.create(
                "postgresql",
                username="different_owner",
                password="maintenance-password",
                host="localhost",
                port=REQUIRED_POSTGRES_PORT,
                database="postgres",
            ).render_as_string(hide_password=False),
        ),
        (
            URL.create(
                "postgresql",
                username=EXPECTED_OWNER_USERNAME,
                password="owner-password",
                host="localhost",
                port=REQUIRED_POSTGRES_PORT + 1,
                database=TARGET_DATABASE_NAME,
            ).render_as_string(hide_password=False),
            URL.create(
                "postgresql",
                username=EXPECTED_OWNER_USERNAME,
                password="maintenance-password",
                host="localhost",
                port=REQUIRED_POSTGRES_PORT + 1,
                database="postgres",
            ).render_as_string(hide_password=False),
        ),
    ],
)
def test_targets_require_the_authorized_owner_and_port(
    owner_url: str,
    maintenance_url: str,
) -> None:
    with pytest.raises(PhaseRPostgresRunnerError):
        _phase_r_database_targets(
            _environment(owner_url=owner_url, maintenance_url=maintenance_url)
        )


@pytest.mark.parametrize(
    "preflight",
    [
        PostgresPreflight(
            database_name="postgres",
            current_user="migration_owner",
            session_user="migration_owner",
            server_address="127.0.0.1",
            server_port=5432,
            is_superuser=False,
        ),
        PostgresPreflight(
            database_name=TARGET_DATABASE_NAME,
            current_user="other_user",
            session_user="other_user",
            server_address="127.0.0.1",
            server_port=5432,
            is_superuser=False,
        ),
        PostgresPreflight(
            database_name=TARGET_DATABASE_NAME,
            current_user="migration_owner",
            session_user="other_user",
            server_address="127.0.0.1",
            server_port=5432,
            is_superuser=False,
        ),
        PostgresPreflight(
            database_name=TARGET_DATABASE_NAME,
            current_user="migration_owner",
            session_user="migration_owner",
            server_address="192.0.2.10",
            server_port=5432,
            is_superuser=False,
        ),
        PostgresPreflight(
            database_name=TARGET_DATABASE_NAME,
            current_user="migration_owner",
            session_user="migration_owner",
            server_address="127.0.0.1",
            server_port=5433,
            is_superuser=False,
        ),
    ],
)
def test_preflight_rejects_any_database_user_address_or_port_mismatch(
    preflight: PostgresPreflight,
) -> None:
    with pytest.raises(PhaseRPostgresRunnerError):
        _assert_preflight(preflight, url=make_url(OWNER_URL))


def test_preflight_accepts_exact_local_target_and_expected_server() -> None:
    preflight = PostgresPreflight(
        database_name=TARGET_DATABASE_NAME,
        current_user=EXPECTED_OWNER_USERNAME,
        session_user=EXPECTED_OWNER_USERNAME,
        server_address="127.0.0.1",
        server_port=5432,
        is_superuser=False,
    )

    _assert_preflight(
        preflight,
        url=make_url(OWNER_URL),
        expected_server=("127.0.0.1", 5432),
    )


@pytest.mark.parametrize(
    ("raw_address", "expected_address"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("::1/128", "::1"),
        ("::1/64", None),
        ("192.0.2.10", "192.0.2.10"),
        ("not-an-address", None),
    ],
)
def test_normalise_server_address_accepts_only_exact_host_addresses(
    raw_address: str,
    expected_address: str | None,
) -> None:
    assert _normalise_server_address(raw_address) == expected_address


def test_maintenance_preflight_requires_a_superuser() -> None:
    preflight = PostgresPreflight(
        database_name="postgres",
        current_user="local_maintenance",
        session_user="local_maintenance",
        server_address="127.0.0.1",
        server_port=5432,
        is_superuser=False,
    )

    with pytest.raises(PhaseRPostgresRunnerError):
        _assert_preflight(
            preflight,
            url=make_url(MAINTENANCE_URL),
            require_superuser=True,
        )


def test_child_environments_hide_the_maintenance_url_and_keep_roles_separate() -> None:
    owner_environment = _owner_environment(
        {
            OWNER_DATABASE_URL_ENV: OWNER_URL,
            MAINTENANCE_DATABASE_URL_ENV: MAINTENANCE_URL,
            "UNRELATED_TEST_SETTING": "preserved",
        },
        owner_url=make_url(OWNER_URL),
    )
    restricted_environment = _restricted_test_environment(
        owner_environment,
        owner_url=make_url(OWNER_URL),
        runtime_role=RUNTIME_ROLE,
        runtime_password=RUNTIME_PASSWORD,
        auth_role=AUTH_ROLE,
        auth_password=AUTH_PASSWORD,
    )

    runtime_url = make_url(restricted_environment["DATABASE_URL"])
    auth_url = make_url(restricted_environment["AUTH_DATABASE_URL"])
    assert MAINTENANCE_DATABASE_URL_ENV not in owner_environment
    assert OWNER_DATABASE_URL_ENV not in owner_environment
    assert owner_environment["UNRELATED_TEST_SETTING"] == "preserved"
    assert runtime_url.username == RUNTIME_ROLE
    assert auth_url.username == AUTH_ROLE
    assert runtime_url.database == TARGET_DATABASE_NAME
    assert auth_url.database == TARGET_DATABASE_NAME
    assert restricted_environment["DATABASE_RLS_ENABLED"] == "true"
    assert restricted_environment["MATA_PHASE_R_RUNTIME_ROLE"] == RUNTIME_ROLE
    assert restricted_environment["MATA_PHASE_R_AUTH_ROLE"] == AUTH_ROLE
    assert restricted_environment["MATA_RLS_DISPOSABLE_DATABASE_NAME"] == TARGET_DATABASE_NAME
    assert restricted_environment["MATA_RLS_RUNTIME_ROLE"] == RUNTIME_ROLE
    assert restricted_environment["MATA_RLS_AUTH_ROLE"] == AUTH_ROLE


def test_pytest_arguments_are_required_for_destructive_database_verification() -> None:
    with pytest.raises(PhaseRPostgresRunnerError):
        _pytest_command([])

    assert _pytest_command(["-q", "tests/test_phase_r_postgres.py"])[-2:] == [
        "-q",
        "tests/test_phase_r_postgres.py",
    ]


def test_recreate_target_drops_only_an_existing_target_with_the_expected_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    connection = object()

    monkeypatch.setattr(
        phase_r_runner,
        "_database_exists",
        lambda received_connection, *, database_name: received_connection is connection
        and database_name == TARGET_DATABASE_NAME,
    )
    monkeypatch.setattr(
        phase_r_runner,
        "_assert_target_database_owner",
        lambda received_connection, *, owner_username: calls.append(
            ("assert-owner", owner_username)
        ),
    )
    monkeypatch.setattr(
        phase_r_runner,
        "_drop_target_database",
        lambda received_connection, *, owner_username: calls.append(
            ("drop", owner_username)
        ),
    )
    monkeypatch.setattr(
        phase_r_runner,
        "_create_target_database",
        lambda received_connection, *, owner_username: calls.append(
            ("create", owner_username)
        ),
    )

    _recreate_target_database(connection, owner_username=EXPECTED_OWNER_USERNAME)

    assert calls == [
        ("assert-owner", EXPECTED_OWNER_USERNAME),
        ("drop", EXPECTED_OWNER_USERNAME),
        ("create", EXPECTED_OWNER_USERNAME),
    ]
