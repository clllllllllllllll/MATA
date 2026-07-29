from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.conftest import (
    MIGRATION_MUTATION_MARKER,
    pytest_collection_modifyitems,
)


@dataclass(frozen=True)
class _CollectedItem:
    nodeid: str
    fixturenames: tuple[str, ...]
    marked: bool

    def get_closest_marker(self, marker_name: str) -> object | None:
        assert marker_name == MIGRATION_MUTATION_MARKER
        return object() if self.marked else None


def test_collection_partition_accepts_exact_marker_fixture_matches() -> None:
    pytest_collection_modifyitems(
        [
            _CollectedItem(
                nodeid="tests/test_migration.py::test_lifecycle",
                fixturenames=("clean_migration_database",),
                marked=True,
            ),
            _CollectedItem(
                nodeid="tests/test_application.py::test_runtime",
                fixturenames=("rls_postgres_harness",),
                marked=False,
            ),
        ]
    )


@pytest.mark.parametrize(
    "item",
    [
        _CollectedItem(
            nodeid="tests/test_migration.py::test_unmarked_lifecycle",
            fixturenames=("clean_migration_database",),
            marked=False,
        ),
        _CollectedItem(
            nodeid="tests/test_application.py::test_wrongly_excluded",
            fixturenames=("rls_postgres_harness",),
            marked=True,
        ),
    ],
)
def test_collection_partition_rejects_omissions_and_overbroad_exclusions(
    item: _CollectedItem,
) -> None:
    with pytest.raises(pytest.UsageError, match=item.nodeid):
        pytest_collection_modifyitems([item])
