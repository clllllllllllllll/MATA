from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import require_external_resident
from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity
from app.schemas.external_resident import (
    ExternalResidentPostingUpdateRequest,
    ExternalResidentRegisterRequest,
)
from app.services import external_residents


router = APIRouter(prefix="/external-residents", tags=["external-residents"])


try:
    from app.database import get_db_session
except Exception:

    async def get_db_session() -> AsyncIterator[AsyncSession | None]:
        yield None


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


@router.post("/register")
async def register_external_resident(
    request: ExternalResidentRegisterRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await external_residents.register_external_resident(
        db,
        name=request.name,
        mcr=request.mcr,
        home_cluster=request.home_cluster,
        current_nhg_posting_code=request.current_nhg_posting_code,
    )


@router.put("/me/posting")
async def update_my_posting(
    request: ExternalResidentPostingUpdateRequest,
    external_context: ExternalResidentContext = Depends(
        require_external_resident_context
    ),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await external_residents.update_my_posting(
        db,
        external_resident_id=external_context.external_resident_id,
        current_nhg_posting_code=request.current_nhg_posting_code,
    )
