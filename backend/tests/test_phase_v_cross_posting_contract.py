from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admission_is_actual_posting_derived_and_sticky() -> None:
    source = _read("app/services/teaching_name_programme_scopes.py")

    assert "resident_postings AS posting" in source
    assert "posting.posting_code = name.origin_posting_code" in source
    assert "posting.status IN ('active', 'loa_working')" in source
    assert "resident.programme_code" in source
    assert "ON CONFLICT (teaching_name_id, programme_code) DO NOTHING" in source
    assert "DELETE FROM teaching_name_programme_scopes" not in source


def test_cross_posting_mapping_stays_in_native_exact_target_scope() -> None:
    admission_source = _read("app/services/teaching_name_programme_scopes.py")
    mapping_source = _read("app/services/teaching_name_mappings.py")

    assert "target.programme_code = scope.programme_code" in admission_source
    assert "target.posting_code = name.origin_posting_code" in admission_source
    assert "target.programme_code = :programme_code" in mapping_source
    assert "target.posting_code = :posting_code" in mapping_source
    assert "target.r_year = :r_year" in mapping_source


def test_resident_resolution_uses_native_programme_and_event_date_r_year() -> None:
    service_source = _read("app/services/teaching_target_resolution.py")
    migration_source = _read(
        "alembic/versions/20260812_000040_cross_posting_teaching_name_scopes.py"
    )

    assert "resolve_native_teaching_target_v2" in service_source
    assert "mapping.programme_code = v_resident_programme" in migration_source
    assert "mapping.posting_code = v_phase.posting_code" in migration_source
    assert "mapping.r_year = v_phase.r_year" in migration_source


def test_cross_posting_resident_event_policy_uses_protected_event_selector() -> None:
    migration_source = _read(
        "alembic/versions/20260813_000041_cross_posting_resident_event_policy.py"
    )

    assert "mata_rls.can_select_teaching_event_row(" in migration_source
    assert "OR mata_rls.can_select_teaching_event(id)" in migration_source
    assert '"v_phase.posting_code::text"' in migration_source
    assert '"v_phase.r_year::text"' in migration_source
    assert "down_revision = \"20260812_000040\"" in migration_source


def test_pc_private_provenance_and_cross_lifecycle_boundary_are_server_owned() -> None:
    pool_source = _read("app/services/teaching_name_pool.py")
    schema_source = _read("app/schemas/teaching_names.py")

    assert '"programme_private"' in pool_source
    assert '"department_shared"' in pool_source
    assert '"origin_posting_code"' in pool_source
    assert "only the Teaching Name source owner may change its lifecycle" in pool_source
    assert "can_manage_name: bool" in schema_source


def test_shared_event_envelope_and_native_resident_timing_are_separate() -> None:
    timing_source = _read("app/services/pool_event_timing.py")
    resident_source = _read("app/services/resident_submission.py")

    assert "sync_secretary_pool_event_timing" in timing_source
    assert "created_for_programme_code IS NULL" in timing_source
    assert "_native_resident_event_view" in resident_source
    assert '"duration_hours": duration_hours' in resident_source
    assert '"resident_r_year": r_year' in resident_source
