from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services import programme_institution_posting


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


async def list_registration_options(db: AsyncSession) -> dict[str, Any]:
    return await programme_institution_posting.list_registration_options(db)


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


def _schedule_validation_error(detail: str) -> ApiError:
    return ApiError(
        status_code=422,
        detail=detail,
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


async def _validate_posting_schedule(
    db: AsyncSession,
    posting_schedule: list[Any],
) -> list[dict[str, Any]]:
    if not posting_schedule:
        raise _schedule_validation_error("posting_schedule must contain at least one row")

    normalised: list[dict[str, Any]] = []
    for row in posting_schedule:
        start_date = row.start_date if hasattr(row, "start_date") else row["start_date"]
        end_date = row.end_date if hasattr(row, "end_date") else row["end_date"]
        programme_code = (
            row.programme_code if hasattr(row, "programme_code") else row["programme_code"]
        )
        institution = row.institution if hasattr(row, "institution") else row["institution"]

        if start_date > end_date:
            raise _schedule_validation_error("posting_schedule start_date must be on or before end_date")
        try:
            programme_code = programme_institution_posting.normalise_mapping_code(
                programme_code,
                field_name="programme_code",
            )
            institution = programme_institution_posting.normalise_mapping_code(
                institution,
                field_name="institution_code",
            )
            posting_code = (
                await programme_institution_posting.resolve_programme_institution_posting(
                    db,
                    programme_code=programme_code,
                    institution_code=institution,
                )
            )
        except programme_institution_posting.PostingMappingUnavailableError as exc:
            raise _schedule_validation_error(exc.detail) from exc

        normalised.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "programme_code": programme_code,
                "institution": institution,
                "posting_code": posting_code,
            }
        )

    normalised.sort(key=lambda item: (item["start_date"], item["end_date"], item["posting_code"]))
    previous: dict[str, Any] | None = None
    for row in normalised:
        if previous is not None and row["start_date"] <= previous["end_date"]:
            raise _schedule_validation_error("posting_schedule rows must not overlap")
        previous = row
    return normalised


def _current_schedule_index(
    posting_schedule: list[dict[str, Any]],
    today: date,
) -> int:
    for index, row in enumerate(posting_schedule):
        if row["start_date"] <= today <= row["end_date"]:
            return index

    future_rows = [
        (index, row)
        for index, row in enumerate(posting_schedule)
        if row["start_date"] > today
    ]
    if future_rows:
        return min(future_rows, key=lambda item: item[1]["start_date"])[0]

    return max(
        enumerate(posting_schedule),
        key=lambda item: item[1]["end_date"],
    )[0]


async def _insert_schedule_rows(
    db: AsyncSession,
    *,
    external_resident_id: UUID | str,
    posting_schedule: list[dict[str, Any]],
    current_schedule_index: int,
) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    for index, row in enumerate(posting_schedule):
        is_current = index == current_schedule_index
        posting_insert = await db.execute(
            text(
                """
                INSERT INTO external_resident_postings (
                    external_resident_id,
                    posting_code,
                    programme_code,
                    start_date,
                    end_date,
                    is_current
                )
                VALUES (
                    :external_resident_id,
                    :posting_code,
                    :programme_code,
                    :start_date,
                    :end_date,
                    :is_current
                )
                RETURNING id, external_resident_id, posting_code, programme_code,
                          start_date, end_date, is_current
                """
            ),
            {
                "external_resident_id": str(external_resident_id),
                "posting_code": row["posting_code"],
                "programme_code": row["programme_code"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "is_current": is_current,
            },
        )
        inserted.append(dict(posting_insert.mappings().one()))
    return inserted


async def _insert_current_schedule_row(
    db: AsyncSession,
    *,
    external_resident_id: UUID | str,
    posting_code: str,
    programme_code: str,
    start_date: date,
    end_date: date | None = None,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            INSERT INTO external_resident_postings (
                external_resident_id,
                posting_code,
                programme_code,
                start_date,
                end_date,
                is_current
            )
            VALUES (
                :external_resident_id,
                :posting_code,
                :programme_code,
                :start_date,
                :end_date,
                true
            )
            RETURNING id, external_resident_id, posting_code, programme_code,
                      start_date, end_date, is_current
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "posting_code": posting_code,
            "programme_code": programme_code,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    return dict(result.mappings().one())


async def register_external_resident(
    db: AsyncSession,
    *,
    name: str,
    mcr: str,
    home_cluster: str,
    posting_schedule: list[Any],
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

    normalised_schedule = await _validate_posting_schedule(db, posting_schedule)
    current_schedule_index = _current_schedule_index(
        normalised_schedule,
        today,
    )
    current_nhg_posting_code = normalised_schedule[current_schedule_index]["posting_code"]

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

    schedule_rows = await _insert_schedule_rows(
        db,
        external_resident_id=resident["id"],
        posting_schedule=normalised_schedule,
        current_schedule_index=current_schedule_index,
    )
    posting = schedule_rows[current_schedule_index]

    await db.commit()
    response = {
        "resident": resident,
        "posting_history": posting,
    }
    response["posting_schedule"] = schedule_rows
    return response


async def update_my_posting(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    programme_code: str,
    institution: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    resident = await _external_resident_or_unauthorized(db, external_resident_id)

    try:
        normalised_programme_code = (
            programme_institution_posting.normalise_mapping_code(
                programme_code,
                field_name="programme_code",
            )
        )
        normalised_institution = programme_institution_posting.normalise_mapping_code(
            institution,
            field_name="institution_code",
        )
        current_nhg_posting_code = (
            await programme_institution_posting.resolve_programme_institution_posting(
                db,
                programme_code=normalised_programme_code,
                institution_code=normalised_institution,
            )
        )
    except programme_institution_posting.PostingMappingUnavailableError as exc:
        raise _schedule_validation_error(exc.detail) from exc

    current_result = await db.execute(
        text(
            """
            SELECT id, external_resident_id, posting_code, programme_code,
                   start_date, end_date, is_current
            FROM external_resident_postings
            WHERE external_resident_id = :external_resident_id
              AND is_current = true
            """
        ),
        {"external_resident_id": str(external_resident_id)},
    )
    current_posting = current_result.mappings().one_or_none()
    if (
        current_posting is not None
        and current_posting["posting_code"] == current_nhg_posting_code
        and current_posting["programme_code"] == normalised_programme_code
    ):
        return {
            "resident": resident,
            "changed": False,
        }

    if current_posting is not None and current_posting["start_date"] >= today:
        posting_update = await db.execute(
            text(
                """
                UPDATE external_resident_postings
                SET posting_code = :posting_code,
                    programme_code = :programme_code
                WHERE id = :posting_id
                RETURNING id, external_resident_id, posting_code, programme_code,
                          start_date, end_date, is_current
                """
            ),
            {
                "posting_id": str(current_posting["id"]),
                "posting_code": current_nhg_posting_code,
                "programme_code": normalised_programme_code,
            },
        )
        posting_row = dict(posting_update.mappings().one())
    else:
        replacement_end_date: date | None = None
        if current_posting is not None:
            previous_end_date = min(
                current_posting["end_date"] or today,
                today - timedelta(days=1),
            )
            if (
                current_posting["end_date"] is not None
                and current_posting["end_date"] >= today
            ):
                replacement_end_date = current_posting["end_date"]
            await db.execute(
                text(
                    """
                    UPDATE external_resident_postings
                    SET end_date = :end_date,
                        is_current = false
                    WHERE id = :posting_id
                    """
                ),
                {
                    "posting_id": str(current_posting["id"]),
                    "end_date": previous_end_date,
                },
            )

        future_result = await db.execute(
            text(
                """
                SELECT id, start_date
                FROM external_resident_postings
                WHERE external_resident_id = :external_resident_id
                  AND start_date > :today
                ORDER BY start_date ASC, id ASC
                """
            ),
            {
                "external_resident_id": str(external_resident_id),
                "today": today,
            },
        )
        current_posting_id = (
            str(current_posting["id"]) if current_posting is not None else None
        )
        next_future_start = next(
            (
                row["start_date"]
                for row in future_result.mappings().all()
                if str(row["id"]) != current_posting_id
            ),
            None,
        )
        if next_future_start is not None:
            next_future_boundary = next_future_start - timedelta(days=1)
            replacement_end_date = min(
                replacement_end_date or next_future_boundary,
                next_future_boundary,
            )

        posting_row = await _insert_current_schedule_row(
            db,
            external_resident_id=external_resident_id,
            posting_code=current_nhg_posting_code,
            programme_code=normalised_programme_code,
            start_date=today,
            end_date=replacement_end_date,
        )

    if resident["current_nhg_posting_code"] == current_nhg_posting_code:
        updated_resident = resident
    else:
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


async def replace_my_posting_schedule(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    posting_schedule: list[Any],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    await _external_resident_or_unauthorized(db, external_resident_id)
    normalised_schedule = await _validate_posting_schedule(db, posting_schedule)
    current_schedule_index = _current_schedule_index(normalised_schedule, today)
    current_nhg_posting_code = normalised_schedule[current_schedule_index]["posting_code"]

    await db.execute(
        text(
            """
            DELETE FROM external_resident_postings
            WHERE external_resident_id = :external_resident_id
            """
        ),
        {"external_resident_id": str(external_resident_id)},
    )
    schedule_rows = await _insert_schedule_rows(
        db,
        external_resident_id=external_resident_id,
        posting_schedule=normalised_schedule,
        current_schedule_index=current_schedule_index,
    )
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
        "posting_schedule": schedule_rows,
        "changed": True,
    }
