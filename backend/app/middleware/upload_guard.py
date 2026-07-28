from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings
from app.errors import ErrorCode, build_error_response


class UploadGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[override]
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() == "POST" and request.url.path.startswith(
            f"{self._settings.api_prefix}/admin/upload/",
        ):
            content_type = (request.headers.get("content-type") or "").lower()
            if "multipart/form-data" not in content_type:
                return build_error_response(
                    status_code=422,
                    detail="Invalid upload content type",
                    error_code=ErrorCode.FILE_VALIDATION_FAILED.value,
                )

        return await call_next(request)
