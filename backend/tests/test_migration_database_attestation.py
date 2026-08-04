from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from tests.attest_migration_database import (
    DatabaseReuseSnapshot,
    _wait_for_database_reuse,
)
from tests.run_rls_restricted_pytest import (
    POLICY_REVISION,
    RestrictedRlsRunnerError,
)


OWNER = "migration_owner"


def _snapshot(
    *,
    other_connections: int = 0,
    residual_test_roles: int = 0,
    current_role: str = OWNER,
) -> DatabaseReuseSnapshot:
    return DatabaseReuseSnapshot(
        database_name="mata_evolved_ttf_dfg_fix_verify",
        current_role=current_role,
        session_role=OWNER,
        database_owner=OWNER,
        login_is_superuser=True,
        revision=POLICY_REVISION,
        other_connections=other_connections,
        residual_test_roles=residual_test_roles,
    )


def _samples(
    snapshots: list[DatabaseReuseSnapshot],
) -> tuple[
    Iterator[DatabaseReuseSnapshot],
    Callable[[], DatabaseReuseSnapshot],
]:
    iterator = iter(snapshots)
    return iterator, lambda: next(iterator)


def test_database_reuse_attestation_waits_for_sessions_and_roles() -> None:
    iterator, sample = _samples(
        [
            _snapshot(other_connections=1),
            _snapshot(residual_test_roles=1),
            _snapshot(),
        ]
    )
    pauses: list[float] = []

    result = _wait_for_database_reuse(
        sample,
        expected_owner=OWNER,
        pause=pauses.append,
    )

    assert result == _snapshot()
    assert pauses == [0.1, 0.1]
    assert list(iterator) == []


def test_database_reuse_attestation_rejects_persistent_contention() -> None:
    pauses: list[float] = []

    with pytest.raises(
        RestrictedRlsRunnerError,
        match="zero competing sessions",
    ):
        _wait_for_database_reuse(
            lambda: _snapshot(other_connections=1),
            expected_owner=OWNER,
            pause=pauses.append,
        )

    assert pauses == [0.1] * 19


def test_database_reuse_attestation_rejects_wrong_owner_immediately() -> None:
    pauses: list[float] = []

    with pytest.raises(
        RestrictedRlsRunnerError,
        match="exact local disposable database",
    ):
        _wait_for_database_reuse(
            lambda: _snapshot(current_role="unexpected_role"),
            expected_owner=OWNER,
            pause=pauses.append,
        )

    assert pauses == []
