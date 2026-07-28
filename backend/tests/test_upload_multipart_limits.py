from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI, File, Form, UploadFile
from fastapi.testclient import TestClient
from starlette import formparsers

from app.routers import admin
from app.routers.upload_multipart import (
    BoundedAdminUploadRoute,
    MAX_UPLOAD_FILENAME_BYTES,
    MAX_UPLOAD_FORM_FIELD_BYTES,
    UPLOAD_MAX_FORM_FIELDS_BY_PATH,
    bounded_admin_upload,
)


_UPLOAD_PATHS = tuple(UPLOAD_MAX_FORM_FIELDS_BY_PATH)
_XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@pytest.fixture
def upload_client() -> Iterator[tuple[TestClient, dict[str, int]]]:
    calls = dict.fromkeys(_UPLOAD_PATHS, 0)
    router = APIRouter(
        prefix="/admin",
        route_class=BoundedAdminUploadRoute,
    )

    @router.post("/upload/rdb")
    @bounded_admin_upload("/admin/upload/rdb")
    async def upload_rdb(
        file: Annotated[UploadFile, File()],
        reporting_period_id: Annotated[str, Form()],
    ) -> dict[str, int]:
        calls["/admin/upload/rdb"] += 1
        return {"size": len(await file.read())}

    @router.post("/upload/ttf")
    @bounded_admin_upload("/admin/upload/ttf")
    async def upload_ttf(
        file: Annotated[UploadFile, File()],
        reporting_period_id: Annotated[str, Form()],
        programme_code: Annotated[str, Form()],
    ) -> dict[str, int]:
        calls["/admin/upload/ttf"] += 1
        return {"size": len(await file.read())}

    @router.post("/upload/form-f1")
    @bounded_admin_upload("/admin/upload/form-f1")
    async def upload_form_f1(
        file: Annotated[UploadFile, File()],
        reporting_period_id: Annotated[str, Form()],
    ) -> dict[str, int]:
        calls["/admin/upload/form-f1"] += 1
        return {"size": len(await file.read())}

    @router.post("/upload/public-holidays")
    @bounded_admin_upload("/admin/upload/public-holidays")
    async def upload_public_holidays(
        file: Annotated[UploadFile, File()],
    ) -> dict[str, int]:
        calls["/admin/upload/public-holidays"] += 1
        return {"size": len(await file.read())}

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, calls


def _file_part(
    *,
    filename: str = "upload.xlsx",
    payload: bytes = b"workbook",
) -> tuple[str, bytes, str]:
    return filename, payload, _XLSX_CONTENT_TYPE


def _assert_controlled_rejection(response) -> None:  # noqa: ANN001
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Upload file validation failed",
        "error_code": "FILE_VALIDATION_FAILED",
        "errors": [],
        "warnings": [],
        "metadata": {},
    }
    assert response.headers["cache-control"] == "no-store, private, max-age=0"


def test_admin_upload_routes_have_route_specific_preparse_limits() -> None:
    routes_by_path = {
        route.path: route
        for route in admin.router.routes
        if isinstance(route, BoundedAdminUploadRoute)
    }

    for path, max_fields in UPLOAD_MAX_FORM_FIELDS_BY_PATH.items():
        route = routes_by_path[path]
        assert route.multipart_max_fields == max_fields


def test_similar_unmarked_path_is_not_treated_as_an_upload_route() -> None:
    router = APIRouter(route_class=BoundedAdminUploadRoute)

    @router.post("/lookalike/admin/upload/rdb")
    async def lookalike() -> None:
        return None

    route = router.routes[0]
    assert isinstance(route, BoundedAdminUploadRoute)
    assert route.multipart_max_fields is None


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/admin/upload/rdb", {"reporting_period_id": "period-1"}),
        (
            "/admin/upload/ttf",
            {
                "reporting_period_id": "period-1",
                "programme_code": "DR",
            },
        ),
        ("/admin/upload/form-f1", {"reporting_period_id": "period-1"}),
        ("/admin/upload/public-holidays", {}),
    ],
)
def test_valid_uploads_reach_the_handler(
    upload_client: tuple[TestClient, dict[str, int]],
    path: str,
    data: dict[str, str],
) -> None:
    client, calls = upload_client

    response = client.post(
        path,
        data=data,
        files={"file": _file_part()},
    )

    assert response.status_code == 200
    assert response.json() == {"size": len(b"workbook")}
    assert calls[path] == 1


def test_second_file_is_rejected_before_the_handler(
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, calls = upload_client
    path = "/admin/upload/rdb"

    response = client.post(
        path,
        data={"reporting_period_id": "period-1"},
        files=[
            ("file", _file_part(filename="first.xlsx")),
            ("extra", _file_part(filename="second.xlsx")),
        ],
    )

    _assert_controlled_rejection(response)
    assert calls[path] == 0


@pytest.mark.parametrize(
    ("path", "data"),
    [
        (
            "/admin/upload/rdb",
            {"reporting_period_id": "period-1", "extra": "unexpected"},
        ),
        (
            "/admin/upload/ttf",
            {
                "reporting_period_id": "period-1",
                "programme_code": "DR",
                "extra": "unexpected",
            },
        ),
        (
            "/admin/upload/form-f1",
            {"reporting_period_id": "period-1", "extra": "unexpected"},
        ),
        ("/admin/upload/public-holidays", {"extra": "unexpected"}),
    ],
)
def test_extra_form_field_is_rejected_before_the_handler(
    upload_client: tuple[TestClient, dict[str, int]],
    path: str,
    data: dict[str, str],
) -> None:
    client, calls = upload_client

    response = client.post(path, data=data, files={"file": _file_part()})

    _assert_controlled_rejection(response)
    assert calls[path] == 0


def test_oversized_non_file_part_is_rejected_before_the_handler(
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, calls = upload_client
    path = "/admin/upload/rdb"

    response = client.post(
        path,
        data={
            "reporting_period_id": "x" * (MAX_UPLOAD_FORM_FIELD_BYTES + 1),
        },
        files={"file": _file_part()},
    )

    _assert_controlled_rejection(response)
    assert calls[path] == 0


def test_oversized_utf8_filename_is_rejected_without_echoing_it(
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, calls = upload_client
    path = "/admin/upload/public-holidays"
    filename = ("é" * (MAX_UPLOAD_FILENAME_BYTES // 2)) + ".xlsx"
    assert len(filename.encode("utf-8")) > MAX_UPLOAD_FILENAME_BYTES

    response = client.post(
        path,
        files={"file": _file_part(filename=filename)},
    )

    _assert_controlled_rejection(response)
    assert filename not in response.text
    assert calls[path] == 0


def test_file_payload_larger_than_form_part_limit_remains_valid(
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, calls = upload_client
    path = "/admin/upload/public-holidays"
    payload = b"x" * (MAX_UPLOAD_FORM_FIELD_BYTES + 1)

    response = client.post(
        path,
        files={"file": _file_part(payload=payload)},
    )

    assert response.status_code == 200
    assert response.json() == {"size": len(payload)}
    assert calls[path] == 1


@pytest.mark.parametrize(
    ("filename", "expected_status"),
    [
        ("valid.xlsx", 200),
        (("\u00e9" * (MAX_UPLOAD_FILENAME_BYTES // 2)) + ".xlsx", 422),
    ],
)
def test_parsed_temporary_files_are_closed(
    monkeypatch: pytest.MonkeyPatch,
    upload_client: tuple[TestClient, dict[str, int]],
    filename: str,
    expected_status: int,
) -> None:
    client, _ = upload_client
    real_spooled_temporary_file = formparsers.SpooledTemporaryFile
    temporary_files = []

    def tracking_spooled_temporary_file(*args, **kwargs):  # noqa: ANN002, ANN003
        temporary_file = real_spooled_temporary_file(*args, **kwargs)
        temporary_files.append(temporary_file)
        return temporary_file

    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        tracking_spooled_temporary_file,
    )

    response = client.post(
        "/admin/upload/public-holidays",
        files={"file": _file_part(filename=filename)},
    )

    assert response.status_code == expected_status
    assert temporary_files
    assert all(temporary_file.closed for temporary_file in temporary_files)


def test_parser_limit_rejection_closes_temporary_files(
    monkeypatch: pytest.MonkeyPatch,
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, _ = upload_client
    real_spooled_temporary_file = formparsers.SpooledTemporaryFile
    temporary_files = []

    def tracking_spooled_temporary_file(*args, **kwargs):  # noqa: ANN002, ANN003
        temporary_file = real_spooled_temporary_file(*args, **kwargs)
        temporary_files.append(temporary_file)
        return temporary_file

    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        tracking_spooled_temporary_file,
    )

    response = client.post(
        "/admin/upload/rdb",
        data={"reporting_period_id": "period-1"},
        files=[
            ("file", _file_part(filename="first.xlsx")),
            ("extra", _file_part(filename="second.xlsx")),
        ],
    )

    _assert_controlled_rejection(response)
    assert temporary_files
    assert all(temporary_file.closed for temporary_file in temporary_files)


def test_malformed_multipart_after_spool_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, calls = upload_client
    real_spooled_temporary_file = formparsers.SpooledTemporaryFile
    temporary_files = []

    def tracking_spooled_temporary_file(*args, **kwargs):  # noqa: ANN002, ANN003
        temporary_file = real_spooled_temporary_file(*args, **kwargs)
        temporary_files.append(temporary_file)
        return temporary_file

    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        tracking_spooled_temporary_file,
    )
    malformed_body = (
        b"--bounded\r\n"
        b'Content-Disposition: form-data; name="file"; filename="upload.xlsx"\r\n'
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
        b"workbook-data"
        b"\r\n--bounded\r\n"
        b'Content-Disposition: form-data; name="extra"\rX'
    )

    response = client.post(
        "/admin/upload/public-holidays",
        content=malformed_body,
        headers={"Content-Type": "multipart/form-data; boundary=bounded"},
    )

    _assert_controlled_rejection(response)
    assert calls["/admin/upload/public-holidays"] == 0
    assert temporary_files
    assert all(temporary_file.closed for temporary_file in temporary_files)


def test_unrelated_oserror_is_not_converted_to_a_validation_response(
    monkeypatch: pytest.MonkeyPatch,
    upload_client: tuple[TestClient, dict[str, int]],
) -> None:
    client, calls = upload_client

    def fail_spooled_temporary_file(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("simulated storage failure")

    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        fail_spooled_temporary_file,
    )

    with pytest.raises(OSError, match="simulated storage failure"):
        client.post(
            "/admin/upload/public-holidays",
            files={"file": _file_part()},
        )

    assert calls["/admin/upload/public-holidays"] == 0
