from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, File, UploadFile
from starlette import formparsers
from starlette import requests as starlette_requests
from starlette.types import Message, Receive, Scope, Send

from app.middleware.request_body_limit import (
    DEFAULT_GLOBAL_BODY_LIMIT_BYTES,
    DEFAULT_UPLOAD_BODY_LIMIT_BYTES,
    MEBIBYTE,
    RequestBodyLimitMiddleware,
)
from app.routers.upload_multipart import (
    BoundedAdminUploadRoute,
    bounded_admin_upload,
)


AsgiCallable = Callable[[Scope, Receive, Send], Awaitable[None]]


def _http_scope(
    *,
    path: str = "/api/v1/example",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": headers or [],
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 50000),
    }


async def _send_empty_response(send: Send, *, status_code: int = 204) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _invoke(
    app: AsgiCallable,
    *,
    scope: Scope | None = None,
    messages: list[Message] | None = None,
    receive_override: Receive | None = None,
) -> tuple[list[Message], int]:
    queued_messages = list(messages or [])
    receive_calls = 0

    async def receive() -> Message:
        nonlocal receive_calls
        receive_calls += 1
        if queued_messages:
            return queued_messages.pop(0)
        return {"type": "http.disconnect"}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(
        scope or _http_scope(),
        receive_override or receive,
        send,
    )
    return sent, receive_calls


def _status(messages: list[Message]) -> int:
    starts = [
        message
        for message in messages
        if message["type"] == "http.response.start"
    ]
    assert len(starts) == 1
    return int(starts[0]["status"])


def _headers(messages: list[Message]) -> dict[bytes, bytes]:
    start = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )
    return dict(start["headers"])


def _json_body(messages: list[Message]) -> dict[str, Any]:
    payload = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return json.loads(payload)


def _request_message(body: bytes, *, more_body: bool) -> Message:
    return {
        "type": "http.request",
        "body": body,
        "more_body": more_body,
    }


@pytest.mark.asyncio
async def test_known_oversized_content_length_never_invokes_downstream_or_receive() -> None:
    downstream_called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True
        raise AssertionError("known oversized request must not reach downstream")

    async def unexpected_receive() -> Message:
        raise AssertionError("known oversized request must not read the body")

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(headers=[(b"content-length", b"9")]),
        receive_override=unexpected_receive,
    )

    assert _status(messages) == 413
    assert downstream_called is False
    assert _headers(messages)[b"cache-control"] == b"no-store"
    assert _json_body(messages)["error_code"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_known_oversized_multipart_never_constructs_parser_or_spool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_called = False

    async def unexpected_parser(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("known oversized multipart must not construct a parser")

    def unexpected_spool(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("known oversized multipart must not construct a spool")

    monkeypatch.setattr(
        starlette_requests,
        "MultiPartParser",
        unexpected_parser,
    )
    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        unexpected_spool,
    )

    app = FastAPI()

    @app.post("/api/v1/admin/upload/rdb")
    async def upload_route(file: UploadFile = File(...)) -> dict[str, bool]:
        nonlocal route_called
        route_called = True
        return {"called": True}

    limiter = RequestBodyLimitMiddleware(
        app,
        global_limit_bytes=128,
        upload_limit_bytes=96,
    )
    messages, receive_calls = await _invoke(
        limiter,
        scope=_http_scope(
            path="/api/v1/admin/upload/rdb",
            headers=[
                (b"content-type", b"multipart/form-data; boundary=bounded"),
                (b"content-length", b"97"),
            ],
        ),
    )

    assert _status(messages) == 413
    assert receive_calls == 0
    assert route_called is False


@pytest.mark.asyncio
async def test_exact_declared_and_streamed_boundary_is_allowed_without_copying() -> None:
    original_body = b"12345678"
    received_body: bytes | None = None

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal received_body
        message = await receive()
        received_body = message["body"]
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(headers=[(b"content-length", b"8")]),
        messages=[_request_message(original_body, more_body=False)],
    )

    assert _status(messages) == 204
    assert received_body is original_body


@pytest.mark.asyncio
async def test_declared_boundary_plus_one_is_rejected_before_downstream() -> None:
    downstream_called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, receive_calls = await _invoke(
        limiter,
        scope=_http_scope(headers=[(b"content-length", b"9")]),
    )

    assert _status(messages) == 413
    assert receive_calls == 0
    assert downstream_called is False


@pytest.mark.asyncio
async def test_default_exact_four_mebibyte_boundary_is_allowed() -> None:
    body = b"x" * DEFAULT_GLOBAL_BODY_LIMIT_BYTES
    received_same_body = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal received_same_body
        received_same_body = (await receive())["body"] is body
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(downstream)
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(
            headers=[
                (
                    b"content-length",
                    str(DEFAULT_GLOBAL_BODY_LIMIT_BYTES).encode("ascii"),
                )
            ]
        ),
        messages=[_request_message(body, more_body=False)],
    )

    assert DEFAULT_GLOBAL_BODY_LIMIT_BYTES == 4 * MEBIBYTE
    assert _status(messages) == 204
    assert received_same_body is True


@pytest.mark.asyncio
async def test_default_upload_path_exact_four_mebibyte_boundary_is_allowed() -> None:
    body = b"x" * DEFAULT_UPLOAD_BODY_LIMIT_BYTES
    received_same_body = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal received_same_body
        received_same_body = (await receive())["body"] is body
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(downstream)
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(
            path="/api/v1/admin/upload/rdb",
            headers=[
                (
                    b"content-length",
                    str(DEFAULT_UPLOAD_BODY_LIMIT_BYTES).encode("ascii"),
                )
            ],
        ),
        messages=[_request_message(body, more_body=False)],
    )

    assert DEFAULT_UPLOAD_BODY_LIMIT_BYTES == 4 * MEBIBYTE
    assert _status(messages) == 204
    assert received_same_body is True


@pytest.mark.asyncio
async def test_default_four_mebibyte_boundary_plus_one_is_rejected_early() -> None:
    downstream_called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    limiter = RequestBodyLimitMiddleware(downstream)
    messages, receive_calls = await _invoke(
        limiter,
        scope=_http_scope(
            headers=[
                (
                    b"content-length",
                    str(DEFAULT_GLOBAL_BODY_LIMIT_BYTES + 1).encode("ascii"),
                )
            ]
        ),
    )

    assert _status(messages) == 413
    assert receive_calls == 0
    assert downstream_called is False


@pytest.mark.asyncio
async def test_default_stream_without_content_length_crosses_four_mebibytes() -> None:
    accepted_chunk = b"x" * MEBIBYTE
    received_chunk_count = 0

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal received_chunk_count
        while True:
            message = await receive()
            received_chunk_count += 1
            if not message.get("more_body", False):
                break
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(downstream)
    messages, receive_calls = await _invoke(
        limiter,
        messages=[
            *[
                _request_message(accepted_chunk, more_body=True)
                for _ in range(4)
            ],
            _request_message(b"y", more_body=False),
        ],
    )

    assert DEFAULT_GLOBAL_BODY_LIMIT_BYTES == 4 * len(accepted_chunk)
    assert _status(messages) == 413
    assert receive_calls == 5
    assert received_chunk_count == 4


@pytest.mark.asyncio
async def test_missing_content_length_is_enforced_on_crossing_chunk() -> None:
    received_chunks: list[bytes] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            received_chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, receive_calls = await _invoke(
        limiter,
        messages=[
            _request_message(b"12345", more_body=True),
            _request_message(b"6789", more_body=True),
        ],
    )

    assert _status(messages) == 413
    assert receive_calls == 2
    assert received_chunks == [b"12345"]


@pytest.mark.asyncio
async def test_falsely_small_content_length_cannot_bypass_stream_counting() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(headers=[(b"content-length", b"1")]),
        messages=[
            _request_message(b"1234", more_body=True),
            _request_message(b"5", more_body=False),
        ],
    )

    assert _status(messages) == 413


@pytest.mark.asyncio
async def test_crossing_on_final_chunk_is_rejected() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )
    messages, _ = await _invoke(
        limiter,
        messages=[
            _request_message(b"1234", more_body=True),
            _request_message(b"5", more_body=False),
        ],
    )

    assert _status(messages) == 413


@pytest.mark.parametrize(
    "raw_value",
    [
        b"",
        b"-1",
        b"+1",
        b"1.0",
        b"1,,1",
        b"1,",
        b"\xff",
        b"9" * 21,
    ],
)
@pytest.mark.asyncio
async def test_malformed_content_length_is_safe_no_store_400(raw_value: bytes) -> None:
    downstream_called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, receive_calls = await _invoke(
        limiter,
        scope=_http_scope(headers=[(b"content-length", raw_value)]),
    )

    assert _status(messages) == 400
    assert receive_calls == 0
    assert downstream_called is False
    assert _headers(messages)[b"cache-control"] == b"no-store"
    assert _json_body(messages) == {
        "detail": "Invalid Content-Length header",
        "error_code": "VALIDATION_FAILED",
        "errors": [],
        "warnings": [],
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_conflicting_duplicate_content_lengths_are_rejected() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError("conflicting lengths must not reach downstream")

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, receive_calls = await _invoke(
        limiter,
        scope=_http_scope(
            headers=[
                (b"content-length", b"4"),
                (b"Content-Length", b"5"),
            ]
        ),
    )

    assert _status(messages) == 400
    assert receive_calls == 0


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"4"), (b"content-length", b"4")],
        [(b"content-length", b"4, 4")],
        [(b"content-length", b"04"), (b"content-length", b"4")],
    ],
)
@pytest.mark.asyncio
async def test_equivalent_duplicate_content_lengths_are_accepted(
    headers: list[tuple[bytes, bytes]],
) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        assert (await receive())["body"] == b"1234"
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(headers=headers),
        messages=[_request_message(b"1234", more_body=False)],
    )

    assert _status(messages) == 204


@pytest.mark.asyncio
async def test_upload_path_uses_narrower_limit_and_safe_upload_envelope() -> None:
    downstream_calls = 0

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1
        await receive()
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=12,
        upload_limit_bytes=11,
        api_prefix="/api/v1/",
    )

    upload_messages, _ = await _invoke(
        limiter,
        scope=_http_scope(
            path="/api/v1/admin/upload/rdb",
            headers=[(b"content-length", b"12")],
        ),
    )
    json_messages, _ = await _invoke(
        limiter,
        scope=_http_scope(
            path="/api/v1/auth/login",
            headers=[
                (b"content-length", b"12"),
                (b"content-type", b"application/json"),
            ],
        ),
        messages=[_request_message(b"x" * 12, more_body=False)],
    )

    assert _status(upload_messages) == 413
    assert _json_body(upload_messages)["error_code"] == "FILE_VALIDATION_FAILED"
    assert _json_body(upload_messages)["detail"] == (
        "Upload request exceeds maximum allowed size"
    )
    assert _status(json_messages) == 204
    assert downstream_calls == 1


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/v1/admin/upload/form-f1", 413),
        ("/api/v1/admin/upload/public-holidays/", 413),
        ("/api/v1/admin/upload/ttf", 413),
        ("/api/v1/admin/upload-warnings", 204),
        ("/api/v10/admin/upload/rdb", 204),
    ],
)
@pytest.mark.asyncio
async def test_upload_path_matching_is_prefix_bounded(
    path: str,
    expected_status: int,
) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(
            path=path,
            headers=[(b"content-length", b"7")],
        ),
        messages=[_request_message(b"1234567", more_body=False)],
    )

    assert _status(messages) == expected_status


@pytest.mark.parametrize(
    "content_type",
    [b"application/json", b"application/x-www-form-urlencoded"],
)
@pytest.mark.asyncio
async def test_global_limit_protects_json_and_form_bodies(content_type: bytes) -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(headers=[(b"content-type", content_type)]),
        messages=[
            _request_message(b"1234", more_body=True),
            _request_message(b"5", more_body=False),
        ],
    )

    assert _status(messages) == 413


@pytest.mark.asyncio
async def test_stream_overflow_uses_oserror_cleanup_path_and_replaces_error() -> None:
    cleanup_ran = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal cleanup_ran
        try:
            while True:
                message = await receive()
                if not message.get("more_body", False):
                    break
        except OSError:
            cleanup_ran = True
            await _send_empty_response(send, status_code=400)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )
    messages, _ = await _invoke(
        limiter,
        messages=[
            _request_message(b"1234", more_body=True),
            _request_message(b"5", more_body=False),
        ],
    )

    assert cleanup_ran is True
    assert _status(messages) == 413


@pytest.mark.asyncio
async def test_stream_overflow_after_response_start_propagates_abort() -> None:
    response_started = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal response_started
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        response_started = True
        await receive()

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )

    with pytest.raises(OSError):
        await _invoke(
            limiter,
            messages=[_request_message(b"12345", more_body=False)],
        )
    assert response_started is True


@pytest.mark.asyncio
async def test_streaming_multipart_overflow_closes_spool_and_replaces_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_spools: list[Any] = []
    route_called = False
    real_spooled_temporary_file = formparsers.SpooledTemporaryFile

    def tracking_spool(*args: Any, **kwargs: Any):
        spool = real_spooled_temporary_file(*args, **kwargs)
        created_spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers.MultiPartParser, "spool_max_size", 16)
    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        tracking_spool,
    )

    router = APIRouter(
        prefix="/admin",
        route_class=BoundedAdminUploadRoute,
    )

    @router.post("/upload/rdb")
    @bounded_admin_upload("/admin/upload/rdb")
    async def upload_route(file: UploadFile = File(...)) -> dict[str, bool]:
        nonlocal route_called
        route_called = True
        return {"called": True}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    multipart_prefix = (
        b"--bounded\r\n"
        b'Content-Disposition: form-data; name="file"; filename="bounded.xlsx"\r\n'
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
    )
    accepted_chunk = multipart_prefix + (b"x" * 64)
    body_limit = len(accepted_chunk)
    limiter = RequestBodyLimitMiddleware(
        app,
        global_limit_bytes=body_limit,
        upload_limit_bytes=body_limit,
    )
    messages, receive_calls = await _invoke(
        limiter,
        scope=_http_scope(
            path="/api/v1/admin/upload/rdb",
            headers=[
                (b"content-type", b"multipart/form-data; boundary=bounded"),
            ],
        ),
        messages=[
            _request_message(accepted_chunk, more_body=True),
            _request_message(b"y", more_body=False),
        ],
    )

    assert _status(messages) == 413
    assert receive_calls == 2
    assert route_called is False
    assert len(created_spools) == 1
    assert created_spools[0]._rolled is True
    assert created_spools[0].closed is True


@pytest.mark.asyncio
async def test_controlled_413_contains_no_request_or_internal_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_marker = "private-filename-M12345A-secret-token"
    caplog.set_level("DEBUG")

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError("known oversized body must not reach downstream")

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, _ = await _invoke(
        limiter,
        scope=_http_scope(
            path="/api/v1/admin/upload/rdb",
            headers=[
                (b"content-length", b"7"),
                (b"x-sensitive-test-marker", sensitive_marker.encode()),
            ],
        ),
    )
    response_text = json.dumps(_json_body(messages))

    assert _status(messages) == 413
    assert sensitive_marker not in response_text
    assert sensitive_marker not in caplog.text
    assert not [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_body_limit"
    ]
    assert "traceback" not in response_text.casefold()
    assert "temporary" not in response_text.casefold()


@pytest.mark.asyncio
async def test_client_disconnect_passes_through_without_becoming_413() -> None:
    saw_disconnect = False
    teardown_ran = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal saw_disconnect, teardown_ran
        try:
            assert (await receive())["type"] == "http.request"
            saw_disconnect = (await receive())["type"] == "http.disconnect"
            await _send_empty_response(send, status_code=400)
        finally:
            teardown_ran = True

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )
    messages, _ = await _invoke(
        limiter,
        messages=[
            _request_message(b"1234", more_body=True),
            {"type": "http.disconnect"},
        ],
    )

    assert saw_disconnect is True
    assert teardown_ran is True
    assert _status(messages) == 400


@pytest.mark.asyncio
async def test_cancellation_propagates_and_runs_downstream_teardown() -> None:
    teardown_ran = False

    async def cancelled_receive() -> Message:
        raise asyncio.CancelledError

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal teardown_ran
        try:
            await receive()
        finally:
            teardown_ran = True

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )

    with pytest.raises(asyncio.CancelledError):
        await _invoke(limiter, receive_override=cancelled_receive)
    assert teardown_ran is True


@pytest.mark.asyncio
async def test_unrelated_receive_error_is_not_converted_to_413() -> None:
    async def failed_receive() -> Message:
        raise OSError("transport failed")

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=8,
        upload_limit_bytes=6,
    )

    with pytest.raises(OSError, match="transport failed"):
        await _invoke(limiter, receive_override=failed_receive)


@pytest.mark.asyncio
async def test_downstream_error_after_overflow_cleanup_is_not_swallowed() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            while True:
                await receive()
        except OSError as exc:
            raise RuntimeError("cleanup failed") from exc

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await _invoke(
            limiter,
            messages=[
                _request_message(b"1234", more_body=True),
                _request_message(b"5", more_body=False),
            ],
        )


@pytest.mark.asyncio
async def test_concurrent_oversized_streams_keep_independent_counters() -> None:
    downstream_calls = 0

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await _send_empty_response(send)

    limiter = RequestBodyLimitMiddleware(
        downstream,
        global_limit_bytes=4,
        upload_limit_bytes=3,
    )

    async def one_request() -> int:
        messages, _ = await _invoke(
            limiter,
            messages=[
                _request_message(b"1234", more_body=True),
                _request_message(b"5", more_body=False),
            ],
        )
        return _status(messages)

    statuses = await asyncio.gather(*(one_request() for _ in range(25)))

    assert statuses == [413] * 25
    assert downstream_calls == 25


def test_limit_configuration_must_be_positive_and_ordered() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        return None

    with pytest.raises(ValueError, match="positive"):
        RequestBodyLimitMiddleware(
            downstream,
            global_limit_bytes=0,
            upload_limit_bytes=1,
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        RequestBodyLimitMiddleware(
            downstream,
            global_limit_bytes=1,
            upload_limit_bytes=2,
        )
