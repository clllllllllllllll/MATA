from __future__ import annotations

import logging
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.security import log_safe_exception
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.services import cache_invalidation
from app.services import data_revalidation_service
from app.services.attendance_loa import reclassify_attendance_loa
from app.services.audit import write_audit_log
from app.services.rdb_parser import (
    ProgrammeConfig,
    ResidentPostingWrite,
    parse_rdb_source_cell_replacement,
    resolve_r_year,
)
from app.services.teaching_target_impacts import stable_target_mapping_impact_counts
from app.services.teaching_name_programme_scopes import (
    reconcile_teaching_name_programme_scopes,
)
from app.services.ttf_scope_lock import acquire_ttf_scope_lock


logger = logging.getLogger(__name__)


_ALLOWED_SCOPE_COLUMN_SQL = frozenset(
    {
        "al.metadata_json ->> 'programme_code'",
        "programme_code",
        "r.programme_code",
        "tt.programme_code",
        "wi.programme_code",
    }
)
_ALLOWED_SEARCH_COLUMN_SQL = frozenset(
    {
        "CAST(amb.end_date AS TEXT)",
        "CAST(amb.start_date AS TEXT)",
        "CAST(COALESCE(ph.year, EXTRACT(YEAR FROM ph.holiday_date)::int) AS TEXT)",
        "CAST(ph.holiday_date AS TEXT)",
        "amb.academic_year_label",
        "amb.ay_date_category",
        "amb.month_label",
        "f.mcr",
        "f.month_label",
        "f.status_raw",
        "ph.day_of_week",
        "ph.name",
        "r.base_institution",
        "r.classification",
        "r.employee_code",
        "r.mcr",
        "r.name",
        "r.programme_code",
        "r.r_year",
        "rp.month_label",
        "rp.posting_code",
        "st.name",
        "tt.posting_code",
        "tt.programme_code",
        "tt.r_year",
        "tt.tag",
    }
)
_ALLOWED_PARTIAL_TEXT_COLUMNS_BY_KEY = {
    "academic_year_label": frozenset({"amb.academic_year_label"}),
    "mcr": frozenset({"f.mcr", "r.mcr"}),
    "month_label": frozenset({"amb.month_label", "f.month_label", "rp.month_label"}),
    "posting_code": frozenset(
        {
            "rp.posting_code",
            "tt.posting_code",
        }
    ),
    "programme_code": _ALLOWED_SCOPE_COLUMN_SQL,
    "r_year": frozenset({"tt.r_year"}),
}


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
    if column_sql not in _ALLOWED_SCOPE_COLUMN_SQL:
        raise ValueError("Untrusted parsed-data scope column")
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
    if not columns_sql or any(
        column not in _ALLOWED_SEARCH_COLUMN_SQL for column in columns_sql
    ):
        raise ValueError("Untrusted parsed-data search column")
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
    allowed_columns = _ALLOWED_PARTIAL_TEXT_COLUMNS_BY_KEY.get(key)
    if allowed_columns is None or column_sql not in allowed_columns:
        raise ValueError("Untrusted parsed-data partial-text filter")
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
    single_query_total: bool = False,
) -> dict[str, Any]:
    where_sql = _where_sql(where_clauses)
    if not single_query_total:
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
    total_column_sql = ", COUNT(*) OVER() AS _page_total" if single_query_total else ""
    result = await db.execute(
        text(
            f"""
            {select_sql}{total_column_sql}
            {from_sql}
            {where_sql}
            {order_sql}
            LIMIT :limit OFFSET :offset
            """
        ),
        query_params,
    )
    items = [dict(row) for row in result.mappings().all()]
    if single_query_total:
        total = int(items[0].pop("_page_total")) if items else 0
        for item in items[1:]:
            item.pop("_page_total")
        if not items and offset:
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
    return {
        "items": items,
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
        single_query_total=True,
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
        columns_sql=["tt.programme_code", "tt.posting_code", "tt.r_year", "st.name", "tt.tag"],
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

_UPDATE_ALLOWED_FIELDS_BY_TABLE = {
    "academic_month_boundaries": frozenset(_ACADEMIC_MONTH_BOUNDARY_ALLOWED_FIELDS),
    "form_f1_records": frozenset(_FORM_F1_ALLOWED_FIELDS),
    "resident_postings": frozenset(_RESIDENT_POSTING_ALLOWED_FIELDS),
    "residents": frozenset(_RESIDENT_ALLOWED_FIELDS),
    "teaching_targets": frozenset(_TEACHING_TARGET_ALLOWED_FIELDS),
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
    "status",
    "academic_year_label",
    "ay_date_category",
    "month_label",
}

_RESIDENT_STATUS_VALUES = {"active", "inactive", "loa", "employed"}
_POSTING_STATUS_VALUES = {"active", "loa", "loa_working", "employed"}
_AY_DATE_CATEGORIES = {"im_subspec", "non_im_subspec"}
_FORM_F1_STATUS_ACTIVE_MAP = {
    "": False,
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
            if field == "monthly_target":
                _raise_validation("monthly_target must be a non-negative whole number")
            return None
        if field == "monthly_target":
            try:
                target = Decimal(str(value))
            except Exception as exc:
                _raise_validation("monthly_target must be a non-negative whole number")
                raise AssertionError from exc
            if (
                not target.is_finite()
                or target < 0
                or target != target.to_integral_value()
            ):
                _raise_validation("monthly_target must be a non-negative whole number")
            return int(target)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            _raise_validation(f"{field} must be an integer")
            raise AssertionError from exc
    if field in _BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        _raise_validation(f"{field} must be a boolean")
    if field == "status_raw" and value is None:
        return ""
    if isinstance(value, str):
        trimmed = value.strip()
        if field == "status_raw":
            return trimmed
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
            _raise_validation("mcr already exists for a Non-NHG Resident")
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
    status = str(row.get("status") or "").lower()
    if status not in _POSTING_STATUS_VALUES:
        _raise_validation("status is not valid")
    if not row.get("posting_code") and status != "loa":
        _raise_validation("posting_code may be null only for pure LOA")
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
) -> None:
    if "monthly_target" in changed and int(merged["monthly_target"]) < 0:
        _raise_validation("monthly_target must be a non-negative whole number")
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

def _validate_form_f1_changes(changed: dict[str, Any], merged: dict[str, Any]) -> None:
    if "status_raw" not in changed and "is_active" not in changed:
        return
    status_key = str(merged.get("status_raw") or "").strip().casefold()
    if status_key not in _FORM_F1_STATUS_ACTIVE_MAP:
        if "is_active" not in changed:
            _raise_validation("custom status_raw values require explicit is_active")
        return
    expected = _FORM_F1_STATUS_ACTIVE_MAP[status_key]
    if "status_raw" in changed:
        changed["is_active"] = expected
        merged["is_active"] = expected
        return
    if bool(merged["is_active"]) is not expected:
        _raise_validation("is_active does not match status_raw")


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
    allowed_fields = _UPDATE_ALLOWED_FIELDS_BY_TABLE.get(table_name)
    if (
        allowed_fields is None
        or not changed
        or not set(changed).issubset(allowed_fields)
    ):
        raise ValueError("Untrusted parsed-data update specification")
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


async def _reconcile_teaching_name_scopes_for_resident(
    db: AsyncSession,
    *,
    resident_id: UUID | str,
    reporting_period_id: UUID | str | None = None,
) -> dict[str, int]:
    """Apply the additive Teaching Name admission rules to current Live Data."""

    params: dict[str, Any] = {
        "resident_id": str(resident_id),
        "reporting_period_id": (
            str(reporting_period_id) if reporting_period_id is not None else None
        ),
    }
    result = await db.execute(
        text(
            """
            /* parsed_data_reconciliation:resident_programme_periods */
            SELECT DISTINCT
                posting.reporting_period_id,
                resident.programme_code
            FROM resident_postings AS posting
            JOIN residents AS resident ON resident.id = posting.resident_id
            WHERE posting.resident_id = CAST(:resident_id AS uuid)
              AND resident.programme_code IS NOT NULL
              AND (
                  CAST(:reporting_period_id AS uuid) IS NULL
                  OR posting.reporting_period_id = CAST(:reporting_period_id AS uuid)
              )
            ORDER BY posting.reporting_period_id, resident.programme_code
            """
        ),
        params,
    )
    totals = {
        "reconciled_programme_periods": 0,
        "programme_scopes_created": 0,
        "pending_mappings_created": 0,
    }
    for row in result.mappings().all():
        counts = await reconcile_teaching_name_programme_scopes(
            db,
            reporting_period_id=row["reporting_period_id"],
            programme_code=row["programme_code"],
        )
        totals["reconciled_programme_periods"] += 1
        totals["programme_scopes_created"] += counts["programme_scopes_created"]
        totals["pending_mappings_created"] += counts["pending_mappings_created"]
    return totals


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
    teaching_name_reconciliation = None
    if "programme_code" in changed:
        teaching_name_reconciliation = await _reconcile_teaching_name_scopes_for_resident(
            db,
            resident_id=row_id,
        )
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
            **(
                {"teaching_name_reconciliation": teaching_name_reconciliation}
                if teaching_name_reconciliation is not None
                else {}
            ),
        },
    )
    await db.commit()
    cache_invalidation.invalidate_after_live_data_correction(
        entity_type="resident",
        entity_id=row_id,
        resident_id=row_id,
        programme_code=after.get("programme_code"),
        mcr=after.get("mcr"),
    )
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
    await reclassify_attendance_loa(
        db,
        reporting_period_id=after["reporting_period_id"],
        resident_id=after["resident_id"],
    )
    teaching_name_reconciliation = await _reconcile_teaching_name_scopes_for_resident(
        db,
        resident_id=after["resident_id"],
        reporting_period_id=after["reporting_period_id"],
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
            "teaching_name_reconciliation": teaching_name_reconciliation,
        },
    )
    await db.commit()
    cache_invalidation.invalidate_after_live_data_correction(
        entity_type="resident_posting",
        entity_id=row_id,
        resident_id=after.get("resident_id"),
        reporting_period_id=after.get("reporting_period_id"),
        programme_code=after.get("programme_code"),
        posting_code=after.get("posting_code"),
    )
    return {
        "item": _row_dict(after),
        "audit_log_id": audit["id"],
        "entity_type": "resident_posting",
        "entity_id": str(row_id),
        "updated_fields": updated_fields,
        "data_revalidation": data_revalidation,
    }


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
    scope_row = await _snapshot_teaching_target(
        db,
        row_id=row_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    try:
        if not await acquire_ttf_scope_lock(
            db,
            reporting_period_id=scope_row["reporting_period_id"],
            programme_code=str(scope_row["programme_code"]),
        ):
            _raise_validation(
                "A TTF target change for this reporting period and programme is already in progress",
                status_code=409,
            )

        # Re-read under the shared lock so an upload or another correction that
        # completed while this request was waiting cannot be overwritten from a
        # stale snapshot.
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
        await _validate_teaching_target_changes(
            db,
            merged=merged,
            changed=changed,
        )
        semantic_changed_fields = sorted(
            {
                "monthly_target",
                "is_tracked",
                "is_reallocatable",
                "tag",
            }
            & set(changed)
        )
        target_semantic_impact = {
            "mappings_with_target_semantics_changed": 0,
            "affected_event_count": 0,
            "affected_attendance_count": 0,
        }
        if semantic_changed_fields:
            raw_target_impact = await stable_target_mapping_impact_counts(
                db,
                target_ids=[row_id],
            )
            target_semantic_impact = {
                "mappings_with_target_semantics_changed": raw_target_impact[
                    "mapped_target_count"
                ],
                "affected_event_count": raw_target_impact["affected_event_count"],
                "affected_attendance_count": raw_target_impact[
                    "affected_attendance_count"
                ],
            }
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
            source_metadata={
                "target_semantic_changed_fields": semantic_changed_fields,
                "target_semantic_impact": target_semantic_impact,
            },
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
                "target_semantic_changed_fields": semantic_changed_fields,
                "target_semantic_impact": target_semantic_impact,
                "data_revalidation": data_revalidation,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    try:
        cache_invalidation.invalidate_after_live_data_correction(
            entity_type="teaching_target",
            entity_id=row_id,
            reporting_period_id=after.get("reporting_period_id"),
            programme_code=after.get("programme_code"),
            posting_code=after.get("posting_code"),
        )
    except Exception as exc:
        log_safe_exception(
            logger,
            "teaching_target_correction_cache_invalidation_failed",
            exc,
            category="cache_invalidation",
        )
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
    cache_invalidation.invalidate_after_live_data_correction(
        entity_type="form_f1_record",
        entity_id=row_id,
        reporting_period_id=after.get("reporting_period_id"),
        programme_code=after.get("programme_code"),
        mcr=after.get("mcr"),
    )
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
    cache_invalidation.invalidate_after_live_data_correction(
        entity_type="academic_month_boundary",
        entity_id=row_id,
    )
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
    await reclassify_attendance_loa(
        db,
        reporting_period_id=before_rows[0]["reporting_period_id"],
        resident_id=before_rows[0]["resident_id"],
    )
    teaching_name_reconciliation = await _reconcile_teaching_name_scopes_for_resident(
        db,
        resident_id=before_rows[0]["resident_id"],
        reporting_period_id=before_rows[0]["reporting_period_id"],
    )
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
        "teaching_name_reconciliation": teaching_name_reconciliation,
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
    cache_invalidation.invalidate_after_live_data_correction(
        entity_type="resident_posting_source_cell",
        entity_id=affected_ids[0] if affected_ids else None,
        resident_id=before_rows[0].get("resident_id"),
        reporting_period_id=before_rows[0].get("reporting_period_id"),
        programme_code=before_rows[0].get("programme_code"),
    )
    return {
        "before_rows": [_row_dict(row) for row in before_rows],
        "after_rows": [_row_dict(row) for row in after_rows],
        "audit_log_id": audit["id"],
        "entity_type": "resident_posting_source_cell",
        "entity_id": affected_ids[0],
        "updated_fields": sorted(_RESIDENT_POSTING_ALLOWED_FIELDS),
        "data_revalidation": data_revalidation,
    }


_SOURCE_CELL_MANUAL_NEXT_ACTION = (
    "Review the preview/apply result, then manually resolve the warning if the source issue is fixed."
)
_RDB_SOURCE_CELL_WARNING_TYPES = {
    "empty_posting_cell",
    "unmatched_multi_posting",
}


def _parse_source_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _source_payload_dates(source_payload: dict[str, Any]) -> tuple[date | None, date | None]:
    candidates = [
        source_payload,
        source_payload.get("source_trace") if isinstance(source_payload.get("source_trace"), dict) else {},
    ]
    for payload in candidates:
        start = (
            _parse_source_date(payload.get("phase_start"))
            or _parse_source_date(payload.get("start_date"))
            or _parse_source_date(payload.get("fragment_start_date"))
        )
        end = (
            _parse_source_date(payload.get("phase_end"))
            or _parse_source_date(payload.get("end_date"))
            or _parse_source_date(payload.get("fragment_end_date"))
        )
        if start is not None and end is not None:
            return start, end
    return None, None


def _source_payload_posting_codes(source_payload: dict[str, Any]) -> list[str]:
    values = source_payload.get("posting_codes") or source_payload.get("postingCodes") or []
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


async def _fetch_warning_source_context(
    db: AsyncSession,
    *,
    warning_issue_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"warning_issue_id": str(warning_issue_id)}
    scope_sql = _scope_filter_sql(
        column_sql="wi.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* rdb_source_cell_warning:context */
            SELECT
                wi.id AS issue_id,
                wi.fingerprint AS issue_fingerprint,
                wi.warning_type AS issue_warning_type,
                wi.severity AS issue_severity,
                wi.status AS issue_status,
                wi.reporting_period_id AS issue_reporting_period_id,
                wi.programme_code AS issue_programme_code,
                wi.resident_id AS issue_resident_id,
                wi.mcr AS issue_mcr,
                wi.month_label AS issue_month_label,
                uw.id AS warning_id,
                uw.upload_log_id AS warning_upload_log_id,
                uw.warning_type AS warning_warning_type,
                uw.severity AS warning_severity,
                uw.reporting_period_id AS warning_reporting_period_id,
                uw.programme_code AS warning_programme_code,
                uw.resident_id AS warning_resident_id,
                uw.mcr AS warning_mcr,
                uw.resident_name AS warning_resident_name,
                uw.month_label AS warning_month_label,
                uw.sheet_name AS warning_sheet_name,
                uw.row_number AS warning_row_number,
                uw.cell_ref AS warning_cell_ref,
                uw.source_payload AS warning_source_payload,
                uw.message AS warning_message,
                uw.suggested_action AS warning_suggested_action,
                uw.fingerprint AS warning_fingerprint,
                uw.created_at AS warning_created_at,
                ul.upload_type,
                ul.uploaded_at,
                ul.summary AS upload_summary
            FROM warning_issues wi
            JOIN LATERAL (
                SELECT *
                FROM upload_warnings latest_uw
                WHERE latest_uw.issue_id = wi.id
                ORDER BY latest_uw.created_at DESC, latest_uw.id DESC
                LIMIT 1
            ) uw ON TRUE
            JOIN upload_logs ul ON ul.id = uw.upload_log_id
            WHERE wi.id = :warning_issue_id
            {scope_sql}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    context = dict(row)
    source_payload = _parse_json_field(context.get("warning_source_payload"))
    if not isinstance(source_payload, dict):
        source_payload = {}
    context["warning_source_payload"] = source_payload
    return context


def _warning_source_trace(context: dict[str, Any]) -> dict[str, Any]:
    source_payload = context.get("warning_source_payload")
    if not isinstance(source_payload, dict):
        source_payload = {}
    reporting_period_id = (
        context.get("warning_reporting_period_id")
        or context.get("issue_reporting_period_id")
    )
    programme_code = context.get("warning_programme_code") or context.get("issue_programme_code")
    mcr = context.get("warning_mcr") or context.get("issue_mcr")
    resident_name = context.get("warning_resident_name")
    month_label = context.get("warning_month_label") or context.get("issue_month_label")
    return {
        "reporting_period_id": str(reporting_period_id) if reporting_period_id else None,
        "programme_code": programme_code,
        "mcr": mcr,
        "resident_name": resident_name,
        "month_label": month_label,
        "sheet_name": context.get("warning_sheet_name"),
        "row_number": context.get("warning_row_number"),
        "cell_ref": context.get("warning_cell_ref"),
        "source_payload": _json_ready(source_payload),
    }


def _validate_warning_stale_context(
    context: dict[str, Any],
    *,
    upload_warning_id: UUID | None,
    expected_latest_upload_warning_id: UUID | None,
    expected_fingerprint: str | None,
) -> None:
    latest_upload_warning_id = str(context["warning_id"])
    if upload_warning_id is not None and str(upload_warning_id) != latest_upload_warning_id:
        _raise_validation(
            "upload_warning_id is not the latest occurrence for this warning issue",
            status_code=409,
        )
    if (
        expected_latest_upload_warning_id is not None
        and str(expected_latest_upload_warning_id) != latest_upload_warning_id
    ):
        _raise_validation(
            "warning issue has a newer upload warning occurrence",
            status_code=409,
        )
    fingerprint = str(context.get("issue_fingerprint") or context.get("warning_fingerprint"))
    if expected_fingerprint is not None and expected_fingerprint != fingerprint:
        _raise_validation("warning fingerprint does not match latest context", status_code=409)


async def _fetch_source_cell_resident(
    db: AsyncSession,
    *,
    mcr: str,
    programme_code: str,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"mcr": mcr, "programme_code": programme_code}
    scope_sql = _scope_filter_sql(
        column_sql="programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
        params=params,
    )
    result = await db.execute(
        text(
            f"""
            /* rdb_source_cell_warning:resident_by_mcr */
            SELECT id, name, mcr, programme_code, r_year
            FROM residents
            WHERE UPPER(mcr) = UPPER(:mcr)
              AND programme_code = :programme_code
            {scope_sql}
            LIMIT 1
            """
        ),
        params,
    )
    resident = result.mappings().one_or_none()
    if resident is None:
        _raise_validation("warning resident could not be resolved in admin scope")
    return dict(resident)


async def _fetch_source_cell_programme_config(
    db: AsyncSession,
    *,
    programme_code: str,
) -> ProgrammeConfig:
    result = await db.execute(
        text(
            """
            SELECT code, r_year_required, is_subspecialty
            FROM programmes
            WHERE code = :programme_code
            LIMIT 1
            """
        ),
        {"programme_code": programme_code},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_validation("programme_code from warning source could not be resolved")
    return ProgrammeConfig(
        code=str(row["code"]),
        r_year_required=bool(row["r_year_required"]),
        is_subspecialty=bool(row["is_subspecialty"]),
    )


async def _resolve_warning_source_phase(
    db: AsyncSession,
    *,
    resident_id: str,
    reporting_period_id: str,
    programme_code: str,
    month_label: str | None,
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    phase_start, phase_end = _source_payload_dates(source_payload)
    if phase_start is not None and phase_end is not None:
        return {
            "phase_start": phase_start,
            "phase_end": phase_end,
            "r_year": source_payload.get("r_year"),
            "source_column_header": source_payload.get("source_column_header"),
            "phase_source": "warning_source_payload",
        }

    if month_label:
        result = await db.execute(
            text(
                """
                /* rdb_source_cell_warning:phase_from_rows */
                SELECT
                    MIN(start_date) AS start_date,
                    MAX(end_date) AS end_date,
                    MIN(r_year) AS r_year
                FROM resident_postings
                WHERE resident_id = :resident_id
                  AND reporting_period_id = :reporting_period_id
                  AND month_label = :month_label
                """
            ),
            {
                "resident_id": resident_id,
                "reporting_period_id": reporting_period_id,
                "month_label": month_label,
            },
        )
        row = result.mappings().one_or_none()
        if row is not None and row.get("start_date") is not None and row.get("end_date") is not None:
            return {
                "phase_start": row["start_date"],
                "phase_end": row["end_date"],
                "r_year": row.get("r_year"),
                "source_column_header": source_payload.get("source_column_header"),
                "phase_source": "resident_postings",
            }

        result = await db.execute(
            text(
                """
                /* rdb_source_cell_warning:phase_from_academic_boundary */
                SELECT amb.start_date, amb.end_date
                FROM academic_month_boundaries amb
                JOIN programmes p ON p.ay_date_category = amb.ay_date_category
                JOIN reporting_periods rp ON rp.id = :reporting_period_id
                WHERE p.code = :programme_code
                  AND amb.month_label = :month_label
                  AND amb.start_date <= rp.end_date
                  AND amb.end_date >= rp.start_date
                ORDER BY amb.start_date ASC, amb.end_date ASC
                LIMIT 1
                """
            ),
            {
                "programme_code": programme_code,
                "reporting_period_id": reporting_period_id,
                "month_label": month_label,
            },
        )
        boundary = result.mappings().one_or_none()
        if boundary is not None:
            return {
                "phase_start": boundary["start_date"],
                "phase_end": boundary["end_date"],
                "r_year": source_payload.get("r_year"),
                "source_column_header": source_payload.get("source_column_header"),
                "phase_source": "academic_month_boundaries",
            }

    return {
        "phase_start": None,
        "phase_end": None,
        "r_year": source_payload.get("r_year"),
        "source_column_header": source_payload.get("source_column_header"),
        "phase_source": "unresolved",
    }


def _candidate_row_from_posting(
    posting: ResidentPostingWrite,
    *,
    resident_id: str,
) -> dict[str, Any]:
    return {
        "resident_id": resident_id,
        "posting_code": posting.posting_code,
        "reporting_period_id": str(posting.reporting_period_id),
        "start_date": posting.start_date,
        "end_date": posting.end_date,
        "day_part": posting.day_part,
        "month_label": posting.month_label,
        "r_year": posting.r_year or "ALL",
        "status": posting.status,
        "loa_type": posting.loa_type,
        "loa_start_date": posting.loa_start_date,
        "loa_end_date": posting.loa_end_date,
        "refresher_training_type": posting.refresher_training_type,
        "refresher_training_start": posting.refresher_training_start,
        "refresher_training_end": posting.refresher_training_end,
        "active_months_weight": posting.active_months_weight,
        "working_days_in_month": posting.working_days_in_month,
    }


async def _insert_missing_posting_codes_for_source_cell(
    db: AsyncSession,
    *,
    posting_codes: set[str],
) -> None:
    for code in sorted(code for code in posting_codes if code):
        await db.execute(
            text(
                """
                INSERT INTO posting_codes (code, display_name)
                VALUES (:code, NULL)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code},
        )


async def _preview_warning_source_cell_replacement(
    db: AsyncSession,
    *,
    warning_issue_id: UUID,
    replacement_raw_cell_value: Any,
    upload_warning_id: UUID | None,
    expected_latest_upload_warning_id: UUID | None,
    expected_fingerprint: str | None,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    context = await _fetch_warning_source_context(
        db,
        warning_issue_id=warning_issue_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    if context is None:
        _raise_not_found("warning issue")
    warning_type = context.get("issue_warning_type") or context.get("warning_warning_type")
    if context.get("upload_type") != "rdb" or warning_type not in _RDB_SOURCE_CELL_WARNING_TYPES:
        _raise_validation("source-cell replacement is only available for RDB source-cell warnings")
    _validate_warning_stale_context(
        context,
        upload_warning_id=upload_warning_id,
        expected_latest_upload_warning_id=expected_latest_upload_warning_id,
        expected_fingerprint=expected_fingerprint,
    )

    source_trace = _warning_source_trace(context)
    reporting_period_id = source_trace.get("reporting_period_id")
    programme_code = source_trace.get("programme_code")
    mcr = source_trace.get("mcr")
    month_label = source_trace.get("month_label")
    if not reporting_period_id or not programme_code or not mcr:
        _raise_validation("warning source trace is missing reporting period, programme, or MCR")

    resident = await _fetch_source_cell_resident(
        db,
        mcr=mcr,
        programme_code=programme_code,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    source_payload = context.get("warning_source_payload")
    if not isinstance(source_payload, dict):
        source_payload = {}
    phase = await _resolve_warning_source_phase(
        db,
        resident_id=str(resident["id"]),
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        month_label=month_label,
        source_payload=source_payload,
    )
    programme = await _fetch_source_cell_programme_config(db, programme_code=programme_code)
    r_year = (
        _source_metadata_value(phase.get("r_year"))
        or resolve_r_year(str(resident.get("r_year") or ""), programme)
        or "ALL"
    )
    parse_result = await parse_rdb_source_cell_replacement(
        db_session=db,
        raw_value=replacement_raw_cell_value,
        reporting_period_id=UUID(reporting_period_id),
        resident_mcr=mcr,
        resident_name=source_trace.get("resident_name") or resident.get("name") or "",
        programme_code=programme_code,
        r_year=r_year,
        month_label=month_label,
        phase_start=phase.get("phase_start"),
        phase_end=phase.get("phase_end"),
        sheet_name=source_trace.get("sheet_name"),
        row_number=source_trace.get("row_number"),
        cell_ref=source_trace.get("cell_ref"),
        source_column_header=phase.get("source_column_header") or month_label,
    )
    candidate_rows = [
        _candidate_row_from_posting(posting, resident_id=str(resident["id"]))
        for posting in parse_result.candidate_postings
    ]
    data_revalidation_context = DataRevalidationContext(
        trigger_source=DataRevalidationTriggerSource.LIVE_DATA_CORRECTION,
        changed_entity=DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT,
        action=DataRevalidationAction.REPLACE,
        scope=DataRevalidationScope.RESIDENT_MONTH,
        entity_id=str(warning_issue_id),
        resident_id=str(resident["id"]),
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        changed_fields=["source_cell_preview"],
        source_metadata={
            "warning_issue_id": str(warning_issue_id),
            "upload_warning_id": str(context["warning_id"]),
            "fingerprint": str(context.get("issue_fingerprint") or context.get("warning_fingerprint")),
            "candidate_row_count": len(candidate_rows),
            "parser_error_count": len(parse_result.errors),
            "phase_source": phase.get("phase_source"),
        },
    )
    data_revalidation = await data_revalidation_service.preview_resident_posting_source_cell_revalidation(
        context=data_revalidation_context,
        db_session=db,
    )
    return {
        "context": context,
        "resident": resident,
        "phase": phase,
        "parse_result": parse_result,
        "candidate_rows": candidate_rows,
        "source_trace": source_trace,
        "data_revalidation": data_revalidation,
    }


async def preview_warning_source_cell_replacement(
    db: AsyncSession,
    *,
    warning_issue_id: UUID,
    replacement_raw_cell_value: Any,
    upload_warning_id: UUID | None,
    expected_latest_upload_warning_id: UUID | None,
    expected_fingerprint: str | None,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    preview = await _preview_warning_source_cell_replacement(
        db,
        warning_issue_id=warning_issue_id,
        replacement_raw_cell_value=replacement_raw_cell_value,
        upload_warning_id=upload_warning_id,
        expected_latest_upload_warning_id=expected_latest_upload_warning_id,
        expected_fingerprint=expected_fingerprint,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    context = preview["context"]
    parse_result = preview["parse_result"]
    return {
        "warning_issue_id": str(context["issue_id"]),
        "upload_warning_id": str(context["warning_id"]),
        "latest_upload_warning_id": str(context["warning_id"]),
        "fingerprint": str(context.get("issue_fingerprint") or context.get("warning_fingerprint")),
        "source_trace": preview["source_trace"],
        "source_payload": preview["source_trace"].get("source_payload") or {},
        "original_warning_type": context.get("issue_warning_type") or context.get("warning_warning_type"),
        "original_warning_status": context.get("issue_status"),
        "replacement_raw_cell_value": replacement_raw_cell_value,
        "normalized_cell_value": parse_result.normalized_value,
        "parsed_candidate_rows": [_row_dict(row) for row in preview["candidate_rows"]],
        "parser_warnings": _json_ready(parse_result.warnings),
        "parser_errors": _json_ready(parse_result.errors),
        "apply_allowed": not parse_result.errors,
        "data_revalidation": preview["data_revalidation"],
        "suggested_next_action": _SOURCE_CELL_MANUAL_NEXT_ACTION,
        "next_actions": [_SOURCE_CELL_MANUAL_NEXT_ACTION],
    }


async def _fetch_warning_source_affected_rows(
    db: AsyncSession,
    *,
    resident_id: str,
    reporting_period_id: str,
    month_label: str | None,
    phase_start: date | None,
    phase_end: date | None,
    posting_codes: list[str],
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            /* rdb_source_cell_warning:affected_rows */
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
            WHERE rp.resident_id = :resident_id
              AND rp.reporting_period_id = :reporting_period_id
              AND (:month_label IS NULL OR rp.month_label = :month_label)
              AND (:phase_start IS NULL OR rp.start_date = :phase_start)
              AND (:phase_end IS NULL OR rp.end_date = :phase_end)
              AND (:filter_posting_codes = false OR rp.posting_code = ANY(:posting_codes))
            ORDER BY rp.start_date ASC, rp.day_part ASC NULLS FIRST, rp.id ASC
            """
        ),
        {
            "resident_id": resident_id,
            "reporting_period_id": reporting_period_id,
            "month_label": month_label,
            "phase_start": phase_start,
            "phase_end": phase_end,
            "filter_posting_codes": bool(posting_codes),
            "posting_codes": posting_codes,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _lock_warning_source_cell_scope(
    db: AsyncSession,
    *,
    resident_id: str,
    reporting_period_id: str,
    month_label: str | None,
) -> None:
    await db.execute(
        text(
            """
            /* rdb_source_cell_warning:lock_resident_month */
            SELECT rp.id
            FROM resident_postings rp
            WHERE rp.resident_id = :resident_id
              AND rp.reporting_period_id = :reporting_period_id
              AND (:month_label IS NULL OR rp.month_label = :month_label)
            FOR UPDATE
            """
        ),
        {
            "resident_id": resident_id,
            "reporting_period_id": reporting_period_id,
            "month_label": month_label,
        },
    )


async def apply_warning_source_cell_replacement(
    db: AsyncSession,
    *,
    warning_issue_id: UUID,
    replacement_raw_cell_value: Any,
    correction_reason: str,
    upload_warning_id: UUID | None,
    expected_latest_upload_warning_id: UUID | None,
    expected_fingerprint: str | None,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    preview = await _preview_warning_source_cell_replacement(
        db,
        warning_issue_id=warning_issue_id,
        replacement_raw_cell_value=replacement_raw_cell_value,
        upload_warning_id=upload_warning_id,
        expected_latest_upload_warning_id=expected_latest_upload_warning_id,
        expected_fingerprint=expected_fingerprint,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    context = preview["context"]
    resident = preview["resident"]
    parse_result = preview["parse_result"]
    candidate_rows = preview["candidate_rows"]
    source_trace = preview["source_trace"]
    phase = preview["phase"]
    if parse_result.errors:
        _raise_validation("replacement source cell could not be parsed")

    reporting_period_id = str(source_trace["reporting_period_id"])
    month_label = source_trace.get("month_label")
    source_payload = context.get("warning_source_payload")
    if not isinstance(source_payload, dict):
        source_payload = {}
    posting_codes = _source_payload_posting_codes(source_payload)
    affected_phase_start = None if posting_codes else phase.get("phase_start")
    affected_phase_end = None if posting_codes else phase.get("phase_end")

    await _lock_warning_source_cell_scope(
        db,
        resident_id=str(resident["id"]),
        reporting_period_id=reporting_period_id,
        month_label=month_label,
    )
    before_rows = await _fetch_warning_source_affected_rows(
        db,
        resident_id=str(resident["id"]),
        reporting_period_id=reporting_period_id,
        month_label=month_label,
        phase_start=affected_phase_start,
        phase_end=affected_phase_end,
        posting_codes=posting_codes,
    )
    await _insert_missing_posting_codes_for_source_cell(
        db,
        posting_codes={
            str(row["posting_code"])
            for row in candidate_rows
            if row.get("posting_code")
        },
    )
    for row in candidate_rows:
        await _validate_resident_posting_payload(
            db,
            row=row,
            programme_scope=programme_scope,
            master_admin=master_admin,
        )
    affected_ids = [str(row["id"]) for row in before_rows]
    await _validate_source_cell_replacement_uniqueness(
        db,
        replacement_rows=candidate_rows,
        affected_ids=affected_ids,
    )
    if affected_ids:
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
    for row in candidate_rows:
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
    await reclassify_attendance_loa(
        db,
        reporting_period_id=reporting_period_id,
        resident_id=resident["id"],
    )
    teaching_name_reconciliation = await _reconcile_teaching_name_scopes_for_resident(
        db,
        resident_id=resident["id"],
        reporting_period_id=reporting_period_id,
    )
    data_revalidation = await _revalidate_live_data_correction(
        db,
        actor=actor,
        changed_entity=DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT,
        action=DataRevalidationAction.REPLACE,
        scope=DataRevalidationScope.RESIDENT_MONTH,
        entity_id=affected_ids[0] if affected_ids else str(warning_issue_id),
        resident_id=str(resident["id"]),
        reporting_period_id=reporting_period_id,
        programme_code=source_trace.get("programme_code"),
        changed_fields=["source_cell_replacement"],
        correction_reason=correction_reason,
        source_metadata={
            "warning_issue_id": str(warning_issue_id),
            "upload_warning_id": str(context["warning_id"]),
            "fingerprint": str(context.get("issue_fingerprint") or context.get("warning_fingerprint")),
            "affected_row_count": len(before_rows),
            "replacement_row_count": len(after_rows),
            "source_trace": source_trace,
        },
    )
    metadata = {
        "correction_reason": correction_reason,
        "updated_fields": sorted(_RESIDENT_POSTING_ALLOWED_FIELDS),
        "affected_resident_posting_ids": affected_ids,
        "replacement_resident_posting_ids": inserted_ids,
        "programme_code": source_trace.get("programme_code"),
        "resident_id": str(resident["id"]),
        "reporting_period_id": reporting_period_id,
        "warning_issue_id": str(warning_issue_id),
        "upload_warning_id": str(context["warning_id"]),
        "fingerprint": str(context.get("issue_fingerprint") or context.get("warning_fingerprint")),
        "before_source_payload": source_trace.get("source_payload"),
        "after_raw_cell_value": replacement_raw_cell_value,
        "normalized_cell_value": parse_result.normalized_value,
        "parsed_row_summary": [_row_dict(row) for row in candidate_rows],
        "source_trace": source_trace,
        "parser_warnings": _json_ready(parse_result.warnings),
        "data_revalidation": data_revalidation,
        "teaching_name_reconciliation": teaching_name_reconciliation,
    }
    audit = await _write_correction_audit(
        db,
        actor=actor,
        action="admin.parsed_data.resident_posting.source_cell_replace",
        entity_type="resident_posting_source_cell",
        entity_id=affected_ids[0] if affected_ids else str(warning_issue_id),
        before={"before_rows": [_row_dict(row) for row in before_rows]},
        after={"after_rows": [_row_dict(row) for row in after_rows]},
        metadata=metadata,
    )
    await db.commit()
    cache_invalidation.invalidate_after_source_cell_apply(
        resident_id=resident["id"],
        reporting_period_id=reporting_period_id,
        programme_code=source_trace.get("programme_code"),
        warning_issue_id=warning_issue_id,
        upload_warning_id=context["warning_id"],
        mcr=source_trace.get("mcr"),
    )
    return {
        "warning_issue_id": str(context["issue_id"]),
        "upload_warning_id": str(context["warning_id"]),
        "latest_upload_warning_id": str(context["warning_id"]),
        "fingerprint": str(context.get("issue_fingerprint") or context.get("warning_fingerprint")),
        "source_trace": source_trace,
        "source_payload": source_trace.get("source_payload") or {},
        "original_warning_type": context.get("issue_warning_type") or context.get("warning_warning_type"),
        "warning_issue_status": context.get("issue_status"),
        "replacement_raw_cell_value": replacement_raw_cell_value,
        "normalized_cell_value": parse_result.normalized_value,
        "before_rows": [_row_dict(row) for row in before_rows],
        "after_rows": [_row_dict(row) for row in after_rows],
        "replacement_summary": {
            "rows_deleted": len(before_rows),
            "rows_inserted": len(after_rows),
        },
        "parser_warnings": _json_ready(parse_result.warnings),
        "parser_errors": _json_ready(parse_result.errors),
        "audit_log_id": audit["id"],
        "entity_type": "resident_posting_source_cell",
        "entity_id": affected_ids[0] if affected_ids else str(warning_issue_id),
        "updated_fields": sorted(_RESIDENT_POSTING_ALLOWED_FIELDS),
        "data_revalidation": data_revalidation,
        "suggested_next_action": _SOURCE_CELL_MANUAL_NEXT_ACTION,
        "next_actions": [_SOURCE_CELL_MANUAL_NEXT_ACTION],
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
        if field not in {"cell_ref", "row_number", "sheet_name", "upload_log_id"}:
            raise ValueError("Untrusted correction-history source field")
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
