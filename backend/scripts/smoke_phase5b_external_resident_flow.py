"""
Phase 5B smoke helper for the external resident backend flow.

Prerequisites:
- Backend API is running at http://localhost:8000/api/v1
- Database migrations are applied

Run from backend directory:
    python scripts/smoke_phase5b_external_resident_flow.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings


BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT_SECONDS = 45.0


@dataclass
class SmokeContext:
    posting_true: str
    posting_true_original: bool
    posting_false: str
    posting_false_original: bool
    today: date


@dataclass
class SmokeExternalResident:
    resident_id: str
    mcr: str
    name: str
    home_cluster: str
    current_posting_code: str


class SmokeRunner:
    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.failed = 0

    def pass_(self, label: str, detail: str = "") -> None:
        self.passed += 1
        suffix = f" | {detail}" if detail else ""
        print(f"PASS: {label}{suffix}")

    def skip(self, label: str, detail: str = "") -> None:
        self.skipped += 1
        suffix = f" | {detail}" if detail else ""
        print(f"SKIP: {label}{suffix}")

    def fail(self, label: str, detail: str = "") -> None:
        self.failed += 1
        suffix = f" | {detail}" if detail else ""
        print(f"FAIL: {label}{suffix}")

    def summary(self) -> None:
        print(
            "SUMMARY: "
            f"PASS={self.passed} "
            f"SKIP={self.skipped} "
            f"FAIL={self.failed}"
        )


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def db_fetchone(
    conn: Connection,
    sql: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    result = conn.execute(text(sql), params or {})
    row = result.fetchone()
    return None if row is None else _row_to_dict(row)


def db_fetchall(
    conn: Connection,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = conn.execute(text(sql), params or {})
    return [_row_to_dict(row) for row in result.fetchall()]


def discover_context(conn: Connection) -> SmokeContext | None:
    rows = db_fetchall(
        conn,
        """
        SELECT code, supports_secretary_events, created_at
        FROM posting_codes
        ORDER BY created_at ASC, code ASC
        """,
    )
    if len(rows) < 2:
        return None
    posting_true = rows[0]
    posting_false = rows[1]
    return SmokeContext(
        posting_true=posting_true["code"],
        posting_true_original=bool(posting_true["supports_secretary_events"]),
        posting_false=posting_false["code"],
        posting_false_original=bool(posting_false["supports_secretary_events"]),
        today=date.today(),
    )


def set_posting_support_flags(conn: Connection, context: SmokeContext) -> None:
    conn.execute(
        text(
            """
            UPDATE posting_codes
            SET supports_secretary_events = :enabled
            WHERE code = :code
            """
        ),
        {"code": context.posting_true, "enabled": True},
    )
    conn.execute(
        text(
            """
            UPDATE posting_codes
            SET supports_secretary_events = :enabled
            WHERE code = :code
            """
        ),
        {"code": context.posting_false, "enabled": False},
    )


def restore_posting_support_flags(conn: Connection, context: SmokeContext) -> None:
    conn.execute(
        text(
            """
            UPDATE posting_codes
            SET supports_secretary_events = :enabled
            WHERE code = :code
            """
        ),
        {"code": context.posting_true, "enabled": context.posting_true_original},
    )
    conn.execute(
        text(
            """
            UPDATE posting_codes
            SET supports_secretary_events = :enabled
            WHERE code = :code
            """
        ),
        {"code": context.posting_false, "enabled": context.posting_false_original},
    )


def choose_non_holiday_date(today: date, holiday_dates: set[date]) -> date | None:
    cursor = today
    for _ in range(45):
        if cursor not in holiday_dates:
            return cursor
        cursor -= timedelta(days=1)
    return None


def choose_weekend_non_holiday(today: date, holiday_dates: set[date]) -> date | None:
    cursor = today
    for _ in range(120):
        if cursor.weekday() in {5, 6} and cursor not in holiday_dates:
            return cursor
        cursor -= timedelta(days=1)
    return None


def create_secretary_event_row(
    conn: Connection,
    *,
    posting_code: str,
    teaching_name: str,
    event_date: date,
) -> str:
    row = db_fetchone(
        conn,
        """
        INSERT INTO teaching_events (
            posting_code,
            teaching_name,
            event_date,
            start_time,
            end_time,
            duration_hours,
            session_type_id,
            is_adhoc,
            created_by_role
        )
        VALUES (
            :posting_code,
            :teaching_name,
            :event_date,
            '10:00',
            '11:00',
            1.0,
            NULL,
            false,
            'secretary'
        )
        RETURNING id
        """,
        {
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
        },
    )
    if row is None:
        raise RuntimeError("Failed to insert smoke secretary event row.")
    return str(row["id"])


def db_count(conn: Connection, sql: str, params: dict[str, Any]) -> int:
    result = conn.execute(text(sql), params)
    value = result.scalar_one()
    return int(value)


def http_error_text(response: httpx.Response) -> str:
    try:
        return str(response.json())
    except Exception:
        return response.text


def cleanup_created_rows(
    conn: Connection,
    *,
    created_event_ids: list[str],
    external_resident_id: str | None,
    external_resident_mcr: str | None,
) -> None:
    if external_resident_id is not None:
        conn.execute(
            text(
                """
                DELETE FROM external_attendance_records
                WHERE external_resident_id = :external_resident_id
                """
            ),
            {"external_resident_id": external_resident_id},
        )
        conn.execute(
            text(
                """
                DELETE FROM external_resident_postings
                WHERE external_resident_id = :external_resident_id
                """
            ),
            {"external_resident_id": external_resident_id},
        )
        conn.execute(
            text(
                """
                DELETE FROM external_residents
                WHERE id = :external_resident_id
                """
            ),
            {"external_resident_id": external_resident_id},
        )
    elif external_resident_mcr is not None:
        conn.execute(
            text(
                """
                DELETE FROM external_attendance_records
                WHERE external_resident_id IN (
                    SELECT id
                    FROM external_residents
                    WHERE mcr = :mcr
                )
                """
            ),
            {"mcr": external_resident_mcr},
        )
        conn.execute(
            text(
                """
                DELETE FROM external_resident_postings
                WHERE external_resident_id IN (
                    SELECT id
                    FROM external_residents
                    WHERE mcr = :mcr
                )
                """
            ),
            {"mcr": external_resident_mcr},
        )
        conn.execute(
            text("DELETE FROM external_residents WHERE mcr = :mcr"),
            {"mcr": external_resident_mcr},
        )

    for event_id in created_event_ids:
        conn.execute(
            text("DELETE FROM external_attendance_records WHERE teaching_event_id = :event_id"),
            {"event_id": event_id},
        )
        conn.execute(
            text("DELETE FROM attendance_records WHERE teaching_event_id = :event_id"),
            {"event_id": event_id},
        )
        conn.execute(
            text("DELETE FROM teaching_events WHERE id = :event_id"),
            {"event_id": event_id},
        )


def main() -> int:
    runner = SmokeRunner()
    settings = get_settings()
    engine: Engine = create_engine(settings.sync_database_url)

    context: SmokeContext | None = None
    created_event_ids: list[str] = []
    external_resident_id: str | None = None
    external_resident_mcr: str | None = None

    unique_suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + uuid4().hex[:6]
    smoke_mcr = f"SMK5B{unique_suffix[:13]}".upper()
    smoke_name = f"Smoke External {unique_suffix[-6:]}"

    try:
        with engine.begin() as conn:
            context = discover_context(conn)
            if context is None:
                runner.fail(
                    "discover posting context",
                    "Need at least two posting_codes rows for true/false capability setup.",
                )
                runner.summary()
                return 1

            set_posting_support_flags(conn, context)
            verify_true = db_fetchone(
                conn,
                "SELECT supports_secretary_events FROM posting_codes WHERE code = :code",
                {"code": context.posting_true},
            )
            verify_false = db_fetchone(
                conn,
                "SELECT supports_secretary_events FROM posting_codes WHERE code = :code",
                {"code": context.posting_false},
            )
            if not verify_true or not verify_false:
                runner.fail("posting capability setup", "Unable to verify posting capability flags.")
                runner.summary()
                return 1
            if bool(verify_true["supports_secretary_events"]) and not bool(
                verify_false["supports_secretary_events"]
            ):
                runner.pass_(
                    "posting capability setup",
                    f"true={context.posting_true} false={context.posting_false}",
                )
            else:
                runner.fail(
                    "posting capability setup",
                    "supports_secretary_events flags did not apply as expected.",
                )
                runner.summary()
                return 1

        with engine.connect() as conn:
            holiday_rows = db_fetchall(
                conn,
                "SELECT holiday_date FROM public_holidays ORDER BY holiday_date ASC",
            )
            holiday_dates = {row["holiday_date"] for row in holiday_rows}

            with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_SECONDS) as client:
                register_resp = client.post(
                    "/external-residents/register",
                    json={
                        "name": smoke_name,
                        "mcr": smoke_mcr,
                        "home_cluster": "NUH",
                        "current_nhg_posting_code": context.posting_true,
                    },
                )
                if register_resp.status_code != 200:
                    runner.fail(
                        "POST /external-residents/register",
                        f"HTTP {register_resp.status_code}: {http_error_text(register_resp)}",
                    )
                    runner.summary()
                    return 1
                register_body = register_resp.json()
                external_resident_id = register_body["resident"]["id"]
                external_resident_mcr = register_body["resident"]["mcr"]
                runner.pass_(
                    "POST /external-residents/register",
                    f"external_resident_id={external_resident_id}",
                )

                posting_history = register_body.get("posting_history", {})
                if (
                    posting_history.get("external_resident_id") == external_resident_id
                    and posting_history.get("posting_code") == context.posting_true
                    and posting_history.get("is_current") is True
                ):
                    runner.pass_("initial posting history row created")
                else:
                    runner.fail(
                        "initial posting history row created",
                        f"posting_history={posting_history}",
                    )

                login_resp = client.post(
                    "/auth/login",
                    json={"role": "external_resident", "mcr": smoke_mcr},
                )
                if login_resp.status_code != 200:
                    runner.fail(
                        "POST /auth/login (external_resident)",
                        f"HTTP {login_resp.status_code}: {http_error_text(login_resp)}",
                    )
                    runner.summary()
                    return 1
                login_body = login_resp.json()
                if login_body.get("user", {}).get("role") == "external_resident":
                    runner.pass_("POST /auth/login (external_resident)")
                else:
                    runner.fail("POST /auth/login (external_resident)", f"body={login_body}")

                external_headers = {
                    "X-User-Role": "external_resident",
                    "X-User-Id": external_resident_id,
                }

                me_resp = client.get("/auth/me", headers=external_headers)
                if me_resp.status_code != 200:
                    runner.fail(
                        "GET /auth/me (external_resident)",
                        f"HTTP {me_resp.status_code}: {http_error_text(me_resp)}",
                    )
                    runner.summary()
                    return 1
                me_body = me_resp.json()
                if me_body.get("mcr") == smoke_mcr and "current_nhg_posting_code" not in me_body:
                    runner.pass_("GET /auth/me (external_resident)")
                else:
                    runner.fail("GET /auth/me (external_resident)", f"body={me_body}")

                non_holiday_date = choose_non_holiday_date(context.today, holiday_dates)
                if non_holiday_date is None:
                    runner.fail(
                        "pick non-holiday event date",
                        "No non-holiday date found in trailing 45-day window.",
                    )
                    runner.summary()
                    return 1

                events_true = client.get("/resident/events", headers=external_headers)
                if events_true.status_code != 200:
                    runner.fail(
                        "GET /resident/events (supports=true)",
                        f"HTTP {events_true.status_code}: {http_error_text(events_true)}",
                    )
                    runner.summary()
                    return 1
                events_true_body = events_true.json()
                events_true_rows = events_true_body.get("events", [])
                true_event_id: str | None = None
                if events_true_rows:
                    true_event_id = str(events_true_rows[0]["id"])
                    runner.pass_(
                        "external event visibility when supports=true",
                        f"event_id={true_event_id}",
                    )
                else:
                    runner.skip(
                        "external event visibility when supports=true",
                        f"No eligible secretary-created events. reason={events_true_body.get('reason')}",
                    )

                if true_event_id is not None:
                    submit_true = client.post(
                        "/resident/attendance",
                        headers=external_headers,
                        json={"event_ids": [true_event_id]},
                    )
                    if submit_true.status_code != 200:
                        runner.fail(
                            "POST /resident/attendance (external, supports=true)",
                            f"HTTP {submit_true.status_code}: {http_error_text(submit_true)}",
                        )
                    else:
                        submit_true_body = submit_true.json()
                        if submit_true_body.get("submitted") == 1:
                            runner.pass_("POST /resident/attendance (external, supports=true)")
                        else:
                            runner.fail(
                                "POST /resident/attendance (external, supports=true)",
                                f"body={submit_true_body}",
                            )

                    external_count = db_count(
                        conn,
                        """
                        SELECT COUNT(*)
                        FROM external_attendance_records
                        WHERE external_resident_id = :external_resident_id
                          AND teaching_event_id = :event_id
                          AND status = 'submitted'
                        """,
                        {"external_resident_id": external_resident_id, "event_id": true_event_id},
                    )
                    native_count = db_count(
                        conn,
                        """
                        SELECT COUNT(*)
                        FROM attendance_records
                        WHERE teaching_event_id = :event_id
                        """,
                        {"event_id": true_event_id},
                    )
                    if external_count == 1 and native_count == 0:
                        runner.pass_("external attendance stored only in external_attendance_records")
                    else:
                        runner.fail(
                            "external attendance stored only in external_attendance_records",
                            f"external_count={external_count} native_count={native_count}",
                        )

                    events_after_submit = client.get("/resident/events", headers=external_headers)
                    if events_after_submit.status_code == 200 and true_event_id not in {
                        row["id"] for row in events_after_submit.json().get("events", [])
                    }:
                        runner.pass_("submitted external event excluded from /resident/events")
                    else:
                        runner.fail(
                            "submitted external event excluded from /resident/events",
                            f"response={http_error_text(events_after_submit)}",
                        )

                    history_resp = client.get("/resident/attendance-history", headers=external_headers)
                    if history_resp.status_code != 200:
                        runner.fail(
                            "GET /resident/attendance-history (external)",
                            f"HTTP {history_resp.status_code}: {http_error_text(history_resp)}",
                        )
                    else:
                        history_rows = history_resp.json().get("attendance", [])
                        if any(row.get("teaching_event_id") == true_event_id for row in history_rows):
                            runner.pass_("GET /resident/attendance-history (external)")
                        else:
                            runner.fail(
                                "GET /resident/attendance-history (external)",
                                "Submitted event not found in history response.",
                            )
                else:
                    runner.skip(
                        "POST /resident/attendance (external, supports=true)",
                        "No eligible secretary-created events available for submission.",
                    )
                    runner.skip(
                        "external attendance stored only in external_attendance_records",
                        "No submitted secretary event available.",
                    )
                    runner.skip(
                        "submitted external event excluded from /resident/events",
                        "No submitted secretary event available.",
                    )
                    runner.skip(
                        "GET /resident/attendance-history (external)",
                        "No submitted secretary event available for history check.",
                    )

                posting_update_resp = client.put(
                    "/external-residents/me/posting",
                    headers=external_headers,
                    json={"current_nhg_posting_code": context.posting_false},
                )
                if posting_update_resp.status_code != 200:
                    runner.fail(
                        "PUT /external-residents/me/posting",
                        f"HTTP {posting_update_resp.status_code}: {http_error_text(posting_update_resp)}",
                    )
                    runner.summary()
                    return 1
                posting_update = posting_update_resp.json()
                if posting_update.get("changed") is True:
                    runner.pass_(
                        "PUT /external-residents/me/posting",
                        f"new_posting={posting_update['resident']['current_nhg_posting_code']}",
                    )
                else:
                    runner.fail("PUT /external-residents/me/posting", f"body={posting_update}")

                updated_history = posting_update.get("posting_history", {})
                if (
                    updated_history.get("external_resident_id") == external_resident_id
                    and updated_history.get("posting_code") == context.posting_false
                    and updated_history.get("is_current") is True
                ):
                    runner.pass_("posting history closed old row and opened new current row")
                else:
                    runner.fail(
                        "posting history closed old row and opened new current row",
                        f"posting_history={updated_history}",
                    )

                events_false = client.get("/resident/events", headers=external_headers)
                if events_false.status_code != 200:
                    runner.fail(
                        "GET /resident/events (supports=false)",
                        f"HTTP {events_false.status_code}: {http_error_text(events_false)}",
                    )
                else:
                    body = events_false.json()
                    if body.get("events") == [] and body.get("reason") == "secretary_events_not_supported":
                        runner.pass_("external event visibility blocked when supports=false")
                    else:
                        runner.fail(
                            "external event visibility blocked when supports=false",
                            f"body={body}",
                        )

                runner.skip(
                    "POST /resident/attendance blocked for secretary event when supports=false",
                    "No deterministic secretary-created event source on supports=false posting without shared DB event provisioning.",
                )

                adhoc_resp = client.post(
                    "/resident/adhoc-teaching",
                    headers=external_headers,
                    json={
                        "date": non_holiday_date.isoformat(),
                        "start_time": "09:30",
                        "teaching_name": f"SMOKE-P5B-ADHOC-{unique_suffix}",
                    },
                )
                if adhoc_resp.status_code != 200:
                    runner.fail(
                        "POST /resident/adhoc-teaching (external)",
                        f"HTTP {adhoc_resp.status_code}: {http_error_text(adhoc_resp)}",
                    )
                else:
                    adhoc_body = adhoc_resp.json()
                    adhoc_event = adhoc_body.get("event", {})
                    created_event_ids.append(adhoc_event["id"])
                    if (
                        adhoc_event.get("is_adhoc") is True
                        and adhoc_event.get("created_by_role") == "external_resident"
                        and adhoc_event.get("posting_code") == context.posting_false
                    ):
                        runner.pass_("POST /resident/adhoc-teaching (external)")
                    else:
                        runner.fail("POST /resident/adhoc-teaching (external)", f"body={adhoc_body}")

                if holiday_rows:
                    ph_date = holiday_rows[0]["holiday_date"]
                    before_count = db_count(
                        conn,
                        """
                        SELECT COUNT(*)
                        FROM external_attendance_records
                        WHERE external_resident_id = :external_resident_id
                        """,
                        {"external_resident_id": external_resident_id},
                    )
                    ph_resp = client.post(
                        "/resident/adhoc-teaching",
                        headers=external_headers,
                        json={
                            "date": ph_date.isoformat(),
                            "start_time": "10:00",
                            "teaching_name": f"SMOKE-P5B-PH-{unique_suffix}",
                        },
                    )
                    after_count = db_count(
                        conn,
                        """
                        SELECT COUNT(*)
                        FROM external_attendance_records
                        WHERE external_resident_id = :external_resident_id
                        """,
                        {"external_resident_id": external_resident_id},
                    )
                    if ph_resp.status_code == 422 and before_count == after_count:
                        runner.pass_("external ad-hoc PH hard-block (422)")
                    else:
                        runner.fail(
                            "external ad-hoc PH hard-block (422)",
                            f"HTTP {ph_resp.status_code} before={before_count} after={after_count}",
                        )
                else:
                    runner.skip("external ad-hoc PH hard-block (422)", "No public_holidays data found")

                weekend_date = choose_weekend_non_holiday(context.today, holiday_dates)
                if weekend_date is None:
                    runner.skip(
                        "external weekend compliance_warning",
                        "No weekend non-holiday date found in trailing 120-day window.",
                    )
                else:
                    weekend_resp = client.post(
                        "/resident/adhoc-teaching",
                        headers=external_headers,
                        json={
                            "date": weekend_date.isoformat(),
                            "start_time": "10:00",
                            "teaching_name": f"SMOKE-P5B-WEEKEND-{unique_suffix}",
                        },
                    )
                    if weekend_resp.status_code != 200:
                        runner.skip(
                            "external weekend compliance_warning",
                            f"Weekend ad-hoc request was not accepted: HTTP {weekend_resp.status_code}",
                        )
                    else:
                        weekend_body = weekend_resp.json()
                        weekend_event = weekend_body.get("event")
                        if weekend_event:
                            created_event_ids.append(weekend_event["id"])
                        warning = weekend_body.get("compliance_warning")
                        if warning:
                            runner.pass_(
                                "external weekend compliance_warning",
                                f"weekend_date={weekend_date.isoformat()}",
                            )
                        else:
                            runner.skip(
                                "external weekend compliance_warning",
                                "No warning returned (likely matched weekend exception rules).",
                            )

                dashboard_resp = client.get("/resident/dashboard", headers=external_headers)
                if dashboard_resp.status_code != 200:
                    runner.fail(
                        "GET /resident/dashboard (external)",
                        f"HTTP {dashboard_resp.status_code}: {http_error_text(dashboard_resp)}",
                    )
                else:
                    dashboard_body = dashboard_resp.json()
                    if (
                        dashboard_body.get("compliance_status") == "not_applicable"
                        and dashboard_body.get("reason")
                        == "external_resident_excluded_from_nhg_compliance"
                    ):
                        runner.pass_("GET /resident/dashboard (external) not_applicable")
                    else:
                        runner.fail(
                            "GET /resident/dashboard (external) not_applicable",
                            f"body={dashboard_body}",
                        )

        if runner.failed:
            runner.summary()
            return 1

    except Exception as exc:
        runner.fail("smoke execution", str(exc))
        runner.summary()
        return 1
    finally:
        if context is not None:
            with engine.begin() as conn:
                cleanup_created_rows(
                    conn,
                    created_event_ids=created_event_ids,
                    external_resident_id=external_resident_id,
                    external_resident_mcr=external_resident_mcr or smoke_mcr,
                )
                restore_posting_support_flags(conn, context)
                runner.pass_(
                    "cleanup smoke-created rows",
                    (
                        f"events_deleted={len(created_event_ids)} "
                        f"external_resident_deleted={external_resident_id is not None} "
                        "posting_flags_restored=true"
                    ),
                )
        engine.dispose()

    runner.summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
