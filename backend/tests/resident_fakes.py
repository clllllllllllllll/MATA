from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.services.reporting_period_status import is_reporting_period_effectively_active


PROGRAMME_SEED_ROWS = (
    ("AIM", "Advanced Internal Medicine"),
    ("ANAES", "Anaesthesiology"),
    ("CARDIO", "Cardiology"),
    ("DERM", "Dermatology"),
    ("DR", "Diagnostic Radiology"),
    ("EM", "Emergency Medicine"),
    ("ENDO", "Endocrinology"),
    ("ENT", "Otorhinolaryngology"),
    ("EYE", "Ophthalmology"),
    ("FM", "Family Medicine"),
    ("GASTRO", "Gastroenterology"),
    ("GERI", "Geriatric Medicine"),
    ("GS", "General Surgery"),
    ("ID", "Infectious Diseases"),
    ("IM", "Internal Medicine"),
    ("MEDONCO", "Medical Oncology"),
    ("ORTHO", "Orthopaedic Surgery"),
    ("PATH", "Pathology"),
    ("PSY", "Psychiatry"),
    ("REHAB", "Rehabilitation Medicine"),
    ("RENAL", "Renal Medicine"),
    ("RESPI", "Respiratory Medicine"),
    ("RHEUM", "Rheumatology"),
    ("SPORTSMED", "Sports Medicine"),
    ("SIG", "Surgery-In-General"),
    ("URO", "Urology"),
    ("MICROB", "Pathology (Microbiology)"),
    ("PALLMED", "Palliative Medicine"),
)


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

    def scalar_one(self):
        return self._scalar


class FakeResidentSession:
    def __init__(self, *, today: date | None = None) -> None:
        self.today = today or date.today()
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
        self.inactive_period_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.other_resident_id = str(uuid4())
        self.admin_id = str(uuid4())
        self.secretary_id = str(uuid4())
        self.session_type_id = str(uuid4())
        self.second_session_type_id = str(uuid4())
        self.adhoc_session_type_id = str(uuid4())
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
        self.rate_limit_buckets: dict[tuple[str, str, datetime, int], int] = {}
        self.rate_limit_rows: list[dict[str, object]] = []

        self.users = [
            {
                "id": self.admin_id,
                "email": "pc@nhg.com.sg",
                "password_hash": "password",
                "role": "admin",
                "name": "Programme Coordinator",
                "posting_code": None,
                "programme_scope": ["GRM", "DR"],
                "admin_level": "programme",
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
                "admin_level": "programme",
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
            {
                "code": "TTSHCardio",
                "display_name": "TTSH Cardiology",
                "institution": "TTSH",
                "supports_secretary_events": True,
            },
            {
                "code": "TTSHNeuro",
                "display_name": "TTSH Neurology",
                "institution": "TTSH",
                "supports_secretary_events": True,
            },
            {
                "code": "KTPHGerMed",
                "display_name": "KTPH Geriatric Medicine",
                "institution": "KTPH",
                "supports_secretary_events": False,
            },
        ]
        self.programmes = [
            {
                "code": "GRM",
                "name": "Geriatric Medicine",
                "native_teaching_posting_code": None,
            },
            {
                "code": "GERI",
                "name": "Geriatric Medicine",
                "native_teaching_posting_code": None,
            },
            {
                "code": "DR",
                "name": "Diagnostic Radiology",
                "native_teaching_posting_code": None,
            },
        ]
        self.programme_institution_posting_map = [
            {
                "id": str(uuid4()),
                "programme_code": code,
                "institution_code": "TTSH",
                "posting_code": None,
                "status": "pending",
                "display_order": display_order,
            }
            for display_order, (code, _name) in enumerate(PROGRAMME_SEED_ROWS)
        ]
        self.secretary_programme_pools = [
            {
                "posting_code": "TTSHCardio",
                "programme_code": "GERI",
                "is_active": True,
            },
            {
                "posting_code": "KTPHGerMed",
                "programme_code": "GERI",
                "is_active": True,
            },
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
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
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
        self.teaching_targets = [
            self._target("TTSHCardio", self.adhoc_session_type_id),
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
        *,
        programme_code: str = "GRM",
        r_year: str = "R2",
        session_type: str | None = None,
        is_tracked: bool = True,
    ) -> dict:
        return {
            "keyword": keyword,
            "posting_code": posting_code,
            "programme_code": programme_code,
            "r_year": r_year,
            "reporting_period_id": self.period_id,
            "session_type_id": session_type_id,
            "session_type": session_type or f"{keyword} [{duration_hours}h]",
            "duration_hours": duration_hours,
            "is_tracked": is_tracked,
        }

    def _target(
        self,
        posting_code: str,
        session_type_id: str,
        *,
        programme_code: str = "GRM",
        r_year: str = "R2",
        session_type: str = "Department/Programme Teaching [1h]",
        duration_hours: Decimal = Decimal("1.0"),
        is_tracked: bool = True,
    ) -> dict:
        return {
            "posting_code": posting_code,
            "programme_code": programme_code,
            "r_year": r_year,
            "reporting_period_id": self.period_id,
            "session_type_id": session_type_id,
            "session_type": session_type,
            "duration_hours": duration_hours,
            "is_tracked": is_tracked,
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
            "created_for_programme_code": None,
            "teaching_name": teaching_name,
            "details_of_session": None,
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

    def _posting_label(self, posting_code: str | None) -> str | None:
        if posting_code is None:
            return None
        posting = next(
            (
                row
                for row in self.posting_codes
                if row["code"] == posting_code
            ),
            None,
        )
        return (posting or {}).get("display_name") or posting_code

    def _resident_with_current_posting(
        self,
        resident: dict,
        *,
        reporting_period_id: str | None,
    ) -> dict:
        def rank(posting: dict) -> tuple[int, int, date, str]:
            posting_end = posting.get("end_date") or date.max
            if posting["start_date"] <= self.today <= posting_end:
                bucket = 0
            elif posting["start_date"] > self.today:
                bucket = 1
            else:
                bucket = 2
            distance = (
                (posting["start_date"] - self.today).days
                if posting["start_date"] > self.today
                else (self.today - min(posting_end, self.today)).days
            )
            return bucket, distance, -posting["start_date"].toordinal(), posting["posting_code"]

        eligible = [
            posting
            for posting in self.resident_postings
            if posting["resident_id"] == resident["id"]
            and posting["status"] in {"active", "loa_working"}
            and reporting_period_id is not None
            and posting["reporting_period_id"] == reporting_period_id
        ]
        current_posting = min(eligible, key=rank) if eligible else None
        posting_code = current_posting["posting_code"] if current_posting else None
        return {
            **resident,
            "current_posting_code": posting_code,
            "current_posting_label": self._posting_label(posting_code),
        }

    def _external_resident_with_current_posting(
        self,
        resident: dict,
        *,
        reporting_period_id: str | None,
        reporting_period_start: date,
        reporting_period_end: date,
    ) -> dict:
        def rank(posting: dict) -> tuple[int, int, date, str]:
            posting_end = posting.get("end_date") or date.max
            if posting["start_date"] <= self.today <= posting_end:
                bucket = 0
            elif posting["start_date"] > self.today:
                bucket = 1
            else:
                bucket = 2
            distance = (
                (posting["start_date"] - self.today).days
                if posting["start_date"] > self.today
                else (self.today - min(posting_end, self.today)).days
            )
            return bucket, distance, -posting["start_date"].toordinal(), posting["posting_code"]

        eligible = [
            posting
            for posting in self.external_resident_postings
            if posting["external_resident_id"] == resident["id"]
            and reporting_period_id is not None
            and posting["start_date"] <= reporting_period_end
            and (posting.get("end_date") or date.max) >= reporting_period_start
        ]
        current_posting = min(eligible, key=rank) if eligible else None
        posting_code = current_posting["posting_code"] if current_posting else None
        return {
            **resident,
            "current_posting_code": posting_code,
            "current_posting_label": self._posting_label(posting_code),
        }

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    def _execute_rate_limit_bucket(self, payload: dict) -> FakeResult:
        key = (
            payload["scope"],
            payload["key_hash"],
            payload["window_start"],
            payload["window_seconds"],
        )
        request_count = self.rate_limit_buckets.get(key, 0) + 1
        self.rate_limit_buckets[key] = request_count
        self.rate_limit_rows.append(
            {
                "scope": payload["scope"],
                "key_hash": payload["key_hash"],
                "window_start": payload["window_start"],
                "window_seconds": payload["window_seconds"],
                "request_count": request_count,
                "expires_at": payload["expires_at"],
            }
        )
        return FakeResult(rows=[{"request_count": request_count}])

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "INSERT INTO rate_limit_buckets" in sql:
            return self._execute_rate_limit_bucket(payload)

        if "DELETE FROM rate_limit_buckets" in sql:
            return FakeResult(rowcount=0)

        if "FROM users" in sql:
            rows = [
                row
                for row in self.users
                if (
                    payload.get("role") == "staff"
                    or row["role"] == payload.get("role")
                )
                and row["email"].lower() == payload.get("email", "").lower()
                and row["is_active"]
            ]
            if "user_id" in payload:
                rows = [row for row in self.users if row["id"] == str(payload["user_id"]) and row["is_active"]]
            return FakeResult(rows=rows)

        if "FROM residents r" in sql and "WHERE r.mcr = :mcr" in sql:
            rows = [
                self._resident_with_current_posting(
                    row,
                    reporting_period_id=payload.get("reporting_period_id"),
                )
                for row in self.residents
                if row["mcr"] == payload.get("mcr")
            ]
            return FakeResult(rows=rows)

        if "FROM residents r" in sql and "WHERE r.id = :resident_id" in sql:
            rows = [
                self._resident_with_current_posting(
                    row,
                    reporting_period_id=payload.get("reporting_period_id"),
                )
                for row in self.residents
                if row["id"] == str(payload.get("resident_id"))
            ]
            return FakeResult(rows=rows)

        if "FROM residents" in sql and "WHERE mcr" in sql:
            rows = [row for row in self.residents if row["mcr"] == payload.get("mcr")]
            if "SELECT 1" in sql:
                return FakeResult(scalar=1 if rows else None)
            return FakeResult(rows=rows)

        if "FROM residents" in sql and "WHERE id" in sql:
            rows = [row for row in self.residents if row["id"] == str(payload.get("resident_id"))]
            return FakeResult(rows=rows)

        if "FROM external_residents er" in sql and "WHERE er.mcr = :mcr" in sql:
            rows = [
                self._external_resident_with_current_posting(
                    row,
                    reporting_period_id=payload.get("reporting_period_id"),
                    reporting_period_start=payload.get("reporting_period_start", date.max),
                    reporting_period_end=payload.get("reporting_period_end", date.min),
                )
                for row in self.external_residents
                if row["mcr"] == payload.get("mcr")
            ]
            return FakeResult(rows=rows)

        if "FROM external_residents" in sql and "WHERE mcr" in sql:
            rows = [row for row in self.external_residents if row["mcr"] == payload.get("mcr")]
            if "SELECT 1" in sql:
                return FakeResult(scalar=1 if rows else None)
            return FakeResult(rows=rows)

        if "FROM external_residents er" in sql and "WHERE er.id = :external_resident_id" in sql:
            lookup_id = str(payload.get("external_resident_id"))
            rows = [
                self._external_resident_with_current_posting(
                    row,
                    reporting_period_id=payload.get("reporting_period_id"),
                    reporting_period_start=payload.get("reporting_period_start", date.max),
                    reporting_period_end=payload.get("reporting_period_end", date.min),
                )
                for row in self.external_residents
                if row["id"] == lookup_id
            ]
            return FakeResult(rows=rows)

        if "FROM external_residents" in sql and "WHERE id" in sql:
            lookup_id = str(
                payload.get("external_resident_id")
                or payload.get("subject_id")
                or payload.get("user_id")
            )
            rows = [row for row in self.external_residents if row["id"] == lookup_id]
            return FakeResult(rows=rows)

        if "FROM external_resident_postings" in sql and "SELECT" in sql:
            start_date = payload.get("start_date") or payload.get("on_date") or date.min
            end_date = payload.get("end_date") or payload.get("on_date") or date.max
            rows = [
                row
                for row in self.external_resident_postings
                if row["external_resident_id"] == str(payload.get("external_resident_id"))
                and row["start_date"] <= end_date
                and ((row.get("end_date") or date.max) >= start_date)
            ]
            rows.sort(key=lambda row: (row["start_date"], row["posting_code"]))
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

        if "SELECT display_name" in sql and "FROM posting_codes" in sql:
            posting = next(
                (
                    row
                    for row in self.posting_codes
                    if row["code"] == payload.get("posting_code")
                ),
                None,
            )
            return FakeResult(rows=[posting] if posting else [])

        if "SELECT code, institution" in sql and "FROM posting_codes" in sql:
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

        if "programme_institution_posting_options" in sql:
            rows = []
            for mapping in sorted(
                self.programme_institution_posting_map,
                key=lambda row: (
                    row["display_order"],
                    row["programme_code"],
                    row["institution_code"],
                ),
            ):
                if mapping["status"] not in {"pending", "active"}:
                    continue
                programme = next(
                    (
                        row
                        for row in self.programmes
                        if row["code"] == mapping["programme_code"]
                    ),
                    None,
                )
                if programme is None:
                    programme_name = next(
                        (
                            name
                            for code, name in PROGRAMME_SEED_ROWS
                            if code == mapping["programme_code"]
                        ),
                        None,
                    )
                    if programme_name is None:
                        continue
                    programme = {
                        "code": mapping["programme_code"],
                        "name": programme_name,
                    }
                posting = next(
                    (
                        row
                        for row in self.posting_codes
                        if row["code"] == mapping["posting_code"]
                    ),
                    None,
                )
                rows.append(
                    {
                        "programme_code": programme["code"],
                        "programme_name": programme["name"],
                        "institution_code": mapping["institution_code"],
                        "status": mapping["status"],
                        "posting_code": mapping["posting_code"],
                        "resolved_posting_code": posting["code"] if posting else None,
                        "display_order": mapping["display_order"],
                    }
                )
            return FakeResult(rows=rows)

        if "programme_institution_posting_resolve" in sql:
            mapping = next(
                (
                    row
                    for row in self.programme_institution_posting_map
                    if row["programme_code"] == payload.get("programme_code")
                    and row["institution_code"] == payload.get("institution_code")
                ),
                None,
            )
            if mapping is None:
                return FakeResult()
            programme = next(
                (
                    row
                    for row in self.programmes
                    if row["code"] == mapping["programme_code"]
                ),
                None,
            )
            posting = next(
                (
                    row
                    for row in self.posting_codes
                    if row["code"] == mapping["posting_code"]
                ),
                None,
            )
            return FakeResult(
                rows=[
                    {
                        "status": mapping["status"],
                        "posting_code": mapping["posting_code"],
                        "resolved_programme_code": programme["code"] if programme else None,
                        "resolved_posting_code": posting["code"] if posting else None,
                    }
                ]
            )

        if "external_registration_options:native" in sql:
            rows = []
            for programme in self.programmes:
                posting = next(
                    (
                        row
                        for row in self.posting_codes
                        if row["code"] == programme.get("native_teaching_posting_code")
                    ),
                    None,
                )
                if posting is not None and posting.get("institution") in {"TTSH", "WH", "KTPH"}:
                    rows.append(
                        {
                            "programme_code": programme["code"],
                            "programme_name": programme["name"],
                            "institution": posting["institution"],
                            "posting_code": posting["code"],
                        }
                    )
            return FakeResult(rows=rows)

        if "external_registration_options:secretary_pool" in sql:
            rows = []
            for pool in self.secretary_programme_pools:
                programme = next(
                    (row for row in self.programmes if row["code"] == pool["programme_code"]),
                    None,
                )
                posting = next(
                    (row for row in self.posting_codes if row["code"] == pool["posting_code"]),
                    None,
                )
                if (
                    programme is not None
                    and posting is not None
                    and pool["is_active"]
                    and posting.get("institution") in {"TTSH", "WH", "KTPH"}
                ):
                    rows.append(
                        {
                            "programme_code": programme["code"],
                            "programme_name": programme["name"],
                            "institution": posting["institution"],
                            "posting_code": posting["code"],
                        }
                    )
            return FakeResult(rows=rows)

        if "external_registration_options:teaching_targets" in sql:
            rows = []
            seen: set[tuple[str, str]] = set()
            for target in self.teaching_targets:
                programme = next(
                    (row for row in self.programmes if row["code"] == target["programme_code"]),
                    None,
                )
                posting = next(
                    (row for row in self.posting_codes if row["code"] == target["posting_code"]),
                    None,
                )
                candidate_key = (target["programme_code"], target["posting_code"])
                if (
                    programme is not None
                    and posting is not None
                    and posting.get("institution") in {"TTSH", "WH", "KTPH"}
                    and candidate_key not in seen
                ):
                    seen.add(candidate_key)
                    rows.append(
                        {
                            "programme_code": programme["code"],
                            "programme_name": programme["name"],
                            "institution": posting["institution"],
                            "posting_code": posting["code"],
                        }
                    )
            return FakeResult(rows=rows)

        if "FROM secretary_programme_pools" in sql and "JOIN posting_codes" in sql:
            rows = []
            for pool in self.secretary_programme_pools:
                posting = next(
                    (
                        row
                        for row in self.posting_codes
                        if row["code"] == pool["posting_code"]
                    ),
                    None,
                )
                if (
                    posting is not None
                    and pool["programme_code"] == payload.get("programme_code")
                    and pool["is_active"]
                    and posting.get("institution") == payload.get("institution")
                ):
                    rows.append({"posting_code": posting["code"]})
            rows.sort(key=lambda row: row["posting_code"])
            return FakeResult(rows=rows)

        if "FROM teaching_targets tt" in sql and "JOIN session_types st" in sql:
            rows = [
                {
                    "session_type_id": row["session_type_id"],
                    "session_type": row["session_type"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": row["is_tracked"],
                    "is_global": False,
                    "r_year": row["r_year"],
                }
                for row in self.teaching_targets
                if row["posting_code"] == payload.get("posting_code")
                and row["programme_code"] == payload.get("programme_code")
                and row["r_year"] in {payload.get("r_year"), "ALL"}
                and row["reporting_period_id"] == str(payload.get("reporting_period_id"))
                and row["session_type"] == payload.get("session_type")
            ]
            rows.sort(key=lambda row: (0 if row["r_year"] == payload.get("r_year") else 1, row["session_type"]))
            return FakeResult(rows=rows[:1])

        if "FROM teaching_targets" in sql and "JOIN posting_codes" in sql:
            rows = []
            seen: set[str] = set()
            for target in self.teaching_targets:
                posting = next(
                    (row for row in self.posting_codes if row["code"] == target["posting_code"]),
                    None,
                )
                if (
                    posting is not None
                    and target["programme_code"] == payload.get("programme_code")
                    and posting.get("institution") == payload.get("institution")
                    and posting["code"] not in seen
                ):
                    seen.add(posting["code"])
                    rows.append({"posting_code": posting["code"]})
            rows.sort(key=lambda row: row["posting_code"])
            return FakeResult(rows=rows)

        if "SELECT 1" in sql and "FROM posting_codes" in sql:
            exists = any(row for row in self.posting_codes if row["code"] == payload.get("posting_code"))
            return FakeResult(scalar=1 if exists else None)

        if "SELECT 1" in sql and "FROM programmes" in sql:
            exists = any(row for row in self.programmes if row["code"] == payload.get("programme_code"))
            return FakeResult(scalar=1 if exists else None)

        if "native_teaching_posting_code" in sql and "FROM programmes" in sql:
            rows = [
                {
                    "native_teaching_posting_code": row.get("native_teaching_posting_code"),
                }
                for row in self.programmes
                if row["code"] == payload.get("programme_code")
            ]
            return FakeResult(rows=rows[:1])

        if "FROM reporting_periods" in sql:
            if "/* reporting_period_resolution:explicit */" in sql:
                rows = [
                    row
                    for row in self.reporting_periods
                    if row["id"] == str(payload["reporting_period_id"])
                ]
                return FakeResult(rows=rows)
            if "/* reporting_period_resolution:list */" in sql:
                return FakeResult(rows=list(self.reporting_periods))
            rows = [
                row
                for row in self.reporting_periods
                if is_reporting_period_effectively_active(row, as_of_date=self.today)
            ]
            rows.sort(key=lambda row: row["start_date"], reverse=True)
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
                    "teaching_name": row["name"],
                    "keyword": row["name"],
                    "session_type_id": None,
                    "session_type": row["name"],
                    "session_type_name": row["name"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": False,
                    "is_global": True,
                }
                for row in self.global_session_types
                if row["is_active"]
                and ("teaching_name" not in payload or row["name"] == payload["teaching_name"])
            ]
            return FakeResult(rows=rows)

        if "pc.code AS posting_code" in sql and "FROM teaching_name_catalogue" in sql:
            if "programme_code" in payload:
                catalogue_rows = [
                    row
                    for row in self.catalogue
                    if row["programme_code"] == payload.get("programme_code")
                    and row["r_year"] in {payload.get("r_year"), "ALL"}
                    and row["reporting_period_id"] == str(payload.get("reporting_period_id"))
                ]
            else:
                catalogue_rows = [
                    row
                    for row in self.catalogue
                    if row["reporting_period_id"] == str(payload.get("reporting_period_id"))
                ]
            rows = []
            seen: set[tuple[str, str]] = set()
            for catalogue_row in catalogue_rows:
                posting = next(
                    (
                        row
                        for row in self.posting_codes
                        if row["code"] == catalogue_row["posting_code"]
                    ),
                    None,
                )
                if posting is None:
                    continue
                key = (posting["code"], catalogue_row["programme_code"])
                if key in seen:
                    continue
                seen.add(key)
                programme = next(
                    (
                        row
                        for row in self.programmes
                        if row["code"] == catalogue_row["programme_code"]
                    ),
                    None,
                )
                rows.append(
                    {
                        "posting_code": posting["code"],
                        "label": posting.get("display_name") or posting["code"],
                        "programme_code": catalogue_row["programme_code"],
                        "programme_name": programme.get("name") if programme else None,
                    }
                )
            rows.sort(key=lambda row: (row["label"], row["posting_code"], row["programme_code"]))
            return FakeResult(rows=rows)

        if "FROM teaching_name_catalogue" in sql:
            if "programme_code" in payload:
                rows = [
                    {
                        "teaching_name": row["keyword"],
                        "keyword": row["keyword"],
                        "session_type_id": row["session_type_id"],
                        "session_type": row["session_type"],
                        "session_type_name": row["session_type"],
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
                        "teaching_name": row["keyword"],
                        "keyword": row["keyword"],
                        "session_type_id": row["session_type_id"],
                        "session_type": row["session_type"],
                        "session_type_name": row["session_type"],
                        "duration_hours": row["duration_hours"],
                        "is_tracked": row["is_tracked"],
                        "is_global": False,
                    }
                    for row in self.catalogue
                    if row["posting_code"] == payload.get("posting_code")
                    and row["reporting_period_id"] == str(payload.get("reporting_period_id"))
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
                    {
                        **row,
                        "already_attended": row["id"] in submitted,
                    }
                    for row in self.events
                    if row["posting_code"] == posting_code
                    and row["event_date"] <= today
                ]
                if "date_from" in payload and payload["date_from"] is not None:
                    rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
                if "date_to" in payload and payload["date_to"] is not None:
                    rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
                if "teaching_name" in payload and payload["teaching_name"]:
                    rows = [row for row in rows if row["teaching_name"] == payload["teaching_name"]]
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
                and row.get("created_by_role") in {"secretary", "programme_pc", None}
                and row.get("created_for_programme_code") in {None, payload.get("programme_code")}
            ]
            if "date_from" in payload and payload["date_from"] is not None:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload and payload["date_to"] is not None:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            if "teaching_name" in payload and payload["teaching_name"]:
                rows = [row for row in rows if row["teaching_name"] == payload["teaching_name"]]
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

        if "FROM attendance_records" in sql and "teaching_event_id = :event_id" in sql:
            rows = [
                row
                for row in self.attendance
                if row["resident_id"] == str(payload.get("resident_id"))
                and row["teaching_event_id"] == str(payload.get("event_id"))
            ]
            return FakeResult(rows=rows[:1])

        if "FROM attendance_records" in sql and "id = :attendance_id" in sql:
            rows = [
                row
                for row in self.attendance
                if row["id"] == str(payload.get("attendance_id"))
                and row["resident_id"] == str(payload.get("resident_id"))
            ]
            return FakeResult(rows=rows[:1])

        if "FROM external_attendance_records" in sql and "id = :attendance_id" in sql:
            rows = [
                row
                for row in self.external_attendance
                if row["id"] == str(payload.get("attendance_id"))
                and row["external_resident_id"] == str(payload.get("external_resident_id"))
            ]
            return FakeResult(rows=rows[:1])

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
            )
            if duplicate:
                raise AssertionError("duplicate insert attempted")
            row = {
                "id": str(uuid4()),
                "resident_id": str(payload["resident_id"]),
                "teaching_event_id": str(payload["event_id"]),
                "status": "submitted",
                "posting_code": payload.get("posting_code"),
                "submitted_at": self.now,
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
            rows: list[dict] = []
            if "SET status = 'submitted'" in sql:
                for row in self.attendance:
                    if (
                        row["id"] == str(payload["attendance_id"])
                        and row["resident_id"] == str(payload["resident_id"])
                        and row["status"] == "removed"
                    ):
                        row["status"] = "submitted"
                        row["posting_code"] = payload.get("posting_code")
                        row["submitted_at"] = self.now
                        rows.append(row)
                return FakeResult(rows=rows, rowcount=len(rows))
            for row in self.attendance:
                if (
                    row["id"] == str(payload["attendance_id"])
                    and row["resident_id"] == str(payload["resident_id"])
                    and row["status"] == "submitted"
                ):
                    row["status"] = "removed"
                    row["submitted_at"] = self.now
                    rows.append(row)
            return FakeResult(rows=rows, rowcount=len(rows))

        if "UPDATE external_attendance_records" in sql:
            rows: list[dict] = []
            for row in self.external_attendance:
                if (
                    row["id"] == str(payload["attendance_id"])
                    and row["external_resident_id"] == str(payload["external_resident_id"])
                    and row["status"] == "submitted"
                ):
                    row["status"] = "removed"
                    row["submitted_at"] = self.now
                    rows.append(row)
            return FakeResult(rows=rows, rowcount=len(rows))

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
            row["details_of_session"] = payload.get("details_of_session")
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
                "end_date": payload.get("end_date"),
                "is_current": payload.get("is_current", True),
            }
            self.external_resident_postings.append(row)
            return FakeResult(rows=[row])

        if "DELETE FROM external_resident_postings" in sql:
            before = len(self.external_resident_postings)
            self.external_resident_postings = [
                row
                for row in self.external_resident_postings
                if row["external_resident_id"] != str(payload["external_resident_id"])
            ]
            return FakeResult(rowcount=before - len(self.external_resident_postings))

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
            include_removed = (
                "attendance.status IN ('submitted', 'removed')" in sql
                or payload.get("status") == "removed"
            )
            rows = [
                {
                    "attendance_id": row["id"],
                    "teaching_event_id": row["teaching_event_id"],
                    "status": row["status"],
                    "submitted_at": row["submitted_at"],
                    "source": "adhoc"
                    if next(event for event in self.events if event["id"] == row["teaching_event_id"])["is_adhoc"]
                    else "scheduled",
                    **next(
                        event
                        for event in self.events
                        if event["id"] == row["teaching_event_id"]
                    ),
                }
                for row in self.external_attendance
                if row["external_resident_id"] == str(payload["subject_id"])
                and (include_removed or row["status"] != "removed")
            ]
            if "status" in payload:
                rows = [row for row in rows if row["status"] == payload["status"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            if "posting_code" in payload:
                rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
            if "teaching_name" in payload:
                rows = [row for row in rows if row["teaching_name"] == payload["teaching_name"]]
            if "is_adhoc" in payload:
                rows = [row for row in rows if row["is_adhoc"] is payload["is_adhoc"]]
            for row in rows:
                row.pop("created_by_role", None)
                row.pop("created_for_programme_code", None)
            rows.sort(key=lambda row: (row["event_date"], row["submitted_at"]), reverse=True)
            return FakeResult(rows=rows[payload.get("offset", 0) : payload.get("offset", 0) + payload.get("limit", len(rows))])

        if "FROM attendance_records attendance" in sql:
            include_removed = (
                "attendance.status IN ('submitted', 'removed')" in sql
                or payload.get("status") == "removed"
            )
            rows = [
                {
                    "attendance_id": row["id"],
                    "teaching_event_id": row["teaching_event_id"],
                    "status": row["status"],
                    "submitted_at": row.get("submitted_at", self.now),
                    "source": "adhoc"
                    if next(event for event in self.events if event["id"] == row["teaching_event_id"])["is_adhoc"]
                    else "scheduled",
                    **next(
                        event
                        for event in self.events
                        if event["id"] == row["teaching_event_id"]
                    ),
                }
                for row in self.attendance
                if row["resident_id"] == str(payload["subject_id"])
                and (include_removed or row["status"] != "removed")
            ]
            if "status" in payload:
                rows = [row for row in rows if row["status"] == payload["status"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            if "posting_code" in payload:
                rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
            if "teaching_name" in payload:
                rows = [row for row in rows if row["teaching_name"] == payload["teaching_name"]]
            if "is_adhoc" in payload:
                rows = [row for row in rows if row["is_adhoc"] is payload["is_adhoc"]]
            for row in rows:
                row.pop("created_by_role", None)
                row.pop("created_for_programme_code", None)
            rows.sort(key=lambda row: (row["event_date"], row["start_time"], row["submitted_at"]), reverse=True)
            return FakeResult(rows=rows[payload.get("offset", 0) : payload.get("offset", 0) + payload.get("limit", len(rows))])

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")
