from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.parser_common import (
    ParserResult,
    UploadValidationError,
    dispatch_parser_by_upload_slot,
    normalise_scope_values,
    validate_upload_payload,
    write_upload_log,
)


router = APIRouter(prefix="/admin", tags=["admin"])


try:
    from app.database import get_db as get_db_session
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
        raise HTTPException(status_code=403, detail="Forbidden - admin role required")
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        user_id = UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc

    return AdminContext(
        user_id=user_id, programme_scope=normalise_scope_values(x_user_programme)
    )


def _require_programme_in_scope(admin_context: AdminContext, programme_code: str) -> None:
    if not admin_context.programme_scope:
        raise HTTPException(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
        )
    if programme_code not in admin_context.programme_scope:
        raise HTTPException(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
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
        "month_labels_parsed": metadata.get("month_labels_parsed", []),
        "active_count": metadata.get("active_count", 0),
        "inactive_count": metadata.get("inactive_count", 0),
        "warnings": result.warnings,
        "errors": result.errors,
    }


def _format_public_holiday_response(result: ParserResult) -> dict[str, Any]:
    metadata = result.metadata or {}
    return {
        "inserted": metadata.get("inserted", result.created_count),
        "skipped": metadata.get("skipped", result.updated_count),
        "warnings": result.warnings,
        "errors": result.errors,
    }


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
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parser_result = await dispatch_parser_by_upload_slot(
        upload_type="rdb",
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
    )

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        reporting_period_id=reporting_period_id,
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parser_result = await dispatch_parser_by_upload_slot(
        upload_type="ttf",
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parser_result = await dispatch_parser_by_upload_slot(
        upload_type="form_f1",
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
        reporting_period_id=reporting_period_id,
    )

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
        reporting_period_id=reporting_period_id,
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parser_result = await dispatch_parser_by_upload_slot(
        upload_type="public_holidays",
        file_bytes=validated.file_bytes,
        original_filename=validated.original_filename,
    )

    await _write_upload_log_safely(
        db=db,
        parser_result=parser_result,
        original_filename=validated.original_filename,
        uploaded_by=admin_context.user_id,
    )

    return _format_public_holiday_response(parser_result)
