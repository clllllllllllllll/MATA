from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from sqlalchemy.engine import make_url

from tests.test_external_registration_migrations_postgres import (
    H_E_DISPOSABLE_DATABASE_NAME,
    MigrationHarness,
    _wait_for_exclusive_mutation_target,
)


OWNER = "migration_owner"
OWNER_URL = make_url(
    "postgresql://migration_owner:test@localhost:5432/"
    f"{H_E_DISPOSABLE_DATABASE_NAME}"
)


def _identity(*, current_role: str = OWNER) -> dict[str, object]:
    return {
        "database_name": H_E_DISPOSABLE_DATABASE_NAME,
        "current_role": current_role,
        "session_role": OWNER,
        "database_owner": OWNER,
        "login_is_superuser": True,
    }


def _samples(
    connection_counts: list[int],
) -> tuple[Iterator[int], Callable[[], tuple[dict[str, object], int]]]:
    iterator = iter(connection_counts)
    return iterator, lambda: (_identity(), next(iterator))


def test_mutation_exclusivity_waits_until_every_peer_is_gone() -> None:
    iterator, sample = _samples([1, 1, 0])
    pauses: list[float] = []

    result = _wait_for_exclusive_mutation_target(
        OWNER_URL,
        sample,
        pause=pauses.append,
    )

    assert result == _identity()
    assert pauses == [0.1, 0.1]
    assert list(iterator) == []


def test_mutation_exclusivity_rejects_persistent_peer_sessions() -> None:
    pauses: list[float] = []

    with pytest.raises(
        pytest.fail.Exception,
        match="exclusive exact named local disposable database",
    ):
        _wait_for_exclusive_mutation_target(
            OWNER_URL,
            lambda: (_identity(), 1),
            pause=pauses.append,
        )

    assert pauses == [0.1] * 19


def test_mutation_exclusivity_rejects_wrong_owner_immediately() -> None:
    pauses: list[float] = []

    with pytest.raises(
        pytest.fail.Exception,
        match="exclusive exact named local disposable database",
    ):
        _wait_for_exclusive_mutation_target(
            OWNER_URL,
            lambda: (_identity(current_role="unexpected_role"), 0),
            pause=pauses.append,
        )

    assert pauses == []


class _UnmarkedNode:
    def get_closest_marker(self, marker_name: str) -> None:
        assert marker_name == "migration_mutation"
        return None


class _UnexpectedEngine:
    def connect(self) -> None:
        raise AssertionError("marker authorization must precede database access")


def test_alembic_primitive_rejects_unmarked_direct_construction() -> None:
    harness = MigrationHarness(
        database_name=H_E_DISPOSABLE_DATABASE_NAME,
        engine=_UnexpectedEngine(),  # type: ignore[arg-type]
        environment={},
        request_node=_UnmarkedNode(),  # type: ignore[arg-type]
    )

    with pytest.raises(
        pytest.fail.Exception,
        match="requires the migration_mutation marker",
    ):
        harness.alembic("upgrade", "head")
