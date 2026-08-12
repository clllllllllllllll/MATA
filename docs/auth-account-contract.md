# Auth and Account Contract

Status: Phase 5B-H-E locally implemented and verified; focused session
lifecycle assurance implemented locally on July 27, 2026; AUD-M-06 reliable
logout implemented and verified locally. Deployment verification remains
pending.

This document defines the current auth/account contract. Phase 5B-H-D replaced normal browser bearer transport with backend-owned opaque PostgreSQL sessions, a host-only cookie, and synchronizer CSRF. Phase 5B-H-E adds the restricted non-owner PostgreSQL runtime, a separate auth-helper boundary, signed transaction-local identity context, complete application-table RLS, and exact grants. Revision `20260727_000027` adds absolute-expiry assurance, interval-gated activity, minimal session helpers, and expiry-aware RLS context. AUD-M-06 supersedes H-D's best-effort frontend logout-completion semantics with an explicit pending/unconfirmed state and proof-positive server confirmation. Historical implementation entries below are retained as an audit trail; where they describe browser Supabase or resident bearer tokens, the H-D/H-E/current lifecycle contract supersedes them.

`security.md` is the current cross-cutting security source of truth. This file
remains authoritative for identity, account, and session-lifecycle behavior.

References checked:
- `AGENTS.md`
- `docs/00_project_context.md`
- `docs/api.md` Authentication Model and Auth/Non-NHG resident endpoints
- `docs/schema.md` `users`, `residents`, `resident_postings`, `external_residents`, `external_resident_postings`, `attendance_records`, `external_attendance_records`, `teaching_events`
- `docs/security.md` cross-cutting security contract and evidence boundary
- `docs/business-logic.md` BL-9 and BL-12 Non-NHG / Cross-Cluster Resident Attendance
- `docs/99_decision_log_and_gap_audit.md` decisions for Non-NHG Residents, master admin, secretary visibility capability flag, bulk TTF deferral, latest TTF export/email deferral
- Supabase docs: JWTs, user management, RLS, and changelog

## Phase 5B-H-D Current Session Contract

- Login, registration options, and Non-NHG registration are intentionally public entry points. An outer Vercel access gate is not required, but no protected data is available without application authentication and server-side authorization.
- Normal production transport is `AUTH_TRANSPORT=cookie` for Master Admin, Programme PC, Secretary, NHG Resident, and Non-NHG Resident.
- Staff email/password authentication is mediated by the backend against Supabase Auth. The browser does not create or retain a Supabase session.
- Resident MCR authentication remains backend-only and creates the same kind of opaque application session while preserving native/external table separation.
- The raw session token exists only in the `HttpOnly`, production `Secure`, `SameSite=Strict`, host-only `__Host-mata_session` cookie. Only keyed token and CSRF digests are stored in `app_sessions`.
- `POST /auth/login`, `GET /auth/me`, `POST /auth/session/refresh`, and `POST /auth/logout` are the session lifecycle endpoints.
- Session responses contain `user`, `csrf_token`, and `session_refresh_required`; they do not return a normal-production access token.
- The effective server-side expiry is the earlier of `idle_expires_at` and the
  immutable family `absolute_expires_at`; equality is expired. Refresh and
  repeated rotation extend neither the parent's current idle deadline nor the
  family absolute deadline, and full login is required after either expiry.
- Only a successful 2xx protected unsafe request qualifies for interval-gated
  idle activity after CSRF and business validation. Safe reads, polling,
  failed requests, refresh, and logout do not slide idle expiry.
- Protected unsafe methods require the current `X-CSRF-Token`; the frontend holds it only in module memory and sends credentials through the relative same-origin `/api/v1` path. Intentionally unauthenticated login and registration mutations do not require an existing-session CSRF token.
- Protected requests reload the current subject row and compare `session_generation`. Ordinary role/scope/active-state changes atomically increment generation and revoke sessions. For a permitted self authorization change, the planned final state is audited before mutation while the request-start actor remains valid; subject invalidation is then the final protected statement in that transaction. Self-change audit metadata marks the revoked-session count as non-exact, while non-self changes retain the exact count. Password reset is deliberately two-stage: the issuance block, generation fence, and revocation commit before the upstream credential call; successful completion clears the block in a second transaction, while failure leaves issuance blocked for authorized retry.
- Rotation locks subject, family, and the database session row in a fixed order. `SELECT ... FOR UPDATE` plus `populate_existing=True` prevents stale SQLAlchemy identity-map state from bypassing the locked row.
- Logout uses an auth-only termination helper with keyed token and CSRF digests. It derives the family server-side. Active proof must be before both deadlines; a parent revoked specifically as `rotated` remains termination-only proof until the immutable family absolute deadline even after its superseded idle deadline. Refresh-first races therefore still terminate the replacement without granting hydration, signed-context, touch, rotation, or refresh authority.
- Cleanup retains a `rotated` parent as bounded logout proof until the immutable family absolute deadline, even after its superseded idle deadline or under shorter retention, and never makes a still-valid unrevoked child eligible.
- `AUTH_TRANSPORT=bearer_compat` is retained for non-production compatibility
  only in the current H-E configuration. Production requires RLS, and RLS
  requires cookie transport, so the legacy rollback flag cannot enable it.
  Production rollback requires a coordinated application/database version
  rollback and forced reauthentication.
- Every current production browser request carries
  `X-MATA-Session-Coordination: web-locks-v1`. Login, refresh, and logout hold
  one same-origin exclusive Web Lock through HTTP response completion so an
  older response cannot overwrite or delete a newer fixed-name HttpOnly
  cookie. Missing/wrong protocol requests fail without `Set-Cookie`; generic
  authentication failures also leave the shared cookie untouched. Logout
  clears it only when the presented token/CSRF proof revokes that family.
- Application startup probes `GET /auth/me` once because browser JavaScript
  cannot inspect the HttpOnly session cookie. After startup resolves as
  conclusively unauthenticated with `401`, ordinary focus and visibility events
  do not repeat that probe. Inconclusive network and server failures remain
  eligible for a later focus retry, including across a failed login that does
  not clear the browser cookie. When an in-memory session exists, those events
  revalidate in the background without replacing the current route with the
  auth loading screen; cross-tab session lifecycle signals may still force a
  probe.
- Logout clears local identity, CSRF, protected read/upload state, and
  user-facing authenticated state immediately, then enters an explicit
  logout-pending/unconfirmed state. A successful HTTP status alone is not
  revocation proof: only `server_logout_confirmed = true` confirms that the
  server revoked the presented family and applied controlled cookie deletion.
- While logout is pending, mount, focus/visibility hydration, and protected
  requests remain blocked. Durable browser state is limited to a non-sensitive
  pending tombstone containing its format version, timestamp, bounded retry
  state, and local request id plus one fixed-size non-sensitive resolution
  watermark containing only its version, request id, initiation/resolution
  timestamps, and resolution kind. No copy of the session token or cookie
  material, CSRF value or digest, identity, MCR, role, scope, credential, or
  server expiry is written to application storage. Until proof-positive
  deletion or expiry, the browser-managed HttpOnly cookie may still exist but
  cannot restore frontend authority through the pending fence.
- A bounded controller may dispatch the original logout proof at nominal
  automatic offsets 0, 1, 3, and 7 seconds while that CSRF/session
  epoch/revision proof remains only in memory, with at most four attempts.
  Explicit retry or an `online` signal may advance one eligible attempt;
  concurrent triggers coalesce and cannot increase the bound. A newer
  authentication revision, superseded lifecycle, or confirmed completion
  cancels old work and releases its memory-only proof.
- After reload, a pending tombstone is proofless and cannot retry or rehydrate
  the old session. Deterministic tombstone election plus the monotonic
  resolution watermark prevents a stale fallback replica or older tab from
  resurrecting a completed lifecycle. The user may establish a fresh login;
  only the successful replacement session commit inside the same Web Lock
  resolves the applicable lifecycle. Failed login does not resolve it, and a
  stale logout response cannot affect a newer pending logout or login.
- Migration `20260722_000024` revokes public/browser-role object privileges. Migrations `20260726_000025` and `20260726_000026` add the H-E role/context/helper foundation and full policy/grant cutover. Migration `20260727_000027` narrows the callable session helpers and makes signed RLS context reject an expired backing session.
- Detailed implementation and evidence: `docs/archive/security/phase-5b/5b_h_d_production_security_implementation.md`, `docs/archive/security/phase-5b/5b_h_e_full_rls_implementation.md`, `docs/archive/security/phase-5b/5b_h_session_lifecycle_assurance.md`, and `docs/archive/security/phase-5b/5b_h_m06_reliable_logout.md`.

Resident identity assurance remains separately governed product debt. Do not
invent a second factor or claim workflow outside an approved product scope.

## Phase 5B-H-E Current Database Contract

Normal application database execution is separated into three credentials:

- the protected runtime login is a member of `mata_app_runtime`;
- the intentionally unauthenticated/session-helper login is a member of `mata_auth_internal`;
- Alembic and object ownership use a distinct migration/ownership login.

The two capability groups are stable `NOLOGIN`, `NOINHERIT`, non-owner, `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`, and `NOREPLICATION` roles. The application login members may `INHERIT` exactly their assigned capability, but startup fails closed if either credential is privileged, owns application objects, can assume the other capability, can delegate grants/membership, or reaches a different database.

Before a protected root transaction performs ordinary application queries, PostgreSQL reloads the application session and current subject and installs signed transaction-local context for subject type/id, app role, explicit admin level, normalized programme scope, posting code, application-session id, and authorization fingerprint. The signature is bound to the transaction, backend process, database, and session login. Its verification also requires the backing session to remain unrevoked and strictly before both deadlines. A SQLAlchemy transaction hook reinstalls and revalidates context after an in-request commit or rollback; transaction end clears cached context and expires ORM identity-map state.

All 35 application tables have RLS enabled in the local final-cutover implementation. Eighty-nine policies target only `mata_app_runtime` at Alembic head `20260812_000039`. `app_sessions`, `rate_limit_buckets`, `programme_institution_posting_map`, `surplus_ledger`, `period_snapshots`, and `clawback_records` have no direct runtime table privilege and are reachable only through explicitly reviewed helpers where a helper exists. The Phase F scheduled-event source helpers are runtime-only and validate the signed subject context, source identity, reporting period, and programme/posting scope for scheduled inserts and updates without treating row provenance as the current editor. Phase G adds the runtime-only authorized source-scope helper and replaces Resident/Non-NHG selection, attendance, and atomic ad-hoc classification with explicit source evidence or deterministic both-null legacy evidence; revision `20260804_000035` adds immutable pool source scope and row-local scheduled-event policy checks. Revision `20260805_000036` removes the retired catalogue and target-details structures without changing that source-evidence boundary. Revision `20260805_000037` adds one runtime-only, read-only target-resolution helper; it derives exact persisted source/phase scope, has no `PUBLIC` or browser execution grant, and permits only the signed native Resident owner, a signed scoped Programme PC, or an explicit signed Master before ordinary event visibility is checked. Revision `20260806_000038` makes the existing pool-event RLS helpers reject a Programme-PC pool source unless an exact Teaching Name/period/programme/posting mapping exists; pending and mapped mappings both qualify, while Master and Secretary boundaries remain unchanged. Revision `20260812_000039` adds a runtime-only staff timing resolver that gives an exact authorized Secretary scope mapping-derived duration without granting direct mapping-table access. It does not grant direct resident access to Teaching Name or target tables. `mata_auth_internal` has no direct application-table or sequence privileges. `PUBLIC`, browser roles, and `service_role` receive no application-table or H-E helper access.

Revision `20260727_000027` owns exactly eight minimal lifecycle helpers: three auth-only issuance wrappers, three shared resolve/touch/CSRF helpers, one runtime-only rotation helper, and the auth-only `revoke_app_session_family_for_logout(bytea,bytea,text)` helper. Runtime has no execute grant on the logout helper; the helper is termination-only and returns no identity or authorization context. Logout normally requires token and CSRF digests from one active or rotation-revoked row. It may also consume an active-child-token/rotated-ancestor-CSRF pair only when both rows have the same immutable subject, generation, family, and authentication source and remain within the required deadlines. Callers never supply a subject, row, or family identifier.

FastAPI role/scope dependencies remain mandatory. RLS is defense in depth and must not be used to weaken HTTP-layer authorization.

## Principles

- Login/register is universal: it covers NHG Resident, Non-NHG Resident, staff, Programme PC, and Master Admin paths.
- Staff/admin accounts live in `users`; NHG Residents do not.
- NHG Residents are RDB-backed in `residents` and authenticate by MCR.
- Non-NHG Residents self-enrol into `external_residents` and authenticate by MCR after registration.
- The frontend exposes one shared Resident MCR login field for both identity types. It sends one neutral `{ "role": "resident", "mcr": "<NORMALIZED_MCR>" }` request, and the backend resolves the unique native or external identity.
- Non-NHG Resident attendance lives in `external_attendance_records` and never enters NHG compliance, numerator, denominator, surplus, snapshots, clawback, or native reports.
- MCR is globally unique across `residents` and `external_residents`.
- Master admin must be explicit. Never infer master access from `programme_scope = NULL`.
- `programme_scope = NULL` or empty means no programme access.
- Secretary scope is `posting_code`; Programme PC scope is `programme_scope`.
- NHG Resident current posting is always derived server-side from `resident_postings` at request time.
- Non-NHG scheduled-event authorization is not derived from native `resident_postings` or token claims; derive the date-specific posting and, where an explicit pool/PC source requires it, programme from the date-matching `external_resident_postings` row.
- Non-NHG ad-hoc authorization derives only one date-specific posting from the sole matching `external_resident_postings` row. It does not require a programme value or permit a client-selected programme/department.
- Non-NHG programme/institution selection resolves only through `programme_institution_posting_map`. It must not reuse native teaching mappings, Secretary pools/capabilities, teaching targets, posting metadata, or constructed posting-code strings.
- Emergency `bearer_compat` external-resident tokens must not carry current posting or posting schedule claims as trusted authorization data.
- User-facing labels are NHG Resident and Non-NHG Resident. Existing backend/internal names such as `resident`, `external_resident`, `/external/*`, and `external_attendance_records` remain acceptable.
- MCR-only resident login is a legacy low-assurance identity flow, not strong authentication. It is preserved for resident UX compatibility and must be tightly scoped to the resident's own NHG Resident or Non-NHG Resident APIs.
- Staff/admin/secretary authentication remains separate from resident MCR identity and uses backend-mediated Supabase password authentication in production.
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
- In H-D cookie mode, staff credentials are sent to the backend, which mediates Supabase password authentication, maps the returned Supabase subject to `users.supabase_user_id`, and derives MATA role/scope only from the active `users` row.
- Supabase `user_metadata` is ignored for MATA authorization. `role`, `admin_level`, `programme_scope`, and `posting_code` remain server-owned in the database.
- `backend/app/routers/auth.py` implements login, hydration, rotation, logout, and staff actor-name endpoints.
- Stub/demo retains local compatibility identity. Supabase cookie mode converges all roles into backend-owned `app_sessions`; bearer tokens are not the normal browser transport.
- `backend/app/database.py` separates protected runtime sessions from the auth/helper session factory when H-E is enabled. Protected request dependencies seed shared or exclusive database context from the already validated application session; login/registration/session infrastructure uses the helper boundary.
- `backend/app/services/database_context.py` installs signed transaction-local context on every root transaction and performs fail-closed startup attestation of credentials, roles, grants, helpers, ownership, policies, schemas, sequences, PUBLIC, and browser-role state.
- `backend/app/routers/external_residents.py` and `backend/app/services/external_residents.py` already implement partial Non-NHG self-enrolment and posting update.
- Phase 5B mapping infrastructure adds `programme_institution_posting_map` and one trusted resolver shared by registration options, registration, current-posting compatibility update, and schedule replacement. The approved TTSH configuration contains 24 active mappings, four inactive/null mappings (`FM`, `PATH`, `SPORTSMED`, and `PALLMED`), and zero pending mappings. The inactive status applies only to Non-NHG registration and posting-schedule selection; it is not a global programme status.
- The current Non-NHG service writes `external_residents` and `external_resident_postings`. Phase 5B posting schedule requirements supersede the older single-current-posting contract: each schedule row persists the validated programme and resolved posting, authorization-sensitive event/ad-hoc derivation uses that row by selected date, and `external_residents.current_nhg_posting_code` remains only a current/cache/backward-compatibility pointer.
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
- `frontend/src/types/auth.ts` defines the implemented typed frontend auth/session identity contract.
- As of 5B-C, the frontend has a universal `/login`, frontend auth/session provider, role-aware route guards, logout/session clearing, and Non-NHG Resident registration plus confirmation UI.
- In `VITE_AUTH_MODE=supabase`, the frontend uses backend cookie-session APIs only. It has no Supabase browser client, bearer persistence, or routine bearer injection.
- On startup, the frontend removes only the exact superseded
  `mata.auth.session.v1` key from Local/Session Storage without reading values
  or clearing unrelated origin data. The repository has no trustworthy exact
  legacy Supabase project reference, so it must not wildcard-delete `sb-*`
  entries. Affected users clear site data once after remediation. This is
  residue cleanup, not an authentication path.
- AUD-M-06 clears authenticated local state immediately but does not present
  server revocation as complete until the machine-readable logout response
  returns `server_logout_confirmed = true`. Pending state blocks hydration and
  protected requests across mount, focus, visibility, reload, and tabs without
  persisting credentials or identity data.
- The shared NHG/registered Non-NHG Resident MCR login checks both identity tables in one request, relies on PostgreSQL-enforced normalized global MCR uniqueness as well as the service preflight, creates an opaque application session, and reloads the resolved active row on protected requests.
- As of 5B-E, staff accounts are generic pass-down role accounts. Master Admin can manage staff accounts at `/admin/staff-accounts`; Supabase-mode create/reset calls are backend-only service-role operations and are mocked in tests.
- As of 5B-E, staff users save `current_staff_actor_name` once after login and can change it from Settings. This is self-declared audit/display metadata only and never an authorization source. Resetting a staff account password clears the saved actor name for handover.

Docker/env:
- `docker-compose.yml` has local backend `AUTH_MODE=stub`, Docker DB URLs using host `db`, and frontend build args for local stub mode.
- `frontend/Dockerfile` passes `VITE_APP_ENV`, `VITE_AUTH_MODE`, and `VITE_API_BASE_URL`; no browser Supabase configuration is required.
- `frontend/nginx.conf` proxies `/api/v1/` to the backend service, so local Docker frontend can use `VITE_API_BASE_URL=/api/v1`.

## Identity Paths

The login UI has one Resident MCR field. NHG Residents and already-registered Non-NHG Residents both submit the neutral request role `resident`; the frontend does not infer an identity type from the MCR and does not retry against another role. The backend resolves the unique matching table and returns `user.role = resident | external_resident`. A first-time Non-NHG Resident uses the separate registration action before subsequently using this shared login. Explicit `role = external_resident` requests remain temporarily accepted for compatibility, are scoped only to `external_residents`, and never fall back to native residents.

The JWT examples retained in the identity subsections are historical/rollback documentation for `bearer_compat`. Normal H-D production sessions expose no identity claims or reusable application token to browser code.

### NHG Resident MCR Login

Input: shared role `resident`, MCR only.

Source table: `residents`.

Server behaviour:
- Normalise MCR.
- Look up the normalized MCR in both `residents` and `external_residents` as one backend resolution operation.
- Resolve to the native path only when exactly one native row and no external row exists.
- Reject missing or inactive residents.
- Reject a cross-table duplicate without selecting an identity or issuing a token, and log no MCR, names, rows, or SQL.
- Return/log in as subject `residents.id`.
- Reload resident `programme_code` from the current row for the application identity and compliance scope. Emergency `bearer_compat` may include it as a claim.
- Never trust current posting from a token or browser state. Resolve posting from `resident_postings` on each request.
- In `AUTH_MODE=supabase`, do not create a Supabase Auth user for the resident and do not write residents into `users`.
- In normal `AUTH_MODE=supabase` cookie mode, create a backend-owned `app_sessions` row and set the opaque session cookie; do not return a browser bearer token.

Legacy emergency bearer-compatibility claims:

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

5B-F registration input: `name`, `mcr`, `home_cluster`, and `posting_schedule[]` rows containing `start_date`, `end_date`, `programme_code`, and `institution`. The client does not send editable `posting_code`; the backend resolves posting codes only from active `programme_institution_posting_map` rows. `current_nhg_posting_code` may remain a compatibility/cache field, but it is backend-derived and is not the current UI contract.

The public registration form loads its data from `GET /external-residents/registration-options`, which is derived from the same trusted resolution table. Pending pairs remain visible with `available = false`; inactive pairs are omitted. The registration endpoint remains authoritative and revalidates every submitted row.

Source table: `external_residents`.

Server behaviour:
- Accept only `home_cluster = NUH | SingHealth`.
- Reject MCR if it exists in `residents` or `external_residents`.
- Normalize each schedule pair and require one active mapping with a non-null, referentially valid posting code; pending, inactive, missing, malformed, or invalid rows fail closed with controlled `422`.
- Resolve every row before writing. A single unavailable row creates no partial external resident or posting schedule.
- Do not create `users`, native `residents`, or native `resident_postings`.
- After registration, use the same shared Resident MCR field and neutral `role = resident` request as NHG Residents. The backend returns `user.role = external_resident` when the unique active match is in `external_residents`.
- In `AUTH_MODE=supabase`, do not create a Supabase Auth user for the external resident.
- In normal `AUTH_MODE=supabase` cookie mode, create a backend-owned `app_sessions` row and set the opaque session cookie; do not return a browser bearer token.
- For authorization-sensitive reads, fetch `external_residents` and derive the date-specific programme/posting pair from `external_resident_postings` where relevant. A Secretary event requires an exact schedule posting match and null programme owner; a Programme PC event requires exact schedule posting and programme-owner matches. `/auth/me` may include display-only `current_posting_code` and `current_posting_label` resolved from today's `external_resident_postings` row first, then an effectively active reporting-period row, then the nearest future row, then the nearest recent past row. `external_residents.current_nhg_posting_code` may remain a cache/backward-compatibility pointer, but `/auth/me` must not fall back to it for shell scope and no token programme claim is trusted.

Legacy emergency bearer-compatibility claims:

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

Programme PC derived application identity:

```json
{
  "id": "<users.id>",
  "app_role": "admin",
  "admin_level": "programme",
  "programme_scope": ["DR", "GRM"]
}
```

Secretary derived application identity:

```json
{
  "id": "<users.id>",
  "app_role": "secretary",
  "posting_code": "TTSHGerMed"
}
```

### Shared Teaching Name management authority (Phase C and Phase D)

Phase C activates the name lifecycle routes and Phase D adds a PC-only mapping
backend. Those preparatory phases preserved the former catalogue-backed parser;
the final E2+B2 cutover at revision `20260805_000036` removes that parser
structure and target-details field. Phase G separately moves Resident/Non-NHG
scheduled-event discovery and attendance to persisted source identity. Phase 6
compliance remains deferred.

- Teaching Name pool access is scoped by `(reporting_period_id, programme_code)`.
  Both a Programme PC with the programme in current scope and a Secretary with
  the explicit `can_manage_teaching_names` capability for that programme may
  create, rename, deactivate, and reactivate names.
- The Secretary capability is independent of
  `programmes.native_teaching_posting_code`, ordinary secretary-event
  visibility, and a posting-name convention. The initial approved pilot is the
  exact TTSH GERI Secretary-to-programme relationship; no other capability is
  inferred from visibility or a first matching row.
- Phase D exposes mapping reads to Master Admin and in-scope Programme PCs, and
  mapping mutation only to in-scope Programme PCs. Mapping requests use the
  persisted mapping revision and an explicit target ID or explicit `null` clear;
  nonzero count-only impact requires `confirm_impact = true`. Secretaries and
  Master Admins have no mapping DML authority. Global session types remain
  Admin-managed and outside the pool.
- A Secretary/PC may delete only an unused name. Master Admin has read,
  oversight, and guarded deletion authority only: an event-used name requires
  the current revision, `force_delete`, nonblank reason, and exact `DELETE`
  confirmation. It clears only optional event identity and preserves snapshots
  and attendance.
- Every protected mutation still uses the current opaque session, reloaded
  subject, CSRF, exact-Origin, authorization, rate-limit, audit, and
  post-commit cache-invalidation contracts. A stale revision, lost capability,
  or out-of-scope request fails without a write. Phase D impact/read and apply
  are revision-fenced; they use no browser-held confirmation token or scope
  fingerprint.

### Master Admin

Source: backend-created or seeded staff account.

Representation: explicit persisted field `users.admin_level = 'master' | 'programme'`.

Derived application identity:

```json
{
  "id": "<users.id>",
  "app_role": "admin",
  "admin_level": "master",
  "programme_scope": []
}
```

Master access must never be inferred from `programme_scope = NULL`, empty scope, missing scope, or a special programme code.

#### First Master Admin bootstrap boundary

A clean production environment cannot use the normal Master Admin-only staff
account API to create its first Master Admin. That first mapping is a
controlled backend operations task, not a browser flow or public bootstrap
endpoint.

The approved operator must:

1. verify the exact application commit, Supabase project origin, database
   target, change approval, and rollback owner without printing credentials;
2. create or identify the intended Supabase Auth staff subject through an
   approved server-side administrative path;
3. map only that subject identifier to one `users` row with
   `role = 'admin'`, explicit `admin_level = 'master'`, `is_active = true`,
   no posting scope, and no inferred programme authority;
4. verify that the subject mapping is unique, at least one intended active
   Master Admin remains, Programme PC scopes are non-empty, and Secretary
   posting scopes are non-empty; and
5. verify backend-mediated login and `/auth/me` return the database-owned
   Master Admin identity before using the normal staff-account workflow.

Passwords, session values, service-role keys, database URLs, and other
credentials must not enter SQL text, shell history, logs, screenshots, or
documentation. A wrong mapping is disabled first and repaired under the same
controlled process; referenced staff rows are not casually deleted.

The detailed historical procedure is retained at
`docs/archive/security/phase-5b/5b_g_staff_bootstrap_runbook.md`, but this
account contract and `docs/security.md` govern any current execution.

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

## Backend Session and Supabase Rules

Supabase Auth is the staff credential authority, not the browser application-session owner:

- Supabase `user_metadata` and arbitrary JWT claims are never MATA authorization sources.
- Backend maps the authenticated Supabase subject to `users.supabase_user_id`, then reloads role, admin level, programme scope, posting code, active state, issuance block, and session generation.
- The browser receives only the MATA `HttpOnly` browser-session cookie plus
  non-secret session-response state. The cookie intentionally has no
  persistent `Max-Age` or `Expires`; PostgreSQL idle/absolute deadlines remain
  authoritative.
- Backend authorization validates role and scope before database work.
- H-E RLS uses only trusted backend-derived, database-revalidated transaction-local context and grants browser roles no application-table access.
- Ordinary application SQL uses the restricted runtime credential. The separate auth credential can execute only its exact reviewed helper set, and the migration/ownership credential is not an application credential.
- Server-only Supabase credentials must never appear in frontend code or any `VITE_` variable.

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
VITE_API_BASE_URL=/api/v1
```

`preview:supabase` uses the same fixed-name cookie response coordination as
production. The frontend must therefore run in a browser secure context
(normally HTTPS, or localhost for development) with Web Locks support.
Unsupported HTTP preview origins and embedded browsers without Web Locks fail
closed before any API request; they are not supported Supabase-cookie clients.

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
AUTH_TRANSPORT=cookie
MATA_DATABASE_RLS_ENABLED=true
MATA_DATABASE_RUNTIME_ROLE=mata_app_runtime
MATA_DATABASE_AUTH_ROLE=mata_auth_internal
DATABASE_URL=<restricted runtime async database url>
MATA_AUTH_DATABASE_URL=<restricted auth-helper async database url>
SYNC_DATABASE_URL=<migration-owner sync database url>
SUPABASE_URL=<supabase project url>
SUPABASE_PUBLISHABLE_KEY=<backend publishable key>
SUPABASE_SERVICE_ROLE_KEY=<server-only key>
MATA_SESSION_HASH_KEY=<server-only random key of at least 32 characters>
MATA_STAFF_IDLE_TIMEOUT_SECONDS=<approved staff idle seconds>
MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS=<approved staff absolute seconds>
MATA_RESIDENT_IDLE_TIMEOUT_SECONDS=<approved Resident idle seconds>
MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS=<approved Resident absolute seconds>
MATA_SESSION_ROTATION_SECONDS=<approved rotation seconds>
MATA_SESSION_TOUCH_INTERVAL_SECONDS=<approved touch interval seconds>
MATA_SESSION_CLEANUP_RETENTION_SECONDS=<approved retention seconds>
MATA_SESSION_CLEANUP_BATCH_SIZE=<approved bounded batch>
MATA_ALLOWED_HOSTS=<exact deployment host>
CORS_ORIGINS=<production frontend origin>
RATE_LIMIT_STORE=postgres
RATE_LIMIT_HASH_SECRET=<server-only random key of at least 32 characters>
```

The runtime, auth-helper, and migration URLs must use distinct credentialed login roles while naming the same PostgreSQL host, port, and database. The runtime and auth groups are stable capability names, not login credentials. Production configuration fails if RLS is disabled, cookie transport is not selected, an H-E URL is local or malformed, the endpoints differ, any two database URLs use the same username, or lifecycle settings violate their ordering/helper bounds. Lifecycle values require organisational approval; repository defaults are examples.

Frontend:

```env
VITE_APP_ENV=production
VITE_AUTH_MODE=supabase
VITE_API_BASE_URL=/api/v1
```

`SUPABASE_SERVICE_ROLE_KEY`, database URLs, session/rate-limit keys, and rollback secrets are server-only. Server-only variables must not use the `VITE_` prefix.
All three production frontend variables are mandatory. The build accepts only
the exact relative `/api/v1` API base in production or Supabase mode; it does
not silently replace an absolute or missing value.

## Frontend Auth State Contract

The in-memory frontend session is the source of truth:

```ts
{
  identity: AuthIdentity
  csrfToken: string
  sessionRefreshRequired?: boolean
}
```

`mode`, `role`, and `isAuthenticated` are derived `AuthSessionState` fields, not persisted credential fields.

Reliable logout has three distinct lifecycle meanings:

- authenticated: a current in-memory identity/CSRF session is usable;
- logout pending/unconfirmed: local session state is already empty, the
  non-sensitive tombstone takes precedence over hydration and protected
  requests, and the server result remains unknown or negative; and
- server logout confirmed: a proof-positive
  `server_logout_confirmed = true` response established revocation.

The tombstone is not an auth session and contains no credential or identity
material.

The legacy-key startup cleanup is deliberately outside this state contract.
After it runs, the current application writes no identity, CSRF value,
Supabase token, or opaque session credential to Local Storage, Session Storage,
or IndexedDB.

Responsibilities:
- Stub/demo mode derives frontend identity from `/auth/login` and `/auth/me`; local header emission is based on the stored session identity.
- Supabase mode derives every role from backend session responses and `/auth/me`.
- The session cookie is browser-unreadable. Identity and CSRF are held in module memory and cleared together.
- Unsafe requests use the current CSRF header; no app bearer is stored or routinely injected.
- Route guards are UX only. Backend remains the security boundary.
- The frontend must redirect after login by role:
  - NHG Resident -> `/resident/submissions`
  - Non-NHG Resident -> `/external/submissions`
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
- One shared Resident MCR field for NHG Residents and already-registered Non-NHG Residents. The frontend sends one neutral request, never selects or infers a subtype, and redirects from the backend-returned role.
- Staff/Admin panel: username/email + password login; backend derives Master Admin, Programme PC, or Secretary from `users`.
- First-time Non-NHG Resident registration CTA using user-facing label "Non-NHG Resident".
- Successful login loads identity and CSRF into module memory and redirects using the target table above; it does not persist a browser credential.
- Stub/demo local mode keeps using session-derived stub headers after login, without a user-facing role switcher.

Current Non-NHG registration:
- User-facing label: Non-NHG Resident.
- Fields: name, MCR, home cluster, and posting schedule rows with date range, programme, and institution.
- Enforces global MCR uniqueness server-side.
- After registration, login remains MCR-only.
- Current backend configuration returns TTSH with exactly 24 active programme choices. The inactive TTSH mappings for `FM`, `PATH`, `SPORTSMED`, and `PALLMED` are omitted from public Non-NHG registration options without changing those programmes elsewhere in MATA.
- Loading, request error, no configured institutions, pending configuration, active availability, and submission validation are distinct UI states.

Implemented Non-NHG posting schedule work:
- Schedule rows capture date range, programme code plus full programme name, and an institution supplied by the backend options response. Resolved posting code is backend-derived and is not requested or displayed in the registration form.
- Each stored schedule row retains the validated `programme_code` as provenance alongside the resolved `posting_code`. Registration, schedule replacement, and the current-posting compatibility route preserve both values.
- Legacy rows may retain a null programme only when authoritative mapping data cannot identify one unique value. Such rows fail closed for Programme PC-event visibility; shared postings such as AIM/IM `TTSHGenMed` and GS/SIG `TTSHGenSrg` are never resolved by first match or inference.
- Rows validate date order, overlap, and mapping availability without string-generated or client-entered posting codes.
- Future KTPH, WH, or other institutions require mapping data only; no frontend institution union or resolver branch exists.

Phase 5B programme/institution mapping rollout:

- **Stage 1 (implemented baseline):** generic table/service/API/frontend infrastructure plus exactly 28 pending/null TTSH rows.
- **Stage 2 (approved state):** one validated all-or-nothing data-only Alembic migration sets 24 exact mappings active, sets `FM`, `PATH`, `SPORTSMED`, and `PALLMED` inactive with null posting codes, and leaves zero TTSH rows pending. `GERI + TTSH -> TTSHGerMed` is ordinary configuration data; no inferred/placeholder code or runtime exception is allowed.
- The four inactive mappings restrict only Non-NHG programme/institution registration and posting-schedule selection. They do not change global programme availability or any native NHG Resident behavior.
- External-registration mapping remains isolated from native teaching visibility, Secretary capabilities, event creation, and compliance attribution.

## Historical Implementation Timeline and Current Follow-up

The entries through 5B-F below preserve superseded implementation history.
They are not the current transport contract and must not be used to configure a
deployment. In particular, every historical browser Supabase or bearer path
was removed by 5B-H-D.

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
- Added universal frontend `/login` with one shared NHG/registered Non-NHG Resident MCR login and separate staff login for Master Admin, Programme PC, and Secretary accounts.
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
- Frontend Supabase mode uses the shared neutral MCR request, then stores, hydrates, transports, and logs out the resolved MATA token for both NHG and registered Non-NHG Resident sessions; staff calls still rely on the latest Supabase session token.
- Non-NHG schedule rows, exact-posting scheduled-event visibility and submission, ad-hoc submission, and admin/PC attendance export are implemented as recording/forwarding-only flows. Every normal Department Secretary or Programme PC event at the one exact date-matched posting is eligible; event programme ownership and Secretary capability do not narrow the resident-facing list. NHG compliance, R-year timing resolution, surplus, snapshots, and clawback remain excluded/deferred for Non-NHG Residents.

5B-F:
- Complete Non-NHG resident submission parity where not already implemented.
- Keep Non-NHG attendance separate from native attendance and compliance.

5B-G completed:
- Phase 5B-G is complete as readiness, documentation, and audit work.
- 5B-G produced the staff bootstrap runbook, RLS/grants/Data API planning matrix, Supabase migration smoke plan, service-role / privileged backend access review, and updated readiness audit.
- 5B-G did not implement RLS, add RLS policy SQL, implement cookie/BFF/CSRF session transport, or implement compliance.

5B-H-D locally implemented:

- Added backend-owned opaque PostgreSQL sessions, strict cookie/CSRF transport, rotation-family locking, generation fencing, logout/revocation, persistent rate limiting, upload/archive hardening, error redaction, same-origin frontend transport, and browser-role privilege revocation.
- Removed the normal frontend Supabase session and bearer-token paths.
- Verified migrations through `20260722_000024`, dependency audits, backend/frontend suites, PostgreSQL races, and source scans locally.
- The cookie transport is deployed; historical deployment evidence and remaining
  timed/manual rows are recorded in `docs/archive/deployed_auth_transport_uat.md`.
  The archived 5B-D report remains historical evidence only.

Deployed-auth transport remediation audit:

- A browser-observed Supabase password grant followed by a cross-origin
  bearer-authenticated `/auth/me` request exactly matches the superseded
  5B-D2/5B-E frontend and cannot be produced by the current merged source.
- The current production build contract is
  `VITE_APP_ENV=production`, `VITE_AUTH_MODE=supabase`, and
  `VITE_API_BASE_URL=/api/v1`; emitted artifacts are scanned after build.
- The current backend performs the Supabase password exchange server-side,
  reloads authority from the database, discards upstream tokens, and issues
  only `__Host-mata_session` plus memory-only CSRF/identity state.
- Read-only Vercel evidence confirms both current projects are READY on the same
  reviewed `main` commit and the backend startup exception is resolved. The
  historical credentialed browser/timed rows remain in
  `docs/archive/deployed_auth_transport_uat.md`.

5B-H-E locally implemented:

- Added the `mata_app_runtime` and `mata_auth_internal` capability groups, distinct runtime/auth database session factories, signed transaction-local identity context, startup catalogue attestation, and database-enforced global MCR uniqueness.
- Enabled RLS on all 34 application tables and installed 84 policies plus exact table, column, helper, schema, sequence, PUBLIC, browser-role, ownership, and default-ACL boundaries.
- Preserved FastAPI authorization and native/Non-NHG identity separation. Privileged infrastructure tables remain helper-only rather than receiving broad direct runtime grants.
- The deployed database reached `20260728_000028`; live catalogue evidence
  confirmed 34 RLS tables, 84 valid policies, restricted runtime/auth logins,
  and successful startup attestation. Current role-workflow UAT remains
  separate. The archived 5B-H-E report remains historical evidence only.

AUD-M-06 descendant locally implemented:

- Immediate local sign-out is distinct from confirmed server revocation.
  Ambiguous transport results and `server_logout_confirmed = false` remain
  explicitly pending/unconfirmed; only the proof-positive boolean confirms
  server revocation.
- A durable non-sensitive pending tombstone blocks hydration/protected
  requests; a separate fixed-size non-sensitive resolution watermark prevents
  completed fallback state from being resurrected. The retry proof remains in
  memory only and is bounded to four attempts with nominal automatic offsets
  0/1/3/7 seconds. Cross-tab, reload, stale-response, deterministic-election,
  and replacement-login transitions are coordinated so an older logout cannot
  affect a newer committed session.
- Final M-06 local gates passed; deployed verification remains pending. See
  `docs/archive/security/phase-5b/5b_h_m06_reliable_logout.md`.

5B-H historical sequencing:
- `5B-H-A`: Vercel UAT security audit and minimal deployment hardening plan.
- `5B-H-B`: Minimal UAT security fixes.
- `5B-H-C`: Supabase/Vercel UAT deployment smoke.
- `5B-H-D`: Locally implemented and verified; post-deployment verification remains required.

5B-H sequencing:
- `5B-H-A`, `5B-H-B`, and `5B-H-C` are required before stakeholder UAT.
- Browser-visible bearer transport is removed from the normal production path.
- Full RLS enablement, runtime-role separation, trusted transaction context,
  and policy SQL are deployed and catalogue-verified; current synthetic-account
  workflow isolation remains separate manual UAT.
- Phase 6 compliance starts only after the protected deployment/security baseline is acceptable.

Still deferred beyond this auth/account roadmap alignment:
- Resident second factor, deployed H-E verification, production staff bootstrap execution, email delivery, bulk upload, NHG compliance/surplus/snapshots/clawback for Non-NHG Residents, STP upload/parser, long-term SSO/corporate identity replacement for self-declared staff actor names, and any production/public launch beyond a controlled UAT security baseline.

## 5A Guardrails Preserved

This historical guardrail list is superseded where Phase G explicitly changed
runtime source handling; the AUD-M-04 resubmission clarification remains:
- NHG Resident scheduled attendance workflow, now authorized from persisted
  source identity (or deterministic legacy evidence).
- Date-first NHG Resident ad-hoc teaching flow with one server-derived posting
  and fixed one-hour record; no attended-department dropdown.
- No catalogue-backed ad-hoc options.
- Server-side posting derivation from `resident_postings`.
- Display/audit-only treatment of `details_of_session`.
- Public holiday hard-blocking.
- Weekend non-exception storage plus `compliance_warning`.
- Soft delete with `status = removed`.
- Soft-removed attendance remains immutable history; AUD-M-04 resubmission
  inserts a new active row and identifier so stale removal cannot affect the
  newer submission.
- `/resident/attendance` and `/resident/attendance-history` compatibility.
- Scheduled filters and Recent Submissions widget behaviour.
- No resident-facing Created By.
- No resident/admin `X-User-Site`.
- No `attendance_records.session_type_id`.
- No hard delete path.
