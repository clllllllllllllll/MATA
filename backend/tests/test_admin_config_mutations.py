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
            if payload.get("description_is_set"):
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


def test_public_holiday_upsert_is_idempotent() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "holiday_date": "2026-08-09",
        "name": "National Day",
        "day_of_week": "Sunday",
        "year": 2026,
    }
    first = client.post("/admin/public-holidays", headers=_admin_headers("DR"), json=payload)
    assert first.status_code == 200
    first_id = first.json()["id"]

    payload["name"] = "National Day Updated"
    second = client.post("/admin/public-holidays", headers=_admin_headers("DR"), json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == first_id
    assert second.json()["name"] == "National Day Updated"


def test_programme_locked_fields_return_422() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/DR",
        headers=_admin_headers("DR"),
        json={"code": "X", "r_year_required": False},
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
        headers=_admin_headers("DR"),
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
        headers=_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    assert response.status_code == 200
    assert calls
