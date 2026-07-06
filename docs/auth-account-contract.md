# Auth and Account Contract

Status: 5B-A through 5B-F-B auth/account foundation, July 4, 2026.

This document defines the Supabase-ready auth/account contract for upcoming 5B login/register work. It is also a repo audit: source-of-truth docs describe the intended design, while the implementation has partial stub/demo and Non-NHG resident support already present.

References checked:
- `AGENTS.md`
- `docs/00_project_context.md`
- `docs/api.md` Authentication Model and Auth/Non-NHG resident endpoints
- `docs/schema.md` `users`, `residents`, `resident_postings`, `external_residents`, `external_resident_postings`, `attendance_records`, `external_attendance_records`, `teaching_events`
- `docs/business-logic.md` BL-9 and BL-12 Non-NHG / Cross-Cluster Resident Attendance
- `docs/99_decision_log_and_gap_audit.md` decisions for Non-NHG Residents, master admin, secretary visibility capability flag, bulk TTF deferral, latest TTF export/email deferral
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
- Non-NHG Resident date-specific posting is not derived from native `resident_postings`; derive it from `external_resident_postings` where event/ad-hoc logic needs a selected date.
- MATA external resident tokens must not carry current posting or posting schedule claims as trusted authorization data.
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
- `backend/app/services/auth.py` issues `stub.<role>.<id>` tokens in stub/demo mode. In Supabase mode, staff sessions come from Supabase Auth and NHG/Non-NHG resident sessions use backend-signed MATA resident tokens.
- `backend/app/routers/external_residents.py` and `backend/app/services/external_residents.py` already implement partial Non-NHG self-enrolment and posting update.
- The current Non-NHG service writes `external_residents` and `external_resident_postings`. Phase 5B posting schedule requirements supersede the older single-current-posting contract: authorization-sensitive event/ad-hoc derivation uses `external_resident_postings` by selected date, while `external_residents.current_nhg_posting_code` may remain a current/cache/backward-compatibility pointer.
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
- As of 5B-F-A, `AUTH_MODE=supabase` also supports NHG Resident MCR login without creating Supabase Auth users. The backend validates MCR against `residents`, issues a backend-signed MATA resident session token, and reloads the active `residents` row on protected requests.
- As of 5B-F-B, `AUTH_MODE=supabase` also supports registered Non-NHG Resident MCR login without creating Supabase Auth users. The backend validates MCR against `external_residents`, issues a backend-signed MATA resident session token with `role/app_role = external_resident`, and reloads the active `external_residents` row on protected requests.
- As of 5B-E, staff accounts are generic pass-down role accounts. Master Admin can manage staff accounts at `/admin/staff-accounts`; Supabase-mode create/reset calls are backend-only service-role operations and are mocked in tests.
- As of 5B-E, staff users save `current_staff_actor_name` once after login and can change it from Settings. This is self-declared audit/display metadata only and never an authorization source. Resetting a staff account password clears the saved actor name for handover.

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
- In `AUTH_MODE=supabase`, do not create a Supabase Auth user for the resident and do not write residents into `users`.
- In `AUTH_MODE=supabase`, return a backend-signed MATA resident session token for `Authorization: Bearer <token>` on resident API calls. The token is signed with server-only `MATA_RESIDENT_SESSION_SECRET`, uses a MATA issuer/audience distinct from Supabase Auth JWTs, and is accepted only for `role/app_role = resident`.

JWT/session claims:

```json
{
  "iss": "mata-api",
  "aud": "mata-resident-session",
  "sub": "<residents.id>",
  "role": "resident",
  "app_role": "resident",
  "mcr": "M12345A",
  "programme_code": "GRM",
  "iat": 12345678,
  "exp": 12345678
}
```

The MATA resident session token must not contain `posting_code`, current posting, staff actor name, `admin_level`, or `programme_scope`. Protected requests reload the resident by `sub` and reject inactive rows. `/auth/me` may include display-only `current_posting_code` and `current_posting_label` for shell display, resolved from today's `resident_postings` row first, then an effectively active reporting-period row, then the nearest future row, then the nearest recent past row; authorization-sensitive resident routes still derive posting in their own services.

### Non-NHG Resident Register + MCR Login

5B-F registration input: `name`, `mcr`, `home_cluster`, and `posting_schedule[]` rows containing `start_date`, `end_date`, `programme_code`, and `institution`. The client does not send editable `posting_code`; the backend resolves posting codes from trusted programme/institution posting configuration. `current_nhg_posting_code` may remain a compatibility/cache field, but it is not the current UI contract.

Source table: `external_residents`.

Server behaviour:
- Accept only `home_cluster = NUH | SingHealth`.
- Reject MCR if it exists in `residents` or `external_residents`.
- Validate each schedule row and resolve exactly one safe posting code from trusted data/config; reject unresolved or ambiguous schedule rows with `422`.
- Do not create `users`, native `residents`, or native `resident_postings`.
- In `AUTH_MODE=supabase`, do not create a Supabase Auth user for the external resident.
- In `AUTH_MODE=supabase`, return a backend-signed MATA resident session token for `Authorization: Bearer <token>` on external resident API calls. The token is signed with server-only `MATA_RESIDENT_SESSION_SECRET`, uses a MATA issuer/audience distinct from Supabase Auth JWTs, and is accepted only for `role/app_role = external_resident`.
- For authorization-sensitive reads, fetch `external_residents` and derive the date-specific posting from `external_resident_postings` where relevant. `/auth/me` may include display-only `current_posting_code` and `current_posting_label` resolved from today's `external_resident_postings` row first, then an effectively active reporting-period row, then the nearest future row, then the nearest recent past row. `external_residents.current_nhg_posting_code` may remain a cache/backward-compatibility pointer, but `/auth/me` must not fall back to it for shell scope.

JWT/session claims:

```json
{
  "iss": "mata-api",
  "aud": "mata-resident-session",
  "sub": "<external_residents.id>",
  "role": "external_resident",
  "app_role": "external_resident",
  "mcr": "E12345A",
  "home_cluster": "NUH",
  "iat": 12345678,
  "exp": 12345678
}
```

The MATA external resident session token must not contain `current_nhg_posting_code`, `posting_code`, posting schedule, staff actor name, `admin_level`, `programme_code`, or `programme_scope`. Protected requests reload the external resident by `sub` and reject inactive rows.

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

### 5B-E Generic Staff Role Accounts and Actor Names

Staff accounts are shared role accounts, not personal workforce identities:

- `users.name` remains the generic account display name, such as `Master Admin`, `Programme PC - DR`, or `Secretary - TTSHCardio`.
- `users.current_staff_actor_name` stores the current human using the account. It is self-declared POC audit metadata only.
- `current_staff_actor_name` must not grant or override `role`, `admin_level`, `programme_scope`, `posting_code`, or any authorization decision.
- `/auth/me` returns `current_staff_actor_name` and `staff_actor_name_required` for staff only.
- Staff users with no saved non-blank actor name are blocked in the frontend by the "Set staff name" flow until they save one. Residents are not prompted.
- Staff can update the saved actor name later from AppShell Settings.
- Master Admin can create, edit, activate/deactivate, and reset password for staff accounts at `/admin/staff-accounts`.
- Password reset/handover clears the saved actor name and timestamps; no new local user is created.
- Production should eventually replace self-declared actor names with SSO/corporate identity. Until then, these names are audit context, not strong identity proof.

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
MATA_RESIDENT_SESSION_SECRET=<backend-only secret for NHG Resident and Non-NHG Resident MATA session tokens>
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
- Supabase mode derives staff identity from verified Supabase session state and backend `/auth/me`.
- Supabase mode derives NHG Resident and Non-NHG Resident identity from the stored MATA resident token and backend `/auth/me` when no valid staff Supabase session exists.
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

Implemented `/login`:
- One universal login surface.
- NHG Resident panel: MCR login.
- Staff/Admin panel: username/email + password login; backend derives Master Admin, Programme PC, or Secretary from `users`.
- Non-NHG Resident CTA using user-facing label "Non-NHG Resident".
- Successful login stores/loads the real session identity and redirects using the target table above.
- Stub/demo local mode keeps using session-derived stub headers after login, without a user-facing role switcher.

Current Non-NHG registration:
- User-facing label: Non-NHG Resident.
- Fields: name, MCR, home cluster, and posting schedule rows with date range, programme, and institution.
- Enforces global MCR uniqueness server-side.
- After registration, login remains MCR-only.

Implemented Non-NHG posting schedule work:
- Schedule rows capture date range, programme code plus full programme name, and institution (`TTSH`, `WH`, `KTPH`). Resolved posting code is backend-derived and may be displayed only as read-only output.
- Rows validate date order, overlap, controlled institution values, and posting-code resolution without string-generated or client-entered posting codes.

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
- Resident and Non-NHG MCR-only Supabase login/provisioning remained deferred in 5B-D2; local stub/demo resident login was unchanged.

5B-D remaining:
- Decide exact staff custom claims source if a future Supabase custom access-token hook is introduced; authorization must still remain server-owned.
- Do not trust Supabase user metadata for authorization.

5B-E:
5B-E implemented:
- Added generic staff role-account management for Master Admin at `/admin/staff-accounts`.
- Added backend-only Supabase Admin user create/password reset using `SUPABASE_SERVICE_ROLE_KEY`; the service role key remains server-only and must not appear in frontend/Vite variables.
- Added nullable `users.current_staff_actor_name`, `staff_actor_name_updated_at`, and `staff_actor_name_updated_by_user_id`.
- Added `/auth/staff-actor-name`, `/auth/me` actor-name fields, frontend first-login actor-name gate, and AppShell Settings update flow.
- Reset password/handover clears the saved actor name and updates the local password hash; passwords are not returned or logged.
- The frontend still transports Supabase access tokens as browser-visible bearer tokens from the Supabase browser session. This is an accepted temporary 5B-D2/5B-E limitation.

5B-F-A implemented:
- Enabled NHG Resident MCR login in `AUTH_MODE=supabase` / `VITE_AUTH_MODE=supabase` without creating resident Supabase Auth accounts.
- NHG Residents remain `residents`-table-backed and are not `users`.
- Backend `/auth/login` validates the MCR against active `residents` rows and issues a backend-signed MATA resident session token with `iss = mata-api`, `aud = mata-resident-session`, `role/app_role = resident`, `sub = residents.id`, `mcr`, `programme_code`, `iat`, and `exp`.
- Supabase-mode protected routes accept either a verified Supabase staff token or a verified MATA resident token. Raw `X-User-*` headers remain ignored in Supabase mode.
- `/auth/me` with a MATA resident token returns resident identity plus display-only current posting code/label when available, and omits staff actor fields, trusted posting code claims, admin level, and programme scope.
- Frontend Supabase mode stores the MATA resident token after NHG Resident login, hydrates it through backend `/auth/me` when no staff Supabase session exists, attaches it as `Authorization: Bearer ...` for resident API calls, and keeps residents out of the staff actor-name gate.

5B-F-B implemented:
- Enabled registered Non-NHG Resident MCR login in `AUTH_MODE=supabase` / `VITE_AUTH_MODE=supabase` without creating external resident Supabase Auth accounts.
- Non-NHG Residents remain `external_residents`-table-backed and are not `users`, native `residents`, or native `resident_postings`.
- Backend `/auth/login` validates the MCR against active `external_residents` rows and issues a backend-signed MATA resident session token with `iss = mata-api`, `aud = mata-resident-session`, `role/app_role = external_resident`, `sub = external_residents.id`, `mcr`, `home_cluster`, `iat`, and `exp`.
- Supabase-mode protected routes accept verified MATA external resident tokens, reload active `external_residents` rows by `sub`, and ignore raw `X-User-*` headers.
- `/auth/me` with a MATA external resident token returns external identity plus display-only current posting code/label when available, and omits `current_nhg_posting_code`, posting schedule, staff actor fields, trusted posting code claims, admin level, programme code, and programme scope.
- Frontend Supabase mode stores, hydrates, transports, and logs out MATA tokens for both NHG and registered Non-NHG Resident sessions; staff calls still rely on the latest Supabase session token.
- Non-NHG schedule rows, secretary-event visibility, ad-hoc submission, and admin/PC attendance export are implemented as recording/forwarding-only flows. NHG compliance, surplus, snapshots, and clawback remain excluded/deferred for Non-NHG Residents.

5B-F:
- Complete Non-NHG resident submission parity where not already implemented.
- Keep Non-NHG attendance separate from native attendance and compliance.

5B-G completed:
- Phase 5B-G is complete as readiness, documentation, and audit work.
- 5B-G produced the staff bootstrap runbook, RLS/grants/Data API planning matrix, Supabase migration smoke plan, service-role / privileged backend access review, and updated readiness audit.
- 5B-G did not implement RLS, add RLS policy SQL, implement cookie/BFF/CSRF session transport, or implement compliance.

5B-H is now the Vercel/Supabase stakeholder UAT security phase:
- `5B-H-A`: Vercel UAT security audit and minimal deployment hardening plan.
- `5B-H-B`: Minimal UAT security fixes.
- `5B-H-C`: Supabase/Vercel UAT deployment smoke.
- `5B-H-D`: Full session transport hardening plan in `docs/5b_h_session_transport_hardening_plan.md`; implementation remains required before real production or public use.

5B-H sequencing:
- `5B-H-A`, `5B-H-B`, and `5B-H-C` are required before stakeholder UAT.
- `5B-H-D` planning can be a deeper follow-up if time is tight, but the actual cookie/BFF/CSRF implementation must be completed before real production or public use.
- Browser-visible bearer-token transport remains a known temporary risk until `5B-H-D`.
- Full RLS enablement and policy SQL remain a later dedicated RLS/grants phase, not part of `5B-H-A`, `5B-H-B`, or `5B-H-C`.
- Phase 6 compliance starts only after the protected deployment/security baseline is acceptable.

Still deferred beyond this auth/account roadmap alignment:
- Resident second factor, full RLS policy implementation, production staff bootstrap execution, email delivery, bulk upload, NHG compliance/surplus/snapshots/clawback for Non-NHG Residents, STP upload/parser, long-term SSO/corporate identity replacement for self-declared staff actor names, and any production/public launch beyond a controlled UAT security baseline.

## 5A Guardrails Preserved

This contract and patch do not change:
- NHG Resident scheduled attendance workflow.
- Date-first NHG Resident ad-hoc teaching flow with attended TTSH department dropdown.
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
