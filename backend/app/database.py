from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.services.database_context import (
    AUTH_BOUNDARY_INFO_KEY,
    MataSyncSession,
    RLS_ENABLED_INFO_KEY,
    RlsContextInvalidError,
    RlsLockMode,
    RlsRuntimeRoleError,
    RlsSubjectType,
    apply_context_to_identity,
    attest_database_role,
    clear_request_context,
    configure_request_context,
    prime_request_context,
)


settings = get_settings()

runtime_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

_auth_database_url = settings.auth_database_url or settings.database_url
if _auth_database_url == settings.database_url:
    auth_engine = runtime_engine
else:
    auth_engine = create_async_engine(
        _auth_database_url,
        pool_pre_ping=True,
    )

# Preserve the long-standing public engine name for migrations, tests, and
# non-RLS integrations. Protected request traffic uses this runtime engine.
engine = runtime_engine

RuntimeSessionLocal = async_sessionmaker(
    bind=runtime_engine,
    class_=AsyncSession,
    sync_session_class=MataSyncSession,
    expire_on_commit=False,
    autoflush=False,
    info={RLS_ENABLED_INFO_KEY: settings.database_rls_enabled},
)

AuthSessionLocal = async_sessionmaker(
    bind=auth_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    info={AUTH_BOUNDARY_INFO_KEY: settings.database_rls_enabled},
)

# Compatibility for authentication and persistent-rate-limit infrastructure
# that historically imported this sessionmaker directly. Normal handlers must
# use the protected get_db_session dependency instead.
AsyncSessionLocal = AuthSessionLocal


@asynccontextmanager
async def _protected_database_session(
    request: Request,
    *,
    lock_mode: RlsLockMode,
) -> AsyncIterator[AsyncSession]:
    async with RuntimeSessionLocal() as session:
        if not settings.database_rls_enabled:
            yield session
            return

        identity = getattr(request.state, "identity", None)
        app_session = getattr(request.state, "app_session", None)
        authorization_fingerprint = getattr(
            request.state,
            "authorization_fingerprint",
            None,
        )
        if identity is None or app_session is None:
            raise RlsContextInvalidError(
                "A verified application session is required"
            )

        expected_subject_type = cast(
            RlsSubjectType,
            str(getattr(app_session, "subject_type", "") or ""),
        )
        expected_subject_id = getattr(app_session, "subject_id", None)
        expected_app_session_id = getattr(app_session, "id", None)
        token_digest = getattr(app_session, "token_digest", b"")
        if not isinstance(authorization_fingerprint, str):
            raise RlsContextInvalidError(
                "Application authorization binding is missing"
            )

        configure_request_context(
            session,
            token_digest=token_digest,
            expected_subject_type=expected_subject_type,
            expected_subject_id=expected_subject_id,
            expected_app_session_id=expected_app_session_id,
            expected_authorization_fingerprint=authorization_fingerprint,
            lock_mode=lock_mode,
        )
        try:
            context = await prime_request_context(session)
            apply_context_to_identity(
                identity,
                context,
                expected_subject_type=expected_subject_type,
                expected_subject_id=expected_subject_id,
                expected_app_session_id=expected_app_session_id,
                expected_authorization_fingerprint=authorization_fingerprint,
            )
            yield session
        finally:
            clear_request_context(session)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with _protected_database_session(
        request,
        lock_mode="shared",
    ) as session:
        yield session


async def get_exclusive_db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    """Use for refresh/logout paths that must lock the family exclusively."""

    async with _protected_database_session(
        request,
        lock_mode="exclusive",
    ) as session:
        yield session


async def get_logout_db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    """Keep no/invalid-cookie logout idempotent; lock valid families exclusively."""

    if getattr(request.state, "app_session", None) is None:
        async with AuthSessionLocal() as session:
            yield session
        return

    async with _protected_database_session(
        request,
        lock_mode="exclusive",
    ) as session:
        yield session


async def get_auth_db_session() -> AsyncIterator[AsyncSession]:
    """Yield the narrow auth/helper boundary without installing user context."""

    async with AuthSessionLocal() as session:
        yield session


async def attest_database_boundaries() -> None:
    if not settings.database_rls_enabled:
        return

    runtime_attestation = await attest_database_role(
        runtime_engine,
        capability_group=settings.database_runtime_role,
        forbidden_capability_group=settings.database_auth_role,
        require_context_installer=True,
    )
    auth_attestation = await attest_database_role(
        auth_engine,
        capability_group=settings.database_auth_role,
        forbidden_capability_group=settings.database_runtime_role,
        require_context_installer=False,
    )
    if runtime_attestation.database_name != auth_attestation.database_name:
        raise RlsRuntimeRoleError(
            "Runtime and auth credentials reached different databases"
        )
    if runtime_attestation.login_role == auth_attestation.login_role:
        raise RlsRuntimeRoleError(
            "Runtime and auth credentials must use distinct login roles"
        )


async def dispose_database_engines() -> None:
    await runtime_engine.dispose()
    if auth_engine is not runtime_engine:
        await auth_engine.dispose()
