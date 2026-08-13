from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database_context import session_uses_rls


async def reconcile_teaching_name_programme_scopes(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
    programme_code: str,
) -> dict[str, int]:
    """Add durable source admissions and exact pending mappings.

    ``programme_code`` is both a bounded source-owner and mapping-programme
    reconciliation hint.  The SQL remains data-derived: it cannot create a
    cross-programme admission without an actual usable Resident posting in the
    same reporting period.
    """

    params: dict[str, Any] = {
        "reporting_period_id": str(reporting_period_id),
        "programme_code": programme_code.strip().upper(),
    }
    if session_uses_rls(db):
        result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.reconcile_teaching_name_programme_scopes(
                    CAST(:reporting_period_id AS uuid),
                    CAST(:programme_code AS text)
                )
                """
            ),
            params,
        )
        row = result.mappings().one()
        return {
            "programme_scopes_created": int(row["programme_scopes_created"] or 0),
            "pending_mappings_created": int(row["pending_mappings_created"] or 0),
        }

    owner_result = await db.execute(
        text(
            """
            /* teaching_name_scopes:admit_owner */
            INSERT INTO teaching_name_programme_scopes (
                teaching_name_id,
                reporting_period_id,
                programme_code,
                admission_reason,
                admitted_by_user_id
            )
            SELECT
                name.id,
                name.reporting_period_id,
                name.programme_code,
                CASE
                    WHEN name.visibility_scope = 'programme_private'
                    THEN 'pc_private'
                    ELSE 'owner_programme'
                END,
                name.created_by_user_id
            FROM teaching_names AS name
            WHERE name.reporting_period_id = :reporting_period_id
              AND name.programme_code = :programme_code
            ON CONFLICT (teaching_name_id, programme_code) DO NOTHING
            """
        ),
        params,
    )
    cross_result = await db.execute(
        text(
            """
            /* teaching_name_scopes:admit_resident_host */
            INSERT INTO teaching_name_programme_scopes (
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
            FROM teaching_names AS name
            JOIN resident_postings AS posting
              ON posting.reporting_period_id = name.reporting_period_id
             AND posting.posting_code = name.origin_posting_code
             AND posting.status IN ('active', 'loa_working')
            JOIN residents AS resident
              ON resident.id = posting.resident_id
             AND resident.programme_code IS NOT NULL
            WHERE name.reporting_period_id = :reporting_period_id
              AND name.created_by_role = 'secretary'
              AND name.visibility_scope = 'department_shared'
              AND (
                  name.programme_code = :programme_code
                  OR resident.programme_code = :programme_code
              )
            ON CONFLICT (teaching_name_id, programme_code) DO NOTHING
            """
        ),
        params,
    )
    mapping_result = await db.execute(
        text(
            """
            /* teaching_name_scopes:provision_mappings */
            INSERT INTO teaching_name_mappings (
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
                CAST(NULL AS uuid)
            FROM teaching_name_programme_scopes AS scope
            JOIN teaching_names AS name
              ON name.id = scope.teaching_name_id
             AND name.reporting_period_id = scope.reporting_period_id
            JOIN teaching_targets AS target
              ON target.reporting_period_id = scope.reporting_period_id
             AND target.programme_code = scope.programme_code
             AND (
                 scope.admission_reason <> 'resident_host_posting'
                 OR target.posting_code = name.origin_posting_code
             )
            WHERE scope.reporting_period_id = :reporting_period_id
              AND name.is_active
              AND (
                  name.programme_code = :programme_code
                  OR scope.programme_code = :programme_code
              )
            ON CONFLICT (
                teaching_name_id,
                programme_code,
                posting_code,
                r_year
            ) DO NOTHING
            """
        ),
        params,
    )
    return {
        "programme_scopes_created": max(int(owner_result.rowcount or 0), 0)
        + max(int(cross_result.rowcount or 0), 0),
        "pending_mappings_created": max(int(mapping_result.rowcount or 0), 0),
    }
