"""enforce explicit scheduled event sources at the RLS boundary

Revision ID: 20260804_000033
Revises: 20260803_000032
Create Date: 2026-08-04

Scheduled-event writes now carry one explicit source identity.  The prior
event-insert policy validates only legacy display text and therefore rejects a
valid pending Teaching Name that has no legacy catalogue row.  This migration
adds narrow runtime policy helpers for scheduled inserts and updates; it leaves the
legacy catalogue path, resident visibility, and ad-hoc helper boundary intact.
"""

from __future__ import annotations

from alembic import op


revision = "20260804_000033"
down_revision = "20260803_000032"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
_OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
_FUNCTION_SIGNATURE = (
    "mata_rls.can_insert_scheduled_event_source(text,text,uuid,uuid,date,boolean,text)"
)
_UPDATE_FUNCTION_SIGNATURE = (
    "mata_rls.can_manage_scheduled_event_source(text,uuid,uuid,date,boolean)"
)


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _revoke_optional_function_privileges(function_signature: str) -> None:
    optional_roles = ", ".join(repr(role) for role in _OPTIONAL_BROWSER_ROLES)
    _execute(
        f"""
DO $migration$
DECLARE
    optional_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[{optional_roles}]::text[]
    LOOP
        IF pg_catalog.to_regrole(optional_role) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION {function_signature} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def _create_scheduled_event_source_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_insert_scheduled_event_source(
    p_posting_code text,
    p_created_for_programme_code text,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
    p_event_date date,
    p_is_adhoc boolean,
    p_created_by_role text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    source_programme_code text;
BEGIN
    IF COALESCE(p_is_adhoc, false)
       OR (p_teaching_name_id IS NULL) = (p_global_session_type_id IS NULL)
    THEN
        RETURN false;
    END IF;

    IF p_teaching_name_id IS NOT NULL THEN
        SELECT teaching_name.programme_code
        INTO source_programme_code
        FROM public.teaching_names AS teaching_name
        JOIN public.reporting_periods AS reporting_period
          ON reporting_period.id = teaching_name.reporting_period_id
        WHERE teaching_name.id = p_teaching_name_id
          AND teaching_name.is_active
          AND p_event_date BETWEEN reporting_period.start_date
                               AND reporting_period.end_date;

        IF NOT FOUND THEN
            RETURN false;
        END IF;

        IF mata_rls.is_master_admin() THEN
            RETURN true;
        END IF;

        IF mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'admin'
           AND p_created_by_role = 'programme_pc'
           AND p_created_for_programme_code = source_programme_code
           AND mata_rls.has_programme_scope(source_programme_code)
        THEN
            RETURN true;
        END IF;

        RETURN mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'secretary'
           AND p_created_by_role = 'secretary'
           AND p_created_for_programme_code IS NULL
           AND mata_rls.is_secretary_for_posting(p_posting_code)
           AND EXISTS (
               SELECT 1
               FROM public.secretary_programme_pools AS pool
               WHERE pool.posting_code = p_posting_code
                 AND pool.programme_code = source_programme_code
                 AND pool.is_active
                 AND pool.can_manage_teaching_names
           );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.global_session_types AS global_type
        WHERE global_type.id = p_global_session_type_id
          AND global_type.is_active
    ) THEN
        RETURN false;
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'admin'
       AND p_created_by_role = 'programme_pc'
       AND p_created_for_programme_code IS NOT NULL
       AND mata_rls.has_programme_scope(p_created_for_programme_code)
       AND (
           EXISTS (
               SELECT 1
               FROM public.secretary_programme_pools AS pool
               WHERE pool.programme_code = pg_catalog.upper(
                   pg_catalog.btrim(p_created_for_programme_code)
               )
                 AND pool.posting_code = p_posting_code
                 AND pool.is_active
           )
           OR EXISTS (
               SELECT 1
               FROM public.teaching_name_catalogue AS catalogue
               JOIN public.reporting_periods AS reporting_period
                 ON reporting_period.id = catalogue.reporting_period_id
               WHERE catalogue.programme_code = pg_catalog.upper(
                   pg_catalog.btrim(p_created_for_programme_code)
               )
                 AND catalogue.posting_code = p_posting_code
                 AND p_event_date BETWEEN reporting_period.start_date
                                      AND reporting_period.end_date
           )
       )
    THEN
        RETURN true;
    END IF;

    RETURN mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'secretary'
       AND p_created_by_role = 'secretary'
       AND p_created_for_programme_code IS NULL
       AND mata_rls.is_secretary_for_posting(p_posting_code);
END
$function$
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        f"{_FUNCTION_SIGNATURE} FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION "
        f"{_FUNCTION_SIGNATURE} TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(_FUNCTION_SIGNATURE)


def _create_scheduled_event_source_update_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_manage_scheduled_event_source(
    p_posting_code text,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
    p_event_date date,
    p_is_adhoc boolean
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    source_programme_code text;
BEGIN
    IF COALESCE(p_is_adhoc, false)
       OR (p_teaching_name_id IS NULL) = (p_global_session_type_id IS NULL)
    THEN
        RETURN false;
    END IF;

    IF p_teaching_name_id IS NOT NULL THEN
        SELECT teaching_name.programme_code
        INTO source_programme_code
        FROM public.teaching_names AS teaching_name
        JOIN public.reporting_periods AS reporting_period
          ON reporting_period.id = teaching_name.reporting_period_id
        WHERE teaching_name.id = p_teaching_name_id
          AND teaching_name.is_active
          AND p_event_date BETWEEN reporting_period.start_date
                               AND reporting_period.end_date;

        IF NOT FOUND THEN
            RETURN false;
        END IF;

        IF mata_rls.is_master_admin() THEN
            RETURN true;
        END IF;

        IF mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'admin'
        THEN
            RETURN mata_rls.has_programme_scope(source_programme_code);
        END IF;

        RETURN mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'secretary'
           AND mata_rls.is_secretary_for_posting(p_posting_code)
           AND EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = p_posting_code
                  AND pool.programme_code = source_programme_code
                  AND pool.is_active
                  AND pool.can_manage_teaching_names
           );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.global_session_types AS global_type
        WHERE global_type.id = p_global_session_type_id
          AND global_type.is_active
    ) THEN
        RETURN false;
    END IF;

    RETURN mata_rls.is_master_admin()
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'admin'
        )
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND mata_rls.is_secretary_for_posting(p_posting_code)
        );
END
$function$
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        f"{_UPDATE_FUNCTION_SIGNATURE} FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION "
        f"{_UPDATE_FUNCTION_SIGNATURE} TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(_UPDATE_FUNCTION_SIGNATURE)


def _replace_event_insert_policy() -> None:
    _execute('DROP POLICY "mata_rls_teaching_events_insert" ON public.teaching_events')
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_insert"
ON public.teaching_events
AS PERMISSIVE
FOR INSERT
TO {RUNTIME_ROLE}
WITH CHECK (
    (
        NOT COALESCE(is_adhoc, false)
        AND mata_rls.can_insert_scheduled_event_source(
            posting_code,
            created_for_programme_code,
            teaching_name_id,
            global_session_type_id,
            event_date,
            is_adhoc,
            created_by_role
        )
    )
    OR (
        COALESCE(is_adhoc, false)
        AND mata_rls.can_insert_teaching_event(
            posting_code,
            created_for_programme_code,
            teaching_name,
            event_date,
            is_adhoc,
            created_by_role
        )
    )
)
"""
    )


def _replace_event_update_policy() -> None:
    _execute('DROP POLICY "mata_rls_teaching_events_update" ON public.teaching_events')
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_update"
ON public.teaching_events
AS PERMISSIVE
FOR UPDATE
TO {RUNTIME_ROLE}
USING (
    mata_rls.can_manage_teaching_event(
        posting_code,
        created_for_programme_code,
        teaching_name,
        event_date,
        is_adhoc,
        created_by_role
    )
)
WITH CHECK (
    mata_rls.can_manage_teaching_event(
        posting_code,
        created_for_programme_code,
        teaching_name,
        event_date,
        is_adhoc,
        created_by_role
    )
    AND (
        COALESCE(is_adhoc, false)
        OR mata_rls.can_manage_scheduled_event_source(
            posting_code,
            teaching_name_id,
            global_session_type_id,
            event_date,
            is_adhoc
        )
    )
)
"""
    )


def _assert_source_helper_security() -> None:
    _execute(
        f"""
DO $migration$
DECLARE
    helper_oid regprocedure := pg_catalog.to_regprocedure(
        '{_FUNCTION_SIGNATURE}'
    );
    update_helper_oid regprocedure := pg_catalog.to_regprocedure(
        '{_UPDATE_FUNCTION_SIGNATURE}'
    );
BEGIN
    IF helper_oid IS NULL
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           WHERE procedure.oid = helper_oid
             AND namespace.nspname = 'mata_rls'
             AND procedure.proowner = pg_catalog.to_regrole(CURRENT_USER)
             AND procedure.prosecdef
             AND procedure.proconfig = ARRAY[
                 'search_path=pg_catalog, pg_temp'
             ]::text[]
             AND pg_catalog.pg_get_function_result(procedure.oid) = 'boolean'
       )
    THEN
        RAISE EXCEPTION 'Scheduled event source helper security assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.has_function_privilege(
               '{RUNTIME_ROLE}', helper_oid, 'EXECUTE'
           )
       OR pg_catalog.has_function_privilege(
               '{AUTH_ROLE}', helper_oid, 'EXECUTE'
           )
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL pg_catalog.aclexplode(
               COALESCE(
                   procedure.proacl,
                   pg_catalog.acldefault('f', procedure.proowner)
               )
           ) AS privilege
           WHERE procedure.oid = helper_oid
             AND privilege.grantee = 0
             AND privilege.privilege_type = 'EXECUTE'
       )
    THEN
        RAISE EXCEPTION 'Scheduled event source helper ACL assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF update_helper_oid IS NULL
       OR NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE procedure.oid = update_helper_oid
              AND namespace.nspname = 'mata_rls'
              AND procedure.proowner = pg_catalog.to_regrole(CURRENT_USER)
              AND procedure.prosecdef
              AND procedure.proconfig = ARRAY[
                  'search_path=pg_catalog, pg_temp'
              ]::text[]
              AND pg_catalog.pg_get_function_result(procedure.oid) = 'boolean'
       )
    THEN
        RAISE EXCEPTION 'Scheduled event update-source helper security assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.has_function_privilege(
               '{RUNTIME_ROLE}', update_helper_oid, 'EXECUTE'
           )
       OR pg_catalog.has_function_privilege(
               '{AUTH_ROLE}', update_helper_oid, 'EXECUTE'
           )
       OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS privilege
            WHERE procedure.oid = update_helper_oid
              AND privilege.grantee = 0
              AND privilege.privilege_type = 'EXECUTE'
       )
    THEN
        RAISE EXCEPTION 'Scheduled event update-source helper ACL assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'teaching_events'
          AND policy.polname = 'mata_rls_teaching_events_insert'
          AND pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
              LIKE '%can_insert_scheduled_event_source%'
    ) THEN
        RAISE EXCEPTION 'Scheduled event insert policy was not replaced'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'teaching_events'
          AND policy.polname = 'mata_rls_teaching_events_update'
          AND pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
              LIKE '%can_manage_scheduled_event_source%'
    ) THEN
        RAISE EXCEPTION 'Scheduled event update policy was not replaced'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def upgrade() -> None:
    _create_scheduled_event_source_helper()
    _create_scheduled_event_source_update_helper()
    _replace_event_insert_policy()
    _replace_event_update_policy()
    _assert_source_helper_security()


def downgrade() -> None:
    _execute('DROP POLICY "mata_rls_teaching_events_insert" ON public.teaching_events')
    _execute('DROP POLICY "mata_rls_teaching_events_update" ON public.teaching_events')
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_insert"
ON public.teaching_events
AS PERMISSIVE
FOR INSERT
TO {RUNTIME_ROLE}
WITH CHECK (
    mata_rls.can_insert_teaching_event(
        posting_code,
        created_for_programme_code,
        teaching_name,
        event_date,
        is_adhoc,
        created_by_role
    )
)
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_update"
ON public.teaching_events
AS PERMISSIVE
FOR UPDATE
TO {RUNTIME_ROLE}
USING (
    mata_rls.can_manage_teaching_event(
        posting_code,
        created_for_programme_code,
        teaching_name,
        event_date,
        is_adhoc,
        created_by_role
    )
)
WITH CHECK (
    mata_rls.can_manage_teaching_event(
        posting_code,
        created_for_programme_code,
        teaching_name,
        event_date,
        is_adhoc,
        created_by_role
    )
)
"""
    )
    _execute(f"DROP FUNCTION IF EXISTS {_UPDATE_FUNCTION_SIGNATURE}")
    _execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_SIGNATURE}")
