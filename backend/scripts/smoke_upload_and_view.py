"""
Manual local smoke helper for upload + persisted-output view verification.

Prerequisites:
- Backend is running at http://localhost:8000 (API base: /api/v1)
- Database migrations are applied
- Sample Excel files exist in backend/tests/data/

Run from repo root:
    python backend/scripts/smoke_upload_and_view.py

Note:
- This script performs real API writes (uploads and possible reporting period create/update)
- It is intended for local manual verification/demo, not CI
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT_SECONDS = 300.0

ADMIN_HEADERS = {
    "X-User-Role": "admin",
    "X-User-Id": "5635c7b4-e0f1-4f59-88e1-f0b976b62d29",
    "X-User-Programme": "DR,GERI",
}

REPORTING_PERIOD_LABEL = "Jul - Dec 2025"
REPORTING_PERIOD_START = "2025-07-01"
REPORTING_PERIOD_END = "2025-12-31"
REPORTING_PERIOD_STATUS = "open"


def _truncate(value: Any, max_chars: int = 600) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "... [truncated]"


def _raise_for_http_error(response: httpx.Response, label: str) -> None:
    if response.status_code < 400:
        return
    try:
        body = response.json()
    except Exception:  # pragma: no cover - defensive for non-json errors
        body = response.text
    raise RuntimeError(
        f"{label} failed with HTTP {response.status_code}: {_truncate(body, max_chars=1200)}"
    )


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    label: str,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    response = client.request(
        method=method,
        url=path,
        params=params,
        data=data,
        files=files,
        json=json_body,
    )
    _raise_for_http_error(response, label)
    if response.status_code == 204:
        return None
    return response.json()


def _resolve_data_files() -> dict[str, Path]:
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = repo_root / "backend" / "tests" / "data"
    expected = {
        "public_holidays": data_dir / "AY26 Changeover dates and PH.xlsx",
        "rdb": data_dir / "AY25 Posting Schedule_2026.04.23.xlsx",
        "ttf_dr": data_dir / "Teaching_Target_File_DR__CL.xlsx",
        "ttf_geri": data_dir / "Teaching_Target_File_GRM__CL.xlsx",
        "form_f1": data_dir / "AY25 Form F1_MOHv4.xlsx",
    }
    missing = [str(path) for path in expected.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing required sample file(s):\n- " + "\n- ".join(missing)
        )
    return expected


def _get_or_create_reporting_period(client: httpx.Client) -> str:
    existing_periods = _request_json(
        client,
        "GET",
        "/admin/reporting-periods",
        label="GET /admin/reporting-periods",
    )
    for row in existing_periods:
        if (
            row.get("label") == REPORTING_PERIOD_LABEL
            and row.get("start_date") == REPORTING_PERIOD_START
            and row.get("end_date") == REPORTING_PERIOD_END
        ):
            reporting_period_id = row["id"]
            if row.get("status") != REPORTING_PERIOD_STATUS:
                _request_json(
                    client,
                    "PUT",
                    f"/admin/reporting-periods/{reporting_period_id}",
                    label=f"PUT /admin/reporting-periods/{reporting_period_id}",
                    json_body={"status": REPORTING_PERIOD_STATUS},
                )
            print(
                f"Reporting period: using existing id={reporting_period_id} label={REPORTING_PERIOD_LABEL}"
            )
            return reporting_period_id

    created = _request_json(
        client,
        "POST",
        "/admin/reporting-periods",
        label="POST /admin/reporting-periods",
        json_body={
            "label": REPORTING_PERIOD_LABEL,
            "start_date": REPORTING_PERIOD_START,
            "end_date": REPORTING_PERIOD_END,
        },
    )
    reporting_period_id = created["id"]
    print(f"Reporting period: created id={reporting_period_id} label={REPORTING_PERIOD_LABEL}")
    return reporting_period_id


def _upload_file(
    client: httpx.Client,
    *,
    label: str,
    endpoint: str,
    file_path: Path,
    form_fields: dict[str, Any] | None = None,
) -> Any:
    with file_path.open("rb") as f:
        payload = _request_json(
            client,
            "POST",
            endpoint,
            label=label,
            data=form_fields or {},
            files={
                "file": (
                    file_path.name,
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    print(f"{label}: HTTP 200")
    print(f"  response: {_truncate(payload)}")
    return payload


def _print_read_result(label: str, rows: list[dict[str, Any]]) -> None:
    print(f"{label}: rows={len(rows)}")
    if rows:
        print(f"  sample: {_truncate(rows[0], max_chars=800)}")


def main() -> None:
    files = _resolve_data_files()
    with httpx.Client(
        base_url=BASE_URL,
        headers=ADMIN_HEADERS,
        timeout=TIMEOUT_SECONDS,
    ) as client:
        reporting_period_id = _get_or_create_reporting_period(client)

        print("\n=== Upload files ===")
        _upload_file(
            client,
            label="POST /admin/upload/public-holidays",
            endpoint="/admin/upload/public-holidays",
            file_path=files["public_holidays"],
        )
        _upload_file(
            client,
            label="POST /admin/upload/rdb",
            endpoint="/admin/upload/rdb",
            file_path=files["rdb"],
            form_fields={"reporting_period_id": reporting_period_id},
        )
        _upload_file(
            client,
            label="POST /admin/upload/ttf (DR)",
            endpoint="/admin/upload/ttf",
            file_path=files["ttf_dr"],
            form_fields={
                "reporting_period_id": reporting_period_id,
                "programme_code": "DR",
            },
        )
        _upload_file(
            client,
            label="POST /admin/upload/ttf (GERI)",
            endpoint="/admin/upload/ttf",
            file_path=files["ttf_geri"],
            form_fields={
                "reporting_period_id": reporting_period_id,
                "programme_code": "GERI",
            },
        )
        _upload_file(
            client,
            label="POST /admin/upload/form-f1",
            endpoint="/admin/upload/form-f1",
            file_path=files["form_f1"],
            form_fields={"reporting_period_id": reporting_period_id},
        )

        print("\n=== View persisted upload outputs ===")
        reads = [
            (
                "GET /admin/residents",
                "/admin/residents",
                {"limit": 100},
            ),
            (
                "GET /admin/resident-postings",
                "/admin/resident-postings",
                {"reporting_period_id": reporting_period_id, "limit": 100},
            ),
            (
                "GET /admin/posting-codes",
                "/admin/posting-codes",
                {"limit": 100},
            ),
            (
                "GET /admin/session-types",
                "/admin/session-types",
                {"limit": 100},
            ),
            (
                "GET /admin/teaching-targets",
                "/admin/teaching-targets",
                {"reporting_period_id": reporting_period_id, "limit": 100},
            ),
            (
                "GET /admin/teaching-name-catalogue",
                "/admin/teaching-name-catalogue",
                {"reporting_period_id": reporting_period_id, "limit": 100},
            ),
            (
                "GET /admin/form-f1-records",
                "/admin/form-f1-records",
                {"reporting_period_id": reporting_period_id},
            ),
            (
                "GET /admin/public-holidays",
                "/admin/public-holidays",
                {},
            ),
            (
                "GET /admin/academic-month-boundaries",
                "/admin/academic-month-boundaries",
                {"limit": 100},
            ),
            (
                "GET /admin/upload-logs",
                "/admin/upload-logs",
                {"reporting_period_id": reporting_period_id, "limit": 100},
            ),
        ]

        for label, path, params in reads:
            payload = _request_json(client, "GET", path, label=label, params=params)
            if not isinstance(payload, list):
                raise RuntimeError(f"{label} expected list payload but got: {_truncate(payload)}")
            _print_read_result(label, payload)


if __name__ == "__main__":
    main()
