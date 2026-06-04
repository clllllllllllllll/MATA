from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.cache import cache


ALLOWED_MULTI_POSTING_RULE_TYPES = {"main_posting", "combine", "half_month"}


def _invalidate_admin_config_cache() -> None:
    # TODO(master-admin): cache keys can be tightened once explicit master-admin claims are added.
    cache.invalidate_prefix("admin_config")


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
    programme_scope: set[str],
    reporting_period_id: UUID | None,
) -> list[dict[str, Any]]:
    if not programme_scope:
        return []
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


async def list_residents(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None,
    mcr: str | None,
    name: str | None,
    status: str | None,
    employer_tag: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = [
        _scope_or_clause(
            field_name="programme_code",
            values=codes,
            params=params,
            param_prefix="programme_code",
        )
    ]
    if mcr is not None:
        params["mcr"] = mcr.strip().upper()
        where_clauses.append("UPPER(mcr) = :mcr")
    if name is not None:
        params["name"] = f"%{name.strip()}%"
        where_clauses.append("name ILIKE :name")
    if status is not None:
        params["status"] = status.strip().lower()
        where_clauses.append("LOWER(status) = :status")
    if employer_tag is not None:
        params["employer_tag"] = employer_tag.strip().upper()
        where_clauses.append("UPPER(employer_tag) = :employer_tag")

    sql = """
        SELECT
            id,
            employee_code,
            name,
            mcr,
            classification,
            programme_code,
            r_year,
            reg_type,
            base_institution,
            email,
            phone,
            status,
            employer_tag,
            created_at,
            updated_at
        FROM residents
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += " ORDER BY programme_code ASC, mcr ASC, id ASC LIMIT :limit"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def get_resident_by_id(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    resident_id: UUID,
) -> dict[str, Any]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=None,
    )
    if not codes:
        _raise_not_found("Resident not found")

    params: dict[str, Any] = {"resident_id": str(resident_id)}
    scope_clause = _scope_or_clause(
        field_name="programme_code",
        values=codes,
        params=params,
        param_prefix="programme_code",
    )
    sql = f"""
        SELECT
            id,
            employee_code,
            name,
            mcr,
            classification,
            programme_code,
            r_year,
            reg_type,
            base_institution,
            email,
            phone,
            status,
            employer_tag,
            created_at,
            updated_at
        FROM residents
        WHERE id = :resident_id AND {scope_clause}
    """
    result = await db.execute(text(sql), params)
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found("Resident not found")
    return dict(row)


async def list_resident_postings(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    reporting_period_id: UUID | None,
    programme_code: str | None,
    posting_code: str | None,
    mcr: str | None,
    resident_id: UUID | None,
    month_label: str | None,
    r_year: str | None,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {"limit": limit}
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
        where_clauses.append("rp.reporting_period_id = :reporting_period_id")
    if posting_code is not None:
        params["posting_code"] = posting_code.strip()
        where_clauses.append("rp.posting_code = :posting_code")
    if mcr is not None:
        params["mcr"] = mcr.strip().upper()
        where_clauses.append("UPPER(r.mcr) = :mcr")
    if resident_id is not None:
        params["resident_id"] = str(resident_id)
        where_clauses.append("rp.resident_id = :resident_id")
    if month_label is not None:
        params["month_label"] = month_label.strip()
        where_clauses.append("rp.month_label = :month_label")
    if r_year is not None:
        params["r_year"] = r_year.strip().upper()
        where_clauses.append("UPPER(rp.r_year) = :r_year")
    if status is not None:
        params["status"] = status.strip().lower()
        where_clauses.append("LOWER(rp.status) = :status")

    sql = """
        SELECT
            rp.id,
            rp.resident_id,
            rp.posting_code,
            rp.reporting_period_id,
            rp.start_date,
            rp.end_date,
            rp.day_part,
            rp.month_label,
            rp.r_year,
            rp.status,
            rp.loa_type,
            rp.loa_start_date,
            rp.loa_end_date,
            rp.refresher_training_type,
            rp.refresher_training_start,
            rp.refresher_training_end,
            rp.active_months_weight,
            rp.working_days_in_month,
            rp.created_at,
            rp.updated_at,
            r.mcr AS resident_mcr,
            r.name AS resident_name,
            r.programme_code AS resident_programme_code
        FROM resident_postings rp
        JOIN residents r ON r.id = rp.resident_id
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += """
        ORDER BY
            rp.reporting_period_id ASC,
            r.mcr ASC,
            rp.start_date ASC,
            rp.day_part ASC NULLS FIRST,
            rp.id ASC
        LIMIT :limit
    """
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_posting_codes(
    db: AsyncSession,
    *,
    code: str | None,
    institution: str | None,
    department: str | None,
    is_emergency: bool | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = []
    if code is not None:
        params["code"] = f"%{code.strip()}%"
        where_clauses.append("code ILIKE :code")
    if institution is not None:
        params["institution"] = f"%{institution.strip()}%"
        where_clauses.append("institution ILIKE :institution")
    if department is not None:
        params["department"] = f"%{department.strip()}%"
        where_clauses.append("department ILIKE :department")
    if is_emergency is not None:
        params["is_emergency"] = is_emergency
        where_clauses.append("is_emergency = :is_emergency")

    sql = """
        SELECT
            id,
            code,
            display_name,
            institution,
            department,
            billing_dept,
            is_emergency,
            created_at,
            updated_at
        FROM posting_codes
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY code ASC, id ASC LIMIT :limit"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_session_types(
    db: AsyncSession,
    *,
    name: str | None,
    duration_hours: Decimal | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = []
    if name is not None:
        params["name"] = f"%{name.strip()}%"
        where_clauses.append("name ILIKE :name")
    if duration_hours is not None:
        params["duration_hours"] = duration_hours
        where_clauses.append("duration_hours = :duration_hours")

    sql = """
        SELECT id, name, duration_hours, duration_label, created_at, updated_at
        FROM session_types
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY name ASC, id ASC LIMIT :limit"
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_teaching_targets(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    reporting_period_id: UUID | None,
    programme_code: str | None,
    posting_code: str | None,
    r_year: str | None,
    session_type_id: UUID | None,
    is_tracked: bool | None,
    limit: int,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = [
        _scope_or_clause(
            field_name="programme_code",
            values=codes,
            params=params,
            param_prefix="programme_code",
        )
    ]
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("reporting_period_id = :reporting_period_id")
    if posting_code is not None:
        params["posting_code"] = posting_code.strip()
        where_clauses.append("posting_code = :posting_code")
    if r_year is not None:
        params["r_year"] = r_year.strip().upper()
        where_clauses.append("UPPER(r_year) = :r_year")
    if session_type_id is not None:
        params["session_type_id"] = str(session_type_id)
        where_clauses.append("session_type_id = :session_type_id")
    if is_tracked is not None:
        params["is_tracked"] = is_tracked
        where_clauses.append("is_tracked = :is_tracked")

    sql = """
        SELECT
            id,
            reporting_period_id,
            programme_code,
            r_year,
            posting_code,
            session_type_id,
            monthly_target,
            is_tracked,
            is_reallocatable,
            tag,
            details_of_training,
            created_at,
            updated_at
        FROM teaching_targets
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += """
        ORDER BY
            reporting_period_id ASC,
            programme_code ASC,
            posting_code ASC,
            r_year ASC,
            session_type_id ASC,
            id ASC
        LIMIT :limit
    """
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_teaching_name_catalogue(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    reporting_period_id: UUID | None,
    programme_code: str | None,
    posting_code: str | None,
    r_year: str | None,
    keyword: str | None,
    session_type_id: UUID | None,
    is_tracked: bool | None,
    limit: int,
) -> list[dict[str, Any]]:
    codes = _scoped_programmes(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not codes:
        return []

    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = [
        _scope_or_clause(
            field_name="programme_code",
            values=codes,
            params=params,
            param_prefix="programme_code",
        )
    ]
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("reporting_period_id = :reporting_period_id")
    if posting_code is not None:
        params["posting_code"] = posting_code.strip()
        where_clauses.append("posting_code = :posting_code")
    if r_year is not None:
        params["r_year"] = r_year.strip().upper()
        where_clauses.append("UPPER(r_year) = :r_year")
    if keyword is not None:
        params["keyword"] = f"%{keyword.strip()}%"
        where_clauses.append("keyword ILIKE :keyword")
    if session_type_id is not None:
        params["session_type_id"] = str(session_type_id)
        where_clauses.append("session_type_id = :session_type_id")
    if is_tracked is not None:
        params["is_tracked"] = is_tracked
        where_clauses.append("is_tracked = :is_tracked")

    sql = """
        SELECT
            id,
            keyword,
            session_type_id,
            posting_code,
            programme_code,
            r_year,
            reporting_period_id,
            duration_hours,
            is_tracked,
            created_at,
            updated_at
        FROM teaching_name_catalogue
        WHERE
    """
    sql += " AND ".join(where_clauses)
    sql += """
        ORDER BY
            reporting_period_id ASC,
            programme_code ASC,
            posting_code ASC,
            r_year ASC,
            keyword ASC,
            id ASC
        LIMIT :limit
    """
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


async def list_academic_month_boundaries(
    db: AsyncSession,
    *,
    ay_date_category: str | None,
    month_label: str | None,
    date_from: date | None,
    date_to: date | None,
    upload_id: UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where_clauses: list[str] = []
    if ay_date_category is not None:
        params["ay_date_category"] = ay_date_category.strip().lower()
        where_clauses.append("ay_date_category = :ay_date_category")
    if month_label is not None:
        params["month_label"] = month_label.strip()
        where_clauses.append("month_label = :month_label")
    if date_from is not None:
        params["date_from"] = date_from
        where_clauses.append("end_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where_clauses.append("start_date <= :date_to")
    if upload_id is not None:
        params["upload_id"] = str(upload_id)
        where_clauses.append("upload_id = :upload_id")

    sql = """
        SELECT
            id,
            academic_year_label,
            ay_date_category,
            month_label,
            start_date,
            end_date,
            upload_id,
            created_at,
            updated_at
        FROM academic_month_boundaries
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += """
        ORDER BY
            academic_year_label ASC,
            ay_date_category ASC,
            start_date ASC,
            id ASC
        LIMIT :limit
    """
    result = await db.execute(text(sql), params)
    return list(result.mappings().all())


def _validate_programme_scope_for_write(programme_scope: set[str]) -> None:
    # TODO(master-admin): introduce an explicit master-admin claim/flag.
    # Do not infer master-admin from empty/null programme_scope.
    if not programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _require_programme_in_scope_for_write(
    *,
    programme_scope: set[str],
    programme_code: str | None,
) -> None:
    _validate_programme_scope_for_write(programme_scope)
    if not programme_code or programme_code not in programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _normalise_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _posting_code_exists(db: AsyncSession, code: str | None) -> bool:
    if code is None:
        return True
    result = await db.execute(
        text("SELECT 1 FROM posting_codes WHERE code = :code LIMIT 1"),
        {"code": code},
    )
    return result.scalar_one_or_none() is not None


async def _session_type_exists(db: AsyncSession, session_type_id: UUID | None) -> bool:
    if session_type_id is None:
        return True
    result = await db.execute(
        text("SELECT 1 FROM session_types WHERE id = :session_type_id LIMIT 1"),
        {"session_type_id": str(session_type_id)},
    )
    return result.scalar_one_or_none() is not None


def _raise_not_found(detail: str) -> None:
    raise ApiError(
        status_code=404,
        detail=detail,
        error_code=ErrorCode.NOT_FOUND.value,
    )


def _raise_conflict(detail: str) -> None:
    raise ApiError(
        status_code=409,
        detail=detail,
        error_code=ErrorCode.CONFLICT.value,
    )


def _raise_validation(detail: str) -> None:
    raise ApiError(
        status_code=422,
        detail=detail,
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


def _raise_dependency_conflict(dependencies: dict[str, int]) -> None:
    raise ApiError(
        status_code=409,
        detail="Reporting period is in use and cannot be deleted",
        error_code=ErrorCode.CONFLICT.value,
        metadata={"dependencies": dependencies},
    )


async def create_reporting_period(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    label: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    _validate_programme_scope_for_write(programme_scope)
    if start_date > end_date:
        _raise_validation("start_date must be on or before end_date")
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO reporting_periods (label, start_date, end_date)
                VALUES (:label, :start_date, :end_date)
                RETURNING id, label, start_date, end_date, status, created_at, updated_at
                """
            ),
            {
                "label": label,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_conflict("Reporting period already exists")
    row = result.mappings().one()
    _invalidate_admin_config_cache()
    return dict(row)


async def update_reporting_period(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    reporting_period_id: UUID,
    label: str | None,
    start_date: date | None,
    end_date: date | None,
    status: str | None,
) -> dict[str, Any]:
    _validate_programme_scope_for_write(programme_scope)
    existing = await db.execute(
        text(
            """
            SELECT id, label, start_date, end_date, status, created_at, updated_at
            FROM reporting_periods
            WHERE id = :id
            """
        ),
        {"id": str(reporting_period_id)},
    )
    current = existing.mappings().one_or_none()
    if current is None:
        _raise_not_found("Reporting period not found")

    resolved_start = start_date if start_date is not None else current["start_date"]
    resolved_end = end_date if end_date is not None else current["end_date"]
    if resolved_start > resolved_end:
        _raise_validation("start_date must be on or before end_date")

    try:
        result = await db.execute(
            text(
                """
                UPDATE reporting_periods
                SET
                    label = COALESCE(:label, label),
                    start_date = COALESCE(:start_date, start_date),
                    end_date = COALESCE(:end_date, end_date),
                    status = COALESCE(:status, status),
                    updated_at = now()
                WHERE id = :id
                RETURNING id, label, start_date, end_date, status, created_at, updated_at
                """
            ),
            {
                "id": str(reporting_period_id),
                "label": label,
                "start_date": start_date,
                "end_date": end_date,
                "status": status,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Reporting period already exists")

    row = result.mappings().one()
    _invalidate_admin_config_cache()
    return dict(row)


async def delete_reporting_period(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    reporting_period_id: UUID,
) -> None:
    _validate_programme_scope_for_write(programme_scope)
    existing = await db.execute(
        text("SELECT id FROM reporting_periods WHERE id = :id"),
        {"id": str(reporting_period_id)},
    )
    if existing.mappings().one_or_none() is None:
        _raise_not_found("Reporting period not found")

    dependencies = await _reporting_period_dependency_counts(
        db,
        reporting_period_id=reporting_period_id,
    )
    blocking_dependencies = {
        table_name: count for table_name, count in dependencies.items() if count > 0
    }
    if blocking_dependencies:
        _raise_dependency_conflict(blocking_dependencies)

    try:
        result = await db.execute(
            text("DELETE FROM reporting_periods WHERE id = :id"),
            {"id": str(reporting_period_id)},
        )
        if result.rowcount == 0:
            await db.rollback()
            _raise_not_found("Reporting period not found")
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Reporting period is in use and cannot be deleted")
    _invalidate_admin_config_cache()


async def _count_reporting_period_dependency(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
    sql: str,
) -> int:
    result = await db.execute(text(sql), {"id": str(reporting_period_id)})
    row = result.mappings().one()
    return int(row["count"] or 0)


async def _reporting_period_dependency_counts(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
) -> dict[str, int]:
    checks = {
        "upload_logs": """
            SELECT COUNT(*) AS count
            FROM upload_logs
            WHERE reporting_period_id = :id
        """,
        "resident_postings": """
            SELECT COUNT(*) AS count
            FROM resident_postings
            WHERE reporting_period_id = :id
        """,
        "teaching_targets": """
            SELECT COUNT(*) AS count
            FROM teaching_targets
            WHERE reporting_period_id = :id
        """,
        "teaching_name_catalogue": """
            SELECT COUNT(*) AS count
            FROM teaching_name_catalogue
            WHERE reporting_period_id = :id
        """,
        "form_f1_records": """
            SELECT COUNT(*) AS count
            FROM form_f1_records
            WHERE reporting_period_id = :id
        """,
        "academic_month_boundaries": """
            SELECT COUNT(*) AS count
            FROM academic_month_boundaries amb
            JOIN upload_logs ul ON ul.id = amb.upload_id
            WHERE ul.reporting_period_id = :id
        """,
        "period_snapshots": """
            SELECT COUNT(*) AS count
            FROM period_snapshots
            WHERE reporting_period_id = :id
        """,
        "clawback_records": """
            SELECT COUNT(*) AS count
            FROM clawback_records
            WHERE reporting_period_id = :id
        """,
        "surplus_ledger": """
            SELECT COUNT(*) AS count
            FROM surplus_ledger
            WHERE reporting_period_id = :id
        """,
    }
    return {
        name: await _count_reporting_period_dependency(
            db,
            reporting_period_id=reporting_period_id,
            sql=sql,
        )
        for name, sql in checks.items()
    }


async def upsert_public_holiday(
    db: AsyncSession,
    *,
    holiday_date: date,
    name: str | None,
    day_of_week: str | None,
    year: int | None,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            INSERT INTO public_holidays (holiday_date, name, day_of_week, year)
            VALUES (:holiday_date, :name, :day_of_week, :year)
            ON CONFLICT (holiday_date)
            DO UPDATE SET
                name = EXCLUDED.name,
                day_of_week = EXCLUDED.day_of_week,
                year = EXCLUDED.year,
                updated_at = now()
            RETURNING id, holiday_date, name, day_of_week, year, created_at, updated_at
            """
        ),
        {
            "holiday_date": holiday_date,
            "name": name,
            "day_of_week": day_of_week,
            "year": year,
        },
    )
    await db.commit()
    row = result.mappings().one()
    _invalidate_admin_config_cache()
    return dict(row)


async def delete_public_holiday(
    db: AsyncSession,
    *,
    holiday_id: UUID,
) -> None:
    result = await db.execute(
        text("DELETE FROM public_holidays WHERE id = :id"),
        {"id": str(holiday_id)},
    )
    if result.rowcount == 0:
        await db.rollback()
        _raise_not_found("Public holiday not found")
    await db.commit()
    _invalidate_admin_config_cache()


async def update_programme(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str,
    r_year_required: bool | None,
    is_subspecialty: bool | None,
    rdb_alias: str | None,
) -> dict[str, Any]:
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    result = await db.execute(
        text(
            """
            UPDATE programmes
            SET
                r_year_required = COALESCE(:r_year_required, r_year_required),
                is_subspecialty = COALESCE(:is_subspecialty, is_subspecialty),
                rdb_alias = CASE
                    WHEN :rdb_alias_is_set THEN :rdb_alias
                    ELSE rdb_alias
                END,
                updated_at = now()
            WHERE code = :programme_code
            RETURNING
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
            """
        ),
        {
            "programme_code": programme_code,
            "r_year_required": r_year_required,
            "is_subspecialty": is_subspecialty,
            "rdb_alias_is_set": rdb_alias is not None,
            "rdb_alias": rdb_alias,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        await db.rollback()
        _raise_not_found("Programme not found")
    await db.commit()
    _invalidate_admin_config_cache()
    return dict(row)


async def create_loa_type(
    db: AsyncSession,
    *,
    code: str,
    description: str | None,
) -> dict[str, Any]:
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO loa_types (code, description)
                VALUES (:code, :description)
                RETURNING id, code, description, created_at, updated_at
                """
            ),
            {"code": code, "description": description},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("LOA type already exists")
    row = result.mappings().one()
    _invalidate_admin_config_cache()
    return dict(row)


async def update_loa_type(
    db: AsyncSession,
    *,
    loa_type_id: UUID,
    code: str | None,
    description: str | None,
) -> dict[str, Any]:
    try:
        result = await db.execute(
            text(
                """
                UPDATE loa_types
                SET
                    code = COALESCE(:code, code),
                    description = CASE
                        WHEN :description_is_set THEN :description
                        ELSE description
                    END,
                    updated_at = now()
                WHERE id = :id
                RETURNING id, code, description, created_at, updated_at
                """
            ),
            {
                "id": str(loa_type_id),
                "code": code,
                "description_is_set": description is not None,
                "description": description,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            await db.rollback()
            _raise_not_found("LOA type not found")
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("LOA type already exists")
    _invalidate_admin_config_cache()
    return dict(row)


async def delete_loa_type(
    db: AsyncSession,
    *,
    loa_type_id: UUID,
) -> None:
    result = await db.execute(
        text("DELETE FROM loa_types WHERE id = :id"),
        {"id": str(loa_type_id)},
    )
    if result.rowcount == 0:
        await db.rollback()
        _raise_not_found("LOA type not found")
    await db.commit()
    _invalidate_admin_config_cache()


def _validate_multi_posting_rule_payload(
    *,
    rule_type: str,
    posting_code_2: str | None,
    combined_label: str | None,
    main_posting_code: str | None,
    exclusion_code: str | None,
) -> None:
    if rule_type not in ALLOWED_MULTI_POSTING_RULE_TYPES:
        _raise_validation("rule_type must be one of: main_posting, combine, half_month")
    if rule_type == "combine":
        if not posting_code_2:
            _raise_validation("combine rules require posting_code_2")
        if not combined_label:
            _raise_validation("combine rules require combined_label")
    elif rule_type == "half_month":
        if not posting_code_2:
            _raise_validation("half_month rules require posting_code_2")
        if any([combined_label, main_posting_code, exclusion_code]):
            _raise_validation("half_month rules must not set output fields")
    elif rule_type == "main_posting":
        if posting_code_2 is not None:
            _raise_validation("main_posting rules must not set posting_code_2")
        if not main_posting_code:
            _raise_validation("main_posting rules require main_posting_code")
        if combined_label is not None:
            _raise_validation("main_posting rules must not set combined_label")


async def _validate_multi_posting_codes_exist(
    db: AsyncSession,
    *,
    posting_code_1: str,
    posting_code_2: str | None,
    main_posting_code: str | None,
    exclusion_code: str | None,
) -> None:
    for posting_code in [posting_code_1, posting_code_2, main_posting_code, exclusion_code]:
        if posting_code and not await _posting_code_exists(db, posting_code):
            _raise_validation(f"Unknown posting code: {posting_code}")


async def _multi_posting_rule_conflict_exists(
    db: AsyncSession,
    *,
    programme_code: str,
    posting_code_1: str,
    posting_code_2: str | None,
    rule_type: str,
    exclude_id: UUID | None = None,
) -> bool:
    params: dict[str, Any] = {
        "programme_code": programme_code,
        "posting_code_1": posting_code_1,
        "posting_code_2": posting_code_2,
        "rule_type": rule_type,
    }
    exclusion_clause = ""
    if exclude_id is not None:
        params["exclude_id"] = str(exclude_id)
        exclusion_clause = " AND id != :exclude_id"

    result = await db.execute(
        text(
            f"""
            SELECT 1
            FROM multi_posting_rules
            WHERE programme_code = :programme_code
              AND posting_code_1 = :posting_code_1
              AND posting_code_2 IS NOT DISTINCT FROM :posting_code_2
              AND rule_type = :rule_type
              {exclusion_clause}
            LIMIT 1
            """
        ),
        params,
    )
    if result.scalar_one_or_none() is not None:
        return True

    if rule_type not in {"combine", "half_month"} or posting_code_2 is None:
        return False

    reverse_params = dict(params)
    reverse_params["posting_code_1"] = posting_code_2
    reverse_params["posting_code_2"] = posting_code_1
    reverse = await db.execute(
        text(
            f"""
            SELECT 1
            FROM multi_posting_rules
            WHERE programme_code = :programme_code
              AND posting_code_1 = :posting_code_1
              AND posting_code_2 IS NOT DISTINCT FROM :posting_code_2
              AND rule_type = :rule_type
              {exclusion_clause}
            LIMIT 1
            """
        ),
        reverse_params,
    )
    return reverse.scalar_one_or_none() is not None


async def create_multi_posting_rule(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str,
    posting_code_1: str,
    posting_code_2: str | None,
    rule_type: str,
    combined_label: str | None,
    main_posting_code: str | None,
    exclusion_code: str | None,
) -> dict[str, Any]:
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    _validate_multi_posting_rule_payload(
        rule_type=rule_type,
        posting_code_2=posting_code_2,
        combined_label=combined_label,
        main_posting_code=main_posting_code,
        exclusion_code=exclusion_code,
    )
    await _validate_multi_posting_codes_exist(
        db,
        posting_code_1=posting_code_1,
        posting_code_2=posting_code_2,
        main_posting_code=main_posting_code,
        exclusion_code=exclusion_code,
    )
    if await _multi_posting_rule_conflict_exists(
        db,
        programme_code=programme_code,
        posting_code_1=posting_code_1,
        posting_code_2=posting_code_2,
        rule_type=rule_type,
    ):
        _raise_conflict("Multi-posting rule already exists")

    try:
        result = await db.execute(
            text(
                """
                INSERT INTO multi_posting_rules (
                    programme_code,
                    posting_code_1,
                    posting_code_2,
                    rule_type,
                    combined_label,
                    main_posting_code,
                    exclusion_code
                )
                VALUES (
                    :programme_code,
                    :posting_code_1,
                    :posting_code_2,
                    :rule_type,
                    :combined_label,
                    :main_posting_code,
                    :exclusion_code
                )
                RETURNING
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
                """
            ),
            {
                "programme_code": programme_code,
                "posting_code_1": posting_code_1,
                "posting_code_2": posting_code_2,
                "rule_type": rule_type,
                "combined_label": combined_label,
                "main_posting_code": main_posting_code,
                "exclusion_code": exclusion_code,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Multi-posting rule already exists")
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def update_multi_posting_rule(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    rule_id: UUID,
    programme_code: str,
    posting_code_1: str,
    posting_code_2: str | None,
    rule_type: str,
    combined_label: str | None,
    main_posting_code: str | None,
    exclusion_code: str | None,
) -> dict[str, Any]:
    existing = await db.execute(
        text("SELECT id, programme_code FROM multi_posting_rules WHERE id = :id"),
        {"id": str(rule_id)},
    )
    existing_row = existing.mappings().one_or_none()
    if existing_row is None:
        _raise_not_found("Multi-posting rule not found")

    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=existing_row["programme_code"],
    )
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )

    _validate_multi_posting_rule_payload(
        rule_type=rule_type,
        posting_code_2=posting_code_2,
        combined_label=combined_label,
        main_posting_code=main_posting_code,
        exclusion_code=exclusion_code,
    )
    await _validate_multi_posting_codes_exist(
        db,
        posting_code_1=posting_code_1,
        posting_code_2=posting_code_2,
        main_posting_code=main_posting_code,
        exclusion_code=exclusion_code,
    )
    if await _multi_posting_rule_conflict_exists(
        db,
        programme_code=programme_code,
        posting_code_1=posting_code_1,
        posting_code_2=posting_code_2,
        rule_type=rule_type,
        exclude_id=rule_id,
    ):
        _raise_conflict("Multi-posting rule already exists")

    try:
        result = await db.execute(
            text(
                """
                UPDATE multi_posting_rules
                SET
                    programme_code = :programme_code,
                    posting_code_1 = :posting_code_1,
                    posting_code_2 = :posting_code_2,
                    rule_type = :rule_type,
                    combined_label = :combined_label,
                    main_posting_code = :main_posting_code,
                    exclusion_code = :exclusion_code,
                    updated_at = now()
                WHERE id = :id
                RETURNING
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
                """
            ),
            {
                "id": str(rule_id),
                "programme_code": programme_code,
                "posting_code_1": posting_code_1,
                "posting_code_2": posting_code_2,
                "rule_type": rule_type,
                "combined_label": combined_label,
                "main_posting_code": main_posting_code,
                "exclusion_code": exclusion_code,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Multi-posting rule already exists")
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def delete_multi_posting_rule(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    rule_id: UUID,
) -> None:
    existing = await db.execute(
        text("SELECT id, programme_code FROM multi_posting_rules WHERE id = :id"),
        {"id": str(rule_id)},
    )
    row = existing.mappings().one_or_none()
    if row is None:
        _raise_not_found("Multi-posting rule not found")
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=row["programme_code"],
    )
    await db.execute(
        text("DELETE FROM multi_posting_rules WHERE id = :id"),
        {"id": str(rule_id)},
    )
    await db.commit()
    _invalidate_admin_config_cache()


async def create_posting_group(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    group_code: str,
    posting_code: str,
    programme_code: str,
) -> dict[str, Any]:
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not await _posting_code_exists(db, posting_code):
        _raise_validation(f"Unknown posting code: {posting_code}")
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO posting_groups (group_code, posting_code, programme_code)
                VALUES (:group_code, :posting_code, :programme_code)
                RETURNING id, group_code, posting_code, programme_code, created_at, updated_at
                """
            ),
            {
                "group_code": group_code,
                "posting_code": posting_code,
                "programme_code": programme_code,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Posting group entry already exists for posting/programme")
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def update_posting_group(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    posting_group_id: UUID,
    group_code: str,
    posting_code: str,
    programme_code: str,
) -> dict[str, Any]:
    existing = await db.execute(
        text("SELECT id, programme_code FROM posting_groups WHERE id = :id"),
        {"id": str(posting_group_id)},
    )
    row = existing.mappings().one_or_none()
    if row is None:
        _raise_not_found("Posting group not found")
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=row["programme_code"],
    )
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=programme_code,
    )
    if not await _posting_code_exists(db, posting_code):
        _raise_validation(f"Unknown posting code: {posting_code}")
    try:
        result = await db.execute(
            text(
                """
                UPDATE posting_groups
                SET
                    group_code = :group_code,
                    posting_code = :posting_code,
                    programme_code = :programme_code,
                    updated_at = now()
                WHERE id = :id
                RETURNING id, group_code, posting_code, programme_code, created_at, updated_at
                """
            ),
            {
                "id": str(posting_group_id),
                "group_code": group_code,
                "posting_code": posting_code,
                "programme_code": programme_code,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Posting group entry already exists for posting/programme")
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def delete_posting_group(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    posting_group_id: UUID,
) -> None:
    existing = await db.execute(
        text("SELECT id, programme_code FROM posting_groups WHERE id = :id"),
        {"id": str(posting_group_id)},
    )
    row = existing.mappings().one_or_none()
    if row is None:
        _raise_not_found("Posting group not found")
    _require_programme_in_scope_for_write(
        programme_scope=programme_scope,
        programme_code=row["programme_code"],
    )
    await db.execute(
        text("DELETE FROM posting_groups WHERE id = :id"),
        {"id": str(posting_group_id)},
    )
    await db.commit()
    _invalidate_admin_config_cache()


async def create_weekend_exception(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None,
    posting_code: str | None,
    day_type: str,
    start_time_min: Any,
    end_time_max: Any,
    session_type_id: UUID | None,
    session_name_pattern: str | None,
    mutates_to_session_type_id: UUID | None,
    adjusted_duration_hours: Decimal | None,
) -> dict[str, Any]:
    if programme_code is not None:
        _require_programme_in_scope_for_write(
            programme_scope=programme_scope,
            programme_code=programme_code,
        )
    else:
        _validate_programme_scope_for_write(programme_scope)
    if posting_code and not await _posting_code_exists(db, posting_code):
        _raise_validation(f"Unknown posting code: {posting_code}")
    if not await _session_type_exists(db, session_type_id):
        _raise_validation("Unknown session_type_id")
    if not await _session_type_exists(db, mutates_to_session_type_id):
        _raise_validation("Unknown mutates_to_session_type_id")

    result = await db.execute(
        text(
            """
            INSERT INTO weekend_exceptions (
                programme_code,
                posting_code,
                day_type,
                start_time_min,
                end_time_max,
                session_type_id,
                session_name_pattern,
                mutates_to_session_type_id,
                adjusted_duration_hours
            )
            VALUES (
                :programme_code,
                :posting_code,
                :day_type,
                :start_time_min,
                :end_time_max,
                :session_type_id,
                :session_name_pattern,
                :mutates_to_session_type_id,
                :adjusted_duration_hours
            )
            RETURNING
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
            """
        ),
        {
            "programme_code": programme_code,
            "posting_code": posting_code,
            "day_type": day_type,
            "start_time_min": start_time_min,
            "end_time_max": end_time_max,
            "session_type_id": str(session_type_id) if session_type_id else None,
            "session_name_pattern": session_name_pattern,
            "mutates_to_session_type_id": (
                str(mutates_to_session_type_id) if mutates_to_session_type_id else None
            ),
            "adjusted_duration_hours": adjusted_duration_hours,
        },
    )
    await db.commit()
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def update_weekend_exception(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    weekend_exception_id: UUID,
    programme_code: str | None,
    posting_code: str | None,
    day_type: str,
    start_time_min: Any,
    end_time_max: Any,
    session_type_id: UUID | None,
    session_name_pattern: str | None,
    mutates_to_session_type_id: UUID | None,
    adjusted_duration_hours: Decimal | None,
) -> dict[str, Any]:
    existing = await db.execute(
        text("SELECT id, programme_code FROM weekend_exceptions WHERE id = :id"),
        {"id": str(weekend_exception_id)},
    )
    row = existing.mappings().one_or_none()
    if row is None:
        _raise_not_found("Weekend exception not found")
    if row["programme_code"] is not None:
        _require_programme_in_scope_for_write(
            programme_scope=programme_scope,
            programme_code=row["programme_code"],
        )
    else:
        _validate_programme_scope_for_write(programme_scope)
    if programme_code is not None:
        _require_programme_in_scope_for_write(
            programme_scope=programme_scope,
            programme_code=programme_code,
        )
    if posting_code and not await _posting_code_exists(db, posting_code):
        _raise_validation(f"Unknown posting code: {posting_code}")
    if not await _session_type_exists(db, session_type_id):
        _raise_validation("Unknown session_type_id")
    if not await _session_type_exists(db, mutates_to_session_type_id):
        _raise_validation("Unknown mutates_to_session_type_id")

    result = await db.execute(
        text(
            """
            UPDATE weekend_exceptions
            SET
                programme_code = :programme_code,
                posting_code = :posting_code,
                day_type = :day_type,
                start_time_min = :start_time_min,
                end_time_max = :end_time_max,
                session_type_id = :session_type_id,
                session_name_pattern = :session_name_pattern,
                mutates_to_session_type_id = :mutates_to_session_type_id,
                adjusted_duration_hours = :adjusted_duration_hours,
                updated_at = now()
            WHERE id = :id
            RETURNING
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
            """
        ),
        {
            "id": str(weekend_exception_id),
            "programme_code": programme_code,
            "posting_code": posting_code,
            "day_type": day_type,
            "start_time_min": start_time_min,
            "end_time_max": end_time_max,
            "session_type_id": str(session_type_id) if session_type_id else None,
            "session_name_pattern": session_name_pattern,
            "mutates_to_session_type_id": (
                str(mutates_to_session_type_id) if mutates_to_session_type_id else None
            ),
            "adjusted_duration_hours": adjusted_duration_hours,
        },
    )
    await db.commit()
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def delete_weekend_exception(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    weekend_exception_id: UUID,
) -> None:
    existing = await db.execute(
        text("SELECT id, programme_code FROM weekend_exceptions WHERE id = :id"),
        {"id": str(weekend_exception_id)},
    )
    row = existing.mappings().one_or_none()
    if row is None:
        _raise_not_found("Weekend exception not found")
    if row["programme_code"] is not None:
        _require_programme_in_scope_for_write(
            programme_scope=programme_scope,
            programme_code=row["programme_code"],
        )
    else:
        _validate_programme_scope_for_write(programme_scope)
    await db.execute(
        text("DELETE FROM weekend_exceptions WHERE id = :id"),
        {"id": str(weekend_exception_id)},
    )
    await db.commit()
    _invalidate_admin_config_cache()


async def create_global_session_type(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    name: str,
    duration_hours: Decimal,
    is_active: bool,
) -> dict[str, Any]:
    _validate_programme_scope_for_write(programme_scope)
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO global_session_types (name, duration_hours, is_active)
                VALUES (:name, :duration_hours, :is_active)
                RETURNING id, name, duration_hours, is_active, created_at, updated_at
                """
            ),
            {
                "name": name,
                "duration_hours": duration_hours,
                "is_active": is_active,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Global session type already exists")
    _invalidate_admin_config_cache()
    return dict(result.mappings().one())


async def update_global_session_type(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    global_session_type_id: UUID,
    name: str | None,
    duration_hours: Decimal | None,
    is_active: bool | None,
) -> dict[str, Any]:
    _validate_programme_scope_for_write(programme_scope)
    try:
        result = await db.execute(
            text(
                """
                UPDATE global_session_types
                SET
                    name = COALESCE(:name, name),
                    duration_hours = COALESCE(:duration_hours, duration_hours),
                    is_active = COALESCE(:is_active, is_active),
                    updated_at = now()
                WHERE id = :id
                RETURNING id, name, duration_hours, is_active, created_at, updated_at
                """
            ),
            {
                "id": str(global_session_type_id),
                "name": name,
                "duration_hours": duration_hours,
                "is_active": is_active,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            await db.rollback()
            _raise_not_found("Global session type not found")
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _raise_conflict("Global session type already exists")
    _invalidate_admin_config_cache()
    return dict(row)


async def delete_global_session_type(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    global_session_type_id: UUID,
) -> None:
    _validate_programme_scope_for_write(programme_scope)
    existing = await db.execute(
        text("SELECT id, name FROM global_session_types WHERE id = :id"),
        {"id": str(global_session_type_id)},
    )
    row = existing.mappings().one_or_none()
    if row is None:
        _raise_not_found("Global session type not found")

    referenced = await db.execute(
        text(
            """
            SELECT 1
            FROM teaching_events
            WHERE teaching_name = :name
            LIMIT 1
            """
        ),
        {"name": row["name"]},
    )
    if referenced.scalar_one_or_none() is not None:
        _raise_conflict("Global session type is in use; deactivate it instead")

    await db.execute(
        text("DELETE FROM global_session_types WHERE id = :id"),
        {"id": str(global_session_type_id)},
    )
    await db.commit()
    _invalidate_admin_config_cache()
