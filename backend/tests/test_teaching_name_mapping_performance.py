from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.services import teaching_name_mappings


class _MappingRows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingRows:
        return _MappingRows(self._rows)


class _Session:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.calls.append((str(statement), dict(params or {})))
        return _Result(self.rows)


def _mapping_scope(
    reporting_period_id: UUID,
    *,
    posting_code: str,
) -> dict:
    return {
        "reporting_period_id": reporting_period_id,
        "programme_code": "GERI",
        "posting_code": posting_code,
        "r_year": "R4",
    }


def _target(
    reporting_period_id: UUID,
    *,
    posting_code: str,
    target_id: UUID,
) -> dict:
    return {
        "id": target_id,
        "session_type_id": UUID("00000000-0000-0000-0000-000000000099"),
        "session_type_name": "Department Teaching [1h]",
        "duration_hours": Decimal("1"),
        "monthly_target": Decimal("2"),
        "is_tracked": True,
        "is_reallocatable": False,
        "tag": None,
        "reporting_period_id": reporting_period_id,
        "programme_code": "GERI",
        "posting_code": posting_code,
        "r_year": "R4",
    }


@pytest.mark.asyncio
async def test_target_options_for_mapping_page_are_loaded_once_per_page() -> None:
    reporting_period_id = UUID("00000000-0000-0000-0000-000000000001")
    session = _Session(
        [
            _target(
                reporting_period_id,
                posting_code="TTSHGerMed",
                target_id=UUID("00000000-0000-0000-0000-000000000011"),
            ),
            _target(
                reporting_period_id,
                posting_code="CGHGerMed",
                target_id=UUID("00000000-0000-0000-0000-000000000012"),
            ),
        ]
    )
    mapping_rows = [
        _mapping_scope(reporting_period_id, posting_code="TTSHGerMed"),
        _mapping_scope(reporting_period_id, posting_code="TTSHGerMed"),
        _mapping_scope(reporting_period_id, posting_code="CGHGerMed"),
    ]

    options = await teaching_name_mappings._target_options_by_scope(
        session,  # type: ignore[arg-type]
        rows=mapping_rows,
    )

    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "requested_scopes" in sql
    assert len(params["reporting_period_ids"]) == 2
    scope = (str(reporting_period_id), "GERI", "TTSHGerMed", "R4")
    assert [option["id"] for option in options[scope]] == [
        UUID("00000000-0000-0000-0000-000000000011")
    ]


@pytest.mark.asyncio
async def test_target_options_for_empty_mapping_page_skip_database() -> None:
    session = _Session([])

    options = await teaching_name_mappings._target_options_by_scope(
        session,  # type: ignore[arg-type]
        rows=[],
    )

    assert options == {}
    assert session.calls == []
