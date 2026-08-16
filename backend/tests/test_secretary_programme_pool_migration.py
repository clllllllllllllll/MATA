from __future__ import annotations

from pathlib import Path
import runpy


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260816_000044_permanent_secretary_teaching_name_pools.py"
)


def test_permanent_secretary_pool_configuration_covers_all_programmes() -> None:
    migration = runpy.run_path(str(MIGRATION_PATH))
    rows = migration["_validate_configuration"]()

    assert len(rows) == 28
    assert len({programme_code for programme_code, _posting_code in rows}) == 28
    assert ("DR", "TTSHDiagRd") in rows
    assert ("GERI", "TTSHGerMed") in rows
    assert ("FM", "NHGPlyNHGPly") in rows
    assert ("PATH", "TTSHLabMed") in rows
    assert ("SPORTSMED", "TTSHOrtSrg(Sports)") in rows
    assert ("PALLMED", "TTSHPallia") in rows


def test_permanent_secretary_pool_seed_has_no_account_or_external_map_dependency() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "FROM users" not in source
    assert "JOIN users" not in source
    assert "FROM programme_institution_posting_map" not in source
    assert "JOIN programme_institution_posting_map" not in source
