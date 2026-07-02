from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK

from app.config import Settings


ASYMMETRIC_ALGORITHMS = {"RS256", "ES256", "EdDSA"}
LEGACY_SHARED_SECRET_ALGORITHMS = {"HS256"}
MAX_JWKS_CACHE_TTL_SECONDS = 600


class SupabaseJwtError(Exception):
    """Raised when a Supabase access token cannot be trusted."""


@dataclass(frozen=True)
class SupabaseJwtConfig:
    issuer: str
    jwks_url: str
    audience: str
    publishable_key: str | None
    jwks_cache_ttl_seconds: int


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise SupabaseJwtError("Missing Authorization header")

    scheme, separator, token = authorization.strip().partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise SupabaseJwtError("Invalid Authorization header")
    return token.strip()


class SupabaseJwtVerifier:
    def __init__(self, settings: Settings) -> None:
        self._config = self._build_config(settings)
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cached_at: float = 0.0

    async def verify_authorization_header(self, authorization: str | None) -> dict[str, Any]:
        return await self.verify(extract_bearer_token(authorization))

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise SupabaseJwtError("Invalid JWT header") from exc

        algorithm = str(header.get("alg") or "")
        if not algorithm or algorithm.lower() == "none":
            raise SupabaseJwtError("Unsupported JWT algorithm")

        if algorithm in LEGACY_SHARED_SECRET_ALGORITHMS:
            return await self._verify_via_auth_server(token)

        if algorithm not in ASYMMETRIC_ALGORITHMS:
            raise SupabaseJwtError("Unsupported JWT algorithm")

        key_id = str(header.get("kid") or "")
        if not key_id:
            raise SupabaseJwtError("Missing JWT key id")

        key = await self._get_signing_key(key_id=key_id, algorithm=algorithm)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self._config.audience,
                issuer=self._config.issuer,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
        except InvalidTokenError as exc:
            raise SupabaseJwtError("Invalid Supabase JWT") from exc

        if not isinstance(claims, dict):
            raise SupabaseJwtError("Invalid JWT claims")
        return claims

    async def _get_signing_key(self, *, key_id: str, algorithm: str) -> Any:
        jwks = await self._get_jwks()
        jwk = self._find_jwk(jwks, key_id=key_id, algorithm=algorithm)
        if jwk is None:
            jwks = await self._get_jwks(force_refresh=True)
            jwk = self._find_jwk(jwks, key_id=key_id, algorithm=algorithm)

        if jwk is None:
            raise SupabaseJwtError("JWT signing key not found")

        try:
            return PyJWK.from_dict(jwk).key
        except Exception as exc:  # pragma: no cover - defensive library boundary
            raise SupabaseJwtError("Invalid JWKS key") from exc

    async def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        ttl = self._config.jwks_cache_ttl_seconds
        if (
            not force_refresh
            and self._jwks_cache is not None
            and ttl > 0
            and now - self._jwks_cached_at < ttl
        ):
            return self._jwks_cache

        jwks = await self._fetch_jwks()
        if not isinstance(jwks.get("keys"), list):
            raise SupabaseJwtError("Invalid JWKS response")

        self._jwks_cache = jwks
        self._jwks_cached_at = now
        return jwks

    async def _fetch_jwks(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self._config.jwks_url)
        except httpx.HTTPError as exc:
            raise SupabaseJwtError("Unable to fetch JWKS") from exc

        if response.status_code != 200:
            raise SupabaseJwtError("Unable to fetch JWKS")

        try:
            return response.json()
        except ValueError as exc:
            raise SupabaseJwtError("Invalid JWKS response") from exc

    async def _verify_via_auth_server(self, token: str) -> dict[str, Any]:
        if not self._config.publishable_key:
            raise SupabaseJwtError("Supabase publishable key required for legacy JWT validation")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self._config.issuer}/user",
                    headers={
                        "apikey": self._config.publishable_key,
                        "Authorization": f"Bearer {token}",
                    },
                )
        except httpx.HTTPError as exc:
            raise SupabaseJwtError("Unable to validate legacy JWT") from exc

        if response.status_code != 200:
            raise SupabaseJwtError("Invalid legacy Supabase JWT")

        return self._decode_unverified_claims_after_auth_server_validation(token)

    def _decode_unverified_claims_after_auth_server_validation(self, token: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_iat": False,
                },
            )
        except InvalidTokenError as exc:
            raise SupabaseJwtError("Invalid JWT claims") from exc

        if not isinstance(claims, dict):
            raise SupabaseJwtError("Invalid JWT claims")

        self._validate_claims_without_signature(claims)
        return claims

    def _validate_claims_without_signature(self, claims: Mapping[str, Any]) -> None:
        if claims.get("iss") != self._config.issuer:
            raise SupabaseJwtError("Invalid JWT issuer")

        audience = claims.get("aud")
        if isinstance(audience, str):
            valid_audience = audience == self._config.audience
        elif isinstance(audience, list):
            valid_audience = self._config.audience in audience
        else:
            valid_audience = False
        if not valid_audience:
            raise SupabaseJwtError("Invalid JWT audience")

        if not claims.get("sub"):
            raise SupabaseJwtError("Missing JWT subject")

        now = int(time.time())
        exp = claims.get("exp")
        if not isinstance(exp, int) or exp <= now:
            raise SupabaseJwtError("Expired JWT")

        iat = claims.get("iat")
        if not isinstance(iat, int) or iat > now + 60:
            raise SupabaseJwtError("Invalid JWT issued-at")

    @staticmethod
    def _find_jwk(
        jwks: Mapping[str, Any],
        *,
        key_id: str,
        algorithm: str,
    ) -> dict[str, Any] | None:
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            return None

        for key in keys:
            if not isinstance(key, dict):
                continue
            if key.get("kid") != key_id:
                continue
            key_algorithm = key.get("alg")
            if key_algorithm is not None and key_algorithm != algorithm:
                continue
            return key
        return None

    @staticmethod
    def _build_config(settings: Settings) -> SupabaseJwtConfig:
        raw_url = (settings.supabase_url or "").strip().rstrip("/")
        if not raw_url:
            raise SupabaseJwtError("SUPABASE_URL is required")

        issuer = (settings.supabase_jwt_issuer or "").strip().rstrip("/")
        if not issuer:
            issuer = f"{raw_url}/auth/v1"

        jwks_url = (settings.supabase_jwks_url or "").strip()
        if not jwks_url:
            jwks_url = f"{issuer}/.well-known/jwks.json"

        ttl = max(0, min(settings.supabase_jwks_cache_ttl_seconds, MAX_JWKS_CACHE_TTL_SECONDS))
        publishable_key = settings.supabase_publishable_key or settings.supabase_anon_key
        return SupabaseJwtConfig(
            issuer=issuer,
            jwks_url=jwks_url,
            audience=settings.supabase_jwt_audience,
            publishable_key=publishable_key,
            jwks_cache_ttl_seconds=ttl,
        )
