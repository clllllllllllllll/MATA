from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from jwt.warnings import InsecureKeyLengthWarning

from app.config import Settings
from app.dependencies.auth import require_master_admin, require_programme_pc, require_resident
from app.middleware import install_error_handlers
from app.middleware.auth_stub import AuthIdentity, AuthStubMiddleware
from app.routers import admin, auth
from app.services.supabase_jwt import SupabaseJwtError, SupabaseJwtVerifier
from tests.resident_fakes import FakeResidentSession


ISSUER = "https://mata-test.supabase.co/auth/v1"
AUDIENCE = "authenticated"
KID = "mata-test-key"
RESIDENT_SECRET = "unit-test-resident-session-secret"


class _FakeScalarSession:
    def __init__(
        self,
        user: SimpleNamespace | None,
        resident: SimpleNamespace | None = None,
        external_resident: SimpleNamespace | None = None,
    ) -> None:
        self.user = user
        self.resident = resident
        self.external_resident = external_resident

    async def __aenter__(self) -> "_FakeScalarSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def scalar(self, statement) -> SimpleNamespace | None:  # noqa: ANN001
        if "FROM external_residents" in str(statement):
            return self.external_resident
        if "FROM residents" in str(statement):
            return self.resident
        return self.user


def _private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_for_key(private_key) -> dict:  # noqa: ANN001
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def _token(
    private_key,
    *,
    sub: str | None = None,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_delta: timedelta = timedelta(minutes=15),
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": sub or str(uuid4()),
        "role": "authenticated",
        "iat": now,
        "exp": now + expires_delta,
    }
    payload.update(extra_claims or {})
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": KID})


def _resident_token(
    fake_db: FakeResidentSession,
    *,
    secret: str = RESIDENT_SECRET,
    expires_delta: timedelta = timedelta(minutes=15),
    issuer: str = "mata-api",
    audience: str = "mata-resident-session",
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": fake_db.resident_id,
        "role": "resident",
        "app_role": "resident",
        "mcr": "M12345A",
        "programme_code": "GRM",
        "iat": now,
        "exp": now + expires_delta,
    }
    payload.update(extra_claims or {})
    return jwt.encode(
        payload,
        secret,
        algorithm="HS256",
    )


def _external_resident_token(
    fake_db: FakeResidentSession,
    *,
    secret: str = RESIDENT_SECRET,
    expires_delta: timedelta = timedelta(minutes=15),
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": "mata-api",
        "aud": "mata-resident-session",
        "sub": fake_db.external_resident_id,
        "role": "external_resident",
        "app_role": "external_resident",
        "mcr": "E12345A",
        "home_cluster": "NUH",
        "iat": now,
        "exp": now + expires_delta,
    }
    payload.update(extra_claims or {})
    return jwt.encode(
        payload,
        secret,
        algorithm="HS256",
    )


def _settings() -> Settings:
    return Settings(
        auth_mode="supabase",
        auth_transport="bearer_compat",
        supabase_url="https://mata-test.supabase.co",
        mata_resident_session_secret=RESIDENT_SECRET,
    )


def _user(
    *,
    user_id: UUID,
    role: str = "admin",
    admin_level: str = "programme",
    programme_scope: list[str] | None = None,
    posting_code: str | None = None,
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        role=role,
        admin_level=admin_level,
        programme_scope=programme_scope,
        posting_code=posting_code,
        is_active=is_active,
        session_generation=0,
        session_issuance_blocked=False,
    )


def _resident(fake_db: FakeResidentSession, *, status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(fake_db.resident_id),
        name="Resident One",
        mcr="M12345A",
        programme_code="GRM",
        status=status,
        session_generation=0,
    )


def _external_resident(
    fake_db: FakeResidentSession,
    *,
    status: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(fake_db.external_resident_id),
        name="External Resident One",
        mcr="E12345A",
        home_cluster="NUH",
        status=status,
        session_generation=0,
    )


def _auth_me_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    jwks: dict,
    middleware_user: SimpleNamespace | None,
    fake_db: FakeResidentSession,
    middleware_resident: SimpleNamespace | None = None,
    middleware_external_resident: SimpleNamespace | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    settings = _settings()

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    monkeypatch.setattr(
        "app.middleware.auth_stub.AsyncSessionLocal",
        lambda: _FakeScalarSession(
            middleware_user,
            middleware_resident,
            middleware_external_resident,
        ),
    )

    async def _db_override():
        yield fake_db

    app.dependency_overrides[auth.get_db_session] = _db_override
    app.add_middleware(AuthStubMiddleware, settings=settings)
    app.include_router(auth.router, prefix="/api/v1")
    return TestClient(app)


def _auth_admin_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    jwks: dict,
    middleware_user: SimpleNamespace | None,
    middleware_resident: SimpleNamespace | None,
    middleware_external_resident: SimpleNamespace | None = None,
    fake_db: FakeResidentSession,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    settings = _settings()

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    monkeypatch.setattr(
        "app.middleware.auth_stub.AsyncSessionLocal",
        lambda: _FakeScalarSession(
            middleware_user,
            middleware_resident,
            middleware_external_resident,
        ),
    )

    async def _db_override():
        yield fake_db

    app.dependency_overrides[auth.get_db_session] = _db_override
    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = lambda: settings
    app.add_middleware(AuthStubMiddleware, settings=settings)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    return TestClient(app)


def _identity_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    jwks: dict,
    middleware_user: SimpleNamespace | None,
    middleware_resident: SimpleNamespace | None = None,
    middleware_external_resident: SimpleNamespace | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    settings = _settings()

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    monkeypatch.setattr(
        "app.middleware.auth_stub.AsyncSessionLocal",
        lambda: _FakeScalarSession(
            middleware_user,
            middleware_resident,
            middleware_external_resident,
        ),
    )

    app.add_middleware(AuthStubMiddleware, settings=settings)

    @app.get("/api/v1/identity")
    async def identity_endpoint(identity: AuthIdentity = Depends(_current_identity)) -> dict:
        return {
            "role": identity.role,
            "subject_id": identity.subject_id,
            "programme_scope": identity.programme_scope,
            "admin_level": identity.admin_level,
            "posting_code": identity.posting_code,
            "mcr": identity.mcr,
            "home_cluster": identity.home_cluster,
        }

    return TestClient(app)


def _scope_guard_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    jwks: dict,
    middleware_user: SimpleNamespace | None,
    middleware_resident: SimpleNamespace | None = None,
    middleware_external_resident: SimpleNamespace | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    settings = _settings()

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    monkeypatch.setattr(
        "app.middleware.auth_stub.AsyncSessionLocal",
        lambda: _FakeScalarSession(
            middleware_user,
            middleware_resident,
            middleware_external_resident,
        ),
    )

    app.add_middleware(AuthStubMiddleware, settings=settings)

    @app.get("/api/v1/programme-pc")
    async def programme_pc_endpoint(
        identity: AuthIdentity = Depends(require_programme_pc),
    ) -> dict:
        return {"programme_scope": identity.programme_scope}

    @app.get("/api/v1/master-only")
    async def master_endpoint(
        identity: AuthIdentity = Depends(require_master_admin),
    ) -> dict:
        return {"admin_level": identity.admin_level}

    @app.get("/api/v1/resident-only")
    async def resident_endpoint(
        identity: AuthIdentity = Depends(require_resident),
    ) -> dict:
        return {
            "role": identity.role,
            "posting_code": identity.posting_code,
            "programme_code": identity.programme_code,
        }

    return TestClient(app)


async def _current_identity(request: Request) -> AuthIdentity:
    identity = getattr(request.state, "identity", None)
    if not isinstance(identity, AuthIdentity):
        raise AssertionError("identity missing")
    return identity


@pytest.mark.asyncio
async def test_supabase_jwt_verifier_accepts_valid_rs256_token(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = _private_key()
    jwks = _jwks_for_key(private_key)

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    verifier = SupabaseJwtVerifier(_settings())

    claims = await verifier.verify(_token(private_key, sub="00000000-0000-0000-0000-000000000001"))

    assert claims["sub"] == "00000000-0000-0000-0000-000000000001"
    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE


@pytest.mark.asyncio
async def test_supabase_jwt_verifier_rejects_undersized_rsa_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    jwks = _jwks_for_key(private_key)

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    verifier = SupabaseJwtVerifier(_settings())
    with pytest.warns(InsecureKeyLengthWarning):
        token = _token(private_key)

    with pytest.raises(SupabaseJwtError, match="Invalid Supabase JWT"):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_supabase_jwt_verifier_allows_small_iat_clock_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    jwks = _jwks_for_key(private_key)

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    verifier = SupabaseJwtVerifier(_settings())

    claims = await verifier.verify(_token(
        private_key,
        sub="00000000-0000-0000-0000-000000000001",
        extra_claims={"iat": datetime.now(UTC) + timedelta(seconds=5)},
    ))

    assert claims["sub"] == "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_supabase_jwt_verifier_rejects_large_iat_clock_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    jwks = _jwks_for_key(private_key)

    async def _fetch_jwks(self: SupabaseJwtVerifier) -> dict:
        return jwks

    monkeypatch.setattr(SupabaseJwtVerifier, "_fetch_jwks", _fetch_jwks)
    verifier = SupabaseJwtVerifier(_settings())

    with pytest.raises(SupabaseJwtError):
        await verifier.verify(_token(
            private_key,
            extra_claims={"iat": datetime.now(UTC) + timedelta(minutes=1)},
        ))


def test_supabase_mode_rejects_protected_request_without_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
    )

    response = client.get(
        "/api/v1/identity",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "DR",
            "X-Admin-Level": "master",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_supabase_mode_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = _private_key()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
    )

    response = client.get("/api/v1/identity", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_supabase_mode_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = _private_key()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
    )

    response = client.get(
        "/api/v1/identity",
        headers={
            "Authorization": f"Bearer {_token(private_key, expires_delta=timedelta(minutes=-1))}",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_supabase_mode_rejects_wrong_issuer_and_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = _private_key()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
    )

    wrong_issuer = client.get(
        "/api/v1/identity",
        headers={
            "Authorization": f"Bearer {_token(private_key, issuer='https://evil.example/auth/v1')}",
        },
    )
    wrong_audience = client.get(
        "/api/v1/identity",
        headers={
            "Authorization": f"Bearer {_token(private_key, audience='anon')}",
        },
    )

    assert wrong_issuer.status_code == 401
    assert wrong_audience.status_code == 401


def test_valid_supabase_token_maps_to_auth_me_from_users_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    supabase_user_id = uuid4()
    fake_db = FakeResidentSession()
    user_id = UUID(fake_db.admin_id)
    fake_db.users[0]["supabase_user_id"] = str(supabase_user_id)
    middleware_user = _user(
        user_id=user_id,
        role="admin",
        admin_level="programme",
        programme_scope=["GRM", "DR"],
    )
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_token(private_key, sub=str(supabase_user_id))}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == fake_db.admin_id
    assert response.json()["role"] == "admin"
    assert response.json()["admin_level"] == "programme"
    assert response.json()["programme_scope"] == ["GRM", "DR"]


def test_unmapped_supabase_user_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = _private_key()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_inactive_supabase_staff_user_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = _private_key()
    middleware_user = _user(user_id=uuid4(), role="admin", is_active=False)
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_master_admin_identity_comes_from_users_admin_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    user_id = uuid4()
    supabase_user_id = uuid4()
    middleware_user = _user(
        user_id=user_id,
        role="admin",
        admin_level="master",
        programme_scope=None,
    )
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_token(private_key, sub=str(supabase_user_id))}"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert response.json()["admin_level"] == "master"
    assert response.json()["programme_scope"] == []


def test_programme_scope_blank_only_is_denied_for_programme_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="admin",
        admin_level="programme",
        programme_scope=[""],
    )
    client = _scope_guard_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/programme-pc",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_programme_scope_null_or_empty_is_denied_for_programme_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    jwks = _jwks_for_key(private_key)
    for scope in (None, []):
        client = _scope_guard_client(
            monkeypatch,
            jwks=jwks,
            middleware_user=_user(
                user_id=uuid4(),
                role="admin",
                admin_level="programme",
                programme_scope=scope,
            ),
        )

        response = client.get(
            "/api/v1/programme-pc",
            headers={"Authorization": f"Bearer {_token(private_key)}"},
        )

        assert response.status_code == 403
        assert response.json()["error_code"] == "FORBIDDEN"


def test_programme_scope_null_does_not_imply_master_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="admin",
        admin_level="programme",
        programme_scope=None,
    )
    client = _scope_guard_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/master-only",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_programme_pc_identity_comes_from_users_programme_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="admin",
        admin_level="programme",
        programme_scope=["DR"],
    )
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 200
    assert response.json()["admin_level"] == "programme"
    assert response.json()["programme_scope"] == ["DR"]


def test_secretary_identity_comes_from_users_posting_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="secretary",
        posting_code="TTSHCardio",
    )
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "secretary"
    assert response.json()["posting_code"] == "TTSHCardio"


def test_secretary_missing_posting_scope_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="secretary",
        posting_code=None,
    )
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_supabase_mode_rejects_raw_identity_headers_even_with_valid_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="secretary",
        posting_code="TTSHCardio",
    )
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={
            "Authorization": f"Bearer {_token(private_key)}",
            "X-User-Role": "admin",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "DR",
            "X-Admin-Level": "master",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_supabase_user_metadata_cannot_grant_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="secretary",
        posting_code="TTSHCardio",
    )
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/identity",
        headers={
            "Authorization": "Bearer "
            + _token(
                private_key,
                extra_claims={
                    "user_metadata": {
                        "role": "admin",
                        "admin_level": "master",
                        "programme_scope": ["DR"],
                    },
                },
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["role"] == "secretary"
    assert response.json()["admin_level"] is None
    assert response.json()["programme_scope"] is None


def test_supabase_staff_token_is_rejected_on_resident_only_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    middleware_user = _user(
        user_id=uuid4(),
        role="admin",
        admin_level="programme",
        programme_scope=["DR"],
    )
    client = _scope_guard_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=middleware_user,
    )

    response = client.get(
        "/api/v1/resident-only",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_mata_resident_token_with_posting_claim_does_not_set_posting_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _scope_guard_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=_resident(fake_db),
    )

    response = client.get(
        "/api/v1/resident-only",
        headers={
            "Authorization": "Bearer "
            + _resident_token(fake_db, extra_claims={"posting_code": "TTSHCardio"}),
        },
    )

    assert response.status_code == 200
    assert response.json()["role"] == "resident"
    assert response.json()["posting_code"] is None


def test_mata_resident_token_wrong_issuer_or_audience_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _scope_guard_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=_resident(fake_db),
    )

    wrong_issuer = client.get(
        "/api/v1/resident-only",
        headers={
            "Authorization": "Bearer "
            + _resident_token(fake_db, issuer="https://mata-test.supabase.co/auth/v1"),
        },
    )
    wrong_audience = client.get(
        "/api/v1/resident-only",
        headers={
            "Authorization": "Bearer "
            + _resident_token(fake_db, audience="authenticated"),
        },
    )

    assert wrong_issuer.status_code == 401
    assert wrong_audience.status_code == 401


def test_mata_external_resident_token_with_posting_claim_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_external_resident=_external_resident(fake_db),
    )

    response = client.get(
        "/api/v1/identity",
        headers={
            "Authorization": "Bearer "
            + _external_resident_token(fake_db, extra_claims={"posting_code": "TTSHCardio"}),
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_mata_resident_token_maps_to_auth_me_without_staff_or_posting_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=_resident(fake_db),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_resident_token(fake_db)}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "id": fake_db.resident_id,
        "role": "resident",
        "name": "Resident One",
        "programme_code": "GRM",
        "mcr": "M12345A",
        "current_posting_code": "TTSHCardio",
        "current_posting_label": "TTSH Cardiology",
    }
    assert "posting_code" not in payload
    assert "staff_actor_name_required" not in payload
    assert "current_staff_actor_name" not in payload


def test_mata_external_resident_token_populates_external_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _identity_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_external_resident=_external_resident(fake_db),
    )

    response = client.get(
        "/api/v1/identity",
        headers={"Authorization": f"Bearer {_external_resident_token(fake_db)}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "external_resident"
    assert payload["subject_id"] == fake_db.external_resident_id
    assert payload["mcr"] == "E12345A"
    assert payload["home_cluster"] == "NUH"
    assert payload["posting_code"] is None
    assert payload["programme_scope"] is None
    assert payload["admin_level"] is None


def test_mata_external_resident_token_maps_to_auth_me_with_display_only_current_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_external_resident=_external_resident(fake_db),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_external_resident_token(fake_db)}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "id": fake_db.external_resident_id,
        "role": "external_resident",
        "name": "External Resident One",
        "mcr": "E12345A",
        "home_cluster": "NUH",
        "current_posting_code": "TTSHCardio",
        "current_posting_label": "TTSH Cardiology",
    }
    assert "current_nhg_posting_code" not in payload
    assert "posting_code" not in payload
    assert "staff_actor_name_required" not in payload
    assert "current_staff_actor_name" not in payload


def test_mata_resident_token_cannot_access_admin_staff_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_admin_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=_resident(fake_db),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/admin/staff-accounts",
        headers={"Authorization": f"Bearer {_resident_token(fake_db)}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_mata_external_resident_token_cannot_access_admin_staff_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_admin_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=None,
        middleware_external_resident=_external_resident(fake_db),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/admin/staff-accounts",
        headers={"Authorization": f"Bearer {_external_resident_token(fake_db)}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_mata_resident_token_rejects_inactive_resident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=_resident(fake_db, status="inactive"),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_resident_token(fake_db)}"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_mata_external_resident_token_rejects_inactive_external_resident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_external_resident=_external_resident(fake_db, status="inactive"),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_external_resident_token(fake_db)}"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_expired_mata_resident_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_resident=_resident(fake_db),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer "
            + _resident_token(fake_db, expires_delta=timedelta(minutes=-1)),
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_expired_mata_external_resident_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = _private_key()
    fake_db = FakeResidentSession()
    client = _auth_me_client(
        monkeypatch,
        jwks=_jwks_for_key(private_key),
        middleware_user=None,
        middleware_external_resident=_external_resident(fake_db),
        fake_db=fake_db,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer "
            + _external_resident_token(fake_db, expires_delta=timedelta(minutes=-1)),
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"
