from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


WARNING_SOURCE_TYPES = {
    "unmatched_multi_posting": "unmatched_multi_posting",
    "empty_posting_cell": "empty_posting_cell",
    "unknown_loa_type": "unknown_loa_type",
    "unknown_loa_types": "unknown_loa_types",
    "mcr_not_found": "mcr_not_found",
    "mcr_not_found_warnings": "mcr_not_found",
    "orphaned_attendance": "orphaned_attendance",
    "public_holiday_day_mismatch": "public_holiday_day_mismatch",
    "duplicate_mcr_error": "duplicate_mcr_error",
    "duplicate_mcr_errors": "duplicate_mcr_error",
    "tag_order_warnings": "tag_order_warning",
    "skipped_mcr_warnings": "skipped_mcr",
    "promotion_date_warnings": "promotion_date_warning",
    "warnings": "warning",
}

WARNING_SOURCE_KEYS = tuple(WARNING_SOURCE_TYPES)
ACTIVE_UPLOAD_STATUSES = {"success", "partial"}
CRITICAL_WARNING_TYPES = {
    "duplicate_mcr_error",
    "duplicate_mcr_errors",
    "unmatched_multi_posting",
}
WARNING_SEVERITY_TYPES = {
    "unknown_loa_type",
    "unknown_loa_types",
    "mcr_not_found",
    "mcr_not_found_warnings",
    "orphaned_attendance",
    "tag_order_warning",
    "tag_order_warnings",
    "skipped_mcr",
    "skipped_mcr_warnings",
    "promotion_date_warning",
    "promotion_date_warnings",
    "warning",
}
INFO_WARNING_TYPES = {
    "empty_posting_cell",
}
MCR_RE = re.compile(r"\b[A-Z]\d{4,6}[A-Z]\b", re.IGNORECASE)


@dataclass(slots=True)
class UploadWarningRow:
    warning_id: str
    upload_log_id: str
    dedupe_key: str
    upload_type: str
    uploaded_at: datetime
    uploaded_by: str | None
    reporting_period_id: str | None
    programme_code: str | None
    warning_type: str
    severity: str
    message: str
    resident_name: str | None = None
    mcr: str | None = None
    month_label: str | None = None
    sheet_name: str | None = None
    row_number: int | None = None
    cell_ref: str | None = None
    posting_codes: list[str] | None = None
    session_type: str | None = None
    count: int | None = None
    source_label: str | None = None
    raw_payload: Any = None
    seen_count: int = 1
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    upload_log_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["uploaded_at"] = self.uploaded_at
        payload["first_seen_at"] = self.first_seen_at or self.uploaded_at
        payload["last_seen_at"] = self.last_seen_at or self.uploaded_at
        if payload["posting_codes"] is None:
            payload["posting_codes"] = []
        if payload["upload_log_ids"] is None:
            payload["upload_log_ids"] = [self.upload_log_id]
        return payload


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, int | float):
        return str(value)
    return None


def _int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _list_string_values(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    values = [_string_value(item) for item in value]
    output = [item for item in values if item]
    return output or None


def _single_string_list(value: Any) -> list[str] | None:
    item = _string_value(value)
    return [item] if item else None


def _canonical_payload(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return repr(value)


def _normalise_key_part(value: Any) -> str:
    text_value = _string_value(value)
    if not text_value:
        return "-"
    return " ".join(text_value.lower().split())


def _normalise_key_mcr(value: str | None) -> str:
    return _normalise_key_part(value).upper().lower()


def _normalise_key_list(values: list[str] | None) -> str:
    if not values:
        return "-"
    normalised = sorted(_normalise_key_part(item) for item in values if _normalise_key_part(item) != "-")
    return ",".join(normalised) if normalised else "-"


def _stable_warning_id(
    *,
    upload_log_id: str,
    source_key: str,
    warning_index: int,
    raw_payload: Any,
) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                upload_log_id,
                source_key,
                str(warning_index),
                _canonical_payload(raw_payload),
            ]
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"{upload_log_id}:{source_key}:{warning_index}:{digest}"


def _extract_mcr_from_text(value: str | None) -> str | None:
    if not value:
        return None
    match = MCR_RE.search(value)
    return match.group(0).upper() if match else None


def _warning_type(source_key: str, payload: Any) -> str:
    if isinstance(payload, dict):
        explicit_type = _string_value(payload.get("type"))
        if explicit_type:
            return explicit_type
    return WARNING_SOURCE_TYPES[source_key]


def _severity_for(warning_type: str, source_key: str, explicit: str | None = None) -> str:
    if explicit:
        normalized_explicit = explicit.strip().lower()
        if normalized_explicit in {"critical", "warning", "info"}:
            return normalized_explicit
    normalized = warning_type.strip().lower()
    source = source_key.strip().lower()
    if normalized in INFO_WARNING_TYPES or source in INFO_WARNING_TYPES:
        return "info"
    if normalized in CRITICAL_WARNING_TYPES or source in CRITICAL_WARNING_TYPES:
        return "critical"
    if normalized in WARNING_SEVERITY_TYPES or source in WARNING_SEVERITY_TYPES:
        return "warning"
    if "duplicate" in normalized or normalized.endswith("_error"):
        return "critical"
    return "warning"


def _source_label(sheet_name: str | None, row_number: int | None, cell_ref: str | None) -> str:
    if not sheet_name and row_number is None and not cell_ref:
        return "Upload summary only"
    label = f"Sheet {sheet_name or 'Unknown'}"
    trace_parts: list[str] = []
    if row_number is not None:
        trace_parts.append(f"R{row_number}")
    if cell_ref:
        trace_parts.append(cell_ref)
    if trace_parts:
        label = f"{label}:{':'.join(trace_parts)}"
    return label


def _message_for(payload: Any, warning_type: str) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            message = _string_value(payload.get(key))
            if message:
                return message
        return _canonical_payload(payload)
    return _canonical_payload(payload) or warning_type


def _summary_sources(summary: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    sources: list[tuple[str, list[Any]]] = []
    containers = [summary]
    metadata = summary.get("metadata")
    if isinstance(metadata, dict):
        containers.append(metadata)

    for container in containers:
        for source_key in WARNING_SOURCE_KEYS:
            value = container.get(source_key)
            if isinstance(value, list):
                sources.append((source_key, value))
            elif value is not None:
                sources.append((source_key, [value]))
    return sources


def _normalise_payload(
    *,
    upload_log: dict[str, Any],
    source_key: str,
    warning_index: int,
    payload: Any,
) -> UploadWarningRow:
    upload_log_id = str(upload_log["id"])
    warning_type = _warning_type(source_key, payload)
    explicit_severity = (
        _string_value(payload.get("severity")) if isinstance(payload, dict) else None
    )

    if isinstance(payload, dict):
        resident_name = _string_value(payload.get("resident_name")) or _string_value(
            payload.get("residentName")
        )
        mcr = (_string_value(payload.get("mcr")) or _extract_mcr_from_text(_message_for(payload, warning_type)))
        programme_code = (
            _string_value(payload.get("programme_code"))
            or _string_value(payload.get("programmeCode"))
            or _string_value(upload_log.get("programme_code"))
        )
        month_label = (
            _string_value(payload.get("month_label"))
            or _string_value(payload.get("month"))
            or _string_value(payload.get("monthLabel"))
        )
        sheet_name = _string_value(payload.get("sheet_name")) or _string_value(payload.get("sheetName"))
        row_number = _int_value(payload.get("row_number")) or _int_value(payload.get("rowNumber"))
        cell_ref = (
            _string_value(payload.get("cell_ref"))
            or _string_value(payload.get("cell"))
            or _string_value(payload.get("cellRef"))
        )
        posting_codes = _list_string_values(payload.get("posting_codes")) or _list_string_values(
            payload.get("postingCodes")
        ) or _single_string_list(payload.get("posting_code")) or _single_string_list(
            payload.get("postingCode")
        )
        session_type = _string_value(payload.get("session_type")) or _string_value(
            payload.get("sessionType")
        )
        count = _int_value(payload.get("count"))
    else:
        message_text = _message_for(payload, warning_type)
        resident_name = None
        mcr = _extract_mcr_from_text(message_text)
        programme_code = _string_value(upload_log.get("programme_code"))
        month_label = None
        sheet_name = None
        row_number = None
        cell_ref = None
        posting_codes = None
        session_type = None
        count = None

    message = _message_for(payload, warning_type)
    return UploadWarningRow(
        warning_id=_stable_warning_id(
            upload_log_id=upload_log_id,
            source_key=source_key,
            warning_index=warning_index,
            raw_payload=payload,
        ),
        upload_log_id=upload_log_id,
        dedupe_key="",
        upload_type=str(upload_log["upload_type"]),
        uploaded_at=upload_log["uploaded_at"],
        uploaded_by=_string_value(upload_log.get("uploaded_by_name"))
        or _string_value(upload_log.get("uploaded_by")),
        reporting_period_id=_string_value(upload_log.get("reporting_period_id")),
        programme_code=programme_code,
        warning_type=warning_type,
        severity=_severity_for(warning_type, source_key, explicit_severity),
        message=message,
        resident_name=resident_name,
        mcr=mcr.upper() if mcr else None,
        month_label=month_label,
        sheet_name=sheet_name,
        row_number=row_number,
        cell_ref=cell_ref,
        posting_codes=posting_codes,
        session_type=session_type,
        count=count,
        source_label=_source_label(sheet_name, row_number, cell_ref),
        raw_payload=payload,
    )


def normalise_warning_rows_from_upload_log(upload_log: dict[str, Any]) -> list[UploadWarningRow]:
    summary = upload_log.get("summary")
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            return []
    if not isinstance(summary, dict):
        return []

    rows: list[UploadWarningRow] = []
    for source_key, payloads in _summary_sources(summary):
        for index, payload in enumerate(payloads):
            row = _normalise_payload(
                upload_log=upload_log,
                source_key=source_key,
                warning_index=index,
                payload=payload,
            )
            row.dedupe_key = _dedupe_key(row)
            rows.append(row)
    return rows


def _dedupe_key(row: UploadWarningRow) -> str:
    warning_type = _normalise_key_part(row.warning_type)
    upload_type = _normalise_key_part(row.upload_type)
    programme_code = _normalise_key_part(row.programme_code)
    mcr = _normalise_key_mcr(row.mcr)
    message = _normalise_key_part(row.message)

    if warning_type == "mcr_not_found":
        if mcr != "-":
            return "|".join(["mcr_not_found", upload_type, warning_type, mcr])

    if warning_type in {"unknown_loa_type", "unknown_loa_types"}:
        return "|".join(
            [
                "unknown_loa_type",
                upload_type,
                warning_type,
                message,
                programme_code,
            ]
        )

    if warning_type == "unmatched_multi_posting":
        posting_codes = _normalise_key_list(row.posting_codes)
        if programme_code != "-" and mcr != "-" and row.month_label and posting_codes != "-":
            return "|".join(
                [
                    "unmatched_multi_posting",
                    upload_type,
                    warning_type,
                    programme_code,
                    mcr,
                    _normalise_key_part(row.month_label),
                    posting_codes,
                ]
            )

    if warning_type == "orphaned_attendance":
        posting_codes = _normalise_key_list(row.posting_codes)
        if programme_code != "-" and posting_codes != "-" and row.session_type:
            return "|".join(
                [
                    "orphaned_attendance",
                    upload_type,
                    warning_type,
                    programme_code,
                    posting_codes,
                    _normalise_key_part(row.session_type),
                ]
            )

    if warning_type == "duplicate_mcr_error":
        return "|".join(
            [
                "duplicate_mcr_error",
                upload_type,
                warning_type,
                mcr if mcr != "-" else message,
            ]
        )

    return "|".join(
        [
            "generic",
            upload_type,
            warning_type,
            programme_code,
            mcr,
            _normalise_key_part(row.resident_name),
            _normalise_key_part(row.month_label),
            _normalise_key_part(row.sheet_name),
            _normalise_key_part(row.row_number),
            _normalise_key_part(row.cell_ref),
            _normalise_key_list(row.posting_codes),
            _normalise_key_part(row.session_type),
            message,
        ]
    )


def _dedupe_rows(rows: list[UploadWarningRow]) -> list[UploadWarningRow]:
    grouped: dict[str, list[UploadWarningRow]] = {}
    for row in rows:
        row.dedupe_key = _dedupe_key(row)
        grouped.setdefault(row.dedupe_key, []).append(row)

    representatives: list[UploadWarningRow] = []
    for dedupe_key, group in grouped.items():
        ordered = sorted(group, key=lambda item: (item.uploaded_at, item.upload_log_id))
        representative = ordered[-1]
        representative.dedupe_key = dedupe_key
        representative.seen_count = len(group)
        representative.first_seen_at = ordered[0].uploaded_at
        representative.last_seen_at = ordered[-1].uploaded_at
        representative.upload_log_ids = [item.upload_log_id for item in ordered]
        representatives.append(representative)

    return sorted(
        representatives,
        key=lambda item: (item.uploaded_at, item.warning_type, item.warning_id),
        reverse=True,
    )


def _replacement_scope_key(upload_log: dict[str, Any]) -> tuple[str, ...]:
    upload_type = _normalise_key_part(upload_log.get("upload_type"))
    reporting_period_id = _normalise_key_part(upload_log.get("reporting_period_id"))
    programme_code = _normalise_key_part(upload_log.get("programme_code"))

    if upload_type in {"rdb", "form_f1"}:
        return (upload_type, reporting_period_id)
    if upload_type == "ttf":
        return (upload_type, reporting_period_id, programme_code)
    if upload_type == "public_holidays":
        return (upload_type, "global")
    return (upload_type, reporting_period_id, programme_code)


def _latest_active_upload_logs(upload_logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_scope: dict[tuple[str, ...], dict[str, Any]] = {}
    for upload_log in upload_logs:
        status = _normalise_key_part(upload_log.get("status"))
        if status not in ACTIVE_UPLOAD_STATUSES:
            continue
        scope_key = _replacement_scope_key(upload_log)
        current = latest_by_scope.get(scope_key)
        if current is None or (
            upload_log.get("uploaded_at"),
            str(upload_log.get("id")),
        ) > (
            current.get("uploaded_at"),
            str(current.get("id")),
        ):
            latest_by_scope[scope_key] = upload_log

    return sorted(
        latest_by_scope.values(),
        key=lambda item: (item.get("uploaded_at"), str(item.get("id"))),
        reverse=True,
    )


def _matches_search(row: UploadWarningRow, search: str | None) -> bool:
    if not search:
        return True
    token = search.strip().lower()
    if not token:
        return True
    values: list[str] = [
        row.warning_type,
        row.message,
        row.resident_name or "",
        row.mcr or "",
        row.programme_code or "",
        row.month_label or "",
        row.sheet_name or "",
        row.cell_ref or "",
        row.source_label or "",
        " ".join(row.posting_codes or []),
    ]
    return token in " ".join(values).lower()


async def _resident_programmes_by_mcr(
    db: AsyncSession,
    mcr_values: set[str],
) -> dict[str, str]:
    if not mcr_values:
        return {}
    result = await db.execute(
        text(
            """
            SELECT UPPER(mcr) AS mcr, programme_code
            FROM residents
            WHERE UPPER(mcr) = ANY(:mcr_values)
            """
        ),
        {"mcr_values": sorted(mcr_values)},
    )
    rows = result.mappings().all()
    return {
        str(row["mcr"]).upper(): str(row["programme_code"])
        for row in rows
        if row.get("mcr") and row.get("programme_code")
    }


def _scope_warning_for_pc(
    row: UploadWarningRow,
    *,
    upload_log_programme_code: str | None,
    resident_programmes: dict[str, str],
    programme_scope: set[str],
) -> UploadWarningRow | None:
    if not programme_scope:
        return None
    scoped_code = row.programme_code or upload_log_programme_code
    if scoped_code:
        return row if scoped_code in programme_scope else None
    if row.mcr:
        resident_programme = resident_programmes.get(row.mcr.upper())
        if resident_programme in programme_scope:
            row.programme_code = resident_programme
            return row
    return None


async def list_upload_warnings(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    upload_type: str | None = None,
    severity: str | None = None,
    programme_code: str | None = None,
    warning_type: str | None = None,
    reporting_period_id: UUID | None = None,
    search: str | None = None,
    mode: str = "active",
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    where_clauses: list[str] = []
    if upload_type:
        params["upload_type"] = upload_type
        where_clauses.append("ul.upload_type = :upload_type")
    if reporting_period_id:
        params["reporting_period_id"] = str(reporting_period_id)
        where_clauses.append("ul.reporting_period_id = :reporting_period_id")
    sql = """
        SELECT
            ul.id,
            ul.upload_type,
            ul.uploaded_by,
            u.name AS uploaded_by_name,
            ul.uploaded_at,
            ul.reporting_period_id,
            ul.programme_code,
            ul.status,
            ul.summary,
            ul.created_at,
            ul.updated_at
        FROM upload_logs ul
        LEFT JOIN users u ON u.id = ul.uploaded_by
    """
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY ul.uploaded_at DESC, ul.id ASC"

    result = await db.execute(text(sql), params)
    upload_logs = [dict(row) for row in result.mappings().all()]
    if mode != "history":
        upload_logs = _latest_active_upload_logs(upload_logs)

    normalized: list[tuple[UploadWarningRow, str | None]] = []
    for upload_log in upload_logs:
        for row in normalise_warning_rows_from_upload_log(upload_log):
            normalized.append((row, _string_value(upload_log.get("programme_code"))))

    mcr_values = {row.mcr for row, _ in normalized if row.mcr}
    resident_programmes = await _resident_programmes_by_mcr(db, mcr_values)

    scoped_rows: list[UploadWarningRow] = []
    for row, upload_log_programme_code in normalized:
        if master_admin:
            scoped_rows.append(row)
        else:
            scoped = _scope_warning_for_pc(
                row,
                upload_log_programme_code=upload_log_programme_code,
                resident_programmes=resident_programmes,
                programme_scope=programme_scope,
            )
            if scoped is not None:
                scoped_rows.append(scoped)

    deduped_rows = _dedupe_rows(scoped_rows)

    if severity:
        deduped_rows = [row for row in deduped_rows if row.severity == severity]
    if warning_type:
        deduped_rows = [row for row in deduped_rows if row.warning_type == warning_type]
    if programme_code:
        deduped_rows = [row for row in deduped_rows if row.programme_code == programme_code]
    deduped_rows = [row for row in deduped_rows if _matches_search(row, search)]

    return [row.to_dict() for row in deduped_rows]
