from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.config import Settings
from app.errors import ApiError, ErrorCode


class SupabaseAdminError(ApiError):
    pass


def _normalise_project_url(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip().rstrip("/")
    return trimmed or None


class SupabaseAdminClient:
    def __init__(self, settings: Settings) -> None:
        self._supabase_url = _normalise_project_url(settings.supabase_url)
        self._service_role_key = settings.supabase_service_role_key

        if not self._supabase_url or not self._service_role_key:
            raise SupabaseAdminError(
                status_code=503,
                detail="Supabase Admin service is not configured",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_role_key or "",
            "Authorization": f"Bearer {self._service_role_key}",
            "Content-Type": "application/json",
        }

    def _admin_url(self, path: str) -> str:
        return f"{self._supabase_url}/auth/v1/admin/{path.lstrip('/')}"

    async def create_user(self, *, email: str, password: str) -> UUID:
        payload = {
            "email": email,
            "password": password,
            "email_confirm": True,
        }
        data = await self._request("POST", self._admin_url("users"), json=payload)
        return self._user_id_from_payload(data)

    async def update_user_password(self, *, supabase_user_id: UUID, password: str) -> None:
        await self._request(
            "PUT",
            self._admin_url(f"users/{supabase_user_id}"),
            json={"password": password},
        )

    async def _request(self, method: str, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                )
        except httpx.HTTPError as exc:
            raise SupabaseAdminError(
                status_code=502,
                detail="Supabase Admin request failed",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            ) from exc

        if response.status_code >= 400:
            detail = "Supabase Admin request rejected"
            if response.status_code == 400:
                detail = "Supabase Admin rejected the request"
            elif response.status_code in {401, 403}:
                detail = "Supabase Admin credentials were rejected"
            elif response.status_code == 422:
                detail = "Supabase Admin validation failed"
            raise SupabaseAdminError(
                status_code=502,
                detail=detail,
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SupabaseAdminError(
                status_code=502,
                detail="Supabase Admin returned an invalid response",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            ) from exc

        if not isinstance(payload, dict):
            raise SupabaseAdminError(
                status_code=502,
                detail="Supabase Admin returned an invalid response",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        return payload

    @staticmethod
    def _user_id_from_payload(payload: dict[str, Any]) -> UUID:
        raw_user_id = payload.get("id")
        if not isinstance(raw_user_id, str):
            raise SupabaseAdminError(
                status_code=502,
                detail="Supabase Admin response did not include a user id",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        try:
            return UUID(raw_user_id)
        except ValueError as exc:
            raise SupabaseAdminError(
                status_code=502,
                detail="Supabase Admin response included an invalid user id",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            ) from exc
