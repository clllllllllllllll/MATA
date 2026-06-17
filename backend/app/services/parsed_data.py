from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.services import data_revalidation_service
from app.services.audit import write_audit_log
from app.services.ttf_parser import split_keywords


def _validate_programme_filter(
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
) -> None:
    if master_admin or programme_code is None or not programme_code.strip():
        return
    token = programme_code.strip().lower()
    if not programme_scope or not any(token in code.lower() for code in programme_scope):
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
        _add_partial_text_filter(
            where_clauses,
            params,
            key="programme_code",
            column_sql=column_sql,
            value=programme_code,
        )
        if not master_admin and programme_scope:
            where_clauses.append(
                _scope_or_clause(
                    column_sql=column_sql,
                    values=sorted(programme_scope),
                    params=params,
                )
            )
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


def _add_partial_text_filter(
    where_clauses: list[str],
    params: dict[str, Any],
    *,
    key: str,
    column_sql: str,
    value: str | None,
) -> None:
    if not value or not value.strip():
        return
    params[key] = f"%{value.strip().lower()}%"
    where_clauses.append(f"LOWER(COALESCE({column_sql}, '')) LIKE :{key}")


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
        _add_partial_text_filter(where_clauses, params, key="mcr", column_sql="r.mcr", value=mcr)
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
                r.email,
                r.phone,
                r.employer_tag,
                r.status,
                r.updated_at
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
        _add_partial_text_filter(
            where_clauses,
            params,
            key="posting_code",
            column_sql="rp.posting_code",
            value=posting_code,
        )
    if mcr:
        _add_partial_text_filter(where_clauses, params, key="mcr", column_sql="r.mcr", value=mcr)
    if status:
        params["status"] = status.strip().lower()
        where_clauses.append("LOWER(rp.status) = :status")
    if month_label:
        _add_partial_text_filter(
            where_clauses,
            params,
            key="month_label",
            column_sql="rp.month_label",
            value=month_label,
        )
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
                rp.updated_at
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
        _add_partial_text_filter(
            where_clauses,
            params,
            key="posting_code",
            column_sql="tt.posting_code",
            value=posting_code,
        )
    if r_year:
        _add_partial_text_filter(where_clauses, params, key="r_year", column_sql="tt.r_year", value=r_year)
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
        columns_sql=["tt.programme_code", "tt.posting_code", "tt.r_year", "st.name", "tt.tag", "tt.details_of_training"],
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
                tt.details_of_training,
                tt.updated_at
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
        _add_partial_text_filter(
            where_clauses,
            params,
            key="posting_code",
            column_sql="tnc.posting_code",
            value=posting_code,
        )
    if r_year:
        _add_partial_text_filter(where_clauses, params, key="r_year", column_sql="tnc.r_year", value=r_year)
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
        _add_partial_text_filter(where_clauses, params, key="mcr", column_sql="f.mcr", value=mcr)
    if month_label:
        _add_partial_text_filter(where_clauses, params, key="month_label", column_sql="f.month_label", value=month_label)
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
                f.upload_id,
                f.updated_at
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
        columns_sql=[
            "ph.name",
            "ph.day_of_week",
            "CAST(ph.holiday_date AS TEXT)",
            "CAST(COALESCE(ph.year, EXTRACT(YEAR FROM ph.holiday_date)::int) AS TEXT)",
        ],
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
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if academic_year_label:
        _add_partial_text_filter(
            where_clauses,
            params,
            key="academic_year_label",
            column_sql="amb.academic_year_label",
            value=academic_year_label,
        )
    if ay_date_category:
        params["ay_date_category"] = ay_date_category.strip().lower()
        where_clauses.append("amb.ay_date_category = :ay_date_category")
    if month_label:
        _add_partial_text_filter(
            where_clauses,
            params,
            key="month_label",
            column_sql="amb.month_label",
            value=month_label,
        )
    _add_search_filter(
        where_clauses,
        params,
        search=search,
        columns_sql=[
            "amb.academic_year_label",
            "amb.ay_date_category",
            "amb.month_label",
            "CAST(amb.start_date AS TEXT)",
            "CAST(amb.end_date AS TEXT)",
        ],
    )
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
                amb.upload_id,
                amb.updated_at
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


_RESIDENT_ALLOWED_FIELDS = {
    "employee_code",
    "name",
    "mcr",
    "programme_code",
    "r_year",
    "classification",
    "reg_type",
    "base_institution",
    "email",
    "phone",
    "status",
    "employer_tag",
}

_RESIDENT_POSTING_ALLOWED_FIELDS = {
    "posting_code",
    "start_date",
    "end_date",
    "day_part",
    "month_label",
    "r_year",
    "status",
    "loa_type",
    "loa_start_date",
    "loa_end_date",
    "refresher_training_type",
    "refresher_training_start",
    "refresher_training_end",
    "active_months_weight",
    "working_days_in_month",
}

_RESIDENT_POSTING_REPLACEMENT_FIELDS = _RESIDENT_POSTING_ALLOWED_FIELDS | {
    "resident_id",
    "reporting_period_id",
}

_TEACHING_TARGET_ALLOWED_FIELDS = {
    "monthly_target",
    "is_tracked",
    "is_reallocatable",
    "tag",
    "details_of_training",
}

_FORM_F1_ALLOWED_FIELDS = {
    "status_raw",
    "is_active",
    "promotion_date",
}

_ACADEMIC_MONTH_BOUNDARY_ALLOWED_FIELDS = {
    "academic_year_label",
    "ay_date_category",
    "month_label",
    "start_date",
    "end_date",
}

_DATE_FIELDS = {
    "start_date",
    "end_date",
    "loa_start_date",
    "loa_end_date",
    "refresher_training_start",
    "refresher_training_end",
    "promotion_date",
}
_UUID_FIELDS = {
    "resident_id",
    "reporting_period_id",
    "session_type_id",
}
_DECIMAL_FIELDS = {"active_months_weight"}
_INT_FIELDS = {"monthly_target", "working_days_in_month"}
_BOOL_FIELDS = {"is_tracked", "is_reallocatable", "is_active"}
_REQUIRED_TEXT_FIELDS = {
    "name",
    "mcr",
    "programme_code",
    "r_year",
    "posting_code",
    "status",
    "status_raw",
    "academic_year_label",
    "ay_date_category",
    "month_label",
    "details_of_training",
}

_RESIDENT_STATUS_VALUES = {"active", "inactive", "loa", "employed"}
_POSTING_STATUS_VALUES = {"active", "loa", "loa_working", "employed"}
_AY_DATE_CATEGORIES = {"im_subspec", "non_im_subspec"}
_FORM_F1_STATUS_ACTIVE_MAP = {
    "active": True,
    "extension": True,
    "inactive": False,
}


def _raise_validation(detail: str, *, status_code: int = 422) -> None:
    raise ApiError(
        status_code=status_code,
        detail=detail,
        error_code=(
            ErrorCode.CONFLICT.value
            if status_code == 409
            else ErrorCode.VALIDATION_FAILED.value
        ),
    )


def _raise_not_found(entity_type: str) -> None:
    raise ApiError(
        status_code=404,
        detail=f"{entity_type} not found",
        error_code=ErrorCode.NOT_FOUND.value,
    )


def _raise_forbidden(detail: str) -> None:
    raise ApiError(
        status_code=403,
        detail=detail,
        error_code=ErrorCode.FORBIDDEN.value,
    )


def _scope_filter_sql(
    *,
    column_sql: str,
    programme_scope: set[str],
    master_admin: bool,
    params: dict[str, Any],
) -> str:
    if master_admin:
        return ""
    if not programme_scope:
        return " AND 1 = 0"
    return " AND " + _scope_or_clause(
        column_sql=column_sql,
        values=sorted(programme_scope),
        params=params,
    )


def _parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _row_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_ready(value) for key, value in dict(row).items()}


def _coerce_date_value(field: str, value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            _raise_validation(f"{field} must be an ISO date")
            raise AssertionError from exc
    _raise_validation(f"{field} must be an ISO date")
    raise AssertionError


def _coerce_uuid_value(field: str, value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        _raise_validation(f"{field} must be a valid UUID")
        raise AssertionError from exc


def _coerce_change_value(field: str, value: Any) -> Any:
    if field in _DATE_FIELDS:
        return _coerce_date_value(field, value)
    if field in _UUID_FIELDS:
        return _coerce_uuid_value(field, value)
    if field in _DECIMAL_FIELDS:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception as exc:
            _raise_validation(f"{field} must be a decimal number")
            raise AssertionError from exc
    if field in _INT_FIELDS:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            _raise_validation(f"{field} must be an integer")
            raise AssertionError from exc
    if field in _BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        _raise_validation(f"{field} must be a boolean")
    if isinstance(value, str):
        trimmed = value.strip()
        if field in _REQUIRED_TEXT_FIELDS and not trimmed:
            _raise_validation(f"{field} is required")
        return trimmed or None
    if field in _REQUIRED_TEXT_FIELDS and value is None:
        _raise_validation(f"{field} is required")
    return value


def _allowlisted_changes(
    changes: dict[str, Any],
    *,
    allowed_fields: set[str],
) -> dict[str, Any]:
    forbidden = sorted(set(changes) - allowed_fields)
    if forbidden:
        _raise_validation(
            "These fields cannot be corrected here: " + ", ".join(forbidden)
        )
    return {
        field: _coerce_change_value(field, value)
        for field, value in changes.items()
    }


def _canonical_compare(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, UUID):
        return str(value)
    if value is None:
        return ""
    return str(value)


def _changed_values(
    before: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    return {
        field: value
        for field, value in changes.items()
        if _canonical_compare(before.get(field)) != _canonical_compare(value)
    }


def _normalise_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_last_seen(
    before: dict[str, Any],
    last_seen_updated_at: datetime | None,
) -> None:
    if last_seen_updated_at is None:
        return
    current = _normalise_datetime(before.get("updated_at"))
    last_seen = _normalise_datetime(last_seen_updated_at)
    if current != last_seen:
        _raise_validation(
            "Parsed data row changed since it was last loaded",
            status_code=409,
        )


def _merged_row(before: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    merged = dict(before)
    merged.update(changes)
    return merged


async def _scalar_exists(db: AsyncSession, sql: str, params: dict[str, Any]) -> bool:
    result = await db.execute(text(sql), params)
    return result.scalar_one_or_none() is not None


async def _snapshot_resident(
    db: AsyncSession,
    *,
    row_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"id": str(row_id)}
    scope_sql = _scope_filter_sql(
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:resident_snapshot */
            SELECT
                r.id,
                r.employee_code,
                r.name,
                r.mcr,
                r.classification,
                r.programme_code,
                r.r_year,
                r.reg_type,
                r.base_institution,
                r.email,
                r.phone,
                r.status,
                r.employer_tag,
                r.created_at,
                r.updated_at
            FROM residents r
            WHERE r.id = :id
            {scope_sql}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found("resident")
    return dict(row)


async def _snapshot_resident_posting(
    db: AsyncSession,
    *,
    row_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"id": str(row_id)}
    scope_sql = _scope_filter_sql(
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:resident_posting_snapshot */
            SELECT
                rp.id,
                rp.resident_id,
                r.name AS resident_name,
                r.mcr,
                r.programme_code,
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
                rp.updated_at
            FROM resident_postings rp
            JOIN residents r ON r.id = rp.resident_id
            WHERE rp.id = :id
            {scope_sql}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found("resident posting")
    return dict(row)


async def _snapshot_teaching_target(
    db: AsyncSession,
    *,
    row_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"id": str(row_id)}
    scope_sql = _scope_filter_sql(
        column_sql="tt.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:teaching_target_snapshot */
            SELECT
                tt.id,
                tt.reporting_period_id,
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
                tt.details_of_training,
                tt.created_at,
                tt.updated_at
            FROM teaching_targets tt
            JOIN session_types st ON st.id = tt.session_type_id
            WHERE tt.id = :id
            {scope_sql}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found("teaching target")
    return dict(row)


async def _snapshot_form_f1_record(
    db: AsyncSession,
    *,
    row_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"id": str(row_id)}
    scope_sql = _scope_filter_sql(
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:form_f1_record_snapshot */
            SELECT
                f.id,
                f.reporting_period_id,
                f.mcr,
                r.name AS resident_name,
                r.programme_code,
                f.month_label,
                f.status_raw,
                f.is_active,
                f.promotion_date,
                f.upload_id,
                f.created_at,
                f.updated_at
            FROM form_f1_records f
            LEFT JOIN residents r ON UPPER(r.mcr) = UPPER(f.mcr)
            WHERE f.id = :id
            {scope_sql}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found("FormF1 record")
    return dict(row)


async def _snapshot_academic_month_boundary(
    db: AsyncSession,
    *,
    row_id: UUID,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            /* parsed_data_correction:academic_month_boundary_snapshot */
            SELECT
                amb.id,
                amb.academic_year_label,
                amb.ay_date_category,
                amb.month_label,
                amb.start_date,
                amb.end_date,
                amb.upload_id,
                amb.created_at,
                amb.updated_at
            FROM academic_month_boundaries amb
            WHERE amb.id = :id
            """
        ),
        {"id": str(row_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found("academic month boundary")
    return dict(row)


async def _validate_resident_changes(
    db: AsyncSession,
    *,
    row_id: UUID,
    merged: dict[str, Any],
    changed: dict[str, Any],
    programme_scope: set[str],
    master_admin: bool,
) -> None:
    if "status" in changed and str(merged["status"]).lower() not in _RESIDENT_STATUS_VALUES:
        _raise_validation("status is not valid")
    if "programme_code" in changed:
        if not await _scalar_exists(
            db,
            """
            /* parsed_data_validation:programme_exists */
            SELECT 1
            FROM programmes
            WHERE code = :programme_code
            LIMIT 1
            """,
            {"programme_code": merged["programme_code"]},
        ):
            _raise_validation("programme_code does not exist")
        if not master_admin:
            if not programme_scope:
                _raise_forbidden("Forbidden - admin programme scope is empty")
            if merged["programme_code"] not in programme_scope:
                _raise_forbidden("Forbidden - programme not in admin scope")
    if "mcr" in changed:
        if not str(merged["mcr"]).strip():
            _raise_validation("mcr is required")
        if await _scalar_exists(
            db,
            """
            /* parsed_data_validation:resident_mcr_unique */
            SELECT 1
            FROM residents
            WHERE UPPER(mcr) = UPPER(:mcr)
              AND id <> :id
            LIMIT 1
            """,
            {"mcr": merged["mcr"], "id": str(row_id)},
        ):
            _raise_validation("mcr already exists for another resident")
        if await _scalar_exists(
            db,
            """
            /* parsed_data_validation:external_mcr_unique */
            SELECT 1
            FROM external_residents
            WHERE UPPER(mcr) = UPPER(:mcr)
            LIMIT 1
            """,
            {"mcr": merged["mcr"]},
        ):
            _raise_validation("mcr already exists for an external resident")
    if "employee_code" in changed and merged.get("employee_code"):
        if await _scalar_exists(
            db,
            """
            /* parsed_data_validation:employee_code_unique */
            SELECT 1
            FROM residents
            WHERE employee_code = :employee_code
              AND id <> :id
            LIMIT 1
            """,
            {"employee_code": merged["employee_code"], "id": str(row_id)},
        ):
            _raise_validation("employee_code already exists for another resident")


async def _validate_resident_posting_payload(
    db: AsyncSession,
    *,
    row: dict[str, Any],
    programme_scope: set[str],
    master_admin: bool,
) -> None:
    if row["start_date"] > row["end_date"]:
        _raise_validation("start_date must be on or before end_date")
    if row.get("day_part") not in {None, "AM", "PM"}:
        _raise_validation("day_part must be AM, PM, or null")
    if str(row.get("status") or "").lower() not in _POSTING_STATUS_VALUES:
        _raise_validation("status is not valid")
    active_weight = Decimal(str(row.get("active_months_weight") or "0"))
    if active_weight <= 0 or active_weight > Decimal("1.0"):
        _raise_validation("active_months_weight must be greater than 0 and at most 1.0")
    working_days = row.get("working_days_in_month")
    if working_days is not None and int(working_days) < 0:
        _raise_validation("working_days_in_month cannot be negative")
    if row.get("posting_code") and not await _scalar_exists(
        db,
        """
        /* parsed_data_validation:posting_code_exists */
        SELECT 1
        FROM posting_codes
        WHERE code = :code
        LIMIT 1
        """,
        {"code": row["posting_code"]},
    ):
        _raise_validation("posting_code does not exist")
    if not await _scalar_exists(
        db,
        """
        /* parsed_data_validation:reporting_period_exists */
        SELECT 1
        FROM reporting_periods
        WHERE id = :reporting_period_id
        LIMIT 1
        """,
        {"reporting_period_id": str(row["reporting_period_id"])},
    ):
        _raise_validation("reporting_period_id does not exist")

    params: dict[str, Any] = {"resident_id": str(row["resident_id"])}
    scope_sql = _scope_filter_sql(
        column_sql="programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* parsed_data_validation:resident_exists */
            SELECT id, programme_code, mcr, name
            FROM residents
            WHERE id = :resident_id
            {scope_sql}
            """
        ),
        params,
    )
    if result.mappings().one_or_none() is None:
        _raise_validation("resident_id does not exist in admin scope")


async def _validate_resident_posting_update_uniqueness(
    db: AsyncSession,
    *,
    row_id: UUID,
    merged: dict[str, Any],
) -> None:
    if await _scalar_exists(
        db,
        """
        /* parsed_data_validation:resident_posting_update_unique */
        SELECT 1
        FROM resident_postings
        WHERE id <> :id
          AND resident_id = :resident_id
          AND reporting_period_id = :reporting_period_id
          AND start_date = :start_date
          AND day_part IS NOT DISTINCT FROM :day_part
        LIMIT 1
        """,
        {
            "id": str(row_id),
            "resident_id": str(merged["resident_id"]),
            "reporting_period_id": str(merged["reporting_period_id"]),
            "start_date": merged["start_date"],
            "day_part": merged.get("day_part"),
        },
    ):
        _raise_validation(
            "resident posting conflicts with another row for resident, period, start_date, and day_part",
            status_code=409,
        )


async def _validate_teaching_target_changes(
    db: AsyncSession,
    *,
    merged: dict[str, Any],
    changed: dict[str, Any],
) -> list[str] | None:
    if "monthly_target" in changed and int(merged["monthly_target"]) <= 0:
        _raise_validation("monthly_target must be positive")
    if bool(merged.get("is_reallocatable")) and not (merged.get("tag") or "").strip():
        _raise_validation("tag is required when is_reallocatable is true")
    if merged.get("posting_code") and not await _scalar_exists(
        db,
        """
        /* parsed_data_validation:posting_code_exists */
        SELECT 1
        FROM posting_codes
        WHERE code = :code
        LIMIT 1
        """,
        {"code": merged["posting_code"]},
    ):
        _raise_validation("posting_code does not exist")

    result = await db.execute(
        text(
            """
            /* parsed_data_validation:session_type_duration */
            SELECT id, name, duration_hours
            FROM session_types
            WHERE id = :session_type_id
            """
        ),
        {"session_type_id": str(merged["session_type_id"])},
    )
    session_type = result.mappings().one_or_none()
    if session_type is None:
        _raise_validation("session_type_id does not exist")
    merged["duration_hours"] = session_type["duration_hours"]

    catalogue_changed = bool(
        set(changed)
        & {
            "details_of_training",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
            "session_type_id",
            "is_tracked",
        }
    )
    if not catalogue_changed:
        return None

    keywords = split_keywords(str(merged.get("details_of_training") or ""))
    if not keywords:
        _raise_validation("details_of_training must include at least one keyword")
    for keyword in keywords:
        if await _scalar_exists(
            db,
            """
            /* parsed_data_validation:catalogue_keyword_conflict */
            SELECT 1
            FROM teaching_name_catalogue
            WHERE reporting_period_id = :reporting_period_id
              AND programme_code = :programme_code
              AND posting_code = :posting_code
              AND r_year = :r_year
              AND LOWER(keyword) = LOWER(:keyword)
              AND session_type_id <> :session_type_id
            LIMIT 1
            """,
            {
                "reporting_period_id": str(merged["reporting_period_id"]),
                "programme_code": merged["programme_code"],
                "posting_code": merged["posting_code"],
                "r_year": merged["r_year"],
                "keyword": keyword,
                "session_type_id": str(merged["session_type_id"]),
            },
        ):
            _raise_validation(
                f"keyword already maps to another session type in this target scope: {keyword}"
            )
    return keywords


def _validate_form_f1_changes(changed: dict[str, Any], merged: dict[str, Any]) -> None:
    if "status_raw" not in changed and "is_active" not in changed:
        return
    status_key = str(merged["status_raw"]).strip().casefold()
    if status_key not in _FORM_F1_STATUS_ACTIVE_MAP:
        if "is_active" not in changed:
            _raise_validation("custom status_raw values require explicit is_active")
        return
    expected = _FORM_F1_STATUS_ACTIVE_MAP[status_key]
    if bool(merged["is_active"]) is not expected:
        _raise_validation("is_active does not match status_raw")
    if "status_raw" in changed:
        changed["is_active"] = expected
        merged["is_active"] = expected


async def _validate_academic_month_boundary_changes(
    db: AsyncSession,
    *,
    row_id: UUID,
    merged: dict[str, Any],
) -> None:
    if merged["start_date"] > merged["end_date"]:
        _raise_validation("start_date must be on or before end_date")
    if merged["ay_date_category"] not in _AY_DATE_CATEGORIES:
        _raise_validation("ay_date_category is not valid")
    if await _scalar_exists(
        db,
        """
        /* parsed_data_validation:academic_month_boundary_unique */
        SELECT 1
        FROM academic_month_boundaries
        WHERE id <> :id
          AND academic_year_label = :academic_year_label
          AND ay_date_category = :ay_date_category
          AND month_label = :month_label
        LIMIT 1
        """,
        {
            "id": str(row_id),
            "academic_year_label": merged["academic_year_label"],
            "ay_date_category": merged["ay_date_category"],
            "month_label": merged["month_label"],
        },
    ):
        _raise_validation(
            "academic month boundary already exists for this academic year, category, and month",
            status_code=409,
        )
    if await _scalar_exists(
        db,
        """
        /* parsed_data_validation:academic_month_boundary_overlap */
        SELECT 1
        FROM academic_month_boundaries
        WHERE id <> :id
          AND academic_year_label = :academic_year_label
          AND ay_date_category = :ay_date_category
          AND daterange(start_date, end_date, '[]') && daterange(:start_date, :end_date, '[]')
        LIMIT 1
        """,
        {
            "id": str(row_id),
            "academic_year_label": merged["academic_year_label"],
            "ay_date_category": merged["ay_date_category"],
            "start_date": merged["start_date"],
            "end_date": merged["end_date"],
        },
    ):
        _raise_validation("academic month boundary overlaps another row in the same category")


async def _apply_update(
    db: AsyncSession,
    *,
    table_name: str,
    row_id: UUID,
    changed: dict[str, Any],
) -> None:
    assignments = ",\n                ".join(
        f"{field} = :{field}" for field in sorted(changed)
    )
    params = {field: value for field, value in changed.items()}
    params["id"] = str(row_id)
    await db.execute(
        text(
            f"""
            UPDATE {table_name} SET
                {assignments},
                updated_at = now()
            WHERE id = :id
            """
        ),
        params,
    )


async def _write_correction_audit(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    action: str,
    entity_type: str,
    entity_id: UUID | str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    audit_metadata = _row_dict(metadata)
    audit_metadata["source_page"] = "parsed_data"
    return await write_audit_log(
        db,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=_row_dict(before) if before is not None else None,
        after=_row_dict(after) if after is not None else None,
        metadata=audit_metadata,
    )


async def _revalidate_live_data_correction(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    changed_entity: DataRevalidationChangedEntity,
    action: DataRevalidationAction,
    scope: DataRevalidationScope,
    entity_id: UUID | str | None,
    changed_fields: list[str],
    correction_reason: str,
    programme_code: str | None = None,
    resident_id: UUID | str | None = None,
    reporting_period_id: UUID | str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = await data_revalidation_service.revalidate_after_live_data_correction(
        context=DataRevalidationContext(
            trigger_source=DataRevalidationTriggerSource.LIVE_DATA_CORRECTION,
            changed_entity=changed_entity,
            action=action,
            scope=scope,
            entity_id=str(entity_id) if entity_id is not None else None,
            programme_code=programme_code,
            resident_id=str(resident_id) if resident_id is not None else None,
            reporting_period_id=(
                str(reporting_period_id) if reporting_period_id is not None else None
            ),
            changed_fields=list(changed_fields),
            source_metadata=source_metadata or {},
            actor_user_id=str(actor.actor_user_id) if actor.actor_user_id else None,
            actor_role=actor.actor_role,
            reason=correction_reason,
        ),
        db_session=db,
    )
    return summary.model_dump(mode="json")


async def correct_resident(
    db: AsyncSession,
    *,
    row_id: UUID,
    changes: dict[str, Any],
    correction_reason: str,
    last_seen_updated_at: datetime | None,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    before = await _snapshot_resident(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    _validate_last_seen(before, last_seen_updated_at)
    coerced = _allowlisted_changes(changes, allowed_fields=_RESIDENT_ALLOWED_FIELDS)
    changed = _changed_values(before, coerced)
    if not changed:
        _raise_validation("changes do not modify the resident row")
    merged = _merged_row(before, changed)
    await _validate_resident_changes(
        db,
        row_id=row_id,
        merged=merged,
        changed=changed,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    await _apply_update(db, table_name="residents", row_id=row_id, changed=changed)
    after = await _snapshot_resident(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    updated_fields = sorted(changed)
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.RESIDENT,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.SINGLE_ROW,
        entity_id=row_id,
        resident_id=row_id,
        programme_code=after.get("programme_code"),
        changed_fields=updated_fields,
        correction_reason=correction_reason,
    )
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.resident.update",
        entity_type="resident",
        entity_id=row_id,
        before=before,
        after=after,
        metadata={
            "correction_reason": correction_reason,
            "updated_fields": updated_fields,
            "programme_code": after.get("programme_code"),
            "data_revalidation": data_revalidation,
        },
    )
    await db.commit()
    return {
        "item": _row_dict(after),
        "audit_log_id": audit["id"],
        "entity_type": "resident",
        "entity_id": str(row_id),
        "updated_fields": updated_fields,
        "data_revalidation": data_revalidation,
    }


async def correct_resident_posting(
    db: AsyncSession,
    *,
    row_id: UUID,
    changes: dict[str, Any],
    correction_reason: str,
    last_seen_updated_at: datetime | None,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    before = await _snapshot_resident_posting(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    _validate_last_seen(before, last_seen_updated_at)
    coerced = _allowlisted_changes(changes, allowed_fields=_RESIDENT_POSTING_ALLOWED_FIELDS)
    changed = _changed_values(before, coerced)
    if not changed:
        _raise_validation("changes do not modify the resident posting row")
    merged = _merged_row(before, changed)
    await _validate_resident_posting_payload(
        db,
        row=merged,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    await _validate_resident_posting_update_uniqueness(
        db,
        row_id=row_id,
        merged=merged,
    )
    await _apply_update(
        db,
        table_name="resident_postings",
        row_id=row_id,
        changed=changed,
    )
    after = await _snapshot_resident_posting(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    updated_fields = sorted(changed)
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.RESIDENT_POSTING,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.RESIDENT_MONTH,
        entity_id=row_id,
        resident_id=after.get("resident_id"),
        reporting_period_id=after.get("reporting_period_id"),
        programme_code=after.get("programme_code"),
        changed_fields=updated_fields,
        correction_reason=correction_reason,
    )
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.resident_posting.update",
        entity_type="resident_posting",
        entity_id=row_id,
        before=before,
        after=after,
        metadata={
            "correction_reason": correction_reason,
            "updated_fields": updated_fields,
            "programme_code": after.get("programme_code"),
            "resident_id": str(after.get("resident_id")),
            "reporting_period_id": str(after.get("reporting_period_id")),
            "data_revalidation": data_revalidation,
        },
    )
    await db.commit()
    return {
        "item": _row_dict(after),
        "audit_log_id": audit["id"],
        "entity_type": "resident_posting",
        "entity_id": str(row_id),
        "updated_fields": updated_fields,
        "data_revalidation": data_revalidation,
    }


async def _regenerate_target_catalogue(
    db: AsyncSession,
    *,
    target_id: UUID,
    before_target: dict[str, Any],
    target: dict[str, Any],
    keywords: list[str],
) -> None:
    for scope in (before_target, target):
        await db.execute(
            text(
                """
                DELETE FROM teaching_name_catalogue
                WHERE reporting_period_id = :reporting_period_id
                  AND programme_code = :programme_code
                  AND posting_code = :posting_code
                  AND r_year = :r_year
                  AND session_type_id = :session_type_id
                  AND EXISTS (
                    SELECT 1 FROM teaching_targets tt WHERE tt.id = :target_id
                  )
                """
            ),
            {
                "target_id": str(target_id),
                "reporting_period_id": str(scope["reporting_period_id"]),
                "programme_code": scope["programme_code"],
                "posting_code": scope["posting_code"],
                "r_year": scope["r_year"],
                "session_type_id": str(scope["session_type_id"]),
            },
        )
    for keyword in keywords:
        await db.execute(
            text(
                """
                INSERT INTO teaching_name_catalogue (
                    keyword,
                    session_type_id,
                    posting_code,
                    programme_code,
                    r_year,
                    reporting_period_id,
                    duration_hours,
                    is_tracked
                )
                VALUES (
                    :keyword,
                    :session_type_id,
                    :posting_code,
                    :programme_code,
                    :r_year,
                    :reporting_period_id,
                    :duration_hours,
                    :is_tracked
                )
                """
            ),
            {
                "keyword": keyword,
                "session_type_id": str(target["session_type_id"]),
                "posting_code": target["posting_code"],
                "programme_code": target["programme_code"],
                "r_year": target["r_year"],
                "reporting_period_id": str(target["reporting_period_id"]),
                "duration_hours": target["duration_hours"],
                "is_tracked": target["is_tracked"],
            },
        )


async def correct_teaching_target(
    db: AsyncSession,
    *,
    row_id: UUID,
    changes: dict[str, Any],
    correction_reason: str,
    last_seen_updated_at: datetime | None,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    before = await _snapshot_teaching_target(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    _validate_last_seen(before, last_seen_updated_at)
    coerced = _allowlisted_changes(changes, allowed_fields=_TEACHING_TARGET_ALLOWED_FIELDS)
    changed = _changed_values(before, coerced)
    if not changed:
        _raise_validation("changes do not modify the teaching target row")
    merged = _merged_row(before, changed)
    keywords = await _validate_teaching_target_changes(db, merged=merged, changed=changed)
    await _apply_update(
        db,
        table_name="teaching_targets",
        row_id=row_id,
        changed=changed,
    )
    after = await _snapshot_teaching_target(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    if keywords is not None:
        await _regenerate_target_catalogue(
            db,
            target_id=row_id,
            before_target=before,
            target=after,
            keywords=keywords,
        )
    updated_fields = sorted(changed)
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.TEACHING_TARGET,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        entity_id=row_id,
        programme_code=after.get("programme_code"),
        reporting_period_id=after.get("reporting_period_id"),
        changed_fields=updated_fields,
        correction_reason=correction_reason,
    )
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.teaching_target.update",
        entity_type="teaching_target",
        entity_id=row_id,
        before=before,
        after=after,
        metadata={
            "correction_reason": correction_reason,
            "updated_fields": updated_fields,
            "programme_code": after.get("programme_code"),
            "reporting_period_id": str(after.get("reporting_period_id")),
            "catalogue_keywords": keywords,
            "data_revalidation": data_revalidation,
        },
    )
    await db.commit()
    return {
        "item": _row_dict(after),
        "audit_log_id": audit["id"],
        "entity_type": "teaching_target",
        "entity_id": str(row_id),
        "updated_fields": updated_fields,
        "data_revalidation": data_revalidation,
    }


async def correct_form_f1_record(
    db: AsyncSession,
    *,
    row_id: UUID,
    changes: dict[str, Any],
    correction_reason: str,
    last_seen_updated_at: datetime | None,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    before = await _snapshot_form_f1_record(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    _validate_last_seen(before, last_seen_updated_at)
    coerced = _allowlisted_changes(changes, allowed_fields=_FORM_F1_ALLOWED_FIELDS)
    changed = _changed_values(before, coerced)
    if not changed:
        _raise_validation("changes do not modify the FormF1 row")
    merged = _merged_row(before, changed)
    _validate_form_f1_changes(changed, merged)
    await _apply_update(
        db,
        table_name="form_f1_records",
        row_id=row_id,
        changed=changed,
    )
    after = await _snapshot_form_f1_record(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    updated_fields = sorted(changed)
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.FORM_F1_RECORD,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.RESIDENT_REPORTING_PERIOD,
        entity_id=row_id,
        programme_code=after.get("programme_code"),
        reporting_period_id=after.get("reporting_period_id"),
        changed_fields=updated_fields,
        correction_reason=correction_reason,
        source_metadata={
            "mcr": after.get("mcr"),
            "month_label": after.get("month_label"),
        },
    )
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.form_f1_record.update",
        entity_type="form_f1_record",
        entity_id=row_id,
        before=before,
        after=after,
        metadata={
            "correction_reason": correction_reason,
            "updated_fields": updated_fields,
            "programme_code": after.get("programme_code"),
            "mcr": after.get("mcr"),
            "reporting_period_id": str(after.get("reporting_period_id")),
            "data_revalidation": data_revalidation,
        },
    )
    await db.commit()
    return {
        "item": _row_dict(after),
        "audit_log_id": audit["id"],
        "entity_type": "form_f1_record",
        "entity_id": str(row_id),
        "updated_fields": updated_fields,
        "data_revalidation": data_revalidation,
    }


async def correct_academic_month_boundary(
    db: AsyncSession,
    *,
    row_id: UUID,
    changes: dict[str, Any],
    correction_reason: str,
    last_seen_updated_at: datetime | None,
    actor: StaffActorContext,
) -> dict[str, Any]:
    before = await _snapshot_academic_month_boundary(db, row_id=row_id)
    _validate_last_seen(before, last_seen_updated_at)
    coerced = _allowlisted_changes(
        changes,
        allowed_fields=_ACADEMIC_MONTH_BOUNDARY_ALLOWED_FIELDS,
    )
    changed = _changed_values(before, coerced)
    if not changed:
        _raise_validation("changes do not modify the academic month boundary row")
    merged = _merged_row(before, changed)
    await _validate_academic_month_boundary_changes(db, row_id=row_id, merged=merged)
    await _apply_update(
        db,
        table_name="academic_month_boundaries",
        row_id=row_id,
        changed=changed,
    )
    after = await _snapshot_academic_month_boundary(db, row_id=row_id)
    updated_fields = sorted(changed)
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.ACADEMIC_MONTH_BOUNDARY,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.GLOBAL,
        entity_id=row_id,
        changed_fields=updated_fields,
        correction_reason=correction_reason,
        source_metadata={
            "academic_year_label": after.get("academic_year_label"),
            "ay_date_category": after.get("ay_date_category"),
            "month_label": after.get("month_label"),
        },
    )
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.academic_month_boundary.update",
        entity_type="academic_month_boundary",
        entity_id=row_id,
        before=before,
        after=after,
        metadata={
            "correction_reason": correction_reason,
            "updated_fields": updated_fields,
            "academic_year_label": after.get("academic_year_label"),
            "ay_date_category": after.get("ay_date_category"),
            "data_revalidation": data_revalidation,
        },
    )
    await db.commit()
    return {
        "item": _row_dict(after),
        "audit_log_id": audit["id"],
        "entity_type": "academic_month_boundary",
        "entity_id": str(row_id),
        "updated_fields": updated_fields,
        "data_revalidation": data_revalidation,
    }


async def _fetch_resident_posting_source_rows(
    db: AsyncSession,
    *,
    row_ids: list[UUID],
    programme_scope: set[str],
    master_admin: bool,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"ids": [str(row_id) for row_id in row_ids]}
    scope_sql = _scope_filter_sql(
        column_sql="r.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:resident_posting_source_rows */
            SELECT
                rp.id,
                rp.resident_id,
                r.name AS resident_name,
                r.mcr,
                r.programme_code,
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
                rp.updated_at
            FROM resident_postings rp
            JOIN residents r ON r.id = rp.resident_id
            WHERE rp.id = ANY(:ids)
            {scope_sql}
            ORDER BY rp.start_date ASC, rp.day_part ASC NULLS FIRST, rp.id ASC
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    if len(rows) != len(row_ids):
        _raise_not_found("resident posting")
    return rows


async def _fetch_resident_posting_rows_by_ids(
    db: AsyncSession,
    *,
    row_ids: list[str],
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            /* parsed_data_correction:resident_posting_rows_by_ids */
            SELECT
                rp.id,
                rp.resident_id,
                r.name AS resident_name,
                r.mcr,
                r.programme_code,
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
                rp.updated_at
            FROM resident_postings rp
            JOIN residents r ON r.id = rp.resident_id
            WHERE rp.id = ANY(:ids)
            ORDER BY rp.start_date ASC, rp.day_part ASC NULLS FIRST, rp.id ASC
            """
        ),
        {"ids": row_ids},
    )
    return [dict(row) for row in result.mappings().all()]


def _source_metadata_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _source_values_match(left: Any, right: Any) -> bool:
    left_value = _source_metadata_value(left)
    right_value = _source_metadata_value(right)
    if left_value is None or right_value is None:
        return left_value == right_value
    return left_value.casefold() == right_value.casefold()


def _normalise_source_cell_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _source_cell_text_matches(fragment: dict[str, Any], source: dict[str, Any]) -> bool:
    supplied = source.get("source_cell_text")
    if supplied is None:
        return True
    return _normalise_source_cell_text(fragment.get("source_cell_text")) == _normalise_source_cell_text(supplied)


def _fragment_matches_source(fragment: dict[str, Any], source: dict[str, Any]) -> bool:
    for field in ("sheet_name", "row_number", "cell_ref"):
        if not _source_values_match(fragment.get(field), source.get(field)):
            return False
    source_column_header = source.get("source_column_header")
    if source_column_header is not None and not _source_values_match(
        fragment.get("source_column_header"),
        source_column_header,
    ):
        return False
    if not _source_cell_text_matches(fragment, source):
        return False
    return True


async def _verify_source_metadata(
    db: AsyncSession,
    *,
    source: dict[str, Any],
    before_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    upload_log_id = source.get("upload_log_id")
    if upload_log_id is None:
        client_source = _row_dict(source)
        return {
            "source_metadata_verified": False,
            "source": client_source,
            "client_selected_source_metadata": client_source,
        }
    missing = [
        field
        for field in ("sheet_name", "row_number", "cell_ref")
        if source.get(field) in {None, ""}
    ]
    if missing:
        _raise_validation(
            "source metadata requires sheet_name, row_number, and cell_ref when upload_log_id is provided"
        )

    result = await db.execute(
        text(
            """
            /* parsed_data_correction:source_upload_log */
            SELECT id, reporting_period_id, programme_code, summary
            FROM upload_logs
            WHERE id = :upload_log_id
            """
        ),
        {"upload_log_id": str(upload_log_id)},
    )
    upload_log = result.mappings().one_or_none()
    if upload_log is None:
        _raise_validation("source upload_log_id does not exist")

    before_period_ids = {str(row.get("reporting_period_id")) for row in before_rows}
    upload_period_id = upload_log.get("reporting_period_id")
    if upload_period_id is not None and str(upload_period_id) not in before_period_ids:
        _raise_validation("source upload log reporting period does not match affected rows")

    summary = _parse_json_field(upload_log.get("summary"))
    if not isinstance(summary, dict):
        _raise_validation("source upload log summary is not readable")
    fragments = summary.get("raw_multi_posting_fragments")
    if not isinstance(fragments, list):
        _raise_validation("source upload log does not contain raw multi-posting fragments")

    matching_fragments = [
        fragment
        for fragment in fragments
        if isinstance(fragment, dict) and _fragment_matches_source(fragment, source)
    ]
    if not matching_fragments:
        _raise_validation("source metadata could not be verified against upload log raw fragments")

    before_mcrs = {str(row.get("mcr")) for row in before_rows if row.get("mcr") is not None}
    before_months = {
        str(row.get("month_label"))
        for row in before_rows
        if row.get("month_label") is not None
    }
    context_matches = []
    for fragment in matching_fragments:
        fragment_mcr = fragment.get("mcr")
        if fragment_mcr is not None and str(fragment_mcr) not in before_mcrs:
            continue
        fragment_month = fragment.get("month_label")
        if fragment_month is not None and str(fragment_month) not in before_months:
            continue
        context_matches.append(fragment)
    if not context_matches:
        _raise_validation("source metadata does not match affected row resident/month context")

    verified_fragment = context_matches[0]
    verified_source = {
        "upload_log_id": str(upload_log_id),
        "sheet_name": verified_fragment.get("sheet_name"),
        "row_number": verified_fragment.get("row_number"),
        "cell_ref": verified_fragment.get("cell_ref"),
        "source_column_header": verified_fragment.get("source_column_header"),
        "source_cell_text": verified_fragment.get("source_cell_text"),
        "mcr": verified_fragment.get("mcr"),
        "month_label": verified_fragment.get("month_label"),
        "matched_fragment_count": len(context_matches),
    }
    return {
        "source_metadata_verified": True,
        "source": _row_dict(verified_source),
        "verified_source_metadata": _row_dict(verified_source),
    }


def _resident_posting_unique_key(row: dict[str, Any]) -> tuple[str, str, date, str | None]:
    return (
        str(row["resident_id"]),
        str(row["reporting_period_id"]),
        row["start_date"],
        row.get("day_part"),
    )


async def _validate_source_cell_replacement_uniqueness(
    db: AsyncSession,
    *,
    replacement_rows: list[dict[str, Any]],
    affected_ids: list[str],
) -> None:
    seen: set[tuple[str, str, date, str | None]] = set()
    for row in replacement_rows:
        key = _resident_posting_unique_key(row)
        if key in seen:
            _raise_validation(
                "replacement rows conflict with each other for resident, period, start_date, and day_part",
                status_code=409,
            )
        seen.add(key)

    for row in replacement_rows:
        result = await db.execute(
            text(
                """
                /* parsed_data_validation:resident_posting_replacement_unique */
                SELECT 1
                FROM resident_postings
                WHERE resident_id = :resident_id
                  AND reporting_period_id = :reporting_period_id
                  AND start_date = :start_date
                  AND day_part IS NOT DISTINCT FROM :day_part
                  AND id <> ALL(:affected_ids)
                LIMIT 1
                """
            ),
            {
                "resident_id": str(row["resident_id"]),
                "reporting_period_id": str(row["reporting_period_id"]),
                "start_date": row["start_date"],
                "day_part": row.get("day_part"),
                "affected_ids": affected_ids,
            },
        )
        if result.scalar_one_or_none() is not None:
            _raise_validation(
                "replacement rows conflict with an existing resident posting outside the source-cell group",
                status_code=409,
            )


async def replace_resident_posting_source_cell(
    db: AsyncSession,
    *,
    affected_resident_posting_ids: list[UUID],
    replacement_rows: list[dict[str, Any]],
    last_seen_rows: list[dict[str, Any]],
    source: dict[str, Any],
    correction_reason: str,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    before_rows = await _fetch_resident_posting_source_rows(
        db,
        row_ids=affected_resident_posting_ids,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    last_seen_by_id = {str(row["id"]): row["updated_at"] for row in last_seen_rows}
    for row in before_rows:
        token = last_seen_by_id.get(str(row["id"]))
        if token is not None:
            _validate_last_seen(row, _normalise_datetime(token))
    source_resident_ids = {str(row["resident_id"]) for row in before_rows}
    source_period_ids = {str(row["reporting_period_id"]) for row in before_rows}
    if len(source_resident_ids) != 1 or len(source_period_ids) != 1:
        _raise_validation("source-cell replacement must target one resident and one reporting period")
    source_metadata = await _verify_source_metadata(
        db,
        source=source,
        before_rows=before_rows,
    )

    coerced_replacements: list[dict[str, Any]] = []
    for replacement in replacement_rows:
        row = {
            field: _coerce_change_value(field, value)
            for field, value in replacement.items()
            if field in _RESIDENT_POSTING_REPLACEMENT_FIELDS
        }
        if str(row["resident_id"]) not in source_resident_ids:
            _raise_validation("replacement resident_id must match the affected source rows")
        if str(row["reporting_period_id"]) not in source_period_ids:
            _raise_validation("replacement reporting_period_id must match the affected source rows")
        await _validate_resident_posting_payload(
            db,
            row=row,
            programme_scope=programme_scope,
            master_admin=master_admin,
        )
        coerced_replacements.append(row)

    affected_ids = [str(row_id) for row_id in affected_resident_posting_ids]
    await _validate_source_cell_replacement_uniqueness(
        db,
        replacement_rows=coerced_replacements,
        affected_ids=affected_ids,
    )
    await db.execute(
        text(
            """
            DELETE FROM resident_postings
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": affected_ids},
    )
    inserted_ids: list[str] = []
    for row in coerced_replacements:
        row_id = str(uuid4())
        inserted_ids.append(row_id)
        await db.execute(
            text(
                """
                INSERT INTO resident_postings (
                    id,
                    resident_id,
                    posting_code,
                    reporting_period_id,
                    start_date,
                    end_date,
                    day_part,
                    month_label,
                    r_year,
                    status,
                    loa_type,
                    loa_start_date,
                    loa_end_date,
                    refresher_training_type,
                    refresher_training_start,
                    refresher_training_end,
                    active_months_weight,
                    working_days_in_month
                )
                VALUES (
                    :id,
                    :resident_id,
                    :posting_code,
                    :reporting_period_id,
                    :start_date,
                    :end_date,
                    :day_part,
                    :month_label,
                    :r_year,
                    :status,
                    :loa_type,
                    :loa_start_date,
                    :loa_end_date,
                    :refresher_training_type,
                    :refresher_training_start,
                    :refresher_training_end,
                    :active_months_weight,
                    :working_days_in_month
                )
                """
            ),
            {"id": row_id, **row},
        )
    after_rows = await _fetch_resident_posting_rows_by_ids(db, row_ids=inserted_ids)
    verified_source_metadata = source_metadata.get("verified_source_metadata")
    if not isinstance(verified_source_metadata, dict):
        verified_source_metadata = source_metadata.get("source")
    source_payload = {
        **(verified_source_metadata if isinstance(verified_source_metadata, dict) else {}),
        **source_metadata,
    }
    source_payload["affected_row_count"] = len(before_rows)
    source_payload["replacement_row_count"] = len(after_rows)
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT,
        action=DataRevalidationAction.REPLACE,
        scope=DataRevalidationScope.RESIDENT_MONTH,
        entity_id=affected_ids[0] if affected_ids else None,
        resident_id=before_rows[0].get("resident_id"),
        reporting_period_id=before_rows[0].get("reporting_period_id"),
        programme_code=before_rows[0].get("programme_code"),
        changed_fields=["source_cell_replacement"],
        correction_reason=correction_reason,
        source_metadata=source_payload,
    )
    metadata = {
        "correction_reason": correction_reason,
        "updated_fields": sorted(_RESIDENT_POSTING_ALLOWED_FIELDS),
        "affected_resident_posting_ids": affected_ids,
        "replacement_resident_posting_ids": inserted_ids,
        "programme_code": before_rows[0].get("programme_code"),
        "resident_id": str(before_rows[0].get("resident_id")),
        "reporting_period_id": str(before_rows[0].get("reporting_period_id")),
        "data_revalidation": data_revalidation,
        **source_metadata,
    }
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.resident_posting.source_cell_replace",
        entity_type="resident_posting_source_cell",
        entity_id=affected_ids[0],
        before={"before_rows": [_row_dict(row) for row in before_rows]},
        after={"after_rows": [_row_dict(row) for row in after_rows]},
        metadata=metadata,
    )
    await db.commit()
    return {
        "before_rows": [_row_dict(row) for row in before_rows],
        "after_rows": [_row_dict(row) for row in after_rows],
        "audit_log_id": audit["id"],
        "entity_type": "resident_posting_source_cell",
        "entity_id": affected_ids[0],
        "updated_fields": sorted(_RESIDENT_POSTING_ALLOWED_FIELDS),
        "data_revalidation": data_revalidation,
    }


async def list_correction_history(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    upload_log_id: UUID | None = None,
    sheet_name: str | None = None,
    row_number: int | None = None,
    cell_ref: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where_clauses = ["al.action LIKE 'admin.parsed_data.%'"]

    def source_filter_sql(field: str) -> str:
        return (
            "COALESCE("
            f"al.metadata_json #>> '{{source,{field}}}', "
            f"al.metadata_json #>> '{{verified_source_metadata,{field}}}', "
            f"al.metadata_json #>> '{{client_selected_source_metadata,{field}}}'"
            ")"
        )

    if entity_type:
        params["entity_type"] = entity_type
        where_clauses.append("al.entity_type = :entity_type")
    if entity_id:
        params["entity_id"] = str(entity_id)
        where_clauses.append("al.entity_id = :entity_id")
    if upload_log_id:
        params["upload_log_id"] = str(upload_log_id)
        where_clauses.append(source_filter_sql("upload_log_id") + " = :upload_log_id")
    if sheet_name:
        params["sheet_name"] = sheet_name
        where_clauses.append(source_filter_sql("sheet_name") + " = :sheet_name")
    if row_number:
        params["row_number"] = str(row_number)
        where_clauses.append(source_filter_sql("row_number") + " = :row_number")
    if cell_ref:
        params["cell_ref"] = cell_ref
        where_clauses.append(source_filter_sql("cell_ref") + " = :cell_ref")
    if not master_admin:
        if not programme_scope:
            where_clauses.append("1 = 0")
        else:
            where_clauses.append(
                _scope_or_clause(
                    column_sql="al.metadata_json ->> 'programme_code'",
                    values=sorted(programme_scope),
                    params=params,
                )
            )

    where_sql = _where_sql(where_clauses)
    count_result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:corrections_history */
            SELECT COUNT(*)
            FROM audit_logs al
            {where_sql}
            """
        ),
        params,
    )
    total = int(count_result.scalar_one() or 0)
    query_params = dict(params)
    query_params["limit"] = limit
    query_params["offset"] = offset
    result = await db.execute(
        text(
            f"""
            /* parsed_data_correction:corrections_history */
            SELECT
                al.id,
                al.created_at,
                al.actor_user_id,
                al.actor_role,
                al.actor_name,
                al.action,
                al.entity_type,
                al.entity_id,
                al.before_json,
                al.after_json,
                al.metadata_json,
                al.metadata_json ->> 'correction_reason' AS correction_reason
            FROM audit_logs al
            {where_sql}
            ORDER BY al.created_at DESC, al.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        query_params,
    )
    rows = []
    for row in result.mappings().all():
        payload = dict(row)
        payload["before_json"] = _parse_json_field(payload.get("before_json"))
        payload["after_json"] = _parse_json_field(payload.get("after_json"))
        metadata = _parse_json_field(payload.get("metadata_json"))
        payload["metadata_json"] = metadata
        if payload.get("correction_reason") is None and isinstance(metadata, dict):
            payload["correction_reason"] = metadata.get("correction_reason")
        rows.append(payload)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


async def resident_posting_corrections_reupload_warning(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            /* parsed_data_correction:corrected_resident_posting_reupload_count */
            WITH corrected_resident_posting_ids AS (
                SELECT entity_id::uuid AS id
                FROM audit_logs
                WHERE action = 'admin.parsed_data.resident_posting.update'
                  AND entity_id IS NOT NULL
                UNION
                SELECT (after_row ->> 'id')::uuid AS id
                FROM audit_logs
                CROSS JOIN LATERAL jsonb_array_elements(after_json -> 'after_rows') AS after_row
                WHERE action = 'admin.parsed_data.resident_posting.source_cell_replace'
                  AND after_json ? 'after_rows'
            )
            SELECT COUNT(DISTINCT rp.id)
            FROM resident_postings rp
            JOIN corrected_resident_posting_ids corrected
              ON corrected.id = rp.id
            WHERE rp.reporting_period_id = :reporting_period_id
            """
        ),
        {"reporting_period_id": str(reporting_period_id)},
    )
    count = int(result.scalar_one() or 0)
    if count <= 0:
        return None
    return {
        "warning_type": "corrected_rows_replaced",
        "severity": "warning",
        "entity_type": "resident_postings",
        "count": count,
        "message": (
            f"RDB re-upload will replace {count} resident_postings row(s) "
            "that were corrected through Parsed Data."
        ),
    }
