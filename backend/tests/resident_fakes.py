from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4


class FakeResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar: object | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "FakeResult":
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


class FakeResidentSession:
    def __init__(self) -> None:
        self.today = date.today()
        self.now = datetime.combine(self.today, time(9, 0), tzinfo=timezone.utc)
        posting_start = self.today - timedelta(days=30)
        posting_end = self.today + timedelta(days=30)
        period_start = self.today - timedelta(days=180)
        period_end = self.today + timedelta(days=180)
        recent_event_day = self.today - timedelta(days=1)
        older_event_day = self.today - timedelta(days=2)
        future_event_day = self.today + timedelta(days=7)
        # derive a deterministic weekend date at or before today
        weekend_offset = (self.today.weekday() - 5) % 7
        weekend_event_day = self.today - timedelta(days=weekend_offset)
        self.period_id = str(uuid4())
        self.closed_period_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.other_resident_id = str(uuid4())
        self.admin_id = str(uuid4())
        self.secretary_id = str(uuid4())
        self.session_type_id = str(uuid4())
        self.second_session_type_id = str(uuid4())
        self.existing_attendance_id = str(uuid4())
        self.other_attendance_id = str(uuid4())
        self.event_id = str(uuid4())
        self.second_event_id = str(uuid4())
        self.future_event_id = str(uuid4())
        self.other_posting_event_id = str(uuid4())
        self.invisible_event_id = str(uuid4())
        self.global_event_id = str(uuid4())
        self.weekend_event_id = str(uuid4())
        self.external_resident_id = str(uuid4())
        self.other_external_resident_id = str(uuid4())
        self.external_existing_attendance_id = str(uuid4())

        self.users = [
            {
                "id": self.admin_id,
                "email": "pc@nhg.com.sg",
                "password_hash": "password",
                "role": "admin",
                "name": "Programme Coordinator",
                "posting_code": None,
                "programme_scope": ["GRM", "DR"],
                "is_active": True,
            },
            {
                "id": self.secretary_id,
                "email": "sec@nhg.com.sg",
                "password_hash": "password",
                "role": "secretary",
                "name": "Department Secretary",
                "posting_code": "TTSHCardio",
                "programme_scope": None,
                "is_active": True,
            },
        ]
        self.residents = [
            {
                "id": self.resident_id,
                "name": "Resident One",
                "mcr": "M12345A",
                "programme_code": "GRM",
                "r_year": "R2",
                "status": "active",
            },
            {
                "id": self.other_resident_id,
                "name": "Resident Two",
                "mcr": "M54321B",
                "programme_code": "GRM",
                "r_year": "R2",
                "status": "active",
            },
        ]
        self.posting_codes = [
            {"code": "TTSHCardio", "supports_secretary_events": True},
            {"code": "TTSHNeuro", "supports_secretary_events": True},
            {"code": "KTPHGerMed", "supports_secretary_events": False},
        ]
        self.external_residents = [
            {
                "id": self.external_resident_id,
                "name": "External Resident One",
                "mcr": "E12345A",
                "home_cluster": "NUH",
                "current_nhg_posting_code": "TTSHCardio",
                "status": "active",
            },
            {
                "id": self.other_external_resident_id,
                "name": "External Resident Two",
                "mcr": "E54321B",
                "home_cluster": "SingHealth",
                "current_nhg_posting_code": "TTSHNeuro",
                "status": "active",
            },
        ]
        self.external_resident_postings = [
            {
                "id": str(uuid4()),
                "external_resident_id": self.external_resident_id,
                "posting_code": "TTSHCardio",
                "start_date": date(2026, 5, 1),
                "end_date": None,
                "is_current": True,
            }
        ]
        self.reporting_periods = [
            {
                "id": self.period_id,
                "label": "Jan - June 2026",
                "start_date": period_start,
                "end_date": period_end,
                "status": "open",
            }
        ]
        self.resident_postings = [
            {
                "resident_id": self.resident_id,
                "reporting_period_id": self.period_id,
                "posting_code": "TTSHCardio",
                "r_year": "R2",
                "start_date": posting_start,
                "end_date": posting_end,
                "status": "active",
            },
            {
                "resident_id": self.other_resident_id,
                "reporting_period_id": self.period_id,
                "posting_code": "TTSHNeuro",
                "r_year": "R2",
                "start_date": posting_start,
                "end_date": posting_end,
                "status": "active",
            },
        ]
        self.catalogue = [
            self._catalogue("Journal Club", "TTSHCardio", self.session_type_id, Decimal("1.0")),
            self._catalogue("Skills Teaching", "TTSHNeuro", self.second_session_type_id, Decimal("2.0")),
        ]
        self.global_session_types = [
            {"name": "Department Meeting [1h]", "duration_hours": Decimal("1.0"), "is_active": True}
        ]
        self.public_holidays = [
            {"holiday_date": date(2026, 5, 1), "name": "Labour Day"},
        ]
        self.weekend_exceptions: list[dict] = []
        self.events = [
            self._event(self.event_id, "TTSHCardio", "Journal Club", recent_event_day),
            self._event(self.second_event_id, "TTSHCardio", "Journal Club", older_event_day),
            self._event(self.future_event_id, "TTSHCardio", "Journal Club", future_event_day),
            self._event(self.other_posting_event_id, "TTSHNeuro", "Skills Teaching", recent_event_day),
            self._event(self.invisible_event_id, "TTSHCardio", "Unmapped Teaching", recent_event_day),
            self._event(self.global_event_id, "TTSHCardio", "Department Meeting [1h]", recent_event_day),
            self._event(self.weekend_event_id, "TTSHCardio", "Journal Club", weekend_event_day),
        ]
        self.attendance = [
            {
                "id": self.existing_attendance_id,
                "resident_id": self.resident_id,
                "teaching_event_id": self.second_event_id,
                "status": "submitted",
                "posting_code": "TTSHCardio",
            },
            {
                "id": self.other_attendance_id,
                "resident_id": self.other_resident_id,
                "teaching_event_id": self.event_id,
                "status": "submitted",
                "posting_code": "TTSHCardio",
            },
        ]
        self.external_attendance = [
            {
                "id": self.external_existing_attendance_id,
                "external_resident_id": self.external_resident_id,
                "teaching_event_id": self.second_event_id,
                "status": "submitted",
                "posting_code": "TTSHCardio",
                "submitted_at": self.now,
            }
        ]
        self.commits = 0

    def _catalogue(
        self,
        keyword: str,
        posting_code: str,
        session_type_id: str,
        duration_hours: Decimal,
    ) -> dict:
        return {
            "keyword": keyword,
            "posting_code": posting_code,
            "programme_code": "GRM",
            "r_year": "R2",
            "reporting_period_id": self.period_id,
            "session_type_id": session_type_id,
            "session_type": f"{keyword} [{duration_hours}h]",
            "duration_hours": duration_hours,
            "is_tracked": True,
        }

    def _event(
        self,
        event_id: str,
        posting_code: str,
        teaching_name: str,
        event_date: date,
        *,
        start_time: time = time(10, 0),
        duration_hours: Decimal = Decimal("1.0"),
    ) -> dict:
        return {
            "id": event_id,
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": time(11, 0),
            "duration_hours": duration_hours,
            "session_type_id": self.session_type_id,
            "series_id": None,
            "cme_points_awarded": False,
            "smc_event_code": None,
            "is_adhoc": False,
            "created_by_role": "secretary",
            "created_at": self.now,
            "updated_at": self.now,
        }

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "FROM users" in sql:
            rows = [
                row
                for row in self.users
                if row["role"] == payload.get("role")
                and row["email"].lower() == payload.get("email", "").lower()
                and row["is_active"]
            ]
            if "user_id" in payload:
                rows = [row for row in self.users if row["id"] == str(payload["user_id"]) and row["is_active"]]
            return FakeResult(rows=rows)

        if "FROM residents" in sql and "WHERE mcr" in sql:
            rows = [row for row in self.residents if row["mcr"] == payload.get("mcr")]
            if "SELECT 1" in sql:
                return FakeResult(scalar=1 if rows else None)
            return FakeResult(rows=rows)

        if "FROM residents" in sql and "WHERE id" in sql:
            rows = [row for row in self.residents if row["id"] == str(payload.get("resident_id"))]
            return FakeResult(rows=rows)

        if "FROM external_residents" in sql and "WHERE mcr" in sql:
            rows = [row for row in self.external_residents if row["mcr"] == payload.get("mcr")]
            if "SELECT 1" in sql:
                return FakeResult(scalar=1 if rows else None)
            return FakeResult(rows=rows)

        if "FROM external_residents" in sql and "WHERE id" in sql:
            lookup_id = str(
                payload.get("external_resident_id")
                or payload.get("subject_id")
                or payload.get("user_id")
            )
            rows = [row for row in self.external_residents if row["id"] == lookup_id]
            return FakeResult(rows=rows)

        if "SELECT supports_secretary_events" in sql and "FROM posting_codes" in sql:
            posting = next(
                (
                    row
                    for row in self.posting_codes
                    if row["code"] == payload.get("posting_code")
                ),
                None,
            )
            return FakeResult(rows=[posting] if posting else [])

        if "SELECT code, supports_secretary_events" in sql and "FROM posting_codes" in sql:
            codes = set(payload.get("posting_codes") or [])
            rows = [row for row in self.posting_codes if row["code"] in codes]
            return FakeResult(rows=rows)

        if "SELECT 1" in sql and "FROM posting_codes" in sql:
            exists = any(row for row in self.posting_codes if row["code"] == payload.get("posting_code"))
            return FakeResult(scalar=1 if exists else None)

        if "FROM reporting_periods" in sql:
            rows = [row for row in self.reporting_periods if row["status"] == "open"]
            return FakeResult(rows=rows[:1])

        if "FROM resident_postings" in sql:
            lookup_date = payload.get("on_date") or payload.get("today")
            rows = [
                row
                for row in self.resident_postings
                if row["resident_id"] == str(payload.get("resident_id"))
                and row["reporting_period_id"] == str(payload.get("reporting_period_id"))
                and row["status"] in {"active", "loa_working"}
                and (
                    lookup_date is None
                    or row["start_date"] <= lookup_date <= row["end_date"]
                )
            ]
            rows.sort(key=lambda row: row["start_date"], reverse=True)
            return FakeResult(rows=rows)

        if "FROM public_holidays" in sql:
            holiday = next(
                (row for row in self.public_holidays if row["holiday_date"] == payload["event_date"]),
                None,
            )
            return FakeResult(rows=[holiday] if holiday else [])

        if "FROM global_session_types" in sql:
            rows = [
                {
                    "keyword": row["name"],
                    "session_type_id": None,
                    "session_type": row["name"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": False,
                    "is_global": True,
                }
                for row in self.global_session_types
                if row["is_active"]
                and ("teaching_name" not in payload or row["name"] == payload["teaching_name"])
            ]
            return FakeResult(rows=rows)

        if "FROM teaching_name_catalogue" in sql:
            if "programme_code" in payload:
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
                    if row["posting_code"] == payload.get("posting_code")
                    and row["programme_code"] == payload.get("programme_code")
                    and row["r_year"] in {payload.get("r_year"), "ALL"}
                    and row["reporting_period_id"] == str(payload.get("reporting_period_id"))
                    and ("teaching_name" not in payload or row["keyword"] == payload["teaching_name"])
                ]
            else:
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
                    if row["posting_code"] == payload.get("posting_code")
                    and ("teaching_name" not in payload or row["keyword"] == payload["teaching_name"])
                ]
            return FakeResult(rows=rows)

        if "FROM teaching_events" in sql and "WHERE id = :event_id" in sql:
            rows = [row for row in self.events if row["id"] == str(payload["event_id"])]
            return FakeResult(rows=rows)

        if "FROM teaching_events" in sql:
            if "external_attendance_records ear" in sql:
                posting_code = payload.get("posting_code")
                today = payload.get("today", date.max)
                submitted = {
                    row["teaching_event_id"]
                    for row in self.external_attendance
                    if row["external_resident_id"] == str(payload.get("external_resident_id"))
                    and row["status"] == "submitted"
                }
                rows = [
                    row
                    for row in self.events
                    if row["posting_code"] == posting_code
                    and row["event_date"] <= today
                    and row["id"] not in submitted
                    and row.get("created_by_role") == "secretary"
                ]
                if "date_from" in payload and payload["date_from"] is not None:
                    rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
                if "date_to" in payload and payload["date_to"] is not None:
                    rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
                rows.sort(key=lambda row: (row["event_date"], row["start_time"], row["teaching_name"]))
                return FakeResult(rows=rows)

            posting_codes = set(payload.get("posting_codes") or [])
            today = payload.get("today", date.max)
            submitted = {
                row["teaching_event_id"]
                for row in self.attendance
                if row["resident_id"] == str(payload.get("resident_id"))
                and row["status"] == "submitted"
            }
            rows = [
                row
                for row in self.events
                if row["posting_code"] in posting_codes
                and row["event_date"] <= today
                and row["event_date"] >= payload.get("period_start", date.min)
                and row["event_date"] <= payload.get("period_end", date.max)
                and row["id"] not in submitted
                and row.get("created_by_role") == "secretary"
            ]
            if "date_from" in payload and payload["date_from"] is not None:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload and payload["date_to"] is not None:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            rows.sort(key=lambda row: (row["event_date"], row["start_time"], row["teaching_name"]))
            return FakeResult(rows=rows)

        if "FROM weekend_exceptions" in sql:
            rows = [
                row
                for row in self.weekend_exceptions
                if row.get("posting_code") in {None, payload.get("posting_code")}
                and row.get("programme_code") in {None, payload.get("programme_code")}
                and row.get("day_type") in {payload.get("day_type"), "both"}
            ]
            return FakeResult(rows=rows)

        if "SELECT 1" in sql and "FROM attendance_records" in sql:
            exists = any(
                row
                for row in self.attendance
                if row["resident_id"] == str(payload.get("resident_id"))
                and row["teaching_event_id"] == str(payload.get("event_id"))
                and row["status"] == "submitted"
            )
            return FakeResult(scalar=1 if exists else None)

        if "SELECT 1" in sql and "FROM external_attendance_records" in sql:
            exists = any(
                row
                for row in self.external_attendance
                if row["external_resident_id"] == str(payload.get("external_resident_id"))
                and row["teaching_event_id"] == str(payload.get("event_id"))
                and row["status"] == "submitted"
            )
            return FakeResult(scalar=1 if exists else None)

        if "INSERT INTO attendance_records" in sql:
            duplicate = any(
                row
                for row in self.attendance
                if row["resident_id"] == str(payload["resident_id"])
                and row["teaching_event_id"] == str(payload["event_id"])
                and row["status"] == "submitted"
            )
            if duplicate:
                raise AssertionError("duplicate insert attempted")
            row = {
                "id": str(uuid4()),
                "resident_id": str(payload["resident_id"]),
                "teaching_event_id": str(payload["event_id"]),
                "status": "submitted",
                "posting_code": payload.get("posting_code"),
            }
            self.attendance.append(row)
            return FakeResult(rows=[row])

        if "INSERT INTO external_attendance_records" in sql:
            duplicate = any(
                row
                for row in self.external_attendance
                if row["external_resident_id"] == str(payload["external_resident_id"])
                and row["teaching_event_id"] == str(payload["event_id"])
                and row["status"] == "submitted"
            )
            if duplicate:
                raise AssertionError("duplicate external insert attempted")
            row = {
                "id": str(uuid4()),
                "external_resident_id": str(payload["external_resident_id"]),
                "teaching_event_id": str(payload["event_id"]),
                "status": "submitted",
                "posting_code": payload.get("posting_code"),
                "submitted_at": self.now,
            }
            self.external_attendance.append(row)
            return FakeResult(rows=[row])

        if "UPDATE attendance_records" in sql:
            updated = 0
            for row in self.attendance:
                if row["id"] == str(payload["attendance_id"]) and row["resident_id"] == str(payload["resident_id"]):
                    row["status"] = "removed"
                    updated += 1
            return FakeResult(rowcount=updated)

        if "INSERT INTO teaching_events" in sql:
            row = self._event(
                str(uuid4()),
                payload["posting_code"],
                payload["teaching_name"],
                payload["event_date"],
                start_time=payload["start_time"],
                duration_hours=payload["duration_hours"],
            )
            row["end_time"] = payload["end_time"]
            row["session_type_id"] = (
                str(payload["session_type_id"]) if payload.get("session_type_id") else None
            )
            row["is_adhoc"] = True
            row["created_by_role"] = (
                "external_resident"
                if "external_resident" in sql
                else "resident"
            )
            self.events.append(row)
            return FakeResult(rows=[row])

        if "INSERT INTO external_residents" in sql:
            row = {
                "id": str(uuid4()),
                "name": payload["name"],
                "mcr": payload["mcr"],
                "home_cluster": payload["home_cluster"],
                "current_nhg_posting_code": payload["current_nhg_posting_code"],
                "status": "active",
            }
            self.external_residents.append(row)
            return FakeResult(rows=[row])

        if "INSERT INTO external_resident_postings" in sql:
            row = {
                "id": str(uuid4()),
                "external_resident_id": str(payload["external_resident_id"]),
                "posting_code": payload["posting_code"],
                "start_date": payload["start_date"],
                "end_date": None,
                "is_current": True,
            }
            self.external_resident_postings.append(row)
            return FakeResult(rows=[row])

        if "UPDATE external_resident_postings" in sql:
            for row in self.external_resident_postings:
                if (
                    row["external_resident_id"] == str(payload["external_resident_id"])
                    and row["is_current"] is True
                    and row["end_date"] is None
                ):
                    row["end_date"] = payload["end_date"]
                    row["is_current"] = False
            return FakeResult(rowcount=1)

        if "UPDATE external_residents" in sql and "SET current_nhg_posting_code" in sql:
            rows: list[dict] = []
            for row in self.external_residents:
                if row["id"] == str(payload["external_resident_id"]):
                    row["current_nhg_posting_code"] = payload["posting_code"]
                    rows.append(row)
            return FakeResult(rows=rows)

        if "FROM external_attendance_records attendance" in sql:
            rows = [
                {
                    "attendance_id": row["id"],
                    "teaching_event_id": row["teaching_event_id"],
                    "status": row["status"],
                    "submitted_at": row["submitted_at"],
                    **next(
                        event
                        for event in self.events
                        if event["id"] == row["teaching_event_id"]
                    ),
                }
                for row in self.external_attendance
                if row["external_resident_id"] == str(payload["subject_id"])
                and row["status"] != "removed"
            ]
            if "status" in payload:
                rows = [row for row in rows if row["status"] == payload["status"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            rows.sort(key=lambda row: (row["event_date"], row["submitted_at"]), reverse=True)
            return FakeResult(rows=rows)

        if "FROM attendance_records attendance" in sql:
            rows = [
                {
                    "attendance_id": row["id"],
                    "teaching_event_id": row["teaching_event_id"],
                    "status": row["status"],
                    "submitted_at": self.now,
                    **next(
                        event
                        for event in self.events
                        if event["id"] == row["teaching_event_id"]
                    ),
                }
                for row in self.attendance
                if row["resident_id"] == str(payload["subject_id"])
                and row["status"] != "removed"
            ]
            if "status" in payload:
                rows = [row for row in rows if row["status"] == payload["status"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            rows.sort(key=lambda row: (row["event_date"], row["submitted_at"]), reverse=True)
            return FakeResult(rows=rows)

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")
