from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.services.pool_event_timing import (
    PoolEventTimingScope,
    resolve_pool_event_timing,
    sync_pool_event_timings,
)


class _Mappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _Result:
    def __init__(self, *, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class _TimingSession:
    def __init__(self, durations: list[Decimal], *, sync_rowcount: int = 0) -> None:
        self.durations = durations
        self.sync_rowcount = sync_rowcount
        self.sync_payloads: list[dict] = []

    async def execute(self, statement, params=None):  # noqa: ANN001
        sql = str(statement)
        payload = dict(params or {})
        if "/* pool_event_timing:resolve */" in sql:
            return _Result(rows=[{"duration_hours": value} for value in self.durations])
        if "/* pool_event_timing:sync */" in sql:
            self.sync_payloads.append(payload)
            return _Result(rowcount=self.sync_rowcount)
        raise AssertionError(f"Unhandled SQL: {sql}")


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


def test_conflicting_r_year_mapping_durations_fail_closed() -> None:
    with pytest.raises(ApiError) as caught:
        asyncio.run(
            resolve_pool_event_timing(  # type: ignore[arg-type]
                _TimingSession([Decimal("1.0"), Decimal("2.0")]),
                scope=_scope(),
            )
        )

    assert caught.value.status_code == 409
    assert "conflicting durations" in caught.value.detail


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
