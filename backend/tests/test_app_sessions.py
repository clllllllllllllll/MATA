from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.services import app_sessions
from app.services.supabase_jwt import SupabaseJwtError
from app.services.supabase_password_auth import (
    GENERIC_STAFF_AUTH_ERROR,
    SupabasePasswordAuthError,
    authenticate_supabase_password,
)


def _settings(**overrides):
    values = {
        "environment": "test",
        "mata_session_hash_key": "unit-test-session-hash-key-32-bytes-minimum",
        "staff_session_idle_timeout_seconds": 30 * 60,
        "staff_session_absolute_timeout_seconds": 8 * 60 * 60,
        "resident_session_idle_timeout_seconds": 60 * 60,
        "resident_session_absolute_timeout_seconds": 12 * 60 * 60,
        "session_rotation_seconds": 15 * 60,
        "session_cleanup_retention_seconds": 7 * 24 * 60 * 60,
        "session_cleanup_batch_size": 500,
        "supabase_url": "https://project.supabase.co",
        "supabase_publishable_key": "sb_publishable_test_key",
        "supabase_anon_key": None,
        "supabase_service_role_key": "must-not-be-used",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushes = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, _statement, _params=None):
        return _ScalarResult(0)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    @property
    def rowcount(self) -> int:
        return 0


class _ResolveDb(_FakeDb):
    def __init__(self, value: object) -> None:
        super().__init__()
        self.value = value

    async def execute(self, _statement, _params=None):
        return _ScalarResult(self.value)


class _SubjectStateDb(_FakeDb):
    def __init__(self, generation: int | None) -> None:
        super().__init__()
        self.generation = generation

    async def execute(self, _statement, _params=None):
        return _ScalarResult(self.generation)


@pytest.mark.asyncio
async def test_create_session_uses_256_bit_opaque_tokens_and_digest_only_storage() -> None:
    settings = _settings()
    db = _FakeDb()
    now = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)

    created = await app_sessions.create_session(
        db,
        settings,
        "staff",
        uuid4(),
        "supabase_staff",
        expected_subject_session_generation=0,
        user_agent="Unit Test Browser",
        now=now,
    )

    session_bytes = app_sessions.parse_session_token(created.session_token)
    csrf_bytes = app_sessions.parse_csrf_token(created.csrf_token)
    assert session_bytes is not None and len(session_bytes) == 32
    assert csrf_bytes is not None and len(csrf_bytes) == 32
    assert created.session.token_digest != session_bytes
    assert created.session.csrf_token_digest != csrf_bytes
    assert created.session.token_digest != created.session.csrf_token_digest
    assert created.session.user_agent_hash is not None
    assert created.session.subject_session_generation == 0
    assert created.session.session_family_id == created.session.id
    assert b"Unit Test Browser" not in created.session.user_agent_hash
    assert created.session.idle_expires_at == now + timedelta(minutes=30)
    assert created.session.absolute_expires_at == now + timedelta(hours=8)
    assert db.added == [created.session]
    assert db.flushes == 1
    assert app_sessions.validate_csrf(
        created.session,
        created.csrf_token,
        settings,
        now=now,
    )


@pytest.mark.asyncio
async def test_session_creation_fails_closed_for_changed_or_blocked_subject() -> None:
    settings = _settings()
    subject_id = uuid4()

    with pytest.raises(app_sessions.AppSessionInvalidError):
        await app_sessions.create_session(
            _SubjectStateDb(1),
            settings,
            "staff",
            subject_id,
            "supabase_staff",
            expected_subject_session_generation=0,
        )

    with pytest.raises(app_sessions.AppSessionInvalidError):
        await app_sessions.create_session(
            _SubjectStateDb(None),
            settings,
            "staff",
            subject_id,
            "supabase_staff",
            expected_subject_session_generation=0,
        )


@pytest.mark.asyncio
async def test_hydration_csrf_is_stable_and_resolve_can_be_side_effect_free() -> None:
    settings = _settings()
    created = await app_sessions.create_session(
        _FakeDb(),
        settings,
        "resident",
        uuid4(),
        "mata_resident",
        expected_subject_session_generation=0,
        now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
    )
    before_last_seen = created.session.last_seen_at
    before_idle_expiry = created.session.idle_expires_at
    db = _ResolveDb(created.session)

    resolved = await app_sessions.resolve_session(
        db,
        settings,
        created.session_token,
        now=datetime(2026, 7, 22, 9, 5, tzinfo=UTC),
        touch=False,
    )

    assert resolved is created.session
    assert db.flushes == 0
    assert created.session.last_seen_at == before_last_seen
    assert created.session.idle_expires_at == before_idle_expiry
    assert (
        app_sessions.csrf_for_session_token(created.session_token, settings=settings)
        == created.csrf_token
    )
    assert (
        app_sessions.csrf_for_session_token(created.session_token, settings=settings)
        == created.csrf_token
    )


def test_raw_token_parser_rejects_noncanonical_or_malformed_values() -> None:
    valid = app_sessions._encode_raw_token(b"x" * 32)
    assert app_sessions.parse_session_token(valid) == b"x" * 32
    assert app_sessions.parse_session_token(valid + "=") is None
    assert app_sessions.parse_session_token(" " + valid) is None
    assert app_sessions.parse_session_token("not-base64!") is None
    assert app_sessions.parse_session_token(app_sessions._encode_raw_token(b"x" * 31)) is None
    assert app_sessions.parse_session_token(None) is None


@pytest.mark.asyncio
async def test_rotation_is_one_time_and_preserves_original_absolute_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    original = await app_sessions.create_session(
        _FakeDb(),
        settings,
        "external_resident",
        uuid4(),
        "mata_resident",
        expected_subject_session_generation=0,
        now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
    )

    async def _locked(_db, _session_id):
        return original.session

    monkeypatch.setattr(app_sessions, "_locked_session_by_id", _locked)
    rotation_time = datetime(2026, 7, 22, 9, 30, tzinfo=UTC)
    rotated = await app_sessions.rotate_session(
        _FakeDb(),
        settings,
        original.session,
        session_token=original.session_token,
        now=rotation_time,
    )

    assert original.session.revoked_at == rotation_time
    assert original.session.revoked_reason == "rotated"
    assert rotated.session.rotated_from_session_id == original.session.id
    assert rotated.session.session_family_id == original.session.session_family_id
    assert rotated.session.subject_session_generation == 0
    assert rotated.session.absolute_expires_at == original.session.absolute_expires_at
    assert rotated.session_token != original.session_token
    assert rotated.csrf_token != original.csrf_token
    assert not app_sessions.validate_csrf(
        original.session,
        original.csrf_token,
        settings,
        now=rotation_time,
    )
    assert app_sessions.validate_csrf(
        rotated.session,
        rotated.csrf_token,
        settings,
        now=rotation_time,
    )

    with pytest.raises(app_sessions.AppSessionInvalidError):
        await app_sessions.rotate_session(
            _FakeDb(),
            settings,
            original.session,
            session_token=original.session_token,
            now=rotation_time,
        )

    original.session.revoked_at = None
    original.session.revoked_reason = None
    with pytest.raises(app_sessions.AppSessionInvalidError):
        await app_sessions.rotate_session(
            _SubjectStateDb(1),
            settings,
            original.session,
            session_token=original.session_token,
            now=rotation_time,
        )


@pytest.mark.asyncio
async def test_invalid_csrf_inputs_fail_without_accepting_expired_session() -> None:
    settings = _settings()
    created = await app_sessions.create_session(
        _FakeDb(),
        settings,
        "staff",
        uuid4(),
        "supabase_staff",
        expected_subject_session_generation=0,
        now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
    )
    assert not app_sessions.validate_csrf(created.session, None, settings)
    assert not app_sessions.validate_csrf(created.session, "bad", settings)
    other = await app_sessions.create_session(
        _FakeDb(),
        settings,
        "staff",
        uuid4(),
        "supabase_staff",
        expected_subject_session_generation=0,
        now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
    )
    assert not app_sessions.validate_csrf(
        created.session,
        other.csrf_token,
        settings,
        now=datetime(2026, 7, 22, 9, 1, tzinfo=UTC),
    )
    assert not app_sessions.validate_csrf(
        created.session,
        created.csrf_token,
        settings,
        now=created.session.absolute_expires_at,
    )


class _Verifier:
    def __init__(self, claims=None, error: Exception | None = None) -> None:
        self.claims = claims or {"sub": str(uuid4()), "aud": "authenticated"}
        self.error = error
        self.tokens: list[str] = []

    async def verify(self, token: str):
        self.tokens.append(token)
        if self.error:
            raise self.error
        return self.claims


@pytest.mark.asyncio
async def test_supabase_password_sign_in_uses_publishable_key_and_returns_claims_only() -> None:
    captured: dict[str, object] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "access_token": "upstream-access-token",
                "refresh_token": "upstream-refresh-token",
                "user": {"id": "untrusted-body-user"},
            },
        )

    verifier = _Verifier(claims={"sub": str(uuid4()), "role": "authenticated"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        claims = await authenticate_supabase_password(
            email="staff@example.com",
            password="correct horse battery staple",
            settings=_settings(),
            verifier=verifier,
            client=client,
        )

    assert captured["url"] == (
        "https://project.supabase.co/auth/v1/token?grant_type=password"
    )
    headers = captured["headers"]
    assert headers["apikey"] == "sb_publishable_test_key"
    assert headers["apikey"] != "must-not-be-used"
    assert captured["body"] == {
        "email": "staff@example.com",
        "password": "correct horse battery staple",
    }
    assert verifier.tokens == ["upstream-access-token"]
    assert claims == verifier.claims
    assert "access_token" not in claims
    assert "refresh_token" not in claims


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
async def test_supabase_password_failures_are_generic(status_code: int) -> None:
    async def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "upstream detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        with pytest.raises(SupabasePasswordAuthError) as exc_info:
            await authenticate_supabase_password(
                email="staff@example.com",
                password="wrong",
                settings=_settings(),
                verifier=_Verifier(),
                client=client,
            )
    assert str(exc_info.value) == GENERIC_STAFF_AUTH_ERROR
    assert "upstream" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_supabase_password_rejects_unverified_access_token_generically() -> None:
    async def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "untrusted-token"})

    verifier = _Verifier(error=SupabaseJwtError("specific verifier detail"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        with pytest.raises(SupabasePasswordAuthError) as exc_info:
            await authenticate_supabase_password(
                email="staff@example.com",
                password="wrong",
                settings=_settings(),
                verifier=verifier,
                client=client,
            )
    assert str(exc_info.value) == GENERIC_STAFF_AUTH_ERROR
    assert verifier.tokens == ["untrusted-token"]
