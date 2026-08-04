from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import secretary
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware


class _FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


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

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult([next(iter(row.values())) for row in self._rows])

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


class FakeSecretarySession:
    def __init__(self) -> None:
        self.now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.secretary_id = str(uuid4())
        self.admin_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.other_resident_id = str(uuid4())
        self.session_type_id = str(uuid4())
        self.other_session_type_id = str(uuid4())
        self.reporting_period_id = str(uuid4())
        self.reporting_periods = [
            {
                "id": self.reporting_period_id,
                "label": "2026 operational period",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
            }
        ]
        self.series_id = str(uuid4())
        self.attended_event_id = str(uuid4())
        self.other_event_id = str(uuid4())
        self.pc_event_id = str(uuid4())
        self.unrelated_pc_event_id = str(uuid4())
        self.deleted_event_ids: list[str] = []
        self.cache_mutation_count = 0
        self.audit_logs: list[dict] = []
        self.commits = 0
        self.rollbacks = 0
        self.operations: list[str] = []
        self.fail_at: str | None = None
        self.locked_event_ids: list[str] = []
        self.locked_series_ids: list[str] = []
        self.event_lock_modes: list[tuple[str, str]] = []

        self.public_holidays = [
            {
                "holiday_date": date(2026, 5, 1),
                "name": "Labour Day",
            }
        ]
        self.catalogue = [
            {
                "keyword": "Journal Club",
                "posting_code": "TTSHCardio",
                "programme_code": "CARD",
                "session_type_id": self.session_type_id,
                "session_type": "Department Teaching [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "Wrong Site Teaching",
                "posting_code": "TTSHNeuro",
                "programme_code": "NEURO",
                "session_type_id": self.other_session_type_id,
                "session_type": "Other Teaching [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 22",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 2",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 10",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 11",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Shared Teaching",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Shared [2h]",
                "duration_hours": Decimal("2.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Shared Teaching",
                "posting_code": "TTSHContCC",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Shared Alt [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
        ]
        for row in self.catalogue:
            row["reporting_period_id"] = self.reporting_period_id
        self.teaching_names = [
            {
                "id": str(uuid4()),
                "display_name": row["keyword"],
                "programme_code": row["programme_code"],
                "reporting_period_id": self.reporting_period_id,
                "is_active": True,
            }
            for row in self.catalogue
        ]
        self.global_session_types = [
            {
                "id": str(uuid4()),
                "name": "Department Meeting [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "Inactive Global [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": False,
            },
        ]
        self.secretary_programme_pools = [
            {
                "posting_code": "TTSHCardio",
                "programme_code": "CARD",
                "is_active": True,
                "can_manage_teaching_names": True,
            },
            {
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "is_active": True,
                "can_manage_teaching_names": True,
            },
            {
                "posting_code": "TTSHGerMed",
                "programme_code": "CARD",
                "is_active": False,
                "can_manage_teaching_names": False,
            },
        ]
        self.residents = [
            {
                "id": self.resident_id,
                "name": "Resident One",
                "mcr": "M12345A",
                "programme_code": "CARD",
                "r_year": "R2",
                "posting_code": "TTSHCardio",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "active",
            },
            {
                "id": self.other_resident_id,
                "name": "Resident Two",
                "mcr": "M54321B",
                "programme_code": "NEURO",
                "r_year": "R1",
                "posting_code": "TTSHNeuro",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "active",
            },
        ]
        for row in self.residents:
            row["reporting_period_id"] = self.reporting_period_id
        self.events = [
            self._event(
                event_id=self.attended_event_id,
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 6),
                start_time=time(10, 0),
                end_time=time(11, 0),
                series_id=self.series_id,
            ),
            self._event(
                event_id=str(uuid4()),
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 13),
                start_time=time(10, 0),
                end_time=time(11, 0),
                series_id=self.series_id,
            ),
            self._event(
                event_id=str(uuid4()),
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 20),
                start_time=time(10, 0),
                end_time=time(11, 0),
                series_id=self.series_id,
            ),
            self._event(
                event_id=self.other_event_id,
                posting_code="TTSHNeuro",
                teaching_name="Wrong Site Teaching",
                event_date=date(2026, 5, 7),
                start_time=time(10, 0),
                end_time=time(11, 0),
                session_type_id=self.other_session_type_id,
            ),
            {
                "id": self.pc_event_id,
                "posting_code": "TTSHCardio",
                "created_for_programme_code": "CARD",
                "teaching_name": "Journal Club",
                "event_date": date(2026, 5, 15),
                "start_time": time(10, 0),
                "end_time": time(11, 0),
                "duration_hours": Decimal("1.0"),
                "session_type_id": self.session_type_id,
                "teaching_name_id": self.teaching_name_id_for("Journal Club", "CARD"),
                "global_session_type_id": None,
                "source_programme_code": "CARD",
                "source_reporting_period_id": self.reporting_period_id,
                "session_type": "Department Teaching [1h]",
                "series_id": None,
                "cme_points_awarded": False,
                "smc_event_code": None,
                "is_adhoc": False,
                "created_by_role": "programme_pc",
                "created_at": self.now,
                "updated_at": self.now,
            },
            {
                "id": str(uuid4()),
                "posting_code": "TTSHCardio",
                "teaching_name": "Journal Club",
                "event_date": date(2026, 5, 9),
                "start_time": time(9, 0),
                "end_time": time(10, 0),
                "duration_hours": Decimal("1.0"),
                "session_type_id": self.session_type_id,
                "teaching_name_id": None,
                "global_session_type_id": None,
                "session_type": "Department Teaching [1h]",
                "series_id": None,
                "cme_points_awarded": False,
                "smc_event_code": None,
                "is_adhoc": True,
                "created_by_role": "resident",
                "created_at": self.now,
                "updated_at": self.now,
            },
        ]
        self.series = [
            {
                "id": self.series_id,
                "posting_code": "TTSHCardio",
                "recurrence_pattern": "weekly",
                "recurrence_interval": 1,
                "days_of_week": ["wed"],
                "end_type": "by_count",
                "end_date": None,
                "end_after_count": 3,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.attendance_event_ids = {self.attended_event_id}
        self.attendance_statuses = {self.attended_event_id: "submitted"}
        self._committed_state = self._snapshot()

    def _event(
        self,
        *,
        event_id: str,
        posting_code: str,
        teaching_name: str,
        event_date: date,
        start_time: time,
        end_time: time,
        series_id: str | None = None,
        session_type_id: str | None = None,
        duration_hours: Decimal = Decimal("1.0"),
        teaching_name_id: str | None = None,
        global_session_type_id: str | None = None,
    ) -> dict:
        if teaching_name_id is None and global_session_type_id is None:
            teaching_name_id = self._teaching_name_id_for_posting(
                teaching_name,
                posting_code,
            )
        source_name = next(
            (
                row
                for row in self.teaching_names
                if row["id"] == str(teaching_name_id)
            ),
            None,
        )
        return {
            "id": event_id,
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": session_type_id or self.session_type_id,
            "teaching_name_id": teaching_name_id,
            "global_session_type_id": global_session_type_id,
            "source_programme_code": (
                source_name["programme_code"] if source_name is not None else None
            ),
            "source_reporting_period_id": (
                source_name["reporting_period_id"] if source_name is not None else None
            ),
            "session_type": "Department Teaching [1h]",
            "series_id": series_id,
            "cme_points_awarded": False,
            "smc_event_code": None,
            "is_adhoc": False,
            "created_for_programme_code": None,
            "created_by_role": "secretary",
            "created_at": self.now,
            "updated_at": self.now,
        }

    def allow_cardio_card_programme_pool(self) -> None:
        self.secretary_programme_pools.append(
            {
                "posting_code": "TTSHCardio",
                "programme_code": "CARD",
                "is_active": True,
                "can_manage_teaching_names": True,
            }
        )

    def teaching_name_id_for(self, display_name: str, programme_code: str) -> str:
        return next(
            row["id"]
            for row in self.teaching_names
            if row["display_name"] == display_name
            and row["programme_code"] == programme_code
        )

    def global_session_type_id_for(self, name: str) -> str:
        return next(row["id"] for row in self.global_session_types if row["name"] == name)

    def _teaching_name_id_for_posting(self, display_name: str, posting_code: str) -> str | None:
        catalogue_row = next(
            (
                row
                for row in self.catalogue
                if row["keyword"] == display_name and row["posting_code"] == posting_code
            ),
            None,
        )
        if catalogue_row is None:
            return None
        return self.teaching_name_id_for(
            display_name,
            catalogue_row["programme_code"],
        )

    def add_unrelated_pc_event_for_cardio(self) -> None:
        row = self._event(
            event_id=self.unrelated_pc_event_id,
            posting_code="TTSHCardio",
            teaching_name="Journal Club",
            event_date=date(2026, 5, 22),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        row["created_by_role"] = "programme_pc"
        row["created_for_programme_code"] = "GERI"
        self.events.append(row)
        self._committed_state = self._snapshot()

    def _snapshot(self) -> dict:
        return {
            "events": deepcopy(self.events),
            "series": deepcopy(self.series),
            "audit_logs": deepcopy(self.audit_logs),
            "deleted_event_ids": deepcopy(self.deleted_event_ids),
            "teaching_names": deepcopy(self.teaching_names),
        }

    def _restore(self, snapshot: dict) -> None:
        self.events = deepcopy(snapshot["events"])
        self.series = deepcopy(snapshot["series"])
        self.audit_logs = deepcopy(snapshot["audit_logs"])
        self.deleted_event_ids = deepcopy(snapshot["deleted_event_ids"])
        self.teaching_names = deepcopy(snapshot["teaching_names"])

    async def commit(self) -> None:
        self.operations.append("commit")
        self.commits += 1
        if self.fail_at == "commit":
            raise RuntimeError("forced commit failure")
        self._committed_state = self._snapshot()

    async def rollback(self) -> None:
        self.operations.append("rollback")
        self.rollbacks += 1
        self._restore(self._committed_state)

    async def scalars(self, statement, params=None) -> _FakeScalarResult:
        return (await self.execute(statement, params)).scalars()

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "/* teaching_event_mutation_lock */" in sql:
            lock_scope = str(payload["lock_scope"])
            if not lock_scope.startswith("teaching-event:"):
                raise AssertionError("Teaching-event mutation lock used an invalid scope")
            return _FakeResult()

        if "/* secretary_events:list_reporting_periods */" in sql:
            return _FakeResult(rows=list(self.reporting_periods))

        if "/* reporting_period_resolution:list */" in sql:
            return _FakeResult(rows=list(self.reporting_periods))

        if "/* reporting_period_resolution:explicit */" in sql:
            rows = [
                row
                for row in self.reporting_periods
                if row["id"] == str(payload["reporting_period_id"])
            ]
            return _FakeResult(rows=rows)

        if "/* scheduled_event_sources:teaching_name */" in sql:
            rows = [
                {
                    "id": row["id"],
                    "reporting_period_id": row["reporting_period_id"],
                    "programme_code": row["programme_code"],
                    "teaching_name": row["display_name"],
                    "is_active": row["is_active"],
                }
                for row in self.teaching_names
                if row["id"] == str(payload["teaching_name_id"])
            ]
            return _FakeResult(rows=rows)

        if "/* scheduled_event_sources:secretary_capability */" in sql:
            allowed = any(
                row["posting_code"] == payload["posting_code"]
                and row["programme_code"] == payload["programme_code"]
                and row["is_active"]
                and row.get("can_manage_teaching_names", False)
                for row in self.secretary_programme_pools
            )
            return _FakeResult(scalar=1 if allowed else None)

        if "/* scheduled_event_sources:global_session_type */" in sql:
            rows = [
                {
                    "id": row["id"],
                    "teaching_name": row["name"],
                    "duration_hours": row["duration_hours"],
                    "is_active": row["is_active"],
                }
                for row in self.global_session_types
                if row["id"] == str(payload["global_session_type_id"])
            ]
            return _FakeResult(rows=rows)

        if "/* secretary_events:options_teaching_names */" in sql:
            rows = [
                {
                    "teaching_name_id": name["id"],
                    "global_session_type_id": None,
                    "keyword": name["display_name"],
                    "teaching_name": name["display_name"],
                    "programme_code": name["programme_code"],
                    "duration_hours": Decimal("1.0"),
                    "is_global": False,
                }
                for name in self.teaching_names
                if name["reporting_period_id"] == str(payload["reporting_period_id"])
                and name["is_active"]
                and any(
                    pool["posting_code"] == payload["posting_code"]
                    and pool["programme_code"] == name["programme_code"]
                    and pool["is_active"]
                    and pool.get("can_manage_teaching_names", False)
                    for pool in self.secretary_programme_pools
                )
            ]
            return _FakeResult(rows=rows)

        if "/* secretary_events:options_global */" in sql:
            return _FakeResult(
                rows=[
                    {
                        "teaching_name_id": None,
                        "global_session_type_id": row["id"],
                        "keyword": row["name"],
                        "teaching_name": row["name"],
                        "programme_code": None,
                        "duration_hours": row["duration_hours"],
                        "is_global": True,
                    }
                    for row in self.global_session_types
                    if row["is_active"]
                ]
            )

        if "INSERT INTO audit_logs" in sql:
            self.operations.append("write_audit")
            if self.fail_at == "audit":
                raise RuntimeError("forced audit failure")
            row = dict(payload)
            row["created_at"] = self.now
            self.audit_logs.append(row)
            return _FakeResult(rows=[row])

        if "/* audit_snapshot:secretary_event */" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload["event_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            if event is not None and ("FOR UPDATE" in sql or "FOR SHARE" in sql):
                lock_mode = "update" if "FOR UPDATE" in sql else "share"
                self.locked_event_ids.append(event["id"])
                self.event_lock_modes.append((event["id"], lock_mode))
            return _FakeResult(rows=[dict(event)] if event else [])

        if "/* audit_snapshot:secretary_series */" in sql:
            series = next(
                (
                    row
                    for row in self.series
                    if row["id"] == str(payload["series_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            if series is not None and "FOR UPDATE" in sql:
                self.locked_series_ids.append(series["id"])
            return _FakeResult(rows=[dict(series)] if series else [])

        if "/* audit_snapshot:secretary_series_events */" in sql:
            rows = [
                dict(row)
                for row in self.events
                if row["series_id"] == str(payload["series_id"])
                and row["posting_code"] == payload["posting_code"]
            ]
            if "FOR UPDATE" in sql:
                self.locked_event_ids.extend(sorted(row["id"] for row in rows))
            rows.sort(key=lambda row: (row["event_date"], row["start_time"]))
            return _FakeResult(rows=rows)

        if "FROM public_holidays" in sql:
            holiday_date = payload["event_date"]
            holiday = next(
                (row for row in self.public_holidays if row["holiday_date"] == holiday_date),
                None,
            )
            return _FakeResult(rows=[holiday] if holiday else [], scalar=1 if holiday else None)

        if "FROM teaching_name_catalogue" in sql and "JOIN session_types" in sql:
            programme_codes = payload.get("programme_codes") or []
            use_programme_pool = bool(programme_codes)
            rows = [
                {
                    "keyword": row["keyword"],
                    "session_type_id": row["session_type_id"],
                    "session_type": row["session_type"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": row["is_tracked"],
                    "is_global": False,
                    "posting_code": row["posting_code"],
                }
                for row in self.catalogue
                if (
                    row["programme_code"] in set(programme_codes)
                    if use_programme_pool
                    else row["posting_code"] == payload["posting_code"]
                )
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
                and (
                    payload.get("teaching_name") in {None, ""}
                    or row["keyword"] == payload.get("teaching_name")
                )
            ]
            return _FakeResult(rows=rows)

        if "FROM secretary_programme_pools" in sql and "FROM teaching_events" not in sql:
            rows = [
                row
                for row in self.secretary_programme_pools
                if row["posting_code"] == payload["posting_code"] and row["is_active"]
                and (
                    "programme_code" not in payload
                    or row["programme_code"] == payload["programme_code"]
                )
            ]
            return _FakeResult(rows=rows)

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
                and (
                    "teaching_name" not in payload
                    or row["name"] == payload["teaching_name"]
                )
            ]
            return _FakeResult(rows=rows)

        if "DELETE FROM teaching_events" in sql:
            ids = {str(value) for value in payload.get("event_ids", [])}
            if not ids and "event_id" in payload:
                ids = {str(payload["event_id"])}
            self.deleted_event_ids.extend(sorted(ids))
            self.events = [row for row in self.events if row["id"] not in ids]
            return _FakeResult(rowcount=len(ids))

        if "DELETE FROM event_series" in sql:
            self.series = [row for row in self.series if row["id"] != str(payload["series_id"])]
            return _FakeResult(rowcount=1)

        if "FROM teaching_events" in sql and "COUNT(*)" in sql and "GROUP BY" in sql:
            scoped_rows = [row for row in self.events if row["posting_code"] == payload["posting_code"]]
            if "created_by_role = 'secretary'" in sql:
                scoped_rows = [row for row in scoped_rows if row["created_by_role"] == "secretary"]
            if "is_adhoc = false" in sql:
                scoped_rows = [row for row in scoped_rows if not row["is_adhoc"]]
            rows = [
                {
                    "total_events": len(scoped_rows),
                    "cme_events": len(
                        [
                            row
                            for row in scoped_rows
                            if row["cme_points_awarded"]
                        ]
                    ),
                    "with_smc_code": len(
                        [
                            row
                            for row in scoped_rows
                            if row["smc_event_code"]
                        ]
                    ),
                }
            ]
            return _FakeResult(rows=rows)

        if "FROM teaching_events" in sql and "WHERE id = :source_event_id" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload["source_event_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            if "FOR UPDATE" in sql and event is not None:
                self.locked_event_ids.append(event["id"])
                self.event_lock_modes.append((event["id"], "update"))
            return _FakeResult(rows=[event] if event else [])

        if "FROM teaching_events" in sql and "WHERE id = :event_id" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload["event_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            if "FOR UPDATE" in sql and event is not None:
                self.locked_event_ids.append(event["id"])
                self.event_lock_modes.append((event["id"], "update"))
            return _FakeResult(rows=[event] if event else [])

        if "FROM teaching_events" in sql and "WHERE series_id = :series_id" in sql:
            rows = [
                row
                for row in self.events
                if row["series_id"] == str(payload["series_id"])
                and row["posting_code"] == payload["posting_code"]
            ]
            if "FOR UPDATE" not in sql and "ORDER BY" not in sql:
                return _FakeResult(rows=[{"id": row["id"]} for row in rows])
            if "ORDER BY id ASC" in sql:
                rows.sort(key=lambda row: row["id"])
            if "FOR UPDATE" in sql:
                self.locked_event_ids.extend(sorted(row["id"] for row in rows))
            if payload.get("scope") == "single":
                rows = [row for row in rows if row["id"] == str(payload["event_id"])]
            if payload.get("scope") == "following":
                anchor = next(
                    (row for row in rows if row["id"] == str(payload["event_id"])),
                    None,
                )
                if anchor is None:
                    rows = []
                else:
                    rows = [row for row in rows if row["event_date"] >= anchor["event_date"]]
            return _FakeResult(rows=rows)

        if "FROM teaching_events" in sql:
            rows = [row for row in self.events if row["posting_code"] == payload["posting_code"]]
            if "created_by_role = 'secretary'" in sql:
                rows = [row for row in rows if row["created_by_role"] == "secretary"]
            if "created_by_role IN ('secretary', 'programme_pc')" in sql:
                rows = [
                    row
                    for row in rows
                    if row["created_by_role"] in {"secretary", "programme_pc"}
                ]
            if "created_for_programme_code IS NULL" in sql and "secretary_programme_pools" in sql:
                active_programmes = {
                    row["programme_code"]
                    for row in self.secretary_programme_pools
                    if row["posting_code"] == payload["posting_code"] and row["is_active"]
                }
                rows = [
                    row
                    for row in rows
                    if row.get("created_for_programme_code") is None
                    or row.get("created_for_programme_code") in active_programmes
                ]
            if "is_adhoc = false" in sql:
                rows = [row for row in rows if not row["is_adhoc"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            if "session_type_id" in payload:
                rows = [row for row in rows if row["session_type_id"] == str(payload["session_type_id"])]
            rows.sort(key=lambda row: (row["event_date"], row["start_time"]))
            return _FakeResult(rows=rows)

        if "FROM resident_postings" in sql:
            today = payload["today"]
            rows = [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "mcr": row["mcr"],
                    "programme_code": row["programme_code"],
                    "r_year": row["r_year"],
                    "posting_code": row["posting_code"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "status": row["status"],
                }
                for row in self.residents
                if row["posting_code"] == payload["posting_code"]
                and row["reporting_period_id"] == str(payload["reporting_period_id"])
                and row["start_date"] <= today <= row["end_date"]
            ]
            return _FakeResult(rows=rows)

        if "SELECT 1" in sql and "FROM attendance_records" in sql:
            ids = set(payload.get("event_ids", []))
            if not ids and "event_id" in payload:
                ids = {str(payload["event_id"])}
            linked_ids = ids & self.attendance_event_ids
            if "status = 'submitted'" in sql:
                has_attendance = any(
                    self.attendance_statuses.get(event_id, "submitted") == "submitted"
                    for event_id in linked_ids
                )
            else:
                has_attendance = bool(linked_ids)
            return _FakeResult(scalar=1 if has_attendance else None)

        if "INSERT INTO event_series" in sql:
            row = {
                "id": str(uuid4()),
                "posting_code": payload["posting_code"],
                "recurrence_pattern": payload["recurrence_pattern"],
                "recurrence_interval": payload["recurrence_interval"],
                "days_of_week": payload.get("days_of_week"),
                "end_type": payload["end_type"],
                "end_date": payload.get("end_date"),
                "end_after_count": payload.get("end_after_count"),
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.series.append(row)
            return _FakeResult(rows=[row])

        if "INSERT INTO teaching_events" in sql:
            row = self._event(
                event_id=str(uuid4()),
                posting_code=payload["posting_code"],
                teaching_name=payload["teaching_name"],
                event_date=payload["event_date"],
                start_time=payload["start_time"],
                end_time=payload["end_time"],
                duration_hours=payload["duration_hours"],
                session_type_id=str(payload["session_type_id"])
                if payload.get("session_type_id")
                else None,
                teaching_name_id=payload.get("teaching_name_id"),
                global_session_type_id=payload.get("global_session_type_id"),
                series_id=str(payload["series_id"]) if payload.get("series_id") else None,
            )
            row["source_programme_code"] = payload.get("source_programme_code")
            row["source_reporting_period_id"] = payload.get(
                "source_reporting_period_id"
            )
            row["cme_points_awarded"] = payload["cme_points_awarded"]
            row["smc_event_code"] = payload.get("smc_event_code")
            self.events.append(row)
            return _FakeResult(rows=[row])

        if "UPDATE teaching_events" in sql:
            row = next(
                (
                    event
                    for event in self.events
                    if event["id"] == str(payload["event_id"])
                    and event["posting_code"] == payload["posting_code"]
                    and event["created_by_role"] == "secretary"
                    and not event["is_adhoc"]
                ),
                None,
            )
            if row is None:
                return _FakeResult(rows=[])
            row.update(
                {
                    "teaching_name": payload["teaching_name"],
                    "event_date": payload["event_date"],
                    "start_time": payload["start_time"],
                    "end_time": payload["end_time"],
                    "duration_hours": payload["duration_hours"],
                    "session_type_id": str(payload["session_type_id"])
                    if payload.get("session_type_id")
                    else None,
                    "teaching_name_id": payload.get("teaching_name_id"),
                    "global_session_type_id": payload.get("global_session_type_id"),
                    "cme_points_awarded": payload["cme_points_awarded"],
                    "smc_event_code": payload.get("smc_event_code"),
                    "updated_at": self.now,
                }
            )
            return _FakeResult(rows=[row])

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")


def _client(
    fake_db: FakeSecretarySession,
    *,
    identity: AuthIdentity | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app, default_identity=identity)

    async def _db_override():
        yield fake_db

    app.dependency_overrides[secretary.get_db_session] = _db_override
    app.include_router(secretary.router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _headers(fake_db: FakeSecretarySession, *, role: str = "secretary", site: str = "TTSHCardio"):
    return {
        "X-User-Role": role,
        "X-User-Id": fake_db.secretary_id if role == "secretary" else fake_db.admin_id,
        "X-User-Site": site,
    }


def _pool_source(
    fake_db: FakeSecretarySession,
    display_name: str = "Journal Club",
    programme_code: str = "CARD",
) -> dict[str, str]:
    return {
        "teaching_name_id": fake_db.teaching_name_id_for(
            display_name,
            programme_code,
        )
    }


def _audit_json(row: dict, field: str) -> dict | None:
    value = row[field]
    if value is None:
        return None
    return json.loads(value)


def test_non_secretary_access_rejected() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db, role="admin"))

    assert response.status_code == 403


def test_secretary_context_uses_verified_identity_posting_without_raw_headers() -> None:
    fake_db = FakeSecretarySession()
    client = _client(
        fake_db,
        identity=AuthIdentity(
            role="secretary",
            subject_id=fake_db.secretary_id,
            posting_code="TTSHGerMed",
        ),
    )

    response = client.get("/secretary/teaching-name-options")

    assert response.status_code == 200
    keywords = [row["keyword"] for row in response.json()["options"]]
    assert "GERI Demo Row 22" in keywords
    assert "Journal Club" not in keywords


def test_secretary_mutation_endpoint_allows_missing_actor_name_and_writes_audit() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    headers = _headers(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={**_pool_source(fake_db), "event_date": "2026-05-18", "start_time": "10:00"},
    )

    assert response.status_code == 200
    assert fake_db.audit_logs[-1]["actor_name"] == "Unknown actor"
    assert fake_db.audit_logs[-1]["action"] == "secretary.teaching_event.create"


def test_secretary_mutation_endpoint_allows_blank_actor_name() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    headers = _headers(fake_db)
    headers["-".join(["X", "Actor", "Name"])] = "   "

    response = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={**_pool_source(fake_db), "event_date": "2026-05-18", "start_time": "10:00"},
    )

    assert response.status_code == 200
    assert fake_db.audit_logs[-1]["actor_name"] == "Unknown actor"


def test_secretary_read_endpoints_do_not_require_actor_name() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    headers = _headers(fake_db)
    paths = [
        "/secretary/reporting-periods",
        "/secretary/teaching-events",
        "/secretary/cme-dashboard",
        "/secretary/residents",
        "/secretary/teaching-name-options",
    ]

    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, path


def test_secretary_reporting_periods_are_available_without_admin_scope() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/reporting-periods", headers=_headers(fake_db))
    denied = client.get(
        "/secretary/reporting-periods",
        headers=_headers(fake_db, role="admin"),
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == fake_db.reporting_period_id
    assert response.json()[0]["status"] == "active"
    assert denied.status_code == 403


def test_secretary_teaching_event_mutations_write_audit_logs() -> None:
    fake_db = FakeSecretarySession()
    fake_db.attendance_event_ids = set()
    client = _client(fake_db)
    headers = _headers(fake_db)
    source_event_id = fake_db.events[0]["id"]

    created = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-18",
            "start_time": "10:00",
            "cme_points_awarded": True,
            "smc_event_code": "SMC-1",
        },
    )
    assert created.status_code == 200

    duplicated = client.post(
        "/secretary/teaching-events/duplicate",
        headers=headers,
        json={
            "source_event_id": source_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
        },
    )
    assert duplicated.status_code == 200
    duplicated_id = duplicated.json()["id"]

    updated = client.put(
        f"/secretary/teaching-events/{duplicated_id}",
        headers=headers,
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-26",
            "start_time": "11:00",
            "cme_points_awarded": False,
            "smc_event_code": "SMC-2",
        },
    )
    assert updated.status_code == 200

    deleted = client.delete(
        f"/secretary/teaching-events/{duplicated_id}",
        headers=headers,
    )
    assert deleted.status_code == 200

    series_created = client.post(
        "/secretary/teaching-events/series",
        headers=headers,
        json={
            **_pool_source(fake_db),
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 2,
        },
    )
    assert series_created.status_code == 200

    series_payload = series_created.json()
    series_id = series_payload["series"]["id"]
    series_event_id = series_payload["events"][0]["id"]
    series_deleted = client.delete(
        f"/secretary/teaching-events/series/{series_id}",
        headers=headers,
        params={"scope": "single", "event_id": series_event_id},
    )
    assert series_deleted.status_code == 200

    assert [row["action"] for row in fake_db.audit_logs] == [
        "secretary.teaching_event.create",
        "secretary.teaching_event.duplicate",
        "secretary.teaching_event.update",
        "secretary.teaching_event.delete",
        "secretary.teaching_event_series.create",
        "secretary.teaching_event_series.delete_single",
    ]
    assert {row["actor_name"] for row in fake_db.audit_logs} == {"Unknown actor"}
    assert fake_db.audit_logs[0]["entity_type"] == "teaching_event"
    assert _audit_json(fake_db.audit_logs[0], "before_json") is None
    assert _audit_json(fake_db.audit_logs[0], "after_json")["teaching_name"] == "Journal Club"
    assert _audit_json(fake_db.audit_logs[1], "before_json")["id"] == source_event_id
    assert _audit_json(fake_db.audit_logs[1], "after_json")["id"] == duplicated_id
    assert _audit_json(fake_db.audit_logs[2], "before_json")["event_date"] == "2026-05-25"
    assert _audit_json(fake_db.audit_logs[2], "after_json")["event_date"] == "2026-05-26"
    assert _audit_json(fake_db.audit_logs[3], "before_json")["id"] == duplicated_id
    assert _audit_json(fake_db.audit_logs[3], "after_json") is None
    series_after = _audit_json(fake_db.audit_logs[4], "after_json")
    series_metadata = _audit_json(fake_db.audit_logs[4], "metadata_json")
    assert fake_db.audit_logs[4]["entity_type"] == "teaching_event_series"
    assert series_after["created_count"] == 1
    assert series_metadata["created_event_ids"] == [series_event_id]
    delete_before = _audit_json(fake_db.audit_logs[5], "before_json")
    delete_metadata = _audit_json(fake_db.audit_logs[5], "metadata_json")
    assert delete_before["scope"] == "single"
    assert delete_metadata["deleted_event_ids"] == [series_event_id]
    assert delete_metadata["deleted_count"] == 1
    assert delete_metadata["posting_code"] == "TTSHCardio"
    assert fake_db.commits == 6
    assert fake_db.rollbacks == 0
    assert fake_db.operations == ["write_audit", "commit"] * 6
    assert (source_event_id, "share") in fake_db.event_lock_modes


@pytest.mark.parametrize(
    "mutation",
    ["create", "duplicate", "update", "delete", "series_create", "series_delete"],
)
def test_secretary_audit_failure_rolls_back_business_mutation_and_skips_cache(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeSecretarySession()
    fake_db.attendance_event_ids = set()
    initial = fake_db._snapshot()
    fake_db.fail_at = "audit"
    cache_calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "app.services.secretary_events.invalidate_secretary_event_caches",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)),
    )
    client = _client(fake_db, raise_server_exceptions=False)
    headers = _headers(fake_db)

    if mutation == "create":
        response = client.post(
            "/secretary/teaching-events",
            headers=headers,
            json={
                **_pool_source(fake_db),
                "event_date": "2026-05-18",
                "start_time": "10:00",
            },
        )
    elif mutation == "duplicate":
        response = client.post(
            "/secretary/teaching-events/duplicate",
            headers=headers,
            json={
                "source_event_id": fake_db.events[0]["id"],
                "event_date": "2026-05-25",
                "start_time": "10:00",
            },
        )
    elif mutation == "update":
        response = client.put(
            f"/secretary/teaching-events/{fake_db.events[1]['id']}",
            headers=headers,
            json={
                **_pool_source(fake_db),
                "event_date": "2026-05-26",
                "start_time": "11:00",
            },
        )
    elif mutation == "delete":
        response = client.delete(
            f"/secretary/teaching-events/{fake_db.events[1]['id']}",
            headers=headers,
        )
    elif mutation == "series_create":
        response = client.post(
            "/secretary/teaching-events/series",
            headers=headers,
            json={
                **_pool_source(fake_db),
                "start_date": "2026-04-24",
                "start_time": "10:00",
                "recurrence_pattern": "weekly",
                "recurrence_interval": 1,
                "days_of_week": ["fri"],
                "end_type": "by_count",
                "end_after_count": 2,
            },
        )
    else:
        response = client.delete(
            f"/secretary/teaching-events/series/{fake_db.series_id}",
            headers=headers,
            params={"scope": "single", "event_id": fake_db.events[1]["id"]},
        )

    assert response.status_code == 500
    assert fake_db.commits == 0
    assert fake_db.rollbacks == 1
    assert fake_db._snapshot() == initial
    assert fake_db.audit_logs == []
    assert fake_db.operations == ["write_audit", "rollback"]
    assert cache_calls == []


def test_secretary_commit_failure_rolls_back_event_and_audit_and_skips_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeSecretarySession()
    initial = fake_db._snapshot()
    fake_db.fail_at = "commit"
    cache_calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "app.services.secretary_events.invalidate_secretary_event_caches",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)),
    )

    response = _client(fake_db, raise_server_exceptions=False).post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 500
    assert fake_db.commits == 1
    assert fake_db.rollbacks == 1
    assert fake_db._snapshot() == initial
    assert fake_db.audit_logs == []
    assert fake_db.operations == ["write_audit", "commit", "rollback"]
    assert cache_calls == []


def test_secretary_cache_failure_does_not_misreport_committed_mutation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_db = FakeSecretarySession()
    initial_event_count = len(fake_db.events)

    def _fail_cache(_posting_code: str) -> None:
        raise RuntimeError("forced cache failure")

    monkeypatch.setattr(
        "app.services.secretary_events.invalidate_secretary_event_caches",
        _fail_cache,
    )

    response = _client(fake_db).post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert fake_db.commits == 1
    assert fake_db.rollbacks == 0
    assert len(fake_db.events) == initial_event_count + 1
    assert len(fake_db.audit_logs) == 1
    assert fake_db.operations == ["write_audit", "commit"]
    assert "secretary_event_cache_invalidation_failed" in caplog.text
    assert "forced cache failure" not in caplog.text


@pytest.mark.parametrize(
    ("scope", "expected_action"),
    [
        ("single", "secretary.teaching_event_series.delete_single"),
        ("following", "secretary.teaching_event_series.delete_following"),
        ("all", "secretary.teaching_event_series.delete_all"),
    ],
)
def test_secretary_series_delete_audit_action_matches_scope(
    scope: str,
    expected_action: str,
) -> None:
    fake_db = FakeSecretarySession()
    fake_db.attendance_event_ids = set()
    client = _client(fake_db)
    params = {"scope": scope}
    if scope in {"single", "following"}:
        params["event_id"] = fake_db.events[1]["id"]

    response = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params=params,
    )

    assert response.status_code == 200
    assert fake_db.audit_logs[-1]["action"] == expected_action


def test_create_event_derives_posting_scope_and_computes_end_time() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-18",
            "start_time": "10:00",
            "cme_points_awarded": True,
            "smc_event_code": "SMC-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["end_time"] == "11:00:00"
    assert payload["session_type_id"] == fake_db.session_type_id
    assert fake_db.events[-1]["posting_code"] == "TTSHCardio"


def test_create_event_rejects_client_posting_code_and_end_time() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    base_payload = {
        **_pool_source(fake_db),
        "event_date": "2026-05-18",
        "start_time": "10:00",
    }

    posting_response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={**base_payload, "posting_code": "TTSHNeuro"},
    )
    end_time_response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={**base_payload, "end_time": "12:00"},
    )

    assert posting_response.status_code == 422
    assert end_time_response.status_code == 422


def test_multi_capability_secretary_cannot_switch_event_source_programme() -> None:
    fake_db = FakeSecretarySession()
    fake_db.secretary_programme_pools.append(
        {
            "posting_code": "TTSHCardio",
            "programme_code": "GERI",
            "is_active": True,
            "can_manage_teaching_names": True,
        }
    )
    source_event = fake_db.events[1]
    before = deepcopy(source_event)
    client = _client(fake_db)

    response = client.put(
        f"/secretary/teaching-events/{source_event['id']}",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db, "GERI Demo Row 22", "GERI"),
            "event_date": "2026-05-26",
            "start_time": "11:00",
        },
    )

    assert response.status_code == 409
    assert source_event == before


def test_create_event_on_public_holiday_returns_422() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-01",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 422


def test_list_endpoint_only_returns_secretary_posting_events() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert {row["posting_code"] for row in payload["events"]} == {"TTSHCardio"}
    assert fake_db.other_event_id not in {row["id"] for row in payload["events"]}
    assert {row["created_by_role"] for row in payload["events"]} == {
        "secretary",
        "programme_pc",
    }
    assert all(not row["is_adhoc"] for row in payload["events"])
    assert payload["events"][0]["session_type"] == "Department Teaching [1h]"


def test_secretary_schedule_includes_programme_pc_events_for_same_posting() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.pc_event_id in ids
    pc_event = next(row for row in response.json()["events"] if row["id"] == fake_db.pc_event_id)
    assert pc_event["created_by_role"] == "programme_pc"


def test_secretary_schedule_excludes_pc_events_outside_active_programme_pool() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    fake_db.add_unrelated_pc_event_for_cardio()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.pc_event_id in ids
    assert fake_db.unrelated_pc_event_id not in ids


def test_secretary_cannot_mutate_pc_event_outside_active_programme_pool() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    fake_db.add_unrelated_pc_event_for_cardio()
    client = _client(fake_db)

    update_response = client.put(
        f"/secretary/teaching-events/{fake_db.unrelated_pc_event_id}",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-26",
            "start_time": "10:00",
        },
    )
    delete_response = client.delete(
        f"/secretary/teaching-events/{fake_db.unrelated_pc_event_id}",
        headers=_headers(fake_db),
    )

    assert update_response.status_code == 404
    assert delete_response.status_code == 404


def test_secretary_cannot_access_another_posting_event() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.delete(
        f"/secretary/teaching-events/{fake_db.other_event_id}",
        headers=_headers(fake_db),
    )

    assert response.status_code == 404


def test_teaching_name_options_use_programme_pool_and_include_active_globals() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db, site="TTSHGerMed"),
    )

    assert response.status_code == 200
    options = response.json()["options"]
    keywords = [row["keyword"] for row in options]

    assert "GERI Demo Row 22" in keywords
    assert keywords.count("GERI Shared Teaching") == 2
    assert "Department Meeting [1h]" in keywords
    assert "Wrong Site Teaching" not in keywords
    assert "Journal Club" not in keywords
    assert "Inactive Global [1h]" not in keywords

    shared = [row for row in options if row["keyword"] == "GERI Shared Teaching"]
    assert {row["teaching_name_id"] for row in shared} == {
        fake_db.teaching_name_id_for("GERI Shared Teaching", "GERI"),
        fake_db.teaching_names[-1]["id"],
    }
    assert all(row["global_session_type_id"] is None for row in shared)

    row2_index = keywords.index("GERI Demo Row 2")
    row10_index = keywords.index("GERI Demo Row 10")
    row11_index = keywords.index("GERI Demo Row 11")
    assert row2_index < row10_index < row11_index


def test_teaching_name_options_do_not_leak_from_future_period() -> None:
    fake_db = FakeSecretarySession()
    future_period_id = str(uuid4())
    fake_db.reporting_periods.append(
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
    fake_db.teaching_names.append(
        {
            "id": str(uuid4()),
            "display_name": "Future Test Teaching",
            "programme_code": "CARD",
            "reporting_period_id": future_period_id,
            "is_active": True,
        }
    )
    client = _client(fake_db)

    current = client.get("/secretary/teaching-name-options", headers=_headers(fake_db))
    explicit_future = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db),
        params={"reporting_period_id": future_period_id},
    )
    mismatched_date = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db),
        params={
            "reporting_period_id": future_period_id,
            "event_date": "2026-05-06",
        },
    )

    assert current.status_code == 200
    assert "Future Test Teaching" not in {row["keyword"] for row in current.json()["options"]}
    assert explicit_future.status_code == 200
    assert "Future Test Teaching" in {row["keyword"] for row in explicit_future.json()["options"]}
    assert mismatched_date.status_code == 422


def test_create_event_accepts_keyword_from_mapped_programme_pool() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db, site="TTSHGerMed"),
        json={
            **_pool_source(fake_db, "GERI Demo Row 22", "GERI"),
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHGerMed"
    assert payload["teaching_name"] == "GERI Demo Row 22"
    assert payload["created_for_programme_code"] is None


def test_other_secretary_posting_cannot_use_ttshgermed_pool_identity() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db, site="TTSHCardio"),
        json={
            **_pool_source(fake_db, "GERI Demo Row 22", "GERI"),
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 403
    assert all(
        row["teaching_name"] != "GERI Demo Row 22" or row["posting_code"] != "TTSHCardio"
        for row in fake_db.events
    )


def test_teaching_name_options_fall_back_to_exact_posting_when_unmapped() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db, site="TTSHCardio"),
    )

    assert response.status_code == 200
    keywords = [row["keyword"] for row in response.json()["options"]]
    assert "Journal Club" in keywords
    assert "GERI Demo Row 22" not in keywords


def test_teaching_name_options_ignore_inactive_programme_pool_mapping() -> None:
    fake_db = FakeSecretarySession()
    fake_db.secretary_programme_pools.append(
        {
            "posting_code": "TTSHCardio",
            "programme_code": "GERI",
            "is_active": False,
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db, site="TTSHCardio"),
    )

    assert response.status_code == 200
    keywords = [row["keyword"] for row in response.json()["options"]]
    assert "Journal Club" in keywords
    assert "GERI Demo Row 22" not in keywords


def test_residents_endpoint_lists_only_current_own_posting_residents() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/residents", headers=_headers(fake_db))

    assert response.status_code == 200
    residents = response.json()["residents"]
    assert [row["mcr"] for row in residents] == ["M12345A"]


def test_residents_endpoint_isolated_to_current_period_and_fails_closed() -> None:
    fake_db = FakeSecretarySession()
    future_period_id = str(uuid4())
    fake_db.reporting_periods.extend(
        [
            {
                "id": str(uuid4()),
                "label": "Reopened past period",
                "start_date": date(2025, 1, 1),
                "end_date": date(2025, 12, 31),
                "status": "active",
                "activate_on": None,
                "deactivate_on": date(2026, 12, 31),
            },
            {
                "id": future_period_id,
                "label": "Future Test Period",
                "start_date": date(2099, 1, 1),
                "end_date": date(2099, 6, 30),
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
            },
        ]
    )
    fake_db.residents.append(
        {
            **fake_db.residents[0],
            "reporting_period_id": future_period_id,
        }
    )
    client = _client(fake_db)

    current = client.get("/secretary/residents", headers=_headers(fake_db))
    assert current.status_code == 200
    assert [row["mcr"] for row in current.json()["residents"]] == ["M12345A"]

    fake_db.reporting_periods[0]["status"] = "inactive"
    unavailable = client.get("/secretary/residents", headers=_headers(fake_db))
    assert unavailable.status_code == 200
    assert unavailable.json()["residents"] == []

    fake_db.reporting_periods[0]["status"] = "active"
    fake_db.reporting_periods.append(
        {
            "id": str(uuid4()),
            "label": "Overlapping current period",
            "start_date": date(2026, 7, 1),
            "end_date": date(2026, 12, 31),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    overlap = client.get("/secretary/residents", headers=_headers(fake_db))
    assert overlap.status_code == 409


def test_duplicate_event_respects_scope_and_rejects_client_posting_code() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.attended_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
            **_pool_source(fake_db),
        },
    )
    forbidden_body = client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.attended_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
            "posting_code": "TTSHNeuro",
        },
    )
    wrong_scope = client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.other_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_code"] == "TTSHCardio"
    assert forbidden_body.status_code == 422
    assert wrong_scope.status_code == 404


def test_delete_event_without_attendance_succeeds_and_with_attendance_conflicts() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    deleteable_id = fake_db.events[1]["id"]

    ok_response = client.delete(
        f"/secretary/teaching-events/{deleteable_id}",
        headers=_headers(fake_db),
    )
    conflict_response = client.delete(
        f"/secretary/teaching-events/{fake_db.attended_event_id}",
        headers=_headers(fake_db),
    )

    assert ok_response.status_code == 200
    assert ok_response.json()["deleted_count"] == 1
    assert conflict_response.status_code == 409


@pytest.mark.parametrize(
    ("status", "method"),
    [("removed", "put"), ("flagged", "delete")],
)
def test_secretary_event_mutation_locks_and_rejects_any_attendance_status(
    status: str,
    method: str,
) -> None:
    fake_db = FakeSecretarySession()
    event_id = fake_db.events[1]["id"]
    fake_db.attendance_event_ids = {event_id}
    fake_db.attendance_statuses = {event_id: status}
    initial = fake_db._snapshot()
    client = _client(fake_db)

    if method == "put":
        response = client.put(
            f"/secretary/teaching-events/{event_id}",
            headers=_headers(fake_db),
            json={
                **_pool_source(fake_db),
                "event_date": "2026-05-26",
                "start_time": "11:00",
            },
        )
    else:
        response = client.delete(
            f"/secretary/teaching-events/{event_id}",
            headers=_headers(fake_db),
        )

    assert response.status_code == 409
    assert fake_db._snapshot() == initial
    assert fake_db.locked_event_ids == [event_id, event_id]
    assert fake_db.event_lock_modes == [
        (event_id, "update"),
        (event_id, "update"),
    ]
    assert fake_db.commits == 0
    assert fake_db.rollbacks == 1


def test_recurring_series_create_scopes_events_and_skips_public_holidays() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events/series",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 3,
        },
    )
    forbidden_body = client.post(
        "/secretary/teaching-events/series",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "posting_code": "TTSHNeuro",
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert payload["warnings"] == [
        "Skipped public holiday occurrence on 2026-05-01 (Labour Day)"
    ]
    assert {row["posting_code"] for row in payload["events"]} == {"TTSHCardio"}
    assert forbidden_body.status_code == 422


def test_series_deletion_scopes_single_following_all_and_blocks_attendance() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    second_event_id = fake_db.events[1]["id"]
    third_event_id = fake_db.events[2]["id"]

    single = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "single", "event_id": third_event_id},
    )
    following = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "following", "event_id": second_event_id},
    )
    blocked = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "all"},
    )

    assert single.status_code == 200
    assert single.json()["deleted_count"] == 1
    assert following.status_code == 200
    assert following.json()["deleted_count"] == 1
    assert blocked.status_code == 409


def test_series_delete_locks_deterministically_and_rejects_flagged_attendance() -> None:
    fake_db = FakeSecretarySession()
    event_id = fake_db.events[1]["id"]
    fake_db.attendance_event_ids = {event_id}
    fake_db.attendance_statuses = {event_id: "flagged"}
    initial = fake_db._snapshot()

    response = _client(fake_db).delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "single", "event_id": event_id},
    )

    series_event_ids = sorted(
        row["id"] for row in fake_db.events if row["series_id"] == fake_db.series_id
    )
    assert response.status_code == 409
    assert fake_db._snapshot() == initial
    assert fake_db.locked_event_ids == series_event_ids * 2
    assert fake_db.locked_series_ids == [fake_db.series_id]
    assert fake_db.commits == 0
    assert fake_db.rollbacks == 1


def test_cme_dashboard_is_scoped_to_secretary_posting() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/cme-dashboard", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["total_events"] == 3


def test_cache_invalidation_called_after_event_mutations(monkeypatch) -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    calls: list[tuple[set[str], dict]] = []
    deleteable_event_id = fake_db.events[1]["id"]
    series_delete_event_id = fake_db.events[2]["id"]

    def _spy(domains, **scope):  # noqa: ANN001
        assert fake_db.commits == len(calls) + 1
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)

    client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )
    client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.events[0]["id"],
            "event_date": "2026-05-25",
            "start_time": "10:00",
        },
    )
    client.delete(
        f"/secretary/teaching-events/{deleteable_event_id}",
        headers=_headers(fake_db),
    )
    client.post(
        "/secretary/teaching-events/series",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 2,
        },
    )
    client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "single", "event_id": series_delete_event_id},
    )

    assert len(calls) >= 5
    assert all({"secretary_events", "resident_events"} <= domains for domains, _scope in calls)
    assert all(scope["posting_code"] == "TTSHCardio" for _domains, scope in calls)


def test_secretary_event_mutation_invalidates_scoped_event_domains(monkeypatch) -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            **_pool_source(fake_db),
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert calls
    domains, scope = calls[-1]
    assert {"secretary_events", "resident_events", "admin_reports", "resident_dashboard"} <= domains
    assert scope["posting_code"] == "TTSHCardio"
