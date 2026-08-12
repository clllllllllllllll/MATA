from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

from app.services.pool_event_timing import (
    PoolEventTimingScope,
    resolve_pool_event_r_year_timing,
    resolve_pool_event_timing,
    sync_pool_event_timings,
)


class _Mappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows

    def one_or_none(self) -> dict | None:
        if not self._rows:
            return None
        if len(self._rows) != 1:
            raise AssertionError("Expected at most one row")
        return self._rows[0]


class _Result:
    def __init__(self, *, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class _TimingSession:
    def __init__(self, durations: list[Decimal | None], *, sync_rowcount: int = 0) -> None:
        self.durations = durations
        self.sync_rowcount = sync_rowcount
        self.sync_payloads: list[dict] = []

    async def execute(self, statement, params=None):  # noqa: ANN001
        sql = str(statement)
        payload = dict(params or {})
        if "/* pool_event_timing:resolve */" in sql:
            return _Result(rows=[self._timing_row(index, value) for index, value in enumerate(self.durations, 1)])
        if "/* pool_event_timing:resolve_r_year */" in sql:
            index = int(str(payload["r_year"]).removeprefix("R")) - 1
            if index < 0 or index >= len(self.durations):
                return _Result()
            return _Result(rows=[self._timing_row(index + 1, self.durations[index])])
        if "/* pool_event_timing:sync */" in sql:
            self.sync_payloads.append(payload)
            return _Result(rowcount=self.sync_rowcount)
        raise AssertionError(f"Unhandled SQL: {sql}")

    @staticmethod
    def _timing_row(index: int, duration: Decimal | None) -> dict:
        mapped = duration is not None
        return {
            "r_year": f"R{index}",
            "teaching_target_id": uuid4() if mapped else None,
            "session_type_id": uuid4() if mapped else None,
            "session_type_name": f"Session [{duration}h]" if mapped else None,
            "duration_hours": duration,
        }


def _scope() -> PoolEventTimingScope:
    return PoolEventTimingScope(
        teaching_name_id=uuid4(),
        reporting_period_id=uuid4(),
        programme_code="GERI",
        posting_code="TTSHGerMed",
    )


def test_pending_scope_uses_temporary_one_hour_duration() -> None:
    timing = asyncio.run(
        resolve_pool_event_timing(_TimingSession([]), scope=_scope())  # type: ignore[arg-type]
    )

    assert timing.duration_hours == Decimal("1.00")
    assert timing.is_mapped is False


def test_different_r_year_durations_use_longest_staff_envelope() -> None:
    timing = asyncio.run(
        resolve_pool_event_timing(  # type: ignore[arg-type]
            _TimingSession([Decimal("1.0"), Decimal("2.0")]),
            scope=_scope(),
        )
    )

    assert timing.duration_hours == Decimal("2.0")
    assert timing.is_mapped is True
    assert timing.duration_varies is True
    assert [row.r_year for row in timing.r_year_timings] == ["R1", "R2"]


def test_resident_timing_uses_exact_r_year_mapping() -> None:
    timing = asyncio.run(
        resolve_pool_event_r_year_timing(  # type: ignore[arg-type]
            _TimingSession([Decimal("1.0"), Decimal("2.0")]),
            scope=_scope(),
            r_year="R1",
        )
    )

    assert timing.r_year == "R1"
    assert timing.duration_hours == Decimal("1.0")
    assert timing.is_mapped is True


def test_sync_recalculates_exact_scope_with_mapped_duration() -> None:
    session = _TimingSession([Decimal("2.0")], sync_rowcount=3)
    scope = _scope()

    updated = asyncio.run(
        sync_pool_event_timings(  # type: ignore[arg-type]
            session,
            scopes=[scope, scope],
        )
    )

    assert updated == 3
    assert len(session.sync_payloads) == 1
    assert session.sync_payloads[0]["duration_hours"] == Decimal("2.0")
    assert session.sync_payloads[0]["duration_seconds"] == 7200
