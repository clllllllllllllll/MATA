from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


def _validate_programme_filter(
    *,
    programme_scope: set[str],
    programme_code: str | None,
) -> None:
    if programme_code is None:
        return
    if not programme_scope or programme_code not in programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _scoped_programmes(
    *,
    programme_scope: set[str],
    programme_code: str | None,
) -> list[str]:
    _validate_programme_filter(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if programme_code is not None:
        return [programme_code]
    return sorted(programme_scope)


def _scope_or_clause(
    *,
    field_name: str,
    values: list[str],
    params: dict[str, Any],
    param_prefix: str,
) -> str:
    fragments: list[str] = []
    for idx, value in enumerate(values):
        key = f"{param_prefix}_{idx}"
        params[key] = value
        fragments.append(f"{field_name} = :{key}")
    return "(" + " OR ".join(fragments) + ")"


async def list_reporting_periods(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("id = :reporting_period_id")

    sql = """
        SELECT id, label, start_date, end_date, status, created_at, updated_at
        FROM reporting_periods
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY start_date DESC, label ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_public_holidays(
    db: AsyncSession,
    *,
    year: int | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if year is not None:
        params["year"] = year
        where_clauses.append("year = :year")

    sql = """
        SELECT id, holiday_date, name, day_of_week, year, created_at, updated_at
        FROM public_holidays
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY holiday_date ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_programmes(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {}
    scope_clause = _scope_or_clause(
        field_name="code",
        values=codes,
        params=params,
        param_prefix="programme_code",
    )
    sql = f"""
        SELECT
            id,
            code,
            name,
            classification,
            ay_date_category,
            r_year_required,
            is_subspecialty,
            rdb_alias,
            created_at,
            updated_at
        FROM programmes
        WHERE {scope_clause}
        ORDER BY code ASC
    """
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_loa_types(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT id, code, description, created_at, updated_at
            FROM loa_types
            ORDER BY code ASC
            """
        )
    )
    return list(result.mappings().all())


async def list_multi_posting_rules(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None,
    rule_type: str | None,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {}
    where_clauses: list[str] = [
        _scope_or_clause(
            field_name="programme_code",
            values=codes,
            params=params,
            param_prefix="programme_code",
        )
    ]
    if rule_type is not None:
        params["rule_type"] = rule_type
        where_clauses.append("rule_type = :rule_type")

    sql = """
        SELECT
            id,
            programme_code,
            posting_code_1,
            posting_code_2,
            rule_type,
            combined_label,
            main_posting_code,
            exclusion_code,
            created_at,
            updated_at
        FROM multi_posting_rules
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += " ORDER BY programme_code ASC, rule_type ASC, posting_code_1 ASC, posting_code_2 ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_posting_groups(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None,
    group_code: str | None,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {}
    where_clauses: list[str] = [
        _scope_or_clause(
            field_name="programme_code",
            values=codes,
            params=params,
            param_prefix="programme_code",
        )
    ]
    if group_code is not None:
        params["group_code"] = group_code
        where_clauses.append("group_code = :group_code")

    sql = """
        SELECT id, group_code, posting_code, programme_code, created_at, updated_at
        FROM posting_groups
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += " ORDER BY programme_code ASC, group_code ASC, posting_code ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_weekend_exceptions(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None,
    posting_code: str | None,
) -> list[dict[str, Any]]:
    _validate_programme_filter(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if programme_code is None and not programme_scope:
        return []
    params: dict[str, Any] = {}
    where_clauses: list[str] = []

    if programme_code is not None:
        params["programme_code"] = programme_code
        where_clauses.append("programme_code = :programme_code")
    elif programme_scope:
        scoped_codes = sorted(programme_scope)
        scope_clause = _scope_or_clause(
            field_name="programme_code",
            values=scoped_codes,
            params=params,
            param_prefix="programme_code",
        )
        where_clauses.append(f"(programme_code IS NULL OR {scope_clause})")
    if posting_code is not None:
        params["posting_code"] = posting_code
        where_clauses.append("posting_code = :posting_code")

    sql = """
        SELECT
            id,
            programme_code,
            posting_code,
            day_type,
            start_time_min,
            end_time_max,
            session_type_id,
            session_name_pattern,
            mutates_to_session_type_id,
            adjusted_duration_hours,
            created_at,
            updated_at
        FROM weekend_exceptions
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY programme_code ASC NULLS FIRST, posting_code ASC NULLS FIRST, day_type ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_global_session_types(
    db: AsyncSession,
    *,
    is_active: bool | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if is_active is not None:
        params["is_active"] = is_active
        where_clauses.append("is_active = :is_active")

    sql = """
        SELECT id, name, duration_hours, is_active, created_at, updated_at
        FROM global_session_types
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY name ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_upload_logs(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    upload_type: str | None,
    programme_code: str | None,
    reporting_period_id: UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    _validate_programme_filter(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if programme_code is None and not programme_scope:
        return []
    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = []

    if upload_type is not None:
        params["upload_type"] = upload_type
        where_clauses.append("upload_type = :upload_type")
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("reporting_period_id = :reporting_period_id")

    if programme_code is not None:
        params["programme_code"] = programme_code
        where_clauses.append("programme_code = :programme_code")
    elif programme_scope:
        scoped_codes = sorted(programme_scope)
        scope_clause = _scope_or_clause(
            field_name="programme_code",
            values=scoped_codes,
            params=params,
            param_prefix="programme_code",
        )
        where_clauses.append(f"(programme_code IS NULL OR {scope_clause})")
    sql = """
        SELECT
            id,
            upload_type,
            uploaded_by,
            uploaded_at,
            reporting_period_id,
            programme_code,
            status,
            summary,
            created_at,
            updated_at
        FROM upload_logs
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY uploaded_at DESC LIMIT :limit"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_form_f1_records(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    reporting_period_id: UUID | None,
    programme_code: str | None,
    mcr: str | None,
    month_label: str | None,
    is_active: bool | None,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {}
    where_clauses: list[str] = [
        _scope_or_clause(
            field_name="r.programme_code",
            values=codes,
            params=params,
            param_prefix="programme_code",
        )
    ]
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("f.reporting_period_id = :reporting_period_id")
    if mcr is not None:
        params["mcr"] = mcr.strip().upper()
        where_clauses.append("UPPER(f.mcr) = :mcr")
    if month_label is not None:
        params["month_label"] = month_label
        where_clauses.append("f.month_label = :month_label")
    if is_active is not None:
        params["is_active"] = is_active
        where_clauses.append("f.is_active = :is_active")

    sql = """
        SELECT
            f.id,
            f.reporting_period_id,
            f.mcr,
            f.month_label,
            f.status_raw,
            f.is_active,
            f.promotion_date,
            f.upload_id,
            f.created_at,
            f.updated_at
        FROM form_f1_records f
        JOIN residents r ON UPPER(r.mcr) = UPPER(f.mcr)
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += " ORDER BY f.mcr ASC, f.month_label ASC"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())
