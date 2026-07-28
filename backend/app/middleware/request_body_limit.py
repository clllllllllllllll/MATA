from __future__ import annotations

from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import ErrorCode, build_error_response


MEBIBYTE = 1024 * 1024
DEFAULT_GLOBAL_BODY_LIMIT_BYTES = 4 * MEBIBYTE
DEFAULT_UPLOAD_BODY_LIMIT_BYTES = 4 * MEBIBYTE

_NO_STORE_HEADERS = {"Cache-Control": "no-store"}
_MAX_CONTENT_LENGTH_DIGITS = 20


class _RequestBodyTooLarge(OSError):
    """Internal receive sentinel that also triggers Starlette file cleanup."""


def _parse_content_length(
    headers: Iterable[tuple[bytes, bytes]],
) -> int | None:
    raw_values = [
        value
        for name, value in headers
        if name.lower() == b"content-length"
    ]
    if not raw_values:
        return None

    parsed_values: set[int] = set()
    for raw_value in raw_values:
        for raw_member in raw_value.split(b","):
            member = raw_member.strip(b" \t")
            if (
                not member
                or len(member) > _MAX_CONTENT_LENGTH_DIGITS
                or any(byte < ord("0") or byte > ord("9") for byte in member)
            ):
                raise ValueError("invalid Content-Length")
            try:
                parsed_values.add(int(member))
            except ValueError as exc:
                # Python rejects extremely long digit strings before allocating
                # an unbounded integer. Treat them like every other malformed
                # Content-Length value.
                raise ValueError("invalid Content-Length") from exc

    if len(parsed_values) != 1:
        raise ValueError("conflicting Content-Length")
    return parsed_values.pop()


class RequestBodyLimitMiddleware:
    """Enforce aggregate request-body limits without buffering the body."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        global_limit_bytes: int = DEFAULT_GLOBAL_BODY_LIMIT_BYTES,
        upload_limit_bytes: int = DEFAULT_UPLOAD_BODY_LIMIT_BYTES,
        api_prefix: str = "/api/v1",
    ) -> None:
        if global_limit_bytes <= 0 or upload_limit_bytes <= 0:
            raise ValueError("Request body limits must be positive")
        if upload_limit_bytes > global_limit_bytes:
            raise ValueError("Upload request body limit cannot exceed the global limit")

        normalised_api_prefix = "/" + api_prefix.strip("/") if api_prefix.strip("/") else ""
        self.app = app
        self._global_limit_bytes = global_limit_bytes
        self._upload_limit_bytes = upload_limit_bytes
        self._upload_path_prefix = f"{normalised_api_prefix}/admin/upload/"

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        is_upload_path = path.startswith(self._upload_path_prefix)
        body_limit = (
            self._upload_limit_bytes
            if is_upload_path
            else self._global_limit_bytes
        )

        try:
            declared_length = _parse_content_length(scope.get("headers", ()))
        except ValueError:
            response = build_error_response(
                status_code=400,
                detail="Invalid Content-Length header",
                error_code=ErrorCode.VALIDATION_FAILED.value,
                headers=_NO_STORE_HEADERS,
            )
            await response(scope, receive, send)
            return

        if declared_length is not None and declared_length > body_limit:
            response = self._too_large_response(is_upload_path=is_upload_path)
            await response(scope, receive, send)
            return

        observed_bytes = 0
        body_too_large = False
        replacement_sent = False
        downstream_response_started = False

        async def limited_receive() -> Message:
            nonlocal body_too_large, observed_bytes

            message = await receive()
            if message["type"] != "http.request":
                return message

            observed_bytes += len(message.get("body", b""))
            if observed_bytes > body_limit:
                body_too_large = True
                # Do not release the crossing chunk downstream. OSError is
                # intentional: Starlette's multipart parser closes every
                # temporary file when an OSError interrupts parsing.
                raise _RequestBodyTooLarge
            return message

        async def limited_send(message: Message) -> None:
            nonlocal downstream_response_started, replacement_sent

            if body_too_large and not downstream_response_started:
                if not replacement_sent and message["type"] == "http.response.start":
                    replacement_sent = True
                    response = self._too_large_response(
                        is_upload_path=is_upload_path,
                    )
                    await response(scope, receive, send)
                return

            if message["type"] == "http.response.start":
                downstream_response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except _RequestBodyTooLarge:
            if downstream_response_started:
                # The status and headers are already on the wire, so replacing
                # them with a controlled 413 is no longer valid ASGI. Preserve
                # the abort signal and let the server terminate the response.
                raise

        if body_too_large and not replacement_sent and not downstream_response_started:
            response = self._too_large_response(is_upload_path=is_upload_path)
            await response(scope, receive, send)

    @staticmethod
    def _too_large_response(*, is_upload_path: bool):
        if is_upload_path:
            detail = "Upload request exceeds maximum allowed size"
            error_code = ErrorCode.FILE_VALIDATION_FAILED.value
        else:
            detail = "Request body exceeds maximum allowed size"
            error_code = ErrorCode.VALIDATION_FAILED.value
        return build_error_response(
            status_code=413,
            detail=detail,
            error_code=error_code,
            headers=_NO_STORE_HEADERS,
        )
