from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings
from app.services.supabase_jwt import (
    SupabaseJwtError,
    SupabaseJwtVerifier,
)


GENERIC_STAFF_AUTH_ERROR = "Invalid staff credentials"


class SupabasePasswordAuthError(RuntimeError):
    """Generic staff password-authentication failure.

    Callers intentionally receive no distinction between an invalid account,
    invalid password, upstream rejection, or unusable upstream response.
    """


def _password_endpoint(settings: Settings) -> str:
    base_url = (settings.supabase_url or "").strip().rstrip("/")
    if not base_url:
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR)
    return f"{base_url}/auth/v1/token"


def _publishable_key(settings: Settings) -> str:
    key = (settings.supabase_publishable_key or settings.supabase_anon_key or "").strip()
    if not key:
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR)
    return key


def _access_token(payload: object) -> str:
    if not isinstance(payload, Mapping):
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR)
    return token.strip()


async def _sign_in(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    email: str,
    password: str,
) -> str:
    try:
        response = await client.post(
            _password_endpoint(settings),
            params={"grant_type": "password"},
            headers={
                "apikey": _publishable_key(settings),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"email": email, "password": password},
        )
    except httpx.HTTPError as exc:
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR) from exc

    if response.status_code != 200:
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR)
    try:
        payload = response.json()
    except ValueError as exc:
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR) from exc
    return _access_token(payload)


async def authenticate_supabase_password(
    *,
    email: str,
    password: str,
    settings: Settings,
    verifier: SupabaseJwtVerifier | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Authenticate staff upstream and return trusted JWT claims only.

    The short-lived upstream access token exists only within this call.  The
    refresh token and the rest of the Auth response are never returned or
    persisted by MATA.
    """

    trusted_verifier = verifier
    if trusted_verifier is None:
        try:
            trusted_verifier = SupabaseJwtVerifier(settings)
        except SupabaseJwtError as exc:
            raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR) from exc

    if client is None:
        async with httpx.AsyncClient(timeout=5.0) as owned_client:
            access_token = await _sign_in(
                owned_client,
                settings=settings,
                email=email,
                password=password,
            )
    else:
        access_token = await _sign_in(
            client,
            settings=settings,
            email=email,
            password=password,
        )

    try:
        claims = await trusted_verifier.verify(access_token)
    except SupabaseJwtError as exc:
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR) from exc
    if not isinstance(claims, dict):
        raise SupabasePasswordAuthError(GENERIC_STAFF_AUTH_ERROR)
    return dict(claims)


class SupabasePasswordAuthClient:
    """Small injectable wrapper used by backend-mediated staff login."""

    def __init__(
        self,
        settings: Settings,
        *,
        verifier: SupabaseJwtVerifier | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._verifier = verifier
        self._client = client

    async def authenticate(self, *, email: str, password: str) -> dict[str, Any]:
        return await authenticate_supabase_password(
            email=email,
            password=password,
            settings=self._settings,
            verifier=self._verifier,
            client=self._client,
        )
