from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session, SessionTransaction


RLS_ENABLED_INFO_KEY = "mata_rls_enabled"
AUTH_BOUNDARY_INFO_KEY = "mata_auth_boundary"
RLS_SEED_INFO_KEY = "mata_rls_seed"
RLS_CONTEXT_INFO_KEY = "mata_rls_context"

RlsLockMode = Literal["shared", "exclusive"]
RlsSubjectType = Literal["staff", "resident", "external_resident"]

_AUTHORIZATION_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")

_RUNTIME_ONLY_HELPERS = frozenset(
    {
        "uuid_advisory_key(uuid)",
        "install_request_context(bytea,text,text,uuid,uuid,text)",
        "context_is_valid()",
        "current_subject_type()",
        "current_subject_id()",
        "current_app_role()",
        "current_admin_level()",
        "current_programme_scope()",
        "current_posting_code()",
        "current_app_session_id()",
        "current_authorization_fingerprint()",
        "is_authenticated()",
        "is_master_admin()",
        "has_programme_scope(text)",
        "is_secretary_for_posting(text)",
        "is_native_resident(uuid)",
        "is_external_resident(uuid)",
        (
            "rotate_app_session_lifecycle("
            "bytea,uuid,uuid,bytea,bytea,integer,bytea)"
        ),
        "revoke_app_session_family(bytea,uuid,text)",
        "invalidate_subject_app_sessions(text,uuid,text,boolean)",
        "replace_external_resident_schedule(uuid,jsonb)",
        "set_external_resident_current_posting(uuid,text,text)",
        "resolve_ttf_session_type(text,numeric,text,text)",
        "ensure_ttf_posting_code(text,text)",
        "append_audit_log(text,text,text,jsonb,jsonb,jsonb)",
        (
            "create_adhoc_attendance("
            "text,text,text,text,text,date,time without time zone,"
            "time without time zone,numeric,uuid)"
        ),
        "update_own_staff_actor_name(text)",
        "reporting_period_dependency_counts(uuid)",
        "hibernate_stale_surplus(uuid)",
    }
)
_AUTH_ONLY_HELPERS = frozenset(
    {
        "staff_login_snapshot(text)",
        "staff_login_candidate(text)",
        "staff_login_identity(uuid,uuid,bigint)",
        "resident_login_candidate(text)",
        (
            "issue_staff_app_session_lifecycle("
            "uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        (
            "issue_resident_app_session_lifecycle("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        (
            "issue_external_resident_app_session_lifecycle("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ),
        "revoke_app_session_family_for_logout(bytea,bytea,text)",
        "external_registration_options()",
        "register_external_resident(text,text,text,jsonb)",
    }
)
_SHARED_HELPERS = frozenset(
    {
        "resolve_app_session_lifecycle(bytea,integer)",
        "touch_app_session_lifecycle(bytea,uuid,integer,integer)",
        "validate_app_session_csrf(bytea,uuid,bytea)",
        "revoke_app_session(bytea,uuid,text)",
        "cleanup_app_sessions(integer,integer)",
        "consume_rate_limit(text,text,integer,integer,integer,integer)",
    }
)
_POLICY_HELPERS = frozenset(
    {
        "can_access_resident(uuid)",
        "can_manage_resident(uuid)",
        "can_access_form_f1(text)",
        "native_assignment_matches(text,text,uuid)",
        "can_access_teaching_catalogue(text,text,uuid)",
        "can_select_teaching_event(uuid)",
        "can_insert_teaching_event(text,text,text,date,boolean,text)",
        "can_manage_teaching_event(text,text,text,date,boolean,text)",
        "can_submit_native_attendance(uuid,uuid)",
        "can_access_external_attendance(uuid,uuid)",
        "can_submit_external_attendance(uuid,uuid)",
    }
)
_EXPECTED_HELPERS_BY_CAPABILITY = {
    "mata_app_runtime": _RUNTIME_ONLY_HELPERS | _SHARED_HELPERS | _POLICY_HELPERS,
    "mata_auth_internal": _AUTH_ONLY_HELPERS | _SHARED_HELPERS,
}
_RUNTIME_TABLE_PRIVILEGES = {
    "academic_month_boundaries": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "attendance_records": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "audit_logs": {"SELECT"},
    "event_series": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "external_attendance_records": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "external_resident_postings": {"SELECT"},
    "external_residents": {"SELECT"},
    "form_f1_records": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "global_session_types": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "loa_types": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "multi_posting_rules": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "posting_codes": {"SELECT"},
    "posting_groups": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "programmes": {"SELECT", "UPDATE"},
    "public_holidays": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "reporting_periods": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "resident_postings": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "residents": {"SELECT", "INSERT", "UPDATE"},
    "secretary_programme_pools": {"SELECT"},
    "session_types": {"SELECT"},
    "teaching_events": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "teaching_name_mappings": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "teaching_names": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "teaching_name_catalogue": {"SELECT", "INSERT", "DELETE"},
    "teaching_targets": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "upload_logs": {"SELECT", "INSERT"},
    "upload_warnings": {"SELECT", "INSERT"},
    "warning_issues": {"SELECT", "INSERT", "UPDATE"},
    "weekend_exceptions": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "users": {"INSERT", "UPDATE"},
}
_USERS_SELECT_COLUMNS = {
    "email",
    "role",
    "name",
    "posting_code",
    "programme_scope",
    "is_active",
    "id",
    "created_at",
    "updated_at",
    "admin_level",
    "supabase_user_id",
    "current_staff_actor_name",
    "staff_actor_name_updated_at",
    "staff_actor_name_updated_by_user_id",
    "session_generation",
    "session_issuance_blocked",
}
_COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
_APPLICATION_TABLES = frozenset(
    {
        "academic_month_boundaries",
        "app_sessions",
        "attendance_records",
        "audit_logs",
        "clawback_records",
        "event_series",
        "external_attendance_records",
        "external_resident_postings",
        "external_residents",
        "form_f1_records",
        "global_session_types",
        "loa_types",
        "multi_posting_rules",
        "period_snapshots",
        "posting_codes",
        "posting_groups",
        "programme_institution_posting_map",
        "programmes",
        "public_holidays",
        "rate_limit_buckets",
        "reporting_periods",
        "resident_postings",
        "residents",
        "secretary_programme_pools",
        "session_types",
        "surplus_ledger",
        "teaching_events",
        "teaching_name_mappings",
        "teaching_names",
        "teaching_name_catalogue",
        "teaching_targets",
        "upload_logs",
        "upload_warnings",
        "users",
        "warning_issues",
        "weekend_exceptions",
    }
)
_RUNTIME_POLICY_ACTIONS = {
    f"{table_name}:{privilege}"
    for table_name, privileges in _RUNTIME_TABLE_PRIVILEGES.items()
    for privilege in privileges
} | {"users:SELECT"}
_RUNTIME_POLICY_CATALOGUE = {
    (
        f"{table_name}:mata_rls_{table_name}_{action.casefold()}:"
        f"{action}"
    )
    for table_name, action in (
        policy_action.split(":", maxsplit=1)
        for policy_action in _RUNTIME_POLICY_ACTIONS
    )
}


class RlsContextError(RuntimeError):
    """Base class for controlled request-context failures."""


class RlsContextInvalidError(RlsContextError):
    """The application session cannot authorize the current transaction."""


class RlsContextUsageError(RlsContextError):
    """The application attempted to seed a transaction context unsafely."""


class RlsRuntimeRoleError(RlsContextError):
    """The configured database role cannot safely enforce MATA RLS."""


@dataclass(frozen=True, slots=True)
class RlsRequestSeed:
    token_digest: bytes
    lock_mode: RlsLockMode
    expected_subject_type: RlsSubjectType
    expected_subject_id: UUID
    expected_app_session_id: UUID
    expected_authorization_fingerprint: str


@dataclass(frozen=True, slots=True)
class DatabaseRoleAttestation:
    database_name: str
    login_role: str
    capability_group: str


class MataSyncSession(Session):
    """Synchronous session used internally by the protected AsyncSession."""


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

_ROLE_ATTESTATION_SQL = text(
    """
    SELECT
        current_database() AS database_name,
        session_user::text AS login_role,
        current_user::text AS current_role,
        current_setting('row_security') AS row_security,
        login.rolcanlogin AS login_can_login,
        login.rolinherit AS login_inherits,
        login.rolsuper AS login_superuser,
        login.rolbypassrls AS login_bypass_rls,
        login.rolcreatedb AS login_create_database,
        login.rolcreaterole AS login_create_role,
        login.rolreplication AS login_replication,
        capability.oid IS NOT NULL AS capability_exists,
        capability.rolcanlogin AS capability_can_login,
        capability.rolinherit AS capability_inherits,
        capability.rolsuper AS capability_superuser,
        capability.rolbypassrls AS capability_bypass_rls,
        capability.rolcreatedb AS capability_create_database,
        capability.rolcreaterole AS capability_create_role,
        capability.rolreplication AS capability_replication,
        COALESCE(
            pg_has_role(login.oid, capability.oid, 'MEMBER'),
            false
        ) AS has_capability,
        COALESCE(
            pg_has_role(login.oid, forbidden_capability.oid, 'MEMBER'),
            false
        ) AS has_forbidden_capability,
        -- ADMIN OPTION on the capability or an intermediary role would let
        -- this credential delegate the full application capability.
        NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members AS delegated_membership
            WHERE delegated_membership.admin_option
              AND (
                  delegated_membership.member = login.oid
                  OR pg_catalog.pg_has_role(
                      login.oid,
                      delegated_membership.member,
                      'MEMBER'
                  )
              )
              AND (
                  delegated_membership.roleid = capability.oid
                  OR pg_catalog.pg_has_role(
                      delegated_membership.roleid,
                      capability.oid,
                      'MEMBER'
                  )
              )
        ) AS capability_membership_is_not_delegable,
        NOT EXISTS (
            SELECT 1
            FROM pg_roles AS privileged
            WHERE (
                privileged.rolsuper
                OR privileged.rolbypassrls
                OR privileged.rolcreatedb
                OR privileged.rolcreaterole
                OR privileged.rolreplication
              )
              AND pg_has_role(login.oid, privileged.oid, 'MEMBER')
        ) AS has_no_privileged_membership,
        -- Grant options are not needed by either application credential. Check
        -- every role the login can assume so SET ROLE cannot expose a hidden
        -- delegation path.
        NOT EXISTS (
            SELECT 1
            FROM (
                SELECT privilege.grantee
                FROM pg_catalog.pg_namespace AS namespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    namespace.nspacl
                ) AS privilege
                WHERE namespace.nspname IN (
                    'public',
                    'mata_rls',
                    'mata_private'
                )
                  AND privilege.is_grantable
                UNION ALL
                SELECT privilege.grantee
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    procedure.proacl
                ) AS privilege
                WHERE namespace.nspname IN (
                    'public',
                    'mata_rls',
                    'mata_private'
                )
                  AND privilege.is_grantable
                UNION ALL
                SELECT privilege.grantee
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    relation.relacl
                ) AS privilege
                WHERE namespace.nspname IN (
                    'public',
                    'mata_rls',
                    'mata_private'
                )
                  AND relation.relkind IN (
                      'r',
                      'p',
                      'v',
                      'm',
                      'f',
                      'S'
                  )
                  AND privilege.is_grantable
                UNION ALL
                SELECT privilege.grantee
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    attribute.attacl
                ) AS privilege
                WHERE namespace.nspname IN (
                    'public',
                    'mata_rls',
                    'mata_private'
                )
                  AND relation.relkind IN (
                      'r',
                      'p',
                      'v',
                      'm',
                      'f'
                  )
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND privilege.is_grantable
            ) AS delegated_acl
            WHERE delegated_acl.grantee <> 0
              AND (
                  delegated_acl.grantee = login.oid
                  OR pg_catalog.pg_has_role(
                      login.oid,
                      delegated_acl.grantee,
                      'MEMBER'
                  )
              )
        ) AS has_no_delegable_acl_privileges,
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS owned_relation
            JOIN pg_namespace AS owned_namespace
              ON owned_namespace.oid = owned_relation.relnamespace
            WHERE owned_namespace.nspname IN ('public', 'mata_rls', 'mata_private')
              AND owned_relation.relkind IN ('r', 'p', 'v', 'm', 'S')
              AND owned_relation.relname <> 'alembic_version'
              AND pg_has_role(login.oid, owned_relation.relowner, 'MEMBER')
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS owned_schema
            WHERE owned_schema.nspname IN ('public', 'mata_rls', 'mata_private')
              AND pg_has_role(login.oid, owned_schema.nspowner, 'MEMBER')
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS owned_function
            JOIN pg_catalog.pg_namespace AS function_namespace
              ON function_namespace.oid = owned_function.pronamespace
            WHERE function_namespace.nspname IN (
                'public',
                'mata_rls',
                'mata_private'
            )
              AND pg_has_role(login.oid, owned_function.proowner, 'MEMBER')
        ) AS has_no_owner_membership,
        NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS optional_role
            WHERE optional_role.rolname IN (
                'anon',
                'authenticated',
                'service_role'
            )
              AND (
                  pg_catalog.pg_has_role(
                      optional_role.oid,
                      capability.oid,
                      'MEMBER'
                  )
                  OR pg_catalog.pg_has_role(
                      optional_role.oid,
                      forbidden_capability.oid,
                      'MEMBER'
                  )
                  OR has_schema_privilege(
                      optional_role.oid,
                      'mata_rls',
                      'USAGE'
                  )
                  OR has_schema_privilege(
                      optional_role.oid,
                      'mata_private',
                      'USAGE'
                  )
                  OR has_schema_privilege(
                      optional_role.oid,
                      'public',
                      'CREATE'
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM pg_catalog.pg_proc AS browser_function
                      JOIN pg_catalog.pg_namespace AS browser_function_namespace
                        ON browser_function_namespace.oid
                           = browser_function.pronamespace
                      WHERE browser_function_namespace.nspname IN (
                          'mata_rls',
                          'mata_private'
                      )
                        AND has_function_privilege(
                            optional_role.oid,
                            browser_function.oid,
                            'EXECUTE'
                        )
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM pg_catalog.pg_class AS browser_relation
                      JOIN pg_catalog.pg_namespace AS browser_relation_namespace
                        ON browser_relation_namespace.oid
                           = browser_relation.relnamespace
                      WHERE browser_relation_namespace.nspname = 'public'
                        AND browser_relation.relkind IN (
                            'r',
                            'p',
                            'v',
                            'm',
                            'f',
                            'S'
                        )
                        AND (
                            (
                                browser_relation.relkind <> 'S'
                                AND (
                                    has_table_privilege(
                                        optional_role.oid,
                                        browser_relation.oid,
                                        'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                                    )
                                    OR has_any_column_privilege(
                                        optional_role.oid,
                                        browser_relation.oid,
                                        'SELECT,INSERT,UPDATE,REFERENCES'
                                    )
                                )
                            )
                            OR (
                                browser_relation.relkind = 'S'
                                AND has_sequence_privilege(
                                    optional_role.oid,
                                    browser_relation.oid,
                                    'USAGE,SELECT,UPDATE'
                                )
                            )
                        )
                  )
              )
        ) AS browser_roles_are_denied,
        NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS public_schema
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    public_schema.nspacl,
                    pg_catalog.acldefault(
                        'n',
                        public_schema.nspowner
                    )
                )
            ) AS privilege
            WHERE public_schema.nspname = 'public'
              AND privilege.grantee = 0
              AND privilege.privilege_type = 'CREATE'
        ) AS public_schema_create_is_denied,
        to_regprocedure(
            'mata_rls.install_request_context(bytea,text,text,uuid,uuid,text)'
        ) IS NOT NULL AS installer_exists,
        COALESCE(
            has_function_privilege(
                login.oid,
                to_regprocedure(
                    'mata_rls.install_request_context(bytea,text,text,uuid,uuid,text)'
                ),
                'EXECUTE'
            ),
            false
        ) AS can_install_context,
        has_schema_privilege(login.oid, 'mata_rls', 'USAGE')
            AS can_use_rls_schema,
        has_schema_privilege(login.oid, 'mata_rls', 'CREATE')
            AS can_create_in_rls_schema,
        has_schema_privilege(login.oid, 'mata_private', 'USAGE')
            AS can_use_private_schema,
        has_schema_privilege(login.oid, 'mata_private', 'CREATE')
            AS can_create_in_private_schema,
        has_schema_privilege(login.oid, 'public', 'CREATE')
            AS can_create_in_public_schema,
        COALESCE(
            has_function_privilege(
                login.oid,
                to_regprocedure('public.gen_random_uuid()'),
                'EXECUTE'
            ),
            false
        ) AS can_generate_uuid,
        COALESCE(
            (
                SELECT array_agg(
                    format(
                        '%s(%s)',
                        procedure.proname,
                        replace(
                            pg_catalog.oidvectortypes(procedure.proargtypes),
                            ', ',
                            ','
                        )
                    )
                    ORDER BY procedure.proname, procedure.proargtypes::text
                )
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'mata_rls'
                  AND has_function_privilege(
                      login.oid,
                      procedure.oid,
                      'EXECUTE'
                  )
            ),
            ARRAY[]::text[]
        ) AS executable_rls_helpers,
        NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            JOIN pg_catalog.pg_roles AS owner_role
              ON owner_role.oid = procedure.proowner
            WHERE namespace.nspname = 'mata_rls'
              AND has_function_privilege(
                  login.oid,
                  procedure.oid,
                  'EXECUTE'
              )
              AND (
                  NOT procedure.prosecdef
                  OR procedure.proconfig IS DISTINCT FROM
                      ARRAY['search_path=pg_catalog, pg_temp']::text[]
                  OR (
                      procedure.proowner <> namespace.nspowner
                      AND NOT (
                          procedure.oid = pg_catalog.to_regprocedure(
                              'mata_rls.create_adhoc_attendance('
                              'text,text,text,text,text,date,'
                              'time without time zone,'
                              'time without time zone,numeric,uuid)'
                          )
                          AND owner_role.rolname
                              = 'mata_adhoc_attendance_definer'
                          AND NOT owner_role.rolcanlogin
                          AND NOT owner_role.rolinherit
                          AND NOT owner_role.rolsuper
                          AND owner_role.rolbypassrls
                          AND NOT owner_role.rolcreatedb
                          AND NOT owner_role.rolcreaterole
                          AND NOT owner_role.rolreplication
                          AND NOT EXISTS (
                              SELECT 1
                              FROM pg_catalog.pg_auth_members
                                  AS owner_membership
                              WHERE owner_membership.member
                                  = owner_role.oid
                          )
                          AND (
                              SELECT
                                  count(*) = 0
                                  OR (
                                      count(*) = 1
                                      AND count(*) FILTER (
                                          WHERE member_role.oid
                                              = namespace.nspowner
                                            AND member_role.rolcreaterole
                                            AND member_role.rolbypassrls
                                            AND grantor_role.rolsuper
                                            AND owner_membership.admin_option
                                            AND NOT owner_membership.inherit_option
                                            AND NOT owner_membership.set_option
                                      ) = 1
                                  )
                              FROM pg_catalog.pg_auth_members
                                  AS owner_membership
                              LEFT JOIN pg_catalog.pg_roles AS member_role
                                ON member_role.oid = owner_membership.member
                              LEFT JOIN pg_catalog.pg_roles AS grantor_role
                                ON grantor_role.oid = owner_membership.grantor
                              WHERE owner_membership.roleid = owner_role.oid
                          )
                      )
                  )
              )
        ) AS executable_rls_helpers_are_hardened,
        COALESCE(
            (
                SELECT array_agg(
                    procedure.oid::regprocedure::text
                    ORDER BY procedure.proname, procedure.proargtypes::text
                )
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'mata_private'
                  AND has_function_privilege(
                      login.oid,
                      procedure.oid,
                      'EXECUTE'
                  )
            ),
            ARRAY[]::text[]
        ) AS executable_private_helpers,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname || ':' || privilege.action
                    ORDER BY relation.relname, privilege.action
                )
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN (
                    VALUES
                        ('SELECT'),
                        ('INSERT'),
                        ('UPDATE'),
                        ('DELETE'),
                        ('TRUNCATE'),
                        ('REFERENCES'),
                        ('TRIGGER')
                ) AS privilege(action)
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND has_table_privilege(
                      login.oid,
                      relation.oid,
                      privilege.action
                  )
            ),
            ARRAY[]::text[]
        ) AS executable_table_privileges,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname || '.' || attribute.attname
                    ORDER BY relation.relname, attribute.attnum
                )
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_attribute AS attribute
                  ON attribute.attrelid = relation.oid
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            ),
            ARRAY[]::text[]
        ) AS public_columns,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname || '.' || attribute.attname
                        || ':' || privilege.action
                    ORDER BY
                        relation.relname,
                        attribute.attnum,
                        privilege.action
                )
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_attribute AS attribute
                  ON attribute.attrelid = relation.oid
                CROSS JOIN (
                    VALUES
                        ('SELECT'),
                        ('INSERT'),
                        ('UPDATE'),
                        ('REFERENCES')
                ) AS privilege(action)
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND has_column_privilege(
                      login.oid,
                      relation.oid,
                      attribute.attnum,
                      privilege.action
                  )
            ),
            ARRAY[]::text[]
        ) AS executable_column_privileges,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname || ':' || privilege.action
                    ORDER BY relation.relname, privilege.action
                )
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN (
                    VALUES ('USAGE'), ('SELECT'), ('UPDATE')
                ) AS privilege(action)
                WHERE namespace.nspname = 'public'
                  AND relation.relkind = 'S'
                  AND has_sequence_privilege(
                      login.oid,
                      relation.oid,
                      privilege.action
                  )
            ),
            ARRAY[]::text[]
        ) AS executable_sequence_privileges,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname
                    ORDER BY relation.relname
                )
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = ANY(
                      ARRAY[
                          'academic_month_boundaries',
                          'app_sessions',
                          'attendance_records',
                          'audit_logs',
                          'clawback_records',
                          'event_series',
                          'external_attendance_records',
                          'external_resident_postings',
                          'external_residents',
                          'form_f1_records',
                          'global_session_types',
                          'loa_types',
                          'multi_posting_rules',
                          'period_snapshots',
                          'posting_codes',
                          'posting_groups',
                          'programme_institution_posting_map',
                          'programmes',
                          'public_holidays',
                          'rate_limit_buckets',
                          'reporting_periods',
                          'resident_postings',
                          'residents',
                          'secretary_programme_pools',
                          'session_types',
                          'surplus_ledger',
                          'teaching_events',
                          'teaching_name_mappings',
                          'teaching_names',
                          'teaching_name_catalogue',
                          'teaching_targets',
                          'upload_logs',
                          'upload_warnings',
                          'users',
                          'warning_issues',
                          'weekend_exceptions'
                      ]::text[]
                  )
                  AND relation.relkind IN ('r', 'p')
                  AND relation.relrowsecurity
            ),
            ARRAY[]::text[]
        ) AS rls_application_tables,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname
                    ORDER BY relation.relname
                )
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = ANY(
                      ARRAY[
                          'academic_month_boundaries',
                          'app_sessions',
                          'attendance_records',
                          'audit_logs',
                          'clawback_records',
                          'event_series',
                          'external_attendance_records',
                          'external_resident_postings',
                          'external_residents',
                          'form_f1_records',
                          'global_session_types',
                          'loa_types',
                          'multi_posting_rules',
                          'period_snapshots',
                          'posting_codes',
                          'posting_groups',
                          'programme_institution_posting_map',
                          'programmes',
                          'public_holidays',
                          'rate_limit_buckets',
                          'reporting_periods',
                          'resident_postings',
                          'residents',
                          'secretary_programme_pools',
                          'session_types',
                          'surplus_ledger',
                          'teaching_events',
                          'teaching_name_mappings',
                          'teaching_names',
                          'teaching_name_catalogue',
                          'teaching_targets',
                          'upload_logs',
                          'upload_warnings',
                          'users',
                          'warning_issues',
                          'weekend_exceptions'
                      ]::text[]
                  )
                  AND relation.relkind IN ('r', 'p')
                  AND relation.relforcerowsecurity
            ),
            ARRAY[]::text[]
        ) AS forced_rls_application_tables,
        COALESCE(
            (
                SELECT array_agg(
                    relation.relname || ':' || policy.polname || ':' ||
                    CASE policy.polcmd
                        WHEN 'r' THEN 'SELECT'
                        WHEN 'a' THEN 'INSERT'
                        WHEN 'w' THEN 'UPDATE'
                        WHEN 'd' THEN 'DELETE'
                        ELSE policy.polcmd::text
                    END
                    ORDER BY relation.relname, policy.polcmd
                )
                FROM pg_catalog.pg_policy AS policy
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = policy.polrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = ANY(
                      ARRAY[
                          'academic_month_boundaries',
                          'app_sessions',
                          'attendance_records',
                          'audit_logs',
                          'clawback_records',
                          'event_series',
                          'external_attendance_records',
                          'external_resident_postings',
                          'external_residents',
                          'form_f1_records',
                          'global_session_types',
                          'loa_types',
                          'multi_posting_rules',
                          'period_snapshots',
                          'posting_codes',
                          'posting_groups',
                          'programme_institution_posting_map',
                          'programmes',
                          'public_holidays',
                          'rate_limit_buckets',
                          'reporting_periods',
                          'resident_postings',
                          'residents',
                          'secretary_programme_pools',
                          'session_types',
                          'surplus_ledger',
                          'teaching_events',
                          'teaching_name_mappings',
                          'teaching_names',
                          'teaching_name_catalogue',
                          'teaching_targets',
                          'upload_logs',
                          'upload_warnings',
                          'users',
                          'warning_issues',
                          'weekend_exceptions'
                      ]::text[]
                  )
            ),
            ARRAY[]::text[]
        ) AS application_policy_catalogue,
        (
            SELECT pg_catalog.count(*)
            FROM pg_catalog.pg_policy AS policy
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = policy.polrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = ANY(
                  ARRAY[
                      'academic_month_boundaries',
                      'app_sessions',
                      'attendance_records',
                      'audit_logs',
                      'clawback_records',
                      'event_series',
                      'external_attendance_records',
                      'external_resident_postings',
                      'external_residents',
                      'form_f1_records',
                      'global_session_types',
                      'loa_types',
                      'multi_posting_rules',
                      'period_snapshots',
                      'posting_codes',
                      'posting_groups',
                      'programme_institution_posting_map',
                      'programmes',
                      'public_holidays',
                      'rate_limit_buckets',
                      'reporting_periods',
                      'resident_postings',
                      'residents',
                      'secretary_programme_pools',
                      'session_types',
                      'surplus_ledger',
                      'teaching_events',
                      'teaching_name_mappings',
                      'teaching_names',
                      'teaching_name_catalogue',
                      'teaching_targets',
                      'upload_logs',
                      'upload_warnings',
                      'users',
                      'warning_issues',
                      'weekend_exceptions'
                  ]::text[]
              )
              AND (
                   NOT policy.polpermissive
                   OR policy.polroles <> ARRAY[
                      (
                          SELECT role.oid
                          FROM pg_catalog.pg_roles AS role
                           WHERE role.rolname = 'mata_app_runtime'
                       )
                   ]::oid[]
                   OR (
                       policy.polcmd = 'r'
                       AND (
                           policy.polqual IS NULL
                           OR policy.polwithcheck IS NOT NULL
                       )
                   )
                   OR (
                       policy.polcmd = 'a'
                       AND (
                           policy.polqual IS NOT NULL
                           OR policy.polwithcheck IS NULL
                       )
                   )
                   OR (
                       policy.polcmd = 'w'
                       AND (
                           policy.polqual IS NULL
                           OR policy.polwithcheck IS NULL
                       )
                   )
                   OR (
                       policy.polcmd = 'd'
                       AND (
                           policy.polqual IS NULL
                           OR policy.polwithcheck IS NOT NULL
                       )
                   )
                   OR (
                       policy.polqual IS NOT NULL
                       AND pg_catalog.strpos(
                           pg_catalog.pg_get_expr(
                               policy.polqual,
                               policy.polrelid
                           ),
                           'mata_rls.'
                       ) = 0
                   )
                   OR (
                       policy.polwithcheck IS NOT NULL
                       AND pg_catalog.strpos(
                           pg_catalog.pg_get_expr(
                               policy.polwithcheck,
                               policy.polrelid
                           ),
                           'mata_rls.'
                       ) = 0
                   )
              )
        ) AS unsafe_application_policy_count
    FROM pg_roles AS login
    LEFT JOIN pg_roles AS capability
      ON capability.rolname = :capability_group
    LEFT JOIN pg_roles AS forbidden_capability
      ON forbidden_capability.rolname = :forbidden_capability_group
    WHERE login.rolname = session_user
    """
)

_ADHOC_DEFINER_ACL_ATTESTATION_SQL = text(
    """
    WITH definer AS (
        SELECT role.oid
        FROM pg_catalog.pg_roles AS role
        WHERE role.rolname = 'mata_adhoc_attendance_definer'
    ),
    expected_schema(schema_name, action) AS (
        VALUES
            ('public', 'USAGE'),
            ('mata_rls', 'USAGE')
    ),
    actual_schema AS (
        SELECT namespace.nspname AS schema_name, privilege.action
        FROM definer
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.nspname IN ('public', 'mata_rls', 'mata_private')
        CROSS JOIN (
            VALUES ('USAGE'), ('CREATE')
        ) AS privilege(action)
        WHERE pg_catalog.has_schema_privilege(
            definer.oid,
            namespace.oid,
            privilege.action
        )
    ),
    expected_table(table_name, action) AS (
        VALUES
            ('attendance_records', 'SELECT'),
            ('attendance_records', 'INSERT'),
            ('external_attendance_records', 'SELECT'),
            ('external_attendance_records', 'INSERT'),
            ('external_resident_postings', 'SELECT'),
            ('external_residents', 'SELECT'),
            ('global_session_types', 'SELECT'),
            ('public_holidays', 'SELECT'),
            ('reporting_periods', 'SELECT'),
            ('resident_postings', 'SELECT'),
            ('residents', 'SELECT'),
            ('session_types', 'SELECT'),
            ('teaching_events', 'SELECT'),
            ('teaching_events', 'INSERT'),
            ('teaching_name_catalogue', 'SELECT'),
            ('teaching_targets', 'SELECT')
    ),
    actual_table AS (
        SELECT relation.relname AS table_name, privilege.action
        FROM definer
        JOIN pg_catalog.pg_class AS relation
          ON relation.relkind IN ('r', 'p', 'v', 'm', 'f')
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
         AND namespace.nspname = 'public'
        CROSS JOIN (
            VALUES
                ('SELECT'),
                ('INSERT'),
                ('UPDATE'),
                ('DELETE'),
                ('TRUNCATE'),
                ('REFERENCES'),
                ('TRIGGER')
        ) AS privilege(action)
        WHERE pg_catalog.has_table_privilege(
            definer.oid,
            relation.oid,
            privilege.action
        )
    ),
    expected_function(signature) AS (
        VALUES
            ('mata_rls.current_subject_type()'),
            ('mata_rls.current_subject_id()'),
            (
                'mata_rls.create_adhoc_attendance('
                'text,text,text,text,text,date,time without time zone,'
                'time without time zone,numeric,uuid)'
            ),
            ('public.gen_random_uuid()')
    ),
    reviewed_function AS (
        SELECT
            procedure.oid,
            procedure.proowner,
            procedure.proacl,
            pg_catalog.format(
                '%I.%I(%s)',
                namespace.nspname,
                procedure.proname,
                pg_catalog.replace(
                    pg_catalog.oidvectortypes(procedure.proargtypes),
                    ', ',
                    ','
                )
            ) AS signature
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname IN ('mata_rls', 'mata_private')
           OR procedure.oid IN (
               pg_catalog.to_regprocedure('public.digest(bytea,text)'),
               pg_catalog.to_regprocedure('public.hmac(bytea,bytea,text)'),
               pg_catalog.to_regprocedure(
                   'public.gen_random_bytes(integer)'
               ),
               pg_catalog.to_regprocedure('public.gen_random_uuid()')
           )
    ),
    actual_function AS (
        SELECT reviewed_function.signature
        FROM definer
        CROSS JOIN reviewed_function
        WHERE pg_catalog.has_function_privilege(
            definer.oid,
            reviewed_function.oid,
            'EXECUTE'
        )
    )
    SELECT
        (SELECT pg_catalog.count(*) FROM definer) = 1
        AND NOT EXISTS (
            SELECT 1
            FROM expected_schema
            WHERE NOT EXISTS (
                SELECT 1
                FROM actual_schema
                WHERE actual_schema.schema_name
                        = expected_schema.schema_name
                  AND actual_schema.action = expected_schema.action
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM actual_schema
            WHERE NOT EXISTS (
                SELECT 1
                FROM expected_schema
                WHERE expected_schema.schema_name
                        = actual_schema.schema_name
                  AND expected_schema.action = actual_schema.action
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM expected_table
            WHERE NOT EXISTS (
                SELECT 1
                FROM actual_table
                WHERE actual_table.table_name = expected_table.table_name
                  AND actual_table.action = expected_table.action
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM actual_table
            WHERE NOT EXISTS (
                SELECT 1
                FROM expected_table
                WHERE expected_table.table_name = actual_table.table_name
                  AND expected_table.action = actual_table.action
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM expected_function
            WHERE NOT EXISTS (
                SELECT 1
                FROM actual_function
                WHERE actual_function.signature = expected_function.signature
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM actual_function
            WHERE NOT EXISTS (
                SELECT 1
                FROM expected_function
                WHERE expected_function.signature = actual_function.signature
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM definer
            JOIN pg_catalog.pg_class AS relation
              ON relation.relkind = 'S'
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
             AND namespace.nspname = 'public'
            CROSS JOIN (
                VALUES ('USAGE'), ('SELECT'), ('UPDATE')
            ) AS privilege(action)
            WHERE pg_catalog.has_sequence_privilege(
                definer.oid,
                relation.oid,
                privilege.action
            )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM definer
            JOIN pg_catalog.pg_class AS relation
              ON relation.relkind IN ('r', 'p', 'v', 'm', 'f')
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
             AND namespace.nspname = 'public'
            JOIN pg_catalog.pg_attribute AS attribute
              ON attribute.attrelid = relation.oid
             AND attribute.attnum > 0
             AND NOT attribute.attisdropped
            CROSS JOIN (
                VALUES
                    ('SELECT'),
                    ('INSERT'),
                    ('UPDATE'),
                    ('REFERENCES')
            ) AS privilege(action)
            WHERE pg_catalog.has_column_privilege(
                definer.oid,
                relation.oid,
                attribute.attnum,
                privilege.action
            )
              AND NOT EXISTS (
                  SELECT 1
                  FROM expected_table
                  WHERE expected_table.table_name = relation.relname
                    AND expected_table.action = privilege.action
              )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM definer
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.nspname IN (
                  'public',
                  'mata_rls',
                  'mata_private'
              )
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    namespace.nspacl,
                    pg_catalog.acldefault('n', namespace.nspowner)
                )
            ) AS acl
            WHERE acl.grantee = definer.oid
              AND acl.is_grantable
        )
        AND NOT EXISTS (
            SELECT 1
            FROM definer
            JOIN pg_catalog.pg_class AS relation
              ON relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
             AND namespace.nspname = 'public'
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    relation.relacl,
                    pg_catalog.acldefault(
                        CAST(
                            CASE
                                WHEN relation.relkind = 'S' THEN 'S'
                                ELSE 'r'
                            END
                            AS "char"
                        ),
                        relation.relowner
                    )
                )
            ) AS acl
            WHERE acl.grantee = definer.oid
              AND acl.is_grantable
        )
        AND NOT EXISTS (
            SELECT 1
            FROM definer
            CROSS JOIN reviewed_function
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    reviewed_function.proacl,
                    pg_catalog.acldefault(
                        'f',
                        reviewed_function.proowner
                    )
                )
            ) AS acl
            WHERE reviewed_function.proowner <> definer.oid
              AND acl.grantee = definer.oid
              AND acl.is_grantable
        )
        AND NOT EXISTS (
            SELECT 1
            FROM definer
            JOIN pg_catalog.pg_attribute AS attribute
              ON attribute.attacl IS NOT NULL
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = attribute.attrelid
             AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
             AND namespace.nspname = 'public'
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                attribute.attacl
            ) AS acl
            WHERE acl.grantee IN (0, definer.oid)
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS namespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    namespace.nspacl,
                    pg_catalog.acldefault('n', namespace.nspowner)
                )
            ) AS acl
            WHERE namespace.nspname IN ('mata_rls', 'mata_private')
              AND acl.grantee = 0
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
             AND namespace.nspname = 'public'
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    relation.relacl,
                    pg_catalog.acldefault(
                        CAST(
                            CASE
                                WHEN relation.relkind = 'S' THEN 'S'
                                ELSE 'r'
                            END
                            AS "char"
                        ),
                        relation.relowner
                    )
                )
            ) AS acl
            WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
              AND acl.grantee = 0
        )
        AND NOT EXISTS (
            SELECT 1
            FROM reviewed_function
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    reviewed_function.proacl,
                    pg_catalog.acldefault(
                        'f',
                        reviewed_function.proowner
                    )
                )
            ) AS acl
            WHERE acl.grantee = 0
              AND acl.privilege_type = 'EXECUTE'
        ) AS adhoc_definer_acl_surface_is_exact
    """
)

_SESSION_HELPER_ACL_ATTESTATION_SQL = text(
    """
    WITH expected(signature, allowed_grantees) AS (
        VALUES
            (
                'issue_staff_app_session_lifecycle(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                ARRAY['mata_auth_internal']::text[]
            ),
            (
                'issue_resident_app_session_lifecycle(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                ARRAY['mata_auth_internal']::text[]
            ),
            (
                'issue_external_resident_app_session_lifecycle(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                ARRAY['mata_auth_internal']::text[]
            ),
            (
                'resolve_app_session_lifecycle(bytea,integer)',
                ARRAY['mata_app_runtime', 'mata_auth_internal']::text[]
            ),
            (
                'touch_app_session_lifecycle(bytea,uuid,integer,integer)',
                ARRAY['mata_app_runtime', 'mata_auth_internal']::text[]
            ),
            (
                'validate_app_session_csrf(bytea,uuid,bytea)',
                ARRAY['mata_app_runtime', 'mata_auth_internal']::text[]
            ),
            (
                'rotate_app_session_lifecycle(bytea,uuid,uuid,bytea,bytea,integer,bytea)',
                ARRAY['mata_app_runtime']::text[]
            ),
            (
                'revoke_app_session_family_for_logout(bytea,bytea,text)',
                ARRAY['mata_auth_internal']::text[]
            ),
            (
                'issue_staff_app_session(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                ARRAY[]::text[]
            ),
            (
                'issue_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                ARRAY[]::text[]
            ),
            (
                'issue_external_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                ARRAY[]::text[]
            ),
            (
                'resolve_app_session(bytea,boolean,integer)',
                ARRAY[]::text[]
            ),
            (
                'rotate_app_session(bytea,uuid,uuid,bytea,bytea,integer,bytea)',
                ARRAY[]::text[]
            )
    )
    SELECT NOT EXISTS (
        SELECT 1
        FROM expected
        LEFT JOIN pg_catalog.pg_proc AS procedure
          ON procedure.oid = pg_catalog.to_regprocedure(
              'mata_rls.' || expected.signature
          )
        LEFT JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE procedure.oid IS NULL
           OR NOT procedure.prosecdef
           OR procedure.proconfig IS DISTINCT FROM
              ARRAY['search_path=pg_catalog, pg_temp']::text[]
           OR procedure.proowner <> namespace.nspowner
           OR EXISTS (
                SELECT 1
                FROM pg_catalog.aclexplode(
                    COALESCE(
                        procedure.proacl,
                        pg_catalog.acldefault('f', procedure.proowner)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee_role
                  ON grantee_role.oid = acl.grantee
                WHERE acl.privilege_type = 'EXECUTE'
                  AND acl.grantee <> procedure.proowner
                  AND (
                      grantee_role.rolname IS NULL
                      OR NOT (
                          grantee_role.rolname
                          = ANY(expected.allowed_grantees)
                      )
                      OR acl.is_grantable
                  )
           )
           OR EXISTS (
                SELECT 1
                FROM pg_catalog.unnest(expected.allowed_grantees)
                    AS allowed_grantee(role_name)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.aclexplode(
                        COALESCE(
                            procedure.proacl,
                            pg_catalog.acldefault(
                                'f',
                                procedure.proowner
                            )
                        )
                    ) AS acl
                    JOIN pg_catalog.pg_roles AS grantee_role
                      ON grantee_role.oid = acl.grantee
                    WHERE grantee_role.rolname
                            = allowed_grantee.role_name
                      AND acl.privilege_type = 'EXECUTE'
                      AND NOT acl.is_grantable
                )
           )
    ) AS session_helper_acls_are_exact
    """
)


def _normalise_scope(raw_scope: object) -> list[str]:
    if raw_scope is None:
        return []
    if not isinstance(raw_scope, (list, tuple)):
        raise RlsRuntimeRoleError(
            "The database returned an invalid programme-scope context"
        )
    return sorted(
        {
            value
            for raw_value in raw_scope
            if (value := str(raw_value).strip().upper())
        }
    )


def _normalise_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _coerce_uuid(value: object, *, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RlsContextInvalidError(f"Invalid {label} binding") from exc


def _validate_fingerprint(value: object) -> str:
    fingerprint = str(value or "")
    if _AUTHORIZATION_FINGERPRINT_PATTERN.fullmatch(fingerprint) is None:
        raise RlsContextInvalidError("Invalid application authorization binding")
    return fingerprint


def _install_context(
    session: Session,
    transaction: SessionTransaction,
    connection: Connection,
) -> None:
    if transaction.parent is not None:
        return
    if not bool(session.info.get(RLS_ENABLED_INFO_KEY)):
        return

    seed = session.info.get(RLS_SEED_INFO_KEY)
    if not isinstance(seed, RlsRequestSeed):
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        raise RlsContextInvalidError(
            "Application session context was not configured"
        )

    row = connection.execute(
        _INSTALL_CONTEXT_SQL,
        {
            "token_digest": seed.token_digest,
            "lock_mode": seed.lock_mode,
            "expected_subject_type": seed.expected_subject_type,
            "expected_subject_id": seed.expected_subject_id,
            "expected_app_session_id": seed.expected_app_session_id,
            "expected_authorization_fingerprint": (
                seed.expected_authorization_fingerprint
            ),
        },
    ).mappings().one_or_none()
    if row is None:
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        raise RlsContextInvalidError("Application session is no longer valid")

    context = dict(row)
    context["programme_scope"] = _normalise_scope(
        context.get("programme_scope")
    )
    actual_fingerprint = _validate_fingerprint(
        context.get("authorization_fingerprint")
    )
    if not hmac.compare_digest(
        actual_fingerprint,
        seed.expected_authorization_fingerprint,
    ):
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        raise RlsContextInvalidError("Application authorization changed")
    if str(context.get("subject_type") or "") != seed.expected_subject_type:
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        raise RlsContextInvalidError("Application session subject changed")
    if (
        _coerce_uuid(context.get("subject_id"), label="subject")
        != seed.expected_subject_id
    ):
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        raise RlsContextInvalidError("Application session subject changed")
    if (
        _coerce_uuid(context.get("app_session_id"), label="session")
        != seed.expected_app_session_id
    ):
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        raise RlsContextInvalidError("Application session changed")

    context["authorization_fingerprint"] = actual_fingerprint
    session.info[RLS_CONTEXT_INFO_KEY] = context


def _clear_transaction_context(
    session: Session,
    transaction: SessionTransaction,
) -> None:
    if (
        transaction.parent is None
        and bool(session.info.get(RLS_ENABLED_INFO_KEY))
    ):
        session.info.pop(RLS_CONTEXT_INFO_KEY, None)
        # A post-commit ORM lookup must not reuse authority-sensitive state
        # from the identity map without starting a freshly validated root
        # transaction.
        session.expire_all()


event.listen(MataSyncSession, "after_begin", _install_context)
event.listen(
    MataSyncSession,
    "after_transaction_end",
    _clear_transaction_context,
)


def session_uses_rls(db: object) -> bool:
    info = getattr(db, "info", None)
    return bool(isinstance(info, dict) and info.get(RLS_ENABLED_INFO_KEY))


def session_uses_auth_boundary(db: object) -> bool:
    info = getattr(db, "info", None)
    return bool(isinstance(info, dict) and info.get(AUTH_BOUNDARY_INFO_KEY))


def session_uses_rls_helpers(db: object) -> bool:
    return session_uses_rls(db) or session_uses_auth_boundary(db)


def configure_request_context(
    db: AsyncSession,
    *,
    token_digest: bytes,
    expected_subject_type: RlsSubjectType,
    expected_subject_id: UUID,
    expected_app_session_id: UUID,
    expected_authorization_fingerprint: str,
    lock_mode: RlsLockMode = "shared",
) -> None:
    if db.in_transaction():
        raise RlsContextUsageError(
            "Request context must be configured before a transaction begins"
        )
    if lock_mode not in {"shared", "exclusive"}:
        raise ValueError("Invalid RLS request lock mode")
    if expected_subject_type not in {
        "staff",
        "resident",
        "external_resident",
    }:
        raise ValueError("Invalid RLS subject type")
    try:
        digest = bytes(token_digest)
    except (TypeError, ValueError) as exc:
        raise RlsContextInvalidError(
            "Invalid application-session digest"
        ) from exc
    if len(digest) != 32:
        raise ValueError("Invalid application-session digest")

    seed = RlsRequestSeed(
        token_digest=digest,
        lock_mode=lock_mode,
        expected_subject_type=expected_subject_type,
        expected_subject_id=_coerce_uuid(
            expected_subject_id,
            label="expected subject",
        ),
        expected_app_session_id=_coerce_uuid(
            expected_app_session_id,
            label="expected session",
        ),
        expected_authorization_fingerprint=_validate_fingerprint(
            expected_authorization_fingerprint
        ),
    )
    existing_seed = db.info.get(RLS_SEED_INFO_KEY)
    if existing_seed is not None and existing_seed != seed:
        raise RlsContextUsageError(
            "Request context cannot change within one database session"
        )
    if db.info.get(RLS_CONTEXT_INFO_KEY) is not None:
        raise RlsContextUsageError(
            "Request context cannot be reseeded after installation"
        )

    db.info[RLS_ENABLED_INFO_KEY] = True
    db.info[RLS_SEED_INFO_KEY] = seed


async def prime_request_context(db: AsyncSession) -> dict[str, Any]:
    if not session_uses_rls(db):
        return {}
    await db.execute(text("SELECT 1"))
    context = db.info.get(RLS_CONTEXT_INFO_KEY)
    if not isinstance(context, dict):
        raise RlsContextInvalidError("Application session context was not installed")
    return dict(context)


def clear_request_context(db: AsyncSession) -> None:
    db.info.pop(RLS_SEED_INFO_KEY, None)
    db.info.pop(RLS_CONTEXT_INFO_KEY, None)


def apply_context_to_identity(
    identity: object,
    context: dict[str, Any],
    *,
    expected_subject_type: RlsSubjectType,
    expected_subject_id: UUID,
    expected_app_session_id: UUID,
    expected_authorization_fingerprint: str,
) -> None:
    """Fail closed unless middleware identity exactly matches DB-owned context."""

    expected_subject_uuid = _coerce_uuid(
        expected_subject_id,
        label="expected subject",
    )
    expected_session_uuid = _coerce_uuid(
        expected_app_session_id,
        label="expected session",
    )
    subject_id = _coerce_uuid(context.get("subject_id"), label="subject")
    identity_subject_id = _coerce_uuid(
        getattr(identity, "subject_id", None),
        label="identity subject",
    )
    if subject_id != expected_subject_uuid or identity_subject_id != subject_id:
        raise RlsContextInvalidError("Application session subject changed")
    if str(context.get("subject_type") or "") != expected_subject_type:
        raise RlsContextInvalidError("Application session subject changed")
    if (
        _coerce_uuid(context.get("app_session_id"), label="session")
        != expected_session_uuid
    ):
        raise RlsContextInvalidError("Application session changed")

    actual_fingerprint = _validate_fingerprint(
        context.get("authorization_fingerprint")
    )
    if not hmac.compare_digest(
        actual_fingerprint,
        _validate_fingerprint(expected_authorization_fingerprint),
    ):
        raise RlsContextInvalidError("Application authorization changed")

    context_role = str(context.get("app_role") or "").strip().lower()
    identity_role = str(getattr(identity, "role", "") or "").strip().lower()
    if context_role != identity_role:
        raise RlsContextInvalidError("Application role changed")

    expected_roles = {
        "staff": {"admin", "secretary"},
        "resident": {"resident"},
        "external_resident": {"external_resident"},
    }
    if identity_role not in expected_roles[expected_subject_type]:
        raise RlsContextInvalidError("Application subject type changed")

    context_admin_level = _normalise_optional_text(context.get("admin_level"))
    identity_admin_level = _normalise_optional_text(
        getattr(identity, "admin_level", None)
    )
    if context_admin_level != identity_admin_level:
        raise RlsContextInvalidError("Application admin level changed")

    context_scope = _normalise_scope(context.get("programme_scope"))
    identity_scope_value = getattr(identity, "programme_scope", None)
    if identity_role == "admin":
        if context_scope != _normalise_scope(identity_scope_value):
            raise RlsContextInvalidError("Application programme scope changed")
    elif identity_role == "resident":
        programme_code = _normalise_optional_text(
            getattr(identity, "programme_code", None)
        )
        expected_scope = [programme_code.upper()] if programme_code else []
        if context_scope != expected_scope:
            raise RlsContextInvalidError("Application programme changed")
    elif context_scope:
        raise RlsContextInvalidError("Unexpected application programme scope")

    context_posting = _normalise_optional_text(context.get("posting_code"))
    identity_posting = _normalise_optional_text(
        getattr(identity, "posting_code", None)
    )
    if context_posting != identity_posting:
        raise RlsContextInvalidError("Application posting scope changed")


async def attest_database_role(
    engine: AsyncEngine,
    *,
    capability_group: str,
    forbidden_capability_group: str,
    require_context_installer: bool,
    require_policy_cutover: bool = True,
) -> DatabaseRoleAttestation:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                _ROLE_ATTESTATION_SQL,
                {
                    "capability_group": capability_group,
                    "forbidden_capability_group": forbidden_capability_group,
                },
            )
        ).mappings().one_or_none()
        session_helper_acls_are_exact = bool(
            await connection.scalar(_SESSION_HELPER_ACL_ATTESTATION_SQL)
        )
        adhoc_definer_acl_surface_is_exact = bool(
            await connection.scalar(_ADHOC_DEFINER_ACL_ATTESTATION_SQL)
        )

    if row is None:
        raise RlsRuntimeRoleError(
            "Database credential role could not be attested"
        )

    failed_checks: list[str] = []
    if not session_helper_acls_are_exact:
        failed_checks.append("session_helper_acls_are_exact")
    if not adhoc_definer_acl_surface_is_exact:
        failed_checks.append("adhoc_definer_acl_surface_is_exact")
    boolean_requirements = {
        "login_can_login": True,
        "login_inherits": True,
        "login_superuser": False,
        "login_bypass_rls": False,
        "login_create_database": False,
        "login_create_role": False,
        "login_replication": False,
        "capability_exists": True,
        "capability_can_login": False,
        "capability_inherits": False,
        "capability_superuser": False,
        "capability_bypass_rls": False,
        "capability_create_database": False,
        "capability_create_role": False,
        "capability_replication": False,
        "has_capability": True,
        "has_forbidden_capability": False,
        "capability_membership_is_not_delegable": True,
        "has_no_privileged_membership": True,
        "has_no_delegable_acl_privileges": True,
        "has_no_owner_membership": True,
        "executable_rls_helpers_are_hardened": True,
        "browser_roles_are_denied": True,
        "public_schema_create_is_denied": True,
    }
    for field, required_value in boolean_requirements.items():
        if bool(row.get(field)) is not required_value:
            failed_checks.append(field)

    if str(row.get("current_role") or "") != str(row.get("login_role") or ""):
        failed_checks.append("current_role")
    if str(row.get("row_security") or "").casefold() != "on":
        failed_checks.append("row_security")
    if not bool(row.get("can_use_rls_schema")):
        failed_checks.append("can_use_rls_schema")
    if bool(row.get("can_create_in_rls_schema")):
        failed_checks.append("can_create_in_rls_schema")
    if bool(row.get("can_use_private_schema")):
        failed_checks.append("can_use_private_schema")
    if bool(row.get("can_create_in_private_schema")):
        failed_checks.append("can_create_in_private_schema")
    if bool(row.get("can_create_in_public_schema")):
        failed_checks.append("can_create_in_public_schema")
    if list(row.get("executable_private_helpers") or []):
        failed_checks.append("executable_private_helpers")

    expected_helpers = _EXPECTED_HELPERS_BY_CAPABILITY.get(capability_group)
    if (
        expected_helpers is not None
        and capability_group == "mata_app_runtime"
        and not require_policy_cutover
    ):
        expected_helpers = expected_helpers - _POLICY_HELPERS
    if expected_helpers is None:
        failed_checks.append("expected_helper_contract")
    else:
        actual_helpers = {
            str(signature)
            for signature in (row.get("executable_rls_helpers") or [])
        }
        if actual_helpers != expected_helpers:
            failed_checks.append("executable_rls_helpers")

    expected_table_privileges: set[str] = set()
    if capability_group == "mata_app_runtime" and require_policy_cutover:
        expected_table_privileges = {
            f"{table_name}:{privilege}"
            for table_name, privileges in _RUNTIME_TABLE_PRIVILEGES.items()
            for privilege in privileges
        }
    actual_table_privileges = {
        str(privilege)
        for privilege in (row.get("executable_table_privileges") or [])
    }
    if actual_table_privileges != expected_table_privileges:
        failed_checks.append("executable_table_privileges")

    expected_column_privileges: set[str] = set()
    if capability_group == "mata_app_runtime" and require_policy_cutover:
        for column_identifier in row.get("public_columns") or []:
            table_name, _, column_name = str(column_identifier).partition(".")
            for privilege in _COLUMN_PRIVILEGES:
                if privilege in _RUNTIME_TABLE_PRIVILEGES.get(table_name, set()):
                    expected_column_privileges.add(
                        f"{column_identifier}:{privilege}"
                    )
            if table_name == "users" and column_name in _USERS_SELECT_COLUMNS:
                expected_column_privileges.add(f"{column_identifier}:SELECT")
    actual_column_privileges = {
        str(privilege)
        for privilege in (row.get("executable_column_privileges") or [])
    }
    if actual_column_privileges != expected_column_privileges:
        failed_checks.append("executable_column_privileges")

    if list(row.get("executable_sequence_privileges") or []):
        failed_checks.append("executable_sequence_privileges")

    if require_policy_cutover:
        if {
            str(table_name)
            for table_name in (row.get("rls_application_tables") or [])
        } != _APPLICATION_TABLES:
            failed_checks.append("rls_application_tables")
        if list(row.get("forced_rls_application_tables") or []):
            failed_checks.append("forced_rls_application_tables")
        actual_policy_catalogue = [
            str(policy)
            for policy in (row.get("application_policy_catalogue") or [])
        ]
        if (
            len(actual_policy_catalogue) != len(_RUNTIME_POLICY_CATALOGUE)
            or set(actual_policy_catalogue) != _RUNTIME_POLICY_CATALOGUE
        ):
            failed_checks.append("application_policy_catalogue")
        if int(row.get("unsafe_application_policy_count") or 0) != 0:
            failed_checks.append("unsafe_application_policy_count")

    if require_context_installer:
        if not bool(row.get("installer_exists")):
            failed_checks.append("installer_exists")
        if not bool(row.get("can_install_context")):
            failed_checks.append("can_install_context")
        if require_policy_cutover and not bool(row.get("can_generate_uuid")):
            failed_checks.append("can_generate_uuid")
        if not require_policy_cutover and bool(row.get("can_generate_uuid")):
            failed_checks.append("can_generate_uuid")
    elif bool(row.get("can_install_context")):
        failed_checks.append("can_install_context")
    elif bool(row.get("can_generate_uuid")):
        failed_checks.append("can_generate_uuid")

    if failed_checks:
        raise RlsRuntimeRoleError(
            "Database role attestation failed for "
            f"{capability_group}: {', '.join(sorted(failed_checks))}"
        )

    return DatabaseRoleAttestation(
        database_name=str(row["database_name"]),
        login_role=str(row["login_role"]),
        capability_group=capability_group,
    )
