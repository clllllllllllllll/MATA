from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings
from app.database import AsyncSessionLocal
from app.errors import ErrorCode, build_error_response
from app.middleware.auth_stub import AuthIdentity
from app.services.persistent_rate_limit import (
    RateLimitPolicy,
    check_rate_limit,
)


@dataclass
class _Bucket:
    count: int
    reset_at: float


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[override]
        super().__init__(app)
        self._settings = settings
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        if self._uses_endpoint_persistent_dependency(request):
            return await call_next(request)

        limit, window_seconds, group = self._resolve_limit_rule(request)
        if limit is not None and window_seconds is not None and group is not None:
            if self._settings.rate_limit_store == "postgres":
                allowed, retry_after = await self._allow_persistent_request(
                    request,
                    group,
                    limit,
                    window_seconds,
                )
            else:
                allowed, retry_after = await self._allow_request(
                    request,
                    group,
                    limit,
                    window_seconds,
                )
            if not allowed:
                response = build_error_response(
                    status_code=429,
                    detail="Too many requests",
                    error_code=ErrorCode.RATE_LIMITED.value,
                )
                response.headers["Retry-After"] = str(max(1, retry_after))
                return response
        return await call_next(request)

    def _resolve_limit_rule(self, request: Request) -> tuple[int | None, int | None, str | None]:
        path = request.url.path
        method = request.method.upper()
        api_prefix = self._settings.api_prefix

        if method == "POST" and path == f"{api_prefix}/auth/login":
            return self._settings.rate_limit_auth_per_minute, 60, "auth_login"

        if method == "POST" and path.startswith(f"{api_prefix}/admin/upload/"):
            return self._settings.rate_limit_upload_per_hour, 3600, "admin_upload"

        if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith(
            f"{api_prefix}/resident/attendance"
        ):
            return (
                self._settings.rate_limit_resident_attendance_per_minute,
                60,
                "resident_attendance",
            )

        if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith(
            f"{api_prefix}/admin/staff-accounts"
        ):
            return self._settings.rate_limit_mutation_per_minute, 60, "staff_account_mutation"

        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return self._settings.rate_limit_mutation_per_minute, 60, "mutation"

        if method == "GET" and self._is_report_or_export_path(path):
            return self._settings.rate_limit_report_per_minute, 60, "report"

        if method == "GET":
            return self._settings.rate_limit_get_per_minute, 60, "get"

        return None, None, None

    def _uses_endpoint_persistent_dependency(self, request: Request) -> bool:
        if request.method.upper() != "POST":
            return False
        path = request.url.path
        api_prefix = self._settings.api_prefix
        if path in {
            f"{api_prefix}/auth/login",
            f"{api_prefix}/external-residents/register",
        }:
            return True
        if self._settings.rate_limit_store == "postgres":
            return False
        return path in {
            f"{api_prefix}/admin/upload/rdb",
            f"{api_prefix}/admin/upload/ttf",
            f"{api_prefix}/admin/upload/form-f1",
        }

    def _is_report_or_export_path(self, path: str) -> bool:
        api_prefix = self._settings.api_prefix
        if not path.startswith(f"{api_prefix}/admin/"):
            return False
        lowered = path.casefold()
        return (
            "/report" in lowered
            or "/export" in lowered
            or lowered.endswith((".xlsx", ".csv"))
            or any(
                segment in lowered
                for segment in (
                    "/external-attendance",
                    "/resident-attendance",
                    "/resident-submissions",
                    "/logs",
                    "/upload-logs",
                )
            )
        )

    async def _allow_persistent_request(
        self,
        request: Request,
        group: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        identity = getattr(request.state, "identity", None)
        subject_id = str(getattr(identity, "subject_id", "") or "").strip()
        role = str(getattr(identity, "role", "") or "").strip().casefold()
        if subject_id and role:
            identifier = f"subject:{role}:{subject_id}"
        else:
            client_ip = request.client.host if request.client else "unknown"
            identifier = f"anonymous-ip:{client_ip}"

        policy = RateLimitPolicy(
            scope=group,
            limit=limit,
            window_seconds=window_seconds,
            message="Too many requests",
        )
        async with AsyncSessionLocal() as isolated_db:
            result = await check_rate_limit(
                isolated_db,
                settings=self._settings,
                policy=policy,
                identifier=identifier,
            )
        return result.allowed, result.retry_after_seconds

    async def _allow_request(
        self,
        request: Request,
        group: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        key = self._build_bucket_key(request, group)
        now = time.monotonic()

        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.reset_at <= now:
                self._buckets[key] = _Bucket(count=1, reset_at=now + window_seconds)
                return True, window_seconds

            if bucket.count >= limit:
                retry_after = int(bucket.reset_at - now)
                return False, retry_after

            bucket.count += 1
            return True, int(bucket.reset_at - now)

    def _build_bucket_key(self, request: Request, group: str) -> str:
        identity = getattr(request.state, "identity", None)
        if isinstance(identity, AuthIdentity):
            role = identity.role
            user_id = identity.subject_id
            programme = ",".join(identity.programme_scope or [])
            site = identity.posting_code or ""
        elif self._stub_header_fallback_allowed():
            role = (request.headers.get("X-User-Role") or "anonymous").strip().lower()
            user_id = (request.headers.get("X-User-Id") or "unknown").strip()
            programme = (request.headers.get("X-User-Programme") or "").strip()
            site = (request.headers.get("X-User-Site") or "").strip()
        else:
            role = "anonymous"
            user_id = "unknown"
            programme = ""
            site = ""
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        return (
            f"{group}|ip={client_ip}|role={role}|user={user_id}|"
            f"programme={programme}|site={site}|path={path}"
        )

    def _stub_header_fallback_allowed(self) -> bool:
        return (
            self._settings.environment != "production"
            and self._settings.auth_mode in {"stub", "demo"}
        )
