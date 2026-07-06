# Phase 5B-G Supabase Production Readiness Audit

Status: Ready for 5B-G-D/E/F/G

Last updated: 2026-07-06

## Scope

This audit covers Phase 5B-G-A/B/C: Supabase-hosted Postgres readiness, Supabase Auth/staff mapping readiness, MATA resident token readiness, raw-header rejection, frontend/env secret exposure, RLS planning, Non-NHG data separation, environment documentation hardening, and targeted auth guardrail tests.

This audit does not enable RLS, add RLS policies, implement compliance, or implement Phase 5B-H cookie/BFF/CSRF/session hardening. Supabase internet documentation was not fetched because this chained task explicitly says not to rely on internet access; local source-of-truth docs and implementation were used.

## Files Inspected

- `AGENTS.md`
- `docs/00_project_context.md`
- `docs/auth-account-contract.md`
- `docs/api.md`
- `docs/schema.md`
- `docs/business-logic.md`
- `docs/99_decision_log_and_gap_audit.md`
- `.env.example`
- `README.md`
- `docs/dev_setup.md`
- `frontend/README.md`
- `docker-compose.yml`
- `frontend/Dockerfile`
- `backend/Dockerfile`
- `.github/workflows/backend-ci.yml`
- `backend/alembic/env.py`
- `backend/alembic/versions/*.py`
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/middleware/auth_stub.py`
- `backend/app/middleware/rate_limit.py`
- `backend/app/middleware/security.py`
- `backend/app/dependencies/auth.py`
- `backend/app/dependencies/staff_actor.py`
- `backend/app/routers/admin.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/external_residents.py`
- `backend/app/routers/resident.py`
- `backend/app/services/auth.py`
- `backend/app/services/mata_resident_token.py`
- `backend/app/services/supabase_jwt.py`
- `backend/app/services/supabase_admin.py`
- `backend/app/services/external_residents.py`
- `backend/app/services/resident_submission.py`
- `backend/app/services/admin_external_attendance.py`
- `backend/app/models/resident.py`
- `backend/app/models/attendance.py`
- `frontend/src/api/auth.ts`
- `frontend/src/api/authHeaders.ts`
- `frontend/src/api/http.ts`
- `frontend/src/api/supabaseClient.ts`
- `frontend/src/config/frontendConfig.ts`
- `backend/tests/test_auth_modes.py`
- `backend/tests/test_auth_supabase.py`
- `backend/tests/test_auth_resident.py`
- `backend/tests/test_external_auth.py`
- `backend/tests/auth_identity_test_helpers.py`
- `backend/tests/resident_fakes.py`

## Current Readiness Summary

Status: Ready for next subphase

The core production-auth shape is in place. `AUTH_MODE=supabase` and `ENV=production` route protected requests through bearer-token verification instead of raw `X-User-*` identity headers. Staff Supabase tokens map by `claims.sub` to `users.supabase_user_id`; MATA role, admin level, programme scope, secretary posting, and staff actor metadata come from the active `users` row. Supabase `user_metadata` is not an authorization source.

NHG Residents and Non-NHG Residents use backend-signed MATA resident tokens in Supabase mode. These tokens use a distinct issuer/audience and reload active `residents` or `external_residents` rows server-side on protected requests. Non-NHG storage remains separate through `external_residents`, `external_resident_postings`, and `external_attendance_records`.

No real committed secret was found in the inspected env/deployment files. The frontend only receives public Vite variables for Supabase URL and publishable/anon keys. `.env.example` and `README.md` now explicitly separate backend-only server variables from browser-exposed `VITE_*` variables.

## Supabase DB / Alembic Findings

Status: Ready

Alembic is configured through `backend/alembic/env.py` to use `SYNC_DATABASE_URL`, which matches the async runtime / sync migration split. The migration chain is linear from `20260514_000001` through `20260704_000014`.

The clean baseline migration creates `pgcrypto` with `CREATE EXTENSION IF NOT EXISTS pgcrypto` and uses `gen_random_uuid()` for UUID primary keys. This is Supabase/Postgres-compatible, assuming the migration role has permission to create or use the extension. The baseline also uses Postgres-specific constructs already expected by this project: `JSONB`, `ARRAY`, GIN indexes, partial indexes, and `UNIQUE NULLS NOT DISTINCT`.

Clean database migration risk is moderate but understandable: `20260514_000001_current_baseline.py` is both schema baseline and seed bootstrap for reference/config data. That makes a clean Supabase DB depend on baseline seed ordering as well as schema ordering. Later migrations add active reporting-period status, warning tables, programme teaching fields, explicit admin level, `users.supabase_user_id`, staff actor metadata, and native teaching posting mapping in order.

No RLS, grants, exposed-schema review, or Supabase Data API posture is implemented here. That is expected for this phase and remains deferred.

## Seed / Bootstrap Findings

Status: Follow-up required in 5B-G-D

The baseline migration seeds programmes, LOA types, posting codes, session types, global session types, weekend exceptions, and multi-posting rules. These seeds do not look local-only and are required reference/config data for clean deployments.

Staff user bootstrap is not production-ready yet. There is no production seed or runbook that creates the first Master Admin and maps `users.supabase_user_id` to Supabase Auth `auth.users.id`. `backend/scripts/reset_demo_staff_logins.py` is deliberately local-only: it refuses non-development/test environments and refuses `AUTH_MODE=supabase`. That is good safety behavior, but production still needs an explicit bootstrap/provisioning step.

The staff account management service can create Supabase Auth users with `SUPABASE_SERVICE_ROLE_KEY` and persist `users.supabase_user_id`, but this depends on having an already-authorized Master Admin. The first-account bootstrap remains a follow-up operational task, not something to infer from `programme_scope = NULL`.

## Auth Mapping Findings

Status: Ready

`backend/app/middleware/auth_stub.py` is the central auth choke point. In Supabase-required modes, it extracts `Authorization: Bearer ...`, detects MATA resident-token family first by issuer/audience/app role, otherwise verifies a Supabase JWT, then maps:

- Supabase staff token `sub` -> `users.supabase_user_id`
- MATA NHG Resident token `sub` -> active `residents.id`
- MATA Non-NHG Resident token `sub` -> active `external_residents.id`

Staff identity comes from the DB row: `role`, `admin_level`, `programme_scope`, `posting_code`, and `current_staff_actor_name`. Supabase token metadata is ignored for MATA authorization.

`backend/app/dependencies/auth.py` correctly treats master admin as explicit `role = admin` plus `admin_level = master`. Programme PC access rejects explicit master accounts and rejects empty/falsey programme scope. Secretary access requires a non-empty DB-owned posting scope.

Resident token signing in `backend/app/services/mata_resident_token.py` avoids trusted posting claims. NHG Resident tokens include `programme_code`, but protected route identity reloads the resident row. Non-NHG Resident tokens reject injected `current_nhg_posting_code`, `posting_code`, `posting_schedule`, `programme_code`, `programme_scope`, `admin_level`, and staff actor claims.

Phase 5B-G-C tightened programme scope normalization at the central identity/dependency boundary. `NULL`, empty arrays, blank strings, and whitespace-only programme scope values resolve to no PC access. Master admin remains explicit via `users.admin_level = master`; it is never inferred from null or empty `programme_scope`.

## Production Raw-Header Rejection Findings

Status: Ready

Direct raw-header reads were found only in the following runtime paths:

- `backend/app/middleware/auth_stub.py`: acceptable stub/demo infrastructure. Reads `X-User-Role`, `X-User-Id`, `X-User-Programme`, and `X-User-Site` only when `environment != production` and `auth_mode in {"stub", "demo"}`. In `AUTH_MODE=supabase` or production, protected routes require bearer-token auth.
- `backend/app/routers/admin.py::require_admin_context`: legacy test/demo fallback. It prefers `request.state.identity`; direct `X-User-*` / `X-Admin-Level` parsing is disabled when `environment == production` or `auth_mode` is not `stub`/`demo`.
- `backend/app/dependencies/staff_actor.py::require_staff_actor`: legacy test/demo fallback. It prefers `request.state.identity`; direct staff actor header parsing is disabled in production and Supabase mode.
- `backend/app/middleware/rate_limit.py::_build_bucket_key`: request bucketing only, not authorization. It uses verified identity when present, raw headers only in stub/demo, and anonymous/unknown values otherwise.
- `frontend/src/api/auth.ts`: local/demo stub header construction only.
- `frontend/src/api/http.ts`: strips `X-User-*`, `X-User-MCR`, and `X-Admin-Level` in Supabase frontend mode before attaching a Supabase or MATA bearer token.

Existing tests verify that `AUTH_MODE=supabase` rejects raw headers without a bearer token, that Supabase mode ignores conflicting raw headers when a valid bearer token is present, and that rate-limit bucketing does not trust raw identity headers in Supabase mode.

Phase 5B-G-C added a targeted production-mode guardrail test proving `ENV=production` rejects raw identity headers even when `AUTH_MODE=stub` is misconfigured.

Generated OpenAPI/docs may still display raw header parameters for endpoints whose dependencies retain stub/demo fallback headers. This is not an authorization path in production, but it can confuse deployment/API consumers and should be reviewed after C.

## Frontend Env and Secret Exposure Findings

Status: Ready

No backend-only secret was found being passed to frontend build args or Vite variables in the inspected committed files. `docker-compose.yml` and `frontend/Dockerfile` pass only:

- `VITE_API_BASE_URL`
- `VITE_APP_ENV`
- `VITE_AUTH_MODE`
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`
- `VITE_SUPABASE_ANON_KEY`
- local/demo Vite defaults such as demo user ids, demo programme scope, and default reporting period

`frontend/src/config/frontendConfig.ts` reads both `VITE_SUPABASE_PUBLISHABLE_KEY` and `VITE_SUPABASE_ANON_KEY`. `frontend/src/api/supabaseClient.ts` prefers the publishable key and falls back to the anon key for compatibility. This compatibility behavior is intentional; do not remove either variable unless code/tests prove one is obsolete.

Backend `backend/app/services/supabase_admin.py` uses `SUPABASE_SERVICE_ROLE_KEY` server-side only for Supabase Admin user create/reset calls. Backend `backend/app/services/supabase_jwt.py` uses `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_ANON_KEY` for legacy HS256 Auth-server validation, not service-role verification.

`frontend/src/api/authSessionStore.ts` stores bearer session state in browser `sessionStorage`. This is already explicitly deferred to Phase 5B-H and must not be changed in this phase.

## `.env.example` / Deployment Guidance Findings

Status: Ready

`.env.example` contains placeholders only. The local development database URL uses the local Docker `postgres:postgres` credential, not a production credential. The production examples use angle-bracket placeholders for Supabase host/user/password/project ref and backend-only secrets.

Hardening completed in Phase 5B-G-B:

- Separate backend-only variables from frontend/browser-exposed variables in `.env.example`.
- Explicitly state that all `VITE_*` variables are public browser-exposed values.
- Document that `SUPABASE_SERVICE_ROLE_KEY` and `MATA_RESIDENT_SESSION_SECRET` are backend-only and must never use a `VITE_` prefix.
- Document production required backend variables and production required frontend variables.
- Update `README.md` because its environment table still lists generic `SECRET_KEY`, while implemented code uses `MATA_RESIDENT_SESSION_SECRET` for MATA resident tokens and Supabase-specific backend settings for Supabase mode.

The local `.env` file exists but is ignored by `.gitignore`; it was not read or printed.

## RLS Readiness Plan Summary

Status: Deferred

RLS should be planned later for sensitive tables, but it is intentionally not enabled in Phase 5B-G-A/B/C.

Likely RLS categories:

- Staff/admin tables: `users`, audit/config/admin read models. Direct client access should remain avoided; backend service-role or server-only access is preferred.
- Native resident tables: `residents`, `resident_postings`, `attendance_records`, native resident dashboard/history surfaces.
- Non-NHG resident tables: `external_residents`, `external_resident_postings`, `external_attendance_records`, scoped separately from native residents.
- Teaching and config tables: `teaching_events`, `teaching_name_catalogue`, `teaching_targets`, `posting_codes`, `posting_groups`, `global_session_types`, `weekend_exceptions`, `reporting_periods`.
- Upload/admin tables: `upload_logs`, `warning_issues`, `upload_warnings`, parser outputs and admin mutation audit data.

Backend operations that span many residents, programmes, uploads, reports, or external attendance exports will likely need privileged server-side access. App-level authorization remains required even after RLS because MATA scope rules are richer than row ownership: programme PC scope, explicit master admin, secretary posting scope, resident-vs-external identity families, event visibility gates, and future period/reporting rules.

Do not enable RLS prematurely. The app currently uses backend-mediated access, and RLS policies need a dedicated policy matrix plus Supabase grant/Data API review.

## Non-NHG Separation Findings

Status: Ready

Non-NHG identity and attendance storage are separated from native NHG storage:

- Staff/admin/secretary accounts: `users`
- Native NHG Residents: `residents` and `resident_postings`
- Non-NHG Residents: `external_residents` and `external_resident_postings`
- Native attendance: `attendance_records`
- Non-NHG attendance: `external_attendance_records`

`backend/app/routers/resident.py` branches native vs external resident behavior from verified central identity. `backend/app/services/resident_submission.py` writes native submissions to `attendance_records` and Non-NHG submissions to `external_attendance_records`. `GET /resident/dashboard` for Non-NHG Residents returns `not_applicable` rather than native compliance metrics.

`backend/app/services/admin_external_attendance.py` reads/export only `external_attendance_records` joined to `external_residents` and `teaching_events`, with programme scoping derived through catalogue/target context. It marks records as export-only and not compliance-included.

Some event-management services check both native and external attendance tables before allowing destructive event edits/deletes. That is an acceptable operational guard, not a compliance join. Phase 6 compliance must continue to read native `attendance_records` only and must never join `external_attendance_records`.

## Recommended 5B-G Follow-up Subphases

Status: Ready

- `5B-G-D`: define production staff bootstrap/runbook for first Master Admin and `users.supabase_user_id` mapping.
- `5B-G-E`: write an RLS policy matrix and Supabase exposed-schema grant plan.
- `5B-G-F`: deployment smoke plan for clean Supabase database migrations, extension availability, and seed ordering.
- `5B-G-G`: service-role / privileged backend access review for admin reports, uploads, staff provisioning, and exports.

## Blocking Issues

Status: Ready

No blocking issue was found that requires stopping before 5B-G-B or 5B-G-C. No real-looking committed secret was found in the inspected env/deployment files, and no production authorization path was found that clearly trusts raw identity headers.

## Non-blocking Issues

Status: Follow-up required

- OpenAPI/generated API docs can still expose legacy raw header parameters for dependencies that retain stub/demo fallback branches.
- First production Master Admin / staff `supabase_user_id` bootstrap is not documented or automated.
- RLS policy/grant/Data API plan is not yet written, by design.
- Clean Supabase database migration smoke test remains a deployment follow-up.
- Service-role / privileged backend access paths still need a dedicated review.

## Explicitly Deferred to 5B-H

Status: Deferred

- Cookie/BFF session transport.
- CSRF protection.
- `HttpOnly`, `Secure`, `SameSite` cookie migration.
- Server-side session invalidation/logout.
- Replacing browser-visible Supabase and MATA bearer token transport.
- Resident second factor or stronger resident identity proof.

## Verification Commands

Status: Ready

Commands run for this audit:

- `git pull --ff-only`
- `git switch -c CL/phase-5b-g-supabase-readiness`
- `git status --short --branch`
- `git check-ignore -v .env`
- `git ls-files .env .env.example docker-compose.yml frontend\Dockerfile backend\Dockerfile .github\workflows\backend-ci.yml`
- `rg --files`
- `Get-Content -Raw AGENTS.md`
- `Get-Content -Raw docs\00_project_context.md`
- `Get-Content -Raw docs\auth-account-contract.md`
- `Get-Content -Raw docs\99_decision_log_and_gap_audit.md`
- Targeted `Get-Content` section reads for `docs\api.md`, `docs\schema.md`, and `docs\business-logic.md`
- `rg -n "X-User-Role|X-User-Id|X-User-Programme|X-User-Site|X-Admin-Level" backend\app frontend\src`
- `rg -n "SUPABASE_SERVICE_ROLE_KEY|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|SECRET_KEY|SERVICE_ROLE|PRIVATE_KEY|DB_PASSWORD" frontend .github docker-compose.yml frontend\Dockerfile backend\Dockerfile .env.example README.md docs\dev_setup.md frontend\README.md`
- `rg -n "VITE_.*(SUPABASE_SERVICE_ROLE_KEY|SERVICE_ROLE|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|SECRET_KEY|PRIVATE_KEY|DB_PASSWORD)|VITE_SUPABASE_SERVICE|VITE_.*SERVICE_ROLE|VITE_.*PRIVATE|VITE_.*SECRET|VITE_.*DATABASE|VITE_.*DB_PASSWORD" .`
- Targeted `Get-Content` reads for backend auth, middleware, models, migrations, env/deployment, and frontend auth/env files listed above

Required A verification:

- `git diff -- docs/5b_g_supabase_readiness_audit.md`

Required B/C verification:

- `rg -n "SUPABASE_SERVICE_ROLE_KEY|MATA_RESIDENT_SESSION_SECRET" frontend docker-compose.yml frontend\Dockerfile .github`
- `rg -n "VITE_(SUPABASE_SERVICE_ROLE_KEY|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|SECRET_KEY|SERVICE_ROLE|PRIVATE_KEY|DB_PASSWORD)" .env.example README.md docs frontend .github docker-compose.yml frontend\Dockerfile backend\Dockerfile`
- `rg -n "VITE_.*(SERVICE_ROLE|PRIVATE_KEY|DB_PASSWORD)|VITE_SUPABASE_SERVICE" .env.example README.md docs frontend .github docker-compose.yml frontend\Dockerfile backend\Dockerfile`
- `python -m pytest tests\test_auth_supabase.py::test_programme_scope_blank_only_is_denied_for_programme_pc -q --tb=short -rA` (failed before the central scope fix, then passed after it)
- `python -m pytest tests\test_auth_modes.py tests\test_auth_supabase.py tests\test_auth_resident.py tests\test_external_auth.py -q --tb=short`
- `python -m compileall app tests`
- `python -m pytest -q --tb=short`

## 5B-G-B Env and Secret Exposure Hardening Update

Status: Ready

Files changed:

- `.env.example`
- `README.md`
- `docs/5b_g_supabase_readiness_audit.md`

Secrets/env checks run:

- Searched committed frontend, workflow, Docker, README, and env-example paths for backend-only secret names.
- Searched for backend-only secret names with `VITE_` prefixes.
- Inspected frontend Docker build args and Vite env loading.
- Inspected `.env.example`, `docker-compose.yml`, `frontend/Dockerfile`, `backend/Dockerfile`, `.github/workflows/backend-ci.yml`, `README.md`, `docs/dev_setup.md`, and `frontend/README.md`.

Findings fixed:

- `.env.example` now separates backend-only server variables from frontend/browser-exposed Vite variables.
- `.env.example` now explicitly states that all `VITE_*` variables are browser-exposed.
- `.env.example` now states that `SUPABASE_SERVICE_ROLE_KEY` and `MATA_RESIDENT_SESSION_SECRET` are backend-only and must never be copied into frontend env, Vite build args, browser bundles, or `VITE_*`.
- `.env.example` preserves both `VITE_SUPABASE_PUBLISHABLE_KEY` and `VITE_SUPABASE_ANON_KEY` because code currently supports publishable-key preference with anon-key fallback.
- `README.md` no longer documents stale generic `SECRET_KEY`; it documents current backend-only Supabase and MATA resident-token settings plus frontend-safe Vite settings.

Remaining risks:

- No production secret values were checked from the local ignored `.env`; it was intentionally not read.
- `docker-compose.yml` still has local development database defaults, including the local Docker `postgres` password. This is acceptable as local-only placeholder/dev configuration, not production guidance.
- Production staff bootstrap and RLS remain separate follow-up work.

Pending decisions:

- None for 5B-G-B. The first Master Admin / production staff bootstrap path still needs a later operational plan, but it does not block the env documentation hardening completed here.

## 5B-G-C Auth Guardrail Test Update

Status: Ready

Files changed:

- `backend/app/dependencies/auth.py`
- `backend/app/dependencies/staff_actor.py`
- `backend/app/middleware/auth_stub.py`
- `backend/app/routers/admin.py`
- `backend/tests/test_auth_modes.py`
- `backend/tests/test_auth_supabase.py`
- `docs/5b_g_supabase_readiness_audit.md`

Guardrails added:

- Production mode rejects raw `X-User-*` identity headers even if `AUTH_MODE=stub`.
- Supabase staff tokens for unmapped or inactive `users` rows are rejected.
- Programme PC access rejects null, empty, blank-only, or whitespace-only scopes.
- Null/empty programme scope never implies master admin.
- Secretary access rejects missing DB-owned posting scope.
- Supabase staff tokens are rejected on resident-only routes.
- MATA resident tokens reject wrong issuer/audience and do not trust injected posting claims.
- MATA external resident tokens do not accept native posting/programme claims.

Fixes made:

- Added central programme scope normalization for auth dependency guards.
- Normalized persisted staff programme scope when building Supabase/stub staff identities.
- Normalized identity-derived programme scope in staff actor and admin context projections.

Verification result:

- Targeted auth suite: 64 passed.
- Admin/staff chunk: 123 passed.
- Resident/external/secretary chunk: 162 passed.
- Parser/upload/read-model chunk: 357 passed.
- Full backend suite: 712 passed in 309.77s.
