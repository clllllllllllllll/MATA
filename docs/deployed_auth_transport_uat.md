# Deployed Authentication Transport Remediation and UAT

Status: authentication transport and database cutover deployed. Read-only
Vercel MCP, public-endpoint, repository, and initial browser verification were
reconciled on 2026-07-31. Both production projects are READY from `main` commit
`c6f51ac0e9f27608280abd1d5f51a293042c5ea9`; the database is at Alembic head
`20260728_000028`; and the current backend deployment has no 5xx, import,
startup, RLS, database-boundary, session, or rate-limit failure signature.
Current-commit credentialed browser revalidation plus timed rotation/expiry,
role-isolation, upload-boundary, and bounded rate-limit observations remain
manual UAT. No environment value, credential, cookie, CSRF value, MCR, or
personal record is part of this evidence.

This is the current deployment record for the authentication transport. It
does not amend or reuse verdicts from archived Phase 5B evidence.

## Observed failure and root-cause boundary

The reported browser chain was:

1. the frontend submitted staff email/password to a Supabase
   `/auth/v1/token?grant_type=password` endpoint;
2. browser JavaScript retained the resulting upstream credential;
3. the browser prepared a cross-origin request to
   `https://mata-backend.vercel.app/api/v1/auth/me` with `Authorization`;
4. the browser sent an `OPTIONS` preflight containing
   `Access-Control-Request-Headers: authorization`; and
5. the backend deployment returned `500 FUNCTION_INVOCATION_FAILED`.

The preflight did not contain the bearer value. The defect was that the bearer
credential existed in browser-controlled JavaScript and was intended for the
actual request.

Git-history inspection shows that the browser chain exactly matches the
superseded frontend introduced before cookie hardening: it created a Supabase
browser client, called `signInWithPassword`, persisted browser session state,
and injected `Authorization: Bearer`. The current merged source removed that
path and has no frontend Supabase dependency. Therefore the observed browser
traffic is strong evidence of frontend deployment/alias/version drift or an
already-open stale asset, not an execution branch in current source.

The superseded backend deployment also failed before `GET /health` could be
registered. Read-only Vercel logs established an import-time production
settings failure: database RLS was not enabled while the database was still at
revision `20260721_000022`. Enabling the flag alone would not have been safe.
That configuration and migration cutover is now complete. The current backend
deployment returns the controlled health response and its startup attestation
succeeds. The settings loader continues to rethrow validation failures without
Pydantic input/context rendering so a future import failure can identify the
violated contract without including fragments of environment values.

The approved Supabase baseline inspection also established two repository
compatibility mismatches: Supabase installed `pgcrypto` in its standard
`extensions` schema while the H-E migrations required the reviewed functions
in `public`, and `users` already had RLS enabled while the original migration
preflight expected only 14 pre-existing RLS tables. Revisions
`20260726_000025` and `20260726_000026` now normalize those states
transactionally and retain the exact function, policy, grant, and startup
attestations. These database mismatches are separate from the stale frontend
deployment that produced the browser bearer path. No speculative fallback or
weakened startup check is approved.

A subsequent upgrade attempt from revision `20260721_000022` exposed a third
bounded compatibility mismatch. When the hosted PostgreSQL 16 migration owner
is a non-superuser with `CREATEROLE`, creating
`mata_adhoc_attendance_definer` automatically adds one creator row to
`pg_auth_members`: the definer is the granted role, the member is the
`mata_rls` schema owner, the grantor is a superuser, `admin_option` is true,
and `inherit_option` and `set_option` are false. The former revision-`000028`
assertion rejected every membership row. It therefore failed, and the
migration transaction rolled back atomically to `000022`.

The corrected contract accepts zero rows or exactly that creator row, and only
when the schema-owning member has both `CREATEROLE` and `BYPASSRLS`. Migration
and startup attestation continue to reject an outgoing definer membership, an
additional or foreign member, a non-superuser grantor, or any row with
`inherit_option` or `set_option`. The corrected migration subsequently reached
`20260728_000028`; the live catalogue showed 34/34 application tables under
RLS, 84 valid policies, the reviewed restricted runtime/auth login separation,
and successful database-boundary startup attestation.

## Required architecture

The only normal production flow is:

```text
Browser
  -> POST https://mata-aine.vercel.app/api/v1/auth/login
  -> frontend Vercel external rewrite
  -> MATA FastAPI backend
  -> server-side Supabase password authentication
  -> trusted MATA staff lookup and authority revalidation
  -> opaque PostgreSQL application session
  -> Set-Cookie: __Host-mata_session
```

The backend uses the upstream access token only long enough to verify the
Supabase subject and discards it. It does not retain or return the upstream
access or refresh token. The cookie contains only an opaque random MATA
session credential and is `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`,
host-only, and non-persistent.

Subsequent browser requests use the same-origin `/api/v1` path, the cookie, and
`X-CSRF-Token` for authenticated unsafe methods. Identity and CSRF remain in
module memory. Normal production requests contain no bearer header and do not
depend on CORS.

## Local controls prepared

- Production and Supabase builds require all three public Vite variables and
  require the API base to equal `/api/v1`.
- The current login, hydration, refresh, and logout client uses backend cookie
  endpoints only and strips legacy identity and authorization headers.
- Startup removes only the exact `mata.auth.session.v1` key from Local/Session
  Storage. It reads no value and preserves unrelated keys, including `sb-*`.
  Affected users clear site data once because the repository does not contain
  a trustworthy exact legacy Supabase project reference.
- The frontend Content Security Policy permits connections only to self.
- The Vercel API external rewrite precedes the SPA fallback, preserves the API
  suffix, and explicitly disables rewrite/browser/CDN caching.
- Production public browser mutations reject Fetch Metadata other than
  `Sec-Fetch-Site: same-origin`; cookie-mode public routes reject
  `Authorization`.
- CI explicitly disables source maps and scans the emitted artifact for the
  superseded password grant, Supabase client/Auth origins, upstream token
  fields, bearer construction, absolute API origins, database URLs, and
  privileged configuration.

## Deployed Vercel attestation

Evidence was collected read-only on 2026-07-31. Vercel MCP exposed project,
deployment, build, alias, protection, runtime-region, and log metadata. It did
not expose an environment-variable inventory, so names/scopes below are
separately identified as operator dashboard evidence. Successful fail-closed
build/startup is supporting evidence, not a substitute for that distinction.

| Field | Frontend | Backend |
|---|---|---|
| Project | `mata-aine` (`prj_cjo979aIu7ipU3bHdxTnkbZHBCJ1`) | `mata-backend` (`prj_GaabR33KbYyRaLU01nLxdbWyArA7`) |
| Production deployment | `dpl_CxE3g7rV2E4YhDxr3Dk6bF1A6Lz9` | `dpl_D8qTvstL5Ro9kUH32gaXXLHuAQpC` |
| State/source | READY; Git `main` | READY; Git `main` |
| Commit | `c6f51ac0e9f27608280abd1d5f51a293042c5ea9` | `c6f51ac0e9f27608280abd1d5f51a293042c5ea9` |
| Created/ready (UTC) | 01:47:09 / 01:47:27 | 01:47:09 / 01:47:42 |
| Runtime region | static deployment in `iad1` | Python function in `hnd1` |
| Build evidence | Node 24 project metadata; `tsc -b && vite build`; 230 modules; 14 seconds; only the reviewed bundle-size warning | Python 3.12; dependencies from `backend/requirements.txt`; 5 seconds |
| Primary alias | `mata-aine.vercel.app` | `mata-backend.vercel.app` |

Both projects have password and Trusted IP protection disabled. Vercel
Authentication is configured for `all_except_custom_domains`; the production
custom aliases remain publicly reachable and no temporary maintenance-denial
response remained on those aliases.

The MCP project endpoint does not expose custom Root Directory, install/build
override, output-directory, or environment-variable fields. Repository and
build evidence establishes the reviewed layout: frontend Vite source and
`frontend/vercel.json`, backend `backend/api/index.py` and
`backend/vercel.json`, frontend build output through Vercel's output pipeline,
and the backend Python dependency set. These facts must not be mislabeled as
an MCP read of hidden project-setting fields.

### Frontend environment and route contract

- Git repository and Production Branch: reviewed repository and `main`.
- Root Directory: `frontend`.
- Framework: Vite.
- Install Command: `npm ci`.
- Build Command: `npm run build`.
- Output Directory: `dist`.
- Node runtime: the reviewed supported version used by CI.
- Production alias: `mata-aine.vercel.app`.
- Deployment source: current reviewed commit `c6f51ac`.
- Preview- and Production-scoped public build variables:
  - `VITE_APP_ENV` — present in both scopes; exact production contract;
  - `VITE_AUTH_MODE` — present in both scopes; exact Supabase-mode contract;
  - `VITE_API_BASE_URL` — present in both scopes; exact same-origin path
    contract.
- Obsolete `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`,
  `VITE_SUPABASE_ANON_KEY`, or any other `VITE_SUPABASE_*` name — absent.

The variable names/scopes and obsolete-name absence above are operator
dashboard evidence recorded after the corrected redeployment. No environment
value was copied. The current deployment's successful fail-closed production
build is consistent with the exact three-variable contract.

GitHub Actions variables do not populate Vercel project settings. Inspect
general and branch-specific Preview entries because a branch-specific value
overrides the general Preview scope. Vercel environment changes require a new
or redeployed build; they do not repair an existing deployment in place.

Preview auth UAT must not be run against production data. The checked-in
external rewrite has one production backend destination; use a separately
reviewed isolated preview project/configuration before enabling authenticated
preview UAT.

### Backend environment and runtime contract

- Git repository and Production Branch: same repository, `main`, and current
  reviewed commit as the frontend.
- Root Directory: `backend`.
- Entrypoint: `api/index.py`.
- Routing configuration: `backend/vercel.json`.
- Region: `hnd1`.
- Python runtime: 3.12, matching CI.
- Build evidence: Python 3.12 resolved `backend/requirements.txt` and completed
  successfully; the MCP did not expose the project-setting override field.
- Production alias: `mata-backend.vercel.app`.

Backend configuration name contract:

- control, server-only configuration:
  `ENV`, `AUTH_MODE`, `AUTH_TRANSPORT`,
  `MATA_DATABASE_RLS_ENABLED`, `MATA_DATABASE_RUNTIME_ROLE`,
  `MATA_DATABASE_AUTH_ROLE`;
- secret database credentials:
  `DATABASE_URL`, `MATA_AUTH_DATABASE_URL`, `SYNC_DATABASE_URL`;
- backend Supabase configuration:
  `SUPABASE_URL`, `SUPABASE_JWT_AUDIENCE`,
  `SUPABASE_PUBLISHABLE_KEY`;
- optional backend Supabase overrides, if present:
  `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL`;
- privileged backend secret:
  `SUPABASE_SERVICE_ROLE_KEY`;
- session secret and lifecycle:
  `MATA_SESSION_HASH_KEY`, `MATA_STAFF_IDLE_TIMEOUT_SECONDS`,
  `MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS`,
  `MATA_RESIDENT_IDLE_TIMEOUT_SECONDS`,
  `MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS`,
  `MATA_SESSION_ROTATION_SECONDS`,
  `MATA_SESSION_TOUCH_INTERVAL_SECONDS`,
  `MATA_SESSION_CLEANUP_RETENTION_SECONDS`,
  `MATA_SESSION_CLEANUP_BATCH_SIZE`, `MATA_CSRF_HEADER_NAME`;
- perimeter:
  `MATA_ALLOWED_HOSTS`, `CORS_ORIGINS`;
- persistent rate limiting:
  `RATE_LIMIT_STORE`, `RATE_LIMIT_HASH_SECRET`,
  `RATE_LIMIT_CLEANUP_RETENTION_SECONDS`,
  `RATE_LIMIT_CLEANUP_BATCH_SIZE`;
- ingress:
  `MAX_REQUEST_BODY_SIZE_MB`, `MAX_UPLOAD_REQUEST_SIZE_MB`,
  `MAX_UPLOAD_SIZE_MB`.

Database URLs, the service-role key, session hash key, and rate-limit hash
secret are secrets. No privileged name may have a `VITE_` prefix. The Supabase
URL, publishable key, hosts, modes, role labels, and lifecycle values remain
backend-only even when their value class is not secret.

Operator dashboard evidence shows these names in Production:
`ENV`, `AUTH_MODE`, `AUTH_TRANSPORT`, `MATA_DATABASE_RLS_ENABLED`,
`MATA_DATABASE_RUNTIME_ROLE`, `MATA_DATABASE_AUTH_ROLE`, `DATABASE_URL`,
`MATA_AUTH_DATABASE_URL`, `SYNC_DATABASE_URL`, `SUPABASE_URL`,
`SUPABASE_JWT_AUDIENCE`, `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL`,
`SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`MATA_SESSION_HASH_KEY`, `MATA_ALLOWED_HOSTS`, `CORS_ORIGINS`,
`RATE_LIMIT_STORE`, and `RATE_LIMIT_HASH_SECRET`. The three database
variable names are distinct. No backend name has a `VITE_` prefix, and no
value was copied into the evidence record.

The operator inventory did not include explicit lifecycle, cleanup, CSRF-name,
or ingress-size overrides. The reviewed application defaults therefore remain
active for those optional names. Their absence is not a startup failure because
the production settings contract validates the reviewed defaults. Timed UAT
must use those deployed defaults and must not change Production merely to
shorten a test.

The historical failure category was production settings validation:
`DATABASE_RLS_ENABLED` was false. The corrected deployment now starts with the
reviewed restricted credentials and returns the controlled health response.
Vercel production log queries covered the preceding 24 hours. The frontend had
zero 5xx. Eleven backend 500s belonged only to obsolete deployments and matched
that already-recorded import failure. The current backend deployment had zero
5xx and zero matches for `FUNCTION_INVOCATION_FAILED`, import failure,
settings/startup failure, RLS configuration failure, database-boundary
failure, session failure, rate-limit failure, or timeout.

Public checks also established controlled signed-out behavior: `/auth/me`
returns `401` when the required public session-coordination marker is present,
and a bare non-browser client missing that marker fails earlier with controlled
`409`. An approved cookie-mode preflight receives an explicit allowlist;
requesting `Authorization` or using an unapproved origin returns controlled
`400` without wildcard or reflected-origin permission.

### Completed database cutover and rollback contract

The approved production baseline was revision `20260721_000022`, with a
verified recovery point and an authorized recovery owner/maintenance window.
The cutover completed at single head `20260728_000028`. The sequence below is
retained as the reviewed rollback/replay contract:

1. rerun the full rollback preflight after the failed attempt: reverify the
   exact approved target, current revision `20260721_000022`, recovery point,
   authorized recovery owner/window, and complete pre-upgrade catalogue without
   displaying any connection value or credential; stop on any mismatch and do
   not rely on the earlier preflight;
2. use only the reviewed migration-owner `SYNC_DATABASE_URL` against the
   approved database and reviewed remediation commit; its scheme must be
   `postgresql://` or `postgresql+psycopg2://` because the production package
   does not include psycopg 3 and rejects `postgresql+psycopg://`;
3. run the Alembic upgrade to the single head `20260728_000028`;
4. allow revision `000025` to move an owned, relocatable `pgcrypto` extension
   from `extensions` to `public` inside the migration transaction; do not run a
   separate manual `ALTER EXTENSION`;
5. allow revision `000026` to normalize `users` RLS before it asserts the exact
   15-pre-existing/19-new table inventory; do not disable `users` RLS;
6. allow revision `000028` and startup attestation to accept only zero definer
   membership rows or the exact PostgreSQL 16 creator row described above; do
   not delete, recreate, or broaden role membership manually;
7. verify the final extension members, 34 RLS tables, 84 policies, roles,
   grants, helper ownership, default ACLs, browser-role denial, and Alembic
   head;
8. create two distinct credentialed PostgreSQL login roles outside Alembic:
   the runtime login must be `LOGIN INHERIT NOSUPERUSER NOBYPASSRLS
   NOCREATEDB NOCREATEROLE NOREPLICATION` and inherit only
   `mata_app_runtime`; the auth-helper login must have the same restricted
   attributes and inherit only `mata_auth_internal`. Neither login may own
   application objects, inherit the migration owner or the other capability,
   or receive membership with `ADMIN OPTION`. Set their passwords only
   through a private database credential channel. Configure `DATABASE_URL`
   and `MATA_AUTH_DATABASE_URL` with those two logins and retain the owner only
   in `SYNC_DATABASE_URL`; all three URLs must identify the same host, port,
   and database with three distinct usernames; and
9. run startup attestation with the reviewed restricted credentials before
   serving traffic.

Downgrade retains the `pgcrypto` `public` namespace and `users` RLS, just as it
retains other security hardening whose prior privilege provenance cannot be
reconstructed. Do not move the extension back or disable `users` RLS as an
ad-hoc rollback.

## Completed deployment actions

- The database migration, restricted runtime/auth credentials, production RLS
  flag, PostgreSQL rate-limit store, session hash, perimeter settings, and
  backend Supabase configuration were prepared through approved private
  channels.
- The backend was deployed and its controlled `/health` response was confirmed
  before the corrected frontend was promoted.
- Both production aliases now point to READY deployments from the same reviewed
  `main` commit.
- CORS was not broadened, production bearer compatibility was not enabled, no
  backend secret was exposed to Vite, and startup/RLS attestation remained
  fail-closed.
- Users exposed to the superseded browser-token deployment must clear site data
  once, close old tabs, and open a new tab.

## Post-deployment verification record

The following statuses distinguish current deployment evidence from historical
cutover evidence and pending manual observation:

| Check | Status | Evidence |
|---|---|---|
| Both projects deploy reviewed `main` commit | PASS | Vercel MCP: both READY on `c6f51ac`; deployment IDs and UTC timestamps recorded above |
| Backend startup and health | PASS | Current `/health` is controlled `200`; current deployment has zero 5xx/startup signatures |
| Signed-out backend auth and bearer CORS denial | PASS | Coordination-aware `/auth/me` is controlled `401`; bare client is controlled `409`; bearer/unapproved preflights are controlled `400` |
| Database revision, RLS, policies, and role split | PASS | Live cutover evidence: head `20260728_000028`, 34/34 RLS tables, 84 valid policies, restricted runtime/auth logins, successful startup attestation |
| Current signed-out frontend bootstrap | PASS | Browser loaded the current deployment and observed same-origin `/api/v1/auth/me`; no Supabase or backend-origin resource |
| Credentialed same-origin login, cookie, CSRF, storage, and logout | MANUAL VERIFICATION REQUIRED | Passed during the cutover on `2d6e7b0`; repeat on current `c6f51ac` before closing the current browser row |
| Session rotation | MANUAL VERIFICATION REQUIRED | Use the deployed source default without changing Production; observe a qualifying post-threshold request |
| Idle and absolute expiry | MANUAL VERIFICATION REQUIRED | Full configured intervals have not been observed against the current deployment |
| Multi-tab and reliable/offline logout | MANUAL VERIFICATION REQUIRED | Local deterministic coverage passed; current live two-tab/throttled observation remains |
| Resident/PC/Secretary isolation | MANUAL VERIFICATION REQUIRED | Database/RLS controls are deployed; current synthetic-account workflow batch remains |
| Upload limits and bounded rate limiting | MANUAL VERIFICATION REQUIRED | Production defaults/startup validation are active; current harmless live boundary batch remains |
| Deployed asset-content scan | MANUAL VERIFICATION REQUIRED | Current browser inventory identified the hashed JS/CSS assets, but non-browser retrieval was intercepted by Vercel Security Checkpoint `429`; local emitted-artifact scan passed |
| Current Vercel log review | PASS | Current frontend/backend deployments have zero 5xx; current backend has zero matched auth/startup/database/session/rate-limit failure signatures |

The credentialed cutover observations are retained as historical evidence, not
silently relabeled as a current-commit run. The merge from `2d6e7b0` to
`c6f51ac` changed frontend focus/visibility revalidation behavior; it did not
change backend authentication, cookie, CSRF, proxy, database, or CORS code.

### Remaining manual procedure

Record only statuses, header names/attributes, asset hashes, and sanitized
error classes. Never record credentials, cookie/CSRF values, password text,
identity fields, MCRs, response bodies containing personal data, or database
URLs.

1. Confirm frontend and backend deployment records identify the same reviewed
   commit, correct branch, correct project, and expected roots.
2. Confirm `GET https://mata-backend.vercel.app/health` returns the expected
   controlled `200` application response, not
   `FUNCTION_INVOCATION_FAILED`, and is non-cacheable.
3. Open a new browser tab with DevTools Network preservation enabled and cache
   disabled. Submit one approved staff login through the UI.
4. Confirm the browser sends exactly
   `POST https://mata-aine.vercel.app/api/v1/auth/login`.
5. Confirm there is no browser request to `*.supabase.co`, `/auth/v1/token`,
   `grant_type=password`, or the absolute backend origin.
6. Confirm the login and subsequent `GET /api/v1/auth/me` are same-origin,
   contain no `Authorization` request header, and produce no authentication
   CORS preflight.
7. Confirm the proxy preserves the backend status, `Set-Cookie`,
   `Cache-Control`, `CDN-Cache-Control`, `Vercel-CDN-Cache-Control`,
   correlation header, and applicable exposed headers without redirecting the
   browser to the backend origin.
8. Confirm `__Host-mata_session` is scoped to the frontend host and has
   `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Domain`, and no
   persistent expiry attributes. Do not copy its value.
9. Confirm Local Storage, Session Storage, IndexedDB, URLs, console output, and
   frontend state contain no Supabase access/refresh token or MATA session
   credential. The bounded startup cleanup may remove only
   `mata.auth.session.v1`; confirm unrelated storage, including unrelated
   `sb-*` entries, survives. Clear site data once for users exposed to the
   browser-token deployment.
10. Perform one authorized unsafe request and confirm it uses the cookie plus
    `X-CSRF-Token`, without bearer authentication. Missing or wrong CSRF must
    return controlled `403`.
11. Confirm direct browser-to-backend public mutation traffic is rejected by
    Fetch Metadata or unsupported by the browser path; do not use real
    credentials for this negative test.
12. Confirm refresh rotates the opaque cookie and CSRF state without exposing
    either, `/auth/me` continues to hydrate, session expiry returns controlled
    `401`, and logout clears the cookie only on proof-positive server
    revocation.
13. Fetch the deployed HTML and referenced JS/CSS artifacts, record hashes,
    confirm no source maps are served, and run the same emitted-artifact
    signatures used in CI.
14. Repeat the controlled error checks for `401`, `403`, `409`, and `5xx`;
    responses and logs must contain no token, password, SQL, filesystem,
    connection-string, or identity detail.

Until every applicable row has current evidence, local success is not a
deployed pass.
