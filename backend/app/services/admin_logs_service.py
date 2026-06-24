from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.schemas.admin_logs import AdminLogType


_AUDIT_LOG_TYPES = {
    AdminLogType.WARNING_ACTION,
    AdminLogType.SOURCE_CELL_CORRECTION,
    AdminLogType.PARSED_DATA_CORRECTION,
    AdminLogType.CONFIG_MUTATION,
    AdminLogType.DATA_REVALIDATION,
}
_CONFIG_ACTION_PREFIX = "admin.config."
_PARSED_DATA_ACTION_PREFIX = "admin.parsed_data."
_WARNING_ACTION_PREFIX = "admin.upload_warning."
_SOURCE_CELL_ACTION = "admin.parsed_data.resident_posting.source_cell_replace"
_SOURCE_FETCH_CAP = 500


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _uuid_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_ready(value) for key, value in payload.items() if value is not None}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _scope_values(programme_scope: set[str]) -> tuple[str, ...]:
    return tuple(sorted(code for code in programme_scope if code))


def _scope_clause(
    where_clauses: list[str],
    params: dict[str, Any],
    *,
    column_sql: str,
    programme_scope: set[str],
    master_admin: bool,
) -> None:
    if master_admin:
        return
    values = _scope_values(programme_scope)
    if not values:
        where_clauses.append("1 = 0")
        return
    where_clauses.append(f"{column_sql} IN :programme_scope")
    params["programme_scope"] = values


def _where_sql(where_clauses: list[str]) -> str:
    if not where_clauses:
        return ""
    return " WHERE " + " AND ".join(where_clauses)


def _statement(sql: str, *, with_scope: bool = False):
    statement = text(sql)
    if with_scope:
        statement = statement.bindparams(bindparam("programme_scope", expanding=True))
    return statement


def _source_limit(limit: int, offset: int) -> int:
    return min(max(limit + offset, limit, 1) + 50, _SOURCE_FETCH_CAP)


def _has_programme_access(
    programme_code: str | None,
    *,
    programme_scope: set[str],
    master_admin: bool,
) -> bool:
    if master_admin:
        return True
    if not programme_scope or not programme_code:
        return False
    return programme_code in programme_scope


def _upload_visible(
    row: dict[str, Any],
    *,
    programme_scope: set[str],
    master_admin: bool,
) -> bool:
    if master_admin:
        return True
    if not programme_scope:
        return False
    return row.get("upload_type") == "ttf" and row.get("programme_code") in programme_scope


def _source_ref_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    source_ref = _compact_dict(
        {
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "cell_ref": row.get("cell_ref"),
        }
    )
    return source_ref or None


def _first_nested_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    for nested_key in (
        "source",
        "source_cell",
        "verified_source_metadata",
        "client_selected_source_metadata",
        "affected_scope",
    ):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            for key in keys:
                value = nested.get(key)
                if value is not None:
                    return value
    data_revalidation = payload.get("data_revalidation")
    if isinstance(data_revalidation, dict):
        affected_scope = data_revalidation.get("affected_scope")
        if isinstance(affected_scope, dict):
            for key in keys:
                value = affected_scope.get(key)
                if value is not None:
                    return value
    return None


def _metadata_programme_code(metadata: dict[str, Any]) -> str | None:
    return _string_or_none(_first_nested_value(metadata, "programme_code"))


def _metadata_reporting_period_id(metadata: dict[str, Any]) -> str | None:
    return _uuid_string(_first_nested_value(metadata, "reporting_period_id"))


def _metadata_upload_log_id(metadata: dict[str, Any]) -> str | None:
    return _uuid_string(_first_nested_value(metadata, "upload_log_id", "source_upload_log_id"))


def _metadata_warning_issue_id(metadata: dict[str, Any]) -> str | None:
    return _uuid_string(_first_nested_value(metadata, "warning_issue_id"))


def _metadata_upload_warning_id(metadata: dict[str, Any]) -> str | None:
    return _uuid_string(_first_nested_value(metadata, "upload_warning_id", "latest_upload_warning_id"))


def _metadata_source_ref(metadata: dict[str, Any]) -> dict[str, Any] | None:
    source_ref = _compact_dict(
        {
            "sheet_name": _first_nested_value(metadata, "sheet_name"),
            "row_number": _first_nested_value(metadata, "row_number"),
            "cell_ref": _first_nested_value(metadata, "cell_ref"),
        }
    )
    return source_ref or None


def _actor_role(row: dict[str, Any]) -> str | None:
    admin_level = _string_or_none(row.get("actor_admin_level"))
    if admin_level in {"master", "master_admin"}:
        return "master_admin"
    stored_role = _string_or_none(row.get("actor_role"))
    if stored_role == "admin":
        return "programme_pc"
    return stored_role


def _deep_link(log_id: str, log_type: AdminLogType) -> dict[str, Any]:
    route_by_type = {
        AdminLogType.UPLOAD: "admin.upload_log.detail",
        AdminLogType.WARNING: "admin.upload_warning.detail",
        AdminLogType.WARNING_ACTION: "admin.logs.warning_action",
        AdminLogType.SOURCE_CELL_CORRECTION: "admin.logs.source_cell_correction",
        AdminLogType.PARSED_DATA_CORRECTION: "admin.logs.parsed_data_correction",
        AdminLogType.CONFIG_MUTATION: "admin.logs.config_mutation",
        AdminLogType.DATA_REVALIDATION: "admin.logs.data_revalidation",
    }
    return {"route": route_by_type[log_type], "params": {"log_id": log_id}, "query": {}}


def _related_entity(
    *,
    entity_type: str,
    entity_id: Any,
    label: str,
    relationship: str,
    deep_link: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": _uuid_string(entity_id),
        "label": label,
        "relationship": relationship,
        "deep_link": deep_link,
    }


def _optional_related_entity(
    *,
    entity_type: str,
    entity_id: Any,
    label: str,
    relationship: str,
    deep_link: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if entity_id is None:
        return None
    return _related_entity(
        entity_type=entity_type,
        entity_id=entity_id,
        label=label,
        relationship=relationship,
        deep_link=deep_link,
    )


def _related_entities(*entities: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [entity for entity in entities if entity is not None]


def _upload_title(upload_type: str | None) -> str:
    label = (upload_type or "upload").replace("_", " ").upper()
    return f"{label} upload"


def _upload_item(row: dict[str, Any]) -> dict[str, Any]:
    log_uuid = str(row["id"])
    log_id = f"upload:{log_uuid}"
    upload_type = _string_or_none(row.get("upload_type"))
    status = _string_or_none(row.get("status"))
    summary = f"{upload_type or 'Upload'} completed with status {status or 'unknown'}."
    return _compact_dict(
        {
            "id": log_id,
            "log_type": AdminLogType.UPLOAD.value,
            "occurred_at": _iso(row.get("uploaded_at") or row.get("occurred_at")),
            "actor_user_id": _uuid_string(row.get("uploaded_by")),
            "actor_name": row.get("uploaded_by_name"),
            "actor_role": "admin",
            "stored_actor_role": None,
            "actor_admin_level": None,
            "programme_code": row.get("programme_code"),
            "reporting_period_id": _uuid_string(row.get("reporting_period_id")),
            "entity_type": "upload_log",
            "entity_id": log_uuid,
            "upload_log_id": log_uuid,
            "status": status,
            "title": _upload_title(upload_type),
            "summary": summary,
            "deep_link": _deep_link(log_id, AdminLogType.UPLOAD),
        }
    )


def _warning_item(row: dict[str, Any]) -> dict[str, Any]:
    log_uuid = str(row["id"])
    log_id = f"warning:{log_uuid}"
    warning_type = _string_or_none(row.get("warning_type")) or "warning"
    source_ref = _source_ref_from_row(row)
    return _compact_dict(
        {
            "id": log_id,
            "log_type": AdminLogType.WARNING.value,
            "occurred_at": _iso(row.get("last_seen_at") or row.get("occurred_at")),
            "programme_code": row.get("programme_code"),
            "reporting_period_id": _uuid_string(row.get("reporting_period_id")),
            "entity_type": "warning_issue",
            "entity_id": log_uuid,
            "upload_log_id": _uuid_string(row.get("last_upload_log_id")),
            "warning_issue_id": log_uuid,
            "upload_warning_id": _uuid_string(row.get("latest_upload_warning_id")),
            "status": row.get("status"),
            "title": f"{warning_type.replace('_', ' ').title()} warning",
            "summary": row.get("message") or row.get("suggested_action") or "Upload warning issue recorded.",
            "source_ref": source_ref,
            "deep_link": _deep_link(log_id, AdminLogType.WARNING),
        }
    )


def _primary_audit_log_type(action: str | None) -> AdminLogType | None:
    if not action:
        return None
    if action.startswith(_WARNING_ACTION_PREFIX):
        return AdminLogType.WARNING_ACTION
    if action == _SOURCE_CELL_ACTION:
        return AdminLogType.SOURCE_CELL_CORRECTION
    if action.startswith(_PARSED_DATA_ACTION_PREFIX):
        return AdminLogType.PARSED_DATA_CORRECTION
    if action.startswith(_CONFIG_ACTION_PREFIX):
        return AdminLogType.CONFIG_MUTATION
    return None


def _action_label(action: str | None) -> str:
    if not action:
        return "admin action"
    return action.removeprefix("admin.").replace(".", " ").replace("_", " ")


def _data_revalidation_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = metadata.get("data_revalidation")
    return payload if isinstance(payload, dict) else {}


def _audit_is_warning_linked(
    row: dict[str, Any],
    *,
    log_type: AdminLogType,
    metadata: dict[str, Any],
) -> bool:
    action = _string_or_none(row.get("action"))
    if action and action.startswith(_WARNING_ACTION_PREFIX):
        return True
    return (
        action == _SOURCE_CELL_ACTION
        and log_type in {
            AdminLogType.SOURCE_CELL_CORRECTION,
            AdminLogType.DATA_REVALIDATION,
        }
        and _metadata_warning_issue_id(metadata) is not None
    )


def _audit_base_item(
    row: dict[str, Any],
    *,
    log_type: AdminLogType,
    metadata: dict[str, Any],
    data_revalidation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit_uuid = str(row["id"])
    log_id = f"{log_type.value}:{audit_uuid}"
    warning_linked = _audit_is_warning_linked(row, log_type=log_type, metadata=metadata)
    programme_code = (
        _string_or_none(row.get("linked_warning_programme_code"))
        if warning_linked
        else _metadata_programme_code(metadata)
    )
    reporting_period_id = _metadata_reporting_period_id(metadata)
    source_ref = _metadata_source_ref(metadata)
    action = _string_or_none(row.get("action"))
    outcome = None
    summary = None
    status = None
    if data_revalidation:
        outcome = _string_or_none(data_revalidation.get("outcome"))
        summary = _string_or_none(data_revalidation.get("summary")) or "Data revalidation summary recorded."
        status = outcome
    elif log_type == AdminLogType.WARNING_ACTION:
        after_json = _json_object(row.get("after_json"))
        status = _string_or_none(
            row.get("after_status")
            or row.get("after_resolution_action")
            or after_json.get("status")
            or after_json.get("resolution_action")
        )
        summary = f"Warning action recorded: {_action_label(action)}."
    elif log_type == AdminLogType.SOURCE_CELL_CORRECTION:
        summary = "Source cell correction applied."
    elif log_type == AdminLogType.PARSED_DATA_CORRECTION:
        summary = "Parsed data correction applied."
    elif log_type == AdminLogType.CONFIG_MUTATION:
        summary = f"Configuration mutation recorded: {_action_label(action)}."

    title_by_type = {
        AdminLogType.WARNING_ACTION: "Warning action",
        AdminLogType.SOURCE_CELL_CORRECTION: "Source cell correction",
        AdminLogType.PARSED_DATA_CORRECTION: "Parsed data correction",
        AdminLogType.CONFIG_MUTATION: "Config mutation",
        AdminLogType.DATA_REVALIDATION: "Data revalidation",
    }
    warning_issue_id = None
    if log_type == AdminLogType.WARNING_ACTION and row.get("entity_type") == "warning_issue":
        warning_issue_id = _uuid_string(row.get("linked_warning_issue_id") or row.get("entity_id"))
    elif warning_linked:
        warning_issue_id = _uuid_string(row.get("linked_warning_issue_id")) or _metadata_warning_issue_id(metadata)
    return _compact_dict(
        {
            "id": log_id,
            "log_type": log_type.value,
            "occurred_at": _iso(row.get("created_at") or row.get("occurred_at")),
            "actor_user_id": _uuid_string(row.get("actor_user_id")),
            "actor_name": row.get("actor_name"),
            "actor_role": _actor_role(row),
            "stored_actor_role": row.get("actor_role"),
            "actor_admin_level": row.get("actor_admin_level"),
            "programme_code": programme_code,
            "reporting_period_id": reporting_period_id,
            "entity_type": row.get("entity_type"),
            "entity_id": _uuid_string(row.get("entity_id")),
            "upload_log_id": _metadata_upload_log_id(metadata),
            "warning_issue_id": warning_issue_id,
            "upload_warning_id": _metadata_upload_warning_id(metadata),
            "status": status,
            "outcome": outcome,
            "title": title_by_type[log_type],
            "summary": summary,
            "source_ref": source_ref,
            "deep_link": _deep_link(log_id, log_type),
        }
    )


def _audit_items(
    row: dict[str, Any],
    *,
    requested_log_type: AdminLogType | None = None,
) -> list[dict[str, Any]]:
    action = _string_or_none(row.get("action"))
    metadata = _json_object(row.get("metadata_json"))
    primary_type = _primary_audit_log_type(action)
    items: list[dict[str, Any]] = []
    if primary_type and requested_log_type in {None, primary_type}:
        items.append(_audit_base_item(row, log_type=primary_type, metadata=metadata))
    data_revalidation = _data_revalidation_payload(metadata)
    if data_revalidation and requested_log_type in {None, AdminLogType.DATA_REVALIDATION}:
        items.append(
            _audit_base_item(
                row,
                log_type=AdminLogType.DATA_REVALIDATION,
                metadata=metadata,
                data_revalidation=data_revalidation,
            )
        )
    return items


def _item_visible(
    item: dict[str, Any],
    *,
    programme_scope: set[str],
    master_admin: bool,
    source_row: dict[str, Any] | None = None,
) -> bool:
    log_type = item.get("log_type")
    if log_type == AdminLogType.UPLOAD.value:
        return _upload_visible(source_row or item, programme_scope=programme_scope, master_admin=master_admin)
    return _has_programme_access(
        item.get("programme_code"),
        programme_scope=programme_scope,
        master_admin=master_admin,
    )


def _matches_search(item: dict[str, Any], search: str | None) -> bool:
    if not search or not search.strip():
        return True
    needle = search.strip().casefold()
    haystack = " ".join(
        str(value)
        for value in (
            item.get("id"),
            item.get("log_type"),
            item.get("title"),
            item.get("summary"),
            item.get("programme_code"),
            item.get("status"),
            item.get("outcome"),
            item.get("entity_type"),
            item.get("entity_id"),
            item.get("upload_log_id"),
            item.get("warning_issue_id"),
        )
        if value is not None
    ).casefold()
    return needle in haystack


def _matches_secondary_filters(
    item: dict[str, Any],
    *,
    correction_type: str | None,
    config_entity_type: str | None,
    status: str | None,
    outcome: str | None,
    actor_role: str | None,
) -> bool:
    log_type = item.get("log_type")
    if correction_type:
        if log_type not in {
            AdminLogType.SOURCE_CELL_CORRECTION.value,
            AdminLogType.PARSED_DATA_CORRECTION.value,
        }:
            return False
        if correction_type not in {log_type, item.get("entity_type"), "source_cell"}:
            return False
    if config_entity_type:
        if log_type != AdminLogType.CONFIG_MUTATION.value:
            return False
        if item.get("entity_type") != config_entity_type:
            return False
    if status and item.get("status") != status:
        return False
    if outcome and item.get("outcome") != outcome:
        return False
    if actor_role and item.get("actor_role") != actor_role:
        return False
    return True


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


def _audit_linked_warning_join_sql() -> str:
    return f"""
            LEFT JOIN warning_issues linked_wi
              ON (
                  al.action LIKE '{_WARNING_ACTION_PREFIX}%'
                  AND al.entity_type = 'warning_issue'
                  AND CAST(linked_wi.id AS TEXT) = CAST(al.entity_id AS TEXT)
              )
              OR (
                  al.action = '{_SOURCE_CELL_ACTION}'
                  AND al.metadata_json ? 'warning_issue_id'
                  AND CAST(linked_wi.id AS TEXT) = al.metadata_json ->> 'warning_issue_id'
              )
            """


def _add_audit_scope_clause(
    where_clauses: list[str],
    params: dict[str, Any],
    *,
    programme_scope: set[str],
    master_admin: bool,
) -> None:
    if master_admin:
        return
    values = _scope_values(programme_scope)
    if not values:
        where_clauses.append("1 = 0")
        return
    params["programme_scope"] = values
    where_clauses.append(
        f"""
        (
            (
                (
                    al.action LIKE '{_WARNING_ACTION_PREFIX}%'
                    OR (
                        al.action = '{_SOURCE_CELL_ACTION}'
                        AND al.metadata_json ? 'warning_issue_id'
                    )
                )
                AND linked_wi.programme_code IN :programme_scope
            )
            OR (
                NOT (
                    al.action LIKE '{_WARNING_ACTION_PREFIX}%'
                    OR (
                        al.action = '{_SOURCE_CELL_ACTION}'
                        AND al.metadata_json ? 'warning_issue_id'
                    )
                )
                AND al.metadata_json ->> 'programme_code' IN :programme_scope
            )
        )
        """
    )


def _base_params(
    *,
    source_limit: int,
) -> dict[str, Any]:
    return {"source_limit": source_limit}


async def _fetch_upload_rows(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    date_from: datetime | None,
    date_to: datetime | None,
    actor_user_id: UUID | None,
    programme_code: str | None,
    reporting_period_id: UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    upload_type: str | None,
    status: str | None,
    source_limit: int,
) -> list[dict[str, Any]]:
    if entity_type and entity_type != "upload_log":
        return []
    where_clauses: list[str] = []
    params = _base_params(source_limit=source_limit)
    if date_from is not None:
        where_clauses.append("ul.uploaded_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        where_clauses.append("ul.uploaded_at <= :date_to")
        params["date_to"] = date_to
    if actor_user_id is not None:
        where_clauses.append("CAST(ul.uploaded_by AS TEXT) = :actor_user_id")
        params["actor_user_id"] = str(actor_user_id)
    if programme_code is not None:
        where_clauses.append("ul.programme_code = :programme_code")
        params["programme_code"] = programme_code
    if reporting_period_id is not None:
        where_clauses.append("CAST(ul.reporting_period_id AS TEXT) = :reporting_period_id")
        params["reporting_period_id"] = str(reporting_period_id)
    if entity_id is not None:
        where_clauses.append("CAST(ul.id AS TEXT) = :entity_id")
        params["entity_id"] = entity_id
    if upload_type is not None:
        where_clauses.append("ul.upload_type = :upload_type")
        params["upload_type"] = upload_type
    if status is not None:
        where_clauses.append("ul.status = :status")
        params["status"] = status
    if not master_admin:
        where_clauses.append("ul.upload_type = 'ttf'")
        _scope_clause(
            where_clauses,
            params,
            column_sql="ul.programme_code",
            programme_scope=programme_scope,
            master_admin=master_admin,
        )
    result = await db.execute(
        _statement(
            f"""
            /* admin_logs:upload_rows */
            SELECT
                ul.id,
                ul.upload_type,
                ul.uploaded_by,
                u.name AS uploaded_by_name,
                ul.uploaded_at,
                ul.reporting_period_id,
                ul.programme_code,
                ul.status
            FROM upload_logs ul
            LEFT JOIN users u ON u.id = ul.uploaded_by
            {_where_sql(where_clauses)}
            ORDER BY ul.uploaded_at DESC, ul.id DESC
            LIMIT :source_limit
            """,
            with_scope="programme_scope" in params,
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


async def _fetch_warning_rows(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    date_from: datetime | None,
    date_to: datetime | None,
    programme_code: str | None,
    reporting_period_id: UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    upload_type: str | None,
    warning_type: str | None,
    status: str | None,
    source_limit: int,
) -> list[dict[str, Any]]:
    if entity_type and entity_type != "warning_issue":
        return []
    where_clauses: list[str] = []
    params = _base_params(source_limit=source_limit)
    if date_from is not None:
        where_clauses.append("wi.last_seen_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        where_clauses.append("wi.last_seen_at <= :date_to")
        params["date_to"] = date_to
    if programme_code is not None:
        where_clauses.append("wi.programme_code = :programme_code")
        params["programme_code"] = programme_code
    if reporting_period_id is not None:
        where_clauses.append("CAST(wi.reporting_period_id AS TEXT) = :reporting_period_id")
        params["reporting_period_id"] = str(reporting_period_id)
    if entity_id is not None:
        where_clauses.append("CAST(wi.id AS TEXT) = :entity_id")
        params["entity_id"] = entity_id
    if upload_type is not None:
        where_clauses.append("last_ul.upload_type = :upload_type")
        params["upload_type"] = upload_type
    if warning_type is not None:
        where_clauses.append("wi.warning_type = :warning_type")
        params["warning_type"] = warning_type
    if status is not None:
        where_clauses.append("wi.status = :status")
        params["status"] = status
    _scope_clause(
        where_clauses,
        params,
        column_sql="wi.programme_code",
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    result = await db.execute(
        _statement(
            f"""
            /* admin_logs:warning_rows */
            SELECT
                wi.id,
                wi.fingerprint,
                wi.warning_type,
                wi.severity,
                wi.status,
                wi.first_seen_upload_log_id AS first_upload_log_id,
                wi.last_seen_upload_log_id AS last_upload_log_id,
                wi.first_seen_at,
                wi.last_seen_at,
                wi.reporting_period_id,
                wi.programme_code,
                wi.resident_id,
                wi.mcr,
                wi.month_label,
                wi.resolution_source_type,
                wi.resolution_source_id,
                wi.resolution_note,
                wi.resolved_by,
                wi.resolved_at,
                latest_uw.id AS latest_upload_warning_id,
                latest_uw.message,
                latest_uw.suggested_action,
                latest_uw.sheet_name,
                latest_uw.row_number,
                latest_uw.cell_ref,
                latest_uw.created_at AS latest_warning_created_at
            FROM warning_issues wi
            LEFT JOIN upload_logs last_ul ON last_ul.id = wi.last_seen_upload_log_id
            LEFT JOIN LATERAL (
                SELECT
                    uw.id,
                    uw.message,
                    uw.suggested_action,
                    uw.sheet_name,
                    uw.row_number,
                    uw.cell_ref,
                    uw.created_at
                FROM upload_warnings uw
                WHERE uw.issue_id = wi.id
                ORDER BY uw.created_at DESC, uw.id DESC
                LIMIT 1
            ) latest_uw ON TRUE
            {_where_sql(where_clauses)}
            ORDER BY wi.last_seen_at DESC, wi.id DESC
            LIMIT :source_limit
            """,
            with_scope="programme_scope" in params,
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


async def _fetch_audit_rows(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    date_from: datetime | None,
    date_to: datetime | None,
    actor_user_id: UUID | None,
    programme_code: str | None,
    reporting_period_id: UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    actor_role: str | None,
    status: str | None,
    outcome: str | None,
    source_limit: int,
) -> list[dict[str, Any]]:
    where_clauses = [
        """
        (
            al.action LIKE 'admin.upload_warning.%'
            OR al.action LIKE 'admin.parsed_data.%'
            OR al.action LIKE 'admin.config.%'
        )
        """,
    ]
    params = _base_params(source_limit=source_limit)
    if date_from is not None:
        where_clauses.append("al.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        where_clauses.append("al.created_at <= :date_to")
        params["date_to"] = date_to
    if actor_user_id is not None:
        where_clauses.append("CAST(al.actor_user_id AS TEXT) = :actor_user_id")
        params["actor_user_id"] = str(actor_user_id)
    if actor_role == "master_admin":
        where_clauses.append(
            "(al.actor_role = 'admin' AND al.actor_admin_level IN ('master', 'master_admin'))"
        )
    elif actor_role is not None:
        where_clauses.append("al.actor_role = :actor_role")
        params["actor_role"] = actor_role
    if programme_code is not None:
        where_clauses.append(
            "COALESCE(linked_wi.programme_code, al.metadata_json ->> 'programme_code') = :programme_code"
        )
        params["programme_code"] = programme_code
    if reporting_period_id is not None:
        where_clauses.append("al.metadata_json ->> 'reporting_period_id' = :reporting_period_id")
        params["reporting_period_id"] = str(reporting_period_id)
    if entity_type is not None:
        where_clauses.append("al.entity_type = :entity_type")
        params["entity_type"] = entity_type
    if entity_id is not None:
        where_clauses.append("CAST(al.entity_id AS TEXT) = :entity_id")
        params["entity_id"] = entity_id
    if status is not None:
        where_clauses.append(
            "(al.after_json ->> 'status' = :status OR al.after_json ->> 'resolution_action' = :status)"
        )
        params["status"] = status
    if outcome is not None:
        where_clauses.append("al.metadata_json #>> '{data_revalidation,outcome}' = :outcome")
        params["outcome"] = outcome
    _add_audit_scope_clause(
        where_clauses,
        params,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    result = await db.execute(
        _statement(
            f"""
            /* admin_logs:audit_rows */
            SELECT
                al.id,
                al.actor_user_id,
                al.actor_role,
                al.actor_name,
                al.actor_site,
                al.actor_programme,
                al.actor_admin_level,
                al.action,
                al.entity_type,
                al.entity_id,
                al.after_json ->> 'status' AS after_status,
                al.after_json ->> 'resolution_action' AS after_resolution_action,
                al.metadata_json,
                al.created_at,
                linked_wi.id AS linked_warning_issue_id,
                linked_wi.programme_code AS linked_warning_programme_code
            FROM audit_logs al
            {_audit_linked_warning_join_sql()}
            {_where_sql(where_clauses)}
            ORDER BY al.created_at DESC, al.id DESC
            LIMIT :source_limit
            """,
            with_scope="programme_scope" in params,
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


async def list_admin_logs(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    log_type: AdminLogType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    actor_user_id: UUID | None = None,
    actor_role: str | None = None,
    programme_code: str | None = None,
    reporting_period_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    upload_type: str | None = None,
    warning_type: str | None = None,
    correction_type: str | None = None,
    config_entity_type: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _validate_programme_filter(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    requested_log_type = log_type if isinstance(log_type, AdminLogType) else None
    source_limit = _source_limit(limit, offset)
    items: list[dict[str, Any]] = []

    if requested_log_type in {None, AdminLogType.UPLOAD}:
        upload_rows = await _fetch_upload_rows(
            db,
            programme_scope=programme_scope,
            master_admin=master_admin,
            date_from=date_from,
            date_to=date_to,
            actor_user_id=actor_user_id,
            programme_code=programme_code,
            reporting_period_id=reporting_period_id,
            entity_type=entity_type,
            entity_id=entity_id,
            upload_type=upload_type,
            status=status,
            source_limit=source_limit,
        )
        for row in upload_rows:
            item = _upload_item(row)
            if _item_visible(item, programme_scope=programme_scope, master_admin=master_admin, source_row=row):
                items.append(item)

    if requested_log_type in {None, AdminLogType.WARNING} and actor_user_id is None and actor_role is None:
        warning_rows = await _fetch_warning_rows(
            db,
            programme_scope=programme_scope,
            master_admin=master_admin,
            date_from=date_from,
            date_to=date_to,
            programme_code=programme_code,
            reporting_period_id=reporting_period_id,
            entity_type=entity_type,
            entity_id=entity_id,
            upload_type=upload_type,
            warning_type=warning_type,
            status=status,
            source_limit=source_limit,
        )
        for row in warning_rows:
            item = _warning_item(row)
            if _item_visible(item, programme_scope=programme_scope, master_admin=master_admin, source_row=row):
                items.append(item)

    if requested_log_type in {None, *_AUDIT_LOG_TYPES}:
        audit_rows = await _fetch_audit_rows(
            db,
            programme_scope=programme_scope,
            master_admin=master_admin,
            date_from=date_from,
            date_to=date_to,
            actor_user_id=actor_user_id,
            programme_code=programme_code,
            reporting_period_id=reporting_period_id,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_role=None if actor_role == "programme_pc" else actor_role,
            status=status,
            outcome=outcome,
            source_limit=source_limit,
        )
        for row in audit_rows:
            for item in _audit_items(row, requested_log_type=requested_log_type):
                if _item_visible(item, programme_scope=programme_scope, master_admin=master_admin, source_row=row):
                    items.append(item)

    filtered_items = [
        item
        for item in items
        if _matches_search(item, search)
        and _matches_secondary_filters(
            item,
            correction_type=correction_type,
            config_entity_type=config_entity_type,
            status=status,
            outcome=outcome,
            actor_role=actor_role,
        )
    ]
    filtered_items.sort(key=lambda item: (item.get("occurred_at") or "", item["id"]), reverse=True)
    total = len(filtered_items)
    return {
        "items": filtered_items[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _parse_log_id(log_id: str) -> tuple[AdminLogType, str]:
    if ":" not in log_id:
        raise ApiError(
            status_code=404,
            detail="Admin log not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    prefix, raw_uuid = log_id.split(":", 1)
    try:
        log_type = AdminLogType(prefix)
        UUID(raw_uuid)
    except (ValueError, TypeError) as exc:
        raise ApiError(
            status_code=404,
            detail="Admin log not found",
            error_code=ErrorCode.NOT_FOUND.value,
        ) from exc
    return log_type, raw_uuid


async def _fetch_upload_detail(
    db: AsyncSession,
    log_uuid: str,
    *,
    include_raw_summary: bool,
) -> dict[str, Any] | None:
    summary_select = ",\n                ul.summary" if include_raw_summary else ""
    result = await db.execute(
        text(
            f"""
            /* admin_logs:upload_detail */
            SELECT
                ul.id,
                ul.upload_type,
                ul.uploaded_by,
                u.name AS uploaded_by_name,
                ul.uploaded_at,
                ul.reporting_period_id,
                ul.programme_code,
                ul.status
                {summary_select}
            FROM upload_logs ul
            LEFT JOIN users u ON u.id = ul.uploaded_by
            WHERE CAST(ul.id AS TEXT) = :log_uuid
            """
        ),
        {"log_uuid": log_uuid, "include_raw_summary": include_raw_summary},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _fetch_warning_detail(db: AsyncSession, log_uuid: str) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            /* admin_logs:warning_detail */
            SELECT
                wi.id,
                wi.fingerprint,
                wi.warning_type,
                wi.severity,
                wi.status,
                wi.first_seen_upload_log_id AS first_upload_log_id,
                wi.last_seen_upload_log_id AS last_upload_log_id,
                wi.first_seen_at,
                wi.last_seen_at,
                wi.reporting_period_id,
                wi.programme_code,
                wi.resident_id,
                wi.mcr,
                wi.month_label,
                wi.resolution_source_type,
                wi.resolution_source_id,
                wi.resolution_note,
                wi.resolved_by,
                wi.resolved_at,
                latest_uw.id AS latest_upload_warning_id,
                latest_uw.message,
                latest_uw.suggested_action,
                latest_uw.sheet_name,
                latest_uw.row_number,
                latest_uw.cell_ref,
                latest_uw.source_payload,
                latest_uw.created_at AS latest_warning_created_at
            FROM warning_issues wi
            LEFT JOIN LATERAL (
                SELECT
                    uw.id,
                    uw.message,
                    uw.suggested_action,
                    uw.sheet_name,
                    uw.row_number,
                    uw.cell_ref,
                    uw.source_payload,
                    uw.created_at
                FROM upload_warnings uw
                WHERE uw.issue_id = wi.id
                ORDER BY uw.created_at DESC, uw.id DESC
                LIMIT 1
            ) latest_uw ON TRUE
            WHERE CAST(wi.id AS TEXT) = :log_uuid
            """
        ),
        {"log_uuid": log_uuid},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _fetch_audit_detail(db: AsyncSession, log_uuid: str) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            /* admin_logs:audit_detail */
            SELECT
                al.id,
                al.actor_user_id,
                al.actor_role,
                al.actor_name,
                al.actor_site,
                al.actor_programme,
                al.actor_admin_level,
                al.action,
                al.entity_type,
                al.entity_id,
                al.before_json,
                al.after_json,
                al.metadata_json,
                al.created_at,
                linked_wi.id AS linked_warning_issue_id,
                linked_wi.programme_code AS linked_warning_programme_code
            FROM audit_logs al
            {_audit_linked_warning_join_sql()}
            WHERE CAST(al.id AS TEXT) = :log_uuid
            """
        ),
        {"log_uuid": log_uuid},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


def _raw_upload_summary(row: dict[str, Any]) -> dict[str, Any]:
    return _json_object(row.get("summary"))


def _upload_detail_payload(
    row: dict[str, Any],
    *,
    include_raw_summary: bool,
) -> dict[str, Any]:
    item = _upload_item(row)
    immutable_evidence = _compact_dict(
        {
            "id": row.get("id"),
            "upload_type": row.get("upload_type"),
            "uploaded_by": row.get("uploaded_by"),
            "uploaded_by_name": row.get("uploaded_by_name"),
            "uploaded_at": row.get("uploaded_at"),
            "reporting_period_id": row.get("reporting_period_id"),
            "programme_code": row.get("programme_code"),
            "status": row.get("status"),
        }
    )
    if include_raw_summary:
        immutable_evidence["summary"] = _json_ready(_raw_upload_summary(row))
    return {
        "id": item["id"],
        "log_type": AdminLogType.UPLOAD.value,
        "list_item": item,
        "immutable_evidence": immutable_evidence,
        "workflow_status": {"status": row.get("status")},
        "related_entities": _related_entities(
            _related_entity(
                entity_type="upload_log",
                entity_id=row.get("id"),
                label="Upload log",
                relationship="upload_log",
                deep_link=item.get("deep_link"),
            )
        ),
        "available_actions": [
            {
                "action": "view_raw_summary",
                "label": "View raw summary",
                "method": "GET",
                "endpoint": f"/admin/logs/{item['id']}?include_raw_summary=true",
                "params": {},
            }
        ],
        "source_ref": None,
    }


def _warning_detail_payload(row: dict[str, Any]) -> dict[str, Any]:
    item = _warning_item(row)
    source_ref = _source_ref_from_row(row)
    source_payload = _json_object(row.get("source_payload"))
    workflow_status = _compact_dict(
        {
            "status": row.get("status"),
            "resolution_source_type": row.get("resolution_source_type"),
            "resolution_source_id": row.get("resolution_source_id"),
            "resolution_note": row.get("resolution_note"),
            "resolved_by": row.get("resolved_by"),
            "resolved_at": row.get("resolved_at"),
        }
    )
    immutable_evidence = _compact_dict(
        {
            "id": row.get("id"),
            "fingerprint": row.get("fingerprint"),
            "warning_type": row.get("warning_type"),
            "severity": row.get("severity"),
            "message": row.get("message"),
            "suggested_action": row.get("suggested_action"),
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
            "source_payload": source_payload or None,
        }
    )
    return {
        "id": item["id"],
        "log_type": AdminLogType.WARNING.value,
        "list_item": item,
        "immutable_evidence": immutable_evidence,
        "workflow_status": workflow_status,
        "related_entities": _related_entities(
            _related_entity(
                entity_type="warning_issue",
                entity_id=row.get("id"),
                label="Warning issue",
                relationship="workflow_issue",
                deep_link=item.get("deep_link"),
            ),
            _optional_related_entity(
                entity_type="upload_warning",
                entity_id=row.get("latest_upload_warning_id"),
                label="Latest warning occurrence",
                relationship="occurrence",
            ),
            _optional_related_entity(
                entity_type="upload_log",
                entity_id=row.get("last_upload_log_id"),
                label="Source upload",
                relationship="upload_log",
            ),
            _optional_related_entity(
                entity_type="reporting_period",
                entity_id=row.get("reporting_period_id"),
                label="Reporting period",
                relationship="related",
            ),
            _optional_related_entity(
                entity_type="resident",
                entity_id=row.get("resident_id"),
                label="Resident",
                relationship="resident",
            ),
        ),
        "available_actions": [],
        "source_ref": source_ref,
    }


def _audit_detail_payload(
    row: dict[str, Any],
    *,
    log_type: AdminLogType,
) -> dict[str, Any]:
    items = _audit_items(row, requested_log_type=log_type)
    if not items:
        raise ApiError(
            status_code=404,
            detail="Admin log not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    item = items[0]
    metadata = _json_object(row.get("metadata_json"))
    data_revalidation = _data_revalidation_payload(metadata)
    workflow_status = None
    if log_type == AdminLogType.DATA_REVALIDATION and data_revalidation:
        workflow_status = _compact_dict(
            {
                "outcome": data_revalidation.get("outcome"),
                "summary": data_revalidation.get("summary"),
            }
        )
    immutable_evidence = _compact_dict(
        {
            "audit_log_id": row.get("id"),
            "action": row.get("action"),
            "entity_type": row.get("entity_type"),
            "entity_id": row.get("entity_id"),
            "before_json": _json_object(row.get("before_json")) or None,
            "after_json": _json_object(row.get("after_json")) or None,
            "metadata_json": metadata or None,
        }
    )
    return {
        "id": item["id"],
        "log_type": log_type.value,
        "list_item": item,
        "immutable_evidence": immutable_evidence,
        "workflow_status": workflow_status,
        "related_entities": _related_entities(
            _related_entity(
                entity_type="audit_log",
                entity_id=row.get("id"),
                label="Audit log",
                relationship="audit_log",
            ),
            _optional_related_entity(
                entity_type=str(row.get("entity_type") or "entity"),
                entity_id=row.get("entity_id"),
                label="Primary entity",
                relationship="primary",
            ),
            _optional_related_entity(
                entity_type="upload_log",
                entity_id=item.get("upload_log_id"),
                label="Source upload",
                relationship="upload_log",
            ),
            _optional_related_entity(
                entity_type="warning_issue",
                entity_id=item.get("warning_issue_id"),
                label="Warning issue",
                relationship="workflow_issue",
            ),
            _optional_related_entity(
                entity_type="reporting_period",
                entity_id=item.get("reporting_period_id"),
                label="Reporting period",
                relationship="related",
            ),
        ),
        "available_actions": [],
        "source_ref": item.get("source_ref"),
    }


async def get_admin_log(
    db: AsyncSession,
    *,
    log_id: str,
    programme_scope: set[str],
    master_admin: bool,
    include_raw_summary: bool = False,
) -> dict[str, Any]:
    log_type, log_uuid = _parse_log_id(log_id)
    if log_type == AdminLogType.UPLOAD:
        row = await _fetch_upload_detail(
            db,
            log_uuid,
            include_raw_summary=include_raw_summary,
        )
        if row is None:
            raise ApiError(
                status_code=404,
                detail="Admin log not found",
                error_code=ErrorCode.NOT_FOUND.value,
            )
        item = _upload_item(row)
        if not _item_visible(item, programme_scope=programme_scope, master_admin=master_admin, source_row=row):
            raise ApiError(
                status_code=403,
                detail="Forbidden - admin log outside scope",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        return _upload_detail_payload(row, include_raw_summary=include_raw_summary)

    if log_type == AdminLogType.WARNING:
        row = await _fetch_warning_detail(db, log_uuid)
        if row is None:
            raise ApiError(
                status_code=404,
                detail="Admin log not found",
                error_code=ErrorCode.NOT_FOUND.value,
            )
        item = _warning_item(row)
        if not _item_visible(item, programme_scope=programme_scope, master_admin=master_admin, source_row=row):
            raise ApiError(
                status_code=403,
                detail="Forbidden - admin log outside scope",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        return _warning_detail_payload(row)

    if log_type in _AUDIT_LOG_TYPES:
        row = await _fetch_audit_detail(db, log_uuid)
        if row is None:
            raise ApiError(
                status_code=404,
                detail="Admin log not found",
                error_code=ErrorCode.NOT_FOUND.value,
            )
        payload = _audit_detail_payload(row, log_type=log_type)
        if not _item_visible(
            payload["list_item"],
            programme_scope=programme_scope,
            master_admin=master_admin,
            source_row=row,
        ):
            raise ApiError(
                status_code=403,
                detail="Forbidden - admin log outside scope",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        return payload

    raise ApiError(
        status_code=404,
        detail="Admin log not found",
        error_code=ErrorCode.NOT_FOUND.value,
    )
