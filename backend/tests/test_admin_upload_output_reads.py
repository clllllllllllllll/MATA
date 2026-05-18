from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


class _FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError("Expected one or zero rows")
        return self._rows[0] if self._rows else None


class FakeUploadOutputReadSession:
    def __init__(self) -> None:
        now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.session_type_dr = str(uuid4())
        self.session_type_grm = str(uuid4())
        self.upload_id = str(uuid4())

        self.residents = [
            {
                "id": str(uuid4()),
                "employee_code": "EMP001",
                "name": "Alice Tan",
                "mcr": "M10001A",
                "classification": "senior",
                "programme_code": "DR",
                "r_year": "R3",
                "reg_type": "residency",
                "base_institution": "TTSH",
                "email": "alice@example.com",
                "phone": "12345678",
                "status": "active",
                "employer_tag": "SAF",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "employee_code": "EMP002",
                "name": "Bob Lim",
                "mcr": "M20002B",
                "classification": "senior",
                "programme_code": "GRM",
                "r_year": "R2",
                "reg_type": "residency",
                "base_institution": "KTPH",
                "email": "bob@example.com",
                "phone": "23456789",
                "status": "inactive",
                "employer_tag": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.resident_postings = [
            {
                "id": str(uuid4()),
                "resident_id": self.residents[0]["id"],
                "posting_code": "TTSHDR",
                "reporting_period_id": self.period_id,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
                "day_part": None,
                "month_label": "Jan-26",
                "r_year": "R3",
                "status": "active",
                "loa_type": None,
                "loa_start_date": None,
                "loa_end_date": None,
                "refresher_training_type": None,
                "refresher_training_start": None,
                "refresher_training_end": None,
                "active_months_weight": Decimal("1.0"),
                "working_days_in_month": 20,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "resident_id": self.residents[1]["id"],
                "posting_code": "TTSHGRM",
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
                "working_days_in_month": 20,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.posting_codes = [
            {
                "id": str(uuid4()),
                "code": "TTSHDR",
                "display_name": "TTSH DR",
                "institution": "TTSH",
                "department": "Radiology",
                "billing_dept": "RAD",
                "is_emergency": False,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "code": "TTSHED",
                "display_name": "TTSH ED",
                "institution": "TTSH",
                "department": "Emergency",
                "billing_dept": "ED",
                "is_emergency": True,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.session_types = [
            {
                "id": self.session_type_dr,
                "name": "Journal Club [1h]",
                "duration_hours": Decimal("1.0"),
                "duration_label": "1h",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": self.session_type_grm,
                "name": "Grand Round [2h]",
                "duration_hours": Decimal("2.0"),
                "duration_label": "2h",
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.teaching_targets = [
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "programme_code": "DR",
                "r_year": "R3",
                "posting_code": "TTSHDR",
                "session_type_id": self.session_type_dr,
                "monthly_target": 4,
                "is_tracked": True,
                "is_reallocatable": False,
                "tag": None,
                "details_of_training": "Journal Club",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "programme_code": "GRM",
                "r_year": "R2",
                "posting_code": "TTSHGRM",
                "session_type_id": self.session_type_grm,
                "monthly_target": 3,
                "is_tracked": False,
                "is_reallocatable": False,
                "tag": None,
                "details_of_training": "Ward teaching",
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.teaching_name_catalogue = [
            {
                "id": str(uuid4()),
                "keyword": "Journal Club",
                "session_type_id": self.session_type_dr,
                "posting_code": "TTSHDR",
                "programme_code": "DR",
                "r_year": "R3",
                "reporting_period_id": self.period_id,
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "keyword": "Ward Teaching",
                "session_type_id": self.session_type_grm,
                "posting_code": "TTSHGRM",
                "programme_code": "GRM",
                "r_year": "R2",
                "reporting_period_id": self.period_id,
                "duration_hours": Decimal("2.0"),
                "is_tracked": False,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.academic_month_boundaries = [
            {
                "id": str(uuid4()),
                "academic_year_label": "AY2026",
                "ay_date_category": "im_subspec",
                "month_label": "Jul-26",
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 31),
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "academic_year_label": "AY2026",
                "ay_date_category": "non_im_subspec",
                "month_label": "Jul-26",
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 31),
                "upload_id": self.upload_id,
                "created_at": now,
                "updated_at": now,
            },
        ]

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})

        if "FROM residents" in sql and "resident_id" not in payload:
            rows = list(self.residents)
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            rows = [row for row in rows if row["programme_code"] in scope_codes]
            if "mcr" in payload:
                rows = [row for row in rows if row["mcr"].upper() == payload["mcr"]]
            if "name" in payload:
                rows = [
                    row
                    for row in rows
                    if payload["name"].strip("%").lower() in row["name"].lower()
                ]
            if "status" in payload:
                rows = [row for row in rows if row["status"].lower() == payload["status"]]
            if "employer_tag" in payload:
                rows = [
                    row
                    for row in rows
                    if (row["employer_tag"] or "").upper() == payload["employer_tag"]
                ]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        if "FROM residents" in sql and "resident_id" in payload:
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            row = next(
                (
                    resident
                    for resident in self.residents
                    if resident["id"] == payload["resident_id"]
                    and resident["programme_code"] in scope_codes
                ),
                None,
            )
            return _FakeMappingResult([row] if row else [])

        if "FROM resident_postings rp" in sql:
            rows = []
            resident_lookup = {resident["id"]: resident for resident in self.residents}
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            for posting in self.resident_postings:
                resident = resident_lookup[posting["resident_id"]]
                if resident["programme_code"] not in scope_codes:
                    continue
                merged = dict(posting)
                merged["resident_mcr"] = resident["mcr"]
                merged["resident_name"] = resident["name"]
                merged["resident_programme_code"] = resident["programme_code"]
                rows.append(merged)

            if "reporting_period_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["reporting_period_id"] == payload["reporting_period_id"]
                ]
            if "posting_code" in payload:
                rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
            if "mcr" in payload:
                rows = [row for row in rows if row["resident_mcr"].upper() == payload["mcr"]]
            if "resident_id" in payload:
                rows = [row for row in rows if row["resident_id"] == payload["resident_id"]]
            if "month_label" in payload:
                rows = [row for row in rows if row["month_label"] == payload["month_label"]]
            if "r_year" in payload:
                rows = [row for row in rows if row["r_year"].upper() == payload["r_year"]]
            if "status" in payload:
                rows = [row for row in rows if row["status"].lower() == payload["status"]]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        if "FROM posting_codes" in sql:
            rows = list(self.posting_codes)
            if "code" in payload:
                token = payload["code"].strip("%").lower()
                rows = [row for row in rows if token in row["code"].lower()]
            if "institution" in payload:
                token = payload["institution"].strip("%").lower()
                rows = [row for row in rows if token in (row["institution"] or "").lower()]
            if "department" in payload:
                token = payload["department"].strip("%").lower()
                rows = [row for row in rows if token in (row["department"] or "").lower()]
            if "is_emergency" in payload:
                rows = [
                    row
                    for row in rows
                    if row["is_emergency"] == payload["is_emergency"]
                ]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        if "FROM session_types" in sql:
            rows = list(self.session_types)
            if "name" in payload:
                token = payload["name"].strip("%").lower()
                rows = [row for row in rows if token in row["name"].lower()]
            if "duration_hours" in payload:
                rows = [
                    row
                    for row in rows
                    if row["duration_hours"] == payload["duration_hours"]
                ]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        if "FROM teaching_targets" in sql:
            rows = list(self.teaching_targets)
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            rows = [row for row in rows if row["programme_code"] in scope_codes]
            if "reporting_period_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["reporting_period_id"] == payload["reporting_period_id"]
                ]
            if "posting_code" in payload:
                rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
            if "r_year" in payload:
                rows = [row for row in rows if row["r_year"].upper() == payload["r_year"]]
            if "session_type_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["session_type_id"] == payload["session_type_id"]
                ]
            if "is_tracked" in payload:
                rows = [
                    row for row in rows if row["is_tracked"] == payload["is_tracked"]
                ]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        if "FROM teaching_name_catalogue" in sql:
            rows = list(self.teaching_name_catalogue)
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            rows = [row for row in rows if row["programme_code"] in scope_codes]
            if "reporting_period_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["reporting_period_id"] == payload["reporting_period_id"]
                ]
            if "posting_code" in payload:
                rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
            if "r_year" in payload:
                rows = [row for row in rows if row["r_year"].upper() == payload["r_year"]]
            if "keyword" in payload:
                token = payload["keyword"].strip("%").lower()
                rows = [row for row in rows if token in row["keyword"].lower()]
            if "session_type_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["session_type_id"] == payload["session_type_id"]
                ]
            if "is_tracked" in payload:
                rows = [
                    row for row in rows if row["is_tracked"] == payload["is_tracked"]
                ]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        if "FROM academic_month_boundaries" in sql:
            rows = list(self.academic_month_boundaries)
            if "ay_date_category" in payload:
                rows = [
                    row
                    for row in rows
                    if row["ay_date_category"] == payload["ay_date_category"]
                ]
            if "month_label" in payload:
                rows = [row for row in rows if row["month_label"] == payload["month_label"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["end_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["start_date"] <= payload["date_to"]]
            if "upload_id" in payload:
                rows = [row for row in rows if row["upload_id"] == payload["upload_id"]]
            return _FakeMappingResult(rows[: int(payload["limit"])])

        raise AssertionError(f"Unhandled SQL in fake upload-output read session: {sql}")


def _build_client_with_session(session: FakeUploadOutputReadSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _admin_headers(scope: str | None = "DR,GRM") -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    return headers


def test_new_upload_output_reads_are_admin_only() -> None:
    session = FakeUploadOutputReadSession()
    client = _build_client_with_session(session)
    headers = {"X-User-Role": "resident", "X-User-Id": str(uuid4())}
    paths = [
        "/admin/residents",
        "/admin/resident-postings",
        "/admin/posting-codes",
        "/admin/session-types",
        "/admin/teaching-targets",
        "/admin/teaching-name-catalogue",
        "/admin/academic-month-boundaries",
    ]
    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 403


def test_residents_and_resident_postings_scoped_reads() -> None:
    session = FakeUploadOutputReadSession()
    client = _build_client_with_session(session)

    residents = client.get("/admin/residents", headers=_admin_headers("DR"))
    assert residents.status_code == 200
    assert [row["programme_code"] for row in residents.json()] == ["DR"]

    postings = client.get("/admin/resident-postings", headers=_admin_headers("DR"))
    assert postings.status_code == 200
    assert {row["resident_programme_code"] for row in postings.json()} == {"DR"}


def test_scoped_reads_reject_out_of_scope_programme_filter() -> None:
    client = _build_client_with_session(FakeUploadOutputReadSession())
    headers = _admin_headers("DR")

    for path in [
        "/admin/residents",
        "/admin/resident-postings",
        "/admin/teaching-targets",
        "/admin/teaching-name-catalogue",
    ]:
        response = client.get(path, headers=headers, params={"programme_code": "GRM"})
        assert response.status_code == 403


def test_programme_scope_null_returns_no_scoped_upload_output_data() -> None:
    client = _build_client_with_session(FakeUploadOutputReadSession())
    headers = _admin_headers(scope=None)

    for path in [
        "/admin/residents",
        "/admin/resident-postings",
        "/admin/teaching-targets",
        "/admin/teaching-name-catalogue",
    ]:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json() == []


def test_resident_detail_scoped_and_404_when_out_of_scope() -> None:
    session = FakeUploadOutputReadSession()
    client = _build_client_with_session(session)

    in_scope_id = session.residents[0]["id"]
    out_scope_id = session.residents[1]["id"]

    ok = client.get(f"/admin/residents/{in_scope_id}", headers=_admin_headers("DR"))
    assert ok.status_code == 200
    assert ok.json()["programme_code"] == "DR"

    missing = client.get(f"/admin/residents/{out_scope_id}", headers=_admin_headers("DR"))
    assert missing.status_code == 404


def test_read_filters_and_limits_work_for_upload_outputs() -> None:
    session = FakeUploadOutputReadSession()
    client = _build_client_with_session(session)
    headers = _admin_headers("DR,GRM")

    residents = client.get(
        "/admin/residents",
        headers=headers,
        params={"programme_code": "DR", "mcr": "m10001a", "limit": 1},
    )
    assert residents.status_code == 200
    assert len(residents.json()) == 1
    assert residents.json()[0]["mcr"] == "M10001A"

    postings = client.get(
        "/admin/resident-postings",
        headers=headers,
        params={
            "reporting_period_id": session.period_id,
            "posting_code": "TTSHDR",
            "status": "active",
            "limit": 1,
        },
    )
    assert postings.status_code == 200
    assert len(postings.json()) == 1
    assert postings.json()[0]["posting_code"] == "TTSHDR"

    targets = client.get(
        "/admin/teaching-targets",
        headers=headers,
        params={
            "reporting_period_id": session.period_id,
            "programme_code": "DR",
            "posting_code": "TTSHDR",
            "r_year": "R3",
        },
    )
    assert targets.status_code == 200
    assert len(targets.json()) == 1
    assert targets.json()[0]["programme_code"] == "DR"

    catalogue = client.get(
        "/admin/teaching-name-catalogue",
        headers=headers,
        params={"keyword": "journal", "is_tracked": "true"},
    )
    assert catalogue.status_code == 200
    assert len(catalogue.json()) == 1
    assert catalogue.json()[0]["keyword"] == "Journal Club"

    assert (
        client.get("/admin/residents", headers=headers, params={"limit": 501}).status_code == 422
    )


def test_global_reference_output_reads_work() -> None:
    session = FakeUploadOutputReadSession()
    client = _build_client_with_session(session)
    headers = _admin_headers("DR")

    posting_codes = client.get(
        "/admin/posting-codes",
        headers=headers,
        params={"department": "Emer", "is_emergency": "true"},
    )
    assert posting_codes.status_code == 200
    assert len(posting_codes.json()) == 1
    assert posting_codes.json()[0]["code"] == "TTSHED"

    session_types = client.get(
        "/admin/session-types",
        headers=headers,
        params={"duration_hours": "2"},
    )
    assert session_types.status_code == 200
    assert len(session_types.json()) == 1
    assert session_types.json()[0]["name"] == "Grand Round [2h]"

    boundaries = client.get(
        "/admin/academic-month-boundaries",
        headers=headers,
        params={
            "ay_date_category": "im_subspec",
            "month_label": "Jul-26",
            "upload_id": session.upload_id,
        },
    )
    assert boundaries.status_code == 200
    assert len(boundaries.json()) == 1
    assert boundaries.json()[0]["ay_date_category"] == "im_subspec"


def test_new_upload_output_resources_are_read_only() -> None:
    session = FakeUploadOutputReadSession()
    client = _build_client_with_session(session)
    headers = _admin_headers("DR")
    resident_id = session.residents[0]["id"]
    paths = [
        "/admin/residents",
        f"/admin/residents/{resident_id}",
        "/admin/resident-postings",
        "/admin/posting-codes",
        "/admin/session-types",
        "/admin/teaching-targets",
        "/admin/teaching-name-catalogue",
        "/admin/academic-month-boundaries",
    ]
    for path in paths:
        assert client.post(path, headers=headers, json={}).status_code in {404, 405}
        assert client.put(path, headers=headers, json={}).status_code in {404, 405}
        assert client.delete(path, headers=headers).status_code in {404, 405}
