from __future__ import annotations

import pytest


MIGRATION_MUTATION_MARKER = "migration_mutation"
MIGRATION_MUTATION_FIXTURES = frozenset(
    {
        "clean_migration_database",
        "in_place_migration_database",
    }
)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    partition_errors: list[str] = []
    for item in items:
        mutation_fixtures = MIGRATION_MUTATION_FIXTURES.intersection(
            item.fixturenames
        )
        is_marked = item.get_closest_marker(MIGRATION_MUTATION_MARKER) is not None
        if bool(mutation_fixtures) == is_marked:
            continue
        partition_errors.append(item.nodeid)

    if partition_errors:
        raise pytest.UsageError(
            "Migration-mutation partition mismatch for: "
            + ", ".join(sorted(partition_errors))
        )
