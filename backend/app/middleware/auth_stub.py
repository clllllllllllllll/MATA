from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import Settings, get_settings
from app.database import AsyncSessionLocal
from app.errors import ErrorCode, build_error_response
from app.models import ExternalResident, Resident, User
from app.services.app_sessions import resolve_session, revoke_session, validate_csrf
from app.services.mata_resident_token import (
    MataResidentTokenError,
    extract_bearer_token,
    is_mata_resident_token,
    verify_mata_resident_token,
)
from app.services.supabase_jwt import SupabaseJwtError, SupabaseJwtVerifier
from app.services.session_transport import clear_session_cookie, session_cookie_name
from app.middleware.security import is_approved_origin, is_unsafe_method


@dataclass
class AuthIdentity:
    role: str
    subject_id: str
    programme_scope: list[str] | None = None
    programme_code: str | None = None
    posting_code: str | None = None
    admin_level: str | None = None
    mcr: str | None = None
    home_cluster: str | None = None
    current_staff_actor_name: str | None = None


class AuthStubMiddleware(BaseHTTPMiddleware):
    OPEN_PATHS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
    RAW_IDENTITY_HEADERS = {
        "x-user-role",
        "x-user-id",
        "x-user-programme",
        "x-user-site",
        "x-user-mcr",
        "x-admin-level",
    }

    def __init__(self, app: Starlette, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()
        self._supabase_verifier: SupabaseJwtVerifier | None = None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        login_path = f"{self._settings.api_prefix}/auth/login"
        registration_path = f"{self._settings.api_prefix}/external-residents/register"
        registration_options_path = (
            f"{self._settings.api_prefix}/external-residents/registration-options"
        )

        if (
            self._settings.environment == "production"
            and is_unsafe_method(request.method)
            and not is_approved_origin(request.headers.get("Origin"), self._settings)
        ):
            return self._forbidden_response()

        if path in {login_path, registration_path} and request.method == "POST":
            if not self._public_json_request_allowed(request):
                return build_error_response(
                    status_code=415,
                    detail="Unsupported media type",
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                )
            return await call_next(request)

        if (
            request.method == "OPTIONS"
            or path in self.OPEN_PATHS
            or (request.method == "GET" and path == registration_options_path)
        ):
            return await call_next(request)

        if not self._stub_header_auth_allowed() and self._has_raw_identity_headers(request):
            return self._unauthorized_response()

        if self._settings.auth_transport == "cookie":
            cookie_result = await self._dispatch_cookie_auth(request, call_next)
            if cookie_result is not None:
                return cookie_result

        if not self._stub_header_auth_allowed():
            if self._supabase_auth_required() and self._bearer_compat_allowed():
                identity_or_error = await self._resolve_supabase_identity(request)
                if isinstance(identity_or_error, Response):
                    return identity_or_error

                request.state.identity = identity_or_error
                return await call_next(request)

            return self._unauthorized_response()

        role = (request.headers.get("X-User-Role") or "").strip().lower()
        raw_subject = (request.headers.get("X-User-Id") or "").strip()

        if not role or not raw_subject:
            return self._unauthorized_response()

        try:
            subject_id = UUID(raw_subject)
        except ValueError:
            return self._unauthorized_response()

        if role in {"admin", "secretary"}:
            identity_or_error = await self._resolve_user_identity(request, role, subject_id)
        elif role == "resident":
            identity_or_error = await self._resolve_resident_identity(request, subject_id)
        elif role == "external_resident":
            identity_or_error = await self._resolve_external_resident_identity(subject_id)
        else:
            return self._unauthorized_response()

        if isinstance(identity_or_error, Response):
            return identity_or_error

        request.state.identity = identity_or_error
        response = await call_next(request)
        if response.status_code == 401:
            clear_session_cookie(response, settings=self._settings)
        return response

    async def _dispatch_cookie_auth(self, request: Request, call_next) -> Response | None:
        if request.headers.get("Authorization") and not self._stub_header_auth_allowed():
            return self._unauthorized_response()

        raw_session_token = request.cookies.get(session_cookie_name(self._settings))
        logout_path = f"{self._settings.api_prefix}/auth/logout"
        if not raw_session_token:
            if request.url.path == logout_path and request.method == "POST":
                return await call_next(request)
            if self._stub_header_auth_allowed():
                return None
            return self._unauthorized_response()

        try:
            async with AsyncSessionLocal() as session_db:
                app_session = await resolve_session(
                    session_db,
                    self._settings,
                    raw_session_token,
                    touch=is_unsafe_method(request.method),
                )
                await session_db.commit()
        except Exception:
            response = build_error_response(
                status_code=503,
                detail="Authentication service unavailable",
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
            clear_session_cookie(response, settings=self._settings)
            return response

        if app_session is None:
            if request.url.path == logout_path and request.method == "POST":
                response = await call_next(request)
            else:
                response = self._unauthorized_response()
            clear_session_cookie(response, settings=self._settings)
            return response

        identity_or_error = await self._resolve_app_session_identity(app_session, request)
        if isinstance(identity_or_error, Response):
            try:
                async with AsyncSessionLocal() as session_db:
                    await revoke_session(
                        session_db,
                        app_session,
                        reason="subject_inactive_or_invalid",
                    )
                    await session_db.commit()
            except Exception:
                pass
            clear_session_cookie(identity_or_error, settings=self._settings)
            return identity_or_error

        request.state.identity = identity_or_error
        request.state.app_session = app_session
        request.state.session_token = raw_session_token

        if is_unsafe_method(request.method):
            csrf_token = request.headers.get(self._settings.csrf_header_name)
            if not validate_csrf(app_session, csrf_token, self._settings):
                return self._forbidden_response()

        response = await call_next(request)
        if response.status_code == 401:
            clear_session_cookie(response, settings=self._settings)
        return response

    async def _resolve_app_session_identity(
        self,
        app_session,
        request: Request,
    ) -> AuthIdentity | Response:
        if app_session.subject_type == "staff":
            return await self._resolve_session_user_identity(
                app_session.subject_id,
                request,
                expected_session_generation=app_session.subject_session_generation,
            )
        if app_session.subject_type == "resident":
            return await self._resolve_mata_resident_identity(
                app_session.subject_id,
                request,
                expected_session_generation=app_session.subject_session_generation,
            )
        if app_session.subject_type == "external_resident":
            return await self._resolve_mata_external_resident_identity(
                app_session.subject_id,
                request,
                expected_session_generation=app_session.subject_session_generation,
            )
        return self._unauthorized_response()

    async def _resolve_session_user_identity(
        self,
        user_id: UUID,
        request: Request,
        *,
        expected_session_generation: int,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
        if (
            user is None
            or not user.is_active
            or user.session_issuance_blocked
            or user.session_generation != expected_session_generation
        ):
            return self._supabase_unauthorized_response(request, "staff_missing_or_inactive")
        return self._identity_from_user(user)

    def _identity_from_user(self, user: User) -> AuthIdentity | Response:
        if user.role not in {"admin", "secretary"}:
            return self._unauthorized_response()
        if user.role == "admin":
            return AuthIdentity(
                role="admin",
                subject_id=str(user.id),
                programme_scope=self._normalise_programme_scope(user.programme_scope),
                admin_level=self._resolve_admin_level(
                    persisted_admin_level=getattr(user, "admin_level", None),
                ),
                current_staff_actor_name=getattr(user, "current_staff_actor_name", None),
            )
        if not user.posting_code:
            return build_error_response(
                status_code=403,
                detail="Forbidden",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        return AuthIdentity(
            role="secretary",
            subject_id=str(user.id),
            posting_code=user.posting_code,
            current_staff_actor_name=getattr(user, "current_staff_actor_name", None),
        )

    async def _resolve_supabase_identity(self, request: Request) -> AuthIdentity | Response:
        try:
            bearer_token = extract_bearer_token(request.headers.get("Authorization"))
        except MataResidentTokenError:
            authorization = request.headers.get("Authorization")
            reason = "missing_authorization" if not authorization else "malformed_bearer"
            return self._supabase_unauthorized_response(request, reason)

        if is_mata_resident_token(bearer_token, settings=self._settings):
            try:
                claims = verify_mata_resident_token(bearer_token, settings=self._settings)
            except MataResidentTokenError:
                return self._supabase_unauthorized_response(request, "mata_token_invalid")

            raw_subject = claims.get("sub")
            if not isinstance(raw_subject, str):
                return self._supabase_unauthorized_response(request, "mata_claims_missing_sub")
            try:
                resident_id = UUID(raw_subject)
            except ValueError:
                return self._supabase_unauthorized_response(request, "mata_claims_invalid_sub")
            if claims.get("app_role") == "external_resident":
                return await self._resolve_mata_external_resident_identity(resident_id, request)
            return await self._resolve_mata_resident_identity(resident_id, request)

        try:
            claims = await self._get_supabase_verifier().verify(bearer_token)
        except SupabaseJwtError:
            return self._supabase_unauthorized_response(request, "supabase_jwt_verify_failed")

        raw_subject = claims.get("sub")
        if not isinstance(raw_subject, str):
            return self._supabase_unauthorized_response(request, "supabase_claims_missing_sub")

        try:
            supabase_user_id = UUID(raw_subject)
        except ValueError:
            return self._supabase_unauthorized_response(request, "supabase_claims_invalid_sub")

        return await self._resolve_supabase_user_identity(supabase_user_id, request)

    async def _resolve_mata_resident_identity(
        self,
        resident_id: UUID,
        request: Request | None = None,
        *,
        expected_session_generation: int | None = None,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            resident = await session.scalar(select(Resident).where(Resident.id == resident_id))

        if (
            resident is None
            or resident.status != "active"
            or (
                expected_session_generation is not None
                and resident.session_generation != expected_session_generation
            )
        ):
            if request is not None:
                return self._supabase_unauthorized_response(request, "mata_resident_missing_or_inactive")
            return self._unauthorized_response()

        return AuthIdentity(
            role="resident",
            subject_id=str(resident.id),
            programme_code=resident.programme_code,
            mcr=resident.mcr,
        )

    async def _resolve_mata_external_resident_identity(
        self,
        external_resident_id: UUID,
        request: Request | None = None,
        *,
        expected_session_generation: int | None = None,
    ) -> AuthIdentity | Response:
        return await self._resolve_external_resident_identity(
            external_resident_id,
            request,
            expected_session_generation=expected_session_generation,
        )

    async def _resolve_supabase_user_identity(
        self,
        supabase_user_id: UUID,
        request: Request,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.supabase_user_id == supabase_user_id),
            )

        if user is None:
            return self._supabase_unauthorized_response(request, "supabase_user_unmapped")

        if not user.is_active or user.session_issuance_blocked:
            return self._supabase_unauthorized_response(request, "supabase_user_inactive")

        if user.role not in {"admin", "secretary"}:
            return self._supabase_unauthorized_response(request, "role_invalid")

        if user.role == "admin":
            return AuthIdentity(
                role="admin",
                subject_id=str(user.id),
                programme_scope=self._normalise_programme_scope(user.programme_scope),
                admin_level=self._resolve_admin_level(
                    persisted_admin_level=getattr(user, "admin_level", None),
                ),
                current_staff_actor_name=getattr(user, "current_staff_actor_name", None),
            )

        if not user.posting_code:
            return build_error_response(
                status_code=403,
                detail="Forbidden",
                error_code=ErrorCode.FORBIDDEN.value,
            )

        return AuthIdentity(
            role="secretary",
            subject_id=str(user.id),
            posting_code=user.posting_code,
            current_staff_actor_name=getattr(user, "current_staff_actor_name", None),
        )

    async def _resolve_user_identity(
        self,
        request: Request,
        role: str,
        subject_id: UUID,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.id == subject_id, User.is_active.is_(True)),
            )

        if user is None or user.role != role or user.session_issuance_blocked:
            return build_error_response(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )

        if role == "admin":
            requested_programmes = self._parse_programme_header(
                request.headers.get("X-User-Programme"),
            )
            allowed_programmes = self._normalise_programme_scope(user.programme_scope)
            admin_level = self._resolve_admin_level(
                persisted_admin_level=getattr(user, "admin_level", None),
            )
            if requested_programmes:
                if not allowed_programmes or not set(requested_programmes).issubset(
                    set(allowed_programmes),
                ):
                    return build_error_response(
                        status_code=403,
                        detail="Forbidden",
                        error_code=ErrorCode.FORBIDDEN.value,
                    )
            return AuthIdentity(
                role=role,
                subject_id=str(user.id),
                programme_scope=allowed_programmes,
                programme_code=",".join(requested_programmes) if requested_programmes else None,
                admin_level=admin_level,
                current_staff_actor_name=getattr(user, "current_staff_actor_name", None),
            )

        # secretary role
        requested_site = (request.headers.get("X-User-Site") or "").strip()
        if not requested_site or requested_site != user.posting_code:
            return build_error_response(
                status_code=403,
                detail="Forbidden",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        return AuthIdentity(
            role=role,
            subject_id=str(user.id),
            posting_code=user.posting_code,
            current_staff_actor_name=getattr(user, "current_staff_actor_name", None),
        )

    async def _resolve_resident_identity(
        self,
        request: Request,
        subject_id: UUID,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            resident = await session.scalar(select(Resident).where(Resident.id == subject_id))

        if resident is None or resident.status != "active":
            return build_error_response(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )

        requested_programme = (request.headers.get("X-User-Programme") or "").strip()
        if requested_programme and requested_programme != (resident.programme_code or ""):
            return build_error_response(
                status_code=403,
                detail="Forbidden",
                error_code=ErrorCode.FORBIDDEN.value,
            )

        return AuthIdentity(
            role="resident",
            subject_id=str(resident.id),
            programme_code=resident.programme_code,
            mcr=resident.mcr,
        )

    async def _resolve_external_resident_identity(
        self,
        subject_id: UUID,
        request: Request | None = None,
        *,
        expected_session_generation: int | None = None,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            resident = await session.scalar(
                select(ExternalResident).where(ExternalResident.id == subject_id),
            )

        if (
            resident is None
            or resident.status != "active"
            or (
                expected_session_generation is not None
                and resident.session_generation != expected_session_generation
            )
        ):
            if request is not None:
                return self._supabase_unauthorized_response(
                    request,
                    "mata_external_resident_missing_or_inactive",
                )
            return build_error_response(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )

        return AuthIdentity(
            role="external_resident",
            subject_id=str(resident.id),
            mcr=resident.mcr,
            home_cluster=resident.home_cluster,
        )

    @staticmethod
    def _unauthorized_response() -> Response:
        return build_error_response(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )

    @staticmethod
    def _forbidden_response() -> Response:
        return build_error_response(
            status_code=403,
            detail="Forbidden",
            error_code=ErrorCode.FORBIDDEN.value,
        )

    @staticmethod
    def _public_json_request_allowed(request: Request) -> bool:
        content_type = (request.headers.get("Content-Type") or "").split(";", 1)[0]
        return content_type.strip().lower() == "application/json"

    def _has_raw_identity_headers(self, request: Request) -> bool:
        return any(header in request.headers for header in self.RAW_IDENTITY_HEADERS)

    @staticmethod
    def _parse_programme_header(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        return [token.strip() for token in raw_value.split(",") if token.strip()]

    @staticmethod
    def _normalise_programme_scope(raw_scope: list[str] | None) -> list[str]:
        if raw_scope is None:
            return []
        return [value for raw in raw_scope if (value := str(raw).strip())]

    def _resolve_admin_level(
        self,
        *,
        persisted_admin_level: str | None,
    ) -> str:
        persisted = self._normalise_admin_level(persisted_admin_level) or "programme"
        if persisted == "master":
            return "master"

        return persisted

    def _stub_header_auth_allowed(self) -> bool:
        return (
            self._settings.environment != "production"
            and self._settings.auth_mode in {"stub", "demo"}
        )

    def _supabase_auth_required(self) -> bool:
        return self._settings.environment == "production" or self._settings.auth_mode == "supabase"

    def _bearer_compat_allowed(self) -> bool:
        if self._settings.auth_transport != "bearer_compat":
            return False
        return (
            self._settings.environment != "production"
            or self._settings.enable_production_bearer_rollback
        )

    def _get_supabase_verifier(self) -> SupabaseJwtVerifier:
        if self._supabase_verifier is None:
            self._supabase_verifier = SupabaseJwtVerifier(self._settings)
        return self._supabase_verifier

    def _supabase_unauthorized_response(self, request: Request, reason: str) -> Response:
        return self._unauthorized_response()

    @staticmethod
    def _normalise_admin_level(raw_value: str | None) -> str | None:
        if not raw_value:
            return None
        value = raw_value.strip().lower()
        if value == "master_admin":
            return "master"
        if value in {"programme", "master"}:
            return value
        return None
