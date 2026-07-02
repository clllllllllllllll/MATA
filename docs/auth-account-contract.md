# Auth and Account Contract

Status: 5B-A foundation plus 5B-B1/5B-B2 backend identity foundation and 5B-C frontend auth/session shell, June 30, 2026.

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
- MCR-only resident login is a legacy low-assurance identity flow, not strong authentication. It is preserved for resident UX compatibility and must be tightly scoped to the resident's own NHG Resident or Non-NHG Resident APIs.
- Staff/admin/secretary authentication remains separate from resident MCR identity and should use stronger Supabase-backed authentication later.
- Resident second factor is deferred. Future MCR + email OTP, magic link, phone OTP, or equivalent verification can be added before identity construction without changing protected-route authorization, because resident routes depend on central backend identity.
- Backend authorization remains the final authority. Frontend route guards are UX convenience only.

## Current Repo State

Backend:
- `backend/app/middleware/auth_stub.py` contains `AuthStubMiddleware` and `AuthIdentity`.
- Protected local stub/demo requests currently use Phase 1 headers derived from the authenticated session identity: `X-User-Role`, `X-User-Id`, `X-User-Programme`, `X-User-Site`, and for some admin routes `X-Admin-Level`.
- The middleware validates staff/resident/external resident subjects against DB tables before routers run in stub/demo modes.
- As of 5B-C cleanup, backend auth is mode-gated:
  - `AUTH_MODE=stub` or `AUTH_MODE=demo` with non-production `ENV`: local header identity is accepted and validated against database rows before routers run.
  - `AUTH_MODE=supabase` or production `ENV`: raw `X-User-*` identity headers are not trusted for protected routes.
- As of 5B-D1, backend Supabase Auth JWT verification is implemented for staff accounts. Protected Supabase-mode requests require `Authorization: Bearer <Supabase access token>`, verify the token, map `claims.sub` to `users.supabase_user_id`, and derive MATA role/scope from the active `users` row.
- Supabase `user_metadata` is ignored for MATA authorization. `role`, `admin_level`, `programme_scope`, and `posting_code` remain server-owned in the database.
- `backend/app/routers/auth.py` has `POST /auth/login` and `GET /auth/me`.
- `backend/app/services/auth.py` currently issues `stub.<role>.<id>` tokens only in stub/demo mode. Supabase mode does not issue stub tokens.
- `backend/app/routers/external_residents.py` and `backend/app/services/external_residents.py` already implement partial Non-NHG self-enrolment and posting update.
- The current Non-NHG service writes `external_residents` and `external_resident_postings`, but the authorization-sensitive source remains `external_residents.current_nhg_posting_code` unless a later phase explicitly wires date-specific external posting semantics.
- `users.admin_level` is now the persisted explicit master marker with allowed values `programme` and `master`. Runtime admin context and staff actor audit metadata prefer `request.state.identity` when middleware provides it; direct-header fallback branches are limited to local stub/demo compatibility.
- `backend/app/dependencies/auth.py` provides central typed identity helpers over `request.state.identity`.
- As of 5B-B2, resident and secretary route contexts read central verified identity dependencies instead of raw route-level `X-*` headers.
- Remaining direct header reads are intentionally limited to middleware/infrastructure or legacy fallback choke points:
  - `AuthStubMiddleware` reads local stub/demo headers and validates subjects before setting `request.state.identity`.
  - `require_admin_context` and `require_staff_actor` prefer `request.state.identity`; their direct-header branches remain only for isolated legacy test/demo compatibility.
  - rate-limit middleware may read headers for request bucketing only, not authorization.

Frontend:
- `frontend/src/components/AppShell.tsx` displays the authenticated identity and logout action; it no longer exposes a role switcher.
- `frontend/src/config/navigation.ts` defines role options, route-role mapping, and redirect targets.
- `frontend/src/api/authHeaders.ts` builds local/demo stub headers only from a stored authenticated session identity.
- As of 5B-C cleanup, the frontend no longer synthesizes pre-login demo identity headers and no longer has a visible role switcher.
- `frontend/src/types/auth.ts` defines the typed frontend auth/session identity contract for later real session wiring.
- As of 5B-C, the frontend has a universal `/login`, frontend auth/session provider, role-aware route guards, logout/session clearing, and Non-NHG Resident registration plus confirmation UI.
- As of 5B-D2, `VITE_AUTH_MODE=supabase` uses the Supabase browser session for staff login, hydration, API bearer transport, and logout. MATA role/scope still comes only from backend `/auth/me`.

Docker/env:
- `docker-compose.yml` has local backend `AUTH_MODE=stub`, Docker DB URLs using host `db`, and frontend build args for local stub mode.
- `frontend/Dockerfile` now passes `VITE_APP_ENV`, `VITE_AUTH_MODE`, `VITE_SUPABASE_URL`, and `VITE_SUPABASE_ANON_KEY` into the Vite build.
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

Input: role `staff`, plus username/email and password. Legacy role-specific `admin` and `secretary` payloads remain accepted for local/demo compatibility, but the universal login frontend submits the neutral staff path.

Source table: `users`.

Server behaviour:
- Look up active `users` by email and derive the staff role from the stored row after password verification.
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
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/mata_db
SYNC_DATABASE_URL=postgresql://postgres:postgres@db:5432/mata_db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080
```

Frontend:

```env
VITE_APP_ENV=local
VITE_AUTH_MODE=stub
VITE_API_BASE_URL=/api/v1
```

### Preview/Staging

Use separate backend and frontend environment variable sets.

Recommended default:

```env
ENV=development
AUTH_MODE=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_JWT_AUDIENCE=authenticated
VITE_APP_ENV=preview
VITE_AUTH_MODE=supabase
```

If a production-like demo/UAT mode is needed later, it must use both backend and frontend explicit flags and must not point at real production data:

```env
AUTH_MODE=demo
VITE_AUTH_MODE=demo
```

### Production

Backend:

```env
ENV=production
AUTH_MODE=supabase
DATABASE_URL=<supabase production database url>
SYNC_DATABASE_URL=<supabase production sync database url>
SUPABASE_URL=<supabase project url>
SUPABASE_JWKS_URL=<optional explicit JWKS url>
SUPABASE_JWT_ISSUER=<optional explicit issuer, defaults to SUPABASE_URL/auth/v1>
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_PUBLISHABLE_KEY=<optional publishable/anon key for legacy HS256 Auth-server validation>
SUPABASE_SERVICE_ROLE_KEY=<server-only key>
CORS_ORIGINS=<production frontend origin>
```

Frontend:

```env
VITE_APP_ENV=production
VITE_AUTH_MODE=supabase
VITE_API_BASE_URL=<deployed backend api base>
VITE_SUPABASE_URL=<production Supabase URL>
VITE_SUPABASE_PUBLISHABLE_KEY=<production Supabase publishable key>
# VITE_SUPABASE_ANON_KEY=<legacy anon key fallback>
```

`SUPABASE_SERVICE_ROLE_KEY` is server-only and is not used for JWT verification. Server-only variables must not use the `VITE_` prefix.

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
- Stub/demo mode derives frontend identity from `/auth/login` and `/auth/me`; local header emission is based on the stored session identity.
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
- Staff/Admin panel: username/email + password login; backend derives Master Admin, Programme PC, or Secretary from `users`.
- Non-NHG Resident CTA using user-facing label "Non-NHG Resident".
- Successful login stores/loads the real session identity and redirects using the target table above.
- Stub/demo local mode keeps using session-derived stub headers after login, without a user-facing role switcher.

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
- Kept local/demo header compatibility environment-gated and moved runtime contexts toward `request.state.identity`.

5B-B2 implemented:
- Converted resident route context to central verified identity with native/external resident role enforcement.
- Converted secretary route context to central verified identity with posting-code scope from the verified identity.
- Preserved local stub/demo compatibility through middleware-provided `request.state.identity`.
- Confirmed Programme PC teaching-event CRUD rejects Master Admin and empty programme scope.

5B-B remaining:
- Continue retiring isolated legacy header fallback branches when surrounding tests no longer need them.
- Audit additional PC-only endpoints only where the intended Programme PC-only boundary is explicit.
- Seed/create the actual backend-owned Master Admin account in the target environment.

5B-C implemented:
- Added universal frontend `/login` with NHG Resident MCR login, registered Non-NHG Resident MCR login, and separate staff login for Master Admin, Programme PC, and Secretary accounts.
- Added frontend auth/session provider, session hydration through `/auth/me` where available, role-aware redirects, protected route guards, and logout/session clearing.
- Added Non-NHG Resident self-registration UI and screenshot-matched registration confirmation state. Registration does not assume immediate login unless the backend returns a session-like response.
- Removed the visible role switcher and kept stub/demo session headers disabled in `VITE_AUTH_MODE=supabase`.

5B-D1 implemented:
- Added backend Supabase Auth JWT verification for protected routes in `AUTH_MODE=supabase` or production.
- Added nullable unique `users.supabase_user_id` for staff-account mapping from Supabase access-token `sub`.
- Verifies asymmetric Supabase JWTs with the project JWKS endpoint and bounded JWKS cache.
- Uses Supabase Auth `/auth/v1/user` with a publishable/anon key as the legacy HS256 fallback; does not use the service role key for JWT verification.
- Derives final MATA staff identity from active `users` rows and ignores `user_metadata` plus all raw `X-User-*` authorization headers in Supabase mode.

5B-D2 implemented:
- Added frontend Supabase session transport for staff login in `VITE_AUTH_MODE=supabase`.
- Staff login calls Supabase Auth email/password sign-in, then backend `/auth/me` with `Authorization: Bearer <access_token>` to derive Master Admin, Programme PC, or Secretary identity.
- Shared frontend API transport attaches the latest Supabase access token as `Authorization: Bearer ...` and strips local/demo identity headers in Supabase mode.
- Supabase hydration reads the current Supabase browser session and validates it through backend `/auth/me`; invalid backend identity clears local app state and signs out locally from Supabase.
- Supabase logout signs out of the local Supabase browser session and clears the MATA AuthContext/session state.
- Resident and Non-NHG MCR-only Supabase login/provisioning remains deferred; local stub/demo resident login is unchanged.

5B-D remaining:
- Decide exact staff custom claims source if a future Supabase custom access-token hook is introduced; authorization must still remain server-owned.
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

Still deferred beyond 5B-D1:
- Resident Supabase provisioning, resident second factor, RLS, staff account UI, password reset, production Supabase deployment, Vercel/backend deployment, Master Admin seed/provisioning script, Non-NHG workflow parity beyond the login/register shell, exports/email, bulk upload, compliance, surplus, snapshots, clawback, and STP upload/parser.

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
