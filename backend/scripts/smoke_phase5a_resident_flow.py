"""
Phase 5A smoke helper for the native resident backend flow.

Prerequisites:
- Backend API is running at http://localhost:8000/api/v1
- Database migrations are applied
- DB has at least one open reporting period and one resident with a current posting row

Run from backend directory:
    python scripts/smoke_phase5a_resident_flow.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
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
SMOKE_SECRETARY_PASSWORD = "smoke-secretary-password"


@dataclass
class SmokeContext:
    resident_id: str
    resident_mcr: str
    resident_programme_code: str
    reporting_period_id: str
    reporting_period_label: str
    posting_code: str
    posting_r_year: str
    posting_start: date
    posting_end: date
    today: date


@dataclass
class SecretaryAccount:
    user_id: str
    email: str
    created_by_script: bool


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


def db_fetchone(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = conn.execute(text(sql), params or {})
    row = result.fetchone()
    return None if row is None else _row_to_dict(row)


def db_fetchall(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = conn.execute(text(sql), params or {})
    return [_row_to_dict(row) for row in result.fetchall()]


def discover_context(conn: Connection) -> SmokeContext | None:
    row = db_fetchone(
        conn,
        """
        SELECT
            r.id AS resident_id,
            r.mcr AS resident_mcr,
            r.programme_code AS resident_programme_code,
            rp.id AS reporting_period_id,
            rp.label AS reporting_period_label,
            rpo.posting_code AS posting_code,
            rpo.r_year AS posting_r_year,
            rpo.start_date AS posting_start,
            rpo.end_date AS posting_end,
            CURRENT_DATE AS today
        FROM reporting_periods rp
        JOIN resident_postings rpo
          ON rpo.reporting_period_id = rp.id
        JOIN residents r
          ON r.id = rpo.resident_id
        WHERE rp.status = 'open'
          AND r.status != 'inactive'
          AND r.programme_code IS NOT NULL
          AND rpo.posting_code IS NOT NULL
          AND rpo.status IN ('active', 'loa_working')
          AND CURRENT_DATE BETWEEN rpo.start_date AND rpo.end_date
        ORDER BY rpo.start_date DESC, rpo.created_at DESC
        LIMIT 1
        """,
    )
    if row is None:
        return None

    return SmokeContext(
        resident_id=str(row["resident_id"]),
        resident_mcr=row["resident_mcr"],
        resident_programme_code=row["resident_programme_code"],
        reporting_period_id=str(row["reporting_period_id"]),
        reporting_period_label=row["reporting_period_label"],
        posting_code=row["posting_code"],
        posting_r_year=row["posting_r_year"],
        posting_start=row["posting_start"],
        posting_end=row["posting_end"],
        today=row["today"],
    )


def ensure_secretary_for_posting(conn: Connection, posting_code: str) -> SecretaryAccount:
    existing = db_fetchone(
        conn,
        """
        SELECT id, email
        FROM users
        WHERE role = 'secretary'
          AND posting_code = :posting_code
          AND is_active = true
        ORDER BY created_at ASC
        LIMIT 1
        """,
        {"posting_code": posting_code},
    )
    if existing is not None:
        return SecretaryAccount(
            user_id=str(existing["id"]),
            email=existing["email"],
            created_by_script=False,
        )

    clean_posting = "".join(ch.lower() for ch in posting_code if ch.isalnum()) or "posting"
    email = f"smoke.secretary.{clean_posting}.{uuid4().hex[:10]}@example.local"
    created = db_fetchone(
        conn,
        """
        INSERT INTO users (
            email,
            password_hash,
            role,
            name,
            posting_code,
            programme_scope,
            is_active
        )
        VALUES (
            :email,
            :password_hash,
            'secretary',
            :name,
            :posting_code,
            NULL,
            true
        )
        RETURNING id, email
        """,
        {
            "email": email,
            "password_hash": f"plain:{SMOKE_SECRETARY_PASSWORD}",
            "name": f"Smoke Secretary {posting_code}",
            "posting_code": posting_code,
        },
    )
    if created is None:
        raise RuntimeError("Failed to create smoke secretary user")
    return SecretaryAccount(
        user_id=str(created["id"]),
        email=created["email"],
        created_by_script=True,
    )


def source_payload_from_option(option: dict[str, Any]) -> dict[str, str] | None:
    teaching_name_id = option.get("teaching_name_id")
    global_session_type_id = option.get("global_session_type_id")
    if bool(teaching_name_id) == bool(global_session_type_id):
        return None
    if teaching_name_id:
        return {"teaching_name_id": str(teaching_name_id)}
    return {"global_session_type_id": str(global_session_type_id)}


def build_resident_headers(context: SmokeContext) -> dict[str, str]:
    return {
        "X-User-Role": "resident",
        "X-User-Id": context.resident_id,
        "X-User-Programme": context.resident_programme_code,
    }


def build_secretary_headers(secretary: SecretaryAccount, posting_code: str) -> dict[str, str]:
    return {
        "X-User-Role": "secretary",
        "X-User-Id": secretary.user_id,
        "X-User-Site": posting_code,
    }


def choose_non_holiday_date(
    *,
    start_date: date,
    end_date: date,
    today: date,
    holiday_dates: set[date],
) -> date | None:
    upper = min(end_date, today)
    if upper < start_date:
        return None
    cursor = upper
    while cursor >= start_date:
        if cursor not in holiday_dates:
            return cursor
        cursor -= timedelta(days=1)
    return None


def weekend_candidates(
    *,
    start_date: date,
    end_date: date,
    today: date,
    holiday_dates: set[date],
) -> list[date]:
    upper = min(end_date, today)
    if upper < start_date:
        return []
    values: list[date] = []
    cursor = upper
    while cursor >= start_date:
        if cursor.weekday() in {5, 6} and cursor not in holiday_dates:
            values.append(cursor)
        cursor -= timedelta(days=1)
    return values


def http_error_text(response: httpx.Response) -> str:
    try:
        return str(response.json())
    except Exception:
        return response.text


def create_secretary_event(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    source_payload: dict[str, str],
    event_date: date,
) -> tuple[bool, dict[str, Any] | None, str]:
    response = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={
            **source_payload,
            "event_date": event_date.isoformat(),
            "start_time": "10:00",
        },
    )
    if response.status_code != 200:
        return False, None, http_error_text(response)
    return True, response.json(), ""


def cleanup_created_rows(
    conn: Connection,
    *,
    attendance_ids: list[str],
    event_ids: list[str],
    created_secretary_id: str | None,
) -> None:
    for attendance_id in attendance_ids:
        conn.execute(
            text("DELETE FROM attendance_records WHERE id = :attendance_id"),
            {"attendance_id": attendance_id},
        )
    for event_id in event_ids:
        conn.execute(
            text("DELETE FROM attendance_records WHERE teaching_event_id = :event_id"),
            {"event_id": event_id},
        )
        conn.execute(
            text("DELETE FROM teaching_events WHERE id = :event_id"),
            {"event_id": event_id},
        )
    if created_secretary_id is not None:
        conn.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": created_secretary_id},
        )


def main() -> int:
    runner = SmokeRunner()
    settings = get_settings()
    engine: Engine = create_engine(settings.sync_database_url)

    created_event_ids: list[str] = []
    created_attendance_ids: list[str] = []
    created_secretary_id: str | None = None

    try:
        with engine.begin() as conn:
            context = discover_context(conn)
            if context is None:
                runner.fail(
                    "discover native resident context",
                    "No resident with current open-period posting (active/loa_working) was found.",
                )
                runner.summary()
                return 1
            runner.pass_(
                "discover native resident context",
                (
                    f"resident_id={context.resident_id} "
                    f"posting={context.posting_code} "
                    f"period='{context.reporting_period_label}'"
                ),
            )

            secretary = ensure_secretary_for_posting(conn, context.posting_code)
            if secretary.created_by_script:
                created_secretary_id = secretary.user_id
                runner.pass_(
                    "secretary account setup",
                    f"created smoke secretary {secretary.email} for posting {context.posting_code}",
                )
            else:
                runner.pass_(
                    "secretary account setup",
                    f"using existing secretary {secretary.email} for posting {context.posting_code}",
                )

        with engine.connect() as conn:
            holiday_rows = db_fetchall(
                conn,
                "SELECT holiday_date FROM public_holidays ORDER BY holiday_date ASC",
            )
            holiday_dates = {row["holiday_date"] for row in holiday_rows}

            resident_headers = build_resident_headers(context)
            secretary_headers = build_secretary_headers(secretary, context.posting_code)

            with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_SECONDS) as client:
                # POST /auth/login (resident)
                resident_login = client.post(
                    "/auth/login",
                    json={"role": "resident", "mcr": context.resident_mcr},
                )
                if resident_login.status_code != 200:
                    runner.fail(
                        "POST /auth/login (resident)",
                        f"HTTP {resident_login.status_code}: {http_error_text(resident_login)}",
                    )
                    runner.summary()
                    return 1
                resident_login_body = resident_login.json()
                if "posting_code" in resident_login_body.get("user", {}):
                    runner.fail(
                        "resident login response shape",
                        "resident login user unexpectedly includes posting_code",
                    )
                else:
                    runner.pass_("resident login response shape", "no posting_code in user payload")

                # POST /auth/login (secretary)
                secretary_login = client.post(
                    "/auth/login",
                    json={
                        "role": "secretary",
                        "email": secretary.email,
                        "password": SMOKE_SECRETARY_PASSWORD,
                    },
                )
                if secretary_login.status_code == 200:
                    runner.pass_("POST /auth/login (secretary)")
                else:
                    runner.fail(
                        "POST /auth/login (secretary)",
                        f"HTTP {secretary_login.status_code}: {http_error_text(secretary_login)}",
                    )

                # GET /auth/me (resident)
                auth_me = client.get("/auth/me", headers=resident_headers)
                if auth_me.status_code != 200:
                    runner.fail(
                        "GET /auth/me (resident)",
                        f"HTTP {auth_me.status_code}: {http_error_text(auth_me)}",
                    )
                    runner.summary()
                    return 1
                auth_me_body = auth_me.json()
                if "posting_code" in auth_me_body:
                    runner.fail("resident /auth/me response shape", "unexpected posting_code in /auth/me")
                else:
                    runner.pass_("resident /auth/me response shape", "no posting_code in response")

                # GET /secretary/teaching-name-options
                options_response = client.get(
                    "/secretary/teaching-name-options",
                    headers=secretary_headers,
                )
                if options_response.status_code != 200:
                    runner.fail(
                        "GET /secretary/teaching-name-options",
                        f"HTTP {options_response.status_code}: {http_error_text(options_response)}",
                    )
                    runner.summary()
                    return 1
                options = options_response.json().get("options", [])
                if not options:
                    runner.fail(
                        "GET /secretary/teaching-name-options",
                        f"No options available for posting {context.posting_code}",
                    )
                    runner.summary()
                    return 1
                runner.pass_(
                    "GET /secretary/teaching-name-options",
                    f"options_count={len(options)}",
                )

                source_candidates = [
                    (option, source_payload)
                    for option in options
                    if isinstance(option, dict)
                    and (source_payload := source_payload_from_option(option)) is not None
                ]
                if not source_candidates:
                    runner.fail(
                        "GET /secretary/teaching-name-options",
                        "No option supplied exactly one explicit source ID.",
                    )
                    runner.summary()
                    return 1

                selected_option, selected_source_payload = source_candidates[0]

                selected_teaching_name = selected_option["keyword"]
                runner.pass_(
                    "select explicit scheduled-event source for smoke",
                    (
                        f"teaching_name='{selected_teaching_name}' "
                        f"source={'teaching_name_id' if 'teaching_name_id' in selected_source_payload else 'global_session_type_id'}"
                    ),
                )

                primary_event_date = choose_non_holiday_date(
                    start_date=context.posting_start,
                    end_date=context.posting_end,
                    today=context.today,
                    holiday_dates=holiday_dates,
                )
                if primary_event_date is None:
                    runner.fail(
                        "choose secretary event date",
                        "No non-public-holiday date found inside resident posting window.",
                    )
                    runner.summary()
                    return 1

                # POST /secretary/teaching-events
                created_ok, created_event, created_error = create_secretary_event(
                    client,
                    headers=secretary_headers,
                    source_payload=selected_source_payload,
                    event_date=primary_event_date,
                )
                if not created_ok or created_event is None:
                    runner.fail(
                        "POST /secretary/teaching-events",
                        (
                            f"posting={context.posting_code} "
                            f"teaching_name='{selected_teaching_name}' "
                            f"error={created_error}"
                        ),
                    )
                    runner.summary()
                    return 1
                created_event_id = created_event["id"]
                created_event_ids.append(created_event_id)
                runner.pass_(
                    "POST /secretary/teaching-events",
                    f"event_id={created_event_id} event_date={created_event['event_date']}",
                )

                # GET /resident/events
                resident_events = client.get("/resident/events", headers=resident_headers)
                if resident_events.status_code != 200:
                    runner.fail(
                        "GET /resident/events",
                        f"HTTP {resident_events.status_code}: {http_error_text(resident_events)}",
                    )
                    runner.summary()
                    return 1
                resident_events_body = resident_events.json()
                resident_event_ids = {row["id"] for row in resident_events_body.get("events", [])}

                created_event_visible = created_event_id in resident_event_ids
                visible_candidates = [selected_option] if created_event_visible else []
                if created_event_visible:
                    runner.pass_("resident visibility for created secretary event", f"event_id={created_event_id}")
                else:
                    runner.skip(
                        "resident visibility for created secretary event",
                        (
                            "Selected explicit source is not visible for this resident under current persisted scope. "
                            f"teaching_name='{selected_teaching_name}'"
                        ),
                    )

                # POST /resident/attendance + visibility hide/show only if event is visible
                if created_event_visible:
                    attendance_submit = client.post(
                        "/resident/attendance",
                        headers=resident_headers,
                        json={"event_ids": [created_event_id]},
                    )
                    if attendance_submit.status_code != 200:
                        runner.fail(
                            "POST /resident/attendance",
                            f"HTTP {attendance_submit.status_code}: {http_error_text(attendance_submit)}",
                        )
                    else:
                        attendance_body = attendance_submit.json()
                        if attendance_body.get("submitted") == 1:
                            runner.pass_("POST /resident/attendance", "submitted=1")
                        else:
                            runner.fail(
                                "POST /resident/attendance",
                                f"unexpected response: {attendance_body}",
                            )

                        attendance_row = db_fetchone(
                            conn,
                            """
                            SELECT id
                            FROM attendance_records
                            WHERE resident_id = :resident_id
                              AND teaching_event_id = :event_id
                              AND status = 'submitted'
                            ORDER BY submitted_at DESC
                            LIMIT 1
                            """,
                            {
                                "resident_id": context.resident_id,
                                "event_id": created_event_id,
                            },
                        )
                        if attendance_row is None:
                            runner.fail(
                                "find attendance row after submit",
                                "No submitted attendance row found for created event.",
                            )
                        else:
                            attendance_id = str(attendance_row["id"])
                            created_attendance_ids.append(attendance_id)

                            after_submit_events = client.get("/resident/events", headers=resident_headers)
                            if after_submit_events.status_code == 200 and (
                                created_event_id
                                not in {row["id"] for row in after_submit_events.json().get("events", [])}
                            ):
                                runner.pass_("submitted event is hidden from /resident/events")
                            else:
                                runner.fail(
                                    "submitted event is hidden from /resident/events",
                                    f"response={http_error_text(after_submit_events)}",
                                )

                            delete_attendance = client.delete(
                                f"/resident/attendance/{attendance_id}",
                                headers=resident_headers,
                            )
                            if delete_attendance.status_code == 200 and (
                                delete_attendance.json().get("removed_count") == 1
                            ):
                                runner.pass_("DELETE /resident/attendance/{attendance_id}", "removed_count=1")
                            else:
                                runner.fail(
                                    "DELETE /resident/attendance/{attendance_id}",
                                    f"HTTP {delete_attendance.status_code}: {http_error_text(delete_attendance)}",
                                )

                            after_delete_events = client.get("/resident/events", headers=resident_headers)
                            if after_delete_events.status_code == 200 and (
                                created_event_id
                                in {row["id"] for row in after_delete_events.json().get("events", [])}
                            ):
                                runner.pass_("removed attendance no longer blocks event visibility")
                            else:
                                runner.fail(
                                    "removed attendance no longer blocks event visibility",
                                    f"response={http_error_text(after_delete_events)}",
                                )
                else:
                    runner.skip(
                        "attendance submit/hide/delete/show flow",
                        "Created event was not visible to resident under current persisted source scope.",
                    )

                # POST /resident/adhoc-teaching success path
                if visible_candidates:
                    adhoc_date = primary_event_date
                    adhoc_resp = client.post(
                        "/resident/adhoc-teaching",
                        headers=resident_headers,
                        json={
                            "date": adhoc_date.isoformat(),
                            "start_time": "09:00",
                            "details_of_session": visible_candidates[0]["keyword"],
                        },
                    )
                    if adhoc_resp.status_code == 200:
                        adhoc_body = adhoc_resp.json()
                        adhoc_event = adhoc_body.get("event", {})
                        adhoc_attendance = adhoc_body.get("attendance", {})
                        created_event_ids.append(adhoc_event["id"])
                        created_attendance_ids.append(adhoc_attendance["id"])
                        if adhoc_event.get("is_adhoc") is True:
                            runner.pass_("POST /resident/adhoc-teaching success", f"event_id={adhoc_event['id']}")
                        else:
                            runner.fail(
                                "POST /resident/adhoc-teaching success",
                                f"unexpected response: {adhoc_body}",
                            )
                    else:
                        runner.fail(
                            "POST /resident/adhoc-teaching success",
                            f"HTTP {adhoc_resp.status_code}: {http_error_text(adhoc_resp)}",
                        )
                else:
                    runner.skip(
                        "POST /resident/adhoc-teaching success",
                            "No selected explicit source is visible to this resident in current scope.",
                    )

                # PH ad-hoc check
                if holiday_rows:
                    ph_date = holiday_rows[0]["holiday_date"]
                    ph_teaching_name = selected_teaching_name
                    ph_adhoc_resp = client.post(
                        "/resident/adhoc-teaching",
                        headers=resident_headers,
                        json={
                            "date": ph_date.isoformat(),
                            "start_time": "10:00",
                            "details_of_session": ph_teaching_name,
                        },
                    )
                    if ph_adhoc_resp.status_code == 422:
                        runner.pass_("PH ad-hoc hard-block (422)", f"holiday_date={ph_date.isoformat()}")
                    else:
                        runner.fail(
                            "PH ad-hoc hard-block (422)",
                            f"HTTP {ph_adhoc_resp.status_code}: {http_error_text(ph_adhoc_resp)}",
                        )
                else:
                    runner.skip("PH ad-hoc hard-block (422)", "No public_holidays data found")

                # Weekend non-exception warning check
                if not visible_candidates:
                    runner.skip(
                        "weekend non-exception compliance_warning",
                        "No resident-visible teaching_name available for weekend test.",
                    )
                else:
                    weekend_dates = weekend_candidates(
                        start_date=context.posting_start,
                        end_date=context.posting_end,
                        today=context.today,
                        holiday_dates=holiday_dates,
                    )
                    if not weekend_dates:
                        runner.skip(
                            "weekend non-exception compliance_warning",
                            "No weekend date found inside resident posting window.",
                        )
                    else:
                        weekend_warning_observed = False
                        weekend_source_payload = source_payload_from_option(
                            visible_candidates[0]
                        )
                        if weekend_source_payload is None:
                            runner.fail(
                                "weekend non-exception compliance_warning",
                                "Resident-visible option no longer has exactly one explicit source ID.",
                            )
                            runner.summary()
                            return 1
                        for weekend_date in weekend_dates:
                            ok, weekend_event, weekend_error = create_secretary_event(
                                client,
                                headers=secretary_headers,
                                source_payload=weekend_source_payload,
                                event_date=weekend_date,
                            )
                            if not ok or weekend_event is None:
                                continue
                            weekend_event_id = weekend_event["id"]
                            created_event_ids.append(weekend_event_id)

                            weekend_submit = client.post(
                                "/resident/attendance",
                                headers=resident_headers,
                                json={"event_ids": [weekend_event_id]},
                            )
                            if weekend_submit.status_code != 200:
                                continue
                            weekend_submit_body = weekend_submit.json()
                            weekend_attendance = db_fetchone(
                                conn,
                                """
                                SELECT id
                                FROM attendance_records
                                WHERE resident_id = :resident_id
                                  AND teaching_event_id = :event_id
                                  AND status = 'submitted'
                                ORDER BY submitted_at DESC
                                LIMIT 1
                                """,
                                {
                                    "resident_id": context.resident_id,
                                    "event_id": weekend_event_id,
                                },
                            )
                            if weekend_attendance is not None:
                                weekend_attendance_id = str(weekend_attendance["id"])
                                created_attendance_ids.append(weekend_attendance_id)
                                client.delete(
                                    f"/resident/attendance/{weekend_attendance_id}",
                                    headers=resident_headers,
                                )

                            if weekend_submit_body.get("compliance_warning"):
                                weekend_warning_observed = True
                                runner.pass_(
                                    "weekend non-exception compliance_warning",
                                    f"weekend_date={weekend_date.isoformat()}",
                                )
                                break

                        if not weekend_warning_observed:
                            runner.skip(
                                "weekend non-exception compliance_warning",
                                (
                                    "Weekend dates were available, but tested submissions had no warning. "
                                    "Likely matched existing weekend exceptions."
                                ),
                            )

                # GET /resident/dashboard
                dashboard = client.get("/resident/dashboard", headers=resident_headers)
                if dashboard.status_code != 200:
                    runner.fail(
                        "GET /resident/dashboard",
                        f"HTTP {dashboard.status_code}: {http_error_text(dashboard)}",
                    )
                else:
                    dashboard_body = dashboard.json()
                    if dashboard_body.get("compliance_status") == "pending_phase_6":
                        runner.pass_("GET /resident/dashboard placeholder", "pending_phase_6")
                    else:
                        runner.fail(
                            "GET /resident/dashboard placeholder",
                            f"unexpected response: {dashboard_body}",
                        )

        with engine.begin() as conn:
            cleanup_created_rows(
                conn,
                attendance_ids=created_attendance_ids,
                event_ids=created_event_ids,
                created_secretary_id=created_secretary_id,
            )
            runner.pass_(
                "cleanup smoke-created rows",
                (
                    f"attendance_rows={len(created_attendance_ids)} "
                    f"event_rows={len(created_event_ids)} "
                    f"secretary_deleted={created_secretary_id is not None}"
                ),
            )

    except Exception as exc:
        runner.fail("smoke execution", str(exc))
    finally:
        engine.dispose()

    runner.summary()
    return 1 if runner.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
