from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import (
    get_auth_db_session,
    get_db_session,
    get_exclusive_db_session,
)
from app.dependencies.auth import require_external_resident
from app.dependencies.persistent_rate_limit import (
    enforce_external_registration_persistent_rate_limit,
)
from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity
from app.schemas.external_resident import (
    ExternalResidentPostingScheduleUpdateRequest,
    ExternalResidentPostingUpdateRequest,
    ExternalResidentRegistrationOptions,
    ExternalResidentRegisterRequest,
)
from app.services import external_residents


router = APIRouter(prefix="/external-residents", tags=["external-residents"])


async def _persistent_registration_rate_limit(
    request: Request,
    db: AsyncSession = Depends(get_auth_db_session),
    settings: Settings = Depends(get_settings),
) -> None:
    await enforce_external_registration_persistent_rate_limit(
        request,
        db=db,
        settings=settings,
    )


@dataclass(slots=True)
class ExternalResidentContext:
    external_resident_id: UUID


async def require_external_resident_context(
    identity: AuthIdentity = Depends(require_external_resident),
) -> ExternalResidentContext:
    try:
        return ExternalResidentContext(external_resident_id=UUID(identity.subject_id))
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc


@router.get(
    "/registration-options",
    response_model=ExternalResidentRegistrationOptions,
)
async def list_registration_options(
    db: AsyncSession = Depends(get_auth_db_session),
) -> ExternalResidentRegistrationOptions:
    rows = await external_residents.list_registration_options(db)
    return ExternalResidentRegistrationOptions.model_validate(rows)


@router.post("/register", dependencies=[Depends(_persistent_registration_rate_limit)])
async def register_external_resident(
    request: ExternalResidentRegisterRequest,
    db: AsyncSession = Depends(get_auth_db_session),
) -> dict:
    return await external_residents.register_external_resident(
        db,
        name=request.name,
        mcr=request.mcr,
        home_cluster=request.home_cluster,
        posting_schedule=request.posting_schedule,
    )


@router.put("/me/posting")
async def update_my_posting(
    request: ExternalResidentPostingUpdateRequest,
    external_context: ExternalResidentContext = Depends(
        require_external_resident_context
    ),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> dict:
    return await external_residents.update_my_posting(
        db,
        external_resident_id=external_context.external_resident_id,
        programme_code=request.programme_code,
        institution=request.institution,
    )


@router.put("/me/posting-schedule")
async def replace_my_posting_schedule(
    request: ExternalResidentPostingScheduleUpdateRequest,
    external_context: ExternalResidentContext = Depends(
        require_external_resident_context
    ),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> dict:
    return await external_residents.replace_my_posting_schedule(
        db,
        external_resident_id=external_context.external_resident_id,
        posting_schedule=request.posting_schedule,
    )
