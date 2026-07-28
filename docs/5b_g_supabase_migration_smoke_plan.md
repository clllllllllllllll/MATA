# 5B-G-F Supabase Migration Smoke Plan

> **Current contract:** `docs/security.md`. This phase-specific smoke plan is
> retained as deployment evidence guidance and does not override the current
> security contract.

Status: Ready for dry-run execution

Last updated: 2026-07-06

## Purpose

This plan defines how to smoke test MATA Alembic migrations and required seed data against a clean Supabase-like PostgreSQL database before any production cutover.

It is an operational readiness plan only. It does not run migrations here, enable RLS, add RLS policy SQL, create real Supabase users, change application code, alter authentication transport, or implement compliance logic.

## Scope

Use this plan for:

- Local disposable PostgreSQL databases that mimic Supabase-supported extensions and Postgres behavior.
- Supabase staging projects created specifically for migration rehearsal.
- A production Supabase project only after explicit human confirmation, backup readiness, and a reviewed deployment window.

Do not use this plan as a blind production deployment script. Each step requires operator review of the target database, environment, and command output.

## Environment Assumptions

### Local Supabase-like database

- Database is disposable and can be dropped/recreated.
- The migration role can create or use the `pgcrypto` extension.
- `AUTH_MODE` may be `stub` or `demo` for local backend tests.
- No real Supabase project URL, service-role key, or production database URL is required.

### Staging Supabase project

- Database is empty or intentionally disposable.
- Project contains no production resident, attendance, staff, or upload data.
- The migration operator has a reviewed connection string and permission to run Alembic migrations.
- Supabase Auth settings may use staging-only values.

### Production Supabase project

- Production migration requires a confirmed deployment window, recent backup, rollback owner, and written operator confirmation.
- Do not point this plan at production if any variable, database host, or project reference is ambiguous.
- Do not print, paste, screenshot, or commit production connection strings, passwords, service-role keys, resident-token secrets, or JWT material.

## Required Environment Variables

Backend-only variables:

```text
DATABASE_URL=postgresql+asyncpg://<placeholder-user>:<placeholder-password>@<placeholder-host>:5432/<placeholder-db>
SYNC_DATABASE_URL=postgresql+psycopg://<placeholder-user>:<placeholder-password>@<placeholder-host>:5432/<placeholder-db>
ENV=development | test | staging | production
AUTH_MODE=stub | demo | supabase
MATA_RESIDENT_SESSION_SECRET=<placeholder-backend-only-secret>
SUPABASE_URL=https://<placeholder-project-ref>.supabase.co
SUPABASE_JWKS_URL=https://<placeholder-project-ref>.supabase.co/auth/v1/.well-known/jwks.json
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_JWT_ISSUER=https://<placeholder-project-ref>.supabase.co/auth/v1
SUPABASE_PUBLISHABLE_KEY=<placeholder-server-read-key>
SUPABASE_ANON_KEY=<placeholder-server-read-key-or-legacy-fallback>
SUPABASE_SERVICE_ROLE_KEY=<placeholder-backend-only-service-role-key>
```

Frontend-public variables are not used for migrations. Never create a `VITE_` variable for database URLs, resident-token secrets, service-role keys, JWT secrets, private keys, or passwords.

## Secrets Handling

- Do not read ignored `.env` files as part of review output.
- Do not commit any real URL, password, service-role key, JWT secret, resident-token secret, or Supabase project credential.
- Redact connection strings in copied logs. Keep only non-secret host/project labels when recording evidence.
- Prefer a password manager, deployment secret store, or CI secret store over shell history.
- Disable shell history or use approved secret injection if running commands manually on production-like hosts.

## Preflight Checklist

Before migration execution:

- Confirm the git branch and commit to be tested.
- Confirm the database target is empty, disposable, or backed up.
- Capture the current Alembic revision, if any.
- Confirm the migration role can create or use `pgcrypto`.
- Confirm `DATABASE_URL` uses the async driver and `SYNC_DATABASE_URL` uses the sync driver.
- Confirm `ENV` and `AUTH_MODE` match the target. Production-like environments should use `AUTH_MODE=supabase`.
- Confirm no real credentials are written into docs, `.env.example`, frontend env files, Vite build args, screenshots, or issue comments.
- Confirm the operator understands this plan does not bootstrap the first Master Admin; that is covered by `docs/5b_g_staff_bootstrap_runbook.md`.

Stop immediately if the target looks like production and the run was not explicitly approved for production.

## Migration Execution

From `backend/`, with dependencies installed:

```powershell
python -m pip install -r requirements.txt
alembic current
alembic upgrade head
alembic current
```

Expected result:

- `alembic upgrade head` completes without errors.
- `alembic current` reports the repository head revision.
- No migration output contains real credentials.
- No migration creates staff Supabase Auth users or assumes staff bootstrap is complete.

## Seed Verification SQL

Run these read-only checks after `alembic upgrade head`. Counts should be compared against the committed baseline and migration expectations for the tested commit.

```sql
SELECT count(*) AS programme_count FROM programmes;
SELECT code, r_year_required, is_subspecialty, rdb_alias
FROM programmes
WHERE code IN ('DR', 'FM', 'ORTHO', 'PALLMED', 'SPORTSMED')
ORDER BY code;

SELECT count(*) AS loa_type_count FROM loa_types;
SELECT count(*) AS posting_code_count FROM posting_codes;
SELECT code FROM posting_codes
WHERE code IN ('TTSHAnaes', 'TTSHGerMed', 'NHGPlyNHGPly', 'IMHGrPsyc & TTSHPsychi')
ORDER BY code;

SELECT name, duration_hours, is_active
FROM global_session_types
ORDER BY name;

SELECT programme_code, day_type, start_time_min, end_time_max, session_name_pattern
FROM weekend_exceptions
ORDER BY programme_code, day_type, start_time_min NULLS FIRST;

SELECT count(*) AS multi_posting_rule_count FROM multi_posting_rules;
SELECT count(*) AS reporting_period_count FROM reporting_periods;
```

Baseline expectations from `20260514_000001_current_baseline.py`:

- 28 programmes.
- 14 LOA types.
- Required posting codes include `TTSHAnaes`, `TTSHGerMed`, `NHGPlyNHGPly`, and combined labels such as `IMHGrPsyc & TTSHPsychi`.
- `Department Meeting [1h]` exists in `global_session_types`.
- Weekend exceptions include URO, DERM, and ORTHO rows, with ORTHO configured for Saturday 08:30 to 10:30 read-time mutation metadata.
- Reporting periods may be empty on a clean database unless separately seeded by an operator or upload workflow.
- Staff users may be empty on a clean database. First Master Admin bootstrap is a separate operational step.

## Schema Verification SQL

These checks verify key Supabase-readiness invariants and project decisions.

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'programmes'
  AND column_name IN ('compliance_variant', 'native_teaching_posting_code');

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'attendance_records'
  AND column_name = 'session_type_id';

SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'users'
  AND column_name IN ('admin_level', 'supabase_user_id');

SELECT constraint_name
FROM information_schema.table_constraints
WHERE table_schema = 'public'
  AND table_name = 'users'
  AND constraint_name IN ('ck_users_admin_level', 'uq_users_supabase_user_id');

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'external_residents',
    'external_resident_postings',
    'external_attendance_records'
  )
ORDER BY table_name;

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'teaching_events'
  AND column_name = 'created_for_programme_code';
```

Expected schema posture:

- `programmes.compliance_variant` must be absent.
- `programmes.native_teaching_posting_code` should be present after the Phase 5B native teaching posting migration.
- `attendance_records.session_type_id` must be absent.
- `users.admin_level` must be present and constrained to explicit admin levels.
- `users.supabase_user_id` must be nullable and unique.
- `external_residents`, `external_resident_postings`, and `external_attendance_records` must exist as separate Non-NHG tables.
- `teaching_events.created_for_programme_code` should exist for PC-created programme-owned scheduled events.

## Upload And Admin Smoke Prerequisites

Migration smoke success is necessary but not sufficient for a usable UAT/prod database. Before staff or resident flows are tested, complete these application-level prerequisites in order:

1. Upload Academic Calendar / Public Holidays so `public_holidays` and `academic_month_boundaries` are populated.
2. Upload RDB so native residents, postings, and rotation schedules exist.
3. Upload TTF so session types, teaching targets, posting groups, and `teaching_name_catalogue` are populated.
4. Upload FormF1 so active/inactive month records exist.
5. Bootstrap the first Master Admin and map `users.supabase_user_id` to the corresponding Supabase Auth staff subject.
6. Create any required staff accounts through the Master Admin flow.

Do not infer Master Admin from missing or empty programme scope. Master Admin is explicit through `users.admin_level = 'master'`.

## Rollback And Recovery

- Prefer restoring from a verified database backup or recreating a disposable database.
- Do not run blind Alembic downgrades against production data.
- Record the git commit, Alembic head revision, database project/ref label, operator, timestamp, and smoke-test result.
- If migration fails before any user data exists, recreate the disposable database and rerun from a known clean state.
- If migration fails after data exists, stop and assign a database owner to inspect the failure before further commands.

## CI And Staging Recommendation

- Maintain a clean disposable database rehearsal before production.
- Run backend tests against local PostgreSQL with the same migration head when possible.
- Keep staging Supabase separate from production and seeded only with synthetic or approved test data.
- Capture seed/schema check output in deployment notes with secrets redacted.

## Stop Conditions

Stop the smoke run if any of these occur:

- `pgcrypto` cannot be created or used by the migration role.
- Alembic reports a missing migration, multiple heads, or unexpected current revision.
- Seed counts or critical seed values differ from the committed baseline without an explained migration.
- The target is a real production database and explicit production confirmation is missing.
- Command output contains real secrets or unredacted connection strings.
- `users.supabase_user_id` is missing, non-unique, or treated as required for local stub/demo users.
- External resident tables are missing or appear merged into native resident tables.
- A migration adds `programmes.compliance_variant` or `attendance_records.session_type_id`.

## Acceptance Checklist

- Migration target confirmed and recorded.
- `alembic upgrade head` completed successfully.
- Alembic current revision equals repository head.
- Required seed checks passed or differences were explained by committed migrations.
- Required schema checks passed.
- No real secrets were printed, committed, or copied into browser-exposed variables.
- Staff bootstrap status is recorded separately.
- RLS/grants/Data API work remains deferred to its dedicated future phase.
