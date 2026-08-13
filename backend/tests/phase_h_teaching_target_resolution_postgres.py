from __future__ import annotations

from collections.abc import AsyncIterator
import os
import re
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.database_context import attest_database_role
from app.services.teaching_target_resolution import (
    GlobalExcludedResolution,
    MappedTargetResolution,
    PendingMappingResolution,
    TeachingTargetResolutionUnavailable,
    resolve_native_teaching_target,
)
from tests.rls_postgres_harness import AUTH_GROUP, RUNTIME_GROUP, RlsPostgresHarness
from tests.test_rls_policy_postgres import (
    PolicyMatrixSeed,
    _runtime_context,
    policy_seed,
    test_phase_h_native_target_resolution_is_exact_and_re_reads_mapping as _test_mapping_resolution,
    test_phase_h_native_target_resolution_requires_native_adhoc_and_excludes_non_nhg as _test_native_adhoc_resolution,
)


PHASE_H_DATABASE_NAME = "mata_evolved_ttf_hij_verify"
PHASE_H_REQUIRED_REVISION = "20260805_000037"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_PHASE_H_SYNC_DATABASE_URL_ENV = "MATA_PHASE_H_SYNC_DATABASE_URL"
_PHASE_H_RUNTIME_ROLE = "MATA_PHASE_H_RUNTIME_ROLE"
_PHASE_H_RUNTIME_PASSWORD = "MATA_PHASE_H_RUNTIME_PASSWORD"
_PHASE_H_AUTH_ROLE = "MATA_PHASE_H_AUTH_ROLE"
_PHASE_H_AUTH_PASSWORD = "MATA_PHASE_H_AUTH_PASSWORD"
_TEST_ROLE_RE = re.compile(r"mata_test_(?:runtime|auth)_[0-9a-f]{16}")


def _is_phase_h_local_url(url: URL, *, async_url: bool) -> bool:
    expected_drivers = (
        {"postgresql+asyncpg"}
        if async_url
        else {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    )
    return (
        url.drivername in expected_drivers
        and url.host in _LOCAL_HOSTS
        and url.database == PHASE_H_DATABASE_NAME
        and bool(url.username)
        and not url.query
    )


@pytest_asyncio.fixture
async def policy_harness() -> AsyncIterator[RlsPostgresHarness]:
    configured_url = os.environ.get(_PHASE_H_SYNC_DATABASE_URL_ENV)
    if not configured_url:
        pytest.fail(
            f"{_PHASE_H_SYNC_DATABASE_URL_ENV} is required for Phase H PostgreSQL verification",
            pytrace=False,
        )
    owner_sync_url = make_url(configured_url)
    owner_async_url = owner_sync_url.set(drivername="postgresql+asyncpg")
    configured_runtime_url = os.environ.get("DATABASE_URL")
    configured_auth_url = os.environ.get("AUTH_DATABASE_URL")
    if not configured_runtime_url or not configured_auth_url:
        pytest.fail(
            "Phase H PostgreSQL verification requires runner-provided RLS URLs",
            pytrace=False,
        )
    runtime_async_url = make_url(configured_runtime_url)
    auth_async_url = make_url(configured_auth_url)
    runtime_role = os.environ.get(_PHASE_H_RUNTIME_ROLE, "")
    runtime_password = os.environ.get(_PHASE_H_RUNTIME_PASSWORD, "")
    auth_role = os.environ.get(_PHASE_H_AUTH_ROLE, "")
    auth_password = os.environ.get(_PHASE_H_AUTH_PASSWORD, "")
    if not (
        _is_phase_h_local_url(owner_sync_url, async_url=False)
        and _is_phase_h_local_url(owner_async_url, async_url=True)
        and _is_phase_h_local_url(runtime_async_url, async_url=True)
        and _is_phase_h_local_url(auth_async_url, async_url=True)
        and os.environ.get("DATABASE_RLS_ENABLED", "").lower() == "true"
    ):
        pytest.fail(
            "Phase H PostgreSQL verification requires the explicit local database "
            f"{PHASE_H_DATABASE_NAME}",
            pytrace=False,
        )
    if (
        _TEST_ROLE_RE.fullmatch(runtime_role) is None
        or _TEST_ROLE_RE.fullmatch(auth_role) is None
        or runtime_role == auth_role
        or not runtime_password
        or not auth_password
    ):
        pytest.fail(
            "Phase H PostgreSQL verification requires distinct runner-created test roles",
            pytrace=False,
        )

    admin_engine = create_engine(owner_sync_url, poolclass=NullPool)
    owner_engine: AsyncEngine | None = None
    runtime_engine: AsyncEngine | None = None
    auth_engine: AsyncEngine | None = None
    try:
        with admin_engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != PHASE_H_REQUIRED_REVISION:
                pytest.fail(
                    "Phase H PostgreSQL verification requires revision "
                    f"{PHASE_H_REQUIRED_REVISION}",
                    pytrace=False,
                )

        owner_engine = create_async_engine(owner_async_url, poolclass=NullPool)
        runtime_engine = create_async_engine(
            owner_async_url.set(username=runtime_role, password=runtime_password),
            pool_size=1,
            max_overflow=0,
            pool_timeout=5,
            pool_pre_ping=True,
        )
        auth_engine = create_async_engine(
            owner_async_url.set(username=auth_role, password=auth_password),
            pool_size=1,
            max_overflow=0,
            pool_timeout=5,
            pool_pre_ping=True,
        )

        yield RlsPostgresHarness(
            owner_engine=owner_engine,
            runtime_engine=runtime_engine,
            auth_engine=auth_engine,
            runtime_role=runtime_role,
            auth_role=auth_role,
            revision=str(revision),
        )
    finally:
        if runtime_engine is not None:
            await runtime_engine.dispose()
        if auth_engine is not None:
            await auth_engine.dispose()
        if owner_engine is not None:
            await owner_engine.dispose()
        admin_engine.dispose()


@pytest.mark.asyncio
async def test_phase_h_local_mapping_resolution(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    await _test_mapping_resolution(policy_harness, policy_seed)


@pytest.mark.asyncio
async def test_phase_h_local_native_adhoc_resolution(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    await _test_native_adhoc_resolution(policy_harness, policy_seed)


@pytest.mark.asyncio
async def test_phase_h_local_helper_acl_and_startup_attestation(
    policy_harness: RlsPostgresHarness,
) -> None:
    async with policy_harness.owner_session() as db:
        owner_role = await db.scalar(text("SELECT current_user"))
        helper = (
            await db.execute(
                text(
                    """
                    SELECT owner_role.rolname AS owner_role,
                           procedure.prosecdef AS security_definer,
                           procedure.proconfig AS config,
                           pg_catalog.has_function_privilege(
                               :runtime_role, procedure.oid, 'EXECUTE'
                           ) AS runtime_can_execute,
                           pg_catalog.has_function_privilege(
                               :auth_role, procedure.oid, 'EXECUTE'
                           ) AS auth_can_execute,
                           NOT EXISTS (
                               SELECT 1
                               FROM pg_catalog.aclexplode(
                                   COALESCE(
                                       procedure.proacl,
                                       pg_catalog.acldefault('f', procedure.proowner)
                                   )
                               ) AS privilege
                               WHERE privilege.grantee = 0
                                 AND privilege.privilege_type = 'EXECUTE'
                           ) AS public_is_denied
                    FROM pg_catalog.pg_proc AS procedure
                    JOIN pg_catalog.pg_roles AS owner_role
                      ON owner_role.oid = procedure.proowner
                    WHERE procedure.oid = pg_catalog.to_regprocedure(
                        'mata_rls.resolve_native_teaching_target(uuid,uuid)'
                    )
                    """
                ),
                {"runtime_role": RUNTIME_GROUP, "auth_role": AUTH_GROUP},
            )
        ).mappings().one()

    assert {
        key: helper[key]
        for key in (
            "owner_role",
            "security_definer",
            "runtime_can_execute",
            "auth_can_execute",
            "public_is_denied",
        )
    } == {
        "owner_role": owner_role,
        "security_definer": True,
        "runtime_can_execute": True,
        "auth_can_execute": False,
        "public_is_denied": True,
    }
    assert list(helper["config"] or []) == ["search_path=pg_catalog, pg_temp"]
    runtime_attestation = await attest_database_role(
        policy_harness.runtime_engine,
        capability_group=RUNTIME_GROUP,
        forbidden_capability_group=AUTH_GROUP,
        require_context_installer=True,
        require_policy_cutover=True,
    )
    auth_attestation = await attest_database_role(
        policy_harness.auth_engine,
        capability_group=AUTH_GROUP,
        forbidden_capability_group=RUNTIME_GROUP,
        require_context_installer=False,
        require_policy_cutover=True,
    )
    assert runtime_attestation.capability_group == RUNTIME_GROUP
    assert auth_attestation.capability_group == AUTH_GROUP


@pytest.mark.asyncio
async def test_phase_h_local_explicit_active_and_historical_inactive_globals_are_excluded(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    active_global_id = uuid4()
    inactive_global_id = uuid4()
    active_event_id = uuid4()
    inactive_event_id = uuid4()

    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO global_session_types (id, name, duration_hours, is_active)
                    VALUES
                        (:active_id, :active_name, 1.00, true),
                        (:inactive_id, :inactive_name, 1.00, true)
                    """
                ),
                {
                    "active_id": active_global_id,
                    "active_name": f"Phase H active global {active_global_id.hex}",
                    "inactive_id": inactive_global_id,
                    "inactive_name": f"Phase H historical global {inactive_global_id.hex}",
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_events (
                        id, posting_code, teaching_name, event_date, start_time,
                        end_time, duration_hours, is_adhoc, created_by_role,
                        global_session_type_id
                    )
                    VALUES
                        (
                            :active_event_id, :posting_code, 'Phase H active global',
                            DATE '2035-03-05', TIME '09:00', TIME '10:00', 1.00,
                            false, 'secretary', :active_global_id
                        ),
                        (
                            :inactive_event_id, :posting_code,
                            'Phase H historical global', DATE '2035-03-05',
                            TIME '09:00', TIME '10:00', 1.00, false, 'secretary',
                            :inactive_global_id
                        )
                    """
                ),
                {
                    "active_event_id": active_event_id,
                    "inactive_event_id": inactive_event_id,
                    "posting_code": values["posting_a"],
                    "active_global_id": active_global_id,
                    "inactive_global_id": inactive_global_id,
                },
            )
            await db.execute(
                text("UPDATE global_session_types SET is_active = false WHERE id = :id"),
                {"id": inactive_global_id},
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            active = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=active_event_id,
            )
            inactive = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=inactive_event_id,
            )

        assert active == GlobalExcludedResolution(
            kind="global_excluded",
            event_id=active_event_id,
            global_session_type_id=active_global_id,
        )
        assert inactive == GlobalExcludedResolution(
            kind="global_excluded",
            event_id=inactive_event_id,
            global_session_type_id=inactive_global_id,
        )
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text("DELETE FROM teaching_events WHERE id IN (:active_id, :inactive_id)"),
                {"active_id": active_event_id, "inactive_id": inactive_event_id},
            )
            await db.execute(
                text(
                    "DELETE FROM global_session_types WHERE id IN (:active_id, :inactive_id)"
                ),
                {"active_id": active_global_id, "inactive_id": inactive_global_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_phase_h_local_mapping_scope_isolated_by_programme_posting_r_year_and_period(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    alternate_target_id = uuid4()
    alternate_mapping_id = uuid4()
    alternate_period_id = uuid4()

    try:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_targets (
                        id, reporting_period_id, programme_code, r_year,
                        posting_code, session_type_id, monthly_target, is_tracked
                    )
                    VALUES (
                        :id, :reporting_period_id, :programme_code, 'R2',
                        :posting_code, :session_type_id, 1, true
                    )
                    """
                ),
                {
                    "id": alternate_target_id,
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_b"],
                    "session_type_id": values["session_type_id"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO teaching_name_mappings (
                        id, teaching_name_id, reporting_period_id, programme_code,
                        posting_code, r_year, teaching_target_id
                    )
                    VALUES (
                        :id, :teaching_name_id, :reporting_period_id,
                        :programme_code, :posting_code, 'R2', :target_id
                    )
                    """
                ),
                {
                    "id": alternate_mapping_id,
                    "teaching_name_id": values["teaching_name_a_id"],
                    "reporting_period_id": values["period_id"],
                    "programme_code": values["programme_a"],
                    "posting_code": values["posting_b"],
                    "target_id": alternate_target_id,
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            baseline = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=values["event_seed_a_id"],
            )
        assert isinstance(baseline, MappedTargetResolution)
        assert (baseline.mapping_id, baseline.teaching_target_id) == (
            values["mapping_a_id"],
            values["target_a_id"],
        )

        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    "UPDATE resident_postings SET posting_code = :posting_code, "
                    "r_year = 'R2' WHERE id = :id"
                ),
                {
                    "posting_code": values["posting_b"],
                    "id": values["resident_posting_a_id"],
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            alternate = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=values["event_seed_a_id"],
            )
        assert isinstance(alternate, MappedTargetResolution)
        assert (alternate.mapping_id, alternate.teaching_target_id) == (
            alternate_mapping_id,
            alternate_target_id,
        )

        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    "UPDATE resident_postings SET posting_code = :posting_code, "
                    "r_year = 'R1' WHERE id = :id"
                ),
                {
                    "posting_code": values["posting_a"],
                    "id": values["resident_posting_a_id"],
                },
            )
            await db.execute(
                text("UPDATE residents SET programme_code = :programme_code WHERE id = :id"),
                {
                    "programme_code": values["programme_b"],
                    "id": values["resident_a_id"],
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            with pytest.raises(TeachingTargetResolutionUnavailable) as programme_error:
                await resolve_native_teaching_target(
                    db,
                    resident_id=values["resident_a_id"],
                    event_id=values["event_seed_a_id"],
                )
        assert programme_error.value.reason == "source_programme_mismatch"

        async with policy_harness.owner_session() as db:
            await db.execute(
                text("UPDATE residents SET programme_code = :programme_code WHERE id = :id"),
                {
                    "programme_code": values["programme_a"],
                    "id": values["resident_a_id"],
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO reporting_periods (id, label, start_date, end_date, status)
                    VALUES (:id, :label, DATE '2034-01-01', DATE '2034-12-31', 'active')
                    """
                ),
                {
                    "id": alternate_period_id,
                    "label": f"H alternate {alternate_period_id.hex[:8]}",
                },
            )
            await db.execute(
                text(
                    "UPDATE resident_postings SET reporting_period_id = :period_id "
                    "WHERE id = :id"
                ),
                {
                    "period_id": alternate_period_id,
                    "id": values["resident_posting_a_id"],
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["master"],
        ) as db:
            with pytest.raises(TeachingTargetResolutionUnavailable) as period_error:
                await resolve_native_teaching_target(
                    db,
                    resident_id=values["resident_a_id"],
                    event_id=values["event_seed_a_id"],
                )
        assert period_error.value.reason == "native_phase_unavailable"
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    "UPDATE residents SET programme_code = :programme_code WHERE id = :id"
                ),
                {
                    "programme_code": values["programme_a"],
                    "id": values["resident_a_id"],
                },
            )
            await db.execute(
                text(
                    """
                    UPDATE resident_postings
                    SET reporting_period_id = :period_id, posting_code = :posting_code,
                        r_year = 'R1'
                    WHERE id = :id
                    """
                ),
                {
                    "period_id": values["period_id"],
                    "posting_code": values["posting_a"],
                    "id": values["resident_posting_a_id"],
                },
            )
            await db.execute(
                text("DELETE FROM teaching_name_mappings WHERE id = :id"),
                {"id": alternate_mapping_id},
            )
            await db.execute(
                text("DELETE FROM teaching_targets WHERE id = :id"),
                {"id": alternate_target_id},
            )
            await db.execute(
                text("DELETE FROM reporting_periods WHERE id = :id"),
                {"id": alternate_period_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_phase_h_local_target_scope_fk_and_defensive_resolver_check(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    constraint_dropped = False

    try:
        async with policy_harness.owner_session() as db:
            with pytest.raises(IntegrityError) as foreign_key_error:
                async with db.begin_nested():
                    await db.execute(
                        text(
                            "UPDATE teaching_name_mappings SET teaching_target_id = :target_id "
                            "WHERE id = :mapping_id"
                        ),
                        {
                            "target_id": values["target_b_id"],
                            "mapping_id": values["mapping_a_id"],
                        },
                    )
            assert getattr(foreign_key_error.value.orig, "sqlstate", None) == "23503"

            # The composite FK prevents this state in ordinary operation.  On the
            # isolated Phase H database, temporarily remove it to prove that the
            # resolver's defense-in-depth check still fails closed for corrupted
            # historical data, then restore the exact constraint below.
            await db.execute(
                text(
                    "ALTER TABLE public.teaching_name_mappings "
                    "DROP CONSTRAINT fk_teaching_name_mappings_target_scope"
                )
            )
            constraint_dropped = True
            await db.execute(
                text(
                    "UPDATE teaching_name_mappings SET teaching_target_id = :target_id "
                    "WHERE id = :mapping_id"
                ),
                {
                    "target_id": values["target_b_id"],
                    "mapping_id": values["mapping_a_id"],
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as db:
            with pytest.raises(TeachingTargetResolutionUnavailable) as mismatch_error:
                await resolve_native_teaching_target(
                    db,
                    resident_id=values["resident_a_id"],
                    event_id=values["event_seed_a_id"],
                )
        assert mismatch_error.value.reason == "target_scope_mismatch"
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    "UPDATE teaching_name_mappings SET teaching_target_id = :target_id "
                    "WHERE id = :mapping_id"
                ),
                {
                    "target_id": values["target_a_id"],
                    "mapping_id": values["mapping_a_id"],
                },
            )
            if constraint_dropped:
                await db.execute(
                    text(
                        """
                        ALTER TABLE public.teaching_name_mappings
                        ADD CONSTRAINT fk_teaching_name_mappings_target_scope
                        FOREIGN KEY (
                            teaching_target_id, reporting_period_id, programme_code,
                            posting_code, r_year
                        ) REFERENCES public.teaching_targets (
                            id, reporting_period_id, programme_code, posting_code, r_year
                        ) ON DELETE RESTRICT
                        """
                    )
                )
            await db.commit()


@pytest.mark.asyncio
async def test_phase_h_local_target_semantic_change_and_removal_re_read_without_evidence_writes(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values
    replacement_session_type_id = uuid4()
    original_target: dict[str, object] | None = None
    event_snapshot: object
    attendance_snapshot: object

    try:
        async with policy_harness.owner_session() as db:
            original_target = dict(
                (
                    await db.execute(
                        text(
                            """
                            SELECT session_type_id, monthly_target, is_tracked
                            FROM teaching_targets
                            WHERE id = :id
                            """
                        ),
                        {"id": values["target_a_id"]},
                    )
                ).mappings().one()
            )
            event_snapshot = await db.scalar(
                text(
                    "SELECT to_jsonb(event) FROM teaching_events AS event "
                    "WHERE id = :id"
                ),
                {"id": values["event_seed_a_id"]},
            )
            attendance_snapshot = await db.scalar(
                text(
                    "SELECT to_jsonb(attendance) FROM attendance_records AS attendance "
                    "WHERE id = :id"
                ),
                {"id": values["attendance_a_id"]},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO session_types (id, name, duration_hours, duration_label)
                    VALUES (:id, :name, 1.00, '1h')
                    """
                ),
                {
                    "id": replacement_session_type_id,
                    "name": f"Phase H semantic session {replacement_session_type_id.hex}",
                },
            )
            await db.execute(
                text(
                    """
                    UPDATE teaching_targets
                    SET session_type_id = :session_type_id,
                        monthly_target = 2,
                        is_tracked = false
                    WHERE id = :id
                    """
                ),
                {
                    "session_type_id": replacement_session_type_id,
                    "id": values["target_a_id"],
                },
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as db:
            changed = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=values["event_seed_a_id"],
            )
        assert isinstance(changed, MappedTargetResolution)
        assert (changed.teaching_target_id, changed.session_type_id) == (
            values["target_a_id"],
            replacement_session_type_id,
        )

        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    "UPDATE teaching_name_mappings SET teaching_target_id = NULL "
                    "WHERE id = :id"
                ),
                {"id": values["mapping_a_id"]},
            )
            await db.commit()

        async with _runtime_context(
            policy_harness,
            policy_seed.contexts["resident"],
        ) as db:
            pending = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=values["event_seed_a_id"],
            )
        assert isinstance(pending, PendingMappingResolution)
        assert pending.mapping_id == values["mapping_a_id"]

        async with policy_harness.owner_session() as db:
            assert await db.scalar(
                text(
                    "SELECT to_jsonb(event) FROM teaching_events AS event "
                    "WHERE id = :id"
                ),
                {"id": values["event_seed_a_id"]},
            ) == event_snapshot
            assert await db.scalar(
                text(
                    "SELECT to_jsonb(attendance) FROM attendance_records AS attendance "
                    "WHERE id = :id"
                ),
                {"id": values["attendance_a_id"]},
            ) == attendance_snapshot
    finally:
        async with policy_harness.owner_session() as db:
            await db.execute(
                text(
                    "UPDATE teaching_name_mappings SET teaching_target_id = :target_id "
                    "WHERE id = :mapping_id"
                ),
                {
                    "target_id": values["target_a_id"],
                    "mapping_id": values["mapping_a_id"],
                },
            )
            if original_target is not None:
                await db.execute(
                    text(
                        """
                        UPDATE teaching_targets
                        SET session_type_id = :session_type_id,
                            monthly_target = :monthly_target,
                            is_tracked = :is_tracked
                        WHERE id = :id
                        """
                    ),
                    {
                        "session_type_id": original_target["session_type_id"],
                        "monthly_target": original_target["monthly_target"],
                        "is_tracked": original_target["is_tracked"],
                        "id": values["target_a_id"],
                    },
                )
            await db.execute(
                text("DELETE FROM session_types WHERE id = :id"),
                {"id": replacement_session_type_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_phase_h_local_resolver_allows_only_signed_native_pc_or_master_contexts(
    policy_harness: RlsPostgresHarness,
    policy_seed: PolicyMatrixSeed,
) -> None:
    values = policy_seed.values

    for context_name in ("resident", "pc", "master"):
        async with _runtime_context(
            policy_harness,
            policy_seed.contexts[context_name],
        ) as db:
            resolution = await resolve_native_teaching_target(
                db,
                resident_id=values["resident_a_id"],
                event_id=values["event_seed_a_id"],
            )
        assert isinstance(resolution, MappedTargetResolution), context_name

    for context_name in ("resident_peer", "pc_null", "pc_empty", "secretary", "external"):
        async with _runtime_context(
            policy_harness,
            policy_seed.contexts[context_name],
        ) as db:
            raw_rows = (
                await db.execute(
                    text(
                        """
                        SELECT outcome
                        FROM mata_rls.resolve_native_teaching_target(
                            CAST(:resident_id AS uuid), CAST(:event_id AS uuid)
                        )
                        """
                    ),
                    {
                        "resident_id": values["resident_a_id"],
                        "event_id": values["event_seed_a_id"],
                    },
                )
            ).mappings().all()
            assert raw_rows == [], context_name
            with pytest.raises(TeachingTargetResolutionUnavailable) as unavailable:
                await resolve_native_teaching_target(
                    db,
                    resident_id=values["resident_a_id"],
                    event_id=values["event_seed_a_id"],
                )
        assert unavailable.value.reason == "not_available", context_name
