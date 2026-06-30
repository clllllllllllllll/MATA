# Auth and Account Contract

Status: 5B-A foundation plus 5B-B1 backend identity foundation, June 29, 2026.

This document defines the Supabase-ready auth/account contract for upcoming 5B login/register work. It is also a repo audit: source-of-truth docs describe the intended design, while the implementation has partial stub/demo and Non-NHG resident support already present.

References checked:
- `AGENTS.md`
- `docs/00_project_context.md`
- `docs/api.md` Authentication Model and Auth/Non-NHG resident endpoints
- `docs/schema.md` `users`, `residents`, `resident_postings`, `external_residents`, `external_resident_postings`, `attendance_records`, `external_attendance_records`, `teaching_events`
- `docs/business-logic.md` BL-9 and BL-12 External / Cross-Cluster Resident Attendance
- `docs/99_decision_log_and_gap_audit.md` decisions for external residents, master admin, secretary visibility capability flag, bulk TTF deferral, latest TTF export/email deferral
- Supabase docs: JWTs, user management, RLS, and changelog

## Principles

- Login/register is universal: it covers NHG Resident, Non-NHG Resident, staff, Programme PC, and Master Admin paths.
- Staff/admin accounts live in `users`; NHG Residents do not.
- NHG Residents are RDB-backed in `residents` and authenticate by MCR.
- Non-NHG Residents self-enrol into `external_residents` and authenticate by MCR after registration.
- Non-NHG Resident attendance lives in `external_attendance_records` and never enters NHG compliance, numerator, denominator, surplus, snapshots, clawback, or native reports.
- MCR is globally unique across `residents` and `external_residents`.
- Master admin must be explicit. Never infer master access from `programme_scope = NULL`.
- `programme_scope = NULL` or empty means no programme access.
- Secretary scope is `posting_code`; Programme PC scope is `programme_scope`.
- NHG Resident current posting is always derived server-side from `resident_postings` at request time.
- Non-NHG Resident current posting is not derived from native `resident_postings`.
- User-facing labels are NHG Resident and Non-NHG Resident. Existing backend/internal names such as `resident`, `external_resident`, `/external/*`, and `external_attendance_records` remain acceptable.

## Current Repo State

Backend:
- `backend/app/middleware/auth_stub.py` contains `AuthStubMiddleware` and `AuthIdentity`.
- Protected requests currently rely on Phase 1 headers: `X-User-Role`, `X-User-Id`, `X-User-Programme`, `X-User-Site`, and for some admin routes `X-Admin-Level`.
- The middleware validates staff/resident/external resident subjects against DB tables before routers run in stub/demo modes.
- As of 5B-A, backend auth is mode-gated:
  - `AUTH_MODE=stub`: local header identity accepted.
  - `AUTH_MODE=demo`: header identity accepted only when `ALLOW_DEMO_ROLE_SWITCHER=true`.
  - `AUTH_MODE=supabase`: mock/dev identity headers are rejected for protected routes.
- `backend/app/routers/auth.py` has `POST /auth/login` and `GET /auth/me`.
- `backend/app/services/auth.py` currently issues `stub.<role>.<id>` tokens only in stub/demo mode. Supabase mode does not issue stub tokens.
- `backend/app/routers/external_residents.py` and `backend/app/services/external_residents.py` already implement partial Non-NHG self-enrolment and posting update.
- The current Non-NHG service writes `external_residents` and `external_resident_postings`, but the authorization-sensitive source remains `external_residents.current_nhg_posting_code` unless a later phase explicitly wires date-specific external posting semantics.
- `users.admin_level` is now the persisted explicit master marker with allowed values `programme` and `master`. Some local/demo paths still accept `X-Admin-Level: master` only when the role switcher is explicitly enabled, but runtime admin context and staff actor audit metadata now prefer `request.state.identity` when middleware provides it.
- `backend/app/dependencies/auth.py` provides central typed identity helpers over `request.state.identity`.
- Several legacy route/test compatibility paths still read headers directly after middleware validation. Future Supabase work must finish replacing those with central verified identity dependencies.

Frontend:
- `frontend/src/components/AppShell.tsx` contains the role switcher.
- `frontend/src/config/navigation.ts` defines role options, route-role mapping, and redirect targets.
- `frontend/src/api/authHeaders.ts` builds local/demo stub headers.
- As of 5B-A, demo headers are emitted only when `VITE_AUTH_MODE !== supabase` and `VITE_ENABLE_ROLE_SWITCHER=true`.
- As of 5B-A, the role switcher is visible only when `VITE_ENABLE_ROLE_SWITCHER=true`.
- `frontend/src/types/auth.ts` defines the typed frontend auth/session identity contract for later real session wiring.
- There is no real Supabase client/session provider or production login page yet.

Docker/env:
- `docker-compose.yml` has local backend `AUTH_MODE=stub`, `ALLOW_DEMO_ROLE_SWITCHER=true`, Docker DB URLs using host `db`, and frontend build args for local stub mode.
- `frontend/Dockerfile` now passes `VITE_APP_ENV`, `VITE_AUTH_MODE`, `VITE_ENABLE_ROLE_SWITCHER`, `VITE_SUPABASE_URL`, and `VITE_SUPABASE_ANON_KEY` into the Vite build.
- `frontend/nginx.conf` proxies `/api/v1/` to the backend service, so local Docker frontend can use `VITE_API_BASE_URL=/api/v1`.

## Identity Paths

### NHG Resident MCR Login

Input: role `resident`, MCR only.

Source table: `residents`.

Server behaviour:
- Normalise MCR.
- Look up `residents.mcr`.
- Reject missing or inactive residents.
- Return/log in as subject `residents.id`.
- Include resident `programme_code` as a native programme claim.
- Do not put current posting in the token. Resolve posting from `resident_postings` on each request.

JWT/session claims:

```json
{
  "sub": "<residents.id>",
  "app_role": "resident",
  "mcr": "M12345A",
  "programme_code": "GRM"
}
```

### Non-NHG Resident Register + MCR Login

Register input: `name`, `mcr`, `home_cluster`, `current_nhg_posting_code`.

Source table: `external_residents`.

Server behaviour:
- Accept only `home_cluster = NUH | SingHealth`.
- Reject MCR if it exists in `residents` or `external_residents`.
- Validate `current_nhg_posting_code` against `posting_codes`.
- Do not create `users`, native `residents`, or native `resident_postings`.
- For authorization-sensitive reads, fetch current posting from `external_residents.current_nhg_posting_code`.

JWT/session claims:

```json
{
  "sub": "<external_residents.id>",
  "app_role": "external_resident",
  "mcr": "E12345A",
  "home_cluster": "NUH"
}
```

Do not trust `current_nhg_posting_code` from JWT for authorization-sensitive reads.

### Staff/Admin Username or Email Login

Input: role `admin` or `secretary`, plus username/email and password.

Source table: `users`.

Server behaviour:
- Reject inactive users.
- Staff users are never residents.
- Secretary identity carries exactly one `posting_code`.
- Programme PC identity carries `programme_scope`.
- Empty or NULL `programme_scope` grants no programme access.

Programme PC claims:

```json
{
  "sub": "<users.id>",
  "app_role": "admin",
  "admin_level": "programme",
  "programme_scope": ["DR", "GRM"]
}
```

Secretary claims:

```json
{
  "sub": "<users.id>",
  "app_role": "secretary",
  "posting_code": "TTSHGerMed"
}
```

### Master Admin

Source: backend-created or seeded staff account.

Representation: explicit persisted field `users.admin_level = 'master' | 'programme'`.

Claims:

```json
{
  "sub": "<users.id>",
  "app_role": "admin",
  "admin_level": "master",
  "programme_scope": []
}
```

Master access must never be inferred from `programme_scope = NULL`, empty scope, missing scope, or a special programme code.

## Supabase-Ready Claim Rules

Use Supabase Auth JWTs for production sessions, but keep MATA authorization data server-owned:
- Store authorization attributes in server-owned DB rows and/or Supabase `app_metadata`, not user-editable user metadata.
- Keep JWT claims small: role, subject id, admin level/scope, secretary posting code, resident programme code, or external home cluster only.
- Use `sub` as the authenticated account subject for the identity path, not as a guessed role-specific foreign key without role context.
- Backend authorization must validate role + scope server-side before DB work.
- RLS policies later must use explicit `TO authenticated` policies plus ownership/scope predicates. Do not rely on authentication alone.
- Server-side backend operations that span residents or programmes must use server-only credentials. Never expose `SUPABASE_SERVICE_ROLE_KEY` to the frontend or any `VITE_` variable.

## Auth Modes and Environments

### Local Docker Development

Backend:

```env
ENV=development
AUTH_MODE=stub
ALLOW_DEMO_ROLE_SWITCHER=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/mata_db
SYNC_DATABASE_URL=postgresql://postgres:postgres@db:5432/mata_db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080
```

Frontend:

```env
VITE_APP_ENV=local
VITE_AUTH_MODE=stub
VITE_ENABLE_ROLE_SWITCHER=true
VITE_API_BASE_URL=/api/v1
```

### Preview/Staging

Use separate backend and frontend environment variable sets.

Recommended default:

```env
ENV=development
AUTH_MODE=supabase
ALLOW_DEMO_ROLE_SWITCHER=false
VITE_APP_ENV=preview
VITE_AUTH_MODE=supabase
VITE_ENABLE_ROLE_SWITCHER=false
```

If a production-like demo/UAT mode is needed later, it must use both backend and frontend explicit flags and must not point at real production data:

```env
AUTH_MODE=demo
ALLOW_DEMO_ROLE_SWITCHER=true
VITE_AUTH_MODE=demo
VITE_ENABLE_ROLE_SWITCHER=true
```

### Production

Backend:

```env
ENV=production
AUTH_MODE=supabase
ALLOW_DEMO_ROLE_SWITCHER=false
DATABASE_URL=<supabase production database url>
SYNC_DATABASE_URL=<supabase production sync database url>
SUPABASE_SERVICE_ROLE_KEY=<server-only key>
CORS_ORIGINS=<production frontend origin>
```

Frontend:

```env
VITE_APP_ENV=production
VITE_AUTH_MODE=supabase
VITE_ENABLE_ROLE_SWITCHER=false
VITE_API_BASE_URL=<deployed backend api base>
VITE_SUPABASE_URL=<production Supabase URL>
VITE_SUPABASE_ANON_KEY=<production Supabase anon/publishable key>
```

Server-only variables must not use the `VITE_` prefix.

## Frontend Auth State Contract

`AuthSessionState` should eventually be the frontend source of truth:

```ts
{
  mode: 'stub' | 'demo' | 'supabase'
  identity: AuthIdentity | null
  role: AppRole | null
  isAuthenticated: boolean
}
```

Responsibilities:
- Stub/demo mode may derive identity from the role switcher.
- Supabase mode must derive identity from verified Supabase session state and backend `/auth/me`.
- Route guards are UX only. Backend remains the security boundary.
- The frontend must redirect after login by role:
  - NHG Resident -> `/resident/submissions`
  - Non-NHG Resident -> `/external/submissions` once the final route exists; current placeholder route is `/external`
  - Secretary -> `/secretary/events`
  - Programme PC -> `/pc/teaching-events`
  - Master Admin -> `/admin`

Current helper surface:
- `roleFromPathname(pathname)`
- `defaultPathForRole(role)`
- `isPathAllowedForRole(pathname, role)`

## Login/Register Frontend Contract

Planned `/login`:
- One universal login surface.
- NHG Resident panel: MCR login.
- Staff/Admin panel: username/email + password login.
- Non-NHG Resident CTA using user-facing label "Non-NHG Resident".
- Successful login stores/loads the real session identity and redirects using the target table above.
- Stub/demo local mode may keep using the role switcher and demo identities.

Planned Non-NHG registration:
- User-facing label: Non-NHG Resident.
- Fields: name, MCR, home cluster, current NHG posting.
- Enforces global MCR uniqueness server-side.
- After registration, login remains MCR-only.

## Implementation TODOs

5B-B1 implemented:
- Added `users.admin_level` as a non-null explicit master marker.
- Added central backend identity dependencies that read `request.state.identity`.
- Converted `/auth/me`, external resident current-posting update, the admin context choke point, and staff actor audit metadata to use the verified identity when available.
- Kept local/demo role-switcher compatibility environment-gated.

5B-B remaining:
- Replace remaining route-level direct header parsing and legacy isolated-router compatibility branches with central dependencies.
- Convert resident and secretary dependencies after targeted route tests are in place.
- Ensure every Programme PC endpoint rejects master admin where required.
- Seed/create the actual backend-owned Master Admin account in the target environment.

5B-C:
- Add real frontend `/login` and auth/session provider.
- Wire route guards to session state.
- Use role-aware redirects.

5B-D:
- Complete Supabase Auth JWT verification in backend.
- Decide exact custom claims source: app metadata hook, backend session exchange, or backend lookup after token verification.
- Do not trust Supabase user metadata for authorization.

5B-E:
- Complete staff/admin credential handling and account provisioning flows.
- Master Admin remains backend-created/seeded.
- Secretary and Programme PC accounts can later be created by Master Admin through UI.

5B-F:
- Complete Non-NHG resident submission parity where not already implemented.
- Keep Non-NHG attendance separate from native attendance and compliance.

5B-G:
- Add production RLS policies and service-role backend data access.
- Verify exposed table grants and RLS behaviour in Supabase.

5B-H:
- Add rate-limit hardening for login/register and mutation surfaces before UAT/public use.

Still deferred beyond 5B-A:
- Production Supabase deployment, Vercel/backend deployment, exports/email, bulk upload, compliance, surplus, snapshots, clawback, STP upload/parser, password reset, and staff account management UI.

## 5A Guardrails Preserved

This contract and patch do not change:
- NHG Resident scheduled attendance workflow.
- Date-first NHG Resident ad-hoc teaching flow.
- Catalogue-backed ad-hoc options.
- Server-side posting derivation from `resident_postings`.
- Display/audit-only treatment of `details_of_session`.
- Public holiday hard-blocking.
- Weekend non-exception storage plus `compliance_warning`.
- Soft delete with `status = removed`.
- Resubmission by restoring removed scheduled attendance.
- `/resident/attendance` and `/resident/attendance-history` compatibility.
- Scheduled filters and Recent Submissions widget behaviour.
- No resident-facing Created By.
- No resident/admin `X-User-Site`.
- No `attendance_records.session_type_id`.
- No hard delete path.
