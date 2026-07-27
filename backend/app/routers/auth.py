from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import (
    get_auth_db_session,
    get_db_session,
    get_exclusive_db_session,
    get_logout_db_session,
)
from app.dependencies.auth import require_authenticated
from app.dependencies.persistent_rate_limit import enforce_auth_login_persistent_rate_limit
from app.errors import ApiError, ErrorCode, build_error_response
from app.middleware.auth_stub import AuthIdentity
from app.schemas.auth import LoginRequest, LogoutResponse, SessionResponse, StaffActorNameRequest
from app.services import auth as auth_service
from app.services.app_sessions import (
    AppSessionInvalidError,
    create_session,
    csrf_for_session_token,
    revoke_session_family,
    rotate_session,
)
from app.services.session_transport import clear_session_cookie, set_session_cookie


router = APIRouter(prefix="/auth", tags=["auth"])


async def _persistent_login_rate_limit(
    request: Request,
    db: AsyncSession = Depends(get_auth_db_session),
    settings: Settings = Depends(get_settings),
) -> None:
    await enforce_auth_login_persistent_rate_limit(
        request,
        db=db,
        settings=settings,
    )


def _parse_subject(raw_value: str | None) -> UUID:
    if not raw_value:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    try:
        return UUID(raw_value)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc


@router.post("/login", dependencies=[Depends(_persistent_login_rate_limit)])
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_auth_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    if settings.auth_transport == "bearer_compat":
        return await auth_service.login(
            db,
            role=payload.role,
            email=payload.email,
            password=payload.password,
            mcr=payload.mcr,
            auth_mode=settings.auth_mode,
            settings=settings,
        )

    authenticated = await auth_service.authenticate_for_app_session(
        db,
        role=payload.role,
        email=payload.email,
        password=payload.password,
        mcr=payload.mcr,
        settings=settings,
    )
    created = await create_session(
        db,
        settings,
        subject_type=authenticated.subject_type,
        subject_id=authenticated.subject_id,
        auth_source=authenticated.auth_source,
        expected_subject_session_generation=authenticated.session_generation,
        normalized_mcr=authenticated.normalized_mcr,
        upstream_subject_id=authenticated.upstream_subject_id,
        user_agent=request.headers.get("User-Agent"),
    )
    await db.commit()
    set_session_cookie(
        response,
        settings=settings,
        session_token=created.session_token,
        absolute_expires_at=created.session.absolute_expires_at,
    )
    return SessionResponse(
        user=authenticated.user,
        csrf_token=created.csrf_token,
        session_refresh_required=False,
    ).model_dump()


@router.get("/me")
async def me(
    request: Request,
    identity: AuthIdentity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    role = identity.role
    if role not in {"admin", "secretary", "resident", "external_resident"}:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    user = await auth_service.get_current_identity(
        db,
        role=role,
        subject_id=_parse_subject(identity.subject_id),
    )
    raw_session_token = getattr(request.state, "session_token", None)
    app_session = getattr(request.state, "app_session", None)
    if not isinstance(raw_session_token, str) or app_session is None:
        # Explicit local/demo and emergency bearer compatibility only.
        return user
    csrf_token = csrf_for_session_token(raw_session_token, settings)
    refresh_required = (
        datetime.now(UTC) - app_session.created_at
    ).total_seconds() >= settings.session_rotation_seconds
    return SessionResponse(
        user=user,
        csrf_token=csrf_token,
        session_refresh_required=refresh_required,
    ).model_dump()


@router.post("/session/refresh", response_model=SessionResponse)
async def refresh_session(
    request: Request,
    response: Response,
    identity: AuthIdentity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_exclusive_db_session),
    settings: Settings = Depends(get_settings),
) -> SessionResponse | Response:
    app_session = getattr(request.state, "app_session", None)
    raw_session_token = getattr(request.state, "session_token", None)
    if app_session is None or not isinstance(raw_session_token, str):
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    try:
        rotated = await rotate_session(
            db,
            settings,
            app_session,
            session_token=raw_session_token,
            user_agent=request.headers.get("User-Agent"),
        )
    except AppSessionInvalidError:
        await db.rollback()
        error_response = build_error_response(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
        clear_session_cookie(error_response, settings=settings)
        return error_response
    user = await auth_service.get_current_identity(
        db,
        role=identity.role,
        subject_id=_parse_subject(identity.subject_id),
    )
    await db.commit()
    set_session_cookie(
        response,
        settings=settings,
        session_token=rotated.session_token,
        absolute_expires_at=rotated.session.absolute_expires_at,
    )
    return SessionResponse(
        user=user,
        csrf_token=rotated.csrf_token,
        session_refresh_required=False,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_logout_db_session),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    app_session = getattr(request.state, "app_session", None)
    if app_session is not None:
        await revoke_session_family(db, app_session, reason="logout")
        await db.commit()
    clear_session_cookie(response, settings=settings)
    return LogoutResponse(success=True)


@router.post("/staff-actor-name")
async def update_staff_actor_name(
    request: StaffActorNameRequest,
    identity: AuthIdentity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> dict:
    if identity.role not in {"admin", "secretary"}:
        raise ApiError(
            status_code=403,
            detail="Forbidden - staff role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    return await auth_service.update_staff_actor_name(
        db,
        user_id=_parse_subject(identity.subject_id),
        role=identity.role,
        full_name=request.full_name,
    )
