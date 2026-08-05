# Development Setup (Docker)

Prerequisites: Python 3.12+, Node.js 22.22+, and PostgreSQL 15+.

Read `security.md` before changing authentication, sessions, RLS, grants,
uploads, deployment configuration, CI, or security verification.

## 1. Create local env file

```bash
cp .env.example .env
```

`.env` is local-only and must never be committed.

## 2. Start backend and database

```bash
docker compose up --build
```

## 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

## 4. Run backend tests

```bash
docker compose exec backend python -B -m compileall app tests
docker compose exec backend python -B -m pytest -q --tb=short -p no:cacheprovider
```

For local non-container verification, run the same commands from `backend/`.

## 5. Run frontend gates

From `frontend/`:

```bash
npm ci
npm test
npm run lint
npm run typecheck
VITE_APP_ENV=production VITE_AUTH_MODE=supabase VITE_API_BASE_URL=/api/v1 npm run build
python ../.github/scripts/security_source_scan.py --frontend-dist
```

The three build variables are public, non-secret configuration. A production
build deliberately fails when any is absent, the environment/mode pair is not
approved, or `VITE_API_BASE_URL` is anything other than `/api/v1`; no browser
Supabase URL or key is required. The emitted-artifact scan fails closed when
`dist` is missing, a source map exists, or a legacy Supabase/bearer/token,
absolute backend API, privileged configuration, or database marker is present.
The Vercel `mata-aine` Preview and Production scopes must both define the same
three values shown above. GitHub Actions variables do not populate Vercel, and
Vercel environment changes affect only a new or redeployed build.

## 6. Run manual upload + view smoke verification

From repo root:

```bash
python backend/scripts/smoke_upload_and_view.py
```

This smoke flow verifies:
- backend upload endpoints for Academic Calendar / Public Holidays, RDB, final A-J TTF, and FormF1
- persisted upload outputs are readable from admin view endpoints (`residents`, `resident_postings`, `posting_codes`, `session_types`, `teaching_targets`, `form_f1_records`, `public_holidays`, `academic_month_boundaries`, `upload_logs`)

## 7. Run Phase 5A native resident flow smoke verification

From backend directory:

```bash
python scripts/smoke_phase5a_resident_flow.py
```

## 8. Run native and Non-NHG Resident UI smoke verification

Use the current identity and workflow contract in
`docs/auth-account-contract.md` and the deployed verification requirements in
`docs/security.md` Section 17. No standalone Phase 5B browser checklist is a
current contract.

## 9. Security verification boundaries

Disposable PostgreSQL security and migration verification must use an explicitly named local database. Never load live credentials or point destructive verification at Supabase. Phase 5B-H-D used only `mata_phase5b_verify_5bhd`; Phase 5B-H-E uses only `mata_phase5b_verify_5bhe`.

For H-E, set `SYNC_DATABASE_URL` to the local owner credential for exactly `mata_phase5b_verify_5bhe`, migrate it to `20260726_000026`, and run the suite through the restricted-role harness:

```powershell
Set-Item -Path Env:SYNC_DATABASE_URL -Value "postgresql://<local-owner>:<local-password>@<local-host>:<local-port>/mata_phase5b_verify_5bhe"
cd backend
python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests
```

The harness creates distinct ephemeral `LOGIN`, non-owner, `NOBYPASSRLS` runtime and auth credentials, grants each only its stable capability group, runs pytest with RLS active, and removes the ephemeral roles afterward. Never point this harness or lifecycle tests at live Supabase.

For focused session-lifecycle assurance, use a fresh child process and exactly
`mata_phase5b_session_lifecycle_verify` at head `20260727_000027`. Verify
`current_database()` before every migration, downgrade, reset, or test command:

```powershell
Set-Item -Path Env:SYNC_DATABASE_URL -Value "postgresql://<local-owner>:<local-password>@<local-host>:<local-port>/mata_phase5b_session_lifecycle_verify"
cd backend
python -B -m alembic current
python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests
```

Never substitute `mata_db`, the earlier H-D/H-E database, or a remote target.

For the current cumulative restricted-harness verification, use exactly
`mata_evolved_ttf_e2b2_verify` at head `20260805_000036`. Both database
URLs must name that local database in a fresh process; the runner derives
separate temporary runtime/auth URLs and removes its `mata_test_*` roles:

```powershell
Set-Item -Path Env:SYNC_DATABASE_URL -Value "postgresql://<local-owner>:<local-password>@localhost:5432/mata_evolved_ttf_e2b2_verify"
Set-Item -Path Env:DATABASE_URL -Value "postgresql+asyncpg://<local-owner>:<local-password>@localhost:5432/mata_evolved_ttf_e2b2_verify"
cd backend
python -B -m alembic current
python -B -m pytest -q --tb=short -p no:cacheprovider --strict-markers -m migration_mutation tests
python -B -m alembic current --check-heads
python -B -m tests.attest_migration_database
python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider --strict-markers -m "not migration_mutation" tests
```

Print and assert the exact database name and local host before every mutation.
Do not drop the database without separate authorization.

GitHub backend jobs start their PostgreSQL service on the maintenance database
`postgres`. The shared local CI action then creates and attests exactly
`mata_evolved_ttf_e2b2_verify`, exports URLs that all name that local
database, and supplies only synthetic CI session/rate-limit secrets. The
`migration_mutation` partition runs first and serially through the direct owner
while its guards require zero competing sessions; CI then rechecks the head.
Before database reuse, a bounded fail-closed attestation proves the exact head,
direct owner, zero competing sessions, and zero residual `mata_test_*` roles.
The broad restricted invocation then selects `not migration_mutation`, replaces
the pre-test runtime/auth URLs with distinct ephemeral `mata_test_*` logins,
enables RLS, keeps cookie transport active, and removes those logins afterward.
The complementary marker expressions cover the complete collection without
duplicating mutation paths.
The job-level `RATE_LIMIT_STORE=postgres` contract is exercised by a dedicated
restricted PostgreSQL security-integration step. Broad regression invocations
override only that setting to `memory` because their unit fixtures explicitly
verify the in-memory middleware; RLS and restricted database credentials remain
enabled. `ENV=test` and `AUTH_MODE=stub` are intentional for this localhost-only
harness; production Settings reject local database URLs. CI provisioning never
contacts Supabase or any other live system.

Production migration rehearsal follows `docs/security.md` Section 15. First
Master Admin bootstrap follows the controlled boundary in
`docs/auth-account-contract.md`; neither is a normal development command.

Registry-backed dependency audits are:

```bash
cd backend
python -m pip_audit -r requirements.txt --no-deps --disable-pip --strict

cd ../frontend
npm audit --omit=dev --audit-level=high
npm audit --audit-level=high
```

Use `.github/scripts/sanitize_dependency_audit.py` and the workflow contract in `.github/workflows/production-security.yml` for saved evidence. Raw registry JSON is temporary and must be deleted after the bounded sanitized report is produced.

Production configuration validation requires cookie transport, RLS enabled, three distinct credentialed database logins targeting the same PostgreSQL endpoint, non-local PostgreSQL URLs, explicit HTTPS CORS origins, explicit allowed hosts, `RATE_LIMIT_STORE=postgres`, and backend-only session/rate-limit secrets of at least 32 characters. The runtime and auth logins inherit only `mata_app_runtime` and `mata_auth_internal`, respectively; the migration login owns application objects. Startup attestation rejects role, ownership, helper, policy, grant, sequence, default-ACL, `PUBLIC`, or browser-role drift. The production browser uses relative `/api/v1` and has no Supabase client configuration.

The first corrected production load removes only the exact historical
`mata.auth.session.v1` key. It deliberately does not wildcard-delete `sb-*`
storage because the repository does not carry a trustworthy exact legacy
Supabase project reference. Users who used a pre-cookie deployment must clear
site data once after the corrected release, then open a new tab. This
operational cleanup is not a substitute for the cookie-only build.

The exact read-only Vercel inspection, deployment configuration, and
post-deployment browser checklist is
`docs/deployed_auth_transport_uat.md`. Do not treat local gates as deployed
evidence or deploy without separate authorization.

The current security contract is `docs/security.md`. Historical
session-transport, restricted-role, lifecycle, and request-ingress reports
are indexed at `docs/archive/security/phase-5b/README.md` as dated
implementation evidence. Local completion does not prove deployed behavior.

Resident identity assurance remains separately governed product debt. Do not
invent a second factor or claim workflow outside an approved product scope.
