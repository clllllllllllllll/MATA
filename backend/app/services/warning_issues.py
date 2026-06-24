from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
from app.services.audit import write_audit_log
from app.services import cache_invalidation
from app.services.upload_warnings import UploadWarningRow, normalise_warning_rows_from_upload_log


WARNING_ISSUE_STATUSES = {"unresolved", "resolved", "dismissed", "superseded", "reappeared"}
WARNING_ISSUE_SEVERITIES = {"critical", "warning", "info"}
REAPPEARABLE_STATUSES = {"resolved", "dismissed", "superseded"}
ACTION_TO_STATUS = {
    "resolve": "resolved",
    "dismiss": "dismissed",
    "supersede": "superseded",
}


class DurableWarningStoreUnavailable(RuntimeError):
    """Raised when the first-class warning tables are not available in a fake/old DB."""


@dataclass(slots=True)
class DerivationResult:
    upload_log_id: str | None
    issues_created: int = 0
    issues_updated: int = 0
    issues_reappeared: int = 0
    occurrences_created: int = 0
    occurrences_skipped: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return str(value)


def _canonical_payload(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return repr(value)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_payload(value).encode("utf-8")).hexdigest()[:24]


def _normalise_text(value: Any, *, preserve_case: bool = False) -> str:
    text_value = _string_value(value)
    if not text_value:
        return "-"
    compact = " ".join(text_value.split())
    return compact if preserve_case else compact.casefold()


def _normalise_mcr(value: Any) -> str:
    text_value = _string_value(value)
    return text_value.upper() if text_value else "-"


def _normalise_warning_type(value: Any) -> str:
    warning_type = _normalise_text(value)
    return {
        "unknown_loa_types": "unknown_loa_type",
        "mcr_not_found_warnings": "mcr_not_found",
        "skipped_mcr_warnings": "skipped_mcr",
        "promotion_date_warnings": "promotion_date_warning",
        "tag_order_warnings": "tag_order_warning",
    }.get(warning_type, warning_type)


def _normalise_posting_combo(values: Any) -> str:
    if not isinstance(values, list):
        return "-"
    normalized = sorted(
        item
        for item in (_normalise_text(value) for value in values)
        if item != "-"
    )
    return ",".join(normalized) if normalized else "-"


def _payload_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("raw_payload")
    return payload if isinstance(payload, dict) else {}


def compute_warning_fingerprint(row: Mapping[str, Any]) -> str:
    warning_type = _normalise_warning_type(row.get("warning_type"))
    payload = _payload_dict(row)
    reporting_period_id = _normalise_text(row.get("reporting_period_id"), preserve_case=True)
    programme_code = _normalise_text(row.get("programme_code"), preserve_case=True)
    mcr = _normalise_mcr(row.get("mcr"))
    month_label = _normalise_text(row.get("month_label"), preserve_case=True)

    if warning_type == "unmatched_multi_posting":
        posting_codes = row.get("posting_codes") or payload.get("posting_codes") or payload.get("postingCodes")
        return "|".join(
            [
                "unmatched_multi_posting",
                reporting_period_id,
                programme_code,
                mcr,
                month_label,
                _normalise_posting_combo(posting_codes),
            ]
        )

    if warning_type == "empty_posting_cell":
        return "|".join(
            ["empty_posting_cell", reporting_period_id, programme_code, mcr, month_label]
        )

    if warning_type == "unknown_loa_type":
        loa_type = (
            payload.get("loa_type")
            or payload.get("loaType")
            or payload.get("value")
            or row.get("message")
        )
        return "|".join(
            [
                "unknown_loa_type",
                reporting_period_id,
                programme_code,
                mcr,
                month_label,
                _normalise_text(loa_type),
            ]
        )

    if warning_type == "mcr_not_found":
        return "|".join(["mcr_not_found", reporting_period_id, mcr])

    if warning_type == "orphaned_attendance":
        posting_code = (
            payload.get("posting_code")
            or payload.get("postingCode")
            or (row.get("posting_codes") or [None])[0]
        )
        teaching_name = payload.get("teaching_name") or payload.get("teachingName")
        session_type = row.get("session_type") or payload.get("session_type") or payload.get("sessionType")
        return "|".join(
            [
                "orphaned_attendance",
                reporting_period_id,
                programme_code,
                _normalise_text(posting_code, preserve_case=True),
                _normalise_text(teaching_name),
                _normalise_text(session_type),
            ]
        )

    if warning_type == "tag_order_warning":
        posting_code = payload.get("posting_code") or payload.get("postingCode")
        tag_group = (
            payload.get("tag_family")
            or payload.get("tagFamily")
            or payload.get("tag_group")
            or payload.get("tagGroup")
            or row.get("message")
        )
        r_year = payload.get("r_year") or payload.get("rYear")
        return "|".join(
            [
                "tag_order_warning",
                reporting_period_id,
                programme_code,
                _normalise_text(posting_code, preserve_case=True),
                _normalise_text(r_year, preserve_case=True),
                _normalise_text(tag_group),
            ]
        )

    if warning_type == "public_holiday_day_mismatch":
        return "|".join(
            [
                "public_holiday_day_mismatch",
                _normalise_text(payload.get("holiday_date") or payload.get("holidayDate"), preserve_case=True),
                _normalise_text(payload.get("holiday_name") or payload.get("name")),
            ]
        )

    return "|".join(
        [
            warning_type,
            reporting_period_id,
            programme_code,
            _hash_payload(row.get("raw_payload") if "raw_payload" in row else dict(row)),
        ]
    )


def _suggested_action(row: UploadWarningRow) -> str | None:
    payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    explicit = _string_value(payload.get("suggested_action")) or _string_value(
        payload.get("suggestedAction")
    )
    if explicit:
        return explicit
    if row.warning_type == "empty_posting_cell":
        return "Check whether the RDB source cell is intentionally blank. If not, update the RDB source file and re-upload."
    if row.warning_type == "unmatched_multi_posting":
        return "Add or update the relevant multi-posting rule, or correct the RDB source file and re-upload."
    if row.warning_type == "mcr_not_found":
        return "Check whether the MCR should exist in the resident database before re-uploading."
    return None


def _row_payload(row: UploadWarningRow) -> dict[str, Any]:
    payload = row.to_dict()
    payload["warning_type"] = _normalise_warning_type(payload.get("warning_type"))
    payload["fingerprint"] = compute_warning_fingerprint(payload)
    return payload


def _sqlstate_from_exception(exc: BaseException) -> str | None:
    candidates = [exc, getattr(exc, "orig", None), getattr(exc, "__cause__", None)]
    for candidate in candidates:
        if candidate is None:
            continue
        for attribute in ("sqlstate", "pgcode", "code"):
            value = getattr(candidate, attribute, None)
            if value:
                return str(value)
    return None


def _is_missing_warning_table_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    mentions_warning_table = "warning_issues" in message or "upload_warnings" in message
    if isinstance(exc, AssertionError):
        return mentions_warning_table and "unhandled sql" in message
    if not isinstance(exc, SQLAlchemyError):
        return False

    sqlstate = _sqlstate_from_exception(exc)
    if sqlstate == "42P01" and mentions_warning_table:
        return True
    return mentions_warning_table and (
        "does not exist" in message
        or "no such table" in message
        or "undefined table" in message
    )


async def _ensure_warning_tables(db: AsyncSession) -> None:
    try:
        await db.execute(text("SELECT 1 FROM warning_issues LIMIT 1"), {})
    except (AssertionError, SQLAlchemyError) as exc:  # pragma: no cover - DB/fake dependent
        if _is_missing_warning_table_error(exc):
            raise DurableWarningStoreUnavailable(str(exc)) from exc
        raise


async def _find_issue_by_fingerprint(
    db: AsyncSession,
    fingerprint: str,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT *
            FROM warning_issues
            WHERE fingerprint = :fingerprint
            """
        ),
        {"fingerprint": fingerprint},
    )
    return dict(result.mappings().one_or_none() or {})


async def _create_issue(
    db: AsyncSession,
    *,
    row: dict[str, Any],
    upload_log: Mapping[str, Any],
    fingerprint: str,
) -> dict[str, Any]:
    issue_id = str(uuid4())
    uploaded_at = upload_log.get("uploaded_at") or _now()
    params = {
        "id": issue_id,
        "fingerprint": fingerprint,
        "warning_type": row["warning_type"],
        "severity": row["severity"],
        "status": "unresolved",
        "first_seen_upload_log_id": str(upload_log["id"]),
        "last_seen_upload_log_id": str(upload_log["id"]),
        "first_seen_at": uploaded_at,
        "last_seen_at": uploaded_at,
        "reporting_period_id": row.get("reporting_period_id"),
        "programme_code": row.get("programme_code"),
        "resident_id": row.get("resident_id"),
        "mcr": row.get("mcr"),
        "month_label": row.get("month_label"),
        "resolution_note": None,
        "resolution_source_type": None,
        "resolution_source_id": None,
        "resolved_by": None,
        "resolved_at": None,
    }
    result = await db.execute(
        text(
            """
            INSERT INTO warning_issues (
                id,
                fingerprint,
                warning_type,
                severity,
                status,
                first_seen_upload_log_id,
                last_seen_upload_log_id,
                first_seen_at,
                last_seen_at,
                reporting_period_id,
                programme_code,
                resident_id,
                mcr,
                month_label,
                resolution_note,
                resolution_source_type,
                resolution_source_id,
                resolved_by,
                resolved_at
            )
            VALUES (
                :id,
                :fingerprint,
                :warning_type,
                :severity,
                :status,
                :first_seen_upload_log_id,
                :last_seen_upload_log_id,
                :first_seen_at,
                :last_seen_at,
                :reporting_period_id,
                :programme_code,
                :resident_id,
                :mcr,
                :month_label,
                :resolution_note,
                :resolution_source_type,
                :resolution_source_id,
                :resolved_by,
                :resolved_at
            )
            RETURNING *
            """
        ),
        params,
    )
    return dict(result.mappings().one())


async def _update_issue_seen(
    db: AsyncSession,
    *,
    issue: dict[str, Any],
    upload_log: Mapping[str, Any],
) -> dict[str, Any]:
    next_status = "reappeared" if issue.get("status") in REAPPEARABLE_STATUSES else issue["status"]
    result = await db.execute(
        text(
            """
            UPDATE warning_issues
            SET
                status = :status,
                last_seen_upload_log_id = :last_seen_upload_log_id,
                last_seen_at = :last_seen_at,
                updated_at = now()
            WHERE id = :issue_id
            RETURNING *
            """
        ),
        {
            "issue_id": str(issue["id"]),
            "status": next_status,
            "last_seen_upload_log_id": str(upload_log["id"]),
            "last_seen_at": upload_log.get("uploaded_at") or _now(),
        },
    )
    return dict(result.mappings().one())


async def _create_occurrence(
    db: AsyncSession,
    *,
    issue_id: str,
    row: dict[str, Any],
    upload_log: Mapping[str, Any],
    fingerprint: str,
    source_payload: Any,
) -> bool:
    result = await db.execute(
        text(
            """
            INSERT INTO upload_warnings (
                id,
                issue_id,
                upload_log_id,
                warning_type,
                severity,
                reporting_period_id,
                programme_code,
                resident_id,
                mcr,
                resident_name,
                month_label,
                sheet_name,
                row_number,
                cell_ref,
                source_table,
                source_record_id,
                source_payload,
                message,
                suggested_action,
                fingerprint
            )
            VALUES (
                :id,
                :issue_id,
                :upload_log_id,
                :warning_type,
                :severity,
                :reporting_period_id,
                :programme_code,
                :resident_id,
                :mcr,
                :resident_name,
                :month_label,
                :sheet_name,
                :row_number,
                :cell_ref,
                :source_table,
                :source_record_id,
                CAST(:source_payload AS JSONB),
                :message,
                :suggested_action,
                :fingerprint
            )
            ON CONFLICT (upload_log_id, fingerprint) DO NOTHING
            RETURNING *
            """
        ),
        {
            "id": str(uuid4()),
            "issue_id": issue_id,
            "upload_log_id": str(upload_log["id"]),
            "warning_type": row["warning_type"],
            "severity": row["severity"],
            "reporting_period_id": row.get("reporting_period_id"),
            "programme_code": row.get("programme_code"),
            "resident_id": row.get("resident_id"),
            "mcr": row.get("mcr"),
            "resident_name": row.get("resident_name"),
            "month_label": row.get("month_label"),
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "cell_ref": row.get("cell_ref"),
            "source_table": row.get("source_table"),
            "source_record_id": row.get("source_record_id"),
            "source_payload": json.dumps(source_payload or {}, default=str),
            "message": row["message"],
            "suggested_action": _suggested_action(_dict_to_warning_row(row, source_payload)),
            "fingerprint": fingerprint,
        },
    )
    return bool(result.mappings().all())


def _dict_to_warning_row(row: dict[str, Any], source_payload: Any) -> UploadWarningRow:
    return UploadWarningRow(
        warning_id=str(row.get("warning_id") or ""),
        upload_log_id=str(row.get("upload_log_id") or ""),
        dedupe_key=str(row.get("dedupe_key") or ""),
        upload_type=str(row.get("upload_type") or ""),
        uploaded_at=row.get("uploaded_at") or _now(),
        uploaded_by=row.get("uploaded_by"),
        reporting_period_id=row.get("reporting_period_id"),
        programme_code=row.get("programme_code"),
        warning_type=row.get("warning_type") or "warning",
        severity=row.get("severity") or "warning",
        message=row.get("message") or "",
        resident_name=row.get("resident_name"),
        mcr=row.get("mcr"),
        month_label=row.get("month_label"),
        sheet_name=row.get("sheet_name"),
        row_number=row.get("row_number"),
        cell_ref=row.get("cell_ref"),
        posting_codes=row.get("posting_codes"),
        session_type=row.get("session_type"),
        count=row.get("count"),
        source_label=row.get("source_label"),
        raw_payload=source_payload,
    )


async def derive_upload_warnings_from_summary(
    session: AsyncSession,
    upload_log: Mapping[str, Any],
    summary: Mapping[str, Any] | str | None,
    actor_id: UUID | str | None = None,
) -> DerivationResult:
    await _ensure_warning_tables(session)
    summary_payload: Any = summary
    if isinstance(summary_payload, str):
        summary_payload = json.loads(summary_payload)
    if not isinstance(summary_payload, dict):
        return DerivationResult(upload_log_id=str(upload_log.get("id")) if upload_log.get("id") else None)

    normalized_upload_log = dict(upload_log)
    normalized_upload_log["summary"] = summary_payload
    normalized_upload_log.setdefault("uploaded_at", _now())
    result = DerivationResult(upload_log_id=str(normalized_upload_log.get("id")))
    for warning_row in normalise_warning_rows_from_upload_log(normalized_upload_log):
        row = _row_payload(warning_row)
        source_payload = warning_row.raw_payload if isinstance(warning_row.raw_payload, dict) else {"value": warning_row.raw_payload}
        fingerprint = row["fingerprint"]
        issue = await _find_issue_by_fingerprint(session, fingerprint)
        if issue:
            previous_status = issue.get("status")
            issue = await _update_issue_seen(session, issue=issue, upload_log=normalized_upload_log)
            if previous_status in REAPPEARABLE_STATUSES:
                result.issues_reappeared += 1
            else:
                result.issues_updated += 1
        else:
            issue = await _create_issue(
                session,
                row=row,
                upload_log=normalized_upload_log,
                fingerprint=fingerprint,
            )
            result.issues_created += 1

        created = await _create_occurrence(
            session,
            issue_id=str(issue["id"]),
            row=row,
            upload_log=normalized_upload_log,
            fingerprint=fingerprint,
            source_payload=source_payload,
        )
        if created:
            result.occurrences_created += 1
        else:
            result.occurrences_skipped += 1

    await session.commit()
    cache_invalidation.invalidate_after_warning_derivation(
        upload_log_id=normalized_upload_log.get("id"),
        reporting_period_id=normalized_upload_log.get("reporting_period_id"),
        programme_code=normalized_upload_log.get("programme_code"),
    )
    return result


async def derive_upload_warnings_from_upload_log(
    session: AsyncSession,
    upload_log_id: UUID | str,
    actor_id: UUID | str | None = None,
) -> DerivationResult:
    await _ensure_warning_tables(session)
    result = await session.execute(
        text(
            """
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
            WHERE ul.id = :upload_log_id
            """
        ),
        {"upload_log_id": str(upload_log_id)},
    )
    upload_log = dict(result.mappings().one())
    return await derive_upload_warnings_from_summary(
        session,
        upload_log,
        upload_log.get("summary"),
        actor_id=actor_id,
    )


def _latest_trace(occurrence: dict[str, Any] | None) -> dict[str, Any] | None:
    if not occurrence:
        return None
    return {
        "sheet_name": occurrence.get("sheet_name"),
        "row_number": occurrence.get("row_number"),
        "cell_ref": occurrence.get("cell_ref"),
    }


def _json_payload_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"value": value}
    return value


def _detail_occurrence_payload(occurrence: dict[str, Any]) -> dict[str, Any]:
    source_payload = _json_payload_value(occurrence.get("source_payload"))
    return {
        "id": str(occurrence["id"]),
        "issue_id": str(occurrence["issue_id"]),
        "source_trace": _latest_trace(occurrence),
        "upload_log_id": str(occurrence["upload_log_id"]),
        "upload_type": occurrence.get("upload_type"),
        "uploaded_at": occurrence.get("uploaded_at"),
        "warning_type": occurrence["warning_type"],
        "severity": occurrence["severity"],
        "reporting_period_id": str(occurrence["reporting_period_id"]) if occurrence.get("reporting_period_id") else None,
        "programme_code": occurrence.get("programme_code"),
        "resident_id": str(occurrence["resident_id"]) if occurrence.get("resident_id") else None,
        "mcr": occurrence.get("mcr"),
        "resident_name": occurrence.get("resident_name"),
        "month_label": occurrence.get("month_label"),
        "sheet_name": occurrence.get("sheet_name"),
        "row_number": occurrence.get("row_number"),
        "cell_ref": occurrence.get("cell_ref"),
        "source_table": occurrence.get("source_table"),
        "source_record_id": str(occurrence["source_record_id"]) if occurrence.get("source_record_id") else None,
        "source_payload": source_payload,
        "message": occurrence["message"],
        "suggested_action": occurrence.get("suggested_action"),
        "fingerprint": occurrence["fingerprint"],
        "created_at": occurrence["created_at"],
    }


async def _occurrences_for_issue(db: AsyncSession, issue_id: str) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT
                uw.*,
                ul.upload_type,
                ul.uploaded_at,
                ul.uploaded_by
            FROM upload_warnings uw
            LEFT JOIN upload_logs ul ON ul.id = uw.upload_log_id
            WHERE uw.issue_id = :issue_id
            ORDER BY COALESCE(ul.uploaded_at, uw.created_at) DESC, uw.id DESC
            """
        ),
        {"issue_id": issue_id},
    )
    return [dict(row) for row in result.mappings().all()]


def _issue_visible(
    issue: Mapping[str, Any],
    *,
    programme_scope: set[str],
    master_admin: bool,
) -> bool:
    if master_admin:
        return True
    programme_code = issue.get("programme_code")
    return bool(programme_code and programme_code in programme_scope)


def _list_item(
    issue: dict[str, Any],
    occurrence: dict[str, Any] | None,
    occurrences: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_warning_id = str(occurrence["id"]) if occurrence else None
    source_payload = occurrence.get("source_payload") if occurrence else None
    source_payload = _json_payload_value(source_payload)
    posting_codes = []
    if isinstance(source_payload, dict):
        payload_posting_codes = source_payload.get("posting_codes") or source_payload.get("postingCodes")
        if isinstance(payload_posting_codes, list):
            posting_codes = [str(item) for item in payload_posting_codes]
    return {
        "issue_id": str(issue["id"]),
        "warning_issue_id": str(issue["id"]),
        "status": issue["status"],
        "warning_id": latest_warning_id or str(issue["id"]),
        "upload_warning_id": latest_warning_id,
        "dedupe_key": issue["fingerprint"],
        "upload_log_id": str(issue.get("last_seen_upload_log_id") or ""),
        "upload_type": occurrence.get("upload_type", "") if occurrence else "",
        "uploaded_at": occurrence.get("created_at") or issue["last_seen_at"],
        "uploaded_by": None,
        "reporting_period_id": str(issue["reporting_period_id"]) if issue.get("reporting_period_id") else None,
        "programme_code": issue.get("programme_code"),
        "warning_type": issue["warning_type"],
        "severity": issue["severity"],
        "message": occurrence.get("message") if occurrence else "",
        "suggested_action": occurrence.get("suggested_action") if occurrence else None,
        "resident_name": occurrence.get("resident_name") if occurrence else None,
        "mcr": issue.get("mcr"),
        "month_label": issue.get("month_label"),
        "sheet_name": occurrence.get("sheet_name") if occurrence else None,
        "row_number": occurrence.get("row_number") if occurrence else None,
        "cell_ref": occurrence.get("cell_ref") if occurrence else None,
        "posting_codes": posting_codes,
        "session_type": source_payload.get("session_type") if isinstance(source_payload, dict) else None,
        "count": source_payload.get("count") if isinstance(source_payload, dict) else None,
        "source_label": None,
        "raw_payload": source_payload,
        "seen_count": len(occurrences) or 1,
        "first_seen_at": issue["first_seen_at"],
        "last_seen_at": issue["last_seen_at"],
        "upload_log_ids": [
            str(item["upload_log_id"])
            for item in occurrences
            if item.get("upload_log_id") is not None
        ],
        "first_seen_upload_log_id": str(issue["first_seen_upload_log_id"]) if issue.get("first_seen_upload_log_id") else None,
        "last_seen_upload_log_id": str(issue["last_seen_upload_log_id"]) if issue.get("last_seen_upload_log_id") else None,
        "latest_upload_warning_id": latest_warning_id,
        "latest_source_trace": _latest_trace(occurrence),
        "reappeared": issue["status"] == "reappeared",
    }


async def list_warning_issues(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    upload_log_id: UUID | None = None,
    upload_type: str | None = None,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
    warning_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    mcr: str | None = None,
    month_label: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if not master_admin and not programme_scope:
        return []
    await _ensure_warning_tables(db)
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    use_scope_bindparam = False
    if not master_admin:
        clauses.append("wi.programme_code IN :programme_scope")
        params["programme_scope"] = tuple(sorted(programme_scope))
        use_scope_bindparam = True
    if upload_log_id is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM upload_warnings uw WHERE uw.issue_id = wi.id AND uw.upload_log_id = :upload_log_id)"
        )
        params["upload_log_id"] = str(upload_log_id)
    if upload_type is not None:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM upload_warnings uw
                JOIN upload_logs ul ON ul.id = uw.upload_log_id
                WHERE uw.issue_id = wi.id
                AND ul.upload_type = :upload_type
            )
            """
        )
        params["upload_type"] = upload_type
    if reporting_period_id is not None:
        clauses.append("wi.reporting_period_id = :reporting_period_id")
        params["reporting_period_id"] = str(reporting_period_id)
    if programme_code is not None:
        clauses.append("wi.programme_code = :programme_code")
        params["programme_code"] = programme_code
    if warning_type is not None:
        clauses.append("wi.warning_type = :warning_type")
        params["warning_type"] = warning_type
    if severity is not None:
        clauses.append("wi.severity = :severity")
        params["severity"] = severity
    if status is not None:
        clauses.append("wi.status = :status")
        params["status"] = status
    if mcr is not None:
        clauses.append("wi.mcr = :mcr")
        params["mcr"] = mcr.upper()
    if month_label is not None:
        clauses.append("wi.month_label = :month_label")
        params["month_label"] = month_label
    if search is not None and search.strip():
        clauses.append(
            """
            (
                wi.fingerprint ILIKE :search
                OR wi.warning_type ILIKE :search
                OR wi.programme_code ILIKE :search
                OR wi.mcr ILIKE :search
                OR wi.month_label ILIKE :search
                OR EXISTS (
                    SELECT 1
                    FROM upload_warnings uw
                    WHERE uw.issue_id = wi.id
                    AND (
                        uw.message ILIKE :search
                        OR uw.resident_name ILIKE :search
                        OR uw.sheet_name ILIKE :search
                    )
                )
            )
            """
        )
        params["search"] = f"%{search.strip()}%"

    sql = "SELECT * FROM warning_issues wi"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY wi.last_seen_at DESC, wi.id DESC LIMIT :limit OFFSET :offset"
    statement = text(sql)
    if use_scope_bindparam:
        statement = statement.bindparams(bindparam("programme_scope", expanding=True))
    result = await db.execute(statement, params)
    issues = [dict(row) for row in result.mappings().all()]
    visible = [
        issue for issue in issues if _issue_visible(issue, programme_scope=programme_scope, master_admin=master_admin)
    ]
    rows: list[dict[str, Any]] = []
    for issue in visible:
        occurrences = await _occurrences_for_issue(db, str(issue["id"]))
        rows.append(_list_item(issue, occurrences[0] if occurrences else None, occurrences))
    return rows


async def get_warning_issue_detail(
    db: AsyncSession,
    *,
    issue_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any] | None:
    await _ensure_warning_tables(db)
    result = await db.execute(
        text("SELECT * FROM warning_issues wi WHERE wi.id = :issue_id"),
        {"issue_id": str(issue_id)},
    )
    issue = dict(result.mappings().one_or_none() or {})
    if not issue or not _issue_visible(issue, programme_scope=programme_scope, master_admin=master_admin):
        return None
    occurrences = await _occurrences_for_issue(db, str(issue["id"]))
    normalized_occurrences: list[dict[str, Any]] = []
    for occurrence in occurrences:
        normalized_occurrences.append(_detail_occurrence_payload(occurrence))
    latest_occurrence = normalized_occurrences[0] if normalized_occurrences else None
    latest_source_payload = (
        latest_occurrence.get("source_payload")
        if isinstance(latest_occurrence, dict)
        else {}
    )
    return {
        "issue_id": str(issue["id"]),
        "warning_issue_id": str(issue["id"]),
        "fingerprint": issue["fingerprint"],
        "warning_type": issue["warning_type"],
        "severity": issue["severity"],
        "status": issue["status"],
        "reappeared": issue["status"] == "reappeared",
        "first_seen_upload_log_id": str(issue["first_seen_upload_log_id"]) if issue.get("first_seen_upload_log_id") else None,
        "last_seen_upload_log_id": str(issue["last_seen_upload_log_id"]) if issue.get("last_seen_upload_log_id") else None,
        "first_seen_at": issue["first_seen_at"],
        "last_seen_at": issue["last_seen_at"],
        "latest_upload_warning_id": str(latest_occurrence["id"]) if latest_occurrence else None,
        "latest_source_trace": _latest_trace(latest_occurrence),
        "latest_source_payload": latest_source_payload if isinstance(latest_source_payload, dict) else {},
        "message": latest_occurrence.get("message") if latest_occurrence else None,
        "suggested_action": latest_occurrence.get("suggested_action") if latest_occurrence else None,
        "resident_name": latest_occurrence.get("resident_name") if latest_occurrence else None,
        "reporting_period_id": str(issue["reporting_period_id"]) if issue.get("reporting_period_id") else None,
        "programme_code": issue.get("programme_code"),
        "resident_id": str(issue["resident_id"]) if issue.get("resident_id") else None,
        "mcr": issue.get("mcr"),
        "month_label": issue.get("month_label"),
        "resolution_note": issue.get("resolution_note"),
        "resolution_source_type": issue.get("resolution_source_type"),
        "resolution_source_id": str(issue["resolution_source_id"]) if issue.get("resolution_source_id") else None,
        "resolved_by": str(issue["resolved_by"]) if issue.get("resolved_by") else None,
        "resolved_at": issue.get("resolved_at"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "occurrences": normalized_occurrences,
    }


async def update_warning_issue_status(
    db: AsyncSession,
    *,
    issue_id: UUID,
    action: str,
    note: str | None,
    actor: StaffActorContext,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any] | None:
    status = ACTION_TO_STATUS[action]
    detail = await get_warning_issue_detail(
        db,
        issue_id=issue_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    if detail is None:
        return None
    before = {
        "id": detail["issue_id"],
        "status": detail["status"],
        "resolution_note": detail.get("resolution_note"),
    }
    result = await db.execute(
        text(
            """
            UPDATE warning_issues
            SET
                status = :status,
                resolution_note = :resolution_note,
                resolution_source_type = :resolution_source_type,
                resolution_source_id = :resolution_source_id,
                resolved_by = :resolved_by,
                resolved_at = :resolved_at,
                updated_at = now()
            WHERE id = :issue_id
            RETURNING *
            """
        ),
        {
            "issue_id": str(issue_id),
            "status": status,
            "resolution_note": note,
            "resolution_source_type": "admin_warning_action",
            "resolution_source_id": str(issue_id),
            "resolved_by": str(actor.actor_user_id) if actor.actor_user_id else None,
            "resolved_at": _now(),
        },
    )
    issue = dict(result.mappings().one())
    await write_audit_log(
        db,
        actor=actor,
        action=f"admin.upload_warning.{action}",
        entity_type="warning_issue",
        entity_id=str(issue_id),
        before=before,
        after={
            "id": str(issue["id"]),
            "status": issue["status"],
            "resolution_note": issue.get("resolution_note"),
        },
        metadata={
            "warning_type": issue["warning_type"],
            "programme_code": issue.get("programme_code"),
            "reporting_period_id": str(issue["reporting_period_id"]) if issue.get("reporting_period_id") else None,
        },
    )
    await db.commit()
    cache_invalidation.invalidate_after_warning_action(
        warning_issue_id=issue_id,
        reporting_period_id=issue.get("reporting_period_id"),
        programme_code=issue.get("programme_code"),
        mcr=issue.get("mcr"),
    )
    return {
        "issue_id": str(issue["id"]),
        "status": issue["status"],
        "previous_status": before["status"],
        "new_status": issue["status"],
        "resolution_note": issue.get("resolution_note"),
        "note": issue.get("resolution_note"),
        "resolved_by": str(issue["resolved_by"]) if issue.get("resolved_by") else None,
        "actor_user_id": str(issue["resolved_by"]) if issue.get("resolved_by") else None,
        "resolved_at": issue.get("resolved_at"),
        "updated_at": issue.get("updated_at"),
    }
