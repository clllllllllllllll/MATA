from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from starlette.responses import Response

from app.config import Settings
from app.models.session import AppSession
from app.services import app_sessions
from app.services.session_transport import set_session_cookie


SESSION_HASH_KEY = "session-lifecycle-assurance-test-key-32-bytes"
BASE_TIME = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "auth_mode": "stub",
        "auth_transport": "cookie",
        "database_rls_enabled": False,
        "mata_session_hash_key": SESSION_HASH_KEY,
        "staff_session_idle_timeout_seconds": 120,
        "staff_session_absolute_timeout_seconds": 600,
        "resident_session_idle_timeout_seconds": 180,
        "resident_session_absolute_timeout_seconds": 900,
        "session_rotation_seconds": 30,
        "session_touch_interval_seconds": 10,
        "session_cleanup_retention_seconds": 3600,
        "session_cleanup_batch_size": 100,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _declared_default_settings() -> Settings:
    session_fields = (
        "staff_session_idle_timeout_seconds",
        "staff_session_absolute_timeout_seconds",
        "resident_session_idle_timeout_seconds",
        "resident_session_absolute_timeout_seconds",
        "session_rotation_seconds",
        "session_touch_interval_seconds",
        "session_cleanup_retention_seconds",
        "session_cleanup_batch_size",
    )
    declared_defaults = {
        field: Settings.model_fields[field].default for field in session_fields
    }
    return Settings(
        _env_file=None,
        environment="test",
        auth_mode="stub",
        auth_transport="cookie",
        database_rls_enabled=False,
        **declared_defaults,
    )


def _session(
    *,
    subject_type: app_sessions.SessionSubjectType = "resident",
    created_at: datetime = BASE_TIME,
    last_seen_at: datetime = BASE_TIME,
    idle_expires_at: datetime = BASE_TIME + timedelta(minutes=3),
    absolute_expires_at: datetime = BASE_TIME + timedelta(minutes=15),
    token_digest: bytes = b"t" * 32,
) -> AppSession:
    session_id = uuid4()
    return AppSession(
        id=session_id,
        token_digest=token_digest,
        subject_type=subject_type,
        subject_id=uuid4(),
        subject_session_generation=0,
        session_family_id=session_id,
        auth_source=(
            "supabase_staff" if subject_type == "staff" else "mata_resident"
        ),
        csrf_token_digest=b"c" * 32,
        created_at=created_at,
        last_seen_at=last_seen_at,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        revoked_at=None,
        revoked_reason=None,
        rotated_from_session_id=None,
        user_agent_hash=None,
    )


class _ScalarResult:
    def __init__(self, value: object = 0) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    @property
    def rowcount(self) -> int:
        return 0


class _FakeSessionDb:
    def __init__(self, *, generation: int = 0) -> None:
        self.generation = generation
        self.rows: dict[UUID, AppSession] = {}
        self.added: list[AppSession] = []
        self.flushes = 0

    def add(self, value: AppSession) -> None:
        self.rows[value.id] = value
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(
        self,
        _statement: object,
        _parameters: object = None,
    ) -> _ScalarResult:
        return _ScalarResult(self.generation)


def _patch_local_row_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _locked(
        db: _FakeSessionDb,
        session_id: UUID,
    ) -> AppSession | None:
        return db.rows.get(session_id)

    monkeypatch.setattr(app_sessions, "_locked_session_by_id", _locked)


@pytest.mark.parametrize(
    ("system_role", "trusted_subject_type", "expected_timeouts"),
    [
        ("master_admin", "staff", (30 * 60, 8 * 60 * 60)),
        ("programme_coordinator", "staff", (30 * 60, 8 * 60 * 60)),
        ("department_secretary", "staff", (30 * 60, 8 * 60 * 60)),
        ("nhg_resident", "resident", (60 * 60, 12 * 60 * 60)),
        (
            "external_resident",
            "external_resident",
            (60 * 60, 12 * 60 * 60),
        ),
    ],
)
def test_default_timeout_class_for_each_system_role(
    system_role: str,
    trusted_subject_type: app_sessions.SessionSubjectType,
    expected_timeouts: tuple[int, int],
) -> None:
    settings = _declared_default_settings()

    assert system_role
    assert app_sessions._timeouts_for_subject(
        settings,
        trusted_subject_type,
    ) == expected_timeouts


@pytest.mark.parametrize("deadline", ["idle", "absolute"])
def test_validity_is_strict_immediately_before_and_at_each_deadline(
    deadline: str,
) -> None:
    idle_deadline = BASE_TIME + timedelta(seconds=30)
    absolute_deadline = (
        BASE_TIME + timedelta(seconds=60)
        if deadline == "idle"
        else idle_deadline
    )
    session = _session(
        idle_expires_at=idle_deadline,
        absolute_expires_at=absolute_deadline,
    )
    boundary = (
        session.idle_expires_at
        if deadline == "idle"
        else session.absolute_expires_at
    )

    assert app_sessions._is_active(
        session,
        now=boundary - timedelta(microseconds=1),
    )
    assert not app_sessions._is_active(session, now=boundary)


@pytest.mark.asyncio
async def test_touch_is_interval_gated_and_extends_idle_once_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        resident_session_idle_timeout_seconds=30,
        resident_session_absolute_timeout_seconds=120,
    )
    session = _session(
        idle_expires_at=BASE_TIME + timedelta(seconds=30),
        absolute_expires_at=BASE_TIME + timedelta(seconds=120),
    )
    db = _FakeSessionDb()
    db.rows[session.id] = session
    _patch_local_row_lock(monkeypatch)

    original_idle = session.idle_expires_at
    assert await app_sessions.touch_session(
        db,
        settings,
        session,
        now=BASE_TIME + timedelta(seconds=9, microseconds=999_999),
    )
    assert db.flushes == 0
    assert session.last_seen_at == BASE_TIME
    assert session.idle_expires_at == original_idle

    due_time = BASE_TIME + timedelta(seconds=10)
    assert await app_sessions.touch_session(
        db,
        settings,
        session,
        now=due_time,
    )
    assert db.flushes == 1
    assert session.last_seen_at == due_time
    assert session.idle_expires_at == BASE_TIME + timedelta(seconds=40)

    assert await app_sessions.touch_session(
        db,
        settings,
        session,
        now=due_time + timedelta(seconds=9, microseconds=999_999),
    )
    assert db.flushes == 1
    assert session.last_seen_at == due_time
    assert session.idle_expires_at == BASE_TIME + timedelta(seconds=40)


@pytest.mark.asyncio
async def test_recent_touch_is_capped_and_absolute_equality_still_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        resident_session_idle_timeout_seconds=30,
        resident_session_absolute_timeout_seconds=120,
    )
    absolute_deadline = BASE_TIME + timedelta(seconds=120)
    session = _session(
        last_seen_at=absolute_deadline - timedelta(seconds=11),
        idle_expires_at=absolute_deadline,
        absolute_expires_at=absolute_deadline,
    )
    db = _FakeSessionDb()
    db.rows[session.id] = session
    _patch_local_row_lock(monkeypatch)
    touch_time = absolute_deadline - timedelta(seconds=1)

    assert await app_sessions.touch_session(
        db,
        settings,
        session,
        now=touch_time,
    )
    assert db.flushes == 1
    assert session.last_seen_at == touch_time
    assert session.idle_expires_at == absolute_deadline
    assert app_sessions._is_active(
        session,
        now=absolute_deadline - timedelta(microseconds=1),
    )
    assert not app_sessions._is_active(session, now=absolute_deadline)


@pytest.mark.asyncio
@pytest.mark.parametrize("expired_by", ["idle", "absolute"])
async def test_touch_never_revives_an_expired_session(
    expired_by: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if expired_by == "idle":
        last_seen_at = BASE_TIME
        idle_expires_at = BASE_TIME + timedelta(seconds=20)
        absolute_expires_at = BASE_TIME + timedelta(seconds=120)
        current_time = idle_expires_at
    else:
        absolute_expires_at = BASE_TIME + timedelta(seconds=120)
        last_seen_at = absolute_expires_at - timedelta(seconds=20)
        idle_expires_at = absolute_expires_at
        current_time = absolute_expires_at
    session = _session(
        last_seen_at=last_seen_at,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )
    db = _FakeSessionDb()
    db.rows[session.id] = session
    _patch_local_row_lock(monkeypatch)
    original_last_seen = session.last_seen_at
    original_idle = session.idle_expires_at

    assert not await app_sessions.touch_session(
        db,
        _settings(
            resident_session_idle_timeout_seconds=30,
            resident_session_absolute_timeout_seconds=120,
        ),
        session,
        now=current_time,
    )
    assert db.flushes == 0
    assert session.last_seen_at == original_last_seen
    assert session.idle_expires_at == original_idle


@pytest.mark.asyncio
async def test_repeated_local_rotations_preserve_or_tighten_idle_and_absolute_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        resident_session_idle_timeout_seconds=1000,
        resident_session_absolute_timeout_seconds=1000,
    )
    raw_token = b"r" * app_sessions.SESSION_TOKEN_BYTES
    session_token = app_sessions._encode_raw_token(raw_token)
    token_digest = app_sessions._session_digest(
        raw_token,
        key=app_sessions._session_hash_key(settings),
    )
    family_deadline = BASE_TIME + timedelta(seconds=1000)
    original_idle_deadline = BASE_TIME + timedelta(seconds=300)
    original = _session(
        token_digest=token_digest,
        idle_expires_at=original_idle_deadline,
        absolute_expires_at=family_deadline,
    )
    db = _FakeSessionDb()
    db.rows[original.id] = original
    _patch_local_row_lock(monkeypatch)

    first = await app_sessions.rotate_session(
        db,
        settings,
        original,
        session_token=session_token,
        now=BASE_TIME + timedelta(seconds=100),
    )
    tightened_settings = settings.model_copy(
        update={"resident_session_idle_timeout_seconds": 50}
    )
    second = await app_sessions.rotate_session(
        db,
        tightened_settings,
        first.session,
        session_token=first.session_token,
        now=BASE_TIME + timedelta(seconds=200),
    )

    assert first.session.absolute_expires_at == family_deadline
    assert second.session.absolute_expires_at == family_deadline
    assert first.session.idle_expires_at == original_idle_deadline
    assert second.session.idle_expires_at == BASE_TIME + timedelta(seconds=250)
    assert first.session.last_seen_at == BASE_TIME
    assert second.session.last_seen_at == BASE_TIME
    assert first.session.session_family_id == original.session_family_id
    assert second.session.session_family_id == original.session_family_id
    assert original.revoked_reason == "rotated"
    assert first.session.revoked_reason == "rotated"
    assert len(db.added) == 2

    # Rotation at t=200 preserved an idle deadline at t=250.  Because refresh
    # did not pretend to be activity, a real mutation at t=201 is immediately
    # eligible and may slide idle expiry.
    assert await app_sessions.touch_session(
        db,
        tightened_settings,
        second.session,
        session_token=second.session_token,
        now=BASE_TIME + timedelta(seconds=201),
    )
    assert second.session.last_seen_at == BASE_TIME + timedelta(seconds=201)
    assert second.session.idle_expires_at == BASE_TIME + timedelta(seconds=251)

    with pytest.raises(
        app_sessions.AppSessionInvalidError,
        match="no longer active",
    ):
        await app_sessions.rotate_session(
            db,
            settings,
            second.session,
            session_token=second.session_token,
            now=second.session.idle_expires_at,
        )
    assert len(db.added) == 2


def test_cookie_is_intentionally_non_persistent() -> None:
    response = Response()

    set_session_cookie(
        response,
        settings=_settings(),
        session_token="opaque-session",
    )

    cookie = response.headers["set-cookie"]
    assert "opaque-session" in cookie
    assert "Max-Age=" not in cookie
    assert "Expires=" not in cookie


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "staff_session_idle_timeout_seconds": 601,
                "staff_session_absolute_timeout_seconds": 600,
            },
            "Staff idle timeout cannot exceed the absolute timeout",
        ),
        (
            {
                "resident_session_idle_timeout_seconds": 901,
                "resident_session_absolute_timeout_seconds": 900,
            },
            "Resident idle timeout cannot exceed the absolute timeout",
        ),
        (
            {"session_touch_interval_seconds": 120},
            "Session touch interval must be shorter than every idle timeout",
        ),
        (
            {"session_rotation_seconds": 600},
            "Session rotation threshold must be shorter than every absolute timeout",
        ),
    ],
)
def test_settings_reject_invalid_session_lifecycle_ordering(
    overrides: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _settings(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "staff_session_idle_timeout_seconds": 86_401,
            "staff_session_absolute_timeout_seconds": 86_401,
        },
        {
            "resident_session_idle_timeout_seconds": 86_401,
            "resident_session_absolute_timeout_seconds": 86_401,
        },
        {"staff_session_absolute_timeout_seconds": 604_801},
        {"resident_session_absolute_timeout_seconds": 604_801},
        {"session_cleanup_retention_seconds": 31_536_001},
        {"session_cleanup_batch_size": 1_001},
    ],
    ids=[
        "staff-idle",
        "resident-idle",
        "staff-absolute",
        "resident-absolute",
        "cleanup-retention",
        "cleanup-batch",
    ],
)
def test_settings_reject_values_above_postgresql_helper_bounds(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(
        ValueError,
        match="Security settings exceed PostgreSQL helper bounds",
    ):
        _settings(**overrides)
