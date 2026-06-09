from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


WARNING_SUMMARY_KEYS = {
    "mcr_not_found",
    "mcr_not_found_warnings",
    "orphaned_attendance",
    "promotion_date_warnings",
    "skipped_mcr_warnings",
    "tag_order_warnings",
    "unknown_loa_type",
    "unknown_loa_types",
    "unmatched_multi_posting",
    "warnings",
}
ARRAY_COUNT_KEYS = {
    "posting_codes_added",
    "promotion_dates_parsed",
}


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
    values: list[str],
    params: dict[str, Any],
) -> str:
    fragments: list[str] = []
    for idx, value in enumerate(values):
        key = f"scope_programme_code_{idx}"
        params[key] = value
        fragments.append(f"ul.programme_code = :{key}")
    return "(" + " OR ".join(fragments) + ")"


def _build_filters(
    *,
    programme_scope: set[str],
    master_admin: bool,
    upload_type: str | None,
    status: str | None,
    programme_code: str | None,
    reporting_period_id: UUID | None,
    search: str | None,
) -> tuple[list[str], dict[str, Any]]:
    _validate_programme_filter(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )

    params: dict[str, Any] = {}
    where_clauses: list[str] = []

    if upload_type:
        params["upload_type"] = upload_type
        where_clauses.append("ul.upload_type = :upload_type")
    if status:
        params["status"] = status
        where_clauses.append("ul.status = :status")
    if programme_code:
        params["programme_code"] = programme_code
        where_clauses.append("ul.programme_code = :programme_code")
    if reporting_period_id:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("ul.reporting_period_id = :reporting_period_id")
    if search and search.strip():
        params["search"] = f"%{search.strip().lower()}%"
        where_clauses.append(
            """
            (
                LOWER(ul.upload_type) LIKE :search
                OR LOWER(ul.status) LIKE :search
                OR LOWER(COALESCE(ul.programme_code, '')) LIKE :search
                OR LOWER(COALESCE(u.name, '')) LIKE :search
                OR LOWER(CAST(ul.summary AS TEXT)) LIKE :search
            )
            """
        )

    if not master_admin:
        if not programme_scope:
            where_clauses.append("1 = 0")
        else:
            where_clauses.append("ul.upload_type = 'ttf'")
            where_clauses.append(
                _scope_or_clause(values=sorted(programme_scope), params=params)
            )

    return where_clauses, params


def _where_sql(where_clauses: list[str]) -> str:
    if not where_clauses:
        return ""
    return " WHERE " + " AND ".join(where_clauses)


def _coerce_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _count_value(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 1


def _is_error_key(key: str) -> bool:
    return key == "errors" or key.endswith("_errors")


def warning_count(summary: dict[str, Any]) -> int:
    return sum(
        _count_value(value)
        for key, value in summary.items()
        if key in WARNING_SUMMARY_KEYS
    )


def error_count(summary: dict[str, Any]) -> int:
    return sum(
        _count_value(value)
        for key, value in summary.items()
        if _is_error_key(key)
    )


def summary_counts(summary: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    excluded_keys = WARNING_SUMMARY_KEYS | {"errors"}
    for key, value in summary.items():
        if key in excluded_keys or _is_error_key(key):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            counts[key] = value
        elif isinstance(value, float) and value.is_integer():
            counts[key] = int(value)
        elif key in ARRAY_COUNT_KEYS and isinstance(value, list):
            counts[key] = len(value)
    return counts


def _original_filename(summary: dict[str, Any]) -> str | None:
    value = summary.get("original_filename")
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _display_row(row: dict[str, Any], *, include_summary: bool) -> dict[str, Any]:
    summary = _coerce_summary(row.get("summary"))
    output = {
        "id": row["id"],
        "upload_type": row["upload_type"],
        "uploaded_at": row["uploaded_at"],
        "uploaded_by": row.get("uploaded_by"),
        "uploaded_by_name": row.get("uploaded_by_name"),
        "status": row["status"],
        "reporting_period_id": row.get("reporting_period_id"),
        "reporting_period_label": row.get("reporting_period_label"),
        "programme_code": row.get("programme_code"),
        "warning_count": warning_count(summary),
        "error_count": error_count(summary),
        "summary_counts": summary_counts(summary),
    }
    if include_summary:
        output["summary"] = summary
        output["original_filename"] = _original_filename(summary)
    return output


async def list_upload_logs(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    upload_type: str | None = None,
    status: str | None = None,
    programme_code: str | None = None,
    reporting_period_id: UUID | None = None,
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
) -> dict[str, Any]:
    where_clauses, params = _build_filters(
        programme_scope=programme_scope,
        master_admin=master_admin,
        upload_type=upload_type,
        status=status,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        search=search,
    )
    where_sql = _where_sql(where_clauses)

    count_result = await db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM upload_logs ul
            LEFT JOIN users u ON u.id = ul.uploaded_by
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
            SELECT
                ul.id,
                ul.upload_type,
                ul.uploaded_by,
                u.name AS uploaded_by_name,
                ul.uploaded_at,
                ul.reporting_period_id,
                rp.label AS reporting_period_label,
                ul.programme_code,
                ul.status,
                ul.summary
            FROM upload_logs ul
            LEFT JOIN users u ON u.id = ul.uploaded_by
            LEFT JOIN reporting_periods rp ON rp.id = ul.reporting_period_id
            {where_sql}
            ORDER BY ul.uploaded_at DESC, ul.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        query_params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    return {
        "items": [_display_row(row, include_summary=False) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def get_upload_log(
    db: AsyncSession,
    *,
    upload_log_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    where_clauses, params = _build_filters(
        programme_scope=programme_scope,
        master_admin=master_admin,
        upload_type=None,
        status=None,
        programme_code=None,
        reporting_period_id=None,
        search=None,
    )
    params["upload_log_id"] = str(upload_log_id)
    where_clauses.append("ul.id = :upload_log_id")
    where_sql = _where_sql(where_clauses)

    result = await db.execute(
        text(
            f"""
            SELECT
                ul.id,
                ul.upload_type,
                ul.uploaded_by,
                u.name AS uploaded_by_name,
                ul.uploaded_at,
                ul.reporting_period_id,
                rp.label AS reporting_period_label,
                ul.programme_code,
                ul.status,
                ul.summary
            FROM upload_logs ul
            LEFT JOIN users u ON u.id = ul.uploaded_by
            LEFT JOIN reporting_periods rp ON rp.id = ul.reporting_period_id
            {where_sql}
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    if not rows:
        raise ApiError(
            status_code=404,
            detail="Upload log not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return _display_row(rows[0], include_summary=True)
