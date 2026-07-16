from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


NOW = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)


class _FakeResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar: object | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected exactly one row, got {len(self._rows)}")
        return self._rows[0]

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError(f"Expected at most one row, got {len(self._rows)}")
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class FakeProgrammeTeachingEventsSession:
    def __init__(self) -> None:
        self.period_id = str(uuid4())
        self.reporting_periods = [
            {
                "id": self.period_id,
                "label": "2026 operational period",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
            }
        ]
        self.session_type_id = str(uuid4())
        self.other_session_type_id = str(uuid4())
        self.pc_dr_event_id = str(uuid4())
        self.secretary_dr_event_id = str(uuid4())
        self.geri_event_id = str(uuid4())
        self.native_attended_event_id = str(uuid4())
        self.external_attended_event_id = str(uuid4())
        self.public_holidays = [
            {"holiday_date": date(2026, 5, 1), "name": "Labour Day"},
        ]
        self.catalogue = [
            self._catalogue("Journal Club", "DR", "TTSHCardio", self.session_type_id),
            self._catalogue("Grand Round", "DR", "TTSHCardio", self.session_type_id),
            self._catalogue("Geri Teaching", "GERI", "TTSHGerMed", self.other_session_type_id),
        ]
        self.global_session_types = [
            {"name": "Department Meeting [1h]", "duration_hours": Decimal("1.0"), "is_active": True},
        ]
        self.secretary_programme_pools = [
            {"posting_code": "TTSHCardio", "programme_code": "DR", "is_active": True},
            {"posting_code": "TTSHGerMed", "programme_code": "GERI", "is_active": True},
        ]
        self.events = [
            self._event(
                event_id=self.pc_dr_event_id,
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                created_by_role="programme_pc",
                created_for_programme_code="DR",
            ),
            self._event(
                event_id=self.secretary_dr_event_id,
                posting_code="TTSHCardio",
                teaching_name="Grand Round",
                created_by_role="secretary",
                created_for_programme_code=None,
            ),
            self._event(
                event_id=self.geri_event_id,
                posting_code="TTSHGerMed",
                teaching_name="Geri Teaching",
                created_by_role="programme_pc",
                created_for_programme_code="GERI",
            ),
            self._event(
                event_id=self.native_attended_event_id,
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                created_by_role="programme_pc",
                created_for_programme_code="DR",
            ),
            self._event(
                event_id=self.external_attended_event_id,
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                created_by_role="programme_pc",
                created_for_programme_code="DR",
            ),
        ]
        self.attendance_event_ids = {self.native_attended_event_id}
        self.external_attendance_event_ids = {self.external_attended_event_id}
        self.commits = 0
        self.deleted_event_ids: list[str] = []

    def _catalogue(
        self,
        keyword: str,
        programme_code: str,
        posting_code: str,
        session_type_id: str,
    ) -> dict:
        return {
            "keyword": keyword,
            "programme_code": programme_code,
            "posting_code": posting_code,
            "r_year": "ALL",
            "reporting_period_id": self.period_id,
            "session_type_id": session_type_id,
            "session_type": f"{keyword} [1h]",
            "duration_hours": Decimal("1.0"),
            "is_tracked": True,
        }

    def _event(
        self,
        *,
        event_id: str,
        posting_code: str,
        teaching_name: str,
        created_by_role: str | None,
        created_for_programme_code: str | None,
        event_date: date = date(2026, 5, 18),
        start_time: time = time(10, 0),
    ) -> dict:
        return {
            "id": event_id,
            "posting_code": posting_code,
            "created_for_programme_code": created_for_programme_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": time(11, 0),
            "duration_hours": Decimal("1.0"),
            "session_type_id": self.session_type_id,
            "session_type": f"{teaching_name} [1h]",
            "series_id": None,
            "cme_points_awarded": False,
            "smc_event_code": None,
            "is_adhoc": False,
            "created_by_role": created_by_role,
            "created_at": NOW,
            "updated_at": NOW,
        }

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "/* reporting_period_resolution:list */" in sql:
            return _FakeResult(rows=list(self.reporting_periods))

        if "/* reporting_period_resolution:explicit */" in sql:
            rows = [
                row
                for row in self.reporting_periods
                if row["id"] == str(payload["reporting_period_id"])
            ]
            return _FakeResult(rows=rows)

        if "/* programme_teaching_events:list */" in sql:
            rows = self._scope_events(
                payload.get("programme_scope") or [],
                reporting_period_id=str(payload["reporting_period_id"]),
            )
            rows = [
                row
                for row in rows
                if payload["reporting_period_start"] <= row["event_date"] <= payload["reporting_period_end"]
            ]
            if payload.get("programme_code"):
                rows = [
                    row
                    for row in rows
                    if row.get("created_for_programme_code") == payload["programme_code"]
                    or (
                        row.get("created_for_programme_code") is None
                        and (
                            self._secretary_programmes(row["posting_code"]) & {payload["programme_code"]}
                            or self._catalogue_programmes(
                                posting_code=row["posting_code"],
                                teaching_name=row["teaching_name"],
                                reporting_period_id=str(payload["reporting_period_id"]),
                            )
                            & {payload["programme_code"]}
                        )
                    )
                ]
            return _FakeResult(rows=rows)

        if "/* programme_teaching_events:options_catalogue */" in sql:
            rows = [
                {
                    "keyword": row["keyword"],
                    "session_type_id": row["session_type_id"],
                    "session_type": row["session_type"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": row["is_tracked"],
                    "is_global": False,
                    "posting_codes": [row["posting_code"]],
                }
                for row in self.catalogue
                if row["programme_code"] == payload["programme_code"]
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
            ]
            return _FakeResult(rows=rows)

        if "/* programme_teaching_events:options_global */" in sql:
            return _FakeResult(
                rows=[
                    {
                        "keyword": row["name"],
                        "session_type_id": None,
                        "session_type": row["name"],
                        "duration_hours": row["duration_hours"],
                        "is_tracked": False,
                        "is_global": True,
                        "posting_codes": [],
                    }
                    for row in self.global_session_types
                    if row["is_active"]
                ]
            )

        if "/* programme_teaching_events:global_posting_options */" in sql:
            programme_code = payload["programme_code"]
            codes = {
                row["posting_code"]
                for row in self.secretary_programme_pools
                if row["programme_code"] == programme_code and row["is_active"]
            }
            codes.update(
                row["posting_code"]
                for row in self.catalogue
                if row["programme_code"] == programme_code
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
            )
            return _FakeResult(rows=[{"posting_code": code} for code in sorted(codes)])

        if "/* programme_teaching_events:public_holiday */" in sql:
            holiday = next(
                (row for row in self.public_holidays if row["holiday_date"] == payload["event_date"]),
                None,
            )
            return _FakeResult(rows=[holiday] if holiday else [])

        if "/* programme_teaching_events:resolve_name */" in sql:
            global_rows = [
                {
                    "keyword": row["name"],
                    "session_type_id": None,
                    "session_type": row["name"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": False,
                    "is_global": True,
                }
                for row in self.global_session_types
                if row["is_active"] and row["name"] == payload["teaching_name"]
            ]
            if global_rows:
                return _FakeResult(rows=global_rows)
            rows = [
                {
                    "keyword": row["keyword"],
                    "session_type_id": row["session_type_id"],
                    "session_type": row["session_type"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": row["is_tracked"],
                    "is_global": False,
                }
                for row in self.catalogue
                if row["programme_code"] == payload["programme_code"]
                and row["posting_code"] == payload["posting_code"]
                and row["keyword"] == payload["teaching_name"]
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
            ]
            return _FakeResult(rows=rows)

        if "/* programme_teaching_events:posting_available */" in sql:
            posting_code = payload["posting_code"]
            programme_code = payload["programme_code"]
            is_available = bool(self._secretary_programmes(posting_code) & {programme_code}) or any(
                row["programme_code"] == programme_code
                and row["posting_code"] == posting_code
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
                for row in self.catalogue
            )
            return _FakeResult(scalar=is_available)

        if "/* programme_teaching_events:insert */" in sql:
            row = self._event(
                event_id=str(uuid4()),
                posting_code=payload["posting_code"],
                teaching_name=payload["teaching_name"],
                created_by_role=payload["created_by_role"],
                created_for_programme_code=payload["programme_code"],
                event_date=payload["event_date"],
                start_time=payload["start_time"],
            )
            row["end_time"] = payload["end_time"]
            row["duration_hours"] = payload["duration_hours"]
            row["session_type_id"] = str(payload["session_type_id"]) if payload.get("session_type_id") else None
            row["cme_points_awarded"] = payload["cme_points_awarded"]
            row["smc_event_code"] = payload.get("smc_event_code")
            self.events.append(row)
            return _FakeResult(rows=[row])

        if "/* programme_teaching_events:get_event */" in sql:
            event = next((row for row in self.events if row["id"] == str(payload["event_id"])), None)
            return _FakeResult(rows=[event] if event else [])

        if "/* programme_teaching_events:event_programme_match */" in sql:
            posting_code = payload["posting_code"]
            programme_code = payload["programme_code"]
            teaching_name = payload["teaching_name"]
            is_match = bool(self._secretary_programmes(posting_code) & {programme_code}) or any(
                row["programme_code"] == programme_code
                and row["posting_code"] == posting_code
                and row["keyword"] == teaching_name
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
                for row in self.catalogue
            )
            return _FakeResult(scalar=is_match)

        if "/* programme_teaching_events:attendance_guard */" in sql:
            event_id = str(payload["event_id"])
            has_attendance = event_id in self.attendance_event_ids or event_id in self.external_attendance_event_ids
            return _FakeResult(scalar=1 if has_attendance else None)

        if "/* programme_teaching_events:update */" in sql:
            event = next((row for row in self.events if row["id"] == str(payload["event_id"])), None)
            if event is None:
                return _FakeResult(rows=[])
            event.update(
                {
                    "posting_code": payload["posting_code"],
                    "teaching_name": payload["teaching_name"],
                    "event_date": payload["event_date"],
                    "start_time": payload["start_time"],
                    "end_time": payload["end_time"],
                    "duration_hours": payload["duration_hours"],
                    "session_type_id": str(payload["session_type_id"]) if payload.get("session_type_id") else None,
                    "cme_points_awarded": payload["cme_points_awarded"],
                    "smc_event_code": payload.get("smc_event_code"),
                    "updated_at": NOW,
                }
            )
            return _FakeResult(rows=[event])

        if "/* programme_teaching_events:delete */" in sql:
            event_id = str(payload["event_id"])
            self.deleted_event_ids.append(event_id)
            self.events = [row for row in self.events if row["id"] != event_id]
            return _FakeResult(rowcount=1)

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")

    def _secretary_programmes(self, posting_code: str) -> set[str]:
        return {
            row["programme_code"]
            for row in self.secretary_programme_pools
            if row["posting_code"] == posting_code and row["is_active"]
        }

    def _catalogue_programmes(
        self,
        *,
        posting_code: str,
        teaching_name: str,
        reporting_period_id: str,
    ) -> set[str]:
        return {
            row["programme_code"]
            for row in self.catalogue
            if row["posting_code"] == posting_code
            and row["keyword"] == teaching_name
            and row["reporting_period_id"] == reporting_period_id
        }

    def _scope_events(self, programme_scope: list[str], *, reporting_period_id: str) -> list[dict]:
        scope = set(programme_scope)
        rows = []
        for row in self.events:
            if row["is_adhoc"]:
                continue
            owner = row.get("created_for_programme_code")
            if owner in scope or (
                owner is None
                and (
                    self._secretary_programmes(row["posting_code"]) & scope
                    or self._catalogue_programmes(
                        posting_code=row["posting_code"],
                        teaching_name=row["teaching_name"],
                        reporting_period_id=reporting_period_id,
                    )
                    & scope
                )
            ):
                rows.append(
                    {
                        **row,
                        "attendance_count": 1 if row["id"] in self.attendance_event_ids else 0,
                        "external_attendance_count": 1 if row["id"] in self.external_attendance_event_ids else 0,
                    }
                )
        rows.sort(key=lambda item: (item["event_date"], item["start_time"], item["teaching_name"]))
        return rows


def _client(session: FakeProgrammeTeachingEventsSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def override_db():
        yield session

    app.dependency_overrides[admin.get_db_session] = override_db
    return TestClient(app)


def _headers(
    *,
    role: str = "admin",
    scope: str = "DR",
    master: bool = False,
) -> dict[str, str]:
    headers = {
        "X-User-Role": role,
        "X-User-Id": str(uuid4()),
        "X-User-Programme": scope,
    }
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def test_pc_can_create_event_for_own_programme() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    response = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope="DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHCardio",
            "teaching_name": "Journal Club",
            "event_date": "2026-05-20",
            "start_time": "10:00",
            "cme_points_awarded": True,
            "smc_event_code": "SMC-DR-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["created_for_programme_code"] == "DR"
    assert payload["created_by_role"] == "programme_pc"
    assert payload["end_time"] == "11:00:00"
    assert session.events[-1]["created_for_programme_code"] == "DR"
    assert session.events[-1]["created_by_role"] == "programme_pc"


def test_pc_can_create_global_department_meeting_for_safe_programme_posting() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    response = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope="GERI"),
        json={
            "programme_code": "GERI",
            "posting_code": "TTSHGerMed",
            "teaching_name": "Department Meeting [1h]",
            "event_date": "2026-05-20",
            "start_time": "10:00",
            "cme_points_awarded": False,
            "smc_event_code": None,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHGerMed"
    assert payload["teaching_name"] == "Department Meeting [1h]"
    assert payload["created_for_programme_code"] == "GERI"
    assert session.events[-1]["session_type_id"] is None


def test_pc_cannot_create_global_department_meeting_for_out_of_scope_posting() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    response = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope="GERI"),
        json={
            "programme_code": "GERI",
            "posting_code": "TTSHCardio",
            "teaching_name": "Department Meeting [1h]",
            "event_date": "2026-05-20",
            "start_time": "10:00",
            "cme_points_awarded": False,
            "smc_event_code": None,
        },
    )

    assert response.status_code in {403, 422}
    assert all(
        row["teaching_name"] != "Department Meeting [1h]"
        or row["created_for_programme_code"] != "GERI"
        or row["posting_code"] != "TTSHCardio"
        for row in session.events
    )


def test_pc_scope_and_master_admin_mutations_are_denied() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)
    body = {
        "programme_code": "DR",
        "posting_code": "TTSHCardio",
        "teaching_name": "Journal Club",
        "event_date": "2026-05-20",
        "start_time": "10:00",
    }

    out_of_scope = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope="GERI"),
        json=body,
    )
    empty_scope = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope=""),
        json=body,
    )
    master = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope="DR,GERI", master=True),
        json=body,
    )
    master_edit = client.put(
        f"/admin/programme-teaching-events/{session.pc_dr_event_id}",
        headers=_headers(scope="DR,GERI", master=True),
        json=body,
    )
    empty_scope_delete = client.delete(
        f"/admin/programme-teaching-events/{session.pc_dr_event_id}",
        headers=_headers(scope=""),
    )
    master_delete_without_programme = client.delete(
        f"/admin/programme-teaching-events/{session.pc_dr_event_id}",
        headers=_headers(scope="", master=True),
    )

    assert out_of_scope.status_code == 403
    assert empty_scope.status_code == 403
    assert master.status_code == 403
    assert master_edit.status_code == 403
    assert empty_scope_delete.status_code == 403
    assert master_delete_without_programme.status_code == 403


def test_pc_list_uses_connected_schedule_scope() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    dr_response = client.get(
        "/admin/programme-teaching-events",
        headers=_headers(scope="DR"),
    )
    geri_response = client.get(
        "/admin/programme-teaching-events",
        headers=_headers(scope="GERI"),
    )

    assert dr_response.status_code == 200
    dr_ids = {row["id"] for row in dr_response.json()["events"]}
    assert session.pc_dr_event_id in dr_ids
    assert session.secretary_dr_event_id in dr_ids
    assert session.geri_event_id not in dr_ids

    assert geri_response.status_code == 200
    geri_ids = {row["id"] for row in geri_response.json()["events"]}
    assert session.geri_event_id in geri_ids
    assert session.pc_dr_event_id not in geri_ids


def test_edit_preserves_created_by_role_and_duplicate_uses_pc_role() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    updated = client.put(
        f"/admin/programme-teaching-events/{session.pc_dr_event_id}",
        headers=_headers(scope="DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHCardio",
            "teaching_name": "Grand Round",
            "event_date": "2026-05-21",
            "start_time": "11:00",
            "cme_points_awarded": False,
            "smc_event_code": None,
        },
    )
    duplicated = client.post(
        f"/admin/programme-teaching-events/{session.secretary_dr_event_id}/duplicate",
        headers=_headers(scope="DR"),
        json={
            "programme_code": "DR",
            "event_date": "2026-05-22",
            "start_time": "12:00",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["created_by_role"] == "programme_pc"
    assert duplicated.status_code == 200
    assert duplicated.json()["created_by_role"] == "programme_pc"
    assert duplicated.json()["created_for_programme_code"] == "DR"


def test_ph_and_attendance_guards_apply_to_pc_mutations() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)
    body = {
        "programme_code": "DR",
        "posting_code": "TTSHCardio",
        "teaching_name": "Journal Club",
        "event_date": "2026-05-01",
        "start_time": "10:00",
    }

    public_holiday = client.post(
        "/admin/programme-teaching-events",
        headers=_headers(scope="DR"),
        json=body,
    )
    native_attendance = client.delete(
        f"/admin/programme-teaching-events/{session.native_attended_event_id}",
        headers=_headers(scope="DR"),
    )
    external_attendance = client.put(
        f"/admin/programme-teaching-events/{session.external_attended_event_id}",
        headers=_headers(scope="DR"),
        json={**body, "event_date": "2026-05-20"},
    )

    assert public_holiday.status_code == 422
    assert native_attendance.status_code == 409
    assert external_attendance.status_code == 409


def test_teaching_name_options_are_programme_scoped() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    response = client.get(
        "/admin/programme-teaching-name-options",
        headers=_headers(scope="DR"),
        params={"programme_code": "DR"},
    )

    assert response.status_code == 200
    keywords = {row["keyword"] for row in response.json()["options"]}
    assert "Journal Club" in keywords
    assert "Grand Round" in keywords
    assert "Department Meeting [1h]" in keywords
    assert "Geri Teaching" not in keywords


def test_teaching_name_options_do_not_leak_from_future_period() -> None:
    session = FakeProgrammeTeachingEventsSession()
    future_period_id = str(uuid4())
    session.reporting_periods.append(
        {
            "id": future_period_id,
            "label": "Future Test Period",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    future_row = session._catalogue("Future Test Teaching", "DR", "TTSHCardio", session.session_type_id)
    future_row["reporting_period_id"] = future_period_id
    session.catalogue.append(future_row)
    client = _client(session)

    current = client.get(
        "/admin/programme-teaching-name-options",
        headers=_headers(scope="DR"),
        params={"programme_code": "DR"},
    )
    explicit_future = client.get(
        "/admin/programme-teaching-name-options",
        headers=_headers(scope="DR"),
        params={"programme_code": "DR", "reporting_period_id": future_period_id},
    )

    assert current.status_code == 200
    assert "Future Test Teaching" not in {row["keyword"] for row in current.json()["options"]}
    assert explicit_future.status_code == 200
    assert "Future Test Teaching" in {row["keyword"] for row in explicit_future.json()["options"]}


def test_pc_event_list_and_management_are_isolated_by_reporting_period() -> None:
    session = FakeProgrammeTeachingEventsSession()
    future_period_id = str(uuid4())
    session.reporting_periods.append(
        {
            "id": future_period_id,
            "label": "Future Test Period",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    future_catalogue = session._catalogue("Future Test Teaching", "DR", "TTSHNeuro", session.session_type_id)
    future_catalogue["reporting_period_id"] = future_period_id
    session.catalogue.append(future_catalogue)
    cross_period_event = session._event(
        event_id=str(uuid4()),
        posting_code="TTSHNeuro",
        teaching_name="Future Test Teaching",
        created_by_role="secretary",
        created_for_programme_code=None,
    )
    future_event = session._event(
        event_id=str(uuid4()),
        posting_code="TTSHNeuro",
        teaching_name="Future Test Teaching",
        created_by_role="secretary",
        created_for_programme_code=None,
        event_date=date(2099, 2, 1),
    )
    session.events.extend([cross_period_event, future_event])
    client = _client(session)

    current = client.get("/admin/programme-teaching-events", headers=_headers(scope="DR"))
    explicit_future = client.get(
        "/admin/programme-teaching-events",
        headers=_headers(scope="DR"),
        params={"reporting_period_id": future_period_id},
    )
    cross_period_update = client.put(
        f"/admin/programme-teaching-events/{cross_period_event['id']}",
        headers=_headers(scope="DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHNeuro",
            "teaching_name": "Future Test Teaching",
            "event_date": "2026-05-20",
            "start_time": "10:00",
        },
    )
    cross_period_delete = client.delete(
        f"/admin/programme-teaching-events/{cross_period_event['id']}",
        headers=_headers(scope="DR"),
    )
    conflicting_dates = client.get(
        "/admin/programme-teaching-events",
        headers=_headers(scope="DR"),
        params={"reporting_period_id": future_period_id, "date_from": "2026-05-20"},
    )

    assert current.status_code == 200
    assert cross_period_event["id"] not in {row["id"] for row in current.json()["events"]}
    assert explicit_future.status_code == 200
    assert {row["id"] for row in explicit_future.json()["events"]} == {future_event["id"]}
    assert cross_period_update.status_code == 403
    assert cross_period_delete.status_code == 403
    assert conflicting_dates.status_code == 422


def test_pc_operational_catalogue_visibility_and_overlap_conflict() -> None:
    session = FakeProgrammeTeachingEventsSession()
    scoped_event = session._event(
        event_id=str(uuid4()),
        posting_code="TTSHNeuro",
        teaching_name="Current-period teaching",
        created_by_role="secretary",
        created_for_programme_code=None,
    )
    session.catalogue.append(
        session._catalogue(
            "Current-period teaching",
            "DR",
            "TTSHNeuro",
            session.session_type_id,
        )
    )
    session.events.append(scoped_event)
    client = _client(session)

    listed = client.get("/admin/programme-teaching-events", headers=_headers(scope="DR"))
    manageable = client.put(
        f"/admin/programme-teaching-events/{scoped_event['id']}",
        headers=_headers(scope="DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHNeuro",
            "teaching_name": "Current-period teaching",
            "event_date": "2026-05-20",
            "start_time": "10:00",
        },
    )
    session.reporting_periods.append(
        {
            "id": str(uuid4()),
            "label": "Overlapping operational period",
            "start_date": date(2026, 7, 1),
            "end_date": date(2026, 12, 31),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    overlap = client.get("/admin/programme-teaching-events", headers=_headers(scope="DR"))

    assert listed.status_code == 200
    assert scoped_event["id"] in {row["id"] for row in listed.json()["events"]}
    assert manageable.status_code == 200
    assert overlap.status_code == 409


def test_global_teaching_name_options_include_safe_programme_postings() -> None:
    session = FakeProgrammeTeachingEventsSession()
    client = _client(session)

    response = client.get(
        "/admin/programme-teaching-name-options",
        headers=_headers(scope="GERI"),
        params={"programme_code": "GERI"},
    )

    assert response.status_code == 200
    department_meeting = next(
        row for row in response.json()["options"] if row["keyword"] == "Department Meeting [1h]"
    )
    assert department_meeting["is_global"] is True
    assert department_meeting["posting_codes"] == ["TTSHGerMed"]
