from __future__ import annotations

import importlib.util
from pathlib import Path


EXPECTED_RLS_TABLES = (
    "alembic_version",
    "academic_month_boundaries",
    "event_series",
    "global_session_types",
    "loa_types",
    "multi_posting_rules",
    "posting_codes",
    "posting_groups",
    "programmes",
    "public_holidays",
    "reporting_periods",
    "secretary_programme_pools",
    "session_types",
    "weekend_exceptions",
)


def test_remaining_public_tables_rls_migration_is_explicit_and_locked_down() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260708_000015_enable_rls_remaining_public_tables.py"
    )

    spec = importlib.util.spec_from_file_location("enable_remaining_public_rls", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260708_000015"
    assert module.down_revision == "20260704_000014"
    assert module.RLS_TABLES == EXPECTED_RLS_TABLES

    source = migration_path.read_text(encoding="utf-8")
    normalized_source = " ".join(source.lower().split())
    assert "create policy" not in normalized_source
    assert "using (true)" not in normalized_source
    assert "using(true)" not in normalized_source
    assert "force row level security" not in normalized_source
    assert "public.{table_name}" not in source

    for table_name in EXPECTED_RLS_TABLES:
        assert f'ALTER TABLE IF EXISTS public."{table_name}" ENABLE ROW LEVEL SECURITY' in source
        assert f'ALTER TABLE IF EXISTS public."{table_name}" DISABLE ROW LEVEL SECURITY' in source
