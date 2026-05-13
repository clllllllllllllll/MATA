from __future__ import annotations

import asyncio
import json
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.routers import admin
from app.services.rdb_parser import parse_rdb_upload


class _FakeScalarResult:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar(self) -> object:
        return self._value

    def mappings(self) -> "_FakeScalarResult":
        return self

    def all(self) -> list[dict]:
        return []


class _FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def scalar(self) -> object:
        if not self._rows:
            return None
        first = self._rows[0]
        return next(iter(first.values()))


class FakeRDBSession:
    def __init__(self) -> None:
        self.programmes: list[dict] = [
            {
                "code": "ANAES",
                "name": "Anaesthesiology",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "AIM",
                "name": "Advanced Internal Medicine",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "CARDIO",
                "name": "Cardiology",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "DERM",
                "name": "Dermatology",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "DR",
                "name": "Diagnostic Radiology",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "EM",
                "name": "Emergency Medicine",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "ENDO",
                "name": "Endocrinology",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "FM",
                "name": "Family Medicine",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "GASTRO",
                "name": "Gastroenterology",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "GERI",
                "name": "Geriatric Medicine",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
            },
            {
                "code": "ID",
                "name": "Infectious Diseases",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": "Infectious Disease",
            },
            {
                "code": "MICROB",
                "name": "Pathology (Microbiology)",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": "Microbiology",
            },
            {
                "code": "PALLMED",
                "name": "Palliative Medicine",
                "r_year_required": False,
                "is_subspecialty": True,
                "rdb_alias": None,
            },
            {
                "code": "RENAL",
                "name": "Renal Medicine",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": "Renal Medicine Extended",
            },
            {
                "code": "SIG",
                "name": "Surgery-In-General",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": "Surgery-in-General",
            },
            {
                "code": "SPORT",
                "name": "Sports Test",
                "r_year_required": True,
                "is_subspecialty": True,
                "rdb_alias": None,
            },
            {
                "code": "SPORTSMED",
                "name": "Sports Medicine",
                "r_year_required": False,
                "is_subspecialty": True,
                "rdb_alias": None,
            },
        ]
        self.loa_types = [
            {"code": "Maternity Leave"},
            {"code": "Annual Leaves"},
            {"code": "No-Pay-Leave"},
            {"code": "Family Care Leave"},
            {"code": "Hospitalisation Leave"},
            {"code": "Medical Leave"},
            {"code": "Training Leave"},
            {"code": "National Service (NS)"},
            {"code": "Paternity Leave"},
        ]
        self.multi_posting_rules: list[dict] = []
        self.posting_codes: set[str] = set()
        self.residents: dict[str, dict] = {}
        self.resident_postings: list[dict] = []
        self.upload_logs: list[dict] = []
        self.surplus_ledger: list[dict] = []
        self.commits = 0
        self.rollbacks = 0
        self.hibernate_calls = 0

    async def execute(self, statement, params: dict | None = None):
        sql = str(statement)
        params = dict(params or {})

        if "FROM programmes" in sql:
            return _FakeMappingResult(self.programmes)

        if "FROM loa_types" in sql:
            return _FakeMappingResult(self.loa_types)

        if "FROM multi_posting_rules" in sql:
            programme_code = params["programme_code"]
            return _FakeMappingResult(
                [
                    rule
                    for rule in self.multi_posting_rules
                    if rule["programme_code"] == programme_code
                ]
            )

        if "SELECT mcr" in sql and "FROM residents" in sql:
            mcrs = set(params["mcrs"])
            return _FakeMappingResult(
                [
                    {
                        "id": resident["id"],
                        "mcr": resident["mcr"],
                    }
                    for resident in self.residents.values()
                    if resident["mcr"] in mcrs
                ]
            )

        if "SELECT code" in sql and "FROM posting_codes" in sql:
            codes = set(params["codes"])
            return _FakeMappingResult(
                [{"code": code} for code in sorted(self.posting_codes & codes)]
            )

        if "INSERT INTO posting_codes" in sql:
            self.posting_codes.add(params["code"])
            return _FakeScalarResult()

        if "INSERT INTO residents" in sql:
            resident_id = uuid4()
            row = dict(params)
            row["id"] = resident_id
            self.residents[row["mcr"]] = row
            return _FakeScalarResult(resident_id)

        if "UPDATE residents" in sql:
            resident = self.residents[params["mcr"]]
            resident.update(params)
            return _FakeScalarResult(resident["id"])

        if "DELETE FROM resident_postings" in sql:
            period_id = str(params["reporting_period_id"])
            self.resident_postings = [
                row
                for row in self.resident_postings
                if str(row["reporting_period_id"]) != period_id
            ]
            return _FakeScalarResult()

        if "INSERT INTO resident_postings" in sql:
            key = (
                params["resident_id"],
                str(params["reporting_period_id"]),
                params["start_date"],
                params.get("day_part"),
            )
            existing_keys = {
                (
                    row["resident_id"],
                    str(row["reporting_period_id"]),
                    row["start_date"],
                    row.get("day_part"),
                )
                for row in self.resident_postings
            }
            if key in existing_keys:
                raise AssertionError(f"duplicate resident_postings insert attempted: {key}")
            self.resident_postings.append(dict(params))
            return _FakeScalarResult()

        if "UPDATE surplus_ledger" in sql:
            self.hibernate_calls += 1
            period_id = str(params["period_id"])
            active_pairs = {
                (row["resident_id"], row["posting_code"])
                for row in self.resident_postings
                if str(row["reporting_period_id"]) == period_id
                and row["status"] in {"active", "loa_working"}
            }
            for row in self.surplus_ledger:
                if (
                    str(row["reporting_period_id"]) == period_id
                    and not row["is_hibernating"]
                    and (row["resident_id"], row["posting_code"]) not in active_pairs
                ):
                    row["is_hibernating"] = True
            return _FakeScalarResult()

        if "INSERT INTO upload_logs" in sql:
            self.upload_logs.append(dict(params))
            return _FakeScalarResult()

        raise AssertionError(f"Unhandled SQL in fake session: {sql}")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _xlsx(rows: list[list[object]], *, sheet_name: str = "Phase 1") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for row_index, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=column_index, value=value)

    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


def _rdb_workbook(data_rows: list[list[object]], *, sheet_name: str = "Phase 1") -> bytes:
    return _xlsx(
        [
            ["", "", "", "", "", "", "", "", "Jul-25", "Aug-25", "Sep-25"],
            [
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "08 Jul 25 - 03 Aug 25",
                "04 Aug 25 - 31 Aug 25",
                "01 Sep 25 - 30 Sep 25",
            ],
            *data_rows,
        ],
        sheet_name=sheet_name,
    )


def _rdb_workbook_with_months(
    data_rows: list[list[object]],
    *,
    month_labels: list[str],
    date_ranges: list[str],
    sheet_name: str = "Phase 1",
) -> bytes:
    return _xlsx(
        [
            ["", "", "", "", "", "", "", "", *month_labels],
            ["", "", "", "", "", "", "", "", *date_ranges],
            *data_rows,
        ],
        sheet_name=sheet_name,
    )


def _resident_row(
    *,
    employee_code: str,
    name: str,
    mcr: str,
    r_year: str,
    programme: str,
    jul: object = "",
    aug: object = "",
    sep: object = "",
) -> list[object]:
    return [
        employee_code,
        name,
        mcr,
        "Junior Resident",
        "TTSH",
        r_year,
        programme,
        "Full",
        jul,
        aug,
        sep,
    ]


def _run(coro):
    return asyncio.run(coro)


def _sample_workbook_bytes(*candidate_names: str) -> bytes:
    search_dirs = [
        Path(__file__).parent / "data",
        Path("C:/tmp/mata-samples"),
    ]
    read_errors: list[str] = []
    for directory in search_dirs:
        for candidate_name in candidate_names:
            path = directory / candidate_name
            if not path.exists():
                continue
            try:
                return path.read_bytes()
            except OSError as exc:
                read_errors.append(f"{path}: {exc}")
    pytest.skip(
        "Sample workbook is unavailable or unreadable. "
        + ("; ".join(read_errors) if read_errors else ", ".join(candidate_names))
    )


def _unmatched_multi_posting_warnings(result) -> list[dict]:
    return [
        item
        for item in result.warnings
        if isinstance(item, dict) and item.get("type") == "unmatched_multi_posting"
    ]


def _distinct_warning_posting_codes(warning: dict) -> list[str]:
    posting_codes = warning.get("posting_codes")
    if not isinstance(posting_codes, list):
        return []
    distinct_codes: list[str] = []
    for code in posting_codes:
        if isinstance(code, str) and code and code not in distinct_codes:
            distinct_codes.append(code)
    return distinct_codes


def _assert_unmatched_warning_trace_fields(
    warning: dict,
    *,
    mcr: str,
    resident_name: str,
    programme_code: str,
    month_label: str,
    sheet_name: str,
    row_number: int,
    cell_ref: str,
) -> None:
    assert warning.get("type") == "unmatched_multi_posting"
    assert warning.get("mcr") == mcr
    assert warning.get("resident_name") == resident_name
    assert warning.get("programme_code") == programme_code
    assert warning.get("month_label") == month_label
    assert warning.get("sheet_name") == sheet_name
    assert warning.get("row_number") == row_number
    assert warning.get("cell_ref") == cell_ref
    assert isinstance(warning.get("posting_codes"), list)
    assert warning.get("message")


def test_sample_upload_creates_residents_postings_posting_codes_and_upload_log() -> None:
    session = FakeRDBSession()
    user_id = uuid4()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            )
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["residents_created"] == 1
    assert result.metadata["postings_created"] == 1
    assert session.residents["M12345A"]["programme_code"] == "DR"
    assert session.resident_postings[0]["posting_code"] == "TTSHAnaes"
    assert session.resident_postings[0]["day_part"] is None
    assert session.resident_postings[0]["r_year"] == "R2"
    assert all(row["r_year"] for row in session.resident_postings)
    assert "TTSHAnaes" in session.posting_codes

    app = FastAPI()
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    client = TestClient(app)
    response = client.post(
        "/admin/upload/rdb",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(user_id),
            "X-User-Programme": "DR",
        },
        data={"reporting_period_id": str(period_id)},
        files={
            "file": (
                "audit-name.xlsx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["residents_updated"] == 1
    assert body["postings_created"] == 1
    assert session.upload_logs[-1]["upload_type"] == "rdb"
    assert session.upload_logs[-1]["uploaded_by"] == str(user_id)
    assert (
        json.loads(session.upload_logs[-1]["summary"])["original_filename"]
        == "audit-name.xlsx"
    )


def test_reupload_delete_first_replaces_entire_reporting_period_snapshot() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    first_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            ),
            _resident_row(
                employee_code="E002",
                name="Resident Two",
                mcr="M54321B",
                r_year="R3",
                programme="DR",
                jul="KTPHDiagRd",
            ),
        ]
    )
    second_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One Updated",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="SGHDiagRd",
            ),
        ]
    )

    _run(
        parse_rdb_upload(
            file_bytes=first_file,
            original_filename="first.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )
    _run(
        parse_rdb_upload(
            file_bytes=second_file,
            original_filename="second.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    one_id = session.residents["M12345A"]["id"]
    one_rows = [row for row in session.resident_postings if row["resident_id"] == one_id]

    assert [row["posting_code"] for row in one_rows] == ["SGHDiagRd"]
    assert len(session.resident_postings) == 1
    assert "M54321B" in session.residents
    assert session.residents["M12345A"]["name"] == "Resident One Updated"


def test_reupload_does_not_delete_resident_postings_from_other_reporting_periods() -> None:
    session = FakeRDBSession()
    first_period_id = uuid4()
    second_period_id = uuid4()

    first_period_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            )
        ]
    )
    second_period_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="KTPHDiagRd",
            )
        ]
    )
    replacement_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One Updated",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="SGHDiagRd",
            )
        ]
    )

    _run(
        parse_rdb_upload(
            file_bytes=first_period_file,
            original_filename="first-period.xlsx",
            reporting_period_id=first_period_id,
            db_session=session,
        )
    )
    _run(
        parse_rdb_upload(
            file_bytes=second_period_file,
            original_filename="second-period.xlsx",
            reporting_period_id=second_period_id,
            db_session=session,
        )
    )
    _run(
        parse_rdb_upload(
            file_bytes=replacement_file,
            original_filename="first-period-reupload.xlsx",
            reporting_period_id=first_period_id,
            db_session=session,
        )
    )

    first_period_rows = [
        row
        for row in session.resident_postings
        if str(row["reporting_period_id"]) == str(first_period_id)
    ]
    second_period_rows = [
        row
        for row in session.resident_postings
        if str(row["reporting_period_id"]) == str(second_period_id)
    ]
    assert [row["posting_code"] for row in first_period_rows] == ["SGHDiagRd"]
    assert [row["posting_code"] for row in second_period_rows] == ["KTPHDiagRd"]


def test_reupload_validation_error_keeps_existing_resident_postings_for_period() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    first_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            )
        ]
    )
    invalid_second_file = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="UNKNOWN_PROGRAMME",
                jul="SGHDiagRd",
            )
        ]
    )

    first_result = _run(
        parse_rdb_upload(
            file_bytes=first_file,
            original_filename="first.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )
    assert first_result.errors == []
    before_rows = list(session.resident_postings)

    second_result = _run(
        parse_rdb_upload(
            file_bytes=invalid_second_file,
            original_filename="second-invalid.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert second_result.errors != []
    assert "no valid resident rows" in second_result.errors[0].lower()
    assert any(
        isinstance(warning, dict) and warning.get("type") == "unknown_programme"
        for warning in second_result.warnings
    )
    assert session.resident_postings == before_rows


def test_programme_alias_r_year_all_subspecialty_and_employed_cells() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Geri Resident",
                mcr="M11111A",
                r_year="R3",
                programme="GERI",
                jul="TTSHGerMed",
            ),
            _resident_row(
                employee_code="E002",
                name="Alias Resident",
                mcr="M22222B",
                r_year="R2",
                programme="Infectious Disease",
                jul="TTSHID",
            ),
            _resident_row(
                employee_code="E003",
                name="Subspecialty Resident",
                mcr="M33333C",
                r_year="R4",
                programme="SPORT",
                jul="SportsPost",
            ),
            _resident_row(
                employee_code="E004",
                name="Employed Resident",
                mcr="M44444D",
                r_year="R2",
                programme="DR",
                jul="SAF-Employed",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    by_mcr = {
        resident["mcr"]: resident["id"] for resident in session.residents.values()
    }
    postings_by_resident = {
        row["resident_id"]: row for row in session.resident_postings
    }

    assert postings_by_resident[by_mcr["M11111A"]]["r_year"] == "ALL"
    assert session.residents["M22222B"]["programme_code"] == "ID"
    assert postings_by_resident[by_mcr["M33333C"]]["r_year"] == "SS1"
    assert session.residents["M44444D"]["employer_tag"] == "SAF"
    assert by_mcr["M44444D"] not in postings_by_resident
    assert result.metadata["employed_residents_flagged"] == 1


def test_column_a_employed_markers_are_stored_as_null_employee_code_and_tagged_by_mcr() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="SAF-Employed",
                name="Employed One",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="SAF-Employed",
            ),
            _resident_row(
                employee_code="SAF-Employed",
                name="Employed Two",
                mcr="M22222B",
                r_year="R2",
                programme="DR",
                jul="SAF-Employed",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert "M11111A" in session.residents
    assert "M22222B" in session.residents
    assert session.residents["M11111A"]["employee_code"] is None
    assert session.residents["M22222B"]["employee_code"] is None
    assert session.residents["M11111A"]["employer_tag"] == "SAF"
    assert session.residents["M22222B"]["employer_tag"] == "SAF"
    assert session.resident_postings == []
    assert all("Employed" not in code for code in session.posting_codes)


def test_same_day_am_pm_multi_posting_does_not_generate_duplicate_phase_rows() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="47008861",
                name="Cardio Resident",
                mcr="M64225H",
                r_year="R6",
                programme="Cardiology",
                jul=(
                    "TTSHCardio\n"
                    "(from 01-Dec-2025 to 01-Dec-2025 AM)\n"
                    "(from 02-Dec-2025 to 05-Jan-2026 )\n"
                    "NHCCardio\n"
                    "(from 01-Dec-2025 to 01-Dec-2025 PM)"
                ),
            )
        ],
        month_labels=["Dec-25"],
        date_ranges=["01 Dec 25 - 05 Jan 26"],
        sheet_name="Phase 3",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="ay25-duplicate-dec.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["postings_created"] == 3
    assert {row["posting_code"] for row in session.resident_postings} == {
        "TTSHCardio",
        "NHCCardio",
    }
    assert len(session.resident_postings) == 3
    phase_keys = [
        (
            row["resident_id"],
            row["reporting_period_id"],
            row["start_date"],
            row["day_part"],
        )
        for row in session.resident_postings
    ]
    assert len(phase_keys) == len(set(phase_keys))
    assert any(
        row["posting_code"] == "TTSHCardio"
        and row["start_date"] == date(2025, 12, 1)
        and row["end_date"] == date(2025, 12, 1)
        and row["day_part"] == "AM"
        for row in session.resident_postings
    )
    assert any(
        row["posting_code"] == "NHCCardio"
        and row["start_date"] == date(2025, 12, 1)
        and row["end_date"] == date(2025, 12, 1)
        and row["day_part"] == "PM"
        for row in session.resident_postings
    )
    assert any(
        row["posting_code"] == "TTSHCardio"
        and row["start_date"] == date(2025, 12, 2)
        and row["end_date"] == date(2026, 1, 5)
        and row["day_part"] is None
        for row in session.resident_postings
    )
    assert not any(
        isinstance(item, dict)
        and item.get("type") == "same_day_multi_posting_deconflicted"
        for item in result.warnings
    )
    assert all(row["r_year"] == "ALL" for row in session.resident_postings)


def test_standard_sheet_stops_parsing_at_red_line_marker() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    marker = "Please do not insert any row beyond this red line"
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Valid Above Marker",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            ),
            [marker, "", "", "", "", "", "", "", "", "", ""],
            _resident_row(
                employee_code="E999",
                name="Legend Like Row",
                mcr="M99999Z",
                r_year="R2",
                programme="DR",
                jul="LegendPostingCode",
            ),
        ],
        sheet_name="Phase 1",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb-red-line-stop.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["rows_skipped"] == 0
    assert result.warnings == []
    assert set(session.residents.keys()) == {"M11111A"}
    assert "M99999Z" not in session.residents
    assert [row["posting_code"] for row in session.resident_postings] == ["TTSHAnaes"]
    assert "LegendPostingCode" not in session.posting_codes


def test_single_posting_explicit_date_fragments_with_am_do_not_emit_unmatched_warning() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="E001",
                name="Single Posting AM",
                mcr="M11111A",
                r_year="R2",
                programme="ANAES",
                jul=(
                    "TTSHAnaes\n"
                    "(from 04-Aug-2025 to 06-Aug-2025)\n"
                    "(from 07-Aug-2025 to 07-Aug-2025 AM)"
                ),
            )
        ],
        month_labels=["Aug-25"],
        date_ranges=["04 Aug 25 - 31 Aug 25"],
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="single-posting-am.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    rows = [row for row in session.resident_postings if row["posting_code"] == "TTSHAnaes"]
    assert len(rows) == 2
    assert any(
        row["start_date"] == date(2025, 8, 4)
        and row["end_date"] == date(2025, 8, 6)
        and row["day_part"] is None
        for row in rows
    )
    assert any(
        row["start_date"] == date(2025, 8, 7)
        and row["end_date"] == date(2025, 8, 7)
        and row["day_part"] == "AM"
        for row in rows
    )
    assert _unmatched_multi_posting_warnings(result) == []


def test_single_posting_explicit_date_fragment_with_pm_do_not_emit_unmatched_warning() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="E001",
                name="Single Posting PM",
                mcr="M11111A",
                r_year="R2",
                programme="EM",
                jul=(
                    "TTSHEmgMed\n"
                    "(from 07-Aug-2025 to 07-Aug-2025 PM)"
                ),
            )
        ],
        month_labels=["Aug-25"],
        date_ranges=["04 Aug 25 - 31 Aug 25"],
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="single-posting-pm.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert len(session.resident_postings) == 1
    row = session.resident_postings[0]
    assert row["posting_code"] == "TTSHEmgMed"
    assert row["start_date"] == date(2025, 8, 7)
    assert row["end_date"] == date(2025, 8, 7)
    assert row["day_part"] == "PM"
    assert _unmatched_multi_posting_warnings(result) == []


def test_single_posting_explicit_date_fragments_with_am_and_pm_keep_both_and_no_warning() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="E001",
                name="Single Posting AM PM",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul=(
                    "NNINeuRad\n"
                    "(from 07-Aug-2025 to 07-Aug-2025 AM)\n"
                    "(from 07-Aug-2025 to 07-Aug-2025 PM)"
                ),
            )
        ],
        month_labels=["Aug-25"],
        date_ranges=["04 Aug 25 - 31 Aug 25"],
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="single-posting-am-pm.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    rows = [row for row in session.resident_postings if row["posting_code"] == "NNINeuRad"]
    assert len(rows) == 2
    assert {row["day_part"] for row in rows} == {"AM", "PM"}
    assert all(row["start_date"] == date(2025, 8, 7) for row in rows)
    assert all(row["end_date"] == date(2025, 8, 7) for row in rows)
    assert _unmatched_multi_posting_warnings(result) == []


def test_true_multi_posting_without_rule_still_emits_unmatched_warning() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="E001",
                name="True Unmatched Multi Posting",
                mcr="M11111A",
                r_year="R2",
                programme="ANAES",
                jul=(
                    "TTSHAnaes\n"
                    "(from 04-Aug-2025 to 06-Aug-2025)\n"
                    "TTSHCardio\n"
                    "(from 07-Aug-2025 to 10-Aug-2025)"
                ),
            )
        ],
        month_labels=["Aug-25"],
        date_ranges=["04 Aug 25 - 31 Aug 25"],
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="true-multi-posting-unmatched.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    warnings = _unmatched_multi_posting_warnings(result)
    assert len(warnings) == 1
    _assert_unmatched_warning_trace_fields(
        warnings[0],
        mcr="M11111A",
        resident_name="True Unmatched Multi Posting",
        programme_code="ANAES",
        month_label="Aug-25",
        sheet_name="Phase 1",
        row_number=3,
        cell_ref="I3",
    )
    assert _distinct_warning_posting_codes(warnings[0]) == ["TTSHAnaes", "TTSHCardio"]


def test_duplicate_same_start_same_day_part_is_suppressed_before_insert() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="E001",
                name="Duplicate Full Day",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul=(
                    "TTSHDiagRd\n"
                    "(from 01-Dec-2025 to 01-Dec-2025 )\n"
                    "SGHDiagRd\n"
                    "(from 01-Dec-2025 to 01-Dec-2025 )"
                ),
            )
        ],
        month_labels=["Dec-25"],
        date_ranges=["01 Dec 25 - 05 Jan 26"],
        sheet_name="Phase 3",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="duplicate-full-day.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["postings_created"] == 1
    assert len(session.resident_postings) == 1
    assert session.resident_postings[0]["start_date"] == date(2025, 12, 1)
    assert session.resident_postings[0]["day_part"] is None
    assert any(
        isinstance(item, dict)
        and item.get("type") == "duplicate_resident_posting_suppressed"
        for item in result.warnings
    )


def test_future_employed_prefix_works_without_hardcoded_whitelist() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="ABC Employed",
                name="Future Employed One",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="ABC employed",
            ),
            _resident_row(
                employee_code="ABC Employed",
                name="Future Employed Two",
                mcr="M22222B",
                r_year="R2",
                programme="DR",
                jul="ABC employed",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert session.residents["M11111A"]["employee_code"] is None
    assert session.residents["M22222B"]["employee_code"] is None
    assert session.residents["M11111A"]["employer_tag"] == "ABC"
    assert session.residents["M22222B"]["employer_tag"] == "ABC"
    assert session.resident_postings == []
    assert all("Employed" not in code for code in session.posting_codes)


def test_numeric_employee_code_still_persists_for_non_employed_rows() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="47008861",
                name="Numeric Employee Code",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert session.residents["M11111A"]["employee_code"] == "47008861"
    assert session.residents["M11111A"]["employer_tag"] is None
    assert [row["posting_code"] for row in session.resident_postings] == ["TTSHAnaes"]


def test_programme_full_name_resolves_to_canonical_code() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Anaes Resident",
                mcr="M11111A",
                r_year="R2",
                programme="Anaesthesiology",
                jul="TTSHAnaes",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert session.residents["M11111A"]["programme_code"] == "ANAES"


def test_programme_resolution_is_case_insensitive_and_trimmed() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Anaes Resident",
                mcr="M11111A",
                r_year="R2",
                programme=" anaesthesiology ",
                jul="TTSHAnaes",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert session.residents["M11111A"]["programme_code"] == "ANAES"


def test_unknown_programme_warns_and_upload_continues() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Known Resident",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="TTSHDiagRd",
            ),
            _resident_row(
                employee_code="E002",
                name="Unknown Resident",
                mcr="M22222B",
                r_year="R2",
                programme="Unknown Programme",
                jul="TTSHAnaes",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert "M11111A" in session.residents
    assert "M22222B" not in session.residents
    assert result.metadata["rows_skipped"] == 1
    assert any(
        isinstance(item, dict)
        and item.get("type") == "unknown_programme"
        and item.get("specialization") == "Unknown Programme"
        for item in result.warnings
    )


def test_loa_refresher_unknown_loa_and_working_days_are_persisted() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Pure LOA",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="LOA (Exam Leave from 10-Jul-2025 to 12-Jul-2025 )",
            ),
            _resident_row(
                employee_code="E002",
                name="Hybrid LOA",
                mcr="M22222B",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes\nLOA (Maternity Leave from 08-Jul-2025 to 09-Jul-2025)",
            ),
            _resident_row(
                employee_code="E003",
                name="Refresher",
                mcr="M33333C",
                r_year="R2",
                programme="DR",
                jul="TTSHDiagRd (Refresher Training (add to Max Cand) from 08-Jul-2025 to 03-Aug-2025)",
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    rows_by_status = {row["status"]: row for row in session.resident_postings}
    pure_loa = rows_by_status["loa"]
    hybrid_loa = rows_by_status["loa_working"]
    refresher = next(row for row in session.resident_postings if row["posting_code"] == "TTSHDiagRd")

    assert pure_loa["posting_code"] is None
    assert pure_loa["loa_type"] == "Exam Leave"
    assert pure_loa["working_days_in_month"] == 24
    assert hybrid_loa["posting_code"] == "TTSHAnaes"
    assert hybrid_loa["loa_type"] == "Maternity Leave"
    assert refresher["refresher_training_type"] == "add to Max Cand"
    assert result.metadata["loa_records"] == 2
    assert result.metadata["unknown_loa_types"] == ["Exam Leave"]
    assert any("Unknown LOA type: Exam Leave" in str(item) for item in result.warnings)


def test_ay25_spaced_hybrid_loa_working_cell_persists_without_unknown_loa_warning() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook_with_months(
        [
            _resident_row(
                employee_code="E001",
                name="AY25 Hybrid",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul=(
                    "TTSHAnaes (Continue working during LOA "
                    "from 06 - Apr - 2026 to 03 - May - 2026 )"
                ),
            )
        ],
        month_labels=["Apr-26"],
        date_ranges=["06 Apr 26 - 03 May 26"],
        sheet_name="Phase 1 & 2",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="ay25-spaced-loa.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert "Continue working during LOA" not in result.metadata["unknown_loa_types"]
    assert not any(
        "Unknown LOA type: Continue working during LOA" in str(item)
        for item in result.warnings
    )
    assert len(session.resident_postings) == 1
    posting = session.resident_postings[0]
    assert posting["posting_code"] == "TTSHAnaes"
    assert posting["status"] == "loa_working"
    assert posting["loa_type"] is None
    assert posting["loa_start_date"] == date(2026, 4, 6)
    assert posting["loa_end_date"] == date(2026, 5, 3)


def test_real_ay25_workbook_does_not_report_continue_working_as_unknown_loa() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _sample_workbook_bytes(
        "AY25 Posting Schedule_2026.04.23.xlsx",
        "AY25.xlsx",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="AY25 Posting Schedule_2026.04.23.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert "Continue working during LOA" not in result.metadata["unknown_loa_types"]
    assert not any(
        "Unknown LOA type: Continue working during LOA" in str(item)
        for item in result.warnings
    )

    resident = session.residents["M64770E"]
    dec_rows = [
        row
        for row in session.resident_postings
        if row["resident_id"] == resident["id"] and row["month_label"] == "Dec-25"
    ]
    assert any(
        row["status"] == "loa_working"
        and row["posting_code"] is None
        and row["loa_type"] is None
        and row["loa_start_date"] == date(2025, 12, 1)
        and row["loa_end_date"] == date(2026, 1, 5)
        for row in dec_rows
    )


def test_real_ay25_workbook_unmatched_multi_posting_warnings_have_no_single_posting_entries() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _sample_workbook_bytes(
        "AY25 Posting Schedule_2026.04.23.xlsx",
        "AY25.xlsx",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="AY25 Posting Schedule_2026.04.23.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["unknown_loa_types"] == []
    assert not any(
        isinstance(item, dict)
        and item.get("type") == "cell_warning"
        and "Malformed employed marker" in str(item.get("message", ""))
        for item in result.warnings
    )

    unmatched = _unmatched_multi_posting_warnings(result)
    for warning in unmatched:
        assert warning.get("mcr")
        assert warning.get("resident_name")
        assert warning.get("programme_code")
        assert warning.get("month_label")
        assert warning.get("sheet_name")
        assert warning.get("row_number")
        assert warning.get("posting_codes")
        assert warning.get("cell_ref")

    single_posting_unmatched = [
        warning
        for warning in unmatched
        if len(_distinct_warning_posting_codes(warning)) == 1
    ]
    true_multi_posting_unmatched = [
        warning
        for warning in unmatched
        if len(_distinct_warning_posting_codes(warning)) >= 2
    ]

    assert single_posting_unmatched == []
    assert len(true_multi_posting_unmatched) == len(unmatched)


def test_real_baseline_rdb_workbook_has_no_unknown_loa_types() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _sample_workbook_bytes(
        "RDB_Posting_Scheduler__CL.xlsx",
        "RDB_baseline.xlsx",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="RDB_Posting_Scheduler__CL.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["unknown_loa_types"] == []
    assert not any(
        isinstance(item, dict)
        and item.get("type") == "cell_warning"
        and str(item.get("message", "")).startswith("Unknown LOA type:")
        for item in result.warnings
    )


def test_refresher_annotations_persist_clean_posting_codes_and_never_upsert_full_annotation() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    valid_refresher = (
        "CGHPsyMed (Refresher Training (don't add to Max Cand) from 20-Feb-2026 to 01-Mar-2026)"
    )
    malformed_refresher = (
        "CGHPsyMed (Refresher Training (dont add to Max Cand) from 20-Feb-2026 to 01-Mar-2026)"
    )
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Valid Refresher",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul=valid_refresher,
            ),
            _resident_row(
                employee_code="E002",
                name="Malformed Refresher",
                mcr="M22222B",
                r_year="R2",
                programme="DR",
                jul=(
                    "LOA (Annual Leaves from 02-Feb-2026 to 18-Feb-2026)\n"
                    + malformed_refresher
                ),
            ),
        ]
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert "CGHPsyMed" in session.posting_codes
    assert valid_refresher not in session.posting_codes
    assert malformed_refresher not in session.posting_codes
    assert all(len(code) <= 50 for code in session.posting_codes)

    refresher_rows = [
        row for row in session.resident_postings if row["posting_code"] == "CGHPsyMed"
    ]
    assert len(refresher_rows) == 2
    assert any(
        row["refresher_training_type"] == "don't add to Max Cand"
        and row["refresher_training_start"] == date(2026, 2, 20)
        and row["refresher_training_end"] == date(2026, 3, 1)
        for row in refresher_rows
    )
    assert any("Malformed refresher" in str(item) for item in result.warnings)


def test_multi_posting_rules_and_unmatched_fallbacks_apply_on_non_fm_sheets() -> None:
    session = FakeRDBSession()
    session.multi_posting_rules.extend(
        [
            {
                "programme_code": "DR",
                "posting_code_1": "A",
                "posting_code_2": "B",
                "rule_type": "combine",
                "combined_label": "A & B",
                "main_posting_code": None,
                "exclusion_code": None,
            },
            {
                "programme_code": "DR",
                "posting_code_1": "C",
                "posting_code_2": "D",
                "rule_type": "half_month",
                "combined_label": None,
                "main_posting_code": None,
                "exclusion_code": None,
            },
            {
                "programme_code": "DR",
                "posting_code_1": "E",
                "posting_code_2": "F",
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "E",
                "exclusion_code": "F",
            },
        ]
    )
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Combine",
                mcr="M11111A",
                r_year="R2",
                programme="DR",
                jul="A\n(from 08-Jul-2025 to 15-Jul-2025)\nB\n(from 16-Jul-2025 to 03-Aug-2025)",
            ),
            _resident_row(
                employee_code="E002",
                name="Half",
                mcr="M22222B",
                r_year="R2",
                programme="DR",
                jul="C\n(from 08-Jul-2025 to 15-Jul-2025)\nD\n(from 16-Jul-2025 to 03-Aug-2025)",
            ),
            _resident_row(
                employee_code="E003",
                name="Main",
                mcr="M33333C",
                r_year="R2",
                programme="DR",
                jul="E\n(from 08-Jul-2025 to 15-Jul-2025)\nF\n(from 16-Jul-2025 to 03-Aug-2025)",
            ),
            _resident_row(
                employee_code="E004",
                name="Unmatched",
                mcr="M44444D",
                r_year="R2",
                programme="DR",
                jul="X\n(from 08-Jul-2025 to 15-Jul-2025)\nY\n(from 16-Jul-2025 to 03-Aug-2025)",
            ),
        ],
        sheet_name="Phase 3",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    codes = [row["posting_code"] for row in session.resident_postings]
    half_rows = [row for row in session.resident_postings if row["posting_code"] in {"C", "D"}]
    unmatched_rows = [row for row in session.resident_postings if row["posting_code"] in {"X", "Y"}]

    assert "A & B" in codes
    assert "E" in codes
    assert [str(row["active_months_weight"]) for row in half_rows] == ["0.5", "0.5"]
    assert all(row["day_part"] is None for row in half_rows)
    assert len(unmatched_rows) == 2
    assert result.metadata["multi_posting_rules_applied"] == 3
    assert any(
        isinstance(item, dict) and item.get("type") == "unmatched_multi_posting"
        for item in result.warnings
    )


def test_fm_main_posting_rule_collapses_specialty_and_nhgply_fragments() -> None:
    session = FakeRDBSession()
    session.multi_posting_rules.append(
        {
            "programme_code": "FM",
            "posting_code_1": "TTSHGenMed",
            "posting_code_2": None,
            "rule_type": "main_posting",
            "combined_label": None,
            "main_posting_code": "TTSHGenMed",
            "exclusion_code": "NHGPlyNHGPly",
        }
    )
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="FM Resident",
                mcr="M11111A",
                r_year="R2",
                programme="FM",
                jul=(
                    "TTSHGenMed\n"
                    "(from 08-Jul-2025 to 08-Jul-2025 AM)\n"
                    "(from 09-Jul-2025 to 03-Aug-2025 )\n"
                    "NHGPlyNHGPly\n"
                    "(from 08-Jul-2025 to 08-Jul-2025 PM)"
                ),
            )
        ],
        sheet_name="Phase 1 & 2",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="fm-main-posting.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["multi_posting_rules_applied"] == 1
    assert result.metadata["postings_created"] == 1
    assert session.resident_postings[0]["posting_code"] == "TTSHGenMed"
    assert session.resident_postings[0]["start_date"] == date(2025, 7, 8)
    assert session.resident_postings[0]["end_date"] == date(2025, 8, 3)
    assert session.resident_postings[0]["day_part"] is None
    assert "NHGPlyNHGPly" not in {
        row["posting_code"] for row in session.resident_postings
    }


def test_fm_main_posting_exact_one_recognised_posting_collapses_without_warning() -> None:
    session = FakeRDBSession()
    session.multi_posting_rules.extend(
        [
            {
                "programme_code": "FM",
                "posting_code_1": "NUHPaedia",
                "posting_code_2": None,
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "NUHPaedia",
                "exclusion_code": "NHGPlyNHGPly",
            },
            {
                "programme_code": "FM",
                "posting_code_1": "TTSHGenSrg",
                "posting_code_2": None,
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "TTSHGenSrg",
                "exclusion_code": "NHGPlyNHGPly",
            },
        ]
    )
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="FM Exact One",
                mcr="M11111A",
                r_year="R2",
                programme="FM",
                jul=(
                    "NUHPaedia\n"
                    "(from 08-Jul-2025 to 15-Jul-2025)\n"
                    "NHGPlyNHGPly\n"
                    "(from 16-Jul-2025 to 03-Aug-2025)"
                ),
            )
        ],
        sheet_name="Phase 1 & 2 (FM)",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="fm-exact-one.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["multi_posting_rules_applied"] == 1
    assert [row["posting_code"] for row in session.resident_postings] == ["NUHPaedia"]
    assert _unmatched_multi_posting_warnings(result) == []


def test_fm_main_posting_zero_recognised_postings_collapses_to_configured_exclusion() -> None:
    session = FakeRDBSession()
    session.multi_posting_rules.append(
        {
            "programme_code": "FM",
            "posting_code_1": "NUHPaedia",
            "posting_code_2": None,
            "rule_type": "main_posting",
            "combined_label": None,
            "main_posting_code": "NUHPaedia",
            "exclusion_code": "NHGPlyNHGPly",
        }
    )
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="FM Zero Match",
                mcr="M11111A",
                r_year="R2",
                programme="FM",
                jul=(
                    "TTSHUrolog\n"
                    "(from 08-Jul-2025 to 15-Jul-2025)\n"
                    "NHGPlyNHGPly\n"
                    "(from 16-Jul-2025 to 03-Aug-2025)"
                ),
            )
        ],
        sheet_name="Phase 1 & 2 (FM)",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="fm-zero-match.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["multi_posting_rules_applied"] == 1
    assert [row["posting_code"] for row in session.resident_postings] == ["NHGPlyNHGPly"]
    assert _unmatched_multi_posting_warnings(result) == []


def test_fm_main_posting_two_or_more_recognised_postings_still_warns() -> None:
    session = FakeRDBSession()
    session.multi_posting_rules.extend(
        [
            {
                "programme_code": "FM",
                "posting_code_1": "TTSHGenSrg",
                "posting_code_2": None,
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "TTSHGenSrg",
                "exclusion_code": "NHGPlyNHGPly",
            },
            {
                "programme_code": "FM",
                "posting_code_1": "TTSHUrolog",
                "posting_code_2": None,
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "TTSHUrolog",
                "exclusion_code": "NHGPlyNHGPly",
            },
        ]
    )
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="FM Ambiguous",
                mcr="M11111A",
                r_year="R2",
                programme="FM",
                jul=(
                    "TTSHGenSrg\n"
                    "(from 08-Jul-2025 to 12-Jul-2025)\n"
                    "TTSHUrolog\n"
                    "(from 13-Jul-2025 to 18-Jul-2025)\n"
                    "NHGPlyNHGPly\n"
                    "(from 19-Jul-2025 to 03-Aug-2025)"
                ),
            )
        ],
        sheet_name="Phase 1 & 2 (FM)",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="fm-ambiguous.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["multi_posting_rules_applied"] == 0
    assert {row["posting_code"] for row in session.resident_postings} == {
        "TTSHGenSrg",
        "TTSHUrolog",
        "NHGPlyNHGPly",
    }
    warnings = _unmatched_multi_posting_warnings(result)
    assert len(warnings) == 1
    _assert_unmatched_warning_trace_fields(
        warnings[0],
        mcr="M11111A",
        resident_name="FM Ambiguous",
        programme_code="FM",
        month_label="Jul-25",
        sheet_name="Phase 1 & 2 (FM)",
        row_number=3,
        cell_ref="I3",
    )
    assert _distinct_warning_posting_codes(warnings[0]) == [
        "TTSHGenSrg",
        "TTSHUrolog",
        "NHGPlyNHGPly",
    ]


def test_singular_nhgply_cell_is_valid_standalone_without_multi_posting_lookup() -> None:
    session = FakeRDBSession()
    session.multi_posting_rules.append(
        {
            "programme_code": "FM",
            "posting_code_1": "NUHPaedia",
            "posting_code_2": None,
            "rule_type": "main_posting",
            "combined_label": None,
            "main_posting_code": "NUHPaedia",
            "exclusion_code": "NHGPlyNHGPly",
        }
    )
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="FM NHGPly",
                mcr="M11111A",
                r_year="R2",
                programme="FM",
                jul="NHGPlyNHGPly",
            )
        ],
        sheet_name="Phase 1 & 2 (FM)",
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="fm-nhgply-standalone.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert result.metadata["multi_posting_rules_applied"] == 0
    assert [row["posting_code"] for row in session.resident_postings] == ["NHGPlyNHGPly"]
    assert _unmatched_multi_posting_warnings(result) == []


def test_non_fm_unknown_pair_persists_independently_and_warns() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Non FM Unknown",
                mcr="M11111A",
                r_year="R2",
                programme="ANAES",
                jul=(
                    "TTSHAnaes\n"
                    "(from 08-Jul-2025 to 15-Jul-2025)\n"
                    "TTSHCardio\n"
                    "(from 16-Jul-2025 to 03-Aug-2025)"
                ),
            )
        ],
    )

    result = _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="non-fm-unmatched.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert result.errors == []
    assert {row["posting_code"] for row in session.resident_postings} == {
        "TTSHAnaes",
        "TTSHCardio",
    }
    warnings = _unmatched_multi_posting_warnings(result)
    assert len(warnings) == 1
    _assert_unmatched_warning_trace_fields(
        warnings[0],
        mcr="M11111A",
        resident_name="Non FM Unknown",
        programme_code="ANAES",
        month_label="Jul-25",
        sheet_name="Phase 1",
        row_number=3,
        cell_ref="I3",
    )
    assert _distinct_warning_posting_codes(warnings[0]) == ["TTSHAnaes", "TTSHCardio"]


def test_hibernate_stale_surplus_runs_after_postings_are_inserted() -> None:
    session = FakeRDBSession()
    period_id = uuid4()
    stale_resident_id = uuid4()
    session.surplus_ledger.append(
        {
            "reporting_period_id": str(period_id),
            "resident_id": stale_resident_id,
            "posting_code": "OldPosting",
            "is_hibernating": False,
        }
    )

    file_bytes = _rdb_workbook(
        [
            _resident_row(
                employee_code="E001",
                name="Resident One",
                mcr="M12345A",
                r_year="R2",
                programme="DR",
                jul="TTSHAnaes",
            )
        ]
    )

    _run(
        parse_rdb_upload(
            file_bytes=file_bytes,
            original_filename="rdb.xlsx",
            reporting_period_id=period_id,
            db_session=session,
        )
    )

    assert session.hibernate_calls == 1
    assert session.surplus_ledger[0]["is_hibernating"] is True
