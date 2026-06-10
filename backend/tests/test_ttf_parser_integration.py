from __future__ import annotations

import asyncio
import json
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.services.ttf_parser import parse_ttf_upload


class _FakeScalarResult:
    def __init__(self, value=None):
        self._value = value

    def scalar(self):
        return self._value

    def mappings(self):
        return self

    def one(self):
        return self._value

    def all(self):
        return []


class _FakeMappingResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeTTFSession:
    def __init__(self) -> None:
        self.lock_available = True
        self.programmes: list[dict] = [
            {
                "code": "DR",
                "r_year_required": True,
                "is_subspecialty": False,
            },
            {
                "code": "GERI",
                "r_year_required": False,
                "is_subspecialty": False,
            },
            {
                "code": "XALL",
                "r_year_required": False,
                "is_subspecialty": False,
            },
            {
                "code": "XSS",
                "r_year_required": True,
                "is_subspecialty": True,
            },
        ]
        self.session_types: dict[str, dict] = {}
        self.posting_codes: dict[str, dict] = {}
        self.teaching_targets: list[dict] = []
        self.catalogue_rows: list[dict] = []
        self.posting_groups: dict[tuple[str, str], dict] = {}
        self.teaching_events: dict[str, dict] = {}
        self.attendance_records: list[dict] = []
        self.upload_logs: list[dict] = []
        self.audit_logs: list[dict] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params: dict | None = None):
        sql = str(statement)
        params = dict(params or {})

        if "pg_try_advisory_xact_lock" in sql:
            return _FakeScalarResult(self.lock_available)

        if "FROM programmes" in sql:
            return _FakeMappingResult(self.programmes)

        if "INSERT INTO session_types" in sql:
            name = params["name"]
            row = self.session_types.get(name)
            if row is None:
                row = {"id": str(uuid4()), "name": name}
            row["duration_hours"] = params["duration_hours"]
            row["duration_label"] = params["duration_label"]
            self.session_types[name] = row
            return _FakeScalarResult()

        if "SELECT id, name FROM session_types" in sql:
            names = set(params["names"])
            return _FakeMappingResult(
                [
                    {"id": row["id"], "name": row["name"]}
                    for row in self.session_types.values()
                    if row["name"] in names
                ]
            )

        if "SELECT code FROM posting_codes" in sql:
            codes = set(params["codes"])
            return _FakeMappingResult(
                [{"code": code} for code in self.posting_codes if code in codes]
            )

        if "INSERT INTO posting_codes" in sql:
            code = params["code"]
            self.posting_codes.setdefault(code, {"code": code, "display_name": None})
            return _FakeScalarResult()

        if "DELETE FROM teaching_name_catalogue" in sql:
            rp = str(params["reporting_period_id"])
            prog = params["programme_code"]
            self.catalogue_rows = [
                row
                for row in self.catalogue_rows
                if not (row["reporting_period_id"] == rp and row["programme_code"] == prog)
            ]
            return _FakeScalarResult()

        if "DELETE FROM teaching_targets" in sql:
            rp = str(params["reporting_period_id"])
            prog = params["programme_code"]
            self.teaching_targets = [
                row
                for row in self.teaching_targets
                if not (row["reporting_period_id"] == rp and row["programme_code"] == prog)
            ]
            return _FakeScalarResult()

        if "INSERT INTO teaching_targets" in sql:
            self.teaching_targets.append(
                {
                    "reporting_period_id": str(params["reporting_period_id"]),
                    "programme_code": params["programme_code"],
                    "r_year": params["r_year"],
                    "posting_code": params["posting_code"],
                    "session_type_id": str(params["session_type_id"]),
                    "monthly_target": params["monthly_target"],
                    "is_tracked": params["is_tracked"],
                    "is_reallocatable": params["is_reallocatable"],
                    "tag": params["tag"],
                    "details_of_training": params["details_of_training"],
                }
            )
            return _FakeScalarResult()

        if "INSERT INTO teaching_name_catalogue" in sql:
            self.catalogue_rows.append(
                {
                    "keyword": params["keyword"],
                    "session_type_id": str(params["session_type_id"]),
                    "posting_code": params["posting_code"],
                    "programme_code": params["programme_code"],
                    "r_year": params["r_year"],
                    "reporting_period_id": str(params["reporting_period_id"]),
                    "duration_hours": params["duration_hours"],
                    "is_tracked": params["is_tracked"],
                }
            )
            return _FakeScalarResult()

        if "INSERT INTO posting_groups" in sql:
            key = (params["posting_code"], params["programme_code"])
            self.posting_groups[key] = {
                "group_code": params["group_code"],
                "posting_code": params["posting_code"],
                "programme_code": params["programme_code"],
            }
            return _FakeScalarResult()

        if "SELECT COUNT(*) AS orphan_count" in sql:
            rp = str(params["reporting_period_id"])
            prog = params["programme_code"]
            catalogue_pairs = {
                (row["keyword"], row["posting_code"])
                for row in self.catalogue_rows
                if row["reporting_period_id"] == rp and row["programme_code"] == prog
            }
            orphan_count = 0
            for attendance in self.attendance_records:
                event = self.teaching_events.get(attendance["teaching_event_id"])
                if event is None:
                    continue
                pair = (event["teaching_name"], event["posting_code"])
                if pair not in catalogue_pairs:
                    orphan_count += 1
            return _FakeScalarResult(orphan_count)

        if "INSERT INTO upload_logs" in sql:
            self.upload_logs.append(dict(params))
            return _FakeScalarResult()

        if "INSERT INTO audit_logs" in sql:
            self.audit_logs.append(dict(params))
            return _FakeScalarResult(dict(params))

        raise AssertionError(f"Unhandled SQL: {sql}")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _run(coro):
    return asyncio.run(coro)


def _ttf_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "TTF"
    headers = [
        "reporting_period",
        "programme_code",
        "r_year",
        "posting_code",
        "dashboard_posting",
        "session_type",
        "monthly_target",
        "is_tracked",
        "is_reallocatable",
        "tag",
        "details_of_training",
    ]
    for idx, header in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=header)
    for r_idx, row in enumerate(rows, start=2):
        for c_idx, value in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=value)
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


def _base_row(**overrides: object) -> list[object]:
    row = [
        "Jan - June",
        "DR",
        "R2",
        "TTSHDiagRd",
        "",
        "Department Learning Events [1h]",
        7,
        "Yes",
        "N",
        "",
        "Journal Club, Bedside Teaching",
    ]
    mapping = {
        "programme": 1,
        "r_year": 2,
        "posting": 3,
        "group": 4,
        "session_type": 5,
        "monthly_target": 6,
        "is_tracked": 7,
        "is_reallocatable": 8,
        "tag": 9,
        "details": 10,
    }
    for key, value in overrides.items():
        row[mapping[key]] = value
    return row


def test_parse_only_mode_still_works_without_db_writes() -> None:
    result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row()]),
            original_filename="ttf.xlsx",
            reporting_period_id=uuid4(),
            programme_code="DR",
            db_session=None,
        )
    )
    assert result.errors == []
    assert result.metadata["counts"]["targets"] == 1
    assert result.metadata["targets_created"] == 0


def test_valid_sample_persists_targets_session_types_posting_codes_and_catalogue() -> None:
    session = FakeTTFSession()
    period_id = uuid4()
    rows = [
        _base_row(posting="TTSHDiagRd", session_type="Department Learning Events [1h]"),
        _base_row(posting="DormantCode123", session_type="National Teaching [3h]", details="Grand Round"),
    ]
    result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes(rows),
            original_filename="ttf.xlsx",
            reporting_period_id=period_id,
            programme_code="DR",
            db_session=session,
        )
    )
    assert result.errors == []
    assert len(session.teaching_targets) == 2
    assert len(session.catalogue_rows) == 3
    assert "Department Learning Events [1h]" in session.session_types
    assert "DormantCode123" in session.posting_codes
    assert "DormantCode123" in result.metadata["posting_codes_added"]


def test_db_programme_config_drives_all_and_subspecialty_years_for_custom_programmes() -> None:
    session = FakeTTFSession()
    period_id = uuid4()
    all_result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes(
                [_base_row(programme="XALL", r_year="R2,R3", details="All Topic")]
            ),
            original_filename="xall.xlsx",
            reporting_period_id=period_id,
            programme_code="XALL",
            db_session=session,
        )
    )
    ss_result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes(
                [_base_row(programme="XSS", r_year="R4, R5, R6", details="SS Topic")]
            ),
            original_filename="xss.xlsx",
            reporting_period_id=period_id,
            programme_code="XSS",
            db_session=session,
        )
    )

    assert all_result.errors == []
    assert ss_result.errors == []
    assert [
        row["r_year"] for row in session.teaching_targets if row["programme_code"] == "XALL"
    ] == ["ALL"]
    assert [
        row["r_year"] for row in session.catalogue_rows if row["programme_code"] == "XALL"
    ] == ["ALL"]
    assert [
        row["r_year"] for row in session.teaching_targets if row["programme_code"] == "XSS"
    ] == ["SS1", "SS2", "SS3"]


def test_reupload_replaces_only_selected_programme_period_scope() -> None:
    session = FakeTTFSession()
    p1 = uuid4()
    p2 = uuid4()
    _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(programme="DR", posting="P1", details="K1")]),
            original_filename="a.xlsx",
            reporting_period_id=p1,
            programme_code="DR",
            db_session=session,
        )
    )
    _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(programme="GERI", posting="OTHER", details="K2")]),
            original_filename="b.xlsx",
            reporting_period_id=p1,
            programme_code="GERI",
            db_session=session,
        )
    )
    _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(programme="DR", posting="P2", details="K3")]),
            original_filename="c.xlsx",
            reporting_period_id=p1,
            programme_code="DR",
            db_session=session,
        )
    )
    _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(programme="DR", posting="P3", details="K4")]),
            original_filename="d.xlsx",
            reporting_period_id=p2,
            programme_code="DR",
            db_session=session,
        )
    )

    assert any(
        row["reporting_period_id"] == str(p1) and row["programme_code"] == "DR" and row["posting_code"] == "P2"
        for row in session.teaching_targets
    )
    assert not any(
        row["reporting_period_id"] == str(p1) and row["programme_code"] == "DR" and row["posting_code"] == "P1"
        for row in session.teaching_targets
    )
    assert any(row["programme_code"] == "GERI" for row in session.teaching_targets)
    assert any(row["reporting_period_id"] == str(p2) and row["programme_code"] == "DR" for row in session.teaching_targets)


def test_existing_attendance_does_not_block_and_orphan_warning_returned() -> None:
    session = FakeTTFSession()
    period_id = uuid4()
    event_id = str(uuid4())
    session.teaching_events[event_id] = {"teaching_name": "Old Topic", "posting_code": "TTSHDiagRd"}
    session.attendance_records.append({"teaching_event_id": event_id})

    result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(details="New Topic")]),
            original_filename="ttf.xlsx",
            reporting_period_id=period_id,
            programme_code="DR",
            db_session=session,
        )
    )
    assert result.errors == []
    warnings = [w for w in result.warnings if isinstance(w, dict)]
    orphan = [w for w in warnings if w.get("type") == "orphaned_attendance"]
    assert orphan and orphan[0]["count"] == 1


def test_non_tracked_rows_persist_with_false_flags() -> None:
    session = FakeTTFSession()
    result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(is_tracked="No")]),
            original_filename="ttf.xlsx",
            reporting_period_id=uuid4(),
            programme_code="DR",
            db_session=session,
        )
    )
    assert result.errors == []
    assert all(row["is_tracked"] is False for row in session.teaching_targets)
    assert all(row["is_tracked"] is False for row in session.catalogue_rows)


def test_posting_groups_seed_and_update_from_column_e() -> None:
    session = FakeTTFSession()
    period_id = uuid4()
    _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(posting="TTSHDiagRd", group="GROUP_A")]),
            original_filename="ttf.xlsx",
            reporting_period_id=period_id,
            programme_code="DR",
            db_session=session,
        )
    )
    _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(posting="TTSHDiagRd", group="GROUP_B")]),
            original_filename="ttf2.xlsx",
            reporting_period_id=period_id,
            programme_code="DR",
            db_session=session,
        )
    )
    assert session.posting_groups[("TTSHDiagRd", "DR")]["group_code"] == "GROUP_B"


def test_validation_error_prevents_any_db_writes_even_with_db_session() -> None:
    session = FakeTTFSession()
    result = _run(
        parse_ttf_upload(
            file_bytes=_ttf_bytes([_base_row(details="")]),
            original_filename="ttf.xlsx",
            reporting_period_id=uuid4(),
            programme_code="DR",
            db_session=session,
        )
    )
    assert result.errors
    assert session.teaching_targets == []
    assert session.catalogue_rows == []
    assert session.posting_groups == {}


def test_upload_route_uses_db_session_writes_upload_log_and_maps_lock_to_409() -> None:
    session = FakeTTFSession()
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    client = TestClient(app)
    period_id = uuid4()
    body_rows = [_base_row(posting="TTSHDiagRd", details="Journal Club")]
    payload = _ttf_bytes(body_rows)

    response = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR",
            "X-Actor-Name": "Dr Lee",
        },
        data={"reporting_period_id": str(period_id), "programme_code": "DR"},
        files={
            "file": (
                "ttf.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200
    assert session.teaching_targets
    assert session.upload_logs
    summary = json.loads(session.upload_logs[-1]["summary"])
    assert summary["upload_type"] == "ttf"

    session.lock_available = False
    response_409 = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR",
            "X-Actor-Name": "Dr Lee",
        },
        data={"reporting_period_id": str(period_id), "programme_code": "DR"},
        files={
            "file": (
                "ttf.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response_409.status_code == 409
