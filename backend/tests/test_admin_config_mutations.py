from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.middleware.errors import install_error_handlers
from app.routers import admin


class _FakeMutationResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar: object | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "_FakeMutationResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError("Expected exactly one row")
        return self._rows[0]

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError("Expected at most one row")
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class FakeMutationSession:
    def __init__(self) -> None:
        self.now = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)

        self.reporting_periods: list[dict] = [
            {
                "id": str(uuid4()),
                "label": "Jan - June 2026",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 6, 30),
                "status": "open",
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.reporting_period_dependencies: dict[str, dict[str, int]] = {}
        self.public_holidays: list[dict] = []
        self.programmes: list[dict] = [
            {
                "id": str(uuid4()),
                "code": "DR",
                "name": "Diagnostic Radiology",
                "classification": "senior",
                "ay_date_category": "non_im_subspec",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
                "created_at": self.now,
                "updated_at": self.now,
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
                "created_at": self.now,
                "updated_at": self.now,
            },
        ]
        self.loa_types: list[dict] = []
        self.posting_codes = {"TTSHDR", "KTPHDR", "TTSHRespi", "TTSHRespi(MICU)"}
        self.session_type_ids = {str(uuid4())}
        self.multi_posting_rules: list[dict] = []
        self.posting_groups: list[dict] = []
        self.weekend_exceptions: list[dict] = []
        self.global_session_types: list[dict] = [
            {
                "id": str(uuid4()),
                "name": "Department Meeting [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": True,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.teaching_events: list[dict] = [{"teaching_name": "Department Meeting [1h]"}]

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "SELECT 1 FROM posting_codes" in sql:
            code = payload["code"]
            return _FakeMutationResult(scalar=1 if code in self.posting_codes else None)

        if "SELECT 1 FROM programmes" in sql:
            code = payload["code"]
            return _FakeMutationResult(scalar=1 if code in {row["code"] for row in self.programmes} else None)

        if "SELECT 1 FROM session_types" in sql:
            sid = payload["session_type_id"]
            return _FakeMutationResult(scalar=1 if sid in self.session_type_ids else None)

        if "INSERT INTO reporting_periods" in sql:
            if any(row["label"] == payload["label"] for row in self.reporting_periods):
                raise IntegrityError("insert reporting_periods", payload, None)
            row = {
                "id": str(uuid4()),
                "label": payload["label"],
                "start_date": payload["start_date"],
                "end_date": payload["end_date"],
                "status": "open",
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.reporting_periods.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, label, start_date, end_date, status, created_at, updated_at" in sql and "FROM reporting_periods" in sql:
            period = next(
                (row for row in self.reporting_periods if row["id"] == payload["id"]),
                None,
            )
            return _FakeMutationResult(rows=[period] if period else [])

        if "UPDATE reporting_periods" in sql:
            period = next(
                (row for row in self.reporting_periods if row["id"] == payload["id"]),
                None,
            )
            if period is None:
                return _FakeMutationResult(rows=[])
            if payload.get("label") is not None:
                duplicate = any(
                    row["label"] == payload["label"] and row["id"] != period["id"]
                    for row in self.reporting_periods
                )
                if duplicate:
                    raise IntegrityError("update reporting_periods", payload, None)
                period["label"] = payload["label"]
            if payload.get("start_date") is not None:
                period["start_date"] = payload["start_date"]
            if payload.get("end_date") is not None:
                period["end_date"] = payload["end_date"]
            if payload.get("status") is not None:
                period["status"] = payload["status"]
            period["updated_at"] = self.now
            return _FakeMutationResult(rows=[period])

        if "SELECT id FROM reporting_periods" in sql:
            period = next(
                (row for row in self.reporting_periods if row["id"] == payload["id"]),
                None,
            )
            return _FakeMutationResult(rows=[{"id": period["id"]}] if period else [])

        if "FROM upload_logs" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("upload_logs", 0)}])

        if "FROM resident_postings" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("resident_postings", 0)}])

        if "FROM teaching_targets" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("teaching_targets", 0)}])

        if "FROM teaching_name_catalogue" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("teaching_name_catalogue", 0)}])

        if "FROM form_f1_records" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("form_f1_records", 0)}])

        if "FROM academic_month_boundaries" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("academic_month_boundaries", 0)}])

        if "FROM period_snapshots" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("period_snapshots", 0)}])

        if "FROM clawback_records" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("clawback_records", 0)}])

        if "FROM surplus_ledger" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("surplus_ledger", 0)}])

        if "DELETE FROM reporting_periods" in sql:
            before = len(self.reporting_periods)
            self.reporting_periods = [r for r in self.reporting_periods if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.reporting_periods))

        if "INSERT INTO public_holidays" in sql:
            existing = next(
                (
                    row
                    for row in self.public_holidays
                    if row["holiday_date"] == payload["holiday_date"]
                ),
                None,
            )
            if existing is None:
                existing = {
                    "id": str(uuid4()),
                    "holiday_date": payload["holiday_date"],
                    "name": payload["name"],
                    "day_of_week": payload["day_of_week"],
                    "year": payload["year"],
                    "created_at": self.now,
                    "updated_at": self.now,
                }
                self.public_holidays.append(existing)
            else:
                existing["name"] = payload["name"]
                existing["day_of_week"] = payload["day_of_week"]
                existing["year"] = payload["year"]
                existing["updated_at"] = self.now
            return _FakeMutationResult(rows=[existing])

        if "UPDATE public_holidays" in sql:
            existing = next(
                (row for row in self.public_holidays if row["id"] == payload["id"]),
                None,
            )
            if existing is None:
                return _FakeMutationResult(rows=[])
            duplicate = any(
                row["holiday_date"] == payload["holiday_date"] and row["id"] != existing["id"]
                for row in self.public_holidays
            )
            if duplicate:
                raise IntegrityError("update public_holidays", payload, None)
            existing["holiday_date"] = payload["holiday_date"]
            existing["name"] = payload["name"]
            existing["day_of_week"] = payload["day_of_week"]
            existing["year"] = payload["year"]
            existing["updated_at"] = self.now
            return _FakeMutationResult(rows=[existing])

        if "DELETE FROM public_holidays" in sql:
            before = len(self.public_holidays)
            self.public_holidays = [r for r in self.public_holidays if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.public_holidays))

        if "UPDATE programmes" in sql:
            programme = next(
                (row for row in self.programmes if row["code"] == payload["programme_code"]),
                None,
            )
            if programme is None:
                return _FakeMutationResult(rows=[])
            if payload.get("r_year_required") is not None:
                programme["r_year_required"] = payload["r_year_required"]
            if payload.get("is_subspecialty") is not None:
                programme["is_subspecialty"] = payload["is_subspecialty"]
            if payload.get("rdb_alias_is_set"):
                programme["rdb_alias"] = payload.get("rdb_alias")
            programme["updated_at"] = self.now
            return _FakeMutationResult(rows=[programme])

        if "INSERT INTO loa_types" in sql:
            if any(row["code"] == payload["code"] for row in self.loa_types):
                raise IntegrityError("insert loa_types", payload, None)
            row = {
                "id": str(uuid4()),
                "code": payload["code"],
                "description": payload["description"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.loa_types.append(row)
            return _FakeMutationResult(rows=[row])

        if "UPDATE loa_types" in sql:
            row = next((item for item in self.loa_types if item["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            if payload.get("code") is not None and any(
                item["code"] == payload["code"] and item["id"] != row["id"]
                for item in self.loa_types
            ):
                raise IntegrityError("update loa_types", payload, None)
            if payload.get("code") is not None:
                row["code"] = payload["code"]
            row["description"] = payload.get("description")
            row["updated_at"] = self.now
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM loa_types" in sql:
            before = len(self.loa_types)
            self.loa_types = [r for r in self.loa_types if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.loa_types))

        if "SELECT 1" in sql and "FROM multi_posting_rules" in sql:
            found = next(
                (
                    row
                    for row in self.multi_posting_rules
                    if row["programme_code"] == payload["programme_code"]
                    and row["posting_code_1"] == payload["posting_code_1"]
                    and row["posting_code_2"] == payload["posting_code_2"]
                    and row["rule_type"] == payload["rule_type"]
                    and (payload.get("exclude_id") is None or row["id"] != payload.get("exclude_id"))
                ),
                None,
            )
            return _FakeMutationResult(scalar=1 if found else None)

        if "INSERT INTO multi_posting_rules" in sql:
            row = {
                "id": str(uuid4()),
                "programme_code": payload["programme_code"],
                "posting_code_1": payload["posting_code_1"],
                "posting_code_2": payload["posting_code_2"],
                "rule_type": payload["rule_type"],
                "combined_label": payload["combined_label"],
                "main_posting_code": payload["main_posting_code"],
                "exclusion_code": payload["exclusion_code"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.multi_posting_rules.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, programme_code FROM multi_posting_rules" in sql:
            row = next((r for r in self.multi_posting_rules if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "UPDATE multi_posting_rules" in sql:
            row = next((r for r in self.multi_posting_rules if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            row.update(
                {
                    "programme_code": payload["programme_code"],
                    "posting_code_1": payload["posting_code_1"],
                    "posting_code_2": payload["posting_code_2"],
                    "rule_type": payload["rule_type"],
                    "combined_label": payload["combined_label"],
                    "main_posting_code": payload["main_posting_code"],
                    "exclusion_code": payload["exclusion_code"],
                    "updated_at": self.now,
                }
            )
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM multi_posting_rules" in sql:
            before = len(self.multi_posting_rules)
            self.multi_posting_rules = [r for r in self.multi_posting_rules if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.multi_posting_rules))

        if "INSERT INTO posting_groups" in sql:
            duplicate = any(
                row["posting_code"] == payload["posting_code"]
                and row["programme_code"] == payload["programme_code"]
                for row in self.posting_groups
            )
            if duplicate:
                raise IntegrityError("insert posting_groups", payload, None)
            row = {
                "id": str(uuid4()),
                "group_code": payload["group_code"],
                "posting_code": payload["posting_code"],
                "programme_code": payload["programme_code"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.posting_groups.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, programme_code FROM posting_groups" in sql:
            row = next((r for r in self.posting_groups if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "UPDATE posting_groups" in sql:
            row = next((r for r in self.posting_groups if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            duplicate = any(
                item["posting_code"] == payload["posting_code"]
                and item["programme_code"] == payload["programme_code"]
                and item["id"] != payload["id"]
                for item in self.posting_groups
            )
            if duplicate:
                raise IntegrityError("update posting_groups", payload, None)
            row.update(
                {
                    "group_code": payload["group_code"],
                    "posting_code": payload["posting_code"],
                    "programme_code": payload["programme_code"],
                    "updated_at": self.now,
                }
            )
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM posting_groups" in sql:
            before = len(self.posting_groups)
            self.posting_groups = [r for r in self.posting_groups if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.posting_groups))

        if "INSERT INTO weekend_exceptions" in sql:
            row = {
                "id": str(uuid4()),
                "programme_code": payload["programme_code"],
                "posting_code": payload["posting_code"],
                "day_type": payload["day_type"],
                "start_time_min": payload["start_time_min"],
                "end_time_max": payload["end_time_max"],
                "session_type_id": payload["session_type_id"],
                "session_name_pattern": payload["session_name_pattern"],
                "mutates_to_session_type_id": payload["mutates_to_session_type_id"],
                "adjusted_duration_hours": payload["adjusted_duration_hours"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.weekend_exceptions.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, programme_code FROM weekend_exceptions" in sql:
            row = next((r for r in self.weekend_exceptions if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "UPDATE weekend_exceptions" in sql:
            row = next((r for r in self.weekend_exceptions if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            row.update(
                {
                    "programme_code": payload["programme_code"],
                    "posting_code": payload["posting_code"],
                    "day_type": payload["day_type"],
                    "start_time_min": payload["start_time_min"],
                    "end_time_max": payload["end_time_max"],
                    "session_type_id": payload["session_type_id"],
                    "session_name_pattern": payload["session_name_pattern"],
                    "mutates_to_session_type_id": payload["mutates_to_session_type_id"],
                    "adjusted_duration_hours": payload["adjusted_duration_hours"],
                    "updated_at": self.now,
                }
            )
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM weekend_exceptions" in sql:
            before = len(self.weekend_exceptions)
            self.weekend_exceptions = [r for r in self.weekend_exceptions if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.weekend_exceptions))

        if "INSERT INTO global_session_types" in sql:
            if any(row["name"] == payload["name"] for row in self.global_session_types):
                raise IntegrityError("insert global_session_types", payload, None)
            row = {
                "id": str(uuid4()),
                "name": payload["name"],
                "duration_hours": payload["duration_hours"],
                "is_active": payload["is_active"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.global_session_types.append(row)
            return _FakeMutationResult(rows=[row])

        if "UPDATE global_session_types" in sql:
            row = next((r for r in self.global_session_types if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            new_name = payload["name"] if payload.get("name") is not None else row["name"]
            if any(
                item["name"] == new_name and item["id"] != payload["id"]
                for item in self.global_session_types
            ):
                raise IntegrityError("update global_session_types", payload, None)
            if payload.get("name") is not None:
                row["name"] = payload["name"]
            if payload.get("duration_hours") is not None:
                row["duration_hours"] = payload["duration_hours"]
            if payload.get("is_active") is not None:
                row["is_active"] = payload["is_active"]
            row["updated_at"] = self.now
            return _FakeMutationResult(rows=[row])

        if "SELECT id, name FROM global_session_types" in sql:
            row = next((r for r in self.global_session_types if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "SELECT 1" in sql and "FROM teaching_events" in sql:
            found = any(row["teaching_name"] == payload["name"] for row in self.teaching_events)
            return _FakeMutationResult(scalar=1 if found else None)

        if "DELETE FROM global_session_types" in sql:
            before = len(self.global_session_types)
            self.global_session_types = [r for r in self.global_session_types if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.global_session_types))

        raise AssertionError(f"Unhandled SQL: {sql}")


def _build_client_with_session(session: FakeMutationSession) -> TestClient:
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


def test_admin_only_mutation_access_rejects_non_admin() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": str(uuid4()),
        },
        json={"code": "Study Leave", "description": "x"},
    )
    assert response.status_code == 403


def test_all_phase3_mutation_endpoints_reject_non_admin() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    headers = {
        "X-User-Role": "resident",
        "X-User-Id": str(uuid4()),
    }
    period_id = session.reporting_periods[0]["id"]
    global_type_id = session.global_session_types[0]["id"]
    paths_with_payloads = [
        ("POST", "/admin/reporting-periods", {"label": "Jul - Dec 2026", "start_date": "2026-07-01", "end_date": "2026-12-31"}),
        ("PUT", f"/admin/reporting-periods/{period_id}", {"status": "closed"}),
        ("DELETE", f"/admin/reporting-periods/{period_id}", None),
        ("POST", "/admin/public-holidays", {"holiday_date": "2026-08-09", "name": "National Day", "day_of_week": "Sunday", "year": 2026}),
        ("PUT", f"/admin/public-holidays/{uuid4()}", {"holiday_date": "2026-08-09", "name": "National Day", "day_of_week": "Sunday", "year": 2026}),
        ("DELETE", f"/admin/public-holidays/{uuid4()}", None),
        ("PUT", "/admin/programmes/DR", {"r_year_required": True}),
        ("POST", "/admin/loa-types", {"code": "Study Leave", "description": "x"}),
        ("PUT", f"/admin/loa-types/{uuid4()}", {"code": "Study Leave", "description": "x"}),
        ("DELETE", f"/admin/loa-types/{uuid4()}", None),
        ("POST", "/admin/multi-posting-rules", {"programme_code": "DR", "posting_code_1": "TTSHDR", "posting_code_2": "KTPHDR", "rule_type": "combine", "combined_label": "TTSHDR & KTPHDR"}),
        ("PUT", f"/admin/multi-posting-rules/{uuid4()}", {"programme_code": "DR", "posting_code_1": "TTSHDR", "posting_code_2": "KTPHDR", "rule_type": "combine", "combined_label": "TTSHDR & KTPHDR"}),
        ("DELETE", f"/admin/multi-posting-rules/{uuid4()}", None),
        ("POST", "/admin/posting-groups", {"group_code": "DR-GROUP", "posting_code": "TTSHRespi", "programme_code": "DR"}),
        ("PUT", f"/admin/posting-groups/{uuid4()}", {"group_code": "DR-GROUP", "posting_code": "TTSHRespi", "programme_code": "DR"}),
        ("DELETE", f"/admin/posting-groups/{uuid4()}", None),
        ("POST", "/admin/weekend-exceptions", {"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"}),
        ("PUT", f"/admin/weekend-exceptions/{uuid4()}", {"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"}),
        ("DELETE", f"/admin/weekend-exceptions/{uuid4()}", None),
        ("POST", "/admin/global-session-types", {"name": "Dept Meeting [1h]", "duration_hours": 1.0, "is_active": True}),
        ("PUT", f"/admin/global-session-types/{global_type_id}", {"is_active": False}),
        ("DELETE", f"/admin/global-session-types/{global_type_id}", None),
    ]

    for method, path, payload in paths_with_payloads:
        if method == "POST":
            response = client.post(path, headers=headers, json=payload or {})
        elif method == "PUT":
            response = client.put(path, headers=headers, json=payload or {})
        else:
            response = client.delete(path, headers=headers)
        assert response.status_code == 403


def test_programme_scope_enforced_for_scoped_mutations() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "GRM",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert response.status_code == 403


def test_null_scope_cannot_mutate_scoped_resources() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/posting-groups",
        headers=_admin_headers(scope=None),
        json={
            "group_code": "DR-GROUP",
            "posting_code": "TTSHRespi",
            "programme_code": "DR",
        },
    )
    assert response.status_code == 403


def test_master_admin_can_mutate_posting_groups_without_programme_scope() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/posting-groups",
        headers=_master_admin_headers(scope=None),
        json={
            "group_code": "DR-GROUP",
            "posting_code": "TTSHRespi",
            "programme_code": "DR",
        },
    )
    assert created.status_code == 200
    posting_group_id = created.json()["id"]

    updated = client.put(
        f"/admin/posting-groups/{posting_group_id}",
        headers=_master_admin_headers(scope=None),
        json={
            "group_code": "DR-GROUP-UPDATED",
            "posting_code": "TTSHRespi(MICU)",
            "programme_code": "DR",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["group_code"] == "DR-GROUP-UPDATED"
    assert updated.json()["posting_code"] == "TTSHRespi(MICU)"

    deleted = client.delete(
        f"/admin/posting-groups/{posting_group_id}",
        headers=_master_admin_headers(scope=None),
    )
    assert deleted.status_code == 204


def test_null_scope_cannot_mutate_reporting_periods() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/reporting-periods",
        headers=_admin_headers(scope=None),
        json={
            "label": "Jul - Dec 2026",
            "start_date": "2026-07-01",
            "end_date": "2026-12-31",
        },
    )
    assert response.status_code == 403


def test_reporting_period_create_update_delete_crud() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    created = client.post(
        "/admin/reporting-periods",
        headers=_master_admin_headers("DR"),
        json={
            "label": "Jul - Dec 2026",
            "start_date": "2026-07-01",
            "end_date": "2026-12-31",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["label"] == "Jul - Dec 2026"
    assert body["status"] == "open"

    duplicate = client.post(
        "/admin/reporting-periods",
        headers=_master_admin_headers("DR"),
        json={
            "label": "Jul - Dec 2026",
            "start_date": "2026-07-01",
            "end_date": "2026-12-31",
        },
    )
    assert duplicate.status_code == 409

    updated = client.put(
        f"/admin/reporting-periods/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={"label": "H2 2026", "status": "closed"},
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "H2 2026"
    assert updated.json()["status"] == "closed"

    deleted = client.delete(
        f"/admin/reporting-periods/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert deleted.status_code == 204


def test_reporting_period_delete_returns_dependency_counts() -> None:
    session = FakeMutationSession()
    period_id = session.reporting_periods[0]["id"]
    session.reporting_period_dependencies[period_id] = {
        "upload_logs": 2,
        "resident_postings": 3,
        "teaching_targets": 1,
        "academic_month_boundaries": 4,
    }
    client = _build_client_with_session(session)

    response = client.delete(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Reporting period is in use and cannot be deleted"
    assert body["metadata"]["dependencies"] == {
        "upload_logs": 2,
        "resident_postings": 3,
        "teaching_targets": 1,
        "academic_month_boundaries": 4,
    }


def test_public_holiday_upsert_is_idempotent() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "holiday_date": "2026-08-09",
        "name": "National Day",
        "day_of_week": "Sunday",
        "year": 2026,
    }
    first = client.post("/admin/public-holidays", headers=_master_admin_headers("DR"), json=payload)
    assert first.status_code == 200
    first_id = first.json()["id"]

    payload["name"] = "National Day Updated"
    second = client.post("/admin/public-holidays", headers=_master_admin_headers("DR"), json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == first_id
    assert second.json()["name"] == "National Day Updated"
    assert second.json()["day_of_week"] == "Sunday"
    assert second.json()["year"] == 2026


def test_public_holiday_update_recomputes_day_and_year() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={
            "holiday_date": "2026-08-09",
            "name": "National Day",
            "day_of_week": "Wrong",
            "year": 1999,
        },
    )
    assert created.status_code == 200
    holiday_id = created.json()["id"]
    assert created.json()["day_of_week"] == "Sunday"
    assert created.json()["year"] == 2026

    updated = client.put(
        f"/admin/public-holidays/{holiday_id}",
        headers=_master_admin_headers("DR"),
        json={
            "holiday_date": "2026-08-10",
            "name": "National Day observed",
            "day_of_week": "Wrong",
            "year": 1999,
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "National Day observed"
    assert body["holiday_date"] == "2026-08-10"
    assert body["day_of_week"] == "Monday"
    assert body["year"] == 2026


def test_public_holiday_empty_name_rejected() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={"holiday_date": "2026-08-09", "name": "   "},
    )

    assert response.status_code == 422


def test_public_holiday_delete_succeeds() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={"holiday_date": "2026-08-09", "name": "National Day"},
    )
    assert created.status_code == 200

    deleted = client.delete(
        f"/admin/public-holidays/{created.json()['id']}",
        headers=_master_admin_headers("DR"),
    )

    assert deleted.status_code == 204


def test_null_scope_cannot_mutate_public_holidays() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/public-holidays",
        headers=_admin_headers(scope=None),
        json={"holiday_date": "2026-08-09", "name": "National Day"},
    )
    assert response.status_code == 403


def test_null_scope_cannot_mutate_loa_types() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    loa_id = str(uuid4())

    create_response = client.post(
        "/admin/loa-types",
        headers=_admin_headers(scope=None),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    update_response = client.put(
        f"/admin/loa-types/{loa_id}",
        headers=_admin_headers(scope=None),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    delete_response = client.delete(
        f"/admin/loa-types/{loa_id}",
        headers=_admin_headers(scope=None),
    )

    assert create_response.status_code == 403
    assert update_response.status_code == 403
    assert delete_response.status_code == 403


def test_programme_pc_cannot_mutate_global_config_endpoints() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    period_id = session.reporting_periods[0]["id"]
    global_type_id = session.global_session_types[0]["id"]

    attempts = [
        client.post(
            "/admin/reporting-periods",
            headers=_admin_headers("DR"),
            json={"label": "Jul - Dec 2026", "start_date": "2026-07-01", "end_date": "2026-12-31"},
        ),
        client.post(
            "/admin/public-holidays",
            headers=_admin_headers("DR"),
            json={"holiday_date": "2026-08-09", "name": "National Day"},
        ),
        client.put(
            "/admin/programmes/DR",
            headers=_admin_headers("DR"),
            json={"r_year_required": False},
        ),
        client.post(
            "/admin/loa-types",
            headers=_admin_headers("DR"),
            json={"code": "Study Leave", "description": "Academic study leave"},
        ),
        client.post(
            "/admin/weekend-exceptions",
            headers=_admin_headers("DR"),
            json={"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"},
        ),
        client.put(
            f"/admin/global-session-types/{global_type_id}",
            headers=_admin_headers("DR"),
            json={"is_active": False},
        ),
        client.delete(f"/admin/reporting-periods/{period_id}", headers=_admin_headers("DR")),
    ]

    assert [response.status_code for response in attempts] == [403, 403, 403, 403, 403, 403, 403]


def test_weekend_exception_crud_allows_nullable_clears_and_both_day_type() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    session_type_id = next(iter(session.session_type_ids))

    created = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHDR",
            "day_type": "both",
            "start_time_min": "08:30:00",
            "end_time_max": "10:30:00",
            "session_type_id": session_type_id,
            "session_name_pattern": "Weekend Teaching",
            "mutates_to_session_type_id": session_type_id,
            "adjusted_duration_hours": "1.0",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["day_type"] == "both"
    assert body["session_name_pattern"] == "Weekend Teaching"

    updated = client.put(
        f"/admin/weekend-exceptions/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": None,
            "posting_code": None,
            "day_type": "sun",
            "start_time_min": None,
            "end_time_max": None,
            "session_type_id": None,
            "session_name_pattern": "   ",
            "mutates_to_session_type_id": None,
            "adjusted_duration_hours": None,
        },
    )
    assert updated.status_code == 200
    cleared = updated.json()
    assert cleared["programme_code"] is None
    assert cleared["posting_code"] is None
    assert cleared["session_name_pattern"] is None
    assert cleared["session_type_id"] is None
    assert cleared["mutates_to_session_type_id"] is None
    assert cleared["adjusted_duration_hours"] is None

    deleted = client.delete(
        f"/admin/weekend-exceptions/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert deleted.status_code == 204
    assert session.weekend_exceptions == []


def test_weekend_exception_validation_rejects_bad_references_and_mutation_shape() -> None:
    client = _build_client_with_session(FakeMutationSession())

    bad_day = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "fri"},
    )
    bad_programme = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "NOPE", "posting_code": "TTSHDR", "day_type": "sat"},
    )
    bad_posting = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "DR", "posting_code": "UNKNOWN", "day_type": "sat"},
    )
    missing_mutation_target = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHDR",
            "day_type": "sat",
            "adjusted_duration_hours": "1.0",
        },
    )

    assert bad_day.status_code == 422
    assert bad_programme.status_code == 422
    assert bad_posting.status_code == 422
    assert missing_mutation_target.status_code == 422


def test_global_session_type_crud_duplicate_delete_guard_and_inactive_update() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)

    created = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "1.0", "is_active": True},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "Smoke Global Teaching [1h]"
    assert body["is_active"] is True

    duplicate = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "1.0", "is_active": True},
    )
    assert duplicate.status_code == 409

    updated = client.put(
        f"/admin/global-session-types/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={"duration_hours": "1.5", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["duration_hours"] == "1.5"
    assert updated.json()["is_active"] is False

    session.teaching_events.append({"teaching_name": "Smoke Global Teaching [1h]"})
    blocked = client.delete(
        f"/admin/global-session-types/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert blocked.status_code == 409

    session.teaching_events = [
        row for row in session.teaching_events if row["teaching_name"] != "Smoke Global Teaching [1h]"
    ]
    deleted = client.delete(
        f"/admin/global-session-types/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert deleted.status_code == 204


def test_global_session_type_rejects_blank_name_and_invalid_duration() -> None:
    client = _build_client_with_session(FakeMutationSession())

    blank_name = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "   ", "duration_hours": "1.0", "is_active": True},
    )
    invalid_duration = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "0", "is_active": True},
    )

    assert blank_name.status_code == 422
    assert invalid_duration.status_code == 422


def test_programme_update_respects_scope_and_editable_fields() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={
            "r_year_required": False,
            "is_subspecialty": True,
            "rdb_alias": "Diagnostic Radiology Alias",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "DR"
    assert body["name"] == "Diagnostic Radiology"
    assert body["classification"] == "senior"
    assert body["ay_date_category"] == "non_im_subspec"
    assert body["r_year_required"] is False
    assert body["is_subspecialty"] is True
    assert body["rdb_alias"] == "Diagnostic Radiology Alias"


def test_programme_update_can_clear_rdb_alias_and_persist_false_booleans() -> None:
    client = _build_client_with_session(FakeMutationSession())
    set_response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={
            "r_year_required": False,
            "is_subspecialty": True,
            "rdb_alias": "Diagnostic Radiology Alias",
        },
    )
    assert set_response.status_code == 200
    assert set_response.json()["rdb_alias"] == "Diagnostic Radiology Alias"

    clear_response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={
            "r_year_required": False,
            "is_subspecialty": False,
            "rdb_alias": None,
        },
    )
    assert clear_response.status_code == 200
    body = clear_response.json()
    assert body["rdb_alias"] is None
    assert body["r_year_required"] is False
    assert body["is_subspecialty"] is False

    set_again = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"rdb_alias": "Alias to trim"},
    )
    assert set_again.status_code == 200

    whitespace_clear = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"rdb_alias": "   "},
    )
    assert whitespace_clear.status_code == 200
    assert whitespace_clear.json()["rdb_alias"] is None


def test_programme_update_out_of_scope_rejected() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/GRM",
        headers=_admin_headers("DR"),
        json={"r_year_required": True},
    )

    assert response.status_code == 403


def test_programme_locked_fields_return_422() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"code": "X", "r_year_required": False},
    )
    assert response.status_code == 422


def test_reporting_period_update_rejects_empty_required_values() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    period_id = session.reporting_periods[0]["id"]

    label_response = client.put(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
        json={"label": "   "},
    )
    assert label_response.status_code == 422

    status_response = client.put(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
        json={"status": "paused"},
    )
    assert status_response.status_code == 422


def test_loa_type_crud_and_duplicate_conflict() -> None:
    client = _build_client_with_session(FakeMutationSession())

    created = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    duplicate = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Duplicate"},
    )

    assert created.status_code == 200
    assert duplicate.status_code == 409

    loa_id = created.json()["id"]
    updated = client.put(
        f"/admin/loa-types/{loa_id}",
        headers=_master_admin_headers("DR"),
        json={"code": "Exam Leave", "description": ""},
    )
    deleted = client.delete(f"/admin/loa-types/{loa_id}", headers=_master_admin_headers("DR"))

    assert updated.status_code == 200
    assert updated.json()["code"] == "Exam Leave"
    assert updated.json()["description"] is None
    assert deleted.status_code == 204


def test_loa_type_empty_code_rejected() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "   ", "description": "Blank code should fail"},
    )

    assert response.status_code == 422


def test_multi_posting_rule_rejects_invalid_rule_type() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "unsupported",
            "combined_label": "x",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert response.status_code == 422


def test_multi_posting_rule_duplicate_and_reverse_conflict_returns_409() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "programme_code": "DR",
        "posting_code_1": "TTSHDR",
        "posting_code_2": "KTPHDR",
        "rule_type": "combine",
        "combined_label": "TTSHDR & KTPHDR",
        "main_posting_code": None,
        "exclusion_code": None,
    }
    created = client.post("/admin/multi-posting-rules", headers=_admin_headers("DR"), json=payload)
    assert created.status_code == 200

    duplicate = client.post("/admin/multi-posting-rules", headers=_admin_headers("DR"), json=payload)
    assert duplicate.status_code == 409

    reverse_payload = dict(payload)
    reverse_payload["posting_code_1"] = payload["posting_code_2"]
    reverse_payload["posting_code_2"] = payload["posting_code_1"]
    reverse = client.post("/admin/multi-posting-rules", headers=_admin_headers("DR"), json=reverse_payload)
    assert reverse.status_code == 409


def test_multi_posting_rule_update_scope_safety() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    response = client.put(
        f"/admin/multi-posting-rules/{rule_id}",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "GRM",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert response.status_code == 403


def test_posting_groups_uniqueness_conflict_returns_409() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "group_code": "DR-GROUP",
        "posting_code": "TTSHRespi",
        "programme_code": "DR",
    }
    first = client.post("/admin/posting-groups", headers=_admin_headers("DR"), json=payload)
    assert first.status_code == 200
    second = client.post("/admin/posting-groups", headers=_admin_headers("DR"), json=payload)
    assert second.status_code == 409


def test_global_session_type_delete_returns_409_when_referenced() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    target_id = session.global_session_types[0]["id"]
    response = client.delete(
        f"/admin/global-session-types/{target_id}",
        headers=_master_admin_headers("DR"),
    )
    assert response.status_code == 409


def test_upload_logs_mutation_endpoints_not_allowed() -> None:
    client = _build_client_with_session(FakeMutationSession())
    headers = _admin_headers("DR")
    assert client.post("/admin/upload-logs", headers=headers, json={}).status_code in {404, 405}
    assert client.put("/admin/upload-logs/abc", headers=headers, json={}).status_code in {404, 405}
    assert client.delete("/admin/upload-logs/abc", headers=headers).status_code in {404, 405}


def test_form_f1_records_mutation_endpoints_not_allowed() -> None:
    client = _build_client_with_session(FakeMutationSession())
    headers = _admin_headers("DR")
    assert client.post("/admin/form-f1-records", headers=headers, json={}).status_code in {404, 405}
    assert client.put("/admin/form-f1-records/abc", headers=headers, json={}).status_code in {404, 405}
    assert client.delete("/admin/form-f1-records/abc", headers=headers).status_code in {404, 405}


def test_cache_invalidation_called_after_successful_mutation(monkeypatch) -> None:
    calls: list[str] = []

    def _spy(prefix: str) -> int:
        calls.append(prefix)
        return 0

    monkeypatch.setattr("app.services.admin_config.cache.invalidate_prefix", _spy)
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    assert response.status_code == 200
    assert calls


def test_mutation_responses_are_not_cached(monkeypatch) -> None:
    calls: list[str] = []

    def _forbid_cache_set(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append("set")
        raise AssertionError("cache.set should not be used for mutation responses")

    monkeypatch.setattr("app.services.admin_config.cache.set", _forbid_cache_set)
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Family Care Leave", "description": "Family care leave"},
    )
    assert response.status_code == 200
    assert calls == []
