from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260727_000027_session_lifecycle_assurance.py"
)


def _function_definition(source: str, function_name: str) -> str:
    start = source.index(f"CREATE FUNCTION mata_rls.{function_name}(")
    body_start = source.index("$function$", start) + len("$function$")
    end = source.index("$function$", body_start)
    return source[start:end]


def test_lifecycle_revision_is_narrow_and_linear() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision = "20260727_000027"' in source
    assert 'down_revision = "20260726_000026"' in source
    assert "op.create_table" not in source
    assert "op.add_column" not in source
    assert "CREATE POLICY" not in source
    assert "GRANT SELECT ON" not in source


def test_restricted_helper_results_do_not_return_stored_session_secrets() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    lifecycle_helpers = (
        "issue_staff_app_session_lifecycle",
        "issue_resident_app_session_lifecycle",
        "issue_external_resident_app_session_lifecycle",
        "resolve_app_session_lifecycle",
        "rotate_app_session_lifecycle",
        "revoke_app_session_family_for_logout",
    )

    for helper_name in lifecycle_helpers:
        definition = _function_definition(source, helper_name)
        result_contract = definition[
            definition.index("RETURNS "):definition.index("LANGUAGE ")
        ]
        assert "token_digest" not in result_contract
        assert "csrf_token_digest" not in result_contract
        assert "idle_expires_at" not in result_contract
        assert "absolute_expires_at" not in result_contract
        assert "cookie_max_age_seconds" not in result_contract

    for helper_name in (
        "touch_app_session_lifecycle",
        "validate_app_session_csrf",
    ):
        definition = _function_definition(source, helper_name)
        result_contract = definition[
            definition.index("RETURNS "):definition.index("LANGUAGE ")
        ]
        assert result_contract.strip() == "RETURNS boolean"

    logout_revoke = _function_definition(
        source,
        "revoke_app_session_family_for_logout",
    )
    result_contract = logout_revoke[
        logout_revoke.index("RETURNS "):logout_revoke.index("LANGUAGE ")
    ]
    assert result_contract.strip() == "RETURNS integer"


def test_lifecycle_helpers_are_fixed_path_and_superseded_grants_are_revoked() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    for helper_name in (
        "issue_staff_app_session_lifecycle",
        "issue_resident_app_session_lifecycle",
        "issue_external_resident_app_session_lifecycle",
        "resolve_app_session_lifecycle",
        "touch_app_session_lifecycle",
        "validate_app_session_csrf",
        "rotate_app_session_lifecycle",
        "revoke_app_session_family_for_logout",
    ):
        definition = _function_definition(source, helper_name)
        assert "SECURITY DEFINER" in definition
        assert "SET search_path = pg_catalog, pg_temp" in definition

    assert "OLD_RUNTIME_FUNCTIONS" in source
    assert "OLD_AUTH_FUNCTIONS" in source
    assert "OLD_SHARED_FUNCTIONS" in source
    assert "_strip_non_owner_helper_acl(old_functions + new_functions)" in source
    assert "DROP FUNCTION IF EXISTS mata_rls.{signature}" in source
    assert "FROM PUBLIC CASCADE" in source
    assert "acl.grantee <> procedure.proowner" in source
    assert "Retired session helper remains callable" in source


def test_logout_helper_is_termination_only_and_auth_boundary_only() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    logout_revoke = _function_definition(
        source,
        "revoke_app_session_family_for_logout",
    )

    assert "p_token_digest bytea" in logout_revoke
    assert "p_csrf_token_digest bytea" in logout_revoke
    assert "p_expected_session_id" not in logout_revoke
    assert "p_subject_id" not in logout_revoke
    assert "p_session_family_id" not in logout_revoke
    assert "token_session.token_digest = p_token_digest" in logout_revoke
    assert "csrf_session.csrf_token_digest = p_csrf_token_digest" in logout_revoke
    assert (
        "csrf_session.session_family_id = token_session.session_family_id"
        in logout_revoke
    )
    assert (
        "csrf_session.subject_session_generation\n"
        "            = token_session.subject_session_generation"
        in logout_revoke
    )
    assert "token_session.id = csrf_session.id" in logout_revoke
    assert "token_session.id <> csrf_session.id" in logout_revoke
    assert "csrf_session.revoked_reason = 'rotated'" in logout_revoke
    assert "observed_at < token_session.idle_expires_at" in logout_revoke
    assert "observed_at < token_session.absolute_expires_at" in logout_revoke
    assert "observed_at < csrf_session.absolute_expires_at" in logout_revoke
    assert "FOR UPDATE OF token_session, csrf_session" in logout_revoke
    assert "app_session.revoked_at IS NULL" in logout_revoke
    assert (
        '"revoke_app_session_family_for_logout(bytea,bytea,text)",'
        in source
    )
    assert (
        "('revoke_app_session_family_for_logout(bytea,bytea,text)', "
        "false, true)"
        in source
    )


def test_touch_and_signed_context_recheck_both_deadlines() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    touch = _function_definition(source, "touch_app_session_lifecycle")

    assert "FOR UPDATE" in touch
    assert "observed_at >= locked_session.idle_expires_at" in touch
    assert "observed_at >= locked_session.absolute_expires_at" in touch
    assert "p_touch_interval_seconds" in touch
    assert "LEAST(" in touch

    assert "session_is_active boolean" in source
    assert "'inactive-session-context-v1'" in source
    assert "RETURN pg_catalog.repeat('0', 64)" not in source
    assert "app_session.revoked_at IS NULL" in source
    assert (
        "pg_catalog.clock_timestamp() < app_session.idle_expires_at"
        in source
    )
    assert (
        "pg_catalog.clock_timestamp() < app_session.absolute_expires_at"
        in source
    )


def test_lifecycle_rotation_preserves_or_tightens_parent_activity_deadline() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    rotation = _function_definition(
        source,
        "rotate_app_session_lifecycle",
    )

    assert "last_seen_at = parent.last_seen_at" in rotation
    assert "child.idle_expires_at" in rotation
    assert "parent.idle_expires_at" in rotation
    assert "LEAST(" in rotation


def test_cleanup_retains_rotated_logout_proof_until_family_absolute_deadline() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    cleanup_replacement = source[
        source.index("def _replace_cleanup_helper("):
        source.index("def _set_helper_acl(")
    ]

    assert (
        "CREATE OR REPLACE FUNCTION mata_rls.cleanup_app_sessions("
        in cleanup_replacement
    )
    assert "SET search_path = pg_catalog, pg_temp" in cleanup_replacement
    assert "app_session.revoked_reason IS DISTINCT FROM 'rotated'" in (
        cleanup_replacement
    )
    assert (
        "OR app_session.absolute_expires_at\n"
        "                    <= pg_catalog.clock_timestamp()"
        in cleanup_replacement
    )
    assert (
        "_replace_cleanup_helper(protect_rotated_logout_proof=True)"
        in source
    )
    assert (
        "_replace_cleanup_helper(protect_rotated_logout_proof=False)"
        in source
    )
