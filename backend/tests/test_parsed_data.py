from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


class _FakeScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class FakeParsedDataSession:
    def __init__(self) -> None:
        now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.other_period_id = str(uuid4())
        self.geri_resident_id = str(uuid4())
        self.dr_resident_id = str(uuid4())
        self.reh_resident_id = str(uuid4())
        self.geri_session_type_id = str(uuid4())
        self.dr_session_type_id = str(uuid4())
        self.upload_id = str(uuid4())
        self.reporting_periods = [
            {
                "id": self.period_id,
                "label": "Jan - June 2026",
            },
            {
                "id": self.other_period_id,
                "label": "Jul - Dec 2026",
            },
        ]
        self.residents = [
            {
                "id": self.geri_resident_id,
                "employee_code": "E001",
                "name": "Geri Resident",
                "mcr": "M11111A",
                "classification": "Senior Resident",
                "programme_code": "GERI",
                "r_year": "R3",
                "reg_type": "Full",
                "base_institution": "TTSH",
                "email": "geri@example.test",
                "phone": None,
                "status": "active",
                "employer_tag": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": self.dr_resident_id,
                "employee_code": "E002",
                "name": "DR Resident",
                "mcr": "M22222B",
                "classification": "Junior Resident",
                "programme_code": "DR",
                "r_year": "R2",
                "reg_type": "Full",
                "base_institution": "KTPH",
                "email": "dr@example.test",
                "phone": None,
                "status": "active",
                "employer_tag": "SAF",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": self.reh_resident_id,
                "employee_code": "E003",
                "name": "REH Resident",
                "mcr": "M33333C",
                "classification": "Senior Resident",
                "programme_code": "REH",
                "r_year": "ALL",
                "reg_type": "Conditional",
                "base_institution": "TTSH",
                "email": "reh@example.test",
                "phone": None,
                "status": "inactive",
                "employer_tag": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.resident_postings = [
            {
                "id": str(uuid4()),
                "resident_id": self.geri_resident_id,
                "posting_code": "TTSHGerMed",
                "reporting_period_id": self.period_id,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
                "day_part": None,
                "month_label": "Jan-26",
                "r_year": "ALL",
                "status": "active",
                "loa_type": None,
                "loa_start_date": None,
                "loa_end_date": None,
                "refresher_training_type": None,
                "refresher_training_start": None,
                "refresher_training_end": None,
                "active_months_weight": Decimal("1.0"),
                "working_days_in_month": 22,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "resident_id": self.dr_resident_id,
                "posting_code": "KTPHDiagRd",
                "reporting_period_id": self.period_id,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
                "day_part": None,
                "month_label": "Jan-26",
                "r_year": "R2",
                "status": "active",
                "loa_type": None,
                "loa_start_date": None,
                "loa_end_date": None,
                "refresher_training_type": None,
                "refresher_training_start": None,
                "refresher_training_end": None,
                "active_months_weight": Decimal("1.0"),
                "working_days_in_month": 21,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "resident_id": self.reh_resident_id,
                "posting_code": "TTSHRehab",
                "reporting_period_id": self.other_period_id,
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 31),
                "day_part": None,
                "month_label": "Jul-26",
                "r_year": "ALL",
                "status": "loa",
                "loa_type": "Annual Leaves",
                "loa_start_date": date(2026, 7, 5),
                "loa_end_date": date(2026, 7, 10),
                "refresher_training_type": "add to Max Cand",
                "refresher_training_start": date(2026, 7, 12),
                "refresher_training_end": date(2026, 7, 14),
                "active_months_weight": Decimal("0.5"),
                "working_days_in_month": 10,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.session_types = [
            {
                "id": self.geri_session_type_id,
                "name": "Department Teaching [1h]",
                "duration_hours": Decimal("1.00"),
                "duration_label": "[1h]",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": self.dr_session_type_id,
                "name": "National Teaching [2h]",
                "duration_hours": Decimal("2.00"),
                "duration_label": "[2h]",
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.teaching_targets = [
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "programme_code": "GERI",
                "r_year": "ALL",
                "posting_code": "TTSHGerMed",
                "session_type_id": self.geri_session_type_id,
                "monthly_target": 4,
                "is_tracked": True,
                "is_reallocatable": True,
                "tag": "A1",
                "details_of_training": "Journal Club",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "programme_code": "DR",
                "r_year": "R2",
                "posting_code": "KTPHDiagRd",
                "session_type_id": self.dr_session_type_id,
                "monthly_target": 2,
                "is_tracked": False,
                "is_reallocatable": False,
                "tag": None,
                "details_of_training": "X-Ray Meeting",
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.teaching_name_catalogue = [
            {
                "id": str(uuid4()),
                "keyword": "Journal Club",
                "programme_code": "GERI",
                "posting_code": "TTSHGerMed",
                "r_year": "ALL",
                "reporting_period_id": self.period_id,
                "session_type_id": self.geri_session_type_id,
                "duration_hours": Decimal("1.00"),
                "is_tracked": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "keyword": "X-Ray Meeting",
                "programme_code": "DR",
                "posting_code": "KTPHDiagRd",
                "r_year": "R2",
                "reporting_period_id": self.period_id,
                "session_type_id": self.dr_session_type_id,
                "duration_hours": Decimal("2.00"),
                "is_tracked": False,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.form_f1_records = [
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "mcr": "M11111A",
                "month_label": "Jan-26",
                "status_raw": "Active",
                "is_active": True,
                "promotion_date": date(2026, 7, 1),
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "mcr": "M22222B",
                "month_label": "Jan-26",
                "status_raw": "Inactive",
                "is_active": False,
                "promotion_date": None,
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "mcr": "M99999Z",
                "month_label": "Jan-26",
                "status_raw": "Active",
                "is_active": True,
                "promotion_date": None,
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.public_holidays = [
            {
                "id": str(uuid4()),
                "holiday_date": date(2026, 1, 1),
                "name": "New Year's Day",
                "day_of_week": "Thursday",
                "year": 2026,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "holiday_date": date(2026, 2, 17),
                "name": "Chinese New Year",
                "day_of_week": "Tuesday",
                "year": 2026,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.academic_month_boundaries = [
            {
                "id": str(uuid4()),
                "academic_year_label": "AY2026",
                "ay_date_category": "im_subspec",
                "month_label": "Jan-26",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "academic_year_label": "AY2026",
                "ay_date_category": "non_im_subspec",
                "month_label": "Jan-26",
                "start_date": date(2026, 1, 5),
                "end_date": date(2026, 2, 1),
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self._original_state = self._state_snapshot()

    def _state_snapshot(self) -> dict[str, list[dict]]:
        return {
            "residents": deepcopy(self.residents),
            "resident_postings": deepcopy(self.resident_postings),
            "teaching_targets": deepcopy(self.teaching_targets),
            "teaching_name_catalogue": deepcopy(self.teaching_name_catalogue),
            "form_f1_records": deepcopy(self.form_f1_records),
            "public_holidays": deepcopy(self.public_holidays),
            "academic_month_boundaries": deepcopy(self.academic_month_boundaries),
        }

    def assert_not_mutated(self) -> None:
        assert self._state_snapshot() == self._original_state

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        rows = self._rows_for_sql(sql, payload)
        if "COUNT(*)" in sql:
            return _FakeScalarResult(len(rows))
        limit = int(payload.get("limit", len(rows)))
        offset = int(payload.get("offset", 0))
        return _FakeMappingResult(rows[offset : offset + limit])

    def _rows_for_sql(self, sql: str, payload: dict) -> list[dict]:
        if "1 = 0" in sql:
            return []
        if "FROM resident_postings rp" in sql:
            return self._resident_posting_rows(payload)
        if "FROM teaching_targets tt" in sql:
            return self._teaching_target_rows(payload)
        if "FROM teaching_name_catalogue tnc" in sql:
            return self._catalogue_rows(payload)
        if "FROM form_f1_records f" in sql:
            return self._form_f1_rows(payload)
        if "FROM public_holidays ph" in sql:
            return self._public_holiday_rows(payload)
        if "FROM academic_month_boundaries amb" in sql:
            return self._academic_boundary_rows(payload)
        if "FROM residents r" in sql:
            return self._resident_rows(payload)
        raise AssertionError(f"Unhandled SQL in fake parsed-data session: {sql}")

    def _scope_codes(self, payload: dict) -> set[str]:
        return {
            value
            for key, value in payload.items()
            if key.startswith("scope_programme_code_")
        }

    def _period_label(self, reporting_period_id: str) -> str | None:
        for row in self.reporting_periods:
            if row["id"] == reporting_period_id:
                return row["label"]
        return None

    def _resident_by_id(self, resident_id: str) -> dict | None:
        return next((row for row in self.residents if row["id"] == resident_id), None)

    def _resident_by_mcr(self, mcr: str) -> dict | None:
        return next((row for row in self.residents if row["mcr"].upper() == mcr.upper()), None)

    def _session_type(self, session_type_id: str) -> dict | None:
        return next((row for row in self.session_types if row["id"] == session_type_id), None)

    def _resident_rows(self, payload: dict) -> list[dict]:
        rows = list(self.residents)
        scope_codes = self._scope_codes(payload)
        if scope_codes:
            rows = [row for row in rows if row["programme_code"] in scope_codes]
        rows = self._filter_programme(rows, payload, key="programme_code")
        rows = self._filter_exact(rows, payload, "mcr", normalise=str.upper)
        rows = self._filter_exact(rows, payload, "status", normalise=str.lower)
        rows = self._filter_search(
            rows,
            payload,
            fields=("name", "mcr", "employee_code", "programme_code", "r_year"),
        )
        return sorted(rows, key=lambda row: (row["programme_code"] or "", row["mcr"], row["id"]))

    def _resident_posting_rows(self, payload: dict) -> list[dict]:
        rows: list[dict] = []
        for posting in self.resident_postings:
            resident = self._resident_by_id(posting["resident_id"])
            if resident is None:
                continue
            row = {
                **posting,
                "resident_name": resident["name"],
                "mcr": resident["mcr"],
                "programme_code": resident["programme_code"],
                "reporting_period_label": self._period_label(posting["reporting_period_id"]),
            }
            rows.append(row)
        scope_codes = self._scope_codes(payload)
        if scope_codes:
            rows = [row for row in rows if row["programme_code"] in scope_codes]
        rows = self._filter_programme(rows, payload, key="programme_code")
        rows = self._filter_exact(rows, payload, "reporting_period_id")
        rows = self._filter_exact(rows, payload, "posting_code")
        rows = self._filter_exact(rows, payload, "mcr", normalise=str.upper)
        rows = self._filter_exact(rows, payload, "month_label")
        rows = self._filter_exact(rows, payload, "status", normalise=str.lower)
        rows = self._filter_search(rows, payload, fields=("resident_name", "mcr", "posting_code"))
        return sorted(
            rows,
            key=lambda row: (
                row["reporting_period_id"],
                row["programme_code"] or "",
                row["mcr"] or "",
                row["start_date"],
                row["id"],
            ),
        )

    def _teaching_target_rows(self, payload: dict) -> list[dict]:
        rows: list[dict] = []
        for target in self.teaching_targets:
            session_type = self._session_type(target["session_type_id"])
            rows.append(
                {
                    **target,
                    "reporting_period_label": self._period_label(target["reporting_period_id"]),
                    "session_type_name": session_type["name"] if session_type else None,
                    "duration_hours": session_type["duration_hours"] if session_type else None,
                }
            )
        scope_codes = self._scope_codes(payload)
        if scope_codes:
            rows = [row for row in rows if row["programme_code"] in scope_codes]
        rows = self._filter_programme(rows, payload, key="programme_code")
        rows = self._filter_exact(rows, payload, "reporting_period_id")
        rows = self._filter_exact(rows, payload, "posting_code")
        rows = self._filter_exact(rows, payload, "r_year", normalise=str.upper)
        if "is_tracked" in payload:
            rows = [row for row in rows if row["is_tracked"] == payload["is_tracked"]]
        if "session_type" in payload:
            token = payload["session_type"].strip("%").lower()
            rows = [
                row
                for row in rows
                if token in (row["session_type_name"] or "").lower()
            ]
        rows = self._filter_search(
            rows,
            payload,
            fields=("programme_code", "posting_code", "session_type_name", "details_of_training"),
        )
        return sorted(
            rows,
            key=lambda row: (
                row["reporting_period_id"],
                row["programme_code"],
                row["posting_code"],
                row["r_year"],
                row["session_type_name"] or "",
            ),
        )

    def _catalogue_rows(self, payload: dict) -> list[dict]:
        rows: list[dict] = []
        for catalogue_row in self.teaching_name_catalogue:
            session_type = self._session_type(catalogue_row["session_type_id"])
            rows.append(
                {
                    **catalogue_row,
                    "reporting_period_label": self._period_label(catalogue_row["reporting_period_id"]),
                    "session_type_name": session_type["name"] if session_type else None,
                }
            )
        scope_codes = self._scope_codes(payload)
        if scope_codes:
            rows = [row for row in rows if row["programme_code"] in scope_codes]
        rows = self._filter_programme(rows, payload, key="programme_code")
        rows = self._filter_exact(rows, payload, "reporting_period_id")
        rows = self._filter_exact(rows, payload, "posting_code")
        rows = self._filter_exact(rows, payload, "r_year", normalise=str.upper)
        if "keyword" in payload:
            token = payload["keyword"].strip("%").lower()
            rows = [row for row in rows if token in row["keyword"].lower()]
        if "is_tracked" in payload:
            rows = [row for row in rows if row["is_tracked"] == payload["is_tracked"]]
        rows = self._filter_search(
            rows,
            payload,
            fields=("keyword", "programme_code", "posting_code", "session_type_name"),
        )
        return sorted(
            rows,
            key=lambda row: (
                row["reporting_period_id"],
                row["programme_code"],
                row["posting_code"],
                row["r_year"],
                row["keyword"],
            ),
        )

    def _form_f1_rows(self, payload: dict) -> list[dict]:
        rows: list[dict] = []
        for record in self.form_f1_records:
            resident = self._resident_by_mcr(record["mcr"])
            rows.append(
                {
                    **record,
                    "reporting_period_label": self._period_label(record["reporting_period_id"]),
                    "resident_name": resident["name"] if resident else None,
                    "programme_code": resident["programme_code"] if resident else None,
                }
            )
        scope_codes = self._scope_codes(payload)
        if scope_codes:
            rows = [row for row in rows if row["programme_code"] in scope_codes]
        rows = self._filter_programme(rows, payload, key="programme_code")
        rows = self._filter_exact(rows, payload, "reporting_period_id")
        rows = self._filter_exact(rows, payload, "mcr", normalise=str.upper)
        rows = self._filter_exact(rows, payload, "month_label")
        if "is_active" in payload:
            rows = [row for row in rows if row["is_active"] == payload["is_active"]]
        rows = self._filter_search(
            rows,
            payload,
            fields=("mcr", "resident_name", "programme_code", "status_raw", "month_label"),
        )
        return sorted(
            rows,
            key=lambda row: (
                row["reporting_period_id"],
                row["mcr"],
                row["month_label"],
            ),
        )

    def _public_holiday_rows(self, payload: dict) -> list[dict]:
        rows = list(self.public_holidays)
        if "year" in payload:
            rows = [row for row in rows if row["year"] == payload["year"]]
        rows = self._filter_search(rows, payload, fields=("name", "day_of_week"))
        return sorted(rows, key=lambda row: (row["holiday_date"], row["id"]))

    def _academic_boundary_rows(self, payload: dict) -> list[dict]:
        rows = list(self.academic_month_boundaries)
        rows = self._filter_exact(rows, payload, "academic_year_label")
        rows = self._filter_exact(rows, payload, "ay_date_category", normalise=str.lower)
        rows = self._filter_exact(rows, payload, "month_label")
        return sorted(
            rows,
            key=lambda row: (
                row["academic_year_label"],
                row["ay_date_category"],
                row["start_date"],
                row["id"],
            ),
        )

    def _filter_programme(self, rows: list[dict], payload: dict, *, key: str) -> list[dict]:
        if "programme_code" not in payload:
            return rows
        return [row for row in rows if row.get(key) == payload["programme_code"]]

    def _filter_exact(
        self,
        rows: list[dict],
        payload: dict,
        field: str,
        *,
        normalise=None,
    ) -> list[dict]:
        if field not in payload:
            return rows
        expected = payload[field]
        if normalise is not None and isinstance(expected, str):
            expected = normalise(expected)
        output = []
        for row in rows:
            value = row.get(field)
            if normalise is not None and isinstance(value, str):
                value = normalise(value)
            if value == expected:
                output.append(row)
        return output

    def _filter_search(self, rows: list[dict], payload: dict, *, fields: tuple[str, ...]) -> list[dict]:
        search = payload.get("search")
        if not search:
            return rows
        token = str(search).strip("%").lower()
        if not token:
            return rows
        return [
            row
            for row in rows
            if token in " ".join(str(row.get(field) or "") for field in fields).lower()
        ]

    async def commit(self) -> None:
        raise AssertionError("parsed data read endpoints must not commit")

    async def rollback(self) -> None:
        raise AssertionError("parsed data read endpoints must not rollback")


def _build_client_with_session(session: FakeParsedDataSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _admin_headers(scope: str | None = "GERI", *, master: bool = False) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def test_master_admin_can_list_residents() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/residents", headers=_admin_headers(scope=None, master=True))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {item["mcr"] for item in body["items"]} == {"M11111A", "M22222B", "M33333C"}


def test_programme_pc_sees_only_residents_in_scope() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/residents", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["programme_code"] == "GERI"


def test_programme_pc_with_null_or_empty_scope_sees_no_residents() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    missing_scope = client.get("/admin/parsed-data/residents", headers=_admin_headers(scope=None))
    empty_scope = client.get("/admin/parsed-data/residents", headers=_admin_headers(scope=""))

    assert missing_scope.status_code == 200
    assert missing_scope.json()["items"] == []
    assert missing_scope.json()["total"] == 0
    assert empty_scope.status_code == 200
    assert empty_scope.json()["items"] == []
    assert empty_scope.json()["total"] == 0


def test_master_admin_can_list_resident_postings_with_joined_fields() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get(
        "/admin/parsed-data/resident-postings",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["mcr"] == "M11111A")
    assert row["resident_name"] == "Geri Resident"
    assert row["programme_code"] == "GERI"
    assert row["reporting_period_label"] == "Jan - June 2026"


def test_programme_pc_sees_only_resident_postings_for_scoped_residents() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/resident-postings", headers=_admin_headers("DR"))

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["programme_code"] == "DR"


def test_master_admin_can_list_teaching_targets() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get(
        "/admin/parsed-data/teaching-targets",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["session_type_name"] for item in response.json()["items"]} == {
        "Department Teaching [1h]",
        "National Teaching [2h]",
    }


def test_programme_pc_sees_only_teaching_targets_in_scope() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/teaching-targets", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["programme_code"] == "GERI"


def test_master_admin_can_list_teaching_name_catalogue_rows() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get(
        "/admin/parsed-data/teaching-name-catalogue",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["keyword"] for item in response.json()["items"]} == {"Journal Club", "X-Ray Meeting"}


def test_programme_pc_sees_only_catalogue_rows_in_scope() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/teaching-name-catalogue", headers=_admin_headers("DR"))

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["programme_code"] == "DR"


def test_master_admin_can_list_form_f1_records_including_unknown_mcr_rows() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get(
        "/admin/parsed-data/form-f1-records",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()["items"]
    unknown = next(item for item in rows if item["mcr"] == "M99999Z")
    assert response.json()["total"] == 3
    assert unknown["resident_name"] is None
    assert unknown["programme_code"] is None


def test_programme_pc_sees_only_form_f1_rows_that_join_to_scoped_residents() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/form-f1-records", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["mcr"] == "M11111A"
    assert response.json()["items"][0]["programme_code"] == "GERI"


def test_programme_pc_does_not_see_unknown_mcr_form_f1_rows() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get("/admin/parsed-data/form-f1-records", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    assert "M99999Z" not in {item["mcr"] for item in response.json()["items"]}


def test_public_holidays_endpoint_is_master_only() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    forbidden = client.get("/admin/parsed-data/public-holidays", headers=_admin_headers("GERI"))
    allowed = client.get(
        "/admin/parsed-data/public-holidays",
        headers=_admin_headers(scope=None, master=True),
    )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["total"] == 2


def test_academic_month_boundaries_endpoint_is_master_only() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    forbidden = client.get("/admin/parsed-data/academic-month-boundaries", headers=_admin_headers("GERI"))
    allowed = client.get(
        "/admin/parsed-data/academic-month-boundaries",
        headers=_admin_headers(scope=None, master=True),
    )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["total"] == 2


def test_filters_work_for_programme_period_mcr_posting_and_active_status() -> None:
    session = FakeParsedDataSession()
    client = _build_client_with_session(session)

    residents = client.get(
        "/admin/parsed-data/residents",
        headers=_admin_headers(scope=None, master=True),
        params={"programme_code": "DR"},
    )
    postings = client.get(
        "/admin/parsed-data/resident-postings",
        headers=_admin_headers(scope=None, master=True),
        params={
            "reporting_period_id": session.period_id,
            "posting_code": "TTSHGerMed",
            "mcr": "M11111A",
        },
    )
    form_f1 = client.get(
        "/admin/parsed-data/form-f1-records",
        headers=_admin_headers(scope=None, master=True),
        params={"is_active": False, "mcr": "M22222B"},
    )

    assert residents.status_code == 200
    assert [item["programme_code"] for item in residents.json()["items"]] == ["DR"]
    assert postings.status_code == 200
    assert postings.json()["total"] == 1
    assert postings.json()["items"][0]["posting_code"] == "TTSHGerMed"
    assert form_f1.status_code == 200
    assert form_f1.json()["total"] == 1
    assert form_f1.json()["items"][0]["is_active"] is False


def test_pagination_returns_items_total_limit_and_offset() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    response = client.get(
        "/admin/parsed-data/residents",
        headers=_admin_headers(scope=None, master=True),
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["items"]) == 1


def test_non_admin_roles_are_rejected() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    secretary_response = client.get(
        "/admin/parsed-data/residents",
        headers={
            "X-User-Role": "secretary",
            "X-User-Id": str(uuid4()),
            "X-User-Site": "TTSHGerMed",
        },
    )
    resident_response = client.get(
        "/admin/parsed-data/residents",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": str(uuid4()),
        },
    )

    assert secretary_response.status_code == 403
    assert resident_response.status_code == 403


def test_master_admin_is_explicit_and_not_inferred_from_null_scope() -> None:
    client = _build_client_with_session(FakeParsedDataSession())

    scoped_preview = client.get("/admin/parsed-data/residents", headers=_admin_headers(scope=None))
    global_preview = client.get("/admin/parsed-data/public-holidays", headers=_admin_headers(scope=None))

    assert scoped_preview.status_code == 200
    assert scoped_preview.json()["items"] == []
    assert scoped_preview.json()["total"] == 0
    assert global_preview.status_code == 403


def test_parsed_data_read_endpoints_do_not_mutate_database() -> None:
    session = FakeParsedDataSession()
    client = _build_client_with_session(session)
    headers = _admin_headers(scope=None, master=True)

    paths = [
        "/admin/parsed-data/residents",
        "/admin/parsed-data/resident-postings",
        "/admin/parsed-data/teaching-targets",
        "/admin/parsed-data/teaching-name-catalogue",
        "/admin/parsed-data/form-f1-records",
        "/admin/parsed-data/public-holidays",
        "/admin/parsed-data/academic-month-boundaries",
    ]
    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 200

    session.assert_not_mutated()
