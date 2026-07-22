from __future__ import annotations

from datetime import date, datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, AsyncIterator, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.dependencies.auth import is_master_admin
from app.dependencies.persistent_rate_limit import enforce_upload_persistent_rate_limit
from app.dependencies.staff_actor import (
    STAFF_ACTOR_FALLBACK_NAME,
    StaffActorContext,
    require_staff_actor,
)
from app.errors import ApiError, ErrorCode, UploadValidationApiError
from app.middleware.auth_stub import AuthIdentity
from app.schemas import (
    AcademicMonthBoundaryResponse,
    AdminExternalAttendanceDetailResponse,
    AdminExternalAttendanceListResponse,
    AdminResidentAttendanceDetailResponse,
    AdminResidentAttendanceOverviewResponse,
    AdminResidentSubmissionDetailResponse,
    AdminResidentSubmissionListResponse,
    AdminSecretaryEventDetailResponse,
    AdminSecretaryEventForceDeleteRequest,
    AdminSecretaryEventForceDeleteResponse,
    AdminSecretaryEventListResponse,
    AdminLogActorRole,
    AdminLogDetailResponse,
    AdminLogListResponse,
    AdminLogType,
    ConfigMutationDeleteResponse,
    FormF1RecordResponse,
    GlobalSessionTypeCreateRequest,
    GlobalSessionTypeMutationResponse,
    GlobalSessionTypeResponse,
    GlobalSessionTypeUpdateRequest,
    LoaTypeCreateRequest,
    LoaTypeMutationResponse,
    LoaTypeResponse,
    LoaTypeUpdateRequest,
    MultiPostingRuleMutationRequest,
    MultiPostingRuleMutationResponseModel,
    MultiPostingRuleResponse,
    ParsedAcademicMonthBoundaryListResponse,
    ParsedDataCorrectionHistoryListResponse,
    ParsedDataCorrectionRequest,
    ParsedDataCorrectionResponse,
    ParsedDataSourceCellReplaceResponse,
    ParsedFormF1RecordListResponse,
    ParsedPublicHolidayListResponse,
    ParsedResidentListResponse,
    ParsedResidentPostingListResponse,
    ParsedTeachingNameCatalogueListResponse,
    ParsedTeachingTargetListResponse,
    ResidentPostingSourceCellReplaceRequest,
    PostingGroupMutationRequest,
    PostingGroupMutationResponse,
    PostingGroupResponse,
    PostingCodeResponse,
    ProgrammeTeachingEventCreateRequest,
    ProgrammeTeachingEventDuplicateRequest,
    ProgrammeTeachingEventUpdateRequest,
    ProgrammeUpdateRequest,
    ProgrammeMutationResponse,
    ProgrammeResponse,
    RDBSourceCellWarningApplyRequest,
    RDBSourceCellWarningApplyResponse,
    RDBSourceCellWarningPreviewRequest,
    RDBSourceCellWarningPreviewResponse,
    ResidentPostingResponse,
    ResidentResponse,
    PublicHolidayUpsertRequest,
    PublicHolidayMutationResponse,
    PublicHolidayResponse,
    ReportingPeriodCreateRequest,
    ReportingPeriodMutationResponse,
    ReportingPeriodResponse,
    ReportingPeriodUpdateRequest,
    SessionTypeResponse,
    StaffAccountCreateRequest,
    StaffAccountListResponse,
    StaffAccountResetPasswordRequest,
    StaffAccountResponse,
    StaffAccountUpdateRequest,
    TeachingNameCatalogueResponse,
    TeachingTargetResponse,
    UploadLogDetailResponse,
    UploadLogListResponse,
    UploadWarningActionRequest,
    UploadWarningIssueActionResponse,
    UploadWarningIssueDetailResponse,
    UploadWarningResponse,
    WeekendExceptionMutationRequest,
    WeekendExceptionMutationResponse,
    WeekendExceptionResponse,
)
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.services import (
    admin_config,
    admin_external_attendance,
    admin_resident_attendance,
    admin_resident_submissions,
    admin_secretary_events,
    cache_invalidation,
    data_revalidation_service,
    parsed_data,
    programme_teaching_events,
    staff_accounts,
)
from app.services.admin_logs_service import (
    get_admin_log as get_admin_log_read_model,
    list_admin_logs as list_admin_logs_read_model,
)
from app.services.audit import write_audit_log
from app.services.upload_logs import (
    error_count,
    get_upload_log as get_upload_log_read_model,
    list_upload_logs as list_upload_logs_read_model,
    summary_counts,
    warning_count,
)
from app.services.upload_warnings import list_upload_warnings
from app.services.warning_issues import (
    DurableWarningStoreUnavailable,
    derive_upload_warnings_from_summary,
    get_warning_issue_detail,
    list_warning_issues,
    update_warning_issue_status,
)
from app.services.parser_common import (
    ParserResult,
    UploadValidationError,
    normalise_scope_values,
    validate_upload_payload,
    write_upload_log,
)
from app.services.reporting_period_status import REPORTING_PERIOD_ACTIVE
from app.services.formf1_parser import parse_formf1_upload
from app.services.public_holiday_parser import parse_public_holiday_upload
from app.services.ttf_parser import TTFUploadLockError, parse_ttf_upload


router = APIRouter(prefix="/admin", tags=["admin"])
RDB_RAW_MULTI_POSTING_FRAGMENT_RESPONSE_LIMIT = 50


try:
    from app.database import get_db_session
except Exception:

    async def get_db_session() -> AsyncIterator[AsyncSession | None]:
        yield None


@dataclass(slots=True)
class AdminContext:
    user_id: UUID
    programme_scope: set[str]
    is_master_admin: bool
    current_staff_actor_name: str | None = None


def _admin_actor_context(admin_context: AdminContext) -> StaffActorContext:
    scope_metadata: dict[str, Any] = {}
    if admin_context.programme_scope:
        scope_metadata["programme_scope"] = sorted(admin_context.programme_scope)
    if admin_context.is_master_admin:
        scope_metadata["admin_level"] = "master"
    return StaffActorContext(
        actor_user_id=admin_context.user_id,
        actor_role="admin",
        actor_name=(
            admin_context.current_staff_actor_name.strip()
            if admin_context.current_staff_actor_name
            and admin_context.current_staff_actor_name.strip()
            else STAFF_ACTOR_FALLBACK_NAME
        ),
        actor_programme=",".join(sorted(admin_context.programme_scope)) or None,
        actor_admin_level="master" if admin_context.is_master_admin else None,
        raw_scope_metadata=scope_metadata,
    )


def _admin_context_from_identity(identity: AuthIdentity) -> AdminContext:
    if identity.role != "admin":
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    try:
        user_id = UUID(identity.subject_id)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc
    return AdminContext(
        user_id=user_id,
        programme_scope=normalise_scope_values(identity.programme_scope),
        is_master_admin=is_master_admin(identity),
        current_staff_actor_name=identity.current_staff_actor_name,
    )


def _stub_header_fallback_allowed(settings: Settings) -> bool:
    return settings.environment != "production" and settings.auth_mode in {"stub", "demo"}


async def require_admin_context(
    request: Request,
    settings: Settings = Depends(get_settings),
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_programme: Annotated[str | None, Header(alias="X-User-Programme")] = None,
    x_admin_level: Annotated[str | None, Header(alias="X-Admin-Level")] = None,
) -> AdminContext:
    identity = getattr(request.state, "identity", None)
    if isinstance(identity, AuthIdentity):
        return _admin_context_from_identity(identity)

    if not _stub_header_fallback_allowed(settings):
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )

    if x_user_role != "admin":
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if not x_user_id:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc

    admin_level = (x_admin_level or "").strip().lower()
    return AdminContext(
        user_id=user_id,
        programme_scope=normalise_scope_values(x_user_programme),
        is_master_admin=admin_level in {"master", "master_admin"},
    )


def _require_master_admin(admin_context: AdminContext) -> None:
    if not admin_context.is_master_admin:
        raise ApiError(
            status_code=403,
            detail="Forbidden - master admin access required",
            error_code=ErrorCode.FORBIDDEN.value,
        )


async def require_master_admin_context(
    admin_context: AdminContext = Depends(require_admin_context),
) -> AdminContext:
    _require_master_admin(admin_context)
    return admin_context


def _require_reporting_period_read_access(admin_context: AdminContext) -> None:
    if admin_context.is_master_admin:
        return
    if not admin_context.programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _global_config_scope(admin_context: AdminContext) -> set[str]:
    return admin_context.programme_scope or {"__master_admin__"}


def _require_programme_in_scope(admin_context: AdminContext, programme_code: str) -> None:
    if admin_context.is_master_admin:
        return
    normalized_scope = {
        value
        for raw_value in admin_context.programme_scope
        if (value := str(raw_value).strip().upper())
    }
    if not normalized_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if programme_code.strip().upper() not in normalized_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _require_programme_pc_context(admin_context: AdminContext) -> None:
    if admin_context.is_master_admin:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme PC access required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if not admin_context.programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _require_programme_pc_scope(admin_context: AdminContext, programme_code: str) -> None:
    _require_programme_pc_context(admin_context)
    if programme_code not in admin_context.programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _format_rdb_response(result: ParserResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    raw_fragments = metadata.get("raw_multi_posting_fragments", [])
    if not isinstance(raw_fragments, list):
        raw_fragments = []
    raw_fragment_count = metadata.get(
        "raw_multi_posting_fragment_count", len(raw_fragments)
    )
    if not isinstance(raw_fragment_count, int):
        raw_fragment_count = len(raw_fragments)
    response_raw_fragments = raw_fragments[
        :RDB_RAW_MULTI_POSTING_FRAGMENT_RESPONSE_LIMIT
    ]
    return {
        "residents_created": metadata.get("residents_created", result.created_count),
        "residents_updated": metadata.get("residents_updated", result.updated_count),
        "postings_created": metadata.get("postings_created", 0),
        "posting_codes_added": metadata.get("posting_codes_added", []),
        "loa_records": metadata.get("loa_records", 0),
        "unknown_loa_types": metadata.get("unknown_loa_types", []),
        "employed_residents_flagged": metadata.get("employed_residents_flagged", 0),
        "multi_posting_rules_applied": metadata.get("multi_posting_rules_applied", 0),
        "raw_multi_posting_fragment_count": raw_fragment_count,
        "raw_multi_posting_fragments": response_raw_fragments,
        "raw_multi_posting_fragments_truncated": raw_fragment_count
        > len(response_raw_fragments),
        "rows_skipped": metadata.get("rows_skipped", 0),
        "skip_reasons": metadata.get("skip_reasons", []),
        "warnings": result.warnings,
        "errors": result.errors,
    }


def _format_ttf_response(result: ParserResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    return {
        "targets_created": metadata.get("targets_created", result.created_count),
        "session_types_upserted": metadata.get("session_types_upserted", result.updated_count),
        "posting_codes_added": metadata.get("posting_codes_added", []),
        "catalogue_rows_seeded": metadata.get("catalogue_rows_seeded", 0),
        "rows_exploded": metadata.get("rows_exploded", 0),
        "warnings": result.warnings,
        "errors": result.errors,
    }


def _format_formf1_response(result: ParserResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    warning_messages = [
        warning.get("message", "Upload warning")
        if isinstance(warning, dict)
        else warning
        for warning in result.warnings
    ]
    return {
        "records_created": metadata.get("records_created", result.created_count),
        "records_updated": metadata.get("records_updated", result.updated_count),
        "mcr_not_found_warnings": metadata.get("mcr_not_found_warnings", []),
        "skipped_mcr_warnings": metadata.get("skipped_mcr_warnings", []),
        "duplicate_mcr_errors": metadata.get("duplicate_mcr_errors", []),
        "month_labels_parsed": metadata.get("month_labels_parsed", []),
        "active_count": metadata.get("active_count", 0),
        "inactive_count": metadata.get("inactive_count", 0),
        "promotion_dates_parsed": metadata.get("promotion_dates_parsed", 0),
        "promotion_date_warnings": metadata.get("promotion_date_warnings", []),
        "warnings": warning_messages,
        "errors": result.errors,
    }


def _format_public_holiday_response(result: ParserResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    return {
        "public_holidays_created": metadata.get("public_holidays_created", 0),
        "academic_month_boundaries_created": metadata.get(
            "academic_month_boundaries_created", 0
        ),
        "ay_categories_parsed": metadata.get("ay_categories_parsed", []),
        "academic_year_label": metadata.get("academic_year_label"),
        "ignored_sheets": metadata.get("ignored_sheets", []),
        "warnings": result.warnings,
        "errors": result.errors,
    }


async def _require_active_upload_reporting_period(
    db: AsyncSession | None,
    reporting_period_id: UUID,
) -> None:
    if db is None:
        return
    result = await db.execute(
        text(
            """
            /* upload:reporting_period_status */
            SELECT status
            FROM reporting_periods
            WHERE id = :reporting_period_id
            """
        ),
        {"reporting_period_id": str(reporting_period_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return
    if str(row.get("status") or "").strip().lower() == REPORTING_PERIOD_ACTIVE:
        return
    raise ApiError(
        status_code=422,
        detail="Selected reporting period is inactive. Activate the reporting period before uploading.",
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


_METADATA_INTERNAL_KEYS = {"exception", "traceback", "stack", "stacktrace"}


def _sanitise_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(metadata or {})
    for key in _METADATA_INTERNAL_KEYS:
        payload.pop(key, None)
    return payload


def _normalise_error_messages(
    errors: list[str | dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    error_messages: list[str] = []
    structured_errors: list[dict[str, Any]] = []
    for item in errors:
        if isinstance(item, str):
            error_messages.append(item)
            continue

        structured_errors.append(item)
        message = item.get("message")
        if isinstance(message, str) and message.strip():
            error_messages.append(message.strip())
        else:
            error_messages.append("Validation error")

    return error_messages, structured_errors


def _raise_upload_validation_error_if_needed(
    *,
    upload_label: str,
    parser_result: ParserResult,
) -> None:
    if not parser_result.errors:
        return

    safe_metadata = _sanitise_metadata(parser_result.metadata)
    error_messages, structured_errors = _normalise_error_messages(parser_result.errors)
    if structured_errors:
        safe_metadata.setdefault("parser_errors", structured_errors)

    if any(key in (parser_result.metadata or {}) for key in _METADATA_INTERNAL_KEYS):
        raise ApiError(
            status_code=500,
            detail="Internal server error",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )

    raise UploadValidationApiError(
        detail=f"{upload_label} validation failed",
        errors=error_messages,
        warnings=parser_result.warnings,
        metadata=safe_metadata,
    )


_UPLOAD_AUDIT_ACTIONS = {
    "rdb": "admin.upload.rdb",
    "ttf": "admin.upload.ttf",
    "form_f1": "admin.upload.form_f1",
    "public_holidays": "admin.upload.public_holidays",
}

_CONFIG_AUDIT_ACTIONS = {
    ("reporting_period", "create"): "admin.config.reporting_period.create",
    ("reporting_period", "update"): "admin.config.reporting_period.update",
    ("reporting_period", "delete"): "admin.config.reporting_period.delete",
    ("reporting_period", "activate"): "admin.config.reporting_period.activate",
    ("reporting_period", "deactivate"): "admin.config.reporting_period.deactivate",
    ("public_holiday", "create"): "admin.config.public_holiday.create",
    ("public_holiday", "update"): "admin.config.public_holiday.update",
    ("public_holiday", "delete"): "admin.config.public_holiday.delete",
    ("programme", "update"): "admin.config.programme.update",
    ("loa_type", "create"): "admin.config.loa_type.create",
    ("loa_type", "update"): "admin.config.loa_type.update",
    ("loa_type", "delete"): "admin.config.loa_type.delete",
    ("multi_posting_rule", "create"): "admin.config.multi_posting_rule.create",
    ("multi_posting_rule", "update"): "admin.config.multi_posting_rule.update",
    ("multi_posting_rule", "delete"): "admin.config.multi_posting_rule.delete",
    ("posting_group", "create"): "admin.config.posting_group.create",
    ("posting_group", "update"): "admin.config.posting_group.update",
    ("posting_group", "delete"): "admin.config.posting_group.delete",
    ("weekend_exception", "create"): "admin.config.weekend_exception.create",
    ("weekend_exception", "update"): "admin.config.weekend_exception.update",
    ("weekend_exception", "delete"): "admin.config.weekend_exception.delete",
    ("global_session_type", "create"): "admin.config.global_session_type.create",
    ("global_session_type", "update"): "admin.config.global_session_type.update",
    ("global_session_type", "delete"): "admin.config.global_session_type.delete",
}

_CONFIG_AUDIT_SNAPSHOT_SQL = {
    "reporting_period": """
        /* audit_snapshot:reporting_period */
        SELECT
            id,
            label,
            start_date,
            end_date,
            status,
            activate_on,
            deactivate_on,
            created_at,
            updated_at
        FROM reporting_periods
        WHERE id = :id
    """,
    "public_holiday": """
        /* audit_snapshot:public_holiday */
        SELECT id, holiday_date, name, day_of_week, year, created_at, updated_at
        FROM public_holidays
        WHERE id = :id
    """,
    "programme": """
        /* audit_snapshot:programme */
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
        WHERE code = :code
    """,
    "loa_type": """
        /* audit_snapshot:loa_type */
        SELECT id, code, description, created_at, updated_at
        FROM loa_types
        WHERE id = :id
    """,
    "multi_posting_rule": """
        /* audit_snapshot:multi_posting_rule */
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
        WHERE id = :id
    """,
    "posting_group": """
        /* audit_snapshot:posting_group */
        SELECT id, group_code, posting_code, programme_code, created_at, updated_at
        FROM posting_groups
        WHERE id = :id
    """,
    "weekend_exception": """
        /* audit_snapshot:weekend_exception */
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
        WHERE id = :id
    """,
    "global_session_type": """
        /* audit_snapshot:global_session_type */
        SELECT id, name, duration_hours, is_active, created_at, updated_at
        FROM global_session_types
        WHERE id = :id
    """,
}


def _upload_log_audit_payload(
    *,
    upload_log: dict[str, Any],
    parser_result: ParserResult,
    original_filename: str,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = parser_result.to_summary()
    summary["original_filename"] = original_filename
    counts = summary_counts(summary)
    warnings = warning_count(summary)
    errors = error_count(summary)
    common = {
        "upload_type": parser_result.upload_type,
        "original_filename": original_filename,
        "reporting_period_id": str(reporting_period_id) if reporting_period_id else None,
        "programme_code": programme_code,
        "status": parser_result.status,
        "warning_count": warnings,
        "error_count": errors,
        "summary_counts": counts,
    }
    after = {
        "id": str(upload_log["id"]),
        "upload_type": parser_result.upload_type,
        "uploaded_by": str(upload_log["uploaded_by"]) if upload_log.get("uploaded_by") else None,
        "reporting_period_id": common["reporting_period_id"],
        "programme_code": programme_code,
        "status": parser_result.status,
        "warning_count": warnings,
        "error_count": errors,
        "summary_counts": counts,
    }
    return after, common


async def _write_upload_log_and_audit(
    *,
    db: AsyncSession | None,
    parser_result: ParserResult,
    original_filename: str,
    uploaded_by: UUID,
    actor: StaffActorContext,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
) -> None:
    if db is None:
        return

    upload_log = await write_upload_log(
        db,
        upload_type=parser_result.upload_type,
        original_filename=original_filename,
        status=parser_result.status,
        summary=parser_result.to_summary(),
        uploaded_by=uploaded_by,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )
    try:
        await derive_upload_warnings_from_summary(
            db,
            upload_log,
            parser_result.to_summary(),
            actor_id=uploaded_by,
        )
    except DurableWarningStoreUnavailable:
        pass
    after, metadata = _upload_log_audit_payload(
        upload_log=upload_log,
        parser_result=parser_result,
        original_filename=original_filename,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )
    await write_audit_log(
        db,
        actor=actor,
        action=_UPLOAD_AUDIT_ACTIONS[parser_result.upload_type],
        entity_type="upload_log",
        entity_id=upload_log["id"],
        before=None,
        after=after,
        metadata=metadata,
    )
    await db.commit()
    cache_invalidation.invalidate_after_upload(
        upload_type=parser_result.upload_type,
        upload_log_id=upload_log.get("id"),
        reporting_period_id=reporting_period_id or upload_log.get("reporting_period_id"),
        programme_code=programme_code or upload_log.get("programme_code"),
    )


def _compact_snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: value for key, value in dict(row).items()}


_CONFIG_REVALIDATION_ENTITY = {
    "reporting_period": DataRevalidationChangedEntity.REPORTING_PERIOD,
    "public_holiday": DataRevalidationChangedEntity.PUBLIC_HOLIDAY,
    "programme": DataRevalidationChangedEntity.PROGRAMME,
    "loa_type": DataRevalidationChangedEntity.LOA_TYPE,
    "multi_posting_rule": DataRevalidationChangedEntity.MULTI_POSTING_RULE,
    "posting_group": DataRevalidationChangedEntity.POSTING_GROUP,
    "weekend_exception": DataRevalidationChangedEntity.WEEKEND_EXCEPTION,
    "global_session_type": DataRevalidationChangedEntity.GLOBAL_SESSION_TYPE,
}

_CONFIG_REVALIDATION_ACTION = {
    "create": DataRevalidationAction.CREATE,
    "update": DataRevalidationAction.UPDATE,
    "delete": DataRevalidationAction.DELETE,
    "activate": DataRevalidationAction.ACTIVATE,
    "deactivate": DataRevalidationAction.DEACTIVATE,
}

_CONFIG_SOURCE_METADATA_FIELDS = {
    "reporting_period": (
        "label",
        "start_date",
        "end_date",
        "status",
        "activate_on",
        "deactivate_on",
    ),
    "public_holiday": ("holiday_date", "name", "day_of_week", "year"),
    "programme": ("code", "r_year_required", "is_subspecialty", "rdb_alias"),
    "loa_type": ("code", "description"),
    "multi_posting_rule": (
        "programme_code",
        "rule_type",
        "posting_code_1",
        "posting_code_2",
        "combined_label",
        "main_posting_code",
        "exclusion_code",
    ),
    "posting_group": ("group_code", "posting_code", "programme_code"),
    "weekend_exception": (
        "programme_code",
        "posting_code",
        "day_type",
        "start_time_min",
        "end_time_max",
        "session_type_id",
        "session_name_pattern",
        "mutates_to_session_type_id",
        "adjusted_duration_hours",
    ),
    "global_session_type": ("name", "duration_hours", "is_active"),
}


def _config_changed_fields(payload: Any) -> list[str]:
    return sorted(getattr(payload, "model_fields_set", set()))


def _config_revalidation_scope(
    *,
    entity_type: str,
    snapshot: dict[str, Any] | None,
) -> DataRevalidationScope:
    if entity_type == "reporting_period":
        return DataRevalidationScope.REPORTING_PERIOD
    if entity_type in {"public_holiday", "loa_type", "global_session_type"}:
        return DataRevalidationScope.GLOBAL
    if entity_type in {"programme", "multi_posting_rule", "posting_group"}:
        return DataRevalidationScope.PROGRAMME
    if entity_type == "weekend_exception":
        snapshot = snapshot or {}
        if snapshot.get("programme_code") is not None:
            return DataRevalidationScope.PROGRAMME
        if snapshot.get("posting_code") is not None:
            return DataRevalidationScope.POSTING
        return DataRevalidationScope.GLOBAL
    return DataRevalidationScope.UNKNOWN


def _config_revalidation_programme_code(
    *,
    entity_type: str,
    snapshot: dict[str, Any] | None,
) -> str | None:
    snapshot = snapshot or {}
    if entity_type == "programme" and snapshot.get("code") is not None:
        return str(snapshot["code"])
    if snapshot.get("programme_code") is not None:
        return str(snapshot["programme_code"])
    return None


def _config_revalidation_source_metadata(
    *,
    entity_type: str,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = snapshot or {}
    return {
        field: snapshot[field]
        for field in _CONFIG_SOURCE_METADATA_FIELDS.get(entity_type, ())
        if snapshot.get(field) is not None
    }


async def _revalidate_config_mutation(
    db: AsyncSession,
    *,
    admin_context: AdminContext,
    actor: StaffActorContext,
    entity_type: str,
    mutation: Literal["create", "update", "delete", "activate", "deactivate"],
    entity_id: UUID | str | None,
    snapshot: dict[str, Any] | None,
    changed_fields: list[str],
    previous_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_metadata = _config_revalidation_source_metadata(
        entity_type=entity_type,
        snapshot=snapshot,
    )
    previous_source_metadata = _config_revalidation_source_metadata(
        entity_type=entity_type,
        snapshot=previous_snapshot,
    )
    if previous_source_metadata:
        source_metadata["previous_source_metadata"] = previous_source_metadata
    summary = await data_revalidation_service.revalidate_after_config_change(
        context=DataRevalidationContext(
            trigger_source=(
                DataRevalidationTriggerSource.ADMIN_CONFIG_CHANGE
                if admin_context.is_master_admin
                else DataRevalidationTriggerSource.PC_CONFIG_CHANGE
            ),
            changed_entity=_CONFIG_REVALIDATION_ENTITY[entity_type],
            action=_CONFIG_REVALIDATION_ACTION[mutation],
            scope=_config_revalidation_scope(
                entity_type=entity_type,
                snapshot=snapshot,
            ),
            entity_id=str(entity_id) if entity_id is not None else None,
            programme_code=_config_revalidation_programme_code(
                entity_type=entity_type,
                snapshot=snapshot,
            ),
            reporting_period_id=(
                str(snapshot["id"])
                if entity_type == "reporting_period" and snapshot and snapshot.get("id") is not None
                else None
            ),
            changed_fields=changed_fields,
            source_metadata=source_metadata,
            actor_user_id=str(actor.actor_user_id) if actor.actor_user_id else None,
            actor_role=actor.actor_role,
            reason=f"Admin Config {entity_type} {mutation}",
        ),
        db_session=db,
    )
    cache_invalidation.invalidate_after_config_change(
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot=snapshot,
        programme_scope=admin_context.programme_scope,
    )
    return summary.model_dump(mode="json")


def _with_data_revalidation(
    row: dict[str, Any],
    data_revalidation: dict[str, Any],
) -> dict[str, Any]:
    return {**row, "data_revalidation": data_revalidation}


def _delete_config_response(
    *,
    entity_type: str,
    entity_id: UUID | str,
    data_revalidation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "deleted": True,
        "data_revalidation": data_revalidation,
    }


async def _read_config_audit_snapshot(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID | str,
) -> dict[str, Any] | None:
    sql = _CONFIG_AUDIT_SNAPSHOT_SQL[entity_type]
    params = (
        {"code": str(entity_id)}
        if entity_type == "programme"
        else {"id": str(entity_id)}
    )
    result = await db.execute(text(sql), params)
    return _compact_snapshot(result.mappings().one_or_none())


def _config_audit_metadata(
    *,
    entity_type: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    data_revalidation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = after or before or {}
    metadata: dict[str, Any] = {
        "route_context": "admin_config_crud",
        "config_entity": entity_type,
        "mutation": action,
        "cache_invalidation_target": "admin_config",
    }
    if entity_type == "reporting_period" and snapshot.get("id") is not None:
        metadata["reporting_period_id"] = str(snapshot["id"])
    if snapshot.get("programme_code") is not None:
        metadata["programme_code"] = snapshot["programme_code"]
    if entity_type == "programme" and snapshot.get("code") is not None:
        metadata["programme_code"] = snapshot["code"]
    if snapshot.get("rule_type") is not None:
        metadata["rule_type"] = snapshot["rule_type"]
    if snapshot.get("posting_code") is not None:
        metadata["posting_code"] = snapshot["posting_code"]
    if data_revalidation is not None:
        metadata["data_revalidation"] = data_revalidation
    return metadata


async def _write_config_audit(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    entity_type: str,
    mutation: Literal["create", "update", "delete", "activate", "deactivate"],
    entity_id: UUID | str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    data_revalidation: dict[str, Any] | None = None,
) -> None:
    await write_audit_log(
        db,
        actor=actor,
        action=_CONFIG_AUDIT_ACTIONS[(entity_type, mutation)],
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        metadata=_config_audit_metadata(
            entity_type=entity_type,
            action=mutation,
            before=before,
            after=after,
            data_revalidation=data_revalidation,
        ),
    )
    await db.commit()


@router.get("/staff-accounts", response_model=StaffAccountListResponse)
async def list_staff_accounts(
    db: AsyncSession = Depends(get_db_session),
    admin_context: AdminContext = Depends(require_admin_context),
) -> dict:
    _require_master_admin(admin_context)
    return await staff_accounts.list_staff_accounts(db)


@router.post("/staff-accounts", response_model=StaffAccountResponse)
async def create_staff_account(
    payload: StaffAccountCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    admin_context: AdminContext = Depends(require_admin_context),
    actor: StaffActorContext = Depends(require_staff_actor),
    settings: Settings = Depends(get_settings),
) -> dict:
    _require_master_admin(admin_context)
    return await staff_accounts.create_staff_account(
        db,
        payload=payload,
        actor=actor,
        settings=settings,
    )


@router.patch("/staff-accounts/{user_id}", response_model=StaffAccountResponse)
async def update_staff_account(
    user_id: UUID,
    payload: StaffAccountUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    admin_context: AdminContext = Depends(require_admin_context),
    actor: StaffActorContext = Depends(require_staff_actor),
) -> dict:
    _require_master_admin(admin_context)
    return await staff_accounts.update_staff_account(
        db,
        user_id=user_id,
        payload=payload,
        actor=actor,
    )


@router.post("/staff-accounts/{user_id}/reset-password", response_model=StaffAccountResponse)
async def reset_staff_account_password(
    user_id: UUID,
    payload: StaffAccountResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    admin_context: AdminContext = Depends(require_admin_context),
    actor: StaffActorContext = Depends(require_staff_actor),
    settings: Settings = Depends(get_settings),
) -> dict:
    _require_master_admin(admin_context)
    return await staff_accounts.reset_staff_account_password(
        db,
        user_id=user_id,
        payload=payload,
        actor=actor,
        settings=settings,
    )


@router.post("/upload/rdb")
async def upload_rdb(
    file: UploadFile = File(...),
    reporting_period_id: UUID = Form(...),
    admin_context: AdminContext = Depends(require_master_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="rdb",
            filename=file.filename,
            file_bytes=file_bytes,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

    await _require_active_upload_reporting_period(db, reporting_period_id)

    await enforce_upload_persistent_rate_limit(
        db,
        settings=settings,
        user_id=admin_context.user_id,
        upload_type="rdb",
    )

    corrected_rows_warning = None
    if db is not None:
        corrected_rows_warning = await parsed_data.resident_posting_corrections_reupload_warning(
            db,
            reporting_period_id=reporting_period_id,
        )

    from app.services.rdb_parser import parse_rdb_upload

    parser_result = await parse_rdb_upload(
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
        db_session=db,
    )
    if corrected_rows_warning is not None:
        parser_result.warnings.append(corrected_rows_warning)

    await _write_upload_log_and_audit(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        actor=staff_actor,
        reporting_period_id=reporting_period_id,
    )
    _raise_upload_validation_error_if_needed(
        upload_label="RDB",
        parser_result=parser_result,
    )

    return _format_rdb_response(parser_result)


@router.post("/upload/ttf")
async def upload_ttf(
    file: UploadFile = File(...),
    reporting_period_id: UUID = Form(...),
    programme_code: str = Form(...),
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    programme_code = programme_code.strip().upper()
    _require_programme_in_scope(admin_context, programme_code)

    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="ttf",
            filename=file.filename,
            file_bytes=file_bytes,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

    await _require_active_upload_reporting_period(db, reporting_period_id)

    await enforce_upload_persistent_rate_limit(
        db,
        settings=settings,
        user_id=admin_context.user_id,
        upload_type="ttf",
        programme_code=programme_code,
    )

    try:
        parser_result = await parse_ttf_upload(
            file_bytes=validated.file_bytes,
            original_filename=validated.original_filename,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
            db_session=db,
        )
    except TTFUploadLockError as exc:
        raise ApiError(
            status_code=409,
            detail="Another TTF upload for this scope is in progress",
            error_code=ErrorCode.CONFLICT.value,
            errors=[str(exc)],
        ) from exc

    await _write_upload_log_and_audit(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        actor=staff_actor,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )
    _raise_upload_validation_error_if_needed(
        upload_label="TTF",
        parser_result=parser_result,
    )

    return _format_ttf_response(parser_result)


@router.post("/upload/form-f1")
async def upload_formf1(
    file: UploadFile = File(...),
    reporting_period_id: UUID = Form(...),
    admin_context: AdminContext = Depends(require_master_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="form_f1",
            filename=file.filename,
            file_bytes=file_bytes,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

    await _require_active_upload_reporting_period(db, reporting_period_id)

    await enforce_upload_persistent_rate_limit(
        db,
        settings=settings,
        user_id=admin_context.user_id,
        upload_type="form_f1",
    )

    parser_result = await parse_formf1_upload(
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
        db_session=db,
    )

    await _write_upload_log_and_audit(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        actor=staff_actor,
        reporting_period_id=reporting_period_id,
    )
    _raise_upload_validation_error_if_needed(
        upload_label="FormF1",
        parser_result=parser_result,
    )
    return _format_formf1_response(parser_result)


@router.post("/upload/public-holidays")
async def upload_public_holidays(
    file: UploadFile = File(...),
    admin_context: AdminContext = Depends(require_master_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="public_holidays",
            filename=file.filename,
            file_bytes=file_bytes,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

    parser_result = await parse_public_holiday_upload(
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        db_session=db,
    )

    await _write_upload_log_and_audit(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        actor=staff_actor,
    )
    _raise_upload_validation_error_if_needed(
        upload_label="Public holiday upload",
        parser_result=parser_result,
    )

    return _format_public_holiday_response(parser_result)


@router.get("/reporting-periods", response_model=list[ReportingPeriodResponse])
async def list_reporting_periods(
    reporting_period_id: UUID | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[ReportingPeriodResponse]:
    _require_reporting_period_read_access(admin_context)
    if db is None:
        return []
    rows = await admin_config.list_reporting_periods(
        db,
        programme_scope=_global_config_scope(admin_context),
        reporting_period_id=reporting_period_id,
    )
    return [ReportingPeriodResponse.model_validate(row) for row in rows]


@router.post("/reporting-periods", response_model=ReportingPeriodMutationResponse)
async def create_reporting_period(
    payload: ReportingPeriodCreateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ReportingPeriodMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.create_reporting_period(
        db,
        programme_scope=_global_config_scope(admin_context),
        label=payload.label,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
        activate_on=payload.activate_on,
        deactivate_on=payload.deactivate_on,
        deactivate_on_set="deactivate_on" in payload.model_fields_set,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="reporting_period",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="reporting_period",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return ReportingPeriodMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/reporting-periods/{reporting_period_id}", response_model=ReportingPeriodMutationResponse)
async def update_reporting_period(
    reporting_period_id: UUID,
    payload: ReportingPeriodUpdateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ReportingPeriodMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="reporting_period",
        entity_id=reporting_period_id,
    )
    try:
        row = await admin_config.update_reporting_period(
            db,
            programme_scope=_global_config_scope(admin_context),
            reporting_period_id=reporting_period_id,
            label=payload.label,
            start_date=payload.start_date,
            end_date=payload.end_date,
            status=payload.status,
            activate_on=payload.activate_on,
            activate_on_set="activate_on" in payload.model_fields_set,
            deactivate_on=payload.deactivate_on,
            deactivate_on_set="deactivate_on" in payload.model_fields_set,
            commit=False,
        )
        verified = await _read_config_audit_snapshot(
            db,
            entity_type="reporting_period",
            entity_id=reporting_period_id,
        )
        if verified is None or (
            payload.status is not None and verified.get("status") != row.get("status")
        ):
            raise ApiError(
                status_code=500,
                detail="Reporting period update could not be verified",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        data_revalidation = await _revalidate_config_mutation(
            db,
            admin_context=admin_context,
            actor=staff_actor,
            entity_type="reporting_period",
            mutation="update",
            entity_id=reporting_period_id,
            snapshot=row,
            changed_fields=_config_changed_fields(payload),
            previous_snapshot=before,
        )
        await _write_config_audit(
            db,
            actor=staff_actor,
            entity_type="reporting_period",
            mutation="update",
            entity_id=reporting_period_id,
            before=before,
            after=_compact_snapshot(row),
            data_revalidation=data_revalidation,
        )
    except Exception:
        await db.rollback()
        raise
    return ReportingPeriodMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


async def _set_reporting_period_status_response(
    *,
    reporting_period_id: UUID,
    status: Literal["active", "inactive"],
    mutation: Literal["activate", "deactivate"],
    admin_context: AdminContext,
    staff_actor: StaffActorContext,
    db: AsyncSession,
) -> ReportingPeriodMutationResponse:
    before = await _read_config_audit_snapshot(
        db,
        entity_type="reporting_period",
        entity_id=reporting_period_id,
    )
    try:
        row = await admin_config.set_reporting_period_status(
            db,
            programme_scope=_global_config_scope(admin_context),
            reporting_period_id=reporting_period_id,
            status=status,
            commit=False,
        )
        verified = await _read_config_audit_snapshot(
            db,
            entity_type="reporting_period",
            entity_id=reporting_period_id,
        )
        if verified is None or verified.get("status") != status:
            raise ApiError(
                status_code=500,
                detail="Reporting period status could not be verified",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        data_revalidation = await _revalidate_config_mutation(
            db,
            admin_context=admin_context,
            actor=staff_actor,
            entity_type="reporting_period",
            mutation=mutation,
            entity_id=reporting_period_id,
            snapshot=row,
            changed_fields=["status"],
            previous_snapshot=before,
        )
        await _write_config_audit(
            db,
            actor=staff_actor,
            entity_type="reporting_period",
            mutation=mutation,
            entity_id=reporting_period_id,
            before=before,
            after=_compact_snapshot(row),
            data_revalidation=data_revalidation,
        )
    except Exception:
        await db.rollback()
        raise
    return ReportingPeriodMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/reporting-periods/{reporting_period_id}/activate", response_model=ReportingPeriodMutationResponse)
async def activate_reporting_period(
    reporting_period_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ReportingPeriodMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    return await _set_reporting_period_status_response(
        reporting_period_id=reporting_period_id,
        status="active",
        mutation="activate",
        admin_context=admin_context,
        staff_actor=staff_actor,
        db=db,
    )


@router.put("/reporting-periods/{reporting_period_id}/deactivate", response_model=ReportingPeriodMutationResponse)
async def deactivate_reporting_period(
    reporting_period_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ReportingPeriodMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    return await _set_reporting_period_status_response(
        reporting_period_id=reporting_period_id,
        status="inactive",
        mutation="deactivate",
        admin_context=admin_context,
        staff_actor=staff_actor,
        db=db,
    )


@router.delete("/reporting-periods/{reporting_period_id}", response_model=ConfigMutationDeleteResponse)
async def delete_reporting_period(
    reporting_period_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="reporting_period",
        entity_id=reporting_period_id,
    )
    await admin_config.delete_reporting_period(
        db,
        programme_scope=_global_config_scope(admin_context),
        reporting_period_id=reporting_period_id,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="reporting_period",
        mutation="delete",
        entity_id=reporting_period_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="reporting_period",
        mutation="delete",
        entity_id=reporting_period_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="reporting_period",
            entity_id=reporting_period_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/public-holidays", response_model=list[PublicHolidayResponse])
async def list_public_holidays(
    year: int | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[PublicHolidayResponse]:
    _require_master_admin(admin_context)
    if db is None:
        return []
    rows = await admin_config.list_public_holidays(
        db,
        programme_scope=_global_config_scope(admin_context),
        year=year,
    )
    return [PublicHolidayResponse.model_validate(row) for row in rows]


@router.post("/public-holidays", response_model=PublicHolidayMutationResponse)
async def upsert_public_holiday(
    payload: PublicHolidayUpsertRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> PublicHolidayMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.upsert_public_holiday(
        db,
        programme_scope=_global_config_scope(admin_context),
        holiday_date=payload.holiday_date,
        name=payload.name,
        day_of_week=payload.day_of_week,
        year=payload.year,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="public_holiday",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="public_holiday",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return PublicHolidayMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/public-holidays/{holiday_id}", response_model=PublicHolidayMutationResponse)
async def update_public_holiday(
    holiday_id: UUID,
    payload: PublicHolidayUpsertRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> PublicHolidayMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="public_holiday",
        entity_id=holiday_id,
    )
    row = await admin_config.update_public_holiday(
        db,
        programme_scope=_global_config_scope(admin_context),
        holiday_id=holiday_id,
        holiday_date=payload.holiday_date,
        name=payload.name,
        day_of_week=payload.day_of_week,
        year=payload.year,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="public_holiday",
        mutation="update",
        entity_id=holiday_id,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="public_holiday",
        mutation="update",
        entity_id=holiday_id,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return PublicHolidayMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.delete("/public-holidays/{holiday_id}", response_model=ConfigMutationDeleteResponse)
async def delete_public_holiday(
    holiday_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="public_holiday",
        entity_id=holiday_id,
    )
    await admin_config.delete_public_holiday(
        db,
        programme_scope=_global_config_scope(admin_context),
        holiday_id=holiday_id,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="public_holiday",
        mutation="delete",
        entity_id=holiday_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="public_holiday",
        mutation="delete",
        entity_id=holiday_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="public_holiday",
            entity_id=holiday_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/programmes", response_model=list[ProgrammeResponse])
async def list_programmes(
    programme_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[ProgrammeResponse]:
    _require_master_admin(admin_context)
    if db is None:
        return []
    rows = await admin_config.list_programmes(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
        master_admin=admin_context.is_master_admin,
    )
    return [ProgrammeResponse.model_validate(row) for row in rows]


@router.put("/programmes/{programme_code}", response_model=ProgrammeMutationResponse)
async def update_programme(
    programme_code: str,
    payload: ProgrammeUpdateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ProgrammeMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    clean_programme_code = programme_code.strip()
    before = await _read_config_audit_snapshot(
        db,
        entity_type="programme",
        entity_id=clean_programme_code,
    )
    row = await admin_config.update_programme(
        db,
        programme_scope={clean_programme_code},
        programme_code=clean_programme_code,
        r_year_required=payload.r_year_required,
        is_subspecialty=payload.is_subspecialty,
        rdb_alias=payload.rdb_alias,
        rdb_alias_is_set="rdb_alias" in payload.model_fields_set,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="programme",
        mutation="update",
        entity_id=clean_programme_code,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="programme",
        mutation="update",
        entity_id=clean_programme_code,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return ProgrammeMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.get("/loa-types", response_model=list[LoaTypeResponse])
async def list_loa_types(
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[LoaTypeResponse]:
    _require_master_admin(admin_context)
    if db is None:
        return []
    rows = await admin_config.list_loa_types(
        db,
        programme_scope=_global_config_scope(admin_context),
    )
    return [LoaTypeResponse.model_validate(row) for row in rows]


@router.post("/loa-types", response_model=LoaTypeMutationResponse)
async def create_loa_type(
    payload: LoaTypeCreateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> LoaTypeMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.create_loa_type(
        db,
        programme_scope=_global_config_scope(admin_context),
        code=payload.code,
        description=payload.description,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="loa_type",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="loa_type",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return LoaTypeMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/loa-types/{loa_type_id}", response_model=LoaTypeMutationResponse)
async def update_loa_type(
    loa_type_id: UUID,
    payload: LoaTypeUpdateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> LoaTypeMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="loa_type",
        entity_id=loa_type_id,
    )
    row = await admin_config.update_loa_type(
        db,
        programme_scope=_global_config_scope(admin_context),
        loa_type_id=loa_type_id,
        code=payload.code,
        description=payload.description,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="loa_type",
        mutation="update",
        entity_id=loa_type_id,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="loa_type",
        mutation="update",
        entity_id=loa_type_id,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return LoaTypeMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.delete("/loa-types/{loa_type_id}", response_model=ConfigMutationDeleteResponse)
async def delete_loa_type(
    loa_type_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="loa_type",
        entity_id=loa_type_id,
    )
    await admin_config.delete_loa_type(
        db,
        programme_scope=_global_config_scope(admin_context),
        loa_type_id=loa_type_id,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="loa_type",
        mutation="delete",
        entity_id=loa_type_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="loa_type",
        mutation="delete",
        entity_id=loa_type_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="loa_type",
            entity_id=loa_type_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/multi-posting-rules", response_model=list[MultiPostingRuleResponse])
async def list_multi_posting_rules(
    programme_code: str | None = Query(default=None),
    rule_type: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[MultiPostingRuleResponse]:
    if db is None:
        return []
    rows = await admin_config.list_multi_posting_rules(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=programme_code,
        rule_type=rule_type,
    )
    return [MultiPostingRuleResponse.model_validate(row) for row in rows]


@router.post("/multi-posting-rules", response_model=MultiPostingRuleMutationResponseModel)
async def create_multi_posting_rule(
    payload: MultiPostingRuleMutationRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> MultiPostingRuleMutationResponseModel:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.create_multi_posting_rule(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=payload.programme_code,
        posting_code_1=payload.posting_code_1,
        posting_code_2=payload.posting_code_2,
        rule_type=payload.rule_type,
        combined_label=payload.combined_label,
        main_posting_code=payload.main_posting_code,
        exclusion_code=payload.exclusion_code,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="multi_posting_rule",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="multi_posting_rule",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return MultiPostingRuleMutationResponseModel.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/multi-posting-rules/{rule_id}", response_model=MultiPostingRuleMutationResponseModel)
async def update_multi_posting_rule(
    rule_id: UUID,
    payload: MultiPostingRuleMutationRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> MultiPostingRuleMutationResponseModel:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="multi_posting_rule",
        entity_id=rule_id,
    )
    row = await admin_config.update_multi_posting_rule(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        rule_id=rule_id,
        programme_code=payload.programme_code,
        posting_code_1=payload.posting_code_1,
        posting_code_2=payload.posting_code_2,
        rule_type=payload.rule_type,
        combined_label=payload.combined_label,
        main_posting_code=payload.main_posting_code,
        exclusion_code=payload.exclusion_code,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="multi_posting_rule",
        mutation="update",
        entity_id=rule_id,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="multi_posting_rule",
        mutation="update",
        entity_id=rule_id,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return MultiPostingRuleMutationResponseModel.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.delete("/multi-posting-rules/{rule_id}", response_model=ConfigMutationDeleteResponse)
async def delete_multi_posting_rule(
    rule_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="multi_posting_rule",
        entity_id=rule_id,
    )
    await admin_config.delete_multi_posting_rule(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        rule_id=rule_id,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="multi_posting_rule",
        mutation="delete",
        entity_id=rule_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="multi_posting_rule",
        mutation="delete",
        entity_id=rule_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="multi_posting_rule",
            entity_id=rule_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/posting-groups", response_model=list[PostingGroupResponse])
async def list_posting_groups(
    programme_code: str | None = Query(default=None),
    group_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[PostingGroupResponse]:
    if db is None:
        return []
    rows = await admin_config.list_posting_groups(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
        group_code=group_code,
        master_admin=admin_context.is_master_admin,
    )
    return [PostingGroupResponse.model_validate(row) for row in rows]


@router.post("/posting-groups", response_model=PostingGroupMutationResponse)
async def create_posting_group(
    payload: PostingGroupMutationRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> PostingGroupMutationResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.create_posting_group(
        db,
        programme_scope=admin_context.programme_scope,
        group_code=payload.group_code,
        posting_code=payload.posting_code,
        programme_code=payload.programme_code,
        master_admin=admin_context.is_master_admin,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="posting_group",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="posting_group",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return PostingGroupMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/posting-groups/{posting_group_id}", response_model=PostingGroupMutationResponse)
async def update_posting_group(
    posting_group_id: UUID,
    payload: PostingGroupMutationRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> PostingGroupMutationResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="posting_group",
        entity_id=posting_group_id,
    )
    row = await admin_config.update_posting_group(
        db,
        programme_scope=admin_context.programme_scope,
        posting_group_id=posting_group_id,
        group_code=payload.group_code,
        posting_code=payload.posting_code,
        programme_code=payload.programme_code,
        master_admin=admin_context.is_master_admin,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="posting_group",
        mutation="update",
        entity_id=posting_group_id,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="posting_group",
        mutation="update",
        entity_id=posting_group_id,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return PostingGroupMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.delete("/posting-groups/{posting_group_id}", response_model=ConfigMutationDeleteResponse)
async def delete_posting_group(
    posting_group_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="posting_group",
        entity_id=posting_group_id,
    )
    await admin_config.delete_posting_group(
        db,
        programme_scope=admin_context.programme_scope,
        posting_group_id=posting_group_id,
        master_admin=admin_context.is_master_admin,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="posting_group",
        mutation="delete",
        entity_id=posting_group_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="posting_group",
        mutation="delete",
        entity_id=posting_group_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="posting_group",
            entity_id=posting_group_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/weekend-exceptions", response_model=list[WeekendExceptionResponse])
async def list_weekend_exceptions(
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[WeekendExceptionResponse]:
    _require_master_admin(admin_context)
    if db is None:
        return []
    rows = await admin_config.list_weekend_exceptions(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
        posting_code=posting_code,
        master_admin=admin_context.is_master_admin,
    )
    return [WeekendExceptionResponse.model_validate(row) for row in rows]


@router.post("/weekend-exceptions", response_model=WeekendExceptionMutationResponse)
async def create_weekend_exception(
    payload: WeekendExceptionMutationRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> WeekendExceptionMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.create_weekend_exception(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=payload.programme_code,
        posting_code=payload.posting_code,
        day_type=payload.day_type,
        start_time_min=payload.start_time_min,
        end_time_max=payload.end_time_max,
        session_type_id=payload.session_type_id,
        session_name_pattern=payload.session_name_pattern,
        mutates_to_session_type_id=payload.mutates_to_session_type_id,
        adjusted_duration_hours=payload.adjusted_duration_hours,
        master_admin=admin_context.is_master_admin,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="weekend_exception",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="weekend_exception",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return WeekendExceptionMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/weekend-exceptions/{weekend_exception_id}", response_model=WeekendExceptionMutationResponse)
async def update_weekend_exception(
    weekend_exception_id: UUID,
    payload: WeekendExceptionMutationRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> WeekendExceptionMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="weekend_exception",
        entity_id=weekend_exception_id,
    )
    row = await admin_config.update_weekend_exception(
        db,
        programme_scope=admin_context.programme_scope,
        weekend_exception_id=weekend_exception_id,
        programme_code=payload.programme_code,
        posting_code=payload.posting_code,
        day_type=payload.day_type,
        start_time_min=payload.start_time_min,
        end_time_max=payload.end_time_max,
        session_type_id=payload.session_type_id,
        session_name_pattern=payload.session_name_pattern,
        mutates_to_session_type_id=payload.mutates_to_session_type_id,
        adjusted_duration_hours=payload.adjusted_duration_hours,
        master_admin=admin_context.is_master_admin,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="weekend_exception",
        mutation="update",
        entity_id=weekend_exception_id,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="weekend_exception",
        mutation="update",
        entity_id=weekend_exception_id,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return WeekendExceptionMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.delete("/weekend-exceptions/{weekend_exception_id}", response_model=ConfigMutationDeleteResponse)
async def delete_weekend_exception(
    weekend_exception_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="weekend_exception",
        entity_id=weekend_exception_id,
    )
    await admin_config.delete_weekend_exception(
        db,
        programme_scope=admin_context.programme_scope,
        weekend_exception_id=weekend_exception_id,
        master_admin=admin_context.is_master_admin,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="weekend_exception",
        mutation="delete",
        entity_id=weekend_exception_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="weekend_exception",
        mutation="delete",
        entity_id=weekend_exception_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="weekend_exception",
            entity_id=weekend_exception_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/global-session-types", response_model=list[GlobalSessionTypeResponse])
async def list_global_session_types(
    is_active: bool | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[GlobalSessionTypeResponse]:
    _require_master_admin(admin_context)
    if db is None:
        return []
    rows = await admin_config.list_global_session_types(db, is_active=is_active)
    return [GlobalSessionTypeResponse.model_validate(row) for row in rows]


@router.post("/global-session-types", response_model=GlobalSessionTypeMutationResponse)
async def create_global_session_type(
    payload: GlobalSessionTypeCreateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> GlobalSessionTypeMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.create_global_session_type(
        db,
        programme_scope=_global_config_scope(admin_context),
        name=payload.name,
        duration_hours=payload.duration_hours,
        is_active=payload.is_active,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="global_session_type",
        mutation="create",
        entity_id=row["id"],
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="global_session_type",
        mutation="create",
        entity_id=row["id"],
        before=None,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return GlobalSessionTypeMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.put("/global-session-types/{global_session_type_id}", response_model=GlobalSessionTypeMutationResponse)
async def update_global_session_type(
    global_session_type_id: UUID,
    payload: GlobalSessionTypeUpdateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> GlobalSessionTypeMutationResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="global_session_type",
        entity_id=global_session_type_id,
    )
    row = await admin_config.update_global_session_type(
        db,
        programme_scope=_global_config_scope(admin_context),
        global_session_type_id=global_session_type_id,
        name=payload.name,
        duration_hours=payload.duration_hours,
        is_active=payload.is_active,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="global_session_type",
        mutation="update",
        entity_id=global_session_type_id,
        snapshot=row,
        changed_fields=_config_changed_fields(payload),
        previous_snapshot=before,
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="global_session_type",
        mutation="update",
        entity_id=global_session_type_id,
        before=before,
        after=_compact_snapshot(row),
        data_revalidation=data_revalidation,
    )
    return GlobalSessionTypeMutationResponse.model_validate(
        _with_data_revalidation(row, data_revalidation)
    )


@router.delete("/global-session-types/{global_session_type_id}", response_model=ConfigMutationDeleteResponse)
async def delete_global_session_type(
    global_session_type_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ConfigMutationDeleteResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    before = await _read_config_audit_snapshot(
        db,
        entity_type="global_session_type",
        entity_id=global_session_type_id,
    )
    await admin_config.delete_global_session_type(
        db,
        programme_scope=_global_config_scope(admin_context),
        global_session_type_id=global_session_type_id,
    )
    data_revalidation = await _revalidate_config_mutation(
        db,
        admin_context=admin_context,
        actor=staff_actor,
        entity_type="global_session_type",
        mutation="delete",
        entity_id=global_session_type_id,
        snapshot=before,
        changed_fields=["deleted"],
    )
    await _write_config_audit(
        db,
        actor=staff_actor,
        entity_type="global_session_type",
        mutation="delete",
        entity_id=global_session_type_id,
        before=before,
        after=None,
        data_revalidation=data_revalidation,
    )
    return ConfigMutationDeleteResponse.model_validate(
        _delete_config_response(
            entity_type="global_session_type",
            entity_id=global_session_type_id,
            data_revalidation=data_revalidation,
        )
    )


@router.get("/programme-teaching-events")
async def list_programme_teaching_events(
    programme_code: str | None = Query(default=None),
    reporting_period_id: UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_programme_pc_context(admin_context)
    if programme_code is not None:
        _require_programme_pc_scope(admin_context, programme_code)
    if db is None:
        return {"events": []}
    events = await programme_teaching_events.list_teaching_events(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        date_from=date_from,
        date_to=date_to,
        posting_code=posting_code,
    )
    return {"events": events}


@router.post("/programme-teaching-events")
async def create_programme_teaching_event(
    request: ProgrammeTeachingEventCreateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_programme_pc_scope(admin_context, request.programme_code)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    return await programme_teaching_events.create_teaching_event(
        db,
        **request.model_dump(mode="python"),
    )


@router.put("/programme-teaching-events/{event_id}")
async def update_programme_teaching_event(
    event_id: UUID,
    request: ProgrammeTeachingEventUpdateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_programme_pc_scope(admin_context, request.programme_code)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    return await programme_teaching_events.update_teaching_event(
        db,
        event_id=event_id,
        **request.model_dump(mode="python"),
    )


@router.post("/programme-teaching-events/{event_id}/duplicate")
async def duplicate_programme_teaching_event(
    event_id: UUID,
    request: ProgrammeTeachingEventDuplicateRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_programme_pc_scope(admin_context, request.programme_code)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    return await programme_teaching_events.duplicate_teaching_event(
        db,
        event_id=event_id,
        **request.model_dump(mode="python"),
    )


@router.delete("/programme-teaching-events/{event_id}")
async def delete_programme_teaching_event(
    event_id: UUID,
    programme_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, int]:
    _require_programme_pc_context(admin_context)
    if programme_code is None and len(admin_context.programme_scope) == 1:
        programme_code = next(iter(admin_context.programme_scope))
    if programme_code is None:
        raise ApiError(
            status_code=422,
            detail="programme_code is required when admin has multiple programmes",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    _require_programme_pc_scope(admin_context, programme_code)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    return await programme_teaching_events.delete_teaching_event(
        db,
        event_id=event_id,
        programme_code=programme_code,
    )


@router.get("/programme-teaching-name-options")
async def list_programme_teaching_name_options(
    programme_code: str = Query(...),
    reporting_period_id: UUID | None = Query(default=None),
    event_date: date | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_programme_pc_scope(admin_context, programme_code)
    if db is None:
        return {"options": []}
    options = await programme_teaching_events.teaching_name_options(
        db,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        relevant_date=event_date,
    )
    return {"options": options}


@router.get("/secretary-events", response_model=AdminSecretaryEventListResponse)
async def list_admin_secretary_events(
    reporting_period_id: UUID | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    teaching_name: str | None = Query(default=None),
    search: str | None = Query(default=None),
    has_attendance: bool | None = Query(default=None),
    session_type_id: UUID | None = Query(default=None),
    series_id: UUID | None = Query(default=None),
    source_type: Literal["all", "secretary", "programme_pc"] = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminSecretaryEventListResponse:
    _require_master_admin(admin_context)
    if db is None:
        return AdminSecretaryEventListResponse.model_validate(
            {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "summary": {
                    "total_events": 0,
                    "with_attendance": 0,
                    "without_attendance": 0,
                    "total_attendance_count": 0,
                    "total_external_attendance_count": 0,
                },
            }
        )
    payload = await admin_secretary_events.list_secretary_events(
        db,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        date_from=date_from,
        date_to=date_to,
        teaching_name=teaching_name,
        search=search,
        has_attendance=has_attendance,
        session_type_id=session_type_id,
        series_id=series_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return AdminSecretaryEventListResponse.model_validate(payload)


@router.get("/secretary-events/{event_id}", response_model=AdminSecretaryEventDetailResponse)
async def get_admin_secretary_event(
    event_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminSecretaryEventDetailResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await admin_secretary_events.get_secretary_event(db, event_id=event_id)
    return AdminSecretaryEventDetailResponse.model_validate(payload)


@router.post(
    "/secretary-events/{event_id}/force-delete",
    response_model=AdminSecretaryEventForceDeleteResponse,
)
async def force_delete_admin_secretary_event(
    event_id: UUID,
    request: AdminSecretaryEventForceDeleteRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminSecretaryEventForceDeleteResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await admin_secretary_events.force_delete_event(
        db,
        event_id=event_id,
        reason=request.reason,
        expected_native_attendance_count=request.expected_native_attendance_count,
        expected_external_attendance_count=request.expected_external_attendance_count,
        actor=_admin_actor_context(admin_context),
    )
    return AdminSecretaryEventForceDeleteResponse.model_validate(payload)


@router.get(
    "/resident-attendance",
    response_model=AdminResidentAttendanceOverviewResponse,
)
async def list_admin_resident_attendance(
    programme_code: str | None = Query(default=None),
    search: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminResidentAttendanceOverviewResponse:
    admin_resident_attendance.ensure_read_access(
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=(programme_code.strip() or None) if programme_code else None,
    )
    if db is None:
        return AdminResidentAttendanceOverviewResponse(
            items=[],
            total=0,
            limit=limit,
            offset=offset,
        )
    payload = await admin_resident_attendance.list_residents(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=programme_code,
        search=search,
        posting_code=posting_code,
        limit=limit,
        offset=offset,
    )
    return AdminResidentAttendanceOverviewResponse.model_validate(payload)


@router.get(
    "/resident-attendance/{resident_id}",
    response_model=AdminResidentAttendanceDetailResponse,
)
async def get_admin_resident_attendance(
    resident_id: UUID,
    reporting_period_id: UUID | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    source: Literal["department_secretary", "programme_pc", "adhoc"] | None = Query(
        default=None
    ),
    status: Literal["submitted", "flagged", "removed"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminResidentAttendanceDetailResponse:
    admin_resident_attendance.ensure_read_access(
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await admin_resident_attendance.get_resident_attendance(
        db,
        resident_id=resident_id,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        date_from=date_from,
        date_to=date_to,
        source=source,
        status=status,
        limit=limit,
        offset=offset,
    )
    return AdminResidentAttendanceDetailResponse.model_validate(payload)


@router.get(
    "/resident-submissions",
    response_model=AdminResidentSubmissionListResponse,
)
async def list_admin_resident_submissions(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    resident_id: UUID | None = Query(default=None),
    mcr: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    source: str | None = Query(default=None),
    is_adhoc: bool | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    teaching_event_id: UUID | None = Query(default=None),
    teaching_name: str | None = Query(default=None),
    session_type_id: UUID | None = Query(default=None),
    submitted_from: datetime | None = Query(default=None),
    submitted_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminResidentSubmissionListResponse:
    if db is None:
        return AdminResidentSubmissionListResponse.model_validate(
            {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "summary": {
                    "total_submissions": 0,
                    "submitted_count": 0,
                    "flagged_count": 0,
                    "removed_count": 0,
                    "secretary_event_count": 0,
                    "adhoc_count": 0,
                },
            }
        )
    payload = await admin_resident_submissions.list_resident_submissions(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        resident_id=resident_id,
        mcr=mcr,
        date_from=date_from,
        date_to=date_to,
        source=source,
        is_adhoc=is_adhoc,
        status=status,
        search=search,
        teaching_event_id=teaching_event_id,
        teaching_name=teaching_name,
        session_type_id=session_type_id,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        limit=limit,
        offset=offset,
    )
    return AdminResidentSubmissionListResponse.model_validate(payload)


@router.get(
    "/resident-submissions/{submission_id}",
    response_model=AdminResidentSubmissionDetailResponse,
)
async def get_admin_resident_submission(
    submission_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminResidentSubmissionDetailResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await admin_resident_submissions.get_resident_submission(
        db,
        submission_id=submission_id,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return AdminResidentSubmissionDetailResponse.model_validate(payload)


@router.get(
    "/external-attendance",
    response_model=AdminExternalAttendanceListResponse,
)
async def list_admin_external_attendance(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    home_cluster: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminExternalAttendanceListResponse:
    if db is None:
        return AdminExternalAttendanceListResponse.model_validate(
            {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "summary": {
                    "total_records": 0,
                    "submitted_count": 0,
                    "flagged_count": 0,
                    "removed_count": 0,
                    "adhoc_count": 0,
                },
            }
        )
    payload = await admin_external_attendance.list_external_attendance(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=programme_code,
        home_cluster=home_cluster,
        posting_code=posting_code,
        mcr=mcr,
        status=status,
        date_from=date_from,
        date_to=date_to,
        reporting_period_id=reporting_period_id,
        limit=limit,
        offset=offset,
    )
    return AdminExternalAttendanceListResponse.model_validate(payload)


@router.get("/external-attendance/export.xlsx")
async def export_admin_external_attendance(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    home_cluster: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> Response:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await admin_external_attendance.export_external_attendance_xlsx(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=programme_code,
        home_cluster=home_cluster,
        posting_code=posting_code,
        mcr=mcr,
        status=status,
        date_from=date_from,
        date_to=date_to,
        reporting_period_id=reporting_period_id,
    )
    return Response(
        content=payload["content"],
        media_type=payload["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{payload["filename"]}"',
        },
    )


@router.get(
    "/external-attendance/{attendance_id}",
    response_model=AdminExternalAttendanceDetailResponse,
)
async def get_admin_external_attendance(
    attendance_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminExternalAttendanceDetailResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await admin_external_attendance.get_external_attendance(
        db,
        attendance_id=attendance_id,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return AdminExternalAttendanceDetailResponse.model_validate(payload)


@router.get("/logs", response_model=AdminLogListResponse)
async def list_admin_logs(
    log_type: AdminLogType | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
    actor_role: AdminLogActorRole | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    reporting_period_id: UUID | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    upload_type: Literal["rdb", "ttf", "form_f1", "public_holidays"] | None = Query(default=None),
    warning_type: str | None = Query(default=None),
    correction_type: str | None = Query(default=None),
    config_entity_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminLogListResponse:
    if db is None:
        return AdminLogListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await list_admin_logs_read_model(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        log_type=log_type,
        date_from=date_from,
        date_to=date_to,
        actor_user_id=actor_user_id,
        actor_role=actor_role.value if actor_role is not None else None,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        entity_type=entity_type,
        entity_id=entity_id,
        upload_type=upload_type,
        warning_type=warning_type,
        correction_type=correction_type,
        config_entity_type=config_entity_type,
        status=status,
        outcome=outcome,
        search=search,
        limit=limit,
        offset=offset,
    )
    return AdminLogListResponse.model_validate(payload)


@router.get("/logs/{log_id}", response_model=AdminLogDetailResponse)
async def get_admin_log_detail(
    log_id: str,
    include_raw_summary: bool = Query(default=False),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> AdminLogDetailResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await get_admin_log_read_model(
        db,
        log_id=log_id,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        include_raw_summary=include_raw_summary,
    )
    return AdminLogDetailResponse.model_validate(payload)


@router.get("/upload-logs", response_model=UploadLogListResponse)
async def list_upload_logs(
    upload_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    reporting_period_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> UploadLogListResponse:
    if db is None:
        return UploadLogListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await list_upload_logs_read_model(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        upload_type=upload_type,
        status=status,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        limit=limit,
        offset=offset,
        search=search,
    )
    return UploadLogListResponse.model_validate(payload)


@router.get("/upload-logs/{upload_log_id}", response_model=UploadLogDetailResponse)
async def get_upload_log_detail(
    upload_log_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> UploadLogDetailResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await get_upload_log_read_model(
        db,
        upload_log_id=upload_log_id,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return UploadLogDetailResponse.model_validate(payload)


@router.get("/upload-warnings", response_model=list[UploadWarningResponse])
async def get_upload_warnings(
    upload_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    warning_type: str | None = Query(default=None),
    reporting_period_id: UUID | None = Query(default=None),
    upload_log_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    month_label: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    mode: Literal["active", "history"] = Query(default="active"),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[UploadWarningResponse]:
    if db is None:
        return []
    try:
        rows = await list_warning_issues(
            db,
            programme_scope=admin_context.programme_scope,
            master_admin=admin_context.is_master_admin,
            upload_log_id=upload_log_id,
            upload_type=upload_type,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
            warning_type=warning_type,
            severity=severity,
            status=status,
            mcr=mcr,
            month_label=month_label,
            search=search,
            limit=limit,
            offset=offset,
        )
    except DurableWarningStoreUnavailable:
        rows = await list_upload_warnings(
            db,
            programme_scope=admin_context.programme_scope,
            master_admin=admin_context.is_master_admin,
            upload_type=upload_type,
            severity=severity,
            programme_code=programme_code,
            warning_type=warning_type,
            reporting_period_id=reporting_period_id,
            search=search,
            mode=mode,
        )
    return [UploadWarningResponse.model_validate(row) for row in rows]


@router.get(
    "/upload-warnings/{warning_issue_id}",
    response_model=UploadWarningIssueDetailResponse,
)
async def get_upload_warning_issue(
    warning_issue_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> UploadWarningIssueDetailResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    try:
        payload = await get_warning_issue_detail(
            db,
            issue_id=warning_issue_id,
            programme_scope=admin_context.programme_scope,
            master_admin=admin_context.is_master_admin,
        )
    except DurableWarningStoreUnavailable as exc:
        raise ApiError(
            status_code=404,
            detail="Warning issue not found",
            error_code=ErrorCode.NOT_FOUND.value,
        ) from exc
    if payload is None:
        raise ApiError(
            status_code=404,
            detail="Warning issue not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return UploadWarningIssueDetailResponse.model_validate(payload)


async def _update_upload_warning_issue(
    *,
    warning_issue_id: UUID,
    action: Literal["resolve", "dismiss", "supersede"],
    body: UploadWarningActionRequest,
    admin_context: AdminContext,
    staff_actor: StaffActorContext,
    db: AsyncSession | None,
) -> UploadWarningIssueActionResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    try:
        payload = await update_warning_issue_status(
            db,
            issue_id=warning_issue_id,
            action=action,
            note=body.note,
            actor=staff_actor,
            programme_scope=admin_context.programme_scope,
            master_admin=admin_context.is_master_admin,
        )
    except DurableWarningStoreUnavailable as exc:
        raise ApiError(
            status_code=404,
            detail="Warning issue not found",
            error_code=ErrorCode.NOT_FOUND.value,
        ) from exc
    if payload is None:
        raise ApiError(
            status_code=404,
            detail="Warning issue not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return UploadWarningIssueActionResponse.model_validate(payload)


@router.post(
    "/upload-warnings/{warning_issue_id}/resolve",
    response_model=UploadWarningIssueActionResponse,
)
async def resolve_upload_warning_issue(
    warning_issue_id: UUID,
    body: UploadWarningActionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> UploadWarningIssueActionResponse:
    return await _update_upload_warning_issue(
        warning_issue_id=warning_issue_id,
        action="resolve",
        body=body,
        admin_context=admin_context,
        staff_actor=staff_actor,
        db=db,
    )


@router.post(
    "/upload-warnings/{warning_issue_id}/dismiss",
    response_model=UploadWarningIssueActionResponse,
)
async def dismiss_upload_warning_issue(
    warning_issue_id: UUID,
    body: UploadWarningActionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> UploadWarningIssueActionResponse:
    return await _update_upload_warning_issue(
        warning_issue_id=warning_issue_id,
        action="dismiss",
        body=body,
        admin_context=admin_context,
        staff_actor=staff_actor,
        db=db,
    )


@router.post(
    "/upload-warnings/{warning_issue_id}/supersede",
    response_model=UploadWarningIssueActionResponse,
)
async def supersede_upload_warning_issue(
    warning_issue_id: UUID,
    body: UploadWarningActionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> UploadWarningIssueActionResponse:
    return await _update_upload_warning_issue(
        warning_issue_id=warning_issue_id,
        action="supersede",
        body=body,
        admin_context=admin_context,
        staff_actor=staff_actor,
        db=db,
    )


@router.post(
    "/upload-warnings/{warning_issue_id}/source-cell-replace/preview",
    response_model=RDBSourceCellWarningPreviewResponse,
)
async def preview_upload_warning_source_cell_replace(
    warning_issue_id: UUID,
    body: RDBSourceCellWarningPreviewRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> RDBSourceCellWarningPreviewResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.preview_warning_source_cell_replacement(
        db,
        warning_issue_id=warning_issue_id,
        replacement_raw_cell_value=body.replacement_raw_cell_value,
        upload_warning_id=body.upload_warning_id,
        expected_latest_upload_warning_id=body.expected_latest_upload_warning_id,
        expected_fingerprint=body.expected_fingerprint,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return RDBSourceCellWarningPreviewResponse.model_validate(payload)


@router.post(
    "/upload-warnings/{warning_issue_id}/source-cell-replace/apply",
    response_model=RDBSourceCellWarningApplyResponse,
)
async def apply_upload_warning_source_cell_replace(
    warning_issue_id: UUID,
    body: RDBSourceCellWarningApplyRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> RDBSourceCellWarningApplyResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.apply_warning_source_cell_replacement(
        db,
        warning_issue_id=warning_issue_id,
        replacement_raw_cell_value=body.replacement_raw_cell_value,
        correction_reason=body.correction_reason,
        upload_warning_id=body.upload_warning_id,
        expected_latest_upload_warning_id=body.expected_latest_upload_warning_id,
        expected_fingerprint=body.expected_fingerprint,
        actor=_admin_actor_context(admin_context),
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return RDBSourceCellWarningApplyResponse.model_validate(payload)


@router.get("/parsed-data/residents", response_model=ParsedResidentListResponse)
async def list_parsed_residents(
    programme_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedResidentListResponse:
    if db is None:
        return ParsedResidentListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_residents(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        programme_code=programme_code,
        mcr=mcr,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ParsedResidentListResponse.model_validate(payload)


@router.get("/parsed-data/resident-postings", response_model=ParsedResidentPostingListResponse)
async def list_parsed_resident_postings(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    status: str | None = Query(default=None),
    month_label: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedResidentPostingListResponse:
    if db is None:
        return ParsedResidentPostingListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_resident_postings(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        mcr=mcr,
        status=status,
        month_label=month_label,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ParsedResidentPostingListResponse.model_validate(payload)


@router.get("/parsed-data/teaching-targets", response_model=ParsedTeachingTargetListResponse)
async def list_parsed_teaching_targets(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    r_year: str | None = Query(default=None),
    session_type: str | None = Query(default=None),
    is_tracked: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedTeachingTargetListResponse:
    if db is None:
        return ParsedTeachingTargetListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_teaching_targets(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        r_year=r_year,
        session_type=session_type,
        is_tracked=is_tracked,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ParsedTeachingTargetListResponse.model_validate(payload)


@router.get(
    "/parsed-data/teaching-name-catalogue",
    response_model=ParsedTeachingNameCatalogueListResponse,
)
async def list_parsed_teaching_name_catalogue(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    r_year: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    is_tracked: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedTeachingNameCatalogueListResponse:
    if db is None:
        return ParsedTeachingNameCatalogueListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_teaching_name_catalogue(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        r_year=r_year,
        keyword=keyword,
        is_tracked=is_tracked,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ParsedTeachingNameCatalogueListResponse.model_validate(payload)


@router.get("/parsed-data/form-f1-records", response_model=ParsedFormF1RecordListResponse)
async def list_parsed_form_f1_records(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    month_label: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedFormF1RecordListResponse:
    if db is None:
        return ParsedFormF1RecordListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_form_f1_records(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        mcr=mcr,
        month_label=month_label,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ParsedFormF1RecordListResponse.model_validate(payload)


@router.get("/parsed-data/public-holidays", response_model=ParsedPublicHolidayListResponse)
async def list_parsed_public_holidays(
    year: int | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedPublicHolidayListResponse:
    _require_master_admin(admin_context)
    if db is None:
        return ParsedPublicHolidayListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_public_holidays(
        db,
        year=year,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ParsedPublicHolidayListResponse.model_validate(payload)


@router.get(
    "/parsed-data/academic-month-boundaries",
    response_model=ParsedAcademicMonthBoundaryListResponse,
)
async def list_parsed_academic_month_boundaries(
    academic_year_label: str | None = Query(default=None),
    ay_date_category: str | None = Query(default=None),
    month_label: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedAcademicMonthBoundaryListResponse:
    _require_master_admin(admin_context)
    if db is None:
        return ParsedAcademicMonthBoundaryListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_academic_month_boundaries(
        db,
        academic_year_label=academic_year_label,
        ay_date_category=ay_date_category,
        month_label=month_label,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ParsedAcademicMonthBoundaryListResponse.model_validate(payload)


@router.patch("/parsed-data/residents/{resident_id}", response_model=ParsedDataCorrectionResponse)
async def correct_parsed_resident(
    resident_id: UUID,
    request: ParsedDataCorrectionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataCorrectionResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.correct_resident(
        db,
        row_id=resident_id,
        changes=request.changes,
        correction_reason=request.correction_reason,
        last_seen_updated_at=request.last_seen_updated_at,
        actor=staff_actor,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return ParsedDataCorrectionResponse.model_validate(payload)


@router.patch(
    "/parsed-data/resident-postings/{resident_posting_id}",
    response_model=ParsedDataCorrectionResponse,
)
async def correct_parsed_resident_posting(
    resident_posting_id: UUID,
    request: ParsedDataCorrectionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataCorrectionResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.correct_resident_posting(
        db,
        row_id=resident_posting_id,
        changes=request.changes,
        correction_reason=request.correction_reason,
        last_seen_updated_at=request.last_seen_updated_at,
        actor=staff_actor,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return ParsedDataCorrectionResponse.model_validate(payload)


@router.patch(
    "/parsed-data/teaching-targets/{teaching_target_id}",
    response_model=ParsedDataCorrectionResponse,
)
async def correct_parsed_teaching_target(
    teaching_target_id: UUID,
    request: ParsedDataCorrectionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataCorrectionResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.correct_teaching_target(
        db,
        row_id=teaching_target_id,
        changes=request.changes,
        correction_reason=request.correction_reason,
        last_seen_updated_at=request.last_seen_updated_at,
        actor=staff_actor,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return ParsedDataCorrectionResponse.model_validate(payload)


@router.patch(
    "/parsed-data/form-f1-records/{form_f1_record_id}",
    response_model=ParsedDataCorrectionResponse,
)
async def correct_parsed_form_f1_record(
    form_f1_record_id: UUID,
    request: ParsedDataCorrectionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataCorrectionResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.correct_form_f1_record(
        db,
        row_id=form_f1_record_id,
        changes=request.changes,
        correction_reason=request.correction_reason,
        last_seen_updated_at=request.last_seen_updated_at,
        actor=staff_actor,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return ParsedDataCorrectionResponse.model_validate(payload)


@router.patch(
    "/parsed-data/academic-month-boundaries/{academic_month_boundary_id}",
    response_model=ParsedDataCorrectionResponse,
)
async def correct_parsed_academic_month_boundary(
    academic_month_boundary_id: UUID,
    request: ParsedDataCorrectionRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataCorrectionResponse:
    _require_master_admin(admin_context)
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.correct_academic_month_boundary(
        db,
        row_id=academic_month_boundary_id,
        changes=request.changes,
        correction_reason=request.correction_reason,
        last_seen_updated_at=request.last_seen_updated_at,
        actor=staff_actor,
    )
    return ParsedDataCorrectionResponse.model_validate(payload)


@router.post(
    "/parsed-data/resident-postings/source-cell-replace",
    response_model=ParsedDataSourceCellReplaceResponse,
)
async def replace_parsed_resident_posting_source_cell(
    request: ResidentPostingSourceCellReplaceRequest,
    admin_context: AdminContext = Depends(require_admin_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataSourceCellReplaceResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    payload = await parsed_data.replace_resident_posting_source_cell(
        db,
        affected_resident_posting_ids=request.affected_resident_posting_ids,
        replacement_rows=[
            row.model_dump(mode="python") for row in request.replacement_rows
        ],
        last_seen_rows=[row.model_dump(mode="python") for row in request.last_seen_rows],
        source=request.source.model_dump(mode="python"),
        correction_reason=request.correction_reason,
        actor=staff_actor,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
    )
    return ParsedDataSourceCellReplaceResponse.model_validate(payload)


@router.get(
    "/parsed-data/corrections",
    response_model=ParsedDataCorrectionHistoryListResponse,
)
async def list_parsed_data_corrections(
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    upload_log_id: UUID | None = Query(default=None),
    sheet_name: str | None = Query(default=None),
    row_number: int | None = Query(default=None, ge=1),
    cell_ref: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ParsedDataCorrectionHistoryListResponse:
    if db is None:
        return ParsedDataCorrectionHistoryListResponse(items=[], total=0, limit=limit, offset=offset)
    payload = await parsed_data.list_correction_history(
        db,
        programme_scope=admin_context.programme_scope,
        master_admin=admin_context.is_master_admin,
        entity_type=entity_type,
        entity_id=entity_id,
        upload_log_id=upload_log_id,
        sheet_name=sheet_name,
        row_number=row_number,
        cell_ref=cell_ref,
        limit=limit,
        offset=offset,
    )
    return ParsedDataCorrectionHistoryListResponse.model_validate(payload)


@router.get("/form-f1-records", response_model=list[FormF1RecordResponse])
async def list_form_f1_records(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    month_label: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[FormF1RecordResponse]:
    if db is None:
        return []
    rows = await admin_config.list_form_f1_records(
        db,
        programme_scope=admin_context.programme_scope,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        mcr=mcr,
        month_label=month_label,
        is_active=is_active,
    )
    return [FormF1RecordResponse.model_validate(row) for row in rows]


@router.get("/residents", response_model=list[ResidentResponse])
async def list_residents(
    programme_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    employer_tag: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[ResidentResponse]:
    if db is None:
        return []
    rows = await admin_config.list_residents(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
        mcr=mcr,
        name=name,
        status=status,
        employer_tag=employer_tag,
        limit=limit,
    )
    return [ResidentResponse.model_validate(row) for row in rows]


@router.get("/residents/{resident_id}", response_model=ResidentResponse)
async def get_resident(
    resident_id: UUID,
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> ResidentResponse:
    if db is None:
        raise ApiError(
            status_code=500,
            detail="Database unavailable",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
    row = await admin_config.get_resident_by_id(
        db,
        programme_scope=admin_context.programme_scope,
        resident_id=resident_id,
    )
    return ResidentResponse.model_validate(row)


@router.get("/resident-postings", response_model=list[ResidentPostingResponse])
async def list_resident_postings(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    mcr: str | None = Query(default=None),
    resident_id: UUID | None = Query(default=None),
    month_label: str | None = Query(default=None),
    r_year: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[ResidentPostingResponse]:
    if db is None:
        return []
    rows = await admin_config.list_resident_postings(
        db,
        programme_scope=admin_context.programme_scope,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        mcr=mcr,
        resident_id=resident_id,
        month_label=month_label,
        r_year=r_year,
        status=status,
        limit=limit,
    )
    return [ResidentPostingResponse.model_validate(row) for row in rows]


@router.get("/posting-codes", response_model=list[PostingCodeResponse])
async def list_posting_codes(
    code: str | None = Query(default=None),
    institution: str | None = Query(default=None),
    department: str | None = Query(default=None),
    is_emergency: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[PostingCodeResponse]:
    del admin_context
    if db is None:
        return []
    rows = await admin_config.list_posting_codes(
        db,
        code=code,
        institution=institution,
        department=department,
        is_emergency=is_emergency,
        limit=limit,
    )
    return [PostingCodeResponse.model_validate(row) for row in rows]


@router.get("/session-types", response_model=list[SessionTypeResponse])
async def list_session_types(
    name: str | None = Query(default=None),
    duration_hours: Decimal | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[SessionTypeResponse]:
    del admin_context
    if db is None:
        return []
    rows = await admin_config.list_session_types(
        db,
        name=name,
        duration_hours=duration_hours,
        limit=limit,
    )
    return [SessionTypeResponse.model_validate(row) for row in rows]


@router.get("/teaching-targets", response_model=list[TeachingTargetResponse])
async def list_teaching_targets(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    r_year: str | None = Query(default=None),
    session_type_id: UUID | None = Query(default=None),
    is_tracked: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[TeachingTargetResponse]:
    if db is None:
        return []
    rows = await admin_config.list_teaching_targets(
        db,
        programme_scope=admin_context.programme_scope,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        r_year=r_year,
        session_type_id=session_type_id,
        is_tracked=is_tracked,
        limit=limit,
    )
    return [TeachingTargetResponse.model_validate(row) for row in rows]


@router.get(
    "/teaching-name-catalogue",
    response_model=list[TeachingNameCatalogueResponse],
)
async def list_teaching_name_catalogue(
    reporting_period_id: UUID | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    r_year: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    session_type_id: UUID | None = Query(default=None),
    is_tracked: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[TeachingNameCatalogueResponse]:
    if db is None:
        return []
    rows = await admin_config.list_teaching_name_catalogue(
        db,
        programme_scope=admin_context.programme_scope,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        r_year=r_year,
        keyword=keyword,
        session_type_id=session_type_id,
        is_tracked=is_tracked,
        limit=limit,
    )
    return [TeachingNameCatalogueResponse.model_validate(row) for row in rows]


@router.get(
    "/academic-month-boundaries",
    response_model=list[AcademicMonthBoundaryResponse],
)
async def list_academic_month_boundaries(
    ay_date_category: str | None = Query(default=None),
    month_label: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    upload_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[AcademicMonthBoundaryResponse]:
    del admin_context
    if db is None:
        return []
    rows = await admin_config.list_academic_month_boundaries(
        db,
        ay_date_category=ay_date_category,
        month_label=month_label,
        date_from=date_from,
        date_to=date_to,
        upload_id=upload_id,
        limit=limit,
    )
    return [AcademicMonthBoundaryResponse.model_validate(row) for row in rows]
