"""seed external-registration posting-code prerequisites

Revision ID: 20260721_000020
Revises: 20260717_000019
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision = "20260721_000020"
down_revision = "20260717_000019"
branch_labels = None
depends_on = None


POSTING_CODE_ROWS = (
    ("752081a5-51ce-5d5a-8049-b77f1a98a160", "NSCDermat"),
    ("ae6edcd5-b5ac-5ed1-a723-a68fdcc90e05", "TTSHGenSrg"),
    ("6ac7d953-4db4-58a2-aec5-81e490ee1365", "TTSHInfect"),
    ("f4561637-68c1-581b-b48a-8469f8a69b7f", "TTSHMedOnc"),
    ("85fc721e-68db-5c8a-953c-cbcf5da11297", "TTSHOrtSrg"),
    ("9fb9712f-3d85-50d2-a12b-79f0ded243d9", "TTSHRehabi"),
    ("56bb8cf2-eae0-5a16-bb64-2d2321fd9cad", "TTSHRenal"),
    ("fd559e99-0b30-5d25-a287-572f37befe98", "TTSHRespir"),
    ("e6a4e9c0-679f-53b8-9561-bfdfdb13f99e", "TTSHRheuma"),
    ("48e7fb87-77e1-51da-ba76-2b562d654b2c", "TTSHUrolog"),
)


def _validate_configuration() -> tuple[tuple[UUID, str], ...]:
    if len(POSTING_CODE_ROWS) != 10:
        raise RuntimeError("Posting-code prerequisite seed must contain exactly 10 rows")

    parsed_rows: list[tuple[UUID, str]] = []
    for raw_id, code in POSTING_CODE_ROWS:
        if not code or code != code.strip():
            raise RuntimeError("Posting-code prerequisite seed contains a blank value")
        try:
            parsed_id = UUID(raw_id)
        except (TypeError, ValueError, AttributeError) as error:
            raise RuntimeError(
                f"Posting-code prerequisite seed has an invalid UUID for {code}"
            ) from error
        if str(parsed_id) != raw_id:
            raise RuntimeError(
                f"Posting-code prerequisite UUID is not canonical for {code}"
            )
        parsed_rows.append((parsed_id, code))

    ids = [row_id for row_id, _code in parsed_rows]
    codes = [code for _row_id, code in parsed_rows]
    if len(set(ids)) != 10:
        raise RuntimeError("Posting-code prerequisite UUIDs must be unique")
    if len(set(codes)) != 10:
        raise RuntimeError("Posting-code prerequisite codes must be unique")
    return tuple(parsed_rows)


def _load_posting_code_rows(connection: Any) -> list[Mapping[str, Any]]:
    return list(
        connection.execute(
            sa.text(
                """
                SELECT id,
                       code,
                       display_name,
                       institution,
                       department,
                       billing_dept,
                       is_emergency,
                       supports_secretary_events,
                       created_at,
                       updated_at
                FROM posting_codes
                ORDER BY code, id
                """
            )
        )
        .mappings()
        .all()
    )


def _row_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["id"],
        row["code"],
        row["display_name"],
        row["institution"],
        row["department"],
        row["billing_dept"],
        row["is_emergency"],
        row["supports_secretary_events"],
        row["created_at"],
        row["updated_at"],
    )


def _rows_by_id(
    rows: list[Mapping[str, Any]],
) -> dict[UUID, tuple[Any, ...]]:
    return {UUID(str(row["id"])): _row_signature(row) for row in rows}


def _validate_existing_rows_unchanged(
    before: list[Mapping[str, Any]],
    after: list[Mapping[str, Any]],
) -> None:
    before_by_id = _rows_by_id(before)
    after_by_id = _rows_by_id(after)
    for row_id, signature in before_by_id.items():
        if after_by_id.get(row_id) != signature:
            raise RuntimeError("Posting-code prerequisite migration changed an existing row")


def _upgrade(connection: Any) -> None:
    configured_rows = _validate_configuration()
    expected_code_by_id = {row_id: code for row_id, code in configured_rows}
    expected_id_by_code = {code: row_id for row_id, code in configured_rows}
    before = _load_posting_code_rows(connection)

    existing_by_code: dict[str, Mapping[str, Any]] = {}
    for row in before:
        row_id = UUID(str(row["id"]))
        code = str(row["code"])
        expected_code = expected_code_by_id.get(row_id)
        if expected_code is not None and code != expected_code:
            raise RuntimeError(
                f"Deterministic posting-code UUID collision: {row_id} is used by {code}"
            )
        if code in expected_id_by_code:
            if code in existing_by_code:
                raise RuntimeError(f"Duplicate prerequisite posting code exists: {code}")
            existing_by_code[code] = row

    missing_rows = [
        (row_id, code)
        for row_id, code in configured_rows
        if code not in existing_by_code
    ]
    insert_statement = sa.text(
        """
        INSERT INTO posting_codes (id, code)
        VALUES (:row_id, :code)
        """
    )
    for row_id, code in missing_rows:
        result = connection.execute(
            insert_statement,
            {"row_id": row_id, "code": code},
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Posting-code prerequisite insert failed for {code}")

    after = _load_posting_code_rows(connection)
    _validate_existing_rows_unchanged(before, after)
    if len(after) != len(before) + len(missing_rows):
        raise RuntimeError("Posting-code prerequisite row-count verification failed")

    after_by_code = {str(row["code"]): row for row in after}
    if not set(expected_id_by_code).issubset(after_by_code):
        raise RuntimeError("Not all posting-code prerequisites exist after upgrade")
    missing_codes = {code for _row_id, code in missing_rows}
    for code in missing_codes:
        row = after_by_code[code]
        if UUID(str(row["id"])) != expected_id_by_code[code]:
            raise RuntimeError(f"Migration-owned UUID verification failed for {code}")
        if (
            row["display_name"] is not None
            or row["institution"] is not None
            or row["department"] is not None
            or row["billing_dept"] is not None
            or row["is_emergency"] is not False
            or row["supports_secretary_events"] is not False
            or row["created_at"] is None
            or row["updated_at"] is None
        ):
            raise RuntimeError(f"Posting-code defaults verification failed for {code}")


def upgrade() -> None:
    _upgrade(op.get_bind())


def _downgrade(connection: Any) -> None:
    configured_rows = _validate_configuration()
    owned_pairs = {(row_id, code) for row_id, code in configured_rows}
    before = _load_posting_code_rows(connection)
    protected_before = [
        row
        for row in before
        if (UUID(str(row["id"])), str(row["code"])) not in owned_pairs
    ]
    owned_before_count = len(before) - len(protected_before)

    delete_statement = sa.text(
        """
        DELETE FROM posting_codes
        WHERE id = :row_id
          AND code = :code
        """
    )
    for row_id, code in configured_rows:
        result = connection.execute(
            delete_statement,
            {"row_id": row_id, "code": code},
        )
        if result.rowcount not in {0, 1}:
            raise RuntimeError(f"Posting-code prerequisite delete failed for {code}")

    after = _load_posting_code_rows(connection)
    _validate_existing_rows_unchanged(protected_before, after)
    if len(after) != len(before) - owned_before_count:
        raise RuntimeError("Posting-code prerequisite downgrade row-count verification failed")
    remaining_pairs = {
        (UUID(str(row["id"])), str(row["code"])) for row in after
    }
    if owned_pairs & remaining_pairs:
        raise RuntimeError("Migration-owned posting-code rows remain after downgrade")


def downgrade() -> None:
    _downgrade(op.get_bind())
