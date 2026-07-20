from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


MAPPING_PENDING_DETAIL = "Posting configuration for this programme is pending."
MAPPING_INACTIVE_DETAIL = "Posting configuration for this programme is unavailable."
MAPPING_MISSING_DETAIL = (
    "No posting configuration is available for this programme and institution."
)
MAPPING_INVALID_DETAIL = "Posting configuration is invalid. Contact an administrator."


@dataclass(slots=True)
class PostingMappingUnavailableError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def normalise_mapping_code(raw_value: str, *, field_name: str) -> str:
    value = raw_value.strip().upper()
    if not value:
        raise PostingMappingUnavailableError(f"{field_name} is required")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PostingMappingUnavailableError(
            f"{field_name} contains invalid control characters"
        )
    return value


async def list_registration_options(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            /* programme_institution_posting_options */
            SELECT p.code AS programme_code,
                   p.name AS programme_name,
                   mapping.institution_code,
                   mapping.status,
                   mapping.posting_code,
                   resolved_posting.code AS resolved_posting_code,
                   mapping.display_order
            FROM programme_institution_posting_map mapping
            JOIN programmes p
              ON p.code = mapping.programme_code
            LEFT JOIN posting_codes resolved_posting
              ON resolved_posting.code = mapping.posting_code
            WHERE mapping.status IN ('pending', 'active')
            ORDER BY mapping.display_order,
                     p.code,
                     mapping.institution_code
            """
        )
    )

    institution_codes: set[str] = set()
    programmes: dict[str, dict[str, Any]] = {}
    for row in result.mappings().all():
        institution_code = str(row["institution_code"])
        institution_codes.add(institution_code)
        programme_code = str(row["programme_code"])
        programme = programmes.setdefault(
            programme_code,
            {
                "programme_code": programme_code,
                "programme_name": str(row["programme_name"]),
                "institutions": [],
            },
        )
        status = str(row["status"])
        programme["institutions"].append(
            {
                "institution_code": institution_code,
                "available": bool(
                    status == "active"
                    and row["posting_code"] is not None
                    and row["resolved_posting_code"] is not None
                ),
                "status": status,
            }
        )

    return {
        "institutions": [
            {"code": institution_code, "name": institution_code}
            for institution_code in sorted(institution_codes)
        ],
        "programmes": list(programmes.values()),
    }


async def resolve_programme_institution_posting(
    db: AsyncSession,
    *,
    programme_code: str,
    institution_code: str,
) -> str:
    normalised_programme = normalise_mapping_code(
        programme_code,
        field_name="programme_code",
    )
    normalised_institution = normalise_mapping_code(
        institution_code,
        field_name="institution_code",
    )
    result = await db.execute(
        text(
            """
            /* programme_institution_posting_resolve */
            SELECT mapping.status,
                   mapping.posting_code,
                   p.code AS resolved_programme_code,
                   resolved_posting.code AS resolved_posting_code
            FROM programme_institution_posting_map mapping
            LEFT JOIN programmes p
              ON p.code = mapping.programme_code
            LEFT JOIN posting_codes resolved_posting
              ON resolved_posting.code = mapping.posting_code
            WHERE mapping.programme_code = :programme_code
              AND mapping.institution_code = :institution_code
            """
        ),
        {
            "programme_code": normalised_programme,
            "institution_code": normalised_institution,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise PostingMappingUnavailableError(MAPPING_MISSING_DETAIL)
    if row["status"] == "pending":
        raise PostingMappingUnavailableError(MAPPING_PENDING_DETAIL)
    if row["status"] == "inactive":
        raise PostingMappingUnavailableError(MAPPING_INACTIVE_DETAIL)
    if (
        row["status"] != "active"
        or row["posting_code"] is None
        or row["resolved_programme_code"] is None
        or row["resolved_posting_code"] is None
    ):
        raise PostingMappingUnavailableError(MAPPING_INVALID_DETAIL)
    return str(row["resolved_posting_code"])
