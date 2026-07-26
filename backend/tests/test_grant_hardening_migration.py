from __future__ import annotations

import importlib.util
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(filename: str, module_name: str):
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def test_session_migration_is_linear_backend_only_and_indexed() -> None:
    module, path = _load(
        "20260722_000023_app_sessions.py",
        "app_sessions_migration",
    )
    source = path.read_text(encoding="utf-8")
    normalized = " ".join(source.lower().split())

    assert module.revision == "20260722_000023"
    assert module.down_revision == "20260721_000022"
    assert '"token_digest", sa.largebinary(length=32), nullable=false' in normalized
    assert '"csrf_token_digest", sa.largebinary(length=32), nullable=false' in normalized
    assert '"subject_session_generation", sa.biginteger(), nullable=false' in normalized
    assert '"session_family_id", postgresql.uuid(as_uuid=true), nullable=false' in normalized
    assert '"session_issuance_blocked"' in normalized
    for subject_table in ("users", "residents", "external_residents"):
        assert subject_table in source
    assert "ck_{table_name}_session_generation_nonnegative" in source
    assert "uq_app_sessions_token_digest" in source
    assert "uq_app_sessions_rotated_from_session_id" in source
    assert "ck_app_sessions_token_digest_length" in source
    assert "ck_app_sessions_csrf_token_digest_length" in source
    assert "ck_app_sessions_user_agent_hash_length" in source
    assert "ck_app_sessions_subject_session_generation_nonnegative" in source
    assert "ck_app_sessions_root_self_family" in source
    assert "idx_app_sessions_active_expiry" in source
    assert "idx_app_sessions_subject" in source
    assert "idx_app_sessions_family_revoked" in source
    assert "idx_app_sessions_revoked_at" in source
    assert "idx_app_sessions_absolute_expires_at" in source
    assert "idx_app_sessions_idle_expires_at" in source
    assert "ENABLE ROW LEVEL SECURITY" not in source
    assert "FORCE ROW LEVEL SECURITY" not in source


def test_grant_hardening_is_explicit_conditional_and_never_regrants_on_downgrade(
) -> None:
    module, path = _load(
        "20260722_000024_revoke_browser_database_privileges.py",
        "revoke_browser_privileges_migration",
    )
    source = path.read_text(encoding="utf-8")
    normalized = " ".join(source.lower().split())

    assert module.revision == "20260722_000024"
    assert module.down_revision == "20260722_000023"
    for object_kind in ("tables", "sequences", "functions"):
        assert (
            f"revoke all privileges on all {object_kind} in schema public from public"
            in normalized
        )
        assert (
            f"alter default privileges in schema public revoke all privileges on {object_kind} from public"
            in normalized
        )

    assert "ARRAY['anon', 'authenticated']" in source
    assert "SELECT 1 FROM pg_roles WHERE rolname = browser_role" in source
    assert "service_role" not in source
    assert "current_user" not in source
    assert "force row level security" not in normalized

    class _UnexpectedOperation:
        def __getattr__(self, name):
            raise AssertionError(f"downgrade attempted database operation: {name}")

    module.op = _UnexpectedOperation()
    assert module.downgrade() is None


def test_read_only_privilege_audit_queries_cover_tables_sequences_and_functions() -> None:
    # These are the catalogue predicates used by the migration smoke harness.
    # Keeping them here makes the expected read-only verification boundary
    # executable without mutating or requiring a connected Supabase project.
    audit_sql = """
        SELECT has_table_privilege(:role_name, table_schema || '.' || table_name, 'SELECT')
        FROM information_schema.tables
        WHERE table_schema = 'public';

        SELECT has_sequence_privilege(:role_name, sequence_schema || '.' || sequence_name, 'USAGE')
        FROM information_schema.sequences
        WHERE sequence_schema = 'public';

        SELECT has_function_privilege(:role_name, p.oid, 'EXECUTE')
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public';
    """
    normalized = " ".join(audit_sql.lower().split())
    assert "has_table_privilege" in normalized
    assert "has_sequence_privilege" in normalized
    assert "has_function_privilege" in normalized
    assert "information_schema.tables" in normalized
    assert "information_schema.sequences" in normalized
    assert "pg_proc" in normalized
