from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode, UploadValidationApiError
from app.schemas import (
    FormF1RecordResponse,
    GlobalSessionTypeResponse,
    LoaTypeResponse,
    MultiPostingRuleResponse,
    PostingGroupResponse,
    ProgrammeResponse,
    PublicHolidayResponse,
    ReportingPeriodResponse,
    UploadLogResponse,
    WeekendExceptionResponse,
)
from app.services import admin_config
from app.services.parser_common import (
    ParserResult,
    UploadValidationError,
    normalise_scope_values,
    validate_upload_payload,
    write_upload_log,
)
from app.services.formf1_parser import parse_formf1_upload
from app.services.public_holiday_parser import parse_public_holiday_upload
from app.services.ttf_parser import TTFUploadLockError, parse_ttf_upload


router = APIRouter(prefix="/admin", tags=["admin"])


try:
    from app.database import get_db_session
except Exception:

    async def get_db_session() -> AsyncIterator[AsyncSession | None]:
        yield None


@dataclass(slots=True)
class AdminContext:
    user_id: UUID
    programme_scope: set[str]


async def require_admin_context(
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_programme: Annotated[str | None, Header(alias="X-User-Programme")] = None,
) -> AdminContext:
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

    return AdminContext(
        user_id=user_id, programme_scope=normalise_scope_values(x_user_programme)
    )


def _require_programme_in_scope(admin_context: AdminContext, programme_code: str) -> None:
    if not admin_context.programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if programme_code not in admin_context.programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _format_rdb_response(result: ParserResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    return {
        "residents_created": metadata.get("residents_created", result.created_count),
        "residents_updated": metadata.get("residents_updated", result.updated_count),
        "postings_created": metadata.get("postings_created", 0),
        "posting_codes_added": metadata.get("posting_codes_added", []),
        "loa_records": metadata.get("loa_records", 0),
        "unknown_loa_types": metadata.get("unknown_loa_types", []),
        "employed_residents_flagged": metadata.get("employed_residents_flagged", 0),
        "multi_posting_rules_applied": metadata.get("multi_posting_rules_applied", 0),
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
        "warnings": result.warnings,
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


async def _write_upload_log_safely(
    *,
    db: AsyncSession | None,
    parser_result: ParserResult,
    original_filename: str,
    uploaded_by: UUID,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
) -> None:
    if db is None:
        return

    try:
        await write_upload_log(
            db,
            upload_type=parser_result.upload_type,
            original_filename=original_filename,
            status=parser_result.status,
            summary=parser_result.to_summary(),
            uploaded_by=uploaded_by,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
        )
    except Exception:
        # Upload log writing should never leak internal DB errors to API callers.
        return


@router.post("/upload/rdb")
async def upload_rdb(
    file: UploadFile = File(...),
    reporting_period_id: UUID = Form(...),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="rdb",
            filename=file.filename,
            file_bytes=file_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

    from app.services.rdb_parser import parse_rdb_upload

    parser_result = await parse_rdb_upload(
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
        db_session=db,
    )

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
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
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    _require_programme_in_scope(admin_context, programme_code)

    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="ttf",
            filename=file.filename,
            file_bytes=file_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

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

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
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
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="form_f1",
            filename=file.filename,
            file_bytes=file_bytes,
        )
    except UploadValidationError as exc:
        raise ApiError(
            status_code=422,
            detail="Upload file validation failed",
            error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
            errors=[str(exc)],
        ) from exc

    parser_result = await parse_formf1_upload(
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
        db_session=db,
    )

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
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
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        validated = validate_upload_payload(
            upload_type="public_holidays",
            filename=file.filename,
            file_bytes=file_bytes,
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

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
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
    del admin_context  # role guard is enforced by dependency
    if db is None:
        return []
    rows = await admin_config.list_reporting_periods(
        db,
        reporting_period_id=reporting_period_id,
    )
    return [ReportingPeriodResponse.model_validate(row) for row in rows]


@router.get("/public-holidays", response_model=list[PublicHolidayResponse])
async def list_public_holidays(
    year: int | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[PublicHolidayResponse]:
    del admin_context  # role guard is enforced by dependency
    if db is None:
        return []
    rows = await admin_config.list_public_holidays(db, year=year)
    return [PublicHolidayResponse.model_validate(row) for row in rows]


@router.get("/programmes", response_model=list[ProgrammeResponse])
async def list_programmes(
    programme_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[ProgrammeResponse]:
    if db is None:
        return []
    rows = await admin_config.list_programmes(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
    )
    return [ProgrammeResponse.model_validate(row) for row in rows]


@router.get("/loa-types", response_model=list[LoaTypeResponse])
async def list_loa_types(
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[LoaTypeResponse]:
    del admin_context  # role guard is enforced by dependency
    if db is None:
        return []
    rows = await admin_config.list_loa_types(db)
    return [LoaTypeResponse.model_validate(row) for row in rows]


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
        programme_code=programme_code,
        rule_type=rule_type,
    )
    return [MultiPostingRuleResponse.model_validate(row) for row in rows]


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
    )
    return [PostingGroupResponse.model_validate(row) for row in rows]


@router.get("/weekend-exceptions", response_model=list[WeekendExceptionResponse])
async def list_weekend_exceptions(
    programme_code: str | None = Query(default=None),
    posting_code: str | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[WeekendExceptionResponse]:
    if db is None:
        return []
    rows = await admin_config.list_weekend_exceptions(
        db,
        programme_scope=admin_context.programme_scope,
        programme_code=programme_code,
        posting_code=posting_code,
    )
    return [WeekendExceptionResponse.model_validate(row) for row in rows]


@router.get("/global-session-types", response_model=list[GlobalSessionTypeResponse])
async def list_global_session_types(
    is_active: bool | None = Query(default=None),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[GlobalSessionTypeResponse]:
    del admin_context  # role guard is enforced by dependency
    if db is None:
        return []
    rows = await admin_config.list_global_session_types(db, is_active=is_active)
    return [GlobalSessionTypeResponse.model_validate(row) for row in rows]


@router.get("/upload-logs", response_model=list[UploadLogResponse])
async def list_upload_logs(
    upload_type: str | None = Query(default=None),
    programme_code: str | None = Query(default=None),
    reporting_period_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    admin_context: AdminContext = Depends(require_admin_context),
    db: AsyncSession | None = Depends(get_db_session),
) -> list[UploadLogResponse]:
    if db is None:
        return []
    rows = await admin_config.list_upload_logs(
        db,
        programme_scope=admin_context.programme_scope,
        upload_type=upload_type,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        limit=limit,
    )
    return [UploadLogResponse.model_validate(row) for row in rows]


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
