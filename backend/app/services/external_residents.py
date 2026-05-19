from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


ALLOWED_HOME_CLUSTERS = {"NUH", "SingHealth"}


def normalise_mcr(raw_mcr: str) -> str:
    cleaned = raw_mcr.strip().upper()
    if not cleaned:
        raise ApiError(
            status_code=422,
            detail="mcr is required",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return cleaned


async def _posting_exists(db: AsyncSession, posting_code: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM posting_codes
            WHERE code = :posting_code
            LIMIT 1
            """
        ),
        {"posting_code": posting_code},
    )
    return result.scalar_one_or_none() is not None


async def _mcr_exists_in_native_residents(db: AsyncSession, mcr: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM residents
            WHERE mcr = :mcr
            LIMIT 1
            """
        ),
        {"mcr": mcr},
    )
    return result.scalar_one_or_none() is not None


async def _mcr_exists_in_external_residents(db: AsyncSession, mcr: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM external_residents
            WHERE mcr = :mcr
            LIMIT 1
            """
        ),
        {"mcr": mcr},
    )
    return result.scalar_one_or_none() is not None


async def _external_resident_or_unauthorized(
    db: AsyncSession,
    external_resident_id: UUID,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, name, mcr, home_cluster, current_nhg_posting_code, status
            FROM external_residents
            WHERE id = :external_resident_id
            """
        ),
        {"external_resident_id": str(external_resident_id)},
    )
    row = result.mappings().one_or_none()
    if row is None or row.get("status") == "inactive":
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    return dict(row)


async def register_external_resident(
    db: AsyncSession,
    *,
    name: str,
    mcr: str,
    home_cluster: str,
    current_nhg_posting_code: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    clean_name = name.strip()
    if not clean_name:
        raise ApiError(
            status_code=422,
            detail="name is required",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    normalised_mcr = normalise_mcr(mcr)
    if home_cluster not in ALLOWED_HOME_CLUSTERS:
        raise ApiError(
            status_code=422,
            detail="home_cluster must be NUH or SingHealth",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if not await _posting_exists(db, current_nhg_posting_code):
        raise ApiError(
            status_code=422,
            detail="current_nhg_posting_code is not valid",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if await _mcr_exists_in_native_residents(db, normalised_mcr):
        raise ApiError(
            status_code=409,
            detail="MCR already exists",
            error_code=ErrorCode.CONFLICT.value,
        )
    if await _mcr_exists_in_external_residents(db, normalised_mcr):
        raise ApiError(
            status_code=409,
            detail="MCR already exists",
            error_code=ErrorCode.CONFLICT.value,
        )

    resident_insert = await db.execute(
        text(
            """
            INSERT INTO external_residents (
                name,
                mcr,
                home_cluster,
                current_nhg_posting_code,
                status
            )
            VALUES (
                :name,
                :mcr,
                :home_cluster,
                :current_nhg_posting_code,
                'active'
            )
            RETURNING id, name, mcr, home_cluster, current_nhg_posting_code, status
            """
        ),
        {
            "name": clean_name,
            "mcr": normalised_mcr,
            "home_cluster": home_cluster,
            "current_nhg_posting_code": current_nhg_posting_code,
        },
    )
    resident = dict(resident_insert.mappings().one())

    posting_insert = await db.execute(
        text(
            """
            INSERT INTO external_resident_postings (
                external_resident_id,
                posting_code,
                start_date,
                end_date,
                is_current
            )
            VALUES (
                :external_resident_id,
                :posting_code,
                :start_date,
                NULL,
                true
            )
            RETURNING id, external_resident_id, posting_code, start_date, end_date, is_current
            """
        ),
        {
            "external_resident_id": str(resident["id"]),
            "posting_code": current_nhg_posting_code,
            "start_date": today,
        },
    )
    posting = dict(posting_insert.mappings().one())

    await db.commit()
    return {
        "resident": resident,
        "posting_history": posting,
    }


async def update_my_posting(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    current_nhg_posting_code: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    resident = await _external_resident_or_unauthorized(db, external_resident_id)

    if not await _posting_exists(db, current_nhg_posting_code):
        raise ApiError(
            status_code=422,
            detail="current_nhg_posting_code is not valid",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    if resident["current_nhg_posting_code"] == current_nhg_posting_code:
        return {
            "resident": resident,
            "changed": False,
        }

    await db.execute(
        text(
            """
            UPDATE external_resident_postings
            SET end_date = :end_date,
                is_current = false
            WHERE external_resident_id = :external_resident_id
              AND is_current = true
              AND end_date IS NULL
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "end_date": today,
        },
    )

    posting_insert = await db.execute(
        text(
            """
            INSERT INTO external_resident_postings (
                external_resident_id,
                posting_code,
                start_date,
                end_date,
                is_current
            )
            VALUES (
                :external_resident_id,
                :posting_code,
                :start_date,
                NULL,
                true
            )
            RETURNING id, external_resident_id, posting_code, start_date, end_date, is_current
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "posting_code": current_nhg_posting_code,
            "start_date": today,
        },
    )
    posting_row = dict(posting_insert.mappings().one())

    resident_update = await db.execute(
        text(
            """
            UPDATE external_residents
            SET current_nhg_posting_code = :posting_code
            WHERE id = :external_resident_id
            RETURNING id, name, mcr, home_cluster, current_nhg_posting_code, status
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "posting_code": current_nhg_posting_code,
        },
    )
    updated_resident = dict(resident_update.mappings().one())
    await db.commit()
    return {
        "resident": updated_resident,
        "posting_history": posting_row,
        "changed": True,
    }
