from __future__ import annotations

import pytest

from tests.postgres_disposable_database import (
    DEFAULT_DISPOSABLE_DATABASE_NAME,
    PHASE_K_DISPOSABLE_DATABASE_NAME,
    PHASE_L_DISPOSABLE_DATABASE_NAME,
    configured_disposable_database_name,
)


def test_configured_disposable_database_name_uses_default(monkeypatch) -> None:
    monkeypatch.delenv("MATA_RLS_DISPOSABLE_DATABASE_NAME", raising=False)

    assert configured_disposable_database_name() == DEFAULT_DISPOSABLE_DATABASE_NAME


def test_configured_disposable_database_name_allows_phase_k_target(monkeypatch) -> None:
    monkeypatch.setenv("MATA_RLS_DISPOSABLE_DATABASE_NAME", PHASE_K_DISPOSABLE_DATABASE_NAME)

    assert configured_disposable_database_name() == PHASE_K_DISPOSABLE_DATABASE_NAME


def test_configured_disposable_database_name_allows_phase_l_target(monkeypatch) -> None:
    monkeypatch.setenv("MATA_RLS_DISPOSABLE_DATABASE_NAME", PHASE_L_DISPOSABLE_DATABASE_NAME)

    assert configured_disposable_database_name() == PHASE_L_DISPOSABLE_DATABASE_NAME


@pytest.mark.parametrize("database_name", ["postgres", "mata_not_disposable"])
def test_configured_disposable_database_name_rejects_unknown_target(
    monkeypatch,
    database_name: str,
) -> None:
    monkeypatch.setenv("MATA_RLS_DISPOSABLE_DATABASE_NAME", database_name)

    with pytest.raises(ValueError, match="not an allowed target"):
        configured_disposable_database_name()
