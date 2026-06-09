from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


def _validate_programme_filter(
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
) -> None:
    if master_admin or programme_code is None:
        return
    if not programme_scope or programme_code not in programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _scope_or_clause(
    *,
    column_sql: str,
    values: list[str],
    params: dict[str, Any],
) -> str:
    fragments: list[str] = []
    for idx, value in enumerate(values):
        key = f"scope_programme_code_{idx}"
        params[key] = value
        fragments.append(f"{column_sql} = :{key}")
    return "(" + " OR ".join(fragments) + ")"


def _add_programme_scope_filter(
    where_clauses: list[str],
    params: dict[str, Any],
    *,
    column_sql: str,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
) -> None:
    _validate_programme_filter(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )

    if programme_code:
        params["programme_code"] = programme_code
        where_clauses.append(f"{column_sql} = :programme_code")
        return

    if master_admin:
        return

    if not programme_scope:
        where_clauses.append("1 = 0")
        return

    where_clauses.append(
        _scope_or_clause(
            column_sql=column_sql,
            values=sorted(programme_scope),
            params=params,
        )
    )


def _where_sql(where_clauses: list[str]) -> str:
    if not where_clauses:
        return ""
    return " WHERE " + " AND ".join(where_clauses)


def _add_search_filter(
    where_clauses: list[str],
    params: dict[str, Any],
    *,
    search: str | None,
    columns_sql: list[str],
) -> None:
    if not search or not search.strip():
        return
    params["search"] = f"%{search.strip().lower()}%"
    where_clauses.append(
        "(" + " OR ".join(f"LOWER(COALESCE({column}, '')) LIKE :search" for column in columns_sql) + ")"
    )


async def _page(
    db: AsyncSession,
    *,
    select_sql: str,
    from_sql: str,
    where_clauses: list[str],
    params: dict[str, Any],
    order_sql: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    where_sql = _where_sql(where_clauses)
    count_result = await db.execute(
        text(
            f"""
            SELECT COUNT(*)
            {from_sql}
            {where_sql}
            """
        ),
        params,
    )
    total = int(count_result.scalar_one())

    query_params = dict(params)
    query_params["limit"] = limit
    query_params["offset"] = offset
    result = await db.execute(
        text(
            f"""
            {select_sql}
            {from_sql}
            {where_sql}
            {order_sql}
            LIMIT :limit OFFSET :offset
            """
        ),
        query_params,
    )
    return {
        "items": [dict(row) for row in result.mappings().all()],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def list_residents(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None = None,
    mcr: str | None = None,
    search: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    _add_programme_scope_filter(
        where_clauses,
        params,
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    if mcr:
        params["mcr"] = mcr.strip().upper()
        where_clauses.append("UPPER(r.mcr) = :mcr")
    if status:
        params["status"] = status.strip().lower()
        where_clauses.append("LOWER(r.status) = :status")
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=[
            "r.name",
            "r.mcr",
            "r.employee_code",
            "r.programme_code",
            "r.r_year",
            "r.classification",
            "r.base_institution",
        ],
    )
    return await _page(
        db,
        select_sql="""
            SELECT
                r.id,
                r.employee_code,
                r.name,
                r.mcr,
                r.programme_code,
                r.r_year,
                r.classification,
                r.reg_type,
                r.base_institution,
                r.employer_tag,
                r.status
        """,
        from_sql="FROM residents r",
        where_clauses=where_clauses,
        params=params,
        order_sql="ORDER BY r.programme_code ASC NULLS LAST, r.mcr ASC, r.id ASC",
        limit=limit,
        offset=offset,
    )


async def list_resident_postings(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
    posting_code: str | None = None,
    mcr: str | None = None,
    status: str | None = None,
    month_label: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    _add_programme_scope_filter(
        where_clauses,
        params,
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    if reporting_period_id:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("rp.reporting_period_id = :reporting_period_id")
    if posting_code:
        params["posting_code"] = posting_code.strip()
        where_clauses.append("rp.posting_code = :posting_code")
    if mcr:
        params["mcr"] = mcr.strip().upper()
        where_clauses.append("UPPER(r.mcr) = :mcr")
    if status:
        params["status"] = status.strip().lower()
        where_clauses.append("LOWER(rp.status) = :status")
    if month_label:
        params["month_label"] = month_label.strip()
        where_clauses.append("rp.month_label = :month_label")
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=["r.name", "r.mcr", "r.programme_code", "rp.posting_code", "rp.month_label"],
    )
    return await _page(
        db,
        select_sql="""
            SELECT
                rp.id,
                rp.resident_id,
                r.name AS resident_name,
                r.mcr,
                r.programme_code,
                rp.posting_code,
                rp.reporting_period_id,
                rper.label AS reporting_period_label,
                rp.start_date,
                rp.end_date,
                rp.month_label,
                rp.r_year,
                rp.status,
                rp.loa_type,
                rp.loa_start_date,
                rp.loa_end_date,
                rp.refresher_training_type,
                rp.active_months_weight,
                rp.working_days_in_month
        """,
        from_sql="""
            FROM resident_postings rp
            JOIN residents r ON r.id = rp.resident_id
            LEFT JOIN reporting_periods rper ON rper.id = rp.reporting_period_id
        """,
        where_clauses=where_clauses,
        params=params,
        order_sql="""
            ORDER BY
                rp.reporting_period_id ASC,
                r.programme_code ASC NULLS LAST,
                r.mcr ASC,
                rp.start_date ASC,
                rp.day_part ASC NULLS FIRST,
                rp.id ASC
        """,
        limit=limit,
        offset=offset,
    )


async def list_teaching_targets(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
    posting_code: str | None = None,
    r_year: str | None = None,
    session_type: str | None = None,
    is_tracked: bool | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    _add_programme_scope_filter(
        where_clauses,
        params,
        column_sql="tt.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    if reporting_period_id:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("tt.reporting_period_id = :reporting_period_id")
    if posting_code:
        params["posting_code"] = posting_code.strip()
        where_clauses.append("tt.posting_code = :posting_code")
    if r_year:
        params["r_year"] = r_year.strip().upper()
        where_clauses.append("UPPER(tt.r_year) = :r_year")
    if session_type:
        params["session_type"] = f"%{session_type.strip()}%"
        where_clauses.append("st.name ILIKE :session_type")
    if is_tracked is not None:
        params["is_tracked"] = is_tracked
        where_clauses.append("tt.is_tracked = :is_tracked")
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=["tt.programme_code", "tt.posting_code", "tt.r_year", "st.name", "tt.details_of_training"],
    )
    return await _page(
        db,
        select_sql="""
            SELECT
                tt.id,
                tt.reporting_period_id,
                rper.label AS reporting_period_label,
                tt.programme_code,
                tt.r_year,
                tt.posting_code,
                tt.session_type_id,
                st.name AS session_type_name,
                st.duration_hours,
                tt.monthly_target,
                tt.is_tracked,
                tt.is_reallocatable,
                tt.tag,
                tt.details_of_training
        """,
        from_sql="""
            FROM teaching_targets tt
            JOIN session_types st ON st.id = tt.session_type_id
            LEFT JOIN reporting_periods rper ON rper.id = tt.reporting_period_id
        """,
        where_clauses=where_clauses,
        params=params,
        order_sql="""
            ORDER BY
                tt.reporting_period_id ASC,
                tt.programme_code ASC,
                tt.posting_code ASC,
                tt.r_year ASC,
                st.name ASC,
                tt.id ASC
        """,
        limit=limit,
        offset=offset,
    )


async def list_teaching_name_catalogue(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
    posting_code: str | None = None,
    r_year: str | None = None,
    keyword: str | None = None,
    is_tracked: bool | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    _add_programme_scope_filter(
        where_clauses,
        params,
        column_sql="tnc.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    if reporting_period_id:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("tnc.reporting_period_id = :reporting_period_id")
    if posting_code:
        params["posting_code"] = posting_code.strip()
        where_clauses.append("tnc.posting_code = :posting_code")
    if r_year:
        params["r_year"] = r_year.strip().upper()
        where_clauses.append("UPPER(tnc.r_year) = :r_year")
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        where_clauses.append("tnc.keyword ILIKE :keyword")
    if is_tracked is not None:
        params["is_tracked"] = is_tracked
        where_clauses.append("tnc.is_tracked = :is_tracked")
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=["tnc.keyword", "tnc.programme_code", "tnc.posting_code", "tnc.r_year", "st.name"],
    )
    return await _page(
        db,
        select_sql="""
            SELECT
                tnc.id,
                tnc.keyword,
                tnc.programme_code,
                tnc.posting_code,
                tnc.r_year,
                tnc.reporting_period_id,
                rper.label AS reporting_period_label,
                tnc.session_type_id,
                st.name AS session_type_name,
                tnc.duration_hours,
                tnc.is_tracked
        """,
        from_sql="""
            FROM teaching_name_catalogue tnc
            JOIN session_types st ON st.id = tnc.session_type_id
            LEFT JOIN reporting_periods rper ON rper.id = tnc.reporting_period_id
        """,
        where_clauses=where_clauses,
        params=params,
        order_sql="""
            ORDER BY
                tnc.reporting_period_id ASC,
                tnc.programme_code ASC,
                tnc.posting_code ASC,
                tnc.r_year ASC,
                tnc.keyword ASC,
                tnc.id ASC
        """,
        limit=limit,
        offset=offset,
    )


async def list_form_f1_records(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
    mcr: str | None = None,
    month_label: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    _add_programme_scope_filter(
        where_clauses,
        params,
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    if reporting_period_id:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("f.reporting_period_id = :reporting_period_id")
    if mcr:
        params["mcr"] = mcr.strip().upper()
        where_clauses.append("UPPER(f.mcr) = :mcr")
    if month_label:
        params["month_label"] = month_label.strip()
        where_clauses.append("f.month_label = :month_label")
    if is_active is not None:
        params["is_active"] = is_active
        where_clauses.append("f.is_active = :is_active")
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=["f.mcr", "f.month_label", "f.status_raw", "r.name", "r.programme_code"],
    )
    return await _page(
        db,
        select_sql="""
            SELECT
                f.id,
                f.reporting_period_id,
                rper.label AS reporting_period_label,
                f.mcr,
                r.name AS resident_name,
                r.programme_code,
                f.month_label,
                f.status_raw,
                f.is_active,
                f.promotion_date,
                f.upload_id
        """,
        from_sql="""
            FROM form_f1_records f
            LEFT JOIN residents r ON UPPER(r.mcr) = UPPER(f.mcr)
            LEFT JOIN reporting_periods rper ON rper.id = f.reporting_period_id
        """,
        where_clauses=where_clauses,
        params=params,
        order_sql="""
            ORDER BY
                f.reporting_period_id ASC,
                f.mcr ASC,
                f.month_label ASC,
                f.id ASC
        """,
        limit=limit,
        offset=offset,
    )


async def list_public_holidays(
    db: AsyncSession,
    *,
    year: int | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if year is not None:
        params["year"] = year
        where_clauses.append("COALESCE(ph.year, EXTRACT(YEAR FROM ph.holiday_date)::int) = :year")
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=["ph.name", "ph.day_of_week"],
    )
    return await _page(
        db,
        select_sql="""
            SELECT
                ph.id,
                ph.holiday_date,
                ph.name,
                ph.day_of_week,
                ph.year
        """,
        from_sql="FROM public_holidays ph",
        where_clauses=where_clauses,
        params=params,
        order_sql="ORDER BY ph.holiday_date ASC, ph.id ASC",
        limit=limit,
        offset=offset,
    )


async def list_academic_month_boundaries(
    db: AsyncSession,
    *,
    academic_year_label: str | None = None,
    ay_date_category: str | None = None,
    month_label: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if academic_year_label:
        params["academic_year_label"] = academic_year_label.strip()
        where_clauses.append("amb.academic_year_label = :academic_year_label")
    if ay_date_category:
        params["ay_date_category"] = ay_date_category.strip().lower()
        where_clauses.append("amb.ay_date_category = :ay_date_category")
    if month_label:
        params["month_label"] = month_label.strip()
        where_clauses.append("amb.month_label = :month_label")
    return await _page(
        db,
        select_sql="""
            SELECT
                amb.id,
                amb.academic_year_label,
                amb.ay_date_category,
                amb.month_label,
                amb.start_date,
                amb.end_date,
                amb.upload_id
        """,
        from_sql="FROM academic_month_boundaries amb",
        where_clauses=where_clauses,
        params=params,
        order_sql="""
            ORDER BY
                amb.academic_year_label ASC,
                amb.ay_date_category ASC,
                amb.start_date ASC,
                amb.id ASC
        """,
        limit=limit,
        offset=offset,
    )
