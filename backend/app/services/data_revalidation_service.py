from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy import bindparam, text

from app.schemas.data_revalidation import (
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationImpactSummary,
    DataRevalidationOutcome,
    DataRevalidationWarningImpact,
)


_ACTIONABLE_WARNING_STATUSES = ("unresolved", "reappeared")
_WARNING_QUERY_LIMIT = 200
_WARNING_ID_RESPONSE_LIMIT = 20
_WARNING_SUMMARY_RESPONSE_LIMIT = 10
_PARSER_CONFIG_WARNING_TYPES = (
    "unmatched_multi_posting",
    "empty_posting_cell",
    "unknown_loa_type",
    "tag_order_warning",
)

@dataclass(frozen=True)
class _WarningCandidatePage:
    rows: list[dict[str, Any]]
    limit_reached: bool


@dataclass(frozen=True)
class _AffectedWarningRows:
    rows: list[dict[str, Any]]
    candidates_examined: int
    candidate_limit_reached: bool


_AFFECTED_MODEL_BY_ENTITY = {
    DataRevalidationChangedEntity.RESIDENT: "residents",
    DataRevalidationChangedEntity.RESIDENT_POSTING: "resident_postings",
    DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT: "resident_postings",
    DataRevalidationChangedEntity.TEACHING_TARGET: "teaching_targets",
    DataRevalidationChangedEntity.FORM_F1_RECORD: "form_f1_records",
    DataRevalidationChangedEntity.ACADEMIC_MONTH_BOUNDARY: "academic_month_boundaries",
    DataRevalidationChangedEntity.REPORTING_PERIOD: "reporting_periods",
    DataRevalidationChangedEntity.PUBLIC_HOLIDAY: "public_holidays",
    DataRevalidationChangedEntity.PROGRAMME: "programmes",
    DataRevalidationChangedEntity.LOA_TYPE: "loa_types",
    DataRevalidationChangedEntity.MULTI_POSTING_RULE: "multi_posting_rules",
    DataRevalidationChangedEntity.POSTING_GROUP: "posting_groups",
    DataRevalidationChangedEntity.WEEKEND_EXCEPTION: "weekend_exceptions",
    DataRevalidationChangedEntity.GLOBAL_SESSION_TYPE: "global_session_types",
}


def _affected_models_for(context: DataRevalidationContext) -> list[str]:
    model_name = _AFFECTED_MODEL_BY_ENTITY.get(context.changed_entity)
    return [model_name] if model_name else []


def _warning_delta(summary: DataRevalidationImpactSummary) -> dict[str, int]:
    return {
        "created": summary.warnings_created,
        "updated": summary.warnings_updated,
        "resolved": summary.warnings_resolved,
        "remaining": summary.warnings_remaining,
    }


def _audit_metadata(
    context: DataRevalidationContext,
    summary: DataRevalidationImpactSummary,
) -> dict[str, Any]:
    return {
        "triggered_by": context.trigger_source.value,
        "trigger_entity": context.changed_entity.value,
        "trigger_entity_id": context.entity_id,
        "impact_summary": {
            "outcome": summary.outcome.value,
            "scope": summary.scope.value,
            "rows_examined": summary.rows_examined,
            "rows_updated": summary.rows_updated,
            "affected_models": list(summary.affected_models),
        },
        "warnings_delta": _warning_delta(summary),
    }


def _summary(
    *,
    context: DataRevalidationContext,
    outcome: DataRevalidationOutcome,
    message: str,
    affected_models: list[str] | None = None,
    details: dict[str, Any] | None = None,
    rows_examined: int = 0,
    rows_updated: int = 0,
    warnings_remaining: int = 0,
    affected_warning_ids: list[str] | None = None,
    warning_impacts: list[DataRevalidationWarningImpact] | None = None,
) -> DataRevalidationImpactSummary:
    base_details: dict[str, Any] = {
        "handler_version": "3H-B",
        "business_tables_mutated": False,
        "warnings_mutated": False,
        "changed_fields": list(context.changed_fields),
    }
    if context.source_metadata:
        base_details["source_metadata"] = dict(context.source_metadata)
    base_details.update(details or {})
    payload = DataRevalidationImpactSummary(
        outcome=outcome,
        trigger_source=context.trigger_source,
        changed_entity=context.changed_entity,
        action=context.action,
        scope=context.scope,
        summary=message,
        reason=context.reason or message,
        rows_examined=rows_examined,
        rows_updated=rows_updated,
        warnings_remaining=warnings_remaining,
        affected_models=affected_models if affected_models is not None else _affected_models_for(context),
        affected_warning_ids=affected_warning_ids or [],
        affected_scope=base_details.get("affected_scope"),
        affected_warning_count=base_details.get("affected_warning_count"),
        affected_warning_issue_ids=list(
            base_details.get("affected_warning_issue_ids")
            or affected_warning_ids
            or []
        ),
        affected_warning_summaries=list(base_details.get("affected_warning_summaries") or []),
        affected_warning_count_is_partial=base_details.get("affected_warning_count_is_partial"),
        affected_warning_details_are_partial=base_details.get("affected_warning_details_are_partial"),
        warning_candidate_limit=base_details.get("warning_candidate_limit"),
        warning_candidate_limit_reached=base_details.get("warning_candidate_limit_reached"),
        affected_entity_counts=dict(base_details.get("affected_entity_counts") or {}),
        next_actions=list(base_details.get("next_actions") or []),
        enrichment_version=base_details.get("enrichment_version"),
        warning_impacts=warning_impacts or [],
        details=base_details,
    )
    payload.audit_metadata = _audit_metadata(context, payload)
    return payload


def _manual_required_summary(
    *,
    context: DataRevalidationContext,
    message: str,
    details: dict[str, Any] | None = None,
) -> DataRevalidationImpactSummary:
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.MANUAL_REVALIDATION_REQUIRED,
        message=message,
        details={"backend_handler_available": False, **(details or {})},
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value


def _parse_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalise_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().casefold()


def _non_blank(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _source_metadata_snapshots(context: DataRevalidationContext) -> list[dict[str, Any]]:
    current = dict(context.source_metadata or {})
    snapshots = [current]
    previous = current.get("previous_source_metadata")
    if isinstance(previous, dict):
        snapshots.append(previous)
    return snapshots


def _metadata_values(context: DataRevalidationContext, fields: Iterable[str]) -> set[str]:
    values: set[str] = set()
    for snapshot in _source_metadata_snapshots(context):
        for field in fields:
            value = _non_blank(snapshot.get(field))
            if value is not None:
                values.add(value)
    return values


def _affected_scope(context: DataRevalidationContext) -> dict[str, Any]:
    metadata = dict(context.source_metadata or {})
    scope: dict[str, Any] = {
        "scope": context.scope.value,
        "entity_id": context.entity_id,
    }
    if context.programme_code is not None:
        scope["programme_code"] = context.programme_code
    if context.reporting_period_id is not None:
        scope["reporting_period_id"] = context.reporting_period_id
    for key in (
        "label",
        "start_date",
        "end_date",
        "status",
        "holiday_date",
        "name",
        "year",
        "code",
        "r_year_required",
        "is_subspecialty",
        "rdb_alias",
        "rule_type",
        "posting_code_1",
        "posting_code_2",
        "combined_label",
        "main_posting_code",
        "exclusion_code",
        "group_code",
        "posting_code",
        "day_type",
        "start_time_min",
        "end_time_max",
        "session_type_id",
        "session_name_pattern",
        "mutates_to_session_type_id",
        "adjusted_duration_hours",
        "duration_hours",
        "is_active",
    ):
        if key in metadata:
            scope[key] = metadata[key]
    return _json_ready({key: value for key, value in scope.items() if value is not None})


def _warning_payload(row: dict[str, Any]) -> dict[str, Any]:
    return _parse_payload(row.get("source_payload"))


def _payload_posting_codes(row: dict[str, Any]) -> list[str]:
    payload = _warning_payload(row)
    values = payload.get("posting_codes") or payload.get("postingCodes") or []
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _payload_loa_type(row: dict[str, Any]) -> str | None:
    payload = _warning_payload(row)
    for key in ("loa_type", "loaType", "raw_loa_type", "rawLoaType", "value", "raw_value", "rawValue"):
        value = _non_blank(payload.get(key))
        if value is not None:
            return value
    return None


def _warning_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "warning_issue_id": str(row.get("issue_id")),
        "latest_upload_warning_id": (
            str(row["latest_upload_warning_id"])
            if row.get("latest_upload_warning_id") is not None
            else None
        ),
        "warning_type": row.get("warning_type"),
        "status": row.get("status"),
        "programme_code": row.get("programme_code"),
        "reporting_period_id": (
            str(row["reporting_period_id"])
            if row.get("reporting_period_id") is not None
            else None
        ),
        "mcr": row.get("mcr"),
        "month_label": row.get("month_label"),
        "message": row.get("message"),
    }
    posting_codes = _payload_posting_codes(row)
    if posting_codes:
        summary["posting_codes"] = posting_codes
    loa_type = _payload_loa_type(row)
    if loa_type is not None:
        summary["loa_type"] = loa_type
    return _json_ready({key: value for key, value in summary.items() if value is not None})


def _warning_impacts(rows: Sequence[dict[str, Any]]) -> list[DataRevalidationWarningImpact]:
    impacts: list[DataRevalidationWarningImpact] = []
    for row in rows[:_WARNING_SUMMARY_RESPONSE_LIMIT]:
        impacts.append(
            DataRevalidationWarningImpact(
                warning_id=str(row.get("issue_id")) if row.get("issue_id") is not None else None,
                warning_type=str(row.get("warning_type") or "unknown"),
                status=str(row.get("status") or "unknown"),
                action="review_required",
                message=str(row.get("message") or "Review affected durable upload warning issue."),
                entity_ref={
                    "programme_code": row.get("programme_code"),
                    "reporting_period_id": (
                        str(row["reporting_period_id"])
                        if row.get("reporting_period_id") is not None
                        else None
                    ),
                    "latest_upload_warning_id": (
                        str(row["latest_upload_warning_id"])
                        if row.get("latest_upload_warning_id") is not None
                        else None
                    ),
                },
            )
        )
    return impacts


async def _fetch_actionable_warning_candidates(
    db_session: Any | None,
    *,
    programme_code: str | None = None,
    reporting_period_id: str | None = None,
    warning_types: Sequence[str] | None = None,
) -> _WarningCandidatePage:
    if db_session is None:
        return _WarningCandidatePage(rows=[], limit_reached=False)
    selected_warning_types = tuple(warning_types or _PARSER_CONFIG_WARNING_TYPES)
    if not selected_warning_types:
        return _WarningCandidatePage(rows=[], limit_reached=False)
    where_clauses = [
        "wi.status IN :statuses",
        "wi.warning_type IN :warning_types",
    ]
    params: dict[str, Any] = {
        "statuses": _ACTIONABLE_WARNING_STATUSES,
        "warning_types": selected_warning_types,
        "limit": _WARNING_QUERY_LIMIT + 1,
    }
    if programme_code is not None:
        where_clauses.append("wi.programme_code = :programme_code")
        params["programme_code"] = programme_code
    if reporting_period_id is not None:
        where_clauses.append("CAST(wi.reporting_period_id AS TEXT) = :reporting_period_id")
        params["reporting_period_id"] = reporting_period_id
    where_sql = "\n          AND ".join(where_clauses)
    statement = text(
        f"""
        /* data_revalidation:warning_candidates */
        SELECT
            wi.id AS issue_id,
            wi.fingerprint,
            wi.warning_type,
            wi.status,
            wi.severity,
            wi.reporting_period_id,
            wi.programme_code,
            wi.mcr,
            wi.month_label,
            wi.last_seen_at,
            latest_uw.id AS latest_upload_warning_id,
            latest_uw.source_payload,
            latest_uw.message,
            latest_uw.suggested_action
        FROM warning_issues wi
        LEFT JOIN LATERAL (
            SELECT *
            FROM upload_warnings uw
            WHERE uw.issue_id = wi.id
            ORDER BY uw.created_at DESC, uw.id DESC
            LIMIT 1
        ) latest_uw ON TRUE
        WHERE {where_sql}
        ORDER BY wi.last_seen_at DESC NULLS LAST, wi.id DESC
        LIMIT :limit
        """
    ).bindparams(
        bindparam("statuses", expanding=True),
        bindparam("warning_types", expanding=True),
    )
    result = await db_session.execute(statement, params)
    rows = [dict(row) for row in result.mappings().all()]
    return _WarningCandidatePage(
        rows=rows[:_WARNING_QUERY_LIMIT],
        limit_reached=len(rows) > _WARNING_QUERY_LIMIT,
    )


async def _count_query(
    db_session: Any | None,
    sql: str,
    params: dict[str, Any],
) -> int:
    if db_session is None:
        return 0
    result = await db_session.execute(text(sql), params)
    row = result.mappings().one_or_none()
    if row is None:
        return 0
    value = row.get("count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _rule_posting_matchers(context: DataRevalidationContext) -> list[tuple[set[str], bool]]:
    matchers: list[tuple[set[str], bool]] = []
    for snapshot in _source_metadata_snapshots(context):
        posting_code_1 = _non_blank(snapshot.get("posting_code_1"))
        posting_code_2 = _non_blank(snapshot.get("posting_code_2"))
        rule_type = _normalise_token(snapshot.get("rule_type"))
        if posting_code_1 is None:
            continue
        if rule_type == "main_posting" and posting_code_2 is None:
            matchers.append(({_normalise_token(posting_code_1)}, True))
            continue
        if posting_code_2 is not None:
            matchers.append(
                (
                    {
                        _normalise_token(posting_code_1),
                        _normalise_token(posting_code_2),
                    },
                    False,
                )
            )
    return matchers


def _matches_multi_posting_rule(row: dict[str, Any], context: DataRevalidationContext) -> bool:
    warning_codes = {_normalise_token(code) for code in _payload_posting_codes(row)}
    if not warning_codes:
        return False
    for rule_codes, trigger_list in _rule_posting_matchers(context):
        if trigger_list and rule_codes.intersection(warning_codes):
            return True
        if not trigger_list and warning_codes == rule_codes:
            return True
    return False


def _matches_loa_type(row: dict[str, Any], context: DataRevalidationContext) -> bool:
    loa_values = {_normalise_token(value) for value in _metadata_values(context, ("code", "description"))}
    if not loa_values:
        return False
    candidate_values = {_normalise_token(_payload_loa_type(row))}
    message = _normalise_token(row.get("message"))
    return bool(loa_values.intersection(candidate_values)) or any(
        value and value in message for value in loa_values
    )


def _matches_public_holiday(row: dict[str, Any], context: DataRevalidationContext) -> bool:
    payload = _warning_payload(row)
    holiday_values = {_normalise_token(value) for value in _metadata_values(context, ("holiday_date", "name", "year"))}
    if not holiday_values:
        return False
    candidate_values = {
        _normalise_token(payload.get("holiday_date") or payload.get("holidayDate")),
        _normalise_token(payload.get("holiday_name") or payload.get("name")),
        _normalise_token(payload.get("year")),
    }
    return bool(holiday_values.intersection(candidate_values))


async def _affected_warning_rows(
    context: DataRevalidationContext,
    db_session: Any | None,
) -> _AffectedWarningRows:
    entity = context.changed_entity
    if entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE:
        candidate_page = await _fetch_actionable_warning_candidates(
            db_session,
            programme_code=context.programme_code,
            warning_types=("unmatched_multi_posting",),
        )
        return _AffectedWarningRows(
            rows=[row for row in candidate_page.rows if _matches_multi_posting_rule(row, context)],
            candidates_examined=len(candidate_page.rows),
            candidate_limit_reached=candidate_page.limit_reached,
        )

    if entity == DataRevalidationChangedEntity.LOA_TYPE:
        candidate_page = await _fetch_actionable_warning_candidates(
            db_session,
            warning_types=("unknown_loa_type",),
        )
        return _AffectedWarningRows(
            rows=[row for row in candidate_page.rows if _matches_loa_type(row, context)],
            candidates_examined=len(candidate_page.rows),
            candidate_limit_reached=candidate_page.limit_reached,
        )

    if entity == DataRevalidationChangedEntity.PROGRAMME:
        candidate_page = await _fetch_actionable_warning_candidates(
            db_session,
            programme_code=context.programme_code,
            warning_types=_PARSER_CONFIG_WARNING_TYPES,
        )
        return _AffectedWarningRows(
            rows=candidate_page.rows,
            candidates_examined=len(candidate_page.rows),
            candidate_limit_reached=candidate_page.limit_reached,
        )

    if entity == DataRevalidationChangedEntity.REPORTING_PERIOD:
        candidate_page = await _fetch_actionable_warning_candidates(
            db_session,
            reporting_period_id=context.reporting_period_id,
            warning_types=_PARSER_CONFIG_WARNING_TYPES,
        )
        return _AffectedWarningRows(
            rows=candidate_page.rows,
            candidates_examined=len(candidate_page.rows),
            candidate_limit_reached=candidate_page.limit_reached,
        )

    if entity == DataRevalidationChangedEntity.PUBLIC_HOLIDAY:
        candidate_page = await _fetch_actionable_warning_candidates(
            db_session,
            warning_types=("public_holiday_day_mismatch",),
        )
        return _AffectedWarningRows(
            rows=[row for row in candidate_page.rows if _matches_public_holiday(row, context)],
            candidates_examined=len(candidate_page.rows),
            candidate_limit_reached=candidate_page.limit_reached,
        )

    return _AffectedWarningRows(rows=[], candidates_examined=0, candidate_limit_reached=False)


async def _affected_entity_counts(
    context: DataRevalidationContext,
    db_session: Any | None,
) -> dict[str, int]:
    metadata = dict(context.source_metadata or {})
    entity = context.changed_entity
    counts: dict[str, int] = {}

    if entity == DataRevalidationChangedEntity.POSTING_GROUP:
        programme_code = context.programme_code or _non_blank(metadata.get("programme_code"))
        posting_code = _non_blank(metadata.get("posting_code"))
        if programme_code and posting_code:
            counts["resident_postings"] = await _count_query(
                db_session,
                """
                /* data_revalidation:count_resident_postings */
                SELECT COUNT(*) AS count
                FROM resident_postings rp
                JOIN residents r ON r.id = rp.resident_id
                WHERE r.programme_code = :programme_code
                  AND rp.posting_code = :posting_code
                """,
                {"programme_code": programme_code, "posting_code": posting_code},
            )

    if entity == DataRevalidationChangedEntity.PUBLIC_HOLIDAY:
        holiday_date = metadata.get("holiday_date")
        if holiday_date is not None:
            counts["teaching_events"] = await _count_query(
                db_session,
                """
                /* data_revalidation:count_teaching_events */
                SELECT COUNT(*) AS count
                FROM teaching_events
                WHERE event_date = :holiday_date
                """,
                {"holiday_date": holiday_date},
            )

    if entity == DataRevalidationChangedEntity.WEEKEND_EXCEPTION:
        posting_code = _non_blank(metadata.get("posting_code"))
        session_name_pattern = _non_blank(metadata.get("session_name_pattern"))
        if posting_code is None and session_name_pattern is None:
            return counts
        sql_filter = """
            (:posting_code IS NULL OR te.posting_code = :posting_code)
            AND (:session_name_pattern IS NULL OR te.teaching_name ILIKE :session_name_pattern)
        """
        params = {
            "posting_code": posting_code,
            "session_name_pattern": f"%{session_name_pattern}%" if session_name_pattern else None,
        }
        counts["teaching_events"] = await _count_query(
            db_session,
            f"""
            /* data_revalidation:count_teaching_events */
            SELECT COUNT(*) AS count
            FROM teaching_events te
            WHERE {sql_filter}
            """,
            params,
        )
        counts["attendance_records"] = await _count_query(
            db_session,
            f"""
            /* data_revalidation:count_attendance_records */
            SELECT COUNT(*) AS count
            FROM attendance_records ar
            JOIN teaching_events te ON te.id = ar.event_id
            WHERE {sql_filter}
            """,
            params,
        )

    if entity == DataRevalidationChangedEntity.GLOBAL_SESSION_TYPE:
        teaching_name = _non_blank(metadata.get("name"))
        if teaching_name:
            counts["teaching_events"] = await _count_query(
                db_session,
                """
                /* data_revalidation:count_teaching_events */
                SELECT COUNT(*) AS count
                FROM teaching_events
                WHERE teaching_name = :teaching_name
                """,
                {"teaching_name": teaching_name},
            )
            counts["attendance_records"] = await _count_query(
                db_session,
                """
                /* data_revalidation:count_attendance_records */
                SELECT COUNT(*) AS count
                FROM attendance_records ar
                JOIN teaching_events te ON te.id = ar.event_id
                WHERE te.teaching_name = :teaching_name
                """,
                {"teaching_name": teaching_name},
            )

    if entity == DataRevalidationChangedEntity.REPORTING_PERIOD and context.reporting_period_id:
        for table_name, marker in (
            ("upload_logs", "count_period_upload_logs"),
            ("resident_postings", "count_period_resident_postings"),
            ("teaching_targets", "count_period_teaching_targets"),
            ("form_f1_records", "count_period_form_f1_records"),
        ):
            counts[table_name] = await _count_query(
                db_session,
                f"""
                /* data_revalidation:{marker} */
                SELECT COUNT(*) AS count
                FROM {table_name}
                WHERE reporting_period_id = :reporting_period_id
                """,
                {"reporting_period_id": context.reporting_period_id},
            )

    return counts


def _config_next_actions(
    context: DataRevalidationContext,
    *,
    affected_warning_count: int,
) -> list[str]:
    entity = context.changed_entity
    if entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE:
        return [
            "Review affected unmatched multi-posting warning issues with source-cell preview/apply or a full RDB re-upload.",
            "No resident_postings were regenerated and no warning issue status was changed.",
        ]
    if entity == DataRevalidationChangedEntity.LOA_TYPE:
        return [
            "Review affected unknown LOA warning issues manually before resolving or dismissing them.",
            "Use a full RDB re-upload or future audited correction flow if historical source data must be revalidated.",
        ]
    if entity == DataRevalidationChangedEntity.PROGRAMME:
        return [
            "Review parser-related warning issues in this programme if the programme metadata change changes interpretation.",
            "Future uploads and future compliance reads will use the updated programme configuration.",
        ]
    if entity == DataRevalidationChangedEntity.POSTING_GROUP:
        return [
            "Posting groups affect compliance aggregation only; they do not resolve unmatched multi-posting parser warnings.",
            "Future compliance reads will use the updated grouping configuration.",
        ]
    if entity == DataRevalidationChangedEntity.WEEKEND_EXCEPTION:
        return [
            "Weekend exceptions affect future compliance inclusion or read-time mutation checks only.",
            "Existing teaching events and attendance records were not mutated.",
        ]
    if entity == DataRevalidationChangedEntity.GLOBAL_SESSION_TYPE:
        return [
            "Global session types affect future compliance exclusion and secretary dropdown behavior.",
            "Existing teaching events and attendance records were not mutated.",
        ]
    if entity == DataRevalidationChangedEntity.PUBLIC_HOLIDAY:
        return [
            "Public holidays affect future secretary event creation and resident ad-hoc submission blocking.",
            "Existing teaching events were not mutated.",
        ]
    if entity == DataRevalidationChangedEntity.REPORTING_PERIOD:
        return [
            "Reporting-period changes affect operational workflow scope only.",
            "No period snapshots, surplus hibernation, clawback, or compliance calculation was run.",
        ]
    if affected_warning_count:
        return ["Review affected warning issues manually; no warning status was changed."]
    return ["No automatic data mutation was run."]


def _config_message(
    context: DataRevalidationContext,
    *,
    affected_warning_count: int,
) -> str:
    entity = context.changed_entity
    if entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE:
        return (
            "Multi-posting rule change may make existing unmatched multi-posting warnings actionable. "
            "No source cells were reparsed, no resident_postings were regenerated, and no warnings were mutated."
        )
    if entity == DataRevalidationChangedEntity.LOA_TYPE and affected_warning_count:
        return (
            "LOA type change may make existing unknown LOA warning issues actionable. "
            "No RDB source data or warning history was mutated."
        )
    if entity == DataRevalidationChangedEntity.PROGRAMME and affected_warning_count:
        return (
            "Programme parser configuration change may affect existing warning review and future uploads. "
            "No source data was reprocessed and no resident_postings were regenerated."
        )
    return (
        "Config change may affect future compliance reads or workflow checks. "
        "3H-E4 returned a lightweight impact summary without mutating business data or warnings."
    )


def _config_outcome(
    context: DataRevalidationContext,
    *,
    affected_warning_count: int,
) -> DataRevalidationOutcome:
    if context.changed_entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE:
        return DataRevalidationOutcome.MANUAL_REVALIDATION_REQUIRED
    if context.changed_entity in {
        DataRevalidationChangedEntity.LOA_TYPE,
        DataRevalidationChangedEntity.PROGRAMME,
    } and affected_warning_count:
        return DataRevalidationOutcome.MANUAL_REVALIDATION_REQUIRED
    return DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT


async def _config_change_summary(
    *,
    context: DataRevalidationContext,
    db_session: Any | None,
) -> DataRevalidationImpactSummary:
    affected_warning_page = await _affected_warning_rows(
        context,
        db_session,
    )
    affected_warnings = affected_warning_page.rows
    warning_candidates_examined = affected_warning_page.candidates_examined
    warning_candidate_limit_reached = affected_warning_page.candidate_limit_reached
    affected_warning_ids = [
        str(row["issue_id"])
        for row in affected_warnings[:_WARNING_ID_RESPONSE_LIMIT]
        if row.get("issue_id") is not None
    ]
    affected_warning_summaries = [
        _warning_summary(row) for row in affected_warnings[:_WARNING_SUMMARY_RESPONSE_LIMIT]
    ]
    affected_entity_counts = await _affected_entity_counts(context, db_session)
    affected_warning_count = len(affected_warnings)
    affected_warning_issue_ids_truncated = affected_warning_count > len(affected_warning_ids)
    affected_warning_summaries_truncated = affected_warning_count > len(affected_warning_summaries)
    affected_warning_count_is_partial = warning_candidate_limit_reached
    affected_warning_details_are_partial = (
        warning_candidate_limit_reached
        or affected_warning_issue_ids_truncated
        or affected_warning_summaries_truncated
    )
    outcome = _config_outcome(context, affected_warning_count=affected_warning_count)
    details = {
        "backend_handler_available": True,
        "enrichment_version": "3H-E4",
        "affected_scope": _affected_scope(context),
        "affected_warning_count": affected_warning_count,
        "affected_warning_issue_ids": affected_warning_ids,
        "affected_warning_issue_ids_truncated": affected_warning_issue_ids_truncated,
        "affected_warning_summaries": affected_warning_summaries,
        "affected_warning_summaries_truncated": affected_warning_summaries_truncated,
        "warning_candidate_limit": _WARNING_QUERY_LIMIT,
        "warning_candidate_limit_reached": warning_candidate_limit_reached,
        "affected_warning_count_is_partial": affected_warning_count_is_partial,
        "affected_warning_details_are_partial": affected_warning_details_are_partial,
        "affected_entity_counts": affected_entity_counts,
        "warning_candidates_examined": warning_candidates_examined,
        "next_actions": _config_next_actions(
            context,
            affected_warning_count=affected_warning_count,
        ),
    }
    if context.changed_entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE:
        details["concrete_revalidation_handler_available"] = False

    return _summary(
        context=context,
        outcome=outcome,
        message=_config_message(context, affected_warning_count=affected_warning_count),
        rows_examined=warning_candidates_examined,
        warnings_remaining=affected_warning_count,
        affected_warning_ids=affected_warning_ids,
        warning_impacts=_warning_impacts(affected_warnings),
        details=details,
    )


async def revalidate_after_upload(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.TARGETED_REVALIDATION,
        message=(
            "Data Revalidation recorded that upload-time parsing already handled "
            "derived data for this scope; no additional 3H-B mutations were run."
        ),
        details={"backend_handler_available": True},
    )


async def revalidate_after_live_data_correction(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    if context.changed_entity == DataRevalidationChangedEntity.UNKNOWN:
        return _summary(
            context=context,
            outcome=DataRevalidationOutcome.NO_OP,
            message="No Data Revalidation handler is selected for this unknown Live Data correction.",
            affected_models=[],
            details={"backend_handler_available": False},
        )

    if context.changed_entity == DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT:
        return await apply_resident_posting_source_cell_revalidation(
            context=context,
            db_session=db_session,
        )

    affected_models: list[str] | None = None
    details: dict[str, Any] = {"backend_handler_available": True}
    if (
        context.changed_entity == DataRevalidationChangedEntity.TEACHING_TARGET
        and "details_of_training" in context.changed_fields
    ):
        affected_models = ["teaching_targets", "teaching_name_catalogue"]
        details["catalogue_regenerated"] = True

    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
        message=(
            "Live Data correction may affect future compliance reads. "
            "No heavy Data Revalidation handler is implemented."
        ),
        affected_models=affected_models,
        details=details,
    )


async def revalidate_after_config_change(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    if context.changed_entity == DataRevalidationChangedEntity.UNKNOWN:
        return _summary(
            context=context,
            outcome=DataRevalidationOutcome.NO_OP,
            message="No Data Revalidation handler is selected for this unknown config change.",
            affected_models=[],
            details={"backend_handler_available": False},
        )

    return await _config_change_summary(
        context=context,
        db_session=db_session,
    )


async def revalidate_warning_scope(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.WARNING_ONLY,
        message=(
            "Data Revalidation warning refresh hook is not implemented yet; "
            "3H-B records warning-only impact without mutating warnings."
        ),
        details={"backend_handler_available": False},
    )


async def preview_resident_posting_source_cell_revalidation(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    details = {
        key: context.source_metadata[key]
        for key in ("affected_row_count", "replacement_row_count")
        if key in context.source_metadata
    }
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.WARNING_ONLY,
        message=(
            "Preview parsed the corrected RDB source-cell text without mutating "
            "resident_postings or warning history."
        ),
        affected_models=[],
        details={"backend_handler_available": True, **details},
    )


async def apply_resident_posting_source_cell_revalidation(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    details = {
        key: context.source_metadata[key]
        for key in ("affected_row_count", "replacement_row_count")
        if key in context.source_metadata
    }
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.TARGETED_REVALIDATION,
        message=(
            "Applied a targeted RDB source-cell replacement for one resident/month scope. "
            "No compliance calculation, snapshots, surplus hibernation, or clawback generation was run."
        ),
        affected_models=["resident_postings"],
        details={
            "backend_handler_available": True,
            "business_tables_mutated": True,
            **details,
        },
    )
