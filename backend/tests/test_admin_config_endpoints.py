from __future__ import annotations

from datetime import date, datetime, time, timezone
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


class _FakeScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeAdminConfigSession:
    def __init__(self) -> None:
        now = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.upload_user_id = str(uuid4())

        self.programmes = [
            {
                "id": str(uuid4()),
                "code": "DR",
                "name": "Diagnostic Radiology",
                "classification": "senior",
                "ay_date_category": "non_im_subspec",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "code": "GRM",
                "name": "Geriatric Medicine",
                "classification": "senior",
                "ay_date_category": "im_subspec",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.multi_posting_rules = [
            {
                "id": str(uuid4()),
                "programme_code": "DR",
                "posting_code_1": "TTSHDR",
                "posting_code_2": "KTPHDR",
                "rule_type": "combine",
                "combined_label": "TTSHDR & KTPHDR",
                "main_posting_code": None,
                "exclusion_code": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "programme_code": "GRM",
                "posting_code_1": "TTSHGRM",
                "posting_code_2": "KTPHGRM",
                "rule_type": "combine",
                "combined_label": "TTSHGRM & KTPHGRM",
                "main_posting_code": None,
                "exclusion_code": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.posting_groups = [
            {
                "id": str(uuid4()),
                "group_code": "DR-GROUP",
                "posting_code": "TTSHDR",
                "programme_code": "DR",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "group_code": "GRM-GROUP",
                "posting_code": "TTSHGRM",
                "programme_code": "GRM",
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.upload_logs = [
            {
                "id": str(uuid4()),
                "upload_type": "rdb",
                "uploaded_by": self.upload_user_id,
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": None,
                "status": "success",
                "summary": {"upload_type": "rdb"},
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "upload_type": "ttf",
                "uploaded_by": self.upload_user_id,
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": "DR",
                "status": "success",
                "summary": {"upload_type": "ttf", "programme_code": "DR"},
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "upload_type": "ttf",
                "uploaded_by": self.upload_user_id,
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": "GRM",
                "status": "success",
                "summary": {"upload_type": "ttf", "programme_code": "GRM"},
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.form_f1_records = [
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "mcr": "M12345A",
                "month_label": "Jul-25",
                "status_raw": "Active",
                "is_active": True,
                "promotion_date": date(2026, 1, 6),
                "upload_id": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "reporting_period_id": self.period_id,
                "mcr": "M99999Z",
                "month_label": "Jul-25",
                "status_raw": "Inactive",
                "is_active": False,
                "promotion_date": None,
                "upload_id": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.residents = [
            {"mcr": "M12345A", "programme_code": "DR"},
            {"mcr": "M99999Z", "programme_code": "GRM"},
        ]
        self.weekend_exceptions = [
            {
                "id": str(uuid4()),
                "programme_code": None,
                "posting_code": None,
                "day_type": "sat",
                "start_time_min": time(8, 30),
                "end_time_max": time(10, 30),
                "session_type_id": str(uuid4()),
                "session_type_name": "Urology Teaching [1h]",
                "session_name_pattern": None,
                "mutates_to_session_type_id": str(uuid4()),
                "mutates_to_session_type_name": "National Didactics & Department Teaching [1h]",
                "adjusted_duration_hours": Decimal("1.00"),
                "created_at": now,
                "updated_at": now,
            }
        ]

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})

        if "FROM programmes" in sql:
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            rows = (
                [row for row in self.programmes if row["code"] in scope_codes]
                if scope_codes
                else list(self.programmes)
            )
            if "programme_code" in payload:
                rows = [row for row in rows if row["code"] == payload["programme_code"]]
            return _FakeMappingResult(rows)

        if "FROM multi_posting_rules" in sql:
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            rows = (
                [row for row in self.multi_posting_rules if row["programme_code"] in scope_codes]
                if scope_codes
                else list(self.multi_posting_rules)
            )
            if "programme_code" in payload:
                rows = [row for row in rows if row["programme_code"] == payload["programme_code"]]
            if "rule_type" in payload:
                rows = [row for row in rows if row["rule_type"] == payload["rule_type"]]
            return _FakeMappingResult(rows)

        if "FROM posting_groups" in sql:
            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            rows = (
                [row for row in self.posting_groups if row["programme_code"] in scope_codes]
                if scope_codes
                else list(self.posting_groups)
            )
            if "group_code" in payload:
                rows = [row for row in rows if row["group_code"] == payload["group_code"]]
            return _FakeMappingResult(rows)

        if "FROM upload_logs" in sql:
            if "1 = 0" in sql:
                if "COUNT(*)" in sql:
                    return _FakeScalarResult(0)
                return _FakeMappingResult([])
            rows = list(self.upload_logs)
            if "upload_type" in payload:
                rows = [row for row in rows if row["upload_type"] == payload["upload_type"]]
            if "reporting_period_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["reporting_period_id"] == payload["reporting_period_id"]
                ]
            if "programme_code" in payload:
                rows = [row for row in rows if row["programme_code"] == payload["programme_code"]]
            else:
                scope_codes = {
                    value
                    for key, value in payload.items()
                    if key.startswith("scope_programme_code_")
                }
                if scope_codes:
                    rows = [
                        row
                        for row in rows
                        if row["upload_type"] == "ttf"
                        and row["programme_code"] in scope_codes
                    ]
                else:
                    rows = []
            if "COUNT(*)" in sql:
                return _FakeScalarResult(len(rows))
            limit = int(payload.get("limit", 20))
            offset = int(payload.get("offset", 0))
            return _FakeMappingResult(rows[offset : offset + limit])

        if "FROM form_f1_records f" in sql:
            rows = list(self.form_f1_records)
            if "reporting_period_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["reporting_period_id"] == payload["reporting_period_id"]
                ]
            if "mcr" in payload:
                rows = [row for row in rows if row["mcr"].upper() == payload["mcr"]]
            if "month_label" in payload:
                rows = [row for row in rows if row["month_label"] == payload["month_label"]]
            if "is_active" in payload:
                rows = [row for row in rows if row["is_active"] == payload["is_active"]]

            scope_codes = {
                value for key, value in payload.items() if key.startswith("programme_code_")
            }
            scoped_mcr = {
                resident["mcr"].upper()
                for resident in self.residents
                if resident["programme_code"] in scope_codes
            }
            rows = [row for row in rows if row["mcr"].upper() in scoped_mcr]
            return _FakeMappingResult(rows)

        if "FROM weekend_exceptions" in sql:
            return _FakeMappingResult(list(self.weekend_exceptions))

        if "FROM reporting_periods" in sql:
            now = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
            rows = [
                {
                    "id": self.period_id,
                    "label": "Jul - Dec 2025",
                    "start_date": date(2025, 7, 1),
                    "end_date": date(2025, 12, 31),
                    "status": "active",
                    "activate_on": None,
                    "deactivate_on": None,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
            return _FakeMappingResult(rows)

        if "FROM public_holidays" in sql:
            now = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
            rows = [
                {
                    "id": str(uuid4()),
                    "holiday_date": date(2026, 8, 9),
                    "name": "National Day",
                    "day_of_week": "Sunday",
                    "year": 2026,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
            return _FakeMappingResult(rows)

        if "FROM loa_types" in sql:
            now = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
            rows = [
                {
                    "id": str(uuid4()),
                    "code": "Annual Leaves",
                    "description": "Annual leave",
                    "created_at": now,
                    "updated_at": now,
                }
            ]
            return _FakeMappingResult(rows)

        if "FROM global_session_types" in sql:
            now = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
            rows = [
                {
                    "id": str(uuid4()),
                    "name": "Department Meeting [1h]",
                    "duration_hours": 1.0,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
            return _FakeMappingResult(rows)

        raise AssertionError(f"Unhandled SQL in fake admin-config session: {sql}")


def _build_client_with_session(session: FakeAdminConfigSession) -> TestClient:
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


def _master_admin_headers(scope: str | None = "DR,GRM") -> dict[str, str]:
    headers = _admin_headers(scope)
    headers["X-Admin-Level"] = "master"
    return headers


def test_admin_only_access_rejects_non_admin() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get(
        "/admin/programmes",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": str(uuid4()),
        },
    )
    assert response.status_code == 403


def test_all_phase3_read_endpoints_reject_non_admin() -> None:
    session = FakeAdminConfigSession()
    client = _build_client_with_session(session)
    headers = {
        "X-User-Role": "resident",
        "X-User-Id": str(uuid4()),
    }
    paths = [
        "/admin/reporting-periods",
        "/admin/public-holidays",
        "/admin/programmes",
        "/admin/loa-types",
        "/admin/multi-posting-rules",
        "/admin/posting-groups",
        "/admin/weekend-exceptions",
        "/admin/global-session-types",
        "/admin/upload-logs",
        "/admin/form-f1-records",
        "/admin/residents",
        "/admin/resident-postings",
        "/admin/posting-codes",
        "/admin/session-types",
        "/admin/teaching-targets",
        "/admin/academic-month-boundaries",
        f"/admin/residents/{uuid4()}",
    ]
    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 403


def test_master_admin_lists_all_programmes() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get("/admin/programmes", headers=_master_admin_headers("DR"))
    assert response.status_code == 200
    body = response.json()
    assert [row["code"] for row in body] == ["DR", "GRM"]


def test_master_admin_lists_all_posting_groups_without_scope_inference() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get("/admin/posting-groups", headers=_master_admin_headers(scope=None))
    assert response.status_code == 200
    assert {row["programme_code"] for row in response.json()} == {"DR", "GRM"}


def test_master_admin_lists_all_multi_posting_rules_without_scope_inference() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get("/admin/multi-posting-rules", headers=_master_admin_headers(scope=None))
    assert response.status_code == 200
    assert {row["programme_code"] for row in response.json()} == {"DR", "GRM"}


def test_programme_pc_cannot_read_global_programmes_config() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get("/admin/programmes", headers=_admin_headers("DR"))
    assert response.status_code == 403


def test_programme_pc_can_read_reporting_periods_for_ttf_upload_selection() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get("/admin/reporting-periods", headers=_admin_headers("DR"))

    assert response.status_code == 200
    assert [row["label"] for row in response.json()] == ["Jul - Dec 2025"]


def test_non_admin_identities_cannot_read_reporting_periods() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    headers_by_role = [
        {
            "X-User-Role": "secretary",
            "X-User-Id": str(uuid4()),
            "X-User-Site": "TTSHGerMed",
        },
        {
            "X-User-Role": "resident",
            "X-User-Id": str(uuid4()),
        },
        {
            "X-User-Role": "external_resident",
            "X-User-Id": str(uuid4()),
        },
    ]

    responses = [
        client.get("/admin/reporting-periods", headers=headers)
        for headers in headers_by_role
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]


def test_programme_scope_null_returns_no_scoped_data() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    headers = _admin_headers(scope=None)

    programmes = client.get("/admin/programmes", headers=headers)
    rules = client.get("/admin/multi-posting-rules", headers=headers)
    groups = client.get("/admin/posting-groups", headers=headers)
    logs = client.get("/admin/upload-logs", headers=headers)
    weekend = client.get("/admin/weekend-exceptions", headers=headers)
    periods = client.get("/admin/reporting-periods", headers=headers)
    holidays = client.get("/admin/public-holidays", headers=headers)
    loa_types = client.get("/admin/loa-types", headers=headers)
    global_types = client.get("/admin/global-session-types", headers=headers)

    assert programmes.status_code == 403
    assert rules.status_code == 200
    assert groups.status_code == 200
    assert logs.status_code == 200
    assert weekend.status_code == 403
    assert periods.status_code == 403
    assert holidays.status_code == 403
    assert loa_types.status_code == 403
    assert global_types.status_code == 403
    assert rules.json() == []
    assert groups.json() == []
    assert logs.json()["items"] == []
    assert logs.json()["total"] == 0


def test_programme_filter_must_be_in_scope() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get(
        "/admin/programmes",
        headers=_admin_headers("DR"),
        params={"programme_code": "GRM"},
    )
    assert response.status_code == 403


def test_upload_logs_list_works_with_scope() -> None:
    session = FakeAdminConfigSession()
    client = _build_client_with_session(session)
    response = client.get(
        "/admin/upload-logs",
        headers=_admin_headers("DR"),
        params={
            "upload_type": "ttf",
            "reporting_period_id": session.period_id,
            "limit": 20,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["upload_type"] == "ttf"
    assert body["items"][0]["programme_code"] == "DR"


def test_weekend_exceptions_list_includes_session_type_display_names() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    response = client.get("/admin/weekend-exceptions", headers=_master_admin_headers("DR"))

    assert response.status_code == 200
    body = response.json()
    assert body[0]["session_type_id"]
    assert body[0]["session_type_name"] == "Urology Teaching [1h]"
    assert body[0]["mutates_to_session_type_id"]
    assert body[0]["mutates_to_session_type_name"] == (
        "National Didactics & Department Teaching [1h]"
    )
    assert body[0]["adjusted_duration_hours"] == "1.00"


def test_form_f1_records_list_works_with_scope_and_filters() -> None:
    session = FakeAdminConfigSession()
    client = _build_client_with_session(session)
    response = client.get(
        "/admin/form-f1-records",
        headers=_admin_headers("DR"),
        params={
            "reporting_period_id": session.period_id,
            "mcr": "m12345a",
            "is_active": "true",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["mcr"] == "M12345A"
    assert body[0]["is_active"] is True


def test_multi_posting_rules_and_posting_groups_scoped_by_programme_code() -> None:
    client = _build_client_with_session(FakeAdminConfigSession())
    headers = _admin_headers("DR")

    rules = client.get(
        "/admin/multi-posting-rules",
        headers=headers,
        params={"programme_code": "DR"},
    )
    groups = client.get(
        "/admin/posting-groups",
        headers=headers,
        params={"programme_code": "DR"},
    )

    assert rules.status_code == 200
    assert groups.status_code == 200
    assert {row["programme_code"] for row in rules.json()} == {"DR"}
    assert {row["programme_code"] for row in groups.json()} == {"DR"}
