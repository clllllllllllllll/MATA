from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings


class UploadGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[override]
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() == "POST" and request.url.path.startswith(
            f"{self._settings.api_prefix}/admin/upload/",
        ):
            content_type = (request.headers.get("content-type") or "").lower()
            content_length = request.headers.get("content-length")

            if "multipart/form-data" not in content_type:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "Invalid upload content type"},
                )

            if content_length:
                try:
                    content_length_int = int(content_length)
                except ValueError:
                    return JSONResponse(
                        status_code=422,
                        content={"detail": "Invalid upload content length"},
                    )
                if content_length_int > self._settings.max_upload_size_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Uploaded file exceeds maximum allowed size"},
                    )

        return await call_next(request)
