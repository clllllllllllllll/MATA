from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.cache import cache


@dataclass(frozen=True)
class CacheInvalidationCall:
    domain: str
    scope: dict[str, str]


_CONFIG_DOMAINS_BY_ENTITY = {
    "reporting_period": (
        "config",
        "resident_events",
        "resident_attendance",
        "resident_dashboard",
        "admin_reports",
    ),
    "public_holiday": (
        "config",
        "public_holidays",
        "secretary_events",
        "resident_events",
        "resident_attendance",
        "resident_dashboard",
        "admin_reports",
    ),
    "programme": (
        "config",
        "parsed_data",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
    "loa_type": ("config", "parsed_data", "upload_warnings"),
    "multi_posting_rule": ("config", "parsed_data", "upload_warnings"),
    "posting_group": ("config", "resident_dashboard", "admin_reports"),
    "weekend_exception": (
        "config",
        "resident_attendance",
        "resident_dashboard",
        "admin_reports",
    ),
    "global_session_type": (
        "config",
        "teaching_name_catalogue",
        "secretary_events",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
}

_UPLOAD_DOMAINS_BY_TYPE = {
    "rdb": (
        "upload_logs",
        "upload_warnings",
        "parsed_data",
        "resident_postings",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
    "ttf": (
        "upload_logs",
        "upload_warnings",
        "teaching_targets",
        "teaching_name_catalogue",
        "secretary_events",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
    "form_f1": (
        "upload_logs",
        "upload_warnings",
        "form_f1",
        "resident_dashboard",
        "admin_reports",
    ),
    "public_holidays": (
        "upload_logs",
        "upload_warnings",
        "public_holidays",
        "academic_month_boundaries",
        "secretary_events",
        "resident_events",
        "resident_attendance",
        "resident_dashboard",
        "admin_reports",
    ),
}

_LIVE_DATA_DOMAINS_BY_ENTITY = {
    "resident": ("parsed_data", "resident_events", "resident_dashboard", "admin_reports"),
    "resident_posting": (
        "parsed_data",
        "resident_postings",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
    "resident_posting_source_cell": (
        "parsed_data",
        "resident_postings",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
    "teaching_target": (
        "parsed_data",
        "teaching_targets",
        "teaching_name_catalogue",
        "secretary_events",
        "resident_events",
        "resident_dashboard",
        "admin_reports",
    ),
    "form_f1_record": (
        "parsed_data",
        "form_f1",
        "resident_dashboard",
        "admin_reports",
    ),
    "academic_month_boundary": (
        "parsed_data",
        "academic_month_boundaries",
        "resident_dashboard",
        "admin_reports",
    ),
}


def _scope_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        return None
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        parts = sorted({str(item).strip() for item in value if str(item).strip()})
        return ",".join(parts) if parts else None
    return str(value)


def _normalise_scope(scope: Mapping[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in scope.items():
        token = _scope_value(value)
        if token is not None:
            normalized[key] = token
    return normalized


def _unique_domains(domains: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for domain in domains:
        if domain and domain not in seen:
            seen.add(domain)
            ordered.append(domain)
    return tuple(ordered)


def _prefixes(domain: str, scope: Mapping[str, str]) -> tuple[str, ...]:
    prefixes = {domain}
    for key, value in scope.items():
        prefixes.add(f"{domain}|{key}={value}")
    if scope:
        scope_segment = "|".join(f"{key}={scope[key]}" for key in sorted(scope))
        prefixes.add(f"{domain}|{scope_segment}")
    return tuple(sorted(prefixes))


def invalidate_cache(domains: Iterable[str], **scope: Any) -> list[CacheInvalidationCall]:
    normalized_scope = _normalise_scope(scope)
    calls: list[CacheInvalidationCall] = []
    for domain in _unique_domains(domains):
        for prefix in _prefixes(domain, normalized_scope):
            cache.invalidate_prefix(prefix)
        calls.append(CacheInvalidationCall(domain=domain, scope=dict(normalized_scope)))
    return calls


def invalidate_after_upload(
    *,
    upload_type: str,
    upload_log_id: Any = None,
    reporting_period_id: Any = None,
    programme_code: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        _UPLOAD_DOMAINS_BY_TYPE.get(upload_type, ("upload_logs", "upload_warnings")),
        upload_type=upload_type,
        upload_log_id=upload_log_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )


def invalidate_after_warning_derivation(
    *,
    upload_log_id: Any = None,
    reporting_period_id: Any = None,
    programme_code: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        ("upload_warnings", "admin_reports"),
        upload_log_id=upload_log_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )


def invalidate_after_warning_action(
    *,
    warning_issue_id: Any,
    reporting_period_id: Any = None,
    programme_code: Any = None,
    mcr: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        ("upload_warnings", "admin_reports"),
        warning_issue_id=warning_issue_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        mcr=mcr,
    )


def invalidate_after_source_cell_apply(
    *,
    resident_id: Any,
    reporting_period_id: Any,
    programme_code: Any = None,
    warning_issue_id: Any = None,
    upload_warning_id: Any = None,
    mcr: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        (
            "parsed_data",
            "resident_postings",
            "upload_warnings",
            "resident_events",
            "resident_dashboard",
            "admin_reports",
        ),
        resident_id=resident_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        warning_issue_id=warning_issue_id,
        upload_warning_id=upload_warning_id,
        mcr=mcr,
    )


def invalidate_after_live_data_correction(
    *,
    entity_type: str,
    entity_id: Any = None,
    resident_id: Any = None,
    reporting_period_id: Any = None,
    programme_code: Any = None,
    posting_code: Any = None,
    mcr: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        _LIVE_DATA_DOMAINS_BY_ENTITY.get(entity_type, ("parsed_data", "admin_reports")),
        entity_type=entity_type,
        entity_id=entity_id,
        resident_id=resident_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        mcr=mcr,
    )


def invalidate_after_config_change(
    *,
    entity_type: str,
    entity_id: Any = None,
    snapshot: Mapping[str, Any] | None = None,
    programme_scope: Iterable[str] | None = None,
) -> list[CacheInvalidationCall]:
    snapshot = snapshot or {}
    reporting_period_id = snapshot.get("id") if entity_type == "reporting_period" else snapshot.get("reporting_period_id")
    programme_code = snapshot.get("code") if entity_type == "programme" else snapshot.get("programme_code")
    return invalidate_cache(
        _CONFIG_DOMAINS_BY_ENTITY.get(entity_type, ("config", "admin_reports")),
        entity_type=entity_type,
        entity_id=entity_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        programme_scope=programme_scope,
        posting_code=snapshot.get("posting_code"),
    )


def invalidate_after_secretary_event_mutation(
    *,
    posting_code: Any,
    reporting_period_id: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        ("secretary_events", "resident_events", "resident_dashboard", "admin_reports"),
        posting_code=posting_code,
        reporting_period_id=reporting_period_id,
    )


def invalidate_after_teaching_name_pool_change(
    *,
    teaching_name_id: Any,
    reporting_period_id: Any,
    programme_code: Any,
    event_references_cleared: bool = False,
) -> list[CacheInvalidationCall]:
    domains: tuple[str, ...] = (
        "teaching_name_pool",
        "teaching_name_mappings",
        "teaching_name_options",
        "programme_teaching_events",
    )
    if event_references_cleared:
        domains += (
            "teaching_events",
            "secretary_events",
            "resident_events",
            "resident_dashboard",
            "admin_reports",
        )
    return invalidate_cache(
        domains,
        teaching_name_id=teaching_name_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )


def invalidate_after_admin_event_force_delete(
    *,
    event_id: Any,
    posting_code: Any,
    programme_code: Any = None,
) -> list[CacheInvalidationCall]:
    return invalidate_cache(
        (
            "teaching_events",
            "secretary_events",
            "programme_teaching_events",
            "admin_secretary_events",
            "resident_events",
            "resident_attendance",
            "external_attendance",
            "resident_dashboard",
            "admin_reports",
        ),
        event_id=event_id,
        posting_code=posting_code,
        programme_code=programme_code,
    )


def invalidate_after_resident_attendance_mutation(
    *,
    resident_id: Any = None,
    external_resident_id: Any = None,
    posting_codes: Iterable[str] = (),
    programme_code: Any = None,
    reporting_period_id: Any = None,
    include_secretary_events: bool = False,
) -> list[CacheInvalidationCall]:
    domains = ["resident_events", "resident_attendance", "resident_dashboard", "admin_reports"]
    if include_secretary_events:
        domains.append("secretary_events")
    return invalidate_cache(
        domains,
        resident_id=resident_id,
        external_resident_id=external_resident_id,
        posting_code=posting_codes,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
    )
