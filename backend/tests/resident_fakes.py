from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

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

TTSH_ACTIVE_REGISTRATION_MAPPINGS = (
    ("AIM", "TTSHGenMed"),
    ("ANAES", "TTSHAnaes"),
    ("CARDIO", "TTSHCardio"),
    ("DERM", "NSCDermat"),
    ("DR", "TTSHDiagRd"),
    ("EM", "TTSHEmgMed"),
    ("ENDO", "TTSHEndocr"),
    ("ENT", "TTSHOtolar"),
    ("EYE", "TTSHOphtha"),
    ("GASTRO", "TTSHGas"),
    ("GERI", "TTSHGerMed"),
    ("GS", "TTSHGenSrg"),
    ("ID", "TTSHInfect"),
    ("IM", "TTSHGenMed"),
    ("MEDONCO", "TTSHMedOnc"),
    ("ORTHO", "TTSHOrtSrg"),
    ("PSY", "TTSHPsychi"),
    ("REHAB", "TTSHRehabi"),
    ("RENAL", "TTSHRenal"),
    ("RESPI", "TTSHRespir"),
    ("RHEUM", "TTSHRheuma"),
    ("SIG", "TTSHGenSrg"),
    ("URO", "TTSHUrolog"),
    ("MICROB", "TTSHLabMed"),
)

TTSH_INACTIVE_REGISTRATION_PROGRAMMES = (
    "FM",
    "PATH",
    "SPORTSMED",
    "PALLMED",
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
        self.global_session_type_id = str(uuid4())
        self.weekend_event_id = str(uuid4())
        self.external_resident_id = str(uuid4())
        self.other_external_resident_id = str(uuid4())
        self.external_existing_attendance_id = str(uuid4())
        self.rate_limit_buckets: dict[tuple[str, str, datetime, int], int] = {}
        self.rate_limit_rows: list[dict[str, object]] = []
        self.executed_sql: list[str] = []

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
                "session_generation": 0,
                "session_issuance_blocked": False,
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
                "session_generation": 0,
                "session_issuance_blocked": False,
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
                "session_generation": 0,
            },
            {
                "id": self.other_resident_id,
                "name": "Resident Two",
                "mcr": "M54321B",
                "programme_code": "GRM",
                "r_year": "R2",
                "status": "active",
                "session_generation": 0,
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
        existing_posting_codes = {row["code"] for row in self.posting_codes}
        self.posting_codes.extend(
            {
                "code": posting_code,
                "display_name": posting_code,
                "institution": None,
                "supports_secretary_events": False,
            }
            for posting_code in dict.fromkeys(
                posting_code
                for _programme_code, posting_code in TTSH_ACTIVE_REGISTRATION_MAPPINGS
            )
            if posting_code not in existing_posting_codes
        )
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
        active_registration_mappings = dict(TTSH_ACTIVE_REGISTRATION_MAPPINGS)
        self.programme_institution_posting_map = [
            {
                "id": str(uuid4()),
                "programme_code": code,
                "institution_code": "TTSH",
                "posting_code": active_registration_mappings.get(code),
                "status": (
                    "active" if code in active_registration_mappings else "inactive"
                ),
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
                "session_generation": 0,
            },
            {
                "id": self.other_external_resident_id,
                "name": "External Resident Two",
                "mcr": "E54321B",
                "home_cluster": "SingHealth",
                "current_nhg_posting_code": "TTSHNeuro",
                "status": "active",
                "session_generation": 0,
            },
        ]
        self.external_resident_postings = [
            {
                "id": str(uuid4()),
                "external_resident_id": self.external_resident_id,
                "programme_code": "CARDIO",
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
        self.teaching_targets = [
            self._target("TTSHCardio", self.adhoc_session_type_id),
        ]
        self.global_session_types = [
            {
                "id": self.global_session_type_id,
                "name": "Department Meeting [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": True,
            }
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
            self._event(
                self.global_event_id,
                "TTSHCardio",
                "Department Meeting [1h]",
                recent_event_day,
                global_session_type_id=self.global_session_type_id,
            ),
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
        self.rollbacks = 0
        self.fail_commit = False
        self._rollback_snapshot: dict[str, list[dict]] | None = None
        self.teaching_event_lock_calls: list[str] = []
        self.native_attendance_lock_calls: list[tuple[int, int]] = []
        self.external_attendance_lock_calls: list[tuple[int, int]] = []
        self.native_attendance_removal_lock_calls: list[str] = []
        self.external_attendance_removal_lock_calls: list[str] = []
        self.adhoc_helper_calls: list[dict] = []
        self._adhoc_attendance_family: str | None = None
        self.pool_event_r_year_timings: dict[
            tuple[str, str, str, str, str], dict | None
        ] = {}

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
        teaching_name_id: str | None = None,
        global_session_type_id: str | None = None,
        source_reporting_period_id: str | None = None,
        source_programme_code: str | None = None,
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
            "teaching_name_id": teaching_name_id,
            "global_session_type_id": global_session_type_id,
            "source_reporting_period_id": source_reporting_period_id,
            "source_programme_code": source_programme_code,
            "session_type": f"{teaching_name} [{duration_hours}h]",
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

    def transaction_state(self) -> dict[str, list[dict]]:
        return {
            "events": deepcopy(self.events),
            "attendance": deepcopy(self.attendance),
            "external_attendance": deepcopy(self.external_attendance),
        }

    def fail_next_commit(self) -> None:
        self._rollback_snapshot = self.transaction_state()
        self.fail_commit = True

    async def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            self.fail_commit = False
            raise RuntimeError("forced commit failure")

    async def rollback(self) -> None:
        self.rollbacks += 1
        if self._rollback_snapshot is None:
            return
        snapshot = self._rollback_snapshot
        self._rollback_snapshot = None
        self.events = deepcopy(snapshot["events"])
        self.attendance = deepcopy(snapshot["attendance"])
        self.external_attendance = deepcopy(
            snapshot["external_attendance"]
        )

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
        self.executed_sql.append(sql)
        payload = dict(params or {})

        if "mata_rls.resolve_native_teaching_target" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload.get("event_id"))
                ),
                None,
            )
            if event is None:
                return FakeResult(rows=[])
            posting = next(
                (
                    row
                    for row in self.resident_postings
                    if row["resident_id"] == str(payload.get("resident_id"))
                    and row["start_date"] <= event["event_date"] <= row["end_date"]
                    and row["status"] in {"active", "loa_working"}
                ),
                None,
            )
            if posting is None:
                return FakeResult(
                    rows=[{"outcome": None, "unavailable_reason": "native_phase_unavailable"}]
                )
            key = (
                str(event.get("teaching_name_id")),
                str(event.get("source_reporting_period_id")),
                str(event.get("source_programme_code")),
                str(posting["posting_code"]),
                str(posting["r_year"]),
            )
            timing = self.pool_event_r_year_timings.get(key)
            if key in self.pool_event_r_year_timings and timing is None:
                return FakeResult(
                    rows=[{"outcome": None, "unavailable_reason": "mapping_unavailable"}]
                )
            if timing is None:
                target = next(
                    (
                        row
                        for row in self.teaching_targets
                        if row["posting_code"] == posting["posting_code"]
                        and row["programme_code"] == event.get("source_programme_code")
                        and row["r_year"] == posting["r_year"]
                        and row["reporting_period_id"]
                        == str(event.get("source_reporting_period_id"))
                    ),
                    None,
                )
                timing = {
                    "teaching_target_id": (
                        target["session_type_id"] if target else self.session_type_id
                    ),
                    "session_type_id": (
                        target["session_type_id"] if target else self.session_type_id
                    ),
                }
            mapped = timing.get("teaching_target_id") is not None
            return FakeResult(
                rows=[
                    {
                        "outcome": "mapped_target" if mapped else "pending_mapping",
                        "unavailable_reason": None,
                        "event_id": UUID(str(event["id"])),
                        "reporting_period_id": UUID(
                            str(event["source_reporting_period_id"])
                        ),
                        "programme_code": event["source_programme_code"],
                        "posting_code": posting["posting_code"],
                        "r_year": posting["r_year"],
                        "global_session_type_id": None,
                        "teaching_name_id": UUID(str(event["teaching_name_id"])),
                        "mapping_id": UUID(str(self.session_type_id)),
                        "mapping_revision": 1,
                        "teaching_target_id": (
                            UUID(str(timing["teaching_target_id"])) if mapped else None
                        ),
                        "session_type_id": (
                            UUID(str(timing["session_type_id"])) if mapped else None
                        ),
                    }
                ]
            )

        if "/* native_resident_event_session_timing */" in sql:
            session_type_id = str(payload.get("session_type_id"))
            timing = next(
                (
                    row
                    for row in self.pool_event_r_year_timings.values()
                    if row is not None
                    and str(row.get("session_type_id")) == session_type_id
                ),
                None,
            )
            target = next(
                (
                    row
                    for row in self.teaching_targets
                    if str(row["session_type_id"]) == session_type_id
                ),
                None,
            )
            source = timing or target
            return FakeResult(
                rows=(
                    [
                        {
                            "name": source.get("session_type_name")
                            or source.get("session_type"),
                            "duration_hours": source["duration_hours"],
                        }
                    ]
                    if source is not None
                    else [
                        {
                            "name": "Department/Programme Teaching [1h]",
                            "duration_hours": Decimal("1.0"),
                        }
                    ]
                )
            )

        if "INSERT INTO rate_limit_buckets" in sql:
            return self._execute_rate_limit_bucket(payload)

        if "DELETE FROM rate_limit_buckets" in sql:
            return FakeResult(rowcount=0)

        if "FOR SHARE" in sql and "session_generation" in sql:
            subject_id = str(payload.get("subject_id"))
            if "FROM users" in sql:
                rows = [
                    row
                    for row in self.users
                    if row["id"] == subject_id
                    and row["is_active"]
                    and not row["session_issuance_blocked"]
                ]
            elif "FROM external_residents" in sql:
                rows = [
                    row
                    for row in self.external_residents
                    if row["id"] == subject_id and row["status"] == "active"
                ]
            else:
                rows = [
                    row
                    for row in self.residents
                    if row["id"] == subject_id and row["status"] == "active"
                ]
            return FakeResult(
                scalar=rows[0]["session_generation"] if len(rows) == 1 else None
            )

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
            if payload.get("posting_code") is not None:
                rows = [
                    row
                    for row in rows
                    if row["posting_code"] == payload["posting_code"]
                ]
            if "start_date > :today" in sql:
                rows = [row for row in rows if row["start_date"] > payload["today"]]
            if "is_current = true" in sql:
                rows = [row for row in rows if row["is_current"] is True]
            rows.sort(
                key=lambda row: (
                    row["start_date"],
                    row["posting_code"],
                    row.get("programme_code") or "",
                )
            )
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
            resolved_programme_code = (
                programme["code"]
                if programme is not None
                else next(
                    (
                        code
                        for code, _name in PROGRAMME_SEED_ROWS
                        if code == mapping["programme_code"]
                    ),
                    None,
                )
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
                        "resolved_programme_code": resolved_programme_code,
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

        if "/* pool_event_timing:resolve_r_year */" in sql:
            key = (
                str(payload["teaching_name_id"]),
                str(payload["reporting_period_id"]),
                str(payload["programme_code"]),
                str(payload["posting_code"]),
                str(payload["r_year"]),
            )
            if key in self.pool_event_r_year_timings:
                row = self.pool_event_r_year_timings[key]
                return FakeResult(rows=[] if row is None else [row])
            target = next(
                (
                    row
                    for row in self.teaching_targets
                    if row["posting_code"] == payload.get("posting_code")
                    and row["programme_code"] == payload.get("programme_code")
                    and row["r_year"] == payload.get("r_year")
                    and row["reporting_period_id"]
                    == str(payload.get("reporting_period_id"))
                ),
                None,
            )
            if target is None:
                return FakeResult(
                    rows=[
                        {
                            "r_year": payload["r_year"],
                            "teaching_target_id": self.session_type_id,
                            "session_type_id": self.session_type_id,
                            "session_type_name": "Department/Programme Teaching [1h]",
                            "duration_hours": Decimal("1.0"),
                        }
                    ]
                )
            return FakeResult(
                rows=[
                    {
                        "r_year": target["r_year"],
                        "teaching_target_id": target["session_type_id"],
                        "session_type_id": target["session_type_id"],
                        "session_type_name": target["session_type"],
                        "duration_hours": target["duration_hours"],
                    }
                ]
            )

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

        if "mata_rls.create_adhoc_attendance" in sql:
            self.adhoc_helper_calls.append(payload)
            event = self._event(
                str(uuid4()),
                payload["posting_code"],
                payload["teaching_name"],
                payload["event_date"],
                start_time=payload["start_time"],
                duration_hours=payload["duration_hours"],
            )
            event["end_time"] = payload["end_time"]
            event["session_type_id"] = (
                str(payload["session_type_id"])
                if payload.get("session_type_id")
                else None
            )
            event["details_of_session"] = payload.get("details_of_session")
            event["is_adhoc"] = True
            event["created_by_role"] = (
                "external_resident"
                if self._adhoc_attendance_family == "external"
                else "resident"
            )
            self.events.append(event)

            attendance_id = str(uuid4())
            if self._adhoc_attendance_family == "external":
                self.external_attendance.append(
                    {
                        "id": attendance_id,
                        "external_resident_id": self.external_resident_id,
                        "teaching_event_id": event["id"],
                        "status": "submitted",
                        "posting_code": event["posting_code"],
                        "submitted_at": self.now,
                    }
                )
            elif self._adhoc_attendance_family == "native":
                self.attendance.append(
                    {
                        "id": attendance_id,
                        "resident_id": self.resident_id,
                        "teaching_event_id": event["id"],
                        "status": "submitted",
                        "posting_code": event["posting_code"],
                        "submitted_at": self.now,
                    }
                )
            else:
                raise AssertionError("ad-hoc helper called without a subject-family lock")
            return FakeResult(
                rows=[{"event_id": event["id"], "attendance_id": attendance_id}]
            )

        if "resident_submission_teaching_event_lock" in sql:
            self.teaching_event_lock_calls.append(str(payload["event_id"]))
            rows = [row for row in self.events if row["id"] == str(payload["event_id"])]
            return FakeResult(rows=rows)

        if "teaching_event_mutation_lock" in sql:
            lock_scope = str(payload["lock_scope"])
            prefix = "teaching-event:"
            if not lock_scope.startswith(prefix):
                raise AssertionError(
                    "teaching-event mutation lock used an invalid scope"
                )
            self.teaching_event_lock_calls.append(
                lock_scope.removeprefix(prefix)
            )
            return FakeResult()

        if (
            "FROM teaching_events" in sql
            and (
                "WHERE id = :event_id" in sql
                or "WHERE teaching_events.id = :event_id" in sql
            )
        ):
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

        if "native_attendance_overlap_lock" in sql:
            self.native_attendance_lock_calls.append(
                (payload["key1"], payload["key2"])
            )
            self._adhoc_attendance_family = "native"
            return FakeResult()

        if "native_attendance_database_overlap_lock" in sql:
            return FakeResult()

        if "external_attendance_overlap_lock" in sql:
            self.external_attendance_lock_calls.append(
                (payload["key1"], payload["key2"])
            )
            self._adhoc_attendance_family = "external"
            return FakeResult()

        if "external_attendance_database_overlap_lock" in sql:
            return FakeResult()

        if "native_attendance_overlap_candidates" in sql:
            rows = []
            for attendance in self.attendance:
                if (
                    attendance["resident_id"] != str(payload.get("resident_id"))
                    or attendance["status"] != "submitted"
                    or (
                        payload.get("event_id") is not None
                        and attendance["teaching_event_id"] == str(payload["event_id"])
                    )
                ):
                    continue
                existing = next(
                    event
                    for event in self.events
                    if event["id"] == attendance["teaching_event_id"]
                )
                if existing["event_date"] in set(payload.get("candidate_dates") or []):
                    rows.append(
                        {
                            "id": existing["id"],
                            "posting_code": existing["posting_code"],
                            "event_date": existing["event_date"],
                            "start_time": existing["start_time"],
                            "end_time": existing.get("end_time"),
                            "duration_hours": existing.get("duration_hours"),
                            "teaching_name_id": existing.get("teaching_name_id"),
                            "global_session_type_id": existing.get("global_session_type_id"),
                            "is_adhoc": existing.get("is_adhoc", False),
                            "source_reporting_period_id": existing.get(
                                "source_reporting_period_id"
                            ),
                            "source_programme_code": existing.get(
                                "source_programme_code"
                            ),
                        }
                    )
            return FakeResult(rows=rows)

        if "FROM attendance_records" in sql and "teaching_event_id = :event_id" in sql:
            rows = [
                row
                for row in self.attendance
                if row["resident_id"] == str(payload.get("resident_id"))
                and row["teaching_event_id"] == str(payload.get("event_id"))
                and (
                    "status = 'submitted'" not in sql
                    or row["status"] == "submitted"
                )
            ]
            return FakeResult(rows=rows[:1])

        if "native_attendance_removal_lock" in sql:
            self.native_attendance_removal_lock_calls.append(
                str(payload["attendance_id"])
            )
            rows = [
                {
                    **row,
                    "event_date": next(
                        event["event_date"]
                        for event in self.events
                        if event["id"] == row["teaching_event_id"]
                    ),
                }
                for row in self.attendance
                if row["id"] == str(payload.get("attendance_id"))
                and row["resident_id"] == str(payload.get("resident_id"))
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

        if "external_attendance_overlap_candidates" in sql:
            rows = []
            for attendance in self.external_attendance:
                if (
                    attendance["external_resident_id"]
                    != str(payload.get("external_resident_id"))
                    or attendance["status"] != "submitted"
                    or (
                        payload.get("event_id") is not None
                        and attendance["teaching_event_id"]
                        == str(payload.get("event_id"))
                    )
                ):
                    continue
                existing = next(
                    event
                    for event in self.events
                    if event["id"] == attendance["teaching_event_id"]
                )
                if existing["event_date"] in set(payload.get("candidate_dates") or []):
                    rows.append(
                        {
                            "event_date": existing["event_date"],
                            "start_time": existing["start_time"],
                            "end_time": existing.get("end_time"),
                        }
                    )
            return FakeResult(rows=rows)

        if "external_attendance_removal_lock" in sql:
            self.external_attendance_removal_lock_calls.append(
                str(payload["attendance_id"])
            )
            rows = [
                {
                    **row,
                    "event_date": next(
                        event["event_date"]
                        for event in self.events
                        if event["id"] == row["teaching_event_id"]
                    ),
                }
                for row in self.external_attendance
                if row["id"] == str(payload.get("attendance_id"))
                and row["external_resident_id"]
                == str(payload.get("external_resident_id"))
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
            for row in self.attendance:
                if (
                    row["id"] == str(payload["attendance_id"])
                    and row["resident_id"] == str(payload["resident_id"])
                    and row["status"] == "submitted"
                ):
                    row["status"] = "removed"
                    row["updated_at"] = self.now
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
                    row["updated_at"] = self.now
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
                "programme_code": payload.get("programme_code"),
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
            if (
                "SET posting_code = :posting_code" in sql
                and "programme_code = :programme_code" in sql
            ):
                rows = []
                for row in self.external_resident_postings:
                    if row["id"] == str(payload["posting_id"]):
                        row["posting_code"] = payload["posting_code"]
                        row["programme_code"] = payload["programme_code"]
                        rows.append(row)
                return FakeResult(rows=rows, rowcount=len(rows))

            if "WHERE id = :posting_id" in sql:
                updated = 0
                for row in self.external_resident_postings:
                    if row["id"] == str(payload["posting_id"]):
                        row["end_date"] = payload["end_date"]
                        row["is_current"] = False
                        updated += 1
                return FakeResult(rowcount=updated)

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
                row.pop("id", None)
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
                row.pop("id", None)
                row.pop("created_by_role", None)
                row.pop("created_for_programme_code", None)
            rows.sort(key=lambda row: (row["event_date"], row["start_time"], row["submitted_at"]), reverse=True)
            return FakeResult(rows=rows[payload.get("offset", 0) : payload.get("offset", 0) + payload.get("limit", len(rows))])

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")
