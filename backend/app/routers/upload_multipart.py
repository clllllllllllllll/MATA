from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.routing import APIRoute
from python_multipart.exceptions import FormParserError
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request
from starlette.responses import Response

from app.errors import ErrorCode, build_error_response


MAX_UPLOAD_FILES = 1
MAX_UPLOAD_FORM_FIELD_BYTES = 4 * 1024
MAX_UPLOAD_FILENAME_BYTES = 255

UPLOAD_MAX_FORM_FIELDS_BY_PATH = {
    "/admin/upload/rdb": 1,
    "/admin/upload/ttf": 2,
    "/admin/upload/form-f1": 1,
    "/admin/upload/public-holidays": 0,
}

_RouteHandler = Callable[[Request], Awaitable[Response]]
_UPLOAD_MAX_FIELDS_ATTRIBUTE = "_mata_upload_multipart_max_fields"


class _UploadMultipartLimitError(ValueError):
    pass


class _CleanupMultiPartParser(MultiPartParser):
    async def parse(self) -> FormData:
        try:
            return await super().parse()
        except BaseException:
            # Starlette closes these files only for MultiPartException and
            # OSError. Cover malformed parser errors and cancellation too,
            # while preserving the original exception.
            for temporary_file in self._files_to_close_on_error:
                try:
                    temporary_file.close()
                except BaseException:
                    continue
            raise


def bounded_admin_upload(
    path: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark one explicitly configured admin upload endpoint for pre-parsing."""

    try:
        max_fields = UPLOAD_MAX_FORM_FIELDS_BY_PATH[path]
    except KeyError as exc:
        raise ValueError("Unknown bounded admin upload path") from exc

    def mark_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]:
        setattr(endpoint, _UPLOAD_MAX_FIELDS_ATTRIBUTE, max_fields)
        return endpoint

    return mark_endpoint


def _is_multipart_request(request: Request) -> bool:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.partition(";")[0].strip().casefold()
    return media_type == "multipart/form-data"


async def _parse_bounded_multipart(
    request: Request,
    *,
    max_fields: int,
) -> FormData:
    parser = _CleanupMultiPartParser(
        request.headers,
        request.stream(),
        max_files=MAX_UPLOAD_FILES,
        max_fields=max_fields,
        max_part_size=MAX_UPLOAD_FORM_FIELD_BYTES,
    )
    form = await parser.parse()
    request._form = form
    return form


def _validate_filenames(form: FormData) -> None:
    for _, value in form.multi_items():
        if not isinstance(value, UploadFile):
            continue
        filename = value.filename or ""
        if len(filename.encode("utf-8")) > MAX_UPLOAD_FILENAME_BYTES:
            raise _UploadMultipartLimitError


async def _close_upload_files(form: FormData) -> None:
    for _, value in form.multi_items():
        if not isinstance(value, UploadFile):
            continue
        try:
            await value.close()
        except OSError:
            # A close failure must not replace the request's response. Continue
            # closing any remaining parsed temporary files.
            continue


def _multipart_rejection_response() -> Response:
    return build_error_response(
        status_code=422,
        detail="Upload file validation failed",
        error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
        headers={"Cache-Control": "no-store, private, max-age=0"},
    )


class BoundedAdminUploadRoute(APIRoute):
    """Apply multipart parser limits before FastAPI resolves body parameters."""

    multipart_max_fields: int | None

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        self.multipart_max_fields = getattr(
            endpoint,
            _UPLOAD_MAX_FIELDS_ATTRIBUTE,
            None,
        )
        super().__init__(path, endpoint, **kwargs)

    def get_route_handler(self) -> _RouteHandler:
        route_handler = super().get_route_handler()
        max_fields = self.multipart_max_fields
        if max_fields is None:
            return route_handler

        async def bounded_route_handler(request: Request) -> Response:
            if not _is_multipart_request(request):
                return await route_handler(request)

            form: FormData | None = None
            try:
                try:
                    # Starlette's max_part_size applies to non-file form parts.
                    # File bytes remain bounded by the upload byte-limit controls.
                    form = await _parse_bounded_multipart(
                        request,
                        max_fields=max_fields,
                    )
                    _validate_filenames(form)
                except (
                    FormParserError,
                    MultiPartException,
                    _UploadMultipartLimitError,
                    UnicodeError,
                ):
                    return _multipart_rejection_response()

                return await route_handler(request)
            finally:
                if form is not None:
                    await _close_upload_files(form)

        return bounded_route_handler
