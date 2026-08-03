from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.services.app_sessions import _session_family_lock_key
from app.services.database_context import (
    RLS_CONTEXT_INFO_KEY,
    RlsRuntimeRoleError,
    attest_database_role,
    configure_request_context,
    prime_request_context,
)
from tests.rls_postgres_harness import (
    AUTH_GROUP,
    RUNTIME_GROUP,
    RlsPostgresHarness,
    _quoted_test_role,
    rls_postgres_harness,
)


CONTEXT_GUCS = (
    "mata.subject_type",
    "mata.subject_id",
    "mata.app_role",
    "mata.admin_level",
    "mata.programme_scope_json",
    "mata.posting_code",
    "mata.app_session_id",
    "mata.authorization_fingerprint",
    "mata.context_signature",
)

RUNTIME_ONLY_FUNCTIONS = frozenset(
    {
        "mata_rls.install_request_context(bytea,text,text,uuid,uuid,text)",
        "mata_rls.context_is_valid()",
        "mata_rls.current_subject_type()",
        "mata_rls.current_subject_id()",
        "mata_rls.current_app_role()",
        "mata_rls.current_admin_level()",
        "mata_rls.current_programme_scope()",
        "mata_rls.current_posting_code()",
        "mata_rls.current_app_session_id()",
        "mata_rls.current_authorization_fingerprint()",
        "mata_rls.is_authenticated()",
        "mata_rls.is_master_admin()",
        "mata_rls.has_programme_scope(text)",
        "mata_rls.is_secretary_for_posting(text)",
        "mata_rls.is_native_resident(uuid)",
        "mata_rls.is_external_resident(uuid)",
        "mata_rls.uuid_advisory_key(uuid)",
        (
            "mata_rls.rotate_app_session_lifecycle("
            "bytea,uuid,uuid,bytea,bytea,integer,bytea)"
        ),
        "mata_rls.revoke_app_session_family(bytea,uuid,text)",
        "mata_rls.invalidate_subject_app_sessions(text,uuid,text,boolean)",
        "mata_rls.replace_external_resident_schedule(uuid,jsonb)",
        "mata_rls.set_external_resident_current_posting(uuid,text,text)",
        "mata_rls.resolve_ttf_session_type(text,numeric,text,text)",
        "mata_rls.ensure_ttf_posting_code(text,text)",
        "mata_rls.append_audit_log(text,text,text,jsonb,jsonb,jsonb)",
        (
            "mata_rls.create_adhoc_attendance("
            "text,text,text,text,text,date,time without time zone,"
            "time without time zone,numeric,uuid)"
        ),
        "mata_rls.update_own_staff_actor_name(text)",
        "mata_rls.reporting_period_dependency_counts(uuid)",
        "mata_rls.hibernate_stale_surplus(uuid)",
    }
)

AUTH_ONLY_FUNCTIONS = frozenset(
    {
        "mata_rls.staff_login_snapshot(text)",
        "mata_rls.staff_login_candidate(text)",
        "mata_rls.staff_login_identity(uuid,uuid,bigint)",
        "mata_rls.resident_login_candidate(text)",
        "mata_rls.external_registration_options()",
        "mata_rls.register_external_resident(text,text,text,jsonb)",
        (
            "mata_rls.issue_staff_app_session_lifecycle("
            "uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        (
            "mata_rls.issue_resident_app_session_lifecycle("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        (
            "mata_rls.issue_external_resident_app_session_lifecycle("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        "mata_rls.revoke_app_session_family_for_logout(bytea,bytea,text)",
    }
)

BOTH_GROUP_FUNCTIONS = frozenset(
    {
        "mata_rls.cleanup_app_sessions(integer,integer)",
        "mata_rls.consume_rate_limit(text,text,integer,integer,integer,integer)",
        "mata_rls.resolve_app_session_lifecycle(bytea,integer)",
        "mata_rls.touch_app_session_lifecycle(bytea,uuid,integer,integer)",
        "mata_rls.validate_app_session_csrf(bytea,uuid,bytea)",
        "mata_rls.revoke_app_session(bytea,uuid,text)",
    }
)

RETIRED_SESSION_FUNCTIONS = frozenset(
    {
        (
            "mata_rls.rotate_app_session("
            "bytea,uuid,uuid,bytea,bytea,integer,bytea)"
        ),
        (
            "mata_rls.issue_staff_app_session("
            "uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        (
            "mata_rls.issue_resident_app_session("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        (
            "mata_rls.issue_external_resident_app_session("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        "mata_rls.resolve_app_session(bytea,boolean,integer)",
    }
)

POLICY_HELPER_FUNCTIONS = frozenset(
    {
        "mata_rls.can_access_resident(uuid)",
        "mata_rls.can_manage_resident(uuid)",
        "mata_rls.can_access_form_f1(text)",
        "mata_rls.native_assignment_matches(text,text,uuid)",
        "mata_rls.can_access_teaching_catalogue(text,text,uuid)",
        "mata_rls.can_select_teaching_event(uuid)",
        (
            "mata_rls.can_insert_teaching_event("
            "text,text,text,date,boolean,text)"
        ),
        (
            "mata_rls.can_manage_teaching_event("
            "text,text,text,date,boolean,text)"
        ),
        "mata_rls.can_submit_native_attendance(uuid,uuid)",
        "mata_rls.can_access_external_attendance(uuid,uuid)",
        "mata_rls.can_submit_external_attendance(uuid,uuid)",
    }
)

PRIVATE_FUNCTIONS = frozenset(
    {
        "mata_private.normalized_scope(text[])",
        "mata_private.normalize_mcr(text)",
        (
            "mata_private.authorization_fingerprint("
            "text,uuid,bigint,text,text,text[],text,uuid,text)"
        ),
        (
            "mata_private.context_signature("
            "text,uuid,text,text,text[],text,uuid,text,"
            "bigint,integer,oid)"
        ),
        "mata_private.verified_context()",
        "mata_private.hydrate_app_session(bytea,text,boolean,integer)",
        "mata_private.mcr_advisory_key(text)",
        "mata_private.enforce_global_mcr_uniqueness()",
        (
            "mata_private.insert_root_app_session("
            "text,uuid,bigint,text,uuid,bytea,bytea,"
            "integer,integer,bytea)"
        ),
        "mata_private.resolve_external_schedule(jsonb)",
        "mata_private.can_select_teaching_event_000027(uuid)",
        (
            "mata_private.can_insert_teaching_event_000027("
            "text,text,text,date,boolean,text)"
        ),
        (
            "mata_private.can_submit_native_attendance_000027("
            "uuid,uuid)"
        ),
        (
            "mata_private.can_submit_external_attendance_000027("
            "uuid,uuid)"
        ),
        (
            "mata_private."
            "enforce_teaching_event_creator_immutability()"
        ),
        "mata_private.enforce_teaching_name_scope_immutability()",
        "mata_private.enforce_attendance_integrity()",
    }
)

_INSTALL_CONTEXT_SQL = text(
    """
    SELECT
        subject_type,
        subject_id,
        app_role,
        admin_level,
        programme_scope,
        posting_code,
        app_session_id,
        authorization_fingerprint
    FROM mata_rls.install_request_context(
        CAST(:token_digest AS bytea),
        CAST(:lock_mode AS text),
        CAST(:expected_subject_type AS text),
        CAST(:expected_subject_id AS uuid),
        CAST(:expected_app_session_id AS uuid),
        CAST(:expected_authorization_fingerprint AS text)
    )
    """
)

_CURRENT_CONTEXT_SQL = text(
    """
    SELECT
        mata_rls.context_is_valid() AS context_is_valid,
        mata_rls.current_subject_type() AS subject_type,
        mata_rls.current_subject_id() AS subject_id,
        mata_rls.current_app_role() AS app_role,
        mata_rls.current_admin_level() AS admin_level,
        mata_rls.current_programme_scope() AS programme_scope,
        mata_rls.current_posting_code() AS posting_code,
        mata_rls.current_app_session_id() AS app_session_id,
        mata_rls.current_authorization_fingerprint()
            AS authorization_fingerprint
    """
)

_RESOLVE_APP_SESSION_SQL = text(
    """
    SELECT *
    FROM mata_rls.resolve_app_session_lifecycle(
        CAST(:token_digest AS bytea),
        CAST(:rotation_threshold_seconds AS integer)
    )
    """
)

_TOUCH_APP_SESSION_SQL = text(
    """
    SELECT mata_rls.touch_app_session_lifecycle(
        CAST(:token_digest AS bytea),
        CAST(:expected_session_id AS uuid),
        CAST(:idle_timeout_seconds AS integer),
        CAST(:touch_interval_seconds AS integer)
    )
    """
)

POLICY_CUTOVER_REVISIONS = frozenset(
    {
        "20260726_000026",
        "20260727_000027",
        "20260728_000028",
        "20260802_000029",
        "20260803_000030",
    }
)
SESSION_LIFECYCLE_REVISIONS = frozenset(
    {
        "20260727_000027",
        "20260728_000028",
        "20260802_000029",
        "20260803_000030",
    }
)

ISSUE_LIFECYCLE_RESULT_COLUMNS = frozenset(
    {
        "id",
        "subject_type",
        "subject_id",
        "subject_session_generation",
        "session_family_id",
        "auth_source",
    }
)

RESOLVE_LIFECYCLE_RESULT_COLUMNS = frozenset(
    {
        "id",
        "subject_type",
        "subject_id",
        "subject_session_generation",
        "session_family_id",
        "auth_source",
        "authorization_fingerprint",
        "app_role",
        "admin_level",
        "programme_scope",
        "posting_code",
        "current_staff_actor_name",
        "session_refresh_required",
    }
)

ROTATE_LIFECYCLE_RESULT_COLUMNS = (
    ISSUE_LIFECYCLE_RESULT_COLUMNS | {"rotated_from_session_id"}
)


@dataclass(frozen=True, slots=True)
class StaffContextSeed:
    token_digest: bytes
    subject_id: UUID
    app_session_id: UUID
    session_family_id: UUID
    authorization_fingerprint: str

    def installer_parameters(self, **overrides: object) -> dict[str, object]:
        parameters: dict[str, object] = {
            "token_digest": self.token_digest,
            "lock_mode": "shared",
            "expected_subject_type": "staff",
            "expected_subject_id": self.subject_id,
            "expected_app_session_id": self.app_session_id,
            "expected_authorization_fingerprint": (
                self.authorization_fingerprint
            ),
        }
        parameters.update(overrides)
        return parameters


@dataclass(slots=True)
class _BorrowedConnectionEngine:
    """Expose one existing transaction to the production attestation helper."""

    connection: AsyncConnection

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        yield self.connection


async def _assert_adhoc_definer_creator_test_role(
    connection: AsyncConnection,
) -> None:
    creator = (
        await connection.execute(
            text(
                """
                SELECT
                    schema_owner.rolname = current_user
                        AS current_user_owns_schema,
                    schema_owner.rolcreaterole AS owner_can_create_role,
                    schema_owner.rolbypassrls AS owner_bypasses_rls,
                    grantor.rolsuper AS current_user_is_superuser
                FROM pg_catalog.pg_namespace AS namespace
                JOIN pg_catalog.pg_roles AS schema_owner
                  ON schema_owner.oid = namespace.nspowner
                JOIN pg_catalog.pg_roles AS grantor
                  ON grantor.rolname = current_user
                WHERE namespace.nspname = 'mata_rls'
                """
            )
        )
    ).mappings().one()
    assert dict(creator) == {
        "current_user_owns_schema": True,
        "owner_can_create_role": True,
        "owner_bypasses_rls": True,
        "current_user_is_superuser": True,
    }


async def _grant_adhoc_definer_membership(
    connection: AsyncConnection,
    *,
    member_role: str | None = None,
    set_enabled: bool = False,
) -> None:
    member_sql = (
        "CURRENT_USER"
        if member_role is None
        else _quoted_test_role(member_role)
    )
    await connection.exec_driver_sql(
        "GRANT mata_adhoc_attendance_definer "
        f"TO {member_sql} WITH ADMIN TRUE"
    )
    await connection.exec_driver_sql(
        "GRANT mata_adhoc_attendance_definer "
        f"TO {member_sql} WITH INHERIT FALSE"
    )
    await connection.exec_driver_sql(
        "GRANT mata_adhoc_attendance_definer "
        f"TO {member_sql} WITH SET {'TRUE' if set_enabled else 'FALSE'}"
    )


def _sqlstate(error: DBAPIError) -> str | None:
    original = error.orig
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


async def _install_context(
    db: AsyncSession,
    seed: StaffContextSeed,
    **overrides: object,
) -> Mapping[str, Any] | None:
    result = await db.execute(
        _INSTALL_CONTEXT_SQL,
        seed.installer_parameters(**overrides),
    )
    return result.mappings().one_or_none()


async def _current_context(db: AsyncSession) -> Mapping[str, Any]:
    return (await db.execute(_CURRENT_CONTEXT_SQL)).mappings().one()


async def _raw_context_gucs(db: AsyncSession) -> dict[str, str]:
    values: dict[str, str] = {}
    for guc_name in CONTEXT_GUCS:
        value = await db.scalar(
            text("SELECT current_setting(:guc_name, true)"),
            {"guc_name": guc_name},
        )
        values[guc_name] = str(value or "")
    return values


@pytest_asyncio.fixture
async def seeded_staff_context(
    rls_postgres_harness: RlsPostgresHarness,
) -> StaffContextSeed:
    subject_id = uuid4()
    app_session_id = uuid4()
    token_digest = secrets.token_bytes(32)
    csrf_digest = secrets.token_bytes(32)
    scope = ["GERI", "DR", "GERI"]

    async with rls_postgres_harness.owner_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO users (
                    id,
                    email,
                    password_hash,
                    role,
                    name,
                    programme_scope,
                    admin_level,
                    is_active,
                    supabase_user_id,
                    session_generation,
                    session_issuance_blocked
                )
                VALUES (
                    :subject_id,
                    :email,
                    'rls-foundation-owner-seed',
                    'admin',
                    'RLS Foundation Master',
                    :programme_scope,
                    'master',
                    true,
                    :subject_id,
                    0,
                    false
                )
                """
            ),
            {
                "subject_id": subject_id,
                "email": f"{subject_id.hex}@example.invalid",
                "programme_scope": scope,
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO app_sessions (
                    id,
                    token_digest,
                    subject_type,
                    subject_id,
                    subject_session_generation,
                    session_family_id,
                    auth_source,
                    csrf_token_digest,
                    idle_expires_at,
                    absolute_expires_at
                )
                VALUES (
                    :app_session_id,
                    :token_digest,
                    'staff',
                    :subject_id,
                    0,
                    :app_session_id,
                    'supabase_staff',
                    :csrf_digest,
                    now() + interval '1 hour',
                    now() + interval '8 hours'
                )
                """
            ),
            {
                "app_session_id": app_session_id,
                "token_digest": token_digest,
                "subject_id": subject_id,
                "csrf_digest": csrf_digest,
            },
        )
        authorization_fingerprint = await db.scalar(
            text(
                """
                SELECT mata_private.authorization_fingerprint(
                    'staff',
                    CAST(:subject_id AS uuid),
                    0,
                    'admin',
                    'master',
                    CAST(:programme_scope AS text[]),
                    NULL,
                    CAST(:app_session_id AS uuid),
                    'supabase_staff'
                )
                """
            ),
            {
                "subject_id": subject_id,
                "programme_scope": scope,
                "app_session_id": app_session_id,
            },
        )
        assert isinstance(authorization_fingerprint, str)
        assert len(authorization_fingerprint) == 64
        assert authorization_fingerprint == authorization_fingerprint.lower()
        await db.commit()

    seed = StaffContextSeed(
        token_digest=token_digest,
        subject_id=subject_id,
        app_session_id=app_session_id,
        session_family_id=app_session_id,
        authorization_fingerprint=authorization_fingerprint,
    )
    try:
        yield seed
    finally:
        async with rls_postgres_harness.owner_session() as db:
            await db.execute(
                text(
                    "DELETE FROM app_sessions "
                    "WHERE id = :app_session_id"
                ),
                {"app_session_id": app_session_id},
            )
            await db.execute(
                text("DELETE FROM users WHERE id = :subject_id"),
                {"subject_id": subject_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_rls_roles_are_hardened_and_runtime_login_is_attested(
    rls_postgres_harness: RlsPostgresHarness,
) -> None:
    harness = rls_postgres_harness
    checked_roles = (
        RUNTIME_GROUP,
        AUTH_GROUP,
        harness.runtime_role,
        harness.auth_role,
    )
    async with harness.owner_session() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT rolname, rolcanlogin, rolsuper, rolcreatedb,
                           rolcreaterole, rolreplication, rolbypassrls
                    FROM pg_roles
                    WHERE rolname = ANY(CAST(:role_names AS text[]))
                    ORDER BY rolname
                    """
                ),
                {"role_names": list(checked_roles)},
            )
        ).mappings().all()
        assert {str(row["rolname"]) for row in rows} == set(checked_roles)
        for row in rows:
            assert row["rolsuper"] is False
            assert row["rolcreatedb"] is False
            assert row["rolcreaterole"] is False
            assert row["rolreplication"] is False
            assert row["rolbypassrls"] is False
            if row["rolname"] in {RUNTIME_GROUP, AUTH_GROUP}:
                assert row["rolcanlogin"] is False
            else:
                assert row["rolcanlogin"] is True

        memberships = (
            await db.execute(
                text(
                    """
                    SELECT
                        pg_has_role(:runtime_role, :runtime_group, 'member')
                            AS runtime_member,
                        pg_has_role(:auth_role, :auth_group, 'member')
                            AS auth_member,
                        pg_has_role(:runtime_role, :auth_group, 'member')
                            AS runtime_is_not_auth,
                        pg_has_role(:auth_role, :runtime_group, 'member')
                            AS auth_is_not_runtime,
                        NOT EXISTS (
                            SELECT 1
                            FROM pg_auth_members AS membership
                            JOIN pg_roles AS granted_role
                              ON granted_role.oid = membership.roleid
                            JOIN pg_roles AS member_role
                              ON member_role.oid = membership.member
                            WHERE granted_role.rolname = :runtime_group
                              AND member_role.rolname = :runtime_role
                              AND membership.admin_option
                        ) AS runtime_membership_not_admin,
                        NOT EXISTS (
                            SELECT 1
                            FROM pg_auth_members AS membership
                            JOIN pg_roles AS granted_role
                              ON granted_role.oid = membership.roleid
                            JOIN pg_roles AS member_role
                              ON member_role.oid = membership.member
                            WHERE granted_role.rolname = :auth_group
                              AND member_role.rolname = :auth_role
                              AND membership.admin_option
                        ) AS auth_membership_not_admin
                    """
                ),
                {
                    "runtime_role": harness.runtime_role,
                    "runtime_group": RUNTIME_GROUP,
                    "auth_role": harness.auth_role,
                    "auth_group": AUTH_GROUP,
                },
            )
        ).mappings().one()
        assert memberships["runtime_member"] is True
        assert memberships["auth_member"] is True
        assert memberships["runtime_is_not_auth"] is False
        assert memberships["auth_is_not_runtime"] is False
        assert memberships["runtime_membership_not_admin"] is True
        assert memberships["auth_membership_not_admin"] is True

        owned_objects = await db.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                JOIN pg_roles AS r ON r.oid = c.relowner
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
                  AND r.rolname = ANY(CAST(:role_names AS text[]))
                """
            ),
            {"role_names": list(checked_roles)},
        )
        assert owned_objects == 0

    async with harness.runtime_session() as db:
        attestation = (
            await db.execute(
                text(
                    """
                    SELECT
                        current_user AS current_user,
                        session_user AS session_user,
                        current_setting('row_security') AS row_security
                    """
                )
            )
        ).mappings().one()
        assert attestation["current_user"] == harness.runtime_role
        assert attestation["session_user"] == harness.runtime_role
        assert attestation["row_security"] == "on"

    runtime_attestation = await attest_database_role(
        harness.runtime_engine,
        capability_group=RUNTIME_GROUP,
        forbidden_capability_group=AUTH_GROUP,
        require_context_installer=True,
        require_policy_cutover=(
            harness.revision in POLICY_CUTOVER_REVISIONS
        ),
    )
    assert runtime_attestation.login_role == harness.runtime_role
    assert runtime_attestation.capability_group == RUNTIME_GROUP

    auth_attestation = await attest_database_role(
        harness.auth_engine,
        capability_group=AUTH_GROUP,
        forbidden_capability_group=RUNTIME_GROUP,
        require_context_installer=False,
        require_policy_cutover=(
            harness.revision in POLICY_CUTOVER_REVISIONS
        ),
    )
    assert auth_attestation.login_role == harness.auth_role
    assert auth_attestation.capability_group == AUTH_GROUP


@pytest.mark.asyncio
async def test_policy_cutover_denies_public_schema_create_exactly(
    rls_postgres_harness: RlsPostgresHarness,
) -> None:
    harness = rls_postgres_harness
    if harness.revision not in POLICY_CUTOVER_REVISIONS:
        pytest.skip("Schema-public CREATE hardening is installed by revision 000026")

    restricted_roles = [
        RUNTIME_GROUP,
        AUTH_GROUP,
        harness.runtime_role,
        harness.auth_role,
        "anon",
        "authenticated",
        "service_role",
    ]
    async with harness.owner_session() as db:
        public_create_grants = await db.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_namespace AS public_schema
                CROSS JOIN LATERAL aclexplode(
                    coalesce(
                        public_schema.nspacl,
                        acldefault('n', public_schema.nspowner)
                    )
                ) AS privilege
                WHERE public_schema.nspname = 'public'
                  AND privilege.grantee = 0
                  AND privilege.privilege_type = 'CREATE'
                """
            )
        )
        roles_with_create = (
            await db.execute(
                text(
                    """
                    SELECT role.rolname
                    FROM pg_roles AS role
                    WHERE role.rolname = ANY(CAST(:roles AS text[]))
                      AND has_schema_privilege(
                          role.oid,
                          'public',
                          'CREATE'
                      )
                    ORDER BY role.rolname
                    """
                ),
                {"roles": restricted_roles},
            )
        ).scalars().all()

    assert public_create_grants == 0
    assert roles_with_create == []


@pytest.mark.asyncio
async def test_startup_attestation_accepts_bounded_adhoc_definer_creator_edge(
    rls_postgres_harness: RlsPostgresHarness,
) -> None:
    harness = rls_postgres_harness
    if harness.revision not in SESSION_LIFECYCLE_REVISIONS:
        pytest.skip("Ad-hoc definer requires a session-lifecycle revision")

    async with harness.owner_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _assert_adhoc_definer_creator_test_role(connection)
            await _grant_adhoc_definer_membership(connection)
            memberships = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            member_role.oid = namespace.nspowner
                                AS member_is_schema_owner,
                            member_role.rolcreaterole
                                AS member_can_create_role,
                            member_role.rolbypassrls
                                AS member_bypasses_rls,
                            grantor_role.rolsuper AS grantor_is_superuser,
                            membership.admin_option,
                            membership.inherit_option,
                            membership.set_option
                        FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS definer_role
                          ON definer_role.oid = membership.roleid
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        JOIN pg_catalog.pg_roles AS grantor_role
                          ON grantor_role.oid = membership.grantor
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.nspname = 'mata_rls'
                        WHERE definer_role.rolname
                            = 'mata_adhoc_attendance_definer'
                        ORDER BY member_role.rolname, grantor_role.rolname
                        """
                    )
                )
            ).mappings().all()
            assert [dict(row) for row in memberships] == [
                {
                    "member_is_schema_owner": True,
                    "member_can_create_role": True,
                    "member_bypasses_rls": True,
                    "grantor_is_superuser": True,
                    "admin_option": True,
                    "inherit_option": False,
                    "set_option": False,
                }
            ]

            await connection.exec_driver_sql(
                "SET LOCAL SESSION AUTHORIZATION "
                f'"{harness.runtime_role}"'
            )
            attestation = await attest_database_role(
                _BorrowedConnectionEngine(connection),  # type: ignore[arg-type]
                capability_group=RUNTIME_GROUP,
                forbidden_capability_group=AUTH_GROUP,
                require_context_installer=True,
                require_policy_cutover=True,
            )
            assert attestation.login_role == harness.runtime_role
            assert attestation.capability_group == RUNTIME_GROUP
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation_kind",
    [
        "table_grant",
        "column_grant",
        "helper_grant",
        "session_helper_third_role_grant",
        "browser_membership",
        "capability_admin_option",
        "schema_grant_option",
        "helper_grant_option",
        "table_grant_option",
        "column_grant_option",
        "public_schema_create",
        "browser_schema_create",
        "helper_security_invoker",
        "helper_search_path",
        "adhoc_definer_membership",
        "adhoc_definer_set_membership",
        "adhoc_definer_foreign_membership",
        "adhoc_definer_additional_membership",
        "adhoc_definer_schema_grant",
        "adhoc_definer_table_grant",
        "adhoc_definer_function_grant",
        "adhoc_definer_public_function_grant",
        "adhoc_definer_grant_option",
        "policy_name",
        "policy_predicate",
    ],
)
async def test_startup_attestation_rejects_transactional_privilege_injection(
    rls_postgres_harness: RlsPostgresHarness,
    mutation_kind: str,
) -> None:
    harness = rls_postgres_harness
    require_policy_cutover = harness.revision in POLICY_CUTOVER_REVISIONS

    # Establish that this mutation starts and ends from the reviewed contract.
    await attest_database_role(
        harness.runtime_engine,
        capability_group=RUNTIME_GROUP,
        forbidden_capability_group=AUTH_GROUP,
        require_context_installer=True,
        require_policy_cutover=require_policy_cutover,
    )

    expected_failed_check = {
        "table_grant": "executable_table_privileges",
        "column_grant": "executable_column_privileges",
        "helper_grant": "executable_rls_helpers",
        "session_helper_third_role_grant": (
            "session_helper_acls_are_exact"
        ),
        "browser_membership": "browser_roles_are_denied",
        "capability_admin_option": (
            "capability_membership_is_not_delegable"
        ),
        "schema_grant_option": "has_no_delegable_acl_privileges",
        "helper_grant_option": "has_no_delegable_acl_privileges",
        "table_grant_option": "has_no_delegable_acl_privileges",
        "column_grant_option": "has_no_delegable_acl_privileges",
        "public_schema_create": "public_schema_create_is_denied",
        "browser_schema_create": "browser_roles_are_denied",
        "helper_security_invoker": "executable_rls_helpers_are_hardened",
        "helper_search_path": "executable_rls_helpers_are_hardened",
        "adhoc_definer_membership": (
            "executable_rls_helpers_are_hardened"
        ),
        "adhoc_definer_set_membership": (
            "executable_rls_helpers_are_hardened"
        ),
        "adhoc_definer_foreign_membership": (
            "executable_rls_helpers_are_hardened"
        ),
        "adhoc_definer_additional_membership": (
            "executable_rls_helpers_are_hardened"
        ),
        "adhoc_definer_schema_grant": (
            "adhoc_definer_acl_surface_is_exact"
        ),
        "adhoc_definer_table_grant": (
            "adhoc_definer_acl_surface_is_exact"
        ),
        "adhoc_definer_function_grant": (
            "adhoc_definer_acl_surface_is_exact"
        ),
        "adhoc_definer_public_function_grant": (
            "adhoc_definer_acl_surface_is_exact"
        ),
        "adhoc_definer_grant_option": (
            "adhoc_definer_acl_surface_is_exact"
        ),
        "policy_name": "application_policy_catalogue",
        "policy_predicate": "unsafe_application_policy_count",
    }[mutation_kind]

    async with harness.owner_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            quoted_runtime_role = _quoted_test_role(harness.runtime_role)
            if mutation_kind == "table_grant":
                await connection.exec_driver_sql(
                    "GRANT SELECT ON TABLE public.app_sessions "
                    "TO mata_app_runtime"
                )
            elif mutation_kind == "column_grant":
                await connection.exec_driver_sql(
                    "GRANT SELECT (password_hash) ON TABLE public.users "
                    "TO mata_app_runtime"
                )
            elif mutation_kind == "helper_grant":
                await connection.exec_driver_sql(
                    "GRANT EXECUTE ON FUNCTION "
                    "mata_rls.staff_login_candidate(text) "
                    "TO mata_app_runtime"
                )
            elif mutation_kind == "session_helper_third_role_grant":
                third_role = f"mata_test_auth_{uuid4().hex[:16]}"
                quoted_third_role = _quoted_test_role(third_role)
                await connection.exec_driver_sql(
                    f"CREATE ROLE {quoted_third_role} "
                    "NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION"
                )
                await connection.exec_driver_sql(
                    "GRANT EXECUTE ON FUNCTION "
                    "mata_rls.resolve_app_session(bytea,boolean,integer) "
                    f"TO {quoted_third_role}"
                )
            elif mutation_kind in {
                "browser_membership",
                "browser_schema_create",
            }:
                browser_exists = bool(
                    await connection.scalar(
                        text(
                            "SELECT EXISTS ("
                            "SELECT 1 FROM pg_roles "
                            "WHERE rolname = 'authenticated')"
                        )
                    )
                )
                if not browser_exists:
                    await connection.exec_driver_sql(
                        "CREATE ROLE authenticated "
                        "NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION"
                    )
                if mutation_kind == "browser_membership":
                    await connection.exec_driver_sql(
                        "GRANT mata_app_runtime TO authenticated"
                    )
                else:
                    await connection.exec_driver_sql(
                        "GRANT CREATE ON SCHEMA public TO authenticated"
                    )
            elif mutation_kind == "capability_admin_option":
                await connection.exec_driver_sql(
                    "GRANT mata_app_runtime TO "
                    f"{quoted_runtime_role} WITH ADMIN OPTION"
                )
            elif mutation_kind == "schema_grant_option":
                await connection.exec_driver_sql(
                    "GRANT USAGE ON SCHEMA mata_rls TO "
                    f"{quoted_runtime_role} WITH GRANT OPTION"
                )
            elif mutation_kind == "helper_grant_option":
                await connection.exec_driver_sql(
                    "GRANT EXECUTE ON FUNCTION "
                    "mata_rls.install_request_context("
                    "bytea,text,text,uuid,uuid,text) TO "
                    f"{quoted_runtime_role} WITH GRANT OPTION"
                )
            elif mutation_kind == "table_grant_option":
                await connection.exec_driver_sql(
                    "GRANT SELECT ON TABLE public.posting_codes TO "
                    f"{quoted_runtime_role} WITH GRANT OPTION"
                )
            elif mutation_kind == "column_grant_option":
                await connection.exec_driver_sql(
                    "GRANT SELECT (id) ON TABLE public.users TO "
                    f"{quoted_runtime_role} WITH GRANT OPTION"
                )
            elif mutation_kind == "public_schema_create":
                await connection.exec_driver_sql(
                    "GRANT CREATE ON SCHEMA public TO PUBLIC"
                )
            elif mutation_kind == "helper_security_invoker":
                await connection.exec_driver_sql(
                    "ALTER FUNCTION mata_rls.install_request_context("
                    "bytea,text,text,uuid,uuid,text) SECURITY INVOKER"
                )
            elif mutation_kind == "helper_search_path":
                await connection.exec_driver_sql(
                    "ALTER FUNCTION mata_rls.install_request_context("
                    "bytea,text,text,uuid,uuid,text) "
                    "SET search_path = public"
                )
            elif mutation_kind in {
                "adhoc_definer_membership",
                "adhoc_definer_set_membership",
                "adhoc_definer_foreign_membership",
                "adhoc_definer_additional_membership",
            }:
                if harness.revision not in SESSION_LIFECYCLE_REVISIONS:
                    pytest.skip(
                        "Ad-hoc definer requires a session-lifecycle revision"
                    )
                if mutation_kind == "adhoc_definer_membership":
                    third_role = f"mata_test_auth_{uuid4().hex[:16]}"
                    quoted_third_role = _quoted_test_role(third_role)
                    await connection.exec_driver_sql(
                        f"CREATE ROLE {quoted_third_role} "
                        "NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION"
                    )
                    await connection.exec_driver_sql(
                        f"GRANT {quoted_third_role} "
                        "TO mata_adhoc_attendance_definer"
                    )
                else:
                    await _assert_adhoc_definer_creator_test_role(connection)
                    if mutation_kind == "adhoc_definer_set_membership":
                        await _grant_adhoc_definer_membership(
                            connection,
                            set_enabled=True,
                        )
                    else:
                        third_role = f"mata_test_auth_{uuid4().hex[:16]}"
                        quoted_third_role = _quoted_test_role(third_role)
                        await connection.exec_driver_sql(
                            f"CREATE ROLE {quoted_third_role} "
                            "NOLOGIN NOINHERIT NOSUPERUSER BYPASSRLS "
                            "NOCREATEDB CREATEROLE NOREPLICATION"
                        )
                        if mutation_kind == (
                            "adhoc_definer_foreign_membership"
                        ):
                            await connection.exec_driver_sql(
                                "REVOKE mata_adhoc_attendance_definer "
                                "FROM CURRENT_USER"
                            )
                        else:
                            assert mutation_kind == (
                                "adhoc_definer_additional_membership"
                            )
                            await _grant_adhoc_definer_membership(
                                connection
                            )
                        await _grant_adhoc_definer_membership(
                            connection,
                            member_role=third_role,
                        )
            elif mutation_kind.startswith("adhoc_definer_"):
                if harness.revision not in SESSION_LIFECYCLE_REVISIONS:
                    pytest.skip(
                        "Ad-hoc definer requires a session-lifecycle revision"
                    )
                if mutation_kind == "adhoc_definer_schema_grant":
                    statement = (
                        "GRANT CREATE ON SCHEMA mata_rls "
                        "TO mata_adhoc_attendance_definer"
                    )
                elif mutation_kind == "adhoc_definer_table_grant":
                    statement = (
                        "GRANT UPDATE ON TABLE public.reporting_periods "
                        "TO mata_adhoc_attendance_definer"
                    )
                elif mutation_kind == "adhoc_definer_function_grant":
                    statement = (
                        "GRANT EXECUTE ON FUNCTION "
                        "mata_rls.is_authenticated() "
                        "TO mata_adhoc_attendance_definer"
                    )
                elif mutation_kind == (
                    "adhoc_definer_public_function_grant"
                ):
                    statement = (
                        "GRANT EXECUTE ON FUNCTION "
                        "mata_rls.current_subject_type() TO PUBLIC"
                    )
                else:
                    assert mutation_kind == "adhoc_definer_grant_option"
                    statement = (
                        "GRANT EXECUTE ON FUNCTION "
                        "mata_rls.current_subject_type() "
                        "TO mata_adhoc_attendance_definer "
                        "WITH GRANT OPTION"
                    )
                await connection.exec_driver_sql(statement)
            elif mutation_kind in {"policy_name", "policy_predicate"}:
                if not require_policy_cutover:
                    pytest.skip("Policy mutation requires revision 000026 or later")
                if mutation_kind == "policy_name":
                    await connection.exec_driver_sql(
                        "ALTER POLICY mata_rls_users_select ON public.users "
                        "RENAME TO mata_rls_users_select_drifted"
                    )
                else:
                    await connection.exec_driver_sql(
                        "ALTER POLICY mata_rls_users_select ON public.users "
                        "USING (true)"
                    )
            else:  # pragma: no cover - parameter list is closed above
                raise AssertionError(
                    f"Unexpected attestation mutation: {mutation_kind}"
                )

            # Production attestation normally opens its own connection. Borrow
            # this owner transaction and locally assume the ephemeral runtime
            # login so it sees the uncommitted catalogue mutation. ROLLBACK
            # restores both SESSION_USER and every injected privilege.
            await connection.exec_driver_sql(
                "SET LOCAL SESSION AUTHORIZATION "
                f'"{harness.runtime_role}"'
            )
            identity = (
                await connection.execute(
                    text(
                        "SELECT session_user::text, current_user::text"
                    )
                )
            ).one()
            assert identity == (
                harness.runtime_role,
                harness.runtime_role,
            )

            with pytest.raises(RlsRuntimeRoleError) as failure:
                await attest_database_role(
                    _BorrowedConnectionEngine(connection),  # type: ignore[arg-type]
                    capability_group=RUNTIME_GROUP,
                    forbidden_capability_group=AUTH_GROUP,
                    require_context_installer=True,
                    require_policy_cutover=require_policy_cutover,
                )
            assert expected_failed_check in str(failure.value)
        finally:
            await transaction.rollback()

    # The mutation must not survive the rollback, including a browser role
    # created only to exercise the membership check.
    restored = await attest_database_role(
        harness.runtime_engine,
        capability_group=RUNTIME_GROUP,
        forbidden_capability_group=AUTH_GROUP,
        require_context_installer=True,
        require_policy_cutover=require_policy_cutover,
    )
    assert restored.login_role == harness.runtime_role
    assert restored.capability_group == RUNTIME_GROUP


@pytest.mark.asyncio
async def test_verified_context_installer_returns_only_database_identity(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    async with rls_postgres_harness.runtime_session() as db:
        installed = await _install_context(db, seeded_staff_context)
        assert installed is not None
        assert dict(installed) == {
            "subject_type": "staff",
            "subject_id": seeded_staff_context.subject_id,
            "app_role": "admin",
            "admin_level": "master",
            "programme_scope": ["DR", "GERI"],
            "posting_code": None,
            "app_session_id": seeded_staff_context.app_session_id,
            "authorization_fingerprint": (
                seeded_staff_context.authorization_fingerprint
            ),
        }

        context = await _current_context(db)
        assert context["context_is_valid"] is True
        assert context["subject_type"] == "staff"
        assert context["subject_id"] == seeded_staff_context.subject_id
        assert context["app_role"] == "admin"
        assert context["admin_level"] == "master"
        assert context["programme_scope"] == ["DR", "GERI"]
        assert context["posting_code"] is None
        assert context["app_session_id"] == seeded_staff_context.app_session_id
        assert (
            context["authorization_fingerprint"]
            == seeded_staff_context.authorization_fingerprint
        )

        predicates = (
            await db.execute(
                text(
                    """
                    SELECT
                        mata_rls.is_authenticated() AS authenticated,
                        mata_rls.is_master_admin() AS master,
                        mata_rls.has_programme_scope('dr') AS in_scope,
                        mata_rls.has_programme_scope('  ') AS blank_scope,
                        mata_rls.is_secretary_for_posting('TTSHGenMed')
                            AS secretary,
                        mata_rls.is_native_resident(:subject_id)
                            AS native_resident,
                        mata_rls.is_external_resident(:subject_id)
                            AS external_resident
                    """
                ),
                {"subject_id": seeded_staff_context.subject_id},
            )
        ).mappings().one()
        assert dict(predicates) == {
            "authenticated": True,
            "master": True,
            # Master access is expressed by is_master_admin(); the scoped
            # predicate remains deliberately specific to programme admins.
            "in_scope": False,
            "blank_scope": False,
            "secretary": False,
            "native_resident": False,
            "external_resident": False,
        }


@pytest.mark.asyncio
async def test_session_lifecycle_helpers_return_only_minimum_results(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    harness = rls_postgres_harness
    if harness.revision not in SESSION_LIFECYCLE_REVISIONS:
        pytest.skip("Minimum lifecycle wrappers are installed by revision 000027")

    parent_id = uuid4()
    child_id = uuid4()
    parent_digest = secrets.token_bytes(32)
    child_digest = secrets.token_bytes(32)
    parent_csrf_digest = secrets.token_bytes(32)
    child_csrf_digest = secrets.token_bytes(32)
    try:
        async with harness.auth_session() as auth_db:
            issued = (
                await auth_db.execute(
                    text(
                        """
                        SELECT *
                        FROM mata_rls.issue_staff_app_session_lifecycle(
                            CAST(:subject_id AS uuid),
                            CAST(:subject_id AS uuid),
                            CAST(0 AS bigint),
                            CAST(:parent_id AS uuid),
                            CAST(:parent_digest AS bytea),
                            CAST(:parent_csrf_digest AS bytea),
                            CAST(1800 AS integer),
                            CAST(28800 AS integer),
                            CAST(NULL AS bytea)
                        )
                        """
                    ),
                    {
                        "subject_id": seeded_staff_context.subject_id,
                        "parent_id": parent_id,
                        "parent_digest": parent_digest,
                        "parent_csrf_digest": parent_csrf_digest,
                    },
                )
            ).mappings().one()
            assert frozenset(issued.keys()) == ISSUE_LIFECYCLE_RESULT_COLUMNS
            assert issued["id"] == parent_id
            assert issued["session_family_id"] == parent_id

            resolved = (
                await auth_db.execute(
                    _RESOLVE_APP_SESSION_SQL,
                    {
                        "token_digest": parent_digest,
                        "rotation_threshold_seconds": 3600,
                    },
                )
            ).mappings().one()
            assert frozenset(resolved.keys()) == RESOLVE_LIFECYCLE_RESULT_COLUMNS
            assert resolved["id"] == parent_id
            assert resolved["subject_id"] == seeded_staff_context.subject_id
            assert resolved["session_refresh_required"] is False
            await auth_db.commit()

        async with harness.runtime_session() as runtime_db:
            rotated = (
                await runtime_db.execute(
                    text(
                        """
                        SELECT *
                        FROM mata_rls.rotate_app_session_lifecycle(
                            CAST(:parent_digest AS bytea),
                            CAST(:parent_id AS uuid),
                            CAST(:child_id AS uuid),
                            CAST(:child_digest AS bytea),
                            CAST(:child_csrf_digest AS bytea),
                            CAST(1800 AS integer),
                            CAST(NULL AS bytea)
                        )
                        """
                    ),
                    {
                        "parent_digest": parent_digest,
                        "parent_id": parent_id,
                        "child_id": child_id,
                        "child_digest": child_digest,
                        "child_csrf_digest": child_csrf_digest,
                    },
                )
            ).mappings().one()
            assert frozenset(rotated.keys()) == ROTATE_LIFECYCLE_RESULT_COLUMNS
            assert rotated["id"] == child_id
            assert rotated["session_family_id"] == parent_id
            assert rotated["rotated_from_session_id"] == parent_id
            await runtime_db.commit()

        async with harness.owner_session() as owner_db:
            rows = (
                await owner_db.execute(
                    text(
                        """
                        SELECT
                            id,
                            revoked_at,
                            last_seen_at,
                            idle_expires_at,
                            absolute_expires_at
                        FROM app_sessions
                        WHERE session_family_id = :family_id
                        ORDER BY created_at, id
                        """
                    ),
                    {"family_id": parent_id},
                )
            ).mappings().all()
            assert [row["id"] for row in rows] == [parent_id, child_id]
            assert rows[0]["revoked_at"] is not None
            assert rows[1]["revoked_at"] is None
            assert rows[0]["absolute_expires_at"] == rows[1][
                "absolute_expires_at"
            ]
            assert rows[0]["last_seen_at"] == rows[1]["last_seen_at"]
            assert rows[1]["last_seen_at"] < rows[1]["idle_expires_at"]
            assert rows[0]["idle_expires_at"] == rows[1]["idle_expires_at"]
    finally:
        async with harness.owner_session() as owner_db:
            await owner_db.execute(
                text(
                    "DELETE FROM app_sessions "
                    "WHERE session_family_id = :family_id"
                ),
                {"family_id": parent_id},
            )
            await owner_db.commit()


@pytest.mark.asyncio
async def test_no_context_denies_identity_and_protected_table_access(
    rls_postgres_harness: RlsPostgresHarness,
) -> None:
    async with rls_postgres_harness.runtime_session() as db:
        context = await _current_context(db)
        assert context["context_is_valid"] is False
        assert context["subject_type"] is None
        assert context["subject_id"] is None
        assert context["app_role"] is None
        assert context["app_session_id"] is None

        try:
            residents = (
                await db.execute(text("SELECT id FROM residents LIMIT 1"))
            ).all()
        except DBAPIError as error:
            assert _sqlstate(error) == "42501"
            await db.rollback()
        else:
            # Foundation has no direct table grant; after the policy migration,
            # RLS may instead expose an empty result to a context-free runtime.
            assert residents == []


@pytest.mark.asyncio
async def test_forged_or_replayed_gucs_and_binding_mismatches_are_rejected(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    fake_values = {
        "mata.subject_type": "staff",
        "mata.subject_id": str(seeded_staff_context.subject_id),
        "mata.app_role": "admin",
        "mata.admin_level": "master",
        "mata.programme_scope_json": '["DR","GERI"]',
        "mata.posting_code": "",
        "mata.app_session_id": str(seeded_staff_context.app_session_id),
        "mata.authorization_fingerprint": (
            seeded_staff_context.authorization_fingerprint
        ),
        "mata.context_signature": "0" * 64,
    }

    async with rls_postgres_harness.runtime_session() as db:
        for guc_name, guc_value in fake_values.items():
            await db.execute(
                text("SELECT set_config(:guc_name, :guc_value, true)"),
                {"guc_name": guc_name, "guc_value": guc_value},
            )
        context = await _current_context(db)
        assert context["context_is_valid"] is False
        assert context["subject_id"] is None

        mismatch = await _install_context(
            db,
            seeded_staff_context,
            expected_subject_id=uuid4(),
        )
        assert mismatch is None
        assert (await _current_context(db))["context_is_valid"] is False

        installed = await _install_context(db, seeded_staff_context)
        assert installed is not None
        signed_values = await _raw_context_gucs(db)
        assert signed_values["mata.context_signature"]
        await db.commit()

        for guc_name, guc_value in signed_values.items():
            await db.execute(
                text("SELECT set_config(:guc_name, :guc_value, true)"),
                {"guc_name": guc_name, "guc_value": guc_value},
            )
        replayed = await _current_context(db)
        assert replayed["context_is_valid"] is False
        assert replayed["subject_id"] is None
        await db.rollback()


@pytest.mark.asyncio
async def test_installer_rejects_stale_authorization_after_subject_change(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    async with rls_postgres_harness.owner_session() as owner_db:
        await owner_db.execute(
            text(
                """
                UPDATE users
                SET programme_scope = ARRAY['DR', 'GERI', 'IM']::text[]
                WHERE id = :subject_id
                """
            ),
            {"subject_id": seeded_staff_context.subject_id},
        )
        await owner_db.commit()

    async with rls_postgres_harness.runtime_session() as runtime_db:
        assert await _install_context(runtime_db, seeded_staff_context) is None
        context = await _current_context(runtime_db)
        assert context["context_is_valid"] is False
        assert context["subject_id"] is None


@pytest.mark.asyncio
async def test_context_clears_after_commit_rollback_and_pool_reuse(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    first_backend_pid: int
    async with rls_postgres_harness.runtime_session() as db:
        first_backend_pid = int(await db.scalar(text("SELECT pg_backend_pid()")))
        assert await _install_context(db, seeded_staff_context) is not None
        assert (await _current_context(db))["context_is_valid"] is True
        await db.commit()

        assert (
            int(await db.scalar(text("SELECT pg_backend_pid()")))
            == first_backend_pid
        )
        assert (await _current_context(db))["context_is_valid"] is False
        await db.rollback()

        assert await _install_context(db, seeded_staff_context) is not None
        assert (await _current_context(db))["context_is_valid"] is True
        await db.rollback()

        assert (
            int(await db.scalar(text("SELECT pg_backend_pid()")))
            == first_backend_pid
        )
        assert (await _current_context(db))["context_is_valid"] is False
        await db.rollback()

    async with rls_postgres_harness.runtime_session() as reused_db:
        assert (
            int(await reused_db.scalar(text("SELECT pg_backend_pid()")))
            == first_backend_pid
        )
        assert (await _current_context(reused_db))["context_is_valid"] is False


@pytest.mark.asyncio
async def test_expiry_invalidates_context_and_pool_size_one_reuse_is_empty(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    harness = rls_postgres_harness
    backend_pid: int
    async with harness.runtime_session() as runtime_db:
        backend_pid = int(
            await runtime_db.scalar(text("SELECT pg_backend_pid()"))
        )
        assert await _install_context(runtime_db, seeded_staff_context) is not None
        assert (await _current_context(runtime_db))["context_is_valid"] is True

        async with harness.owner_session() as owner_db:
            await owner_db.execute(
                text(
                    """
                    WITH deadline AS MATERIALIZED (
                        SELECT clock_timestamp() AS expired_at
                    )
                    UPDATE app_sessions AS app_session
                    SET
                        last_seen_at = deadline.expired_at,
                        idle_expires_at = deadline.expired_at,
                        absolute_expires_at = deadline.expired_at
                    FROM deadline
                    WHERE app_session.id = :app_session_id
                    """
                ),
                {"app_session_id": seeded_staff_context.app_session_id},
            )
            await owner_db.commit()

        expired_context = await _current_context(runtime_db)
        assert expired_context["context_is_valid"] is False
        assert expired_context["subject_type"] is None
        assert expired_context["subject_id"] is None
        assert expired_context["app_role"] is None
        assert expired_context["app_session_id"] is None

        assert await _install_context(runtime_db, seeded_staff_context) is None
        await runtime_db.execute(
            text(
                """
                SELECT set_config(
                    'mata.context_signature',
                    repeat('0', 64),
                    true
                )
                """
            )
        )
        assert (await _current_context(runtime_db))["context_is_valid"] is False
        await runtime_db.rollback()

    async with harness.runtime_session() as reused_db:
        assert (
            int(await reused_db.scalar(text("SELECT pg_backend_pid()")))
            == backend_pid
        )
        assert (await _current_context(reused_db))["context_is_valid"] is False
        assert all(
            raw_value == ""
            for raw_value in (await _raw_context_gucs(reused_db)).values()
        )


@pytest.mark.asyncio
async def test_context_hook_revalidates_after_every_new_root_transaction(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    async with rls_postgres_harness.runtime_context_session() as db:
        configure_request_context(
            db,
            token_digest=seeded_staff_context.token_digest,
            expected_subject_type="staff",
            expected_subject_id=seeded_staff_context.subject_id,
            expected_app_session_id=seeded_staff_context.app_session_id,
            expected_authorization_fingerprint=(
                seeded_staff_context.authorization_fingerprint
            ),
            lock_mode="shared",
        )

        first = await prime_request_context(db)
        assert first["subject_id"] == seeded_staff_context.subject_id
        assert db.info[RLS_CONTEXT_INFO_KEY]["app_session_id"] == (
            seeded_staff_context.app_session_id
        )
        await db.commit()
        assert RLS_CONTEXT_INFO_KEY not in db.info

        after_commit = await prime_request_context(db)
        assert after_commit["subject_id"] == seeded_staff_context.subject_id
        await db.rollback()
        assert RLS_CONTEXT_INFO_KEY not in db.info

        after_rollback = await prime_request_context(db)
        assert after_rollback["subject_id"] == seeded_staff_context.subject_id
        assert after_rollback["authorization_fingerprint"] == (
            seeded_staff_context.authorization_fingerprint
        )


@pytest.mark.asyncio
async def test_failed_transaction_cannot_leak_context_through_runtime_pool(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    async with rls_postgres_harness.runtime_session() as db:
        backend_pid = int(await db.scalar(text("SELECT pg_backend_pid()")))
        assert await _install_context(db, seeded_staff_context) is not None
        with pytest.raises(DBAPIError) as caught:
            await db.execute(text("SELECT 1 / 0"))
        assert _sqlstate(caught.value) == "22012"
        await db.rollback()

    async with rls_postgres_harness.runtime_session() as reused_db:
        assert (
            int(await reused_db.scalar(text("SELECT pg_backend_pid()")))
            == backend_pid
        )
        assert (await _current_context(reused_db))["context_is_valid"] is False


@pytest.mark.asyncio
async def test_installer_shared_lock_matches_python_session_family_lock(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    expected_key = _session_family_lock_key(seeded_staff_context.session_family_id)

    async with rls_postgres_harness.runtime_session() as runtime_db:
        database_key = await runtime_db.scalar(
            text(
                "SELECT mata_rls.uuid_advisory_key("
                "CAST(:session_family_id AS uuid))"
            ),
            {"session_family_id": seeded_staff_context.session_family_id},
        )
        assert database_key == expected_key
        assert await _install_context(runtime_db, seeded_staff_context) is not None

        async with rls_postgres_harness.owner_session() as competing_db:
            acquired_while_shared = await competing_db.scalar(
                text(
                    "SELECT pg_try_advisory_xact_lock("
                    "CAST(:family_lock_key AS bigint))"
                ),
                {"family_lock_key": expected_key},
            )
            assert acquired_while_shared is False

            await runtime_db.rollback()

            acquired_after_rollback = await competing_db.scalar(
                text(
                    "SELECT pg_try_advisory_xact_lock("
                    "CAST(:family_lock_key AS bigint))"
                ),
                {"family_lock_key": expected_key},
            )
            assert acquired_after_rollback is True
            await competing_db.rollback()


@pytest.mark.asyncio
async def test_concurrent_session_touches_do_not_lock_upgrade_deadlock(
    rls_postgres_harness: RlsPostgresHarness,
    seeded_staff_context: StaffContextSeed,
) -> None:
    harness = rls_postgres_harness
    barrier = asyncio.Barrier(2)
    concurrent_engine = create_async_engine(
        harness.runtime_engine.url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )

    async def resolve_then_touch() -> tuple[int, bool]:
        async with AsyncSession(
            concurrent_engine,
            expire_on_commit=False,
        ) as db:
            await db.execute(text("SET LOCAL statement_timeout = '10s'"))
            initial = (
                await db.execute(
                    _RESOLVE_APP_SESSION_SQL,
                    {
                        "token_digest": seeded_staff_context.token_digest,
                        "rotation_threshold_seconds": 3600,
                    },
                )
            ).mappings().one()
            assert initial["id"] == seeded_staff_context.app_session_id
            backend_pid = int(
                await db.scalar(text("SELECT pg_backend_pid()"))
            )

            # Both transactions retain their read-only subject/family locks
            # before either attempts the row-updating touch. This reproduces
            # the former SHARE -> UPDATE lock-upgrade deadlock deterministically.
            await barrier.wait()
            touched = bool(
                await db.scalar(
                    _TOUCH_APP_SESSION_SQL,
                    {
                        "token_digest": seeded_staff_context.token_digest,
                        "expected_session_id": (
                            seeded_staff_context.app_session_id
                        ),
                        "idle_timeout_seconds": 1800,
                        "touch_interval_seconds": 60,
                    },
                )
            )
            await db.commit()
            return backend_pid, touched

    try:
        outcomes = await asyncio.wait_for(
            asyncio.gather(resolve_then_touch(), resolve_then_touch()),
            timeout=15,
        )
    finally:
        await concurrent_engine.dispose()

    backend_pids = {backend_pid for backend_pid, _row in outcomes}
    assert len(backend_pids) == 2
    assert all(touched is True for _backend_pid, touched in outcomes)

    async with harness.owner_session() as db:
        family_state = (
            await db.execute(
                text(
                    """
                    SELECT
                        count(*) AS total_count,
                        count(*) FILTER (
                            WHERE revoked_at IS NULL
                        ) AS active_count,
                        array_agg(id ORDER BY id) AS session_ids
                    FROM app_sessions
                    WHERE session_family_id = :session_family_id
                    """
                ),
                {
                    "session_family_id": (
                        seeded_staff_context.session_family_id
                    )
                },
            )
        ).mappings().one()
        assert family_state["total_count"] == 1
        assert family_state["active_count"] == 1
        assert family_state["session_ids"] == [
            seeded_staff_context.app_session_id
        ]


@pytest.mark.asyncio
async def test_foundation_function_acls_search_paths_and_table_denials_are_exact(
    rls_postgres_harness: RlsPostgresHarness,
) -> None:
    harness = rls_postgres_harness
    async with harness.owner_session() as db:
        functions = (
            await db.execute(
                text(
                    """
                    SELECT
                        format(
                            '%I.%I(%s)',
                            n.nspname,
                            p.proname,
                            pg_catalog.replace(
                                pg_catalog.oidvectortypes(p.proargtypes),
                                ', ',
                                ','
                            )
                        ) AS signature,
                        n.nspname AS schema_name,
                        p.prosecdef AS security_definer,
                        p.proconfig AS configuration,
                        p.proowner = n.nspowner AS owned_by_schema_owner,
                        owner_role.rolname AS owner_role,
                        has_function_privilege(
                            :runtime_role, p.oid, 'EXECUTE'
                        ) AS runtime_execute,
                        has_function_privilege(
                            :auth_role, p.oid, 'EXECUTE'
                        ) AS auth_execute,
                        COALESCE(
                            has_function_privilege(
                                pg_catalog.to_regrole('anon'),
                                p.oid,
                                'EXECUTE'
                            ),
                            false
                        ) AS anon_execute,
                        COALESCE(
                            has_function_privilege(
                                pg_catalog.to_regrole('authenticated'),
                                p.oid,
                                'EXECUTE'
                            ),
                            false
                        ) AS authenticated_execute,
                        COALESCE(
                            has_function_privilege(
                                pg_catalog.to_regrole('service_role'),
                                p.oid,
                                'EXECUTE'
                            ),
                            false
                        ) AS service_role_execute,
                        NOT EXISTS (
                            SELECT 1
                            FROM aclexplode(
                                coalesce(
                                    p.proacl,
                                    acldefault('f', p.proowner)
                                )
                            ) AS acl
                            WHERE acl.grantee = 0
                              AND acl.privilege_type = 'EXECUTE'
                        ) AS public_denied
                    FROM pg_proc AS p
                    JOIN pg_namespace AS n ON n.oid = p.pronamespace
                    JOIN pg_roles AS owner_role
                      ON owner_role.oid = p.proowner
                    WHERE n.nspname IN ('mata_rls', 'mata_private')
                    ORDER BY signature
                    """
                ),
                {
                    "runtime_role": harness.runtime_role,
                    "auth_role": harness.auth_role,
                },
            )
        ).mappings().all()
        by_signature = {str(row["signature"]): row for row in functions}
        mata_rls_signatures = {
            str(row["signature"])
            for row in functions
            if row["schema_name"] == "mata_rls"
        }
        mata_private_signatures = {
            str(row["signature"])
            for row in functions
            if row["schema_name"] == "mata_private"
        }
        expected_public_helpers = (
            RUNTIME_ONLY_FUNCTIONS
            | AUTH_ONLY_FUNCTIONS
            | BOTH_GROUP_FUNCTIONS
        )
        if harness.revision in POLICY_CUTOVER_REVISIONS:
            expected_public_helpers |= POLICY_HELPER_FUNCTIONS
        if harness.revision in SESSION_LIFECYCLE_REVISIONS:
            expected_public_helpers |= RETIRED_SESSION_FUNCTIONS
        assert mata_rls_signatures == expected_public_helpers
        assert mata_private_signatures == PRIVATE_FUNCTIONS
        assert all(row["public_denied"] is True for row in functions)
        assert all(row["anon_execute"] is False for row in functions)
        assert all(row["authenticated_execute"] is False for row in functions)
        assert all(row["service_role_execute"] is False for row in functions)

        for signature in RUNTIME_ONLY_FUNCTIONS:
            row = by_signature[signature]
            assert row["runtime_execute"] is True
            assert row["auth_execute"] is False

        for signature in AUTH_ONLY_FUNCTIONS:
            row = by_signature[signature]
            assert row["runtime_execute"] is False
            assert row["auth_execute"] is True

        for signature in BOTH_GROUP_FUNCTIONS:
            row = by_signature[signature]
            assert row["runtime_execute"] is True
            assert row["auth_execute"] is True

        if harness.revision in POLICY_CUTOVER_REVISIONS:
            for signature in POLICY_HELPER_FUNCTIONS:
                row = by_signature[signature]
                assert row["runtime_execute"] is True
                assert row["auth_execute"] is False

        if harness.revision in SESSION_LIFECYCLE_REVISIONS:
            for signature in RETIRED_SESSION_FUNCTIONS:
                row = by_signature[signature]
                assert row["runtime_execute"] is False
                assert row["auth_execute"] is False

        for row in functions:
            if row["schema_name"] == "mata_private":
                assert row["runtime_execute"] is False
                assert row["auth_execute"] is False
            assert row["security_definer"] is True
            if row["signature"] == (
                "mata_rls.create_adhoc_attendance("
                "text,text,text,text,text,date,time without time zone,"
                "time without time zone,numeric,uuid)"
            ):
                assert row["owned_by_schema_owner"] is False
                assert row["owner_role"] == (
                    "mata_adhoc_attendance_definer"
                )
            else:
                assert row["owned_by_schema_owner"] is True
            configuration = [
                str(value) for value in (row["configuration"] or [])
            ]
            assert configuration == ["search_path=pg_catalog, pg_temp"]

        schema_acl = (
            await db.execute(
                text(
                    """
                    SELECT
                        has_schema_privilege(
                            :runtime_role, 'mata_rls', 'USAGE'
                        ) AS runtime_public_helper,
                        has_schema_privilege(
                            :runtime_role, 'mata_private', 'USAGE'
                        ) AS runtime_private,
                        has_schema_privilege(
                            :auth_role, 'mata_rls', 'USAGE'
                        ) AS auth_public_helper,
                        has_schema_privilege(
                            :auth_role, 'mata_private', 'USAGE'
                        ) AS auth_private,
                        NOT EXISTS (
                            SELECT 1
                            FROM pg_namespace AS helper_namespace
                            CROSS JOIN LATERAL aclexplode(
                                coalesce(
                                    helper_namespace.nspacl,
                                    acldefault(
                                        'n',
                                        helper_namespace.nspowner
                                    )
                                )
                            ) AS acl
                            WHERE helper_namespace.nspname IN (
                                'mata_rls',
                                'mata_private'
                            )
                              AND acl.grantee = 0
                              AND acl.privilege_type = 'USAGE'
                        ) AS public_helpers_denied
                    """
                ),
                {
                    "runtime_role": harness.runtime_role,
                    "auth_role": harness.auth_role,
                },
            )
        ).mappings().one()
        assert dict(schema_acl) == {
            "runtime_public_helper": True,
            "runtime_private": False,
            "auth_public_helper": True,
            "auth_private": False,
            "public_helpers_denied": True,
        }

        direct_privileges = (
            await db.execute(
                text(
                    """
                    SELECT role_name, table_name, privilege,
                           has_table_privilege(
                               role_name,
                               format('public.%I', table_name),
                               privilege
                           ) AS allowed
                    FROM unnest(CAST(:roles AS text[])) AS role_name
                    CROSS JOIN unnest(CAST(:tables AS text[])) AS table_name
                    CROSS JOIN unnest(CAST(:privileges AS text[])) AS privilege
                    ORDER BY role_name, table_name, privilege
                    """
                ),
                {
                    "roles": [
                        RUNTIME_GROUP,
                        AUTH_GROUP,
                        harness.runtime_role,
                        harness.auth_role,
                    ],
                    "tables": [
                        "app_sessions",
                        "rate_limit_buckets",
                        "programme_institution_posting_map",
                        "surplus_ledger",
                        "period_snapshots",
                        "clawback_records",
                    ],
                    "privileges": ["SELECT", "INSERT", "UPDATE", "DELETE"],
                },
            )
        ).mappings().all()
        assert direct_privileges
        assert all(row["allowed"] is False for row in direct_privileges)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "isolation_level",
    ["REPEATABLE READ", "SERIALIZABLE"],
)
async def test_global_mcr_writes_fail_closed_above_read_committed(
    rls_postgres_harness: RlsPostgresHarness,
    isolation_level: str,
) -> None:
    mcr = f"RLSISO{uuid4().hex[:10].upper()}"
    subject_id = uuid4()
    isolation_sql = {
        "REPEATABLE READ": (
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        ),
        "SERIALIZABLE": "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
    }[isolation_level]

    async with rls_postgres_harness.owner_session() as db:
        await db.execute(text(isolation_sql))
        with pytest.raises(DBAPIError) as caught:
            await db.execute(
                text(
                    """
                    INSERT INTO residents (id, name, mcr, status)
                    VALUES (
                        :subject_id,
                        'Isolation-rejected native RLS resident',
                        :mcr,
                        'active'
                    )
                    """
                ),
                {"subject_id": subject_id, "mcr": mcr},
            )
        assert _sqlstate(caught.value) == "0A000"
        await db.rollback()

    async with rls_postgres_harness.owner_session() as db:
        identity_count = await db.scalar(
            text(
                """
                SELECT (
                    SELECT count(*)
                    FROM residents
                    WHERE id = :subject_id OR upper(btrim(mcr)) = :mcr
                ) + (
                    SELECT count(*)
                    FROM external_residents
                    WHERE id = :subject_id OR upper(btrim(mcr)) = :mcr
                )
                """
            ),
            {"subject_id": subject_id, "mcr": mcr},
        )
        assert identity_count == 0


async def _insert_concurrent_mcr(
    harness: RlsPostgresHarness,
    *,
    subject_kind: str,
    subject_id: UUID,
    mcr: str,
    posting_code: str,
    barrier: asyncio.Barrier,
) -> Exception | None:
    try:
        await barrier.wait()
        async with harness.owner_session() as db:
            async with db.begin():
                if subject_kind == "resident":
                    await db.execute(
                        text(
                            """
                            INSERT INTO residents (id, name, mcr, status)
                            VALUES (
                                :subject_id,
                                'Concurrent native RLS resident',
                                :mcr,
                                'active'
                            )
                            """
                        ),
                        {"subject_id": subject_id, "mcr": mcr},
                    )
                elif subject_kind == "external_resident":
                    await db.execute(
                        text(
                            """
                            INSERT INTO external_residents (
                                id,
                                name,
                                mcr,
                                home_cluster,
                                current_nhg_posting_code,
                                status
                            )
                            VALUES (
                                :subject_id,
                                'Concurrent external RLS resident',
                                :mcr,
                                'NUH',
                                :posting_code,
                                'active'
                            )
                            """
                        ),
                        {
                            "subject_id": subject_id,
                            "mcr": mcr,
                            "posting_code": posting_code,
                        },
                    )
    except Exception as error:
        return error
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_kind", "second_kind"),
    [
        ("resident", "external_resident"),
        ("external_resident", "external_resident"),
    ],
)
async def test_global_mcr_trigger_serializes_concurrent_inserts(
    rls_postgres_harness: RlsPostgresHarness,
    first_kind: str,
    second_kind: str,
) -> None:
    harness = rls_postgres_harness
    posting_code = f"RlsMcr{uuid4().hex[:12]}"
    created_mcrs: list[str] = []
    async with harness.owner_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO posting_codes (id, code, display_name)
                VALUES (:id, :code, 'RLS MCR concurrency posting')
                """
            ),
            {"id": uuid4(), "code": posting_code},
        )
        await db.commit()

    try:
        for iteration in range(4):
            canonical_mcr = f"RLS{uuid4().hex[:10].upper()}"
            created_mcrs.append(canonical_mcr)
            variants = (
                canonical_mcr.lower(),
                f"  {canonical_mcr}  ",
            )
            if iteration % 2:
                variants = tuple(reversed(variants))
            barrier = asyncio.Barrier(2)
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    _insert_concurrent_mcr(
                        harness,
                        subject_kind=first_kind,
                        subject_id=uuid4(),
                        mcr=variants[0],
                        posting_code=posting_code,
                        barrier=barrier,
                    ),
                    _insert_concurrent_mcr(
                        harness,
                        subject_kind=second_kind,
                        subject_id=uuid4(),
                        mcr=variants[1],
                        posting_code=posting_code,
                        barrier=barrier,
                    ),
                ),
                timeout=15,
            )
            assert sum(outcome is None for outcome in outcomes) == 1
            failures = [
                outcome for outcome in outcomes if outcome is not None
            ]
            assert len(failures) == 1
            loser = failures[0]
            assert isinstance(loser, IntegrityError)
            assert _sqlstate(loser) == "23505"
            assert "mcr" in str(loser).casefold()

            async with harness.owner_session() as db:
                counts = (
                    await db.execute(
                        text(
                            """
                            SELECT
                                (
                                    SELECT count(*)
                                    FROM residents
                                    WHERE upper(btrim(mcr)) = :mcr
                                ) AS native_count,
                                (
                                    SELECT count(*)
                                    FROM external_residents
                                    WHERE upper(btrim(mcr)) = :mcr
                                ) AS external_count
                            """
                        ),
                        {"mcr": canonical_mcr},
                    )
                ).one()
                assert sum(int(value) for value in counts) == 1
    finally:
        async with harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM external_residents
                    WHERE upper(btrim(mcr)) =
                          ANY(CAST(:mcrs AS text[]))
                    """
                ),
                {"mcrs": created_mcrs},
            )
            await db.execute(
                text(
                    """
                    DELETE FROM residents
                    WHERE upper(btrim(mcr)) =
                          ANY(CAST(:mcrs AS text[]))
                    """
                ),
                {"mcrs": created_mcrs},
            )
            await db.execute(
                text("DELETE FROM posting_codes WHERE code = :posting_code"),
                {"posting_code": posting_code},
            )
            await db.commit()
