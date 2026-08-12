"""add cross-posting Teaching Name programme scopes

Revision ID: 20260812_000040
Revises: 20260812_000039
Create Date: 2026-08-12
"""

from alembic import op


revision = "20260812_000040"
down_revision = "20260812_000039"
branch_labels = None
depends_on = None

RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _secure_runtime_function(signature: str) -> None:
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} TO {RUNTIME_ROLE}"
    )


def upgrade() -> None:
    _execute(
        r"""
ALTER TABLE public.teaching_names
    ADD COLUMN created_by_role varchar(20),
    ADD COLUMN visibility_scope varchar(30),
    ADD COLUMN origin_posting_code varchar(50);

UPDATE public.teaching_names AS name
SET created_by_role = CASE
        WHEN creator.role = 'secretary' AND creator.posting_code IS NOT NULL
        THEN 'secretary'
        ELSE 'programme_pc'
    END,
    visibility_scope = CASE
        WHEN creator.role = 'secretary' AND creator.posting_code IS NOT NULL
        THEN 'department_shared'
        ELSE 'programme_private'
    END,
    origin_posting_code = CASE
        WHEN creator.role = 'secretary' AND creator.posting_code IS NOT NULL
        THEN creator.posting_code
        ELSE NULL
    END
FROM public.users AS creator
WHERE creator.id = name.created_by_user_id;

UPDATE public.teaching_names
SET created_by_role = 'programme_pc',
    visibility_scope = 'programme_private',
    origin_posting_code = NULL
WHERE created_by_role IS NULL;

ALTER TABLE public.teaching_names
    ALTER COLUMN created_by_role SET NOT NULL,
    ALTER COLUMN visibility_scope SET NOT NULL,
    ADD CONSTRAINT fk_teaching_names_origin_posting
        FOREIGN KEY (origin_posting_code)
        REFERENCES public.posting_codes(code),
    ADD CONSTRAINT ck_teaching_names_provenance CHECK (
        (created_by_role = 'secretary'
         AND visibility_scope = 'department_shared'
         AND origin_posting_code IS NOT NULL)
        OR
        (created_by_role = 'programme_pc'
         AND visibility_scope = 'programme_private'
         AND origin_posting_code IS NULL)
    ),
    ADD CONSTRAINT uq_teaching_names_id_period
        UNIQUE (id, reporting_period_id);

CREATE OR REPLACE FUNCTION mata_private.enforce_teaching_name_scope_immutability()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NEW.reporting_period_id IS DISTINCT FROM OLD.reporting_period_id
       OR NEW.programme_code IS DISTINCT FROM OLD.programme_code
       OR NEW.created_by_role IS DISTINCT FROM OLD.created_by_role
       OR NEW.visibility_scope IS DISTINCT FROM OLD.visibility_scope
       OR NEW.origin_posting_code IS DISTINCT FROM OLD.origin_posting_code
    THEN
        RAISE EXCEPTION
            'Teaching Name source ownership and provenance are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER mata_enforce_teaching_name_scope_immutability
ON public.teaching_names;
CREATE TRIGGER mata_enforce_teaching_name_scope_immutability
BEFORE UPDATE OF reporting_period_id, programme_code, created_by_role,
                 visibility_scope, origin_posting_code
ON public.teaching_names
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_teaching_name_scope_immutability();

CREATE TABLE public.teaching_name_programme_scopes (
    teaching_name_id uuid NOT NULL,
    reporting_period_id uuid NOT NULL,
    programme_code varchar(20) NOT NULL,
    admission_reason varchar(30) NOT NULL,
    admitted_by_user_id uuid,
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_teaching_name_programme_scopes_name_period
        FOREIGN KEY (teaching_name_id, reporting_period_id)
        REFERENCES public.teaching_names(id, reporting_period_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_teaching_name_programme_scopes_programme
        FOREIGN KEY (programme_code) REFERENCES public.programmes(code),
    CONSTRAINT fk_teaching_name_programme_scopes_admitted_by
        FOREIGN KEY (admitted_by_user_id) REFERENCES public.users(id),
    CONSTRAINT ck_teaching_name_programme_scopes_reason CHECK (
        admission_reason IN (
            'owner_programme', 'resident_host_posting', 'pc_private'
        )
    ),
    CONSTRAINT uq_teaching_name_programme_scopes_identity
        UNIQUE (teaching_name_id, programme_code),
    CONSTRAINT uq_teaching_name_programme_scopes_mapping_scope
        UNIQUE (teaching_name_id, reporting_period_id, programme_code)
);

CREATE INDEX idx_teaching_name_programme_scopes_programme_period
ON public.teaching_name_programme_scopes(
    programme_code, reporting_period_id, teaching_name_id
);

INSERT INTO public.teaching_name_programme_scopes (
    teaching_name_id,
    reporting_period_id,
    programme_code,
    admission_reason,
    admitted_by_user_id
)
SELECT
    id,
    reporting_period_id,
    programme_code,
    CASE
        WHEN visibility_scope = 'programme_private' THEN 'pc_private'
        ELSE 'owner_programme'
    END,
    created_by_user_id
FROM public.teaching_names;

INSERT INTO public.teaching_name_programme_scopes (
    teaching_name_id,
    reporting_period_id,
    programme_code,
    admission_reason
)
SELECT DISTINCT
    name.id,
    name.reporting_period_id,
    resident.programme_code,
    'resident_host_posting'
FROM public.teaching_names AS name
JOIN public.resident_postings AS posting
  ON posting.reporting_period_id = name.reporting_period_id
 AND posting.posting_code = name.origin_posting_code
 AND posting.status IN ('active', 'loa_working')
JOIN public.residents AS resident
  ON resident.id = posting.resident_id
 AND resident.programme_code IS NOT NULL
WHERE name.created_by_role = 'secretary'
  AND name.visibility_scope = 'department_shared'
  AND resident.programme_code <> name.programme_code
ON CONFLICT (teaching_name_id, programme_code) DO NOTHING;

ALTER TABLE public.teaching_name_mappings
    DROP CONSTRAINT fk_teaching_name_mappings_name_pool,
    DROP CONSTRAINT uq_teaching_name_mappings_identity,
    ADD CONSTRAINT fk_teaching_name_mappings_programme_scope
        FOREIGN KEY (teaching_name_id, reporting_period_id, programme_code)
        REFERENCES public.teaching_name_programme_scopes(
            teaching_name_id, reporting_period_id, programme_code
        ) ON DELETE CASCADE,
    ADD CONSTRAINT uq_teaching_name_mappings_identity
        UNIQUE (teaching_name_id, programme_code, posting_code, r_year);

INSERT INTO public.teaching_name_mappings (
    teaching_name_id,
    reporting_period_id,
    programme_code,
    posting_code,
    r_year,
    teaching_target_id
)
SELECT DISTINCT
    scope.teaching_name_id,
    scope.reporting_period_id,
    scope.programme_code,
    target.posting_code,
    target.r_year,
    NULL::uuid
FROM public.teaching_name_programme_scopes AS scope
JOIN public.teaching_names AS name
  ON name.id = scope.teaching_name_id
 AND name.reporting_period_id = scope.reporting_period_id
JOIN public.teaching_targets AS target
  ON target.reporting_period_id = scope.reporting_period_id
 AND target.programme_code = scope.programme_code
 AND target.posting_code = name.origin_posting_code
WHERE scope.admission_reason = 'resident_host_posting'
  AND name.is_active
ON CONFLICT (
    teaching_name_id, programme_code, posting_code, r_year
) DO NOTHING;

WITH programme_timing AS (
    SELECT
        mapping.teaching_name_id,
        mapping.reporting_period_id,
        mapping.programme_code,
        mapping.posting_code,
        max(COALESCE(session_type.duration_hours, 1.00)) AS duration_hours
    FROM public.teaching_name_mappings AS mapping
    LEFT JOIN public.teaching_targets AS target
      ON target.id = mapping.teaching_target_id
    LEFT JOIN public.session_types AS session_type
      ON session_type.id = target.session_type_id
    GROUP BY
        mapping.teaching_name_id,
        mapping.reporting_period_id,
        mapping.programme_code,
        mapping.posting_code
)
UPDATE public.teaching_events AS event
SET duration_hours = timing.duration_hours,
    end_time = (
        event.start_time
        + make_interval(secs => (timing.duration_hours * 3600)::integer)
    )::time,
    updated_at = clock_timestamp()
FROM programme_timing AS timing
WHERE event.teaching_name_id = timing.teaching_name_id
  AND event.source_reporting_period_id = timing.reporting_period_id
  AND event.posting_code = timing.posting_code
  AND event.created_for_programme_code = timing.programme_code
  AND event.global_session_type_id IS NULL
  AND event.is_adhoc = false;

WITH secretary_timing AS (
    SELECT
        mapping.teaching_name_id,
        mapping.reporting_period_id,
        mapping.posting_code,
        max(COALESCE(session_type.duration_hours, 1.00)) AS duration_hours
    FROM public.teaching_name_mappings AS mapping
    LEFT JOIN public.teaching_targets AS target
      ON target.id = mapping.teaching_target_id
    LEFT JOIN public.session_types AS session_type
      ON session_type.id = target.session_type_id
    GROUP BY
        mapping.teaching_name_id,
        mapping.reporting_period_id,
        mapping.posting_code
)
UPDATE public.teaching_events AS event
SET duration_hours = timing.duration_hours,
    end_time = (
        event.start_time
        + make_interval(secs => (timing.duration_hours * 3600)::integer)
    )::time,
    updated_at = clock_timestamp()
FROM secretary_timing AS timing
WHERE event.teaching_name_id = timing.teaching_name_id
  AND event.source_reporting_period_id = timing.reporting_period_id
  AND event.posting_code = timing.posting_code
  AND event.created_for_programme_code IS NULL
  AND event.global_session_type_id IS NULL
  AND event.is_adhoc = false;

DROP TRIGGER IF EXISTS mata_reconcile_teaching_name_pending_mappings
ON public.teaching_names;
DROP FUNCTION IF EXISTS mata_private.reconcile_teaching_name_pending_mappings();
"""
    )

    _execute(
        r"""
ALTER TABLE public.teaching_name_programme_scopes ENABLE ROW LEVEL SECURITY;

CREATE POLICY mata_rls_teaching_name_programme_scopes_select
ON public.teaching_name_programme_scopes
FOR SELECT TO mata_app_runtime
USING (
    mata_rls.is_master_admin()
    OR mata_rls.has_programme_scope(programme_code)
    OR EXISTS (
        SELECT 1 FROM public.secretary_programme_pools AS pool
        WHERE pool.programme_code = teaching_name_programme_scopes.programme_code
         AND pool.is_active
         AND pool.can_manage_teaching_names
          AND mata_rls.is_secretary_for_posting(pool.posting_code)
    )
);

REVOKE ALL PRIVILEGES ON TABLE public.teaching_name_programme_scopes
FROM PUBLIC, mata_app_runtime, mata_auth_internal;
GRANT SELECT ON TABLE public.teaching_name_programme_scopes TO mata_app_runtime;

DROP POLICY mata_rls_teaching_names_select ON public.teaching_names;
CREATE POLICY mata_rls_teaching_names_select
ON public.teaching_names FOR SELECT TO mata_app_runtime
USING (
    mata_rls.is_master_admin()
    OR mata_rls.has_programme_scope(programme_code)
    OR EXISTS (
        SELECT 1
        FROM public.teaching_name_programme_scopes AS scope
        WHERE scope.teaching_name_id = teaching_names.id
          AND mata_rls.has_programme_scope(scope.programme_code)
    )
    OR EXISTS (
        SELECT 1
        FROM public.secretary_programme_pools AS pool
        WHERE pool.programme_code = teaching_names.programme_code
          AND pool.is_active
          AND pool.can_manage_teaching_names
          AND mata_rls.is_secretary_for_posting(pool.posting_code)
          AND (
              teaching_names.origin_posting_code = pool.posting_code
              OR (
                  teaching_names.visibility_scope = 'programme_private'
                  AND EXISTS (
                      SELECT 1 FROM public.programmes AS programme
                      WHERE programme.code = teaching_names.programme_code
                        AND programme.native_teaching_posting_code
                            = pool.posting_code
                  )
              )
          )
    )
);

DROP POLICY mata_rls_teaching_names_insert ON public.teaching_names;
CREATE POLICY mata_rls_teaching_names_insert
ON public.teaching_names FOR INSERT TO mata_app_runtime
WITH CHECK (
    (
        created_by_role = 'programme_pc'
        AND visibility_scope = 'programme_private'
        AND origin_posting_code IS NULL
        AND mata_rls.has_programme_scope(programme_code)
    ) OR (
        created_by_role = 'secretary'
        AND visibility_scope = 'department_shared'
        AND origin_posting_code IS NOT NULL
        AND mata_rls.is_secretary_for_posting(origin_posting_code)
        AND EXISTS (
            SELECT 1 FROM public.secretary_programme_pools AS pool
            WHERE pool.posting_code = teaching_names.origin_posting_code
              AND pool.programme_code = teaching_names.programme_code
              AND pool.is_active
              AND pool.can_manage_teaching_names
        )
    )
);

DROP POLICY mata_rls_teaching_names_update ON public.teaching_names;
CREATE POLICY mata_rls_teaching_names_update
ON public.teaching_names FOR UPDATE TO mata_app_runtime
USING (
    mata_rls.has_programme_scope(programme_code)
    OR (
        created_by_role = 'secretary'
        AND mata_rls.is_secretary_for_posting(origin_posting_code)
        AND EXISTS (
            SELECT 1 FROM public.secretary_programme_pools AS pool
            WHERE pool.posting_code = teaching_names.origin_posting_code
              AND pool.programme_code = teaching_names.programme_code
              AND pool.is_active
              AND pool.can_manage_teaching_names
        )
    )
)
WITH CHECK (
    mata_rls.has_programme_scope(programme_code)
    OR (
        created_by_role = 'secretary'
        AND mata_rls.is_secretary_for_posting(origin_posting_code)
        AND EXISTS (
            SELECT 1 FROM public.secretary_programme_pools AS pool
            WHERE pool.posting_code = teaching_names.origin_posting_code
              AND pool.programme_code = teaching_names.programme_code
              AND pool.is_active
              AND pool.can_manage_teaching_names
        )
    )
);

DROP POLICY mata_rls_teaching_names_delete ON public.teaching_names;
CREATE POLICY mata_rls_teaching_names_delete
ON public.teaching_names FOR DELETE TO mata_app_runtime
USING (
    mata_rls.is_master_admin()
    OR (
        NOT EXISTS (
            SELECT 1 FROM public.teaching_events AS event
            WHERE event.teaching_name_id = teaching_names.id
        )
        AND (
            mata_rls.has_programme_scope(programme_code)
            OR (
                created_by_role = 'secretary'
                AND mata_rls.is_secretary_for_posting(origin_posting_code)
                AND EXISTS (
                    SELECT 1 FROM public.secretary_programme_pools AS pool
                    WHERE pool.posting_code = teaching_names.origin_posting_code
                      AND pool.programme_code = teaching_names.programme_code
                      AND pool.is_active
                      AND pool.can_manage_teaching_names
                )
            )
        )
    )
);
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.reconcile_teaching_name_programme_scopes(
    p_reporting_period_id uuid,
    p_programme_code text
)
RETURNS TABLE(
    programme_scopes_created integer,
    pending_mappings_created integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_owner_count integer := 0;
    v_cross_count integer := 0;
    v_mapping_count integer := 0;
BEGIN
    IF p_programme_code IS NULL OR btrim(p_programme_code) = '' THEN
        RAISE EXCEPTION 'Programme scope is required'
            USING ERRCODE = '22023';
    END IF;
    IF NOT (
        mata_rls.is_master_admin()
        OR mata_rls.has_programme_scope(p_programme_code)
        OR EXISTS (
            SELECT 1 FROM public.secretary_programme_pools AS pool
            WHERE pool.programme_code = p_programme_code
              AND pool.is_active
              AND pool.can_manage_teaching_names
              AND mata_rls.is_secretary_for_posting(pool.posting_code)
        )
    ) THEN
        RAISE EXCEPTION 'Teaching Name programme scope required'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO public.teaching_name_programme_scopes (
        teaching_name_id, reporting_period_id, programme_code,
        admission_reason, admitted_by_user_id
    )
    SELECT
        name.id, name.reporting_period_id, name.programme_code,
        CASE WHEN name.visibility_scope = 'programme_private'
             THEN 'pc_private' ELSE 'owner_programme' END,
        name.created_by_user_id
    FROM public.teaching_names AS name
    WHERE name.reporting_period_id = p_reporting_period_id
      AND name.programme_code = p_programme_code
    ON CONFLICT (teaching_name_id, programme_code) DO NOTHING;
    GET DIAGNOSTICS v_owner_count = ROW_COUNT;

    INSERT INTO public.teaching_name_programme_scopes (
        teaching_name_id, reporting_period_id, programme_code,
        admission_reason, admitted_by_user_id
    )
    SELECT DISTINCT
        name.id, name.reporting_period_id, resident.programme_code,
        'resident_host_posting', mata_rls.current_subject_id()
    FROM public.teaching_names AS name
    JOIN public.resident_postings AS posting
      ON posting.reporting_period_id = name.reporting_period_id
     AND posting.posting_code = name.origin_posting_code
     AND posting.status IN ('active', 'loa_working')
    JOIN public.residents AS resident
      ON resident.id = posting.resident_id
     AND resident.programme_code IS NOT NULL
    WHERE name.reporting_period_id = p_reporting_period_id
      AND name.created_by_role = 'secretary'
      AND name.visibility_scope = 'department_shared'
      AND (
          name.programme_code = p_programme_code
          OR resident.programme_code = p_programme_code
      )
    ON CONFLICT (teaching_name_id, programme_code) DO NOTHING;
    GET DIAGNOSTICS v_cross_count = ROW_COUNT;

    INSERT INTO public.teaching_name_mappings (
        teaching_name_id, reporting_period_id, programme_code,
        posting_code, r_year, teaching_target_id
    )
    SELECT DISTINCT
        scope.teaching_name_id, scope.reporting_period_id,
        scope.programme_code, target.posting_code, target.r_year, NULL::uuid
    FROM public.teaching_name_programme_scopes AS scope
    JOIN public.teaching_names AS name
      ON name.id = scope.teaching_name_id
     AND name.reporting_period_id = scope.reporting_period_id
    JOIN public.teaching_targets AS target
      ON target.reporting_period_id = scope.reporting_period_id
     AND target.programme_code = scope.programme_code
     AND (
         scope.admission_reason <> 'resident_host_posting'
         OR target.posting_code = name.origin_posting_code
     )
    WHERE scope.reporting_period_id = p_reporting_period_id
      AND name.is_active
      AND (
          name.programme_code = p_programme_code
          OR scope.programme_code = p_programme_code
      )
    ON CONFLICT (
        teaching_name_id, programme_code, posting_code, r_year
    ) DO NOTHING;
    GET DIAGNOSTICS v_mapping_count = ROW_COUNT;

    RETURN QUERY SELECT
        v_owner_count + v_cross_count,
        v_mapping_count;
END
$function$;
"""
    )
    _secure_runtime_function(
        "reconcile_teaching_name_programme_scopes(uuid,text)"
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.reconcile_ttf_teaching_name_mappings_v2(
    p_reporting_period_id uuid,
    p_programme_code text,
    p_stale_target_ids uuid[],
    p_introduced_posting_codes text[],
    p_introduced_r_years text[]
)
RETURNS TABLE(
    mappings_invalidated integer,
    pending_mappings_created integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_programme text := upper(btrim(p_programme_code));
    actor_id uuid := mata_rls.current_subject_id();
BEGIN
    IF NOT mata_rls.context_is_valid()
       OR NOT (
           mata_rls.is_master_admin()
           OR mata_rls.has_programme_scope(normalized_programme)
       )
    THEN
        RAISE EXCEPTION 'TTF programme scope required'
            USING ERRCODE = '42501';
    END IF;

    IF actor_id IS NULL
       OR p_reporting_period_id IS NULL
       OR normalized_programme = ''
       OR length(normalized_programme) > 20
       OR p_stale_target_ids IS NULL
       OR p_introduced_posting_codes IS NULL
       OR p_introduced_r_years IS NULL
       OR cardinality(p_stale_target_ids) > 10000
       OR cardinality(p_introduced_posting_codes) > 10000
       OR cardinality(p_introduced_posting_codes)
            <> cardinality(p_introduced_r_years)
    THEN
        RAISE EXCEPTION 'Invalid TTF mapping reconciliation input'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(p_stale_target_ids) AS stale(target_id)
        WHERE stale.target_id IS NULL
    ) OR cardinality(p_stale_target_ids) <> (
        SELECT count(DISTINCT stale.target_id)
        FROM unnest(p_stale_target_ids) AS stale(target_id)
    ) OR cardinality(p_stale_target_ids) <> (
        SELECT count(*)
        FROM public.teaching_targets AS target
        WHERE target.id = ANY(p_stale_target_ids)
          AND target.reporting_period_id = p_reporting_period_id
          AND target.programme_code = normalized_programme
    ) THEN
        RAISE EXCEPTION 'Stale TTF targets must belong to the requested scope'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(p_introduced_posting_codes) WITH ORDINALITY
             AS posting(posting_code, ordinal_position)
        JOIN unnest(p_introduced_r_years) WITH ORDINALITY
             AS resident_year(r_year, ordinal_position)
          USING (ordinal_position)
        WHERE posting.posting_code IS NULL
           OR resident_year.r_year IS NULL
           OR posting.posting_code <> btrim(posting.posting_code)
           OR resident_year.r_year <> btrim(resident_year.r_year)
           OR posting.posting_code = ''
           OR resident_year.r_year = ''
           OR length(posting.posting_code) > 50
           OR length(resident_year.r_year) > 10
           OR NOT EXISTS (
               SELECT 1
               FROM public.teaching_targets AS target
               WHERE target.reporting_period_id = p_reporting_period_id
                 AND target.programme_code = normalized_programme
                 AND target.posting_code = posting.posting_code
                 AND target.r_year = resident_year.r_year
           )
    ) OR cardinality(p_introduced_posting_codes) <> (
        SELECT count(*)
        FROM (
            SELECT DISTINCT posting.posting_code, resident_year.r_year
            FROM unnest(p_introduced_posting_codes) WITH ORDINALITY
                 AS posting(posting_code, ordinal_position)
            JOIN unnest(p_introduced_r_years) WITH ORDINALITY
                 AS resident_year(r_year, ordinal_position)
              USING (ordinal_position)
        ) AS distinct_scope
    ) THEN
        RAISE EXCEPTION 'Invalid introduced TTF target scope'
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.teaching_name_mappings AS mapping
    SET teaching_target_id = NULL,
        revision = mapping.revision + 1,
        updated_at = clock_timestamp(),
        updated_by_user_id = actor_id
    WHERE mapping.reporting_period_id = p_reporting_period_id
      AND mapping.programme_code = normalized_programme
      AND mapping.teaching_target_id = ANY(p_stale_target_ids);
    GET DIAGNOSTICS mappings_invalidated = ROW_COUNT;

    INSERT INTO public.teaching_name_mappings (
        teaching_name_id, reporting_period_id, programme_code,
        posting_code, r_year, teaching_target_id,
        created_by_user_id, updated_by_user_id
    )
    SELECT
        scope.teaching_name_id, scope.reporting_period_id,
        scope.programme_code, posting.posting_code,
        resident_year.r_year, NULL::uuid, actor_id, actor_id
    FROM public.teaching_name_programme_scopes AS scope
    JOIN public.teaching_names AS name
      ON name.id = scope.teaching_name_id
     AND name.reporting_period_id = scope.reporting_period_id
    CROSS JOIN unnest(p_introduced_posting_codes) WITH ORDINALITY
         AS posting(posting_code, ordinal_position)
    JOIN unnest(p_introduced_r_years) WITH ORDINALITY
         AS resident_year(r_year, ordinal_position)
      USING (ordinal_position)
    WHERE scope.reporting_period_id = p_reporting_period_id
      AND scope.programme_code = normalized_programme
      AND name.is_active
      AND (
          scope.admission_reason <> 'resident_host_posting'
          OR name.origin_posting_code = posting.posting_code
      )
    ON CONFLICT (
        teaching_name_id, programme_code, posting_code, r_year
    ) DO NOTHING;
    GET DIAGNOSTICS pending_mappings_created = ROW_COUNT;

    RETURN NEXT;
END
$function$;
"""
    )
    _secure_runtime_function(
        "reconcile_ttf_teaching_name_mappings_v2(uuid,text,uuid[],text[],text[])"
    )
    _execute(
        "REVOKE EXECUTE ON FUNCTION "
        "mata_rls.reconcile_ttf_teaching_name_mappings("
        "uuid,text,uuid[],text[],text[]) FROM mata_app_runtime"
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.can_select_cross_programme_secretary_event(
    p_event_id uuid,
    p_posting_code text,
    p_event_date date,
    p_created_for_programme_code text,
    p_teaching_name_id uuid,
    p_source_programme_code text,
    p_source_reporting_period_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.current_subject_type() = 'resident'
       AND p_created_for_programme_code IS NULL
       AND p_teaching_name_id IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM public.residents AS resident
           JOIN public.resident_postings AS posting
             ON posting.resident_id = resident.id
            AND posting.reporting_period_id = p_source_reporting_period_id
            AND posting.posting_code = p_posting_code
            AND posting.start_date <= p_event_date
            AND posting.end_date >= p_event_date
            AND posting.status IN ('active', 'loa_working')
           JOIN public.teaching_names AS name
             ON name.id = p_teaching_name_id
            AND name.reporting_period_id = p_source_reporting_period_id
            AND name.programme_code = p_source_programme_code
            AND name.created_by_role = 'secretary'
            AND name.visibility_scope = 'department_shared'
            AND name.origin_posting_code = p_posting_code
           JOIN public.teaching_name_programme_scopes AS scope
             ON scope.teaching_name_id = name.id
            AND scope.reporting_period_id = name.reporting_period_id
            AND scope.programme_code = resident.programme_code
           JOIN public.teaching_name_mappings AS mapping
             ON mapping.teaching_name_id = name.id
            AND mapping.reporting_period_id = name.reporting_period_id
            AND mapping.programme_code = resident.programme_code
            AND mapping.posting_code = posting.posting_code
            AND mapping.r_year = posting.r_year
           WHERE resident.id = mata_rls.current_subject_id()
             AND resident.status = 'active'
             AND resident.programme_code IS NOT NULL
             AND resident.programme_code <> p_source_programme_code
       )
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
mata_private.can_select_cross_programme_secretary_event(
    uuid,text,date,text,uuid,text,uuid
) FROM PUBLIC, mata_app_runtime, mata_auth_internal;

CREATE OR REPLACE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE((
        SELECT mata_rls.can_select_teaching_event_row(
            event.id, event.is_adhoc, event.posting_code, event.event_date,
            event.created_for_programme_code, event.created_by_role,
            event.created_by_resident_id,
            event.created_by_external_resident_id,
            event.teaching_name_id, event.global_session_type_id,
            event.source_programme_code, event.source_reporting_period_id
        ) OR mata_private.can_select_cross_programme_secretary_event(
            event.id, event.posting_code, event.event_date,
            event.created_for_programme_code, event.teaching_name_id,
            event.source_programme_code, event.source_reporting_period_id
        )
        FROM public.teaching_events AS event
        WHERE event.id = p_event_id
    ), false)
$function$;
"""
    )
    _secure_runtime_function("can_select_teaching_event(uuid)")

    _execute(
        r"""
CREATE FUNCTION mata_rls.resolve_native_teaching_target_v2(
    p_resident_id uuid,
    p_event_id uuid
)
RETURNS TABLE(
    outcome text, unavailable_reason text, event_id uuid,
    reporting_period_id uuid, programme_code text, posting_code text,
    r_year text, global_session_type_id uuid, teaching_name_id uuid,
    mapping_id uuid, mapping_revision integer, teaching_target_id uuid,
    session_type_id uuid
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_existing record;
    v_event record;
    v_resident_programme text;
    v_phase record;
    v_mapping record;
    v_target record;
BEGIN
    SELECT * INTO v_existing
    FROM mata_rls.resolve_native_teaching_target(p_resident_id, p_event_id);

    IF v_existing.outcome IS NULL AND v_existing.unavailable_reason IS NULL THEN
        RETURN;
    END IF;

    IF v_existing.outcome IS NOT NULL
       OR v_existing.unavailable_reason IS DISTINCT FROM 'source_programme_mismatch'
    THEN
        RETURN QUERY SELECT
            v_existing.outcome, v_existing.unavailable_reason,
            v_existing.event_id, v_existing.reporting_period_id,
            v_existing.programme_code, v_existing.posting_code,
            v_existing.r_year, v_existing.global_session_type_id,
            v_existing.teaching_name_id, v_existing.mapping_id,
            v_existing.mapping_revision, v_existing.teaching_target_id,
            v_existing.session_type_id;
        RETURN;
    END IF;

    SELECT event.* INTO v_event
    FROM public.teaching_events AS event
    WHERE event.id = p_event_id
      AND mata_rls.can_select_teaching_event(event.id);
    IF NOT FOUND OR v_event.created_for_programme_code IS NOT NULL THEN
        RETURN QUERY SELECT
            NULL::text, 'source_programme_mismatch', p_event_id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT resident.programme_code INTO v_resident_programme
    FROM public.residents AS resident
    WHERE resident.id = p_resident_id;

    SELECT posting.reporting_period_id, posting.posting_code, posting.r_year
    INTO v_phase
    FROM public.resident_postings AS posting
    WHERE posting.resident_id = p_resident_id
      AND posting.reporting_period_id = v_event.source_reporting_period_id
      AND posting.posting_code = v_event.posting_code
      AND posting.start_date <= v_event.event_date
      AND posting.end_date >= v_event.event_date
      AND posting.status IN ('active', 'loa_working');
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'native_phase_unavailable', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT mapping.id, mapping.revision, mapping.teaching_target_id
    INTO v_mapping
    FROM public.teaching_name_mappings AS mapping
    JOIN public.teaching_name_programme_scopes AS scope
      ON scope.teaching_name_id = mapping.teaching_name_id
     AND scope.reporting_period_id = mapping.reporting_period_id
     AND scope.programme_code = mapping.programme_code
    WHERE mapping.teaching_name_id = v_event.teaching_name_id
      AND mapping.reporting_period_id = v_phase.reporting_period_id
      AND mapping.programme_code = v_resident_programme
      AND mapping.posting_code = v_phase.posting_code
      AND mapping.r_year = v_phase.r_year;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'mapping_unavailable', v_event.id,
            v_phase.reporting_period_id, v_resident_programme,
            v_phase.posting_code, v_phase.r_year,
            NULL::uuid, v_event.teaching_name_id,
            NULL::uuid, NULL::integer, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_mapping.teaching_target_id IS NULL THEN
        RETURN QUERY SELECT
            'pending_mapping'::text, NULL::text, v_event.id,
            v_phase.reporting_period_id, v_resident_programme,
            v_phase.posting_code, v_phase.r_year,
            NULL::uuid, v_event.teaching_name_id,
            v_mapping.id, v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT target.id, target.session_type_id INTO v_target
    FROM public.teaching_targets AS target
    WHERE target.id = v_mapping.teaching_target_id
      AND target.reporting_period_id = v_phase.reporting_period_id
      AND target.programme_code = v_resident_programme
      AND target.posting_code = v_phase.posting_code
      AND target.r_year = v_phase.r_year;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'target_scope_mismatch', v_event.id,
            v_phase.reporting_period_id, v_resident_programme,
            v_phase.posting_code, v_phase.r_year,
            NULL::uuid, v_event.teaching_name_id,
            v_mapping.id, v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        'mapped_target'::text, NULL::text, v_event.id,
        v_phase.reporting_period_id, v_resident_programme,
        v_phase.posting_code, v_phase.r_year,
        NULL::uuid, v_event.teaching_name_id,
        v_mapping.id, v_mapping.revision, v_target.id,
        v_target.session_type_id;
END
$function$;
"""
    )
    _secure_runtime_function("resolve_native_teaching_target_v2(uuid,uuid)")

    _execute(
        r"""
DROP FUNCTION mata_rls.resolve_staff_pool_event_timings(uuid[],uuid,text,text);
CREATE FUNCTION mata_rls.resolve_staff_pool_event_timings(
    p_teaching_name_ids uuid[],
    p_reporting_period_id uuid,
    p_programme_code text,
    p_posting_code text
)
RETURNS TABLE(
    teaching_name_id uuid, programme_code text, posting_code text, r_year text,
    teaching_target_id uuid, session_type_id uuid,
    session_type_name text, duration_hours numeric
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF p_teaching_name_ids IS NULL
       OR cardinality(p_teaching_name_ids) = 0
       OR cardinality(p_teaching_name_ids) > 500
       OR p_reporting_period_id IS NULL
    THEN
        RETURN;
    END IF;

    IF mata_rls.is_master_admin() THEN
        NULL;
    ELSIF p_programme_code IS NOT NULL
       AND mata_rls.has_programme_scope(p_programme_code)
    THEN
        NULL;
    ELSIF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'secretary'
       AND p_posting_code IS NOT NULL
       AND mata_rls.is_secretary_for_posting(p_posting_code)
       AND NOT EXISTS (
           SELECT 1
           FROM unnest(p_teaching_name_ids) AS requested(id)
           JOIN public.teaching_names AS name ON name.id = requested.id
           WHERE name.reporting_period_id <> p_reporting_period_id
              OR (
                  name.origin_posting_code <> p_posting_code
                  AND NOT (
                      name.visibility_scope = 'programme_private'
                      AND EXISTS (
                          SELECT 1
                          FROM public.programmes AS programme
                          WHERE programme.code = name.programme_code
                            AND programme.native_teaching_posting_code
                                = p_posting_code
                      )
                  )
              )
       )
    THEN
        NULL;
    ELSE
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        mapping.teaching_name_id,
        mapping.programme_code::text,
        mapping.posting_code::text,
        mapping.r_year::text,
        mapping.teaching_target_id,
        target.session_type_id,
        session_type.name::text,
        session_type.duration_hours
    FROM public.teaching_name_mappings AS mapping
    JOIN public.teaching_names AS name
      ON name.id = mapping.teaching_name_id
    LEFT JOIN public.teaching_targets AS target
      ON target.id = mapping.teaching_target_id
    LEFT JOIN public.session_types AS session_type
      ON session_type.id = target.session_type_id
    WHERE mapping.teaching_name_id = ANY(p_teaching_name_ids)
      AND mapping.reporting_period_id = p_reporting_period_id
      AND (p_programme_code IS NULL
           OR mapping.programme_code = p_programme_code)
      AND (p_posting_code IS NULL OR mapping.posting_code = p_posting_code)
    ORDER BY mapping.teaching_name_id, mapping.programme_code, mapping.r_year;
END
$function$;
"""
    )
    _secure_runtime_function(
        "resolve_staff_pool_event_timings(uuid[],uuid,text,text)"
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.sync_secretary_pool_event_timing(
    p_teaching_name_id uuid,
    p_reporting_period_id uuid,
    p_mapping_programme_code text,
    p_posting_code text
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_duration numeric := 1.00;
    v_updated integer := 0;
BEGIN
    IF NOT mata_rls.context_is_valid()
       OR NOT (
           mata_rls.is_master_admin()
           OR mata_rls.has_programme_scope(p_mapping_programme_code)
       )
       OR NOT EXISTS (
           SELECT 1
           FROM public.teaching_name_mappings AS mapping
           WHERE mapping.teaching_name_id = p_teaching_name_id
             AND mapping.reporting_period_id = p_reporting_period_id
             AND mapping.programme_code = p_mapping_programme_code
             AND mapping.posting_code = p_posting_code
       )
    THEN
        RAISE EXCEPTION 'Teaching Name mapping scope required'
            USING ERRCODE = '42501';
    END IF;

    SELECT COALESCE(
        max(COALESCE(session_type.duration_hours, 1.00)),
        1.00
    )
    INTO v_duration
    FROM public.teaching_name_mappings AS mapping
    LEFT JOIN public.teaching_targets AS target
      ON target.id = mapping.teaching_target_id
    LEFT JOIN public.session_types AS session_type
      ON session_type.id = target.session_type_id
    WHERE mapping.teaching_name_id = p_teaching_name_id
      AND mapping.reporting_period_id = p_reporting_period_id
      AND mapping.posting_code = p_posting_code;

    UPDATE public.teaching_events AS event
    SET duration_hours = v_duration,
        end_time = (
            event.start_time
            + make_interval(secs => (v_duration * 3600)::integer)
        )::time,
        updated_at = clock_timestamp()
    WHERE event.teaching_name_id = p_teaching_name_id
      AND event.source_reporting_period_id = p_reporting_period_id
      AND event.posting_code = p_posting_code
      AND event.created_for_programme_code IS NULL
      AND event.global_session_type_id IS NULL
      AND event.is_adhoc = false
      AND (
          event.duration_hours IS DISTINCT FROM v_duration
          OR event.end_time IS DISTINCT FROM (
              event.start_time
              + make_interval(secs => (v_duration * 3600)::integer)
          )::time
      );
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated;
END
$function$;
"""
    )
    _secure_runtime_function(
        "sync_secretary_pool_event_timing(uuid,uuid,text,text)"
    )

    _execute(
        r"""
DO $migration$
DECLARE optional_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[
        'anon', 'authenticated', 'service_role'
    ] LOOP
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = optional_role
        ) THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON TABLE '
                'public.teaching_name_programme_scopes FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_rls.reconcile_teaching_name_programme_scopes(uuid,text) '
                'FROM %I', optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_rls.sync_secretary_pool_event_timing(uuid,uuid,text,text) '
                'FROM %I', optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_rls.resolve_native_teaching_target_v2(uuid,uuid) '
                'FROM %I', optional_role
            );
        END IF;
    END LOOP;
END
$migration$;
"""
    )


def downgrade() -> None:
    _execute(
        r"""
DO $migration$
BEGIN
    RAISE EXCEPTION
        'Phase V downgrade is intentionally unsupported because it would discard programme admissions and mapping identity';
END
$migration$;
"""
    )
