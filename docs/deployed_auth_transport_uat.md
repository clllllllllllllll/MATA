# Deployed Authentication Transport Remediation and UAT

Status: local remediation prepared; live Vercel inspection, configuration
changes, deployment, and post-deployment verification require separate
authorization.

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

The public backend currently also fails on `GET /health`, before login business
logic is involved. That narrows the platform failure to deployment identity,
project root/entrypoint, import-time settings, dependency/runtime loading, or
lifespan database-boundary attestation. The exact category is not established
without Vercel runtime logs and environment-name/scope inspection. No
speculative fallback application or weakened startup check is approved.

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

## Read-only Vercel inspection required before any mutation

An authorized operator must inspect both projects without copying values into
the evidence record.

For each variable, record only its name, Vercel scope, presence/absence,
public/server classification, and contract consistency.

### Frontend project

- Git repository and Production Branch: expected repository and `main`.
- Root Directory: `frontend`.
- Framework: Vite.
- Install Command: `npm ci`.
- Build Command: `npm run build`.
- Output Directory: `dist`.
- Node runtime: the reviewed supported version used by CI.
- Production alias: `mata-aine.vercel.app`.
- Deployment source: the reviewed remediation commit.
- Production-scoped public build variables:
  - `VITE_APP_ENV` — present, public, exact production contract;
  - `VITE_AUTH_MODE` — present, public, exact Supabase-mode contract;
  - `VITE_API_BASE_URL` — present, public, exact same-origin path contract.
- Obsolete `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`,
  `VITE_SUPABASE_ANON_KEY`, or any other `VITE_SUPABASE_*` name — absent.

Preview auth UAT must not be run against production data. The checked-in
external rewrite has one production backend destination; use a separately
reviewed isolated preview project/configuration before enabling authenticated
preview UAT.

### Backend project

- Git repository and Production Branch: same repository and reviewed commit as
  the frontend.
- Root Directory: `backend`.
- Entrypoint: `api/index.py`.
- Routing configuration: `backend/vercel.json`.
- Region: `hnd1`.
- Python runtime: 3.12, matching CI.
- Build-command override: absent unless separately reviewed.
- Production alias: `mata-backend.vercel.app`.

Production-scoped backend configuration names:

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

Inspect the failing `/health` invocation log and record only one sanitized
category:

- settings validation/missing variable names;
- Python import or dependency error;
- wrong project root or missing entrypoint;
- database DNS/connectivity/driver error;
- runtime/auth database role or endpoint mismatch;
- missing migration/helper/policy/grant/ownership boundary;
- startup timeout; or
- another exception class that contains no value, path, SQL, credential,
  identity, or bearer material.

If database connectivity is the category, verify that all three URLs target
the same approved database endpoint with distinct roles and that the endpoint
is reachable from Vercel. Do not switch blindly between direct, session-pool,
or transaction-pool endpoints; asyncpg prepared-statement compatibility and
the startup attestation must be tested against the selected mode.

## Separately authorized deployment actions

1. Correct only the inconsistent variable names/scopes, project roots, branch,
   route settings, or database endpoint class established by the read-only
   inspection.
2. Do not broaden CORS, enable production bearer compatibility, expose a
   backend secret to Vite, weaken RLS/startup attestation, or add a browser
   Supabase key.
3. Commit and review the local remediation separately; do not deploy an
   uncommitted worktree.
4. Deploy the backend reviewed commit first.
5. Confirm backend `/health` returns the controlled application response
   before deploying the frontend.
6. Deploy the same reviewed commit from the frontend project.
7. Confirm the production aliases point to the intended deployments; do not
   infer success from a completed build alone.
8. Users who used the superseded browser-token deployment should clear site
   data once, close old tabs, and open a new tab after promotion.

## Post-deployment verification

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
