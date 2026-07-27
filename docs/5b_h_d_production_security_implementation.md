# 5B-H-D Production Security Implementation

Status: local/source implementation and verification complete on 2026-07-26; deployment verification not performed.

This report records the Phase 5B-H-D security implementation and its local evidence. It does not claim that Vercel, Supabase, or any other deployed environment has these controls. No live deployment, live database, live account, or live environment setting was changed while producing this evidence.

## Scope and public-portal boundary

The login, registration-options, and Non-NHG registration pages are intentionally public entry points. Vercel Deployment Protection, Vercel Authentication, or another outer gate is not a current application requirement. Public reachability does not make protected application data public:

- every protected API continues to require MATA authentication and server-side authorization;
- unauthenticated HTML must contain no protected shell data;
- browser roles retain no direct application-table privileges;
- exact Host, Origin, CORS, cookie, CSRF, caching, and security-header controls remain mandatory;
- frontend role guards are user-experience controls only;
- backend authorization remains mandatory even after Phase 5B-H-E adds full RLS.

## Implemented architecture

Production uses a same-origin browser topology:

```text
Browser
  -> relative /api/v1
  -> Vercel/Nginx same-origin proxy
  -> FastAPI
  -> backend-owned PostgreSQL app_sessions
  -> trusted users/residents/external_residents reload
```

The browser does not persist or routinely send an application bearer token. Staff credentials are sent to the MATA backend; the backend mediates the Supabase password flow and creates a MATA session. Native and Non-NHG Resident MCR login also create the same kind of backend-owned application session while retaining separate subject tables.

The normal production transport is `AUTH_TRANSPORT=cookie`. `bearer_compat` is an emergency rollback path only. Production rejects it unless the explicit rollback flag is also enabled; its resident HS256 secret must be at least 32 UTF-8 bytes and strict key-length enforcement is enabled.

## Cookie and CSRF contract

The production cookie is:

- named `__Host-mata_session`;
- `HttpOnly`;
- `Secure`;
- `SameSite=Strict`;
- `Path=/`;
- host-only, with no `Domain` attribute;
- bounded by the server-side absolute expiry.

Non-production uses a separate local cookie name so an insecure local cookie cannot shadow the production `__Host-` cookie.

The CSRF design is a synchronizer token:

- the raw CSRF value is returned only in the authenticated session response and held in frontend module memory;
- only a keyed digest is stored in `app_sessions`;
- Axios includes credentials on API requests;
- `X-CSRF-Token` is added only to `POST`, `PUT`, `PATCH`, and `DELETE`;
- caller-supplied CSRF headers are stripped before the trusted current value is applied;
- safe methods do not retain a CSRF header;
- on protected cookie-authenticated unsafe requests, missing, malformed, stale, or mismatched CSRF fails with a controlled `403`;
- rotation changes both session and CSRF material, so the old CSRF value is rejected.

## Session lifecycle and concurrency

`app_sessions` stores keyed token and CSRF digests, never the reusable raw values. It records subject type/id, subject generation, auth source, family id, idle and absolute expiry, revocation state, rotation parent, and an optional keyed user-agent hash.

The lifecycle is:

1. authenticate the staff or resident credential;
2. lock and reload the trusted subject;
3. create one root session family and set the cookie;
4. resolve the keyed token digest on each protected request;
5. reload the current subject and compare `session_generation`;
6. require current CSRF on protected cookie-authenticated unsafe methods;
7. rotate through `POST /auth/session/refresh`;
8. revoke the whole family on logout;
9. delete expired/revoked rows only through bounded cleanup.

Staff idle/absolute defaults are 1,800/28,800 seconds. Resident defaults are 3,600/43,200 seconds. Rotation defaults to 900 seconds. Revision `20260727_000027` subsequently adds a 60-second default touch interval, post-validation qualifying activity, minimal lifecycle helpers, and expiry-aware RLS context. All values remain configurable examples rather than approved production durations; see `docs/5b_h_session_lifecycle_assurance.md`.

### Concurrent rotation result

The original failing PostgreSQL test did not prove a production double-rotation defect. It allowed the second worker to begin resolution after the winning transaction committed. That worker safely observed no active old session and then failed through the test's `assert loaded is not None`, leaving the test's `AppSessionInvalidError` loser list empty. At the request boundary this is already a controlled invalid/unauthenticated outcome.

The test-only correction synchronizes both workers after they have resolved the original session. It therefore exercises the actual locked-row race rather than mixing it with the valid pre-rotation resolution outcome. No production relaxation was made.

The production rotation path:

- locks the subject;
- takes a transaction-scoped family advisory lock;
- reloads the database row with `SELECT ... FOR UPDATE`;
- uses `populate_existing=True`, so SQLAlchemy identity-map state cannot bypass the locked row;
- revalidates active state, subject identity, generation, family, and supplied token digest;
- revokes the parent before flushing one replacement;
- has a unique constraint on `rotated_from_session_id`.

Evidence from 20 process-isolated race repetitions, plus the focused PostgreSQL suite:

- exactly one rotation succeeded;
- exactly one loser received `AppSessionInvalidError`;
- exactly one child row existed and was usable;
- the parent was revoked with reason `rotated` and its token no longer resolved;
- no losing attempt created another child;
- old CSRF failed against both parent and child;
- the winner's rotated CSRF succeeded;
- no assertion, SQLAlchemy, transaction, connection, or pooling error occurred.

Separate AsyncSessions/connections were used for the workers and post-race verification. The authoritative locked row is refreshed from PostgreSQL, and no application-session object is retained as connection-local state, preventing pooled connections from reviving stale session state.

## Trusted identity and account-change invalidation

Every cookie-authenticated request reloads the current subject from `users`, `residents`, or `external_residents`. Client headers, frontend state, Supabase `user_metadata`, and stale token claims cannot grant role or scope.

Migration `20260722_000023` adds non-negative `session_generation` to all three subject tables and `session_issuance_blocked` to staff users. Staff deactivation, role/scope change, and ordinary approved account mutations atomically increment generation and revoke subject sessions. Password reset is deliberately two-stage: the issuance block, generation fence, and revocation commit before the upstream credential call; successful completion clears the block in a second transaction, while failure leaves issuance blocked for authorized retry. Refresh, logout, and subject-wide invalidation follow the global lock order subject -> family -> session rows so a losing transaction cannot resurrect a family.

## Frontend transport

The production frontend:

- has no Supabase browser client;
- has no browser app-token persistence;
- does not inject routine `Authorization: Bearer` headers;
- keeps only current identity, CSRF, and refresh-needed state in module memory;
- calls backend login, hydration, refresh, logout, and staff-account APIs;
- uses relative `/api/v1` in production;
- sends cookies with credentials;
- prevents a stale `401` response from clearing a newer session revision;
- retains all five role redirects and cross-role route guards.

The final dependency graph uses React 19.2.8, ReactDOM 19.2.8, and React Router 8.3.0. React Router v8 removed `react-router-dom`; all application imports now come from `react-router`.

## Request-boundary controls

- Production CORS origins and allowed hosts must be explicit, non-local values; wildcard entries fail configuration.
- Credentialed CORS allows only the configured CSRF header and necessary request headers.
- Protected cookie-authenticated unsafe requests require both an approved Origin and valid CSRF. Intentionally unauthenticated login/registration mutations require Origin and JSON but no existing-session CSRF.
- Trusted Host processing is enabled. The Starlette regression test confirms a malformed Host cannot poison the path used by middleware.
- Authenticated/session responses are `Cache-Control: no-store`; the same-origin proxy prevents CDN caching of API responses.
- Security headers include CSP, frame denial, content-type sniffing denial, HSTS in production, and a restrictive referrer policy.
- Production rejects stub/demo identity headers and does not trust raw `X-User-*`.

## PostgreSQL rate limiting

Production requires `RATE_LIMIT_STORE=postgres` and a server-only `RATE_LIMIT_HASH_SECRET` of at least 32 characters. `rate_limit_buckets` uses an atomic PostgreSQL upsert keyed by scope, keyed identifier hash, window start, and duration. Raw login identifiers, session ids, MCRs, and addresses are not stored in the bucket key. Cleanup is bounded by age and batch size.

## Upload and output hardening

XLSX input is checked before parser use for archive entry count, per-entry size, total uncompressed size, compression ratio, encrypted members, unsafe ZIP paths, and malformed workbook XML. Public write content types and declared body sizes are constrained before parsing. Parser, error, and audit paths redact credentials, tokens, database details, SQL, tracebacks, and sensitive row content. Existing spreadsheet formula protections remain in export paths.

## Database migrations and browser boundary

The H-D migration chain is linear:

- `20260722_000023` — durable backend-owned sessions and generation fencing;
- `20260722_000024` — revoke object and default privileges for `PUBLIC` and, when present, `anon` and `authenticated`.

Revision `20260722_000024` covers public-schema tables, sequences, and functions. Its downgrade deliberately does not recreate unknown broad grants; an operator may restore only a separately documented prior grant set.

This privilege boundary is not full row-level authorization. Earlier migrations enabled RLS on existing tables without a complete policy/runtime-role architecture. Phase 5B-H-E is the separate implementation phase for a non-owner, `NOBYPASSRLS` runtime role, transaction-local trusted identity context, complete policies, and workflow verification.

## Dependency advisory disposition

Registry requests contained only dependency names and versions. Raw responses were temporary, sanitized locally, and removed.

### Backend runtime

| Package | Original -> final | Advisory IDs | Severity | Fixed version |
|---|---|---|---|---|
| `idna` | 3.13 -> 3.15 | GHSA-65pc-fj4g-8rjx / CVE-2026-45409 / PYSEC-2026-215 | Moderate | 3.15 |
| `Mako` | 1.3.11 -> 1.3.12 | GHSA-2h4p-vjrc-8xpq / CVE-2026-44307 / PYSEC-2026-2617 | High | 1.3.12 |
| `pydantic-settings` | 2.14.0 -> 2.14.2 | GHSA-4xgf-cpjx-pc3j | Moderate | 2.14.2 |
| `python-multipart` | 0.0.26 -> 0.0.31 | GHSA-pp6c-gr5w-3c5g; GHSA-5rvq-cxj2-64vf; GHSA-6jv3-5f52-599m; GHSA-v9pg-7xvm-68hf | High; High; Low; Low | 0.0.27; 0.0.30; 0.0.30; 0.0.31 |
| `cryptography` | 45.0.7 -> 48.0.1 | GHSA-r6ph-v2qm-q3c2; GHSA-m959-cc7f-wv43; GHSA-p423-j2cm-9vmq; GHSA-537c-gmf6-5ccf | Scanner did not supply severity | 46.0.5; 46.0.6; 46.0.7; 48.0.1 |
| `PyJWT` | 2.10.1 -> 2.13.0 | PYSEC-2025-183 / CVE-2025-45768; GHSA-752w-5fwx-jx9f; GHSA-993g-76c3-p5m4; GHSA-jq35-7prp-9v3f; GHSA-fhv5-28vv-h8m8; GHSA-w7vc-732c-9m39; GHSA-xgmm-8j9v-c9wx | High/disputed; Critical; scanner did not supply the remaining severities | 2.13.0 |
| `starlette` | 1.0.0 -> 1.3.1 | GHSA-86qp-5c8j-p5mr; GHSA-wqp7-x3pw-xc5r; GHSA-x746-7m8f-x49c; GHSA-jp82-jpqv-5vv3; GHSA-82w8-qh3p-5jfq | Moderate; High; Moderate; Low; High | 1.0.1; 1.1.0; 1.1.0; 1.3.0; 1.3.1 |

The final sanitized `pip-audit` result is zero known vulnerabilities.

### Frontend runtime and development tree

| Package | Original range/version -> final | Advisory IDs | Severity | Type | Recommended fixed version |
|---|---|---|---|---|---|
| `axios` | `^1.16.0` / 1.16.0 -> `^1.18.1` / 1.18.1 | npm 1123882, 1123884, 1123885, 1123957, 1123959, 1123961, 1123967, 1123969, 1123971, 1123973 | High (1123967); others Moderate | Runtime | 1.18.0 |
| `react-router` | 7.15.1 -> 8.3.0 | npm 1124268, 1124271, 1124272, 1124276, 1124282 | Moderate, Moderate, Moderate, High, High | Runtime | 8.3.0 |
| `react-router-dom` | `^7.15.1` -> removed | aggregate moderate dependency finding | Moderate | Runtime | Remove for React Router v8 |
| `brace-expansion` | 5.0.7 -> 5.0.8 | GHSA-mh99-v99m-4gvg / npm 1124334 | High | Development-only (`eslint` -> `minimatch`) | 5.0.8 |
| `postcss` | 8.5.16 -> 8.5.23 | GHSA-r28c-9q8g-f849 / npm 1124288 | High | Development-only (`vite`) | 8.5.18 |

The Axios high path concerned the Node HTTP adapter; the deployed browser bundle did not establish that path, but the compatible patch was applied. The two development-only highs affected build/CI supply-chain tools and were patched without overrides. Final sanitized runtime and full-tree `npm audit` results are both empty.

No `audit fix`, `--force`, incompatible override, or automatic broad dependency upgrade was used.

## Local verification evidence

All PostgreSQL commands used only the disposable database `mata_phase5b_verify_5bhd`.

| Gate | Result |
|---|---|
| Backend compile | `python -m compileall app tests` passed |
| Alembic topology | one head: `20260722_000024` |
| Clean migration | recreated disposable DB, baseline -> head passed |
| Downgrade/re-upgrade | `20260722_000024` -> `20260721_000022` -> head passed |
| Alembic all-heads check | `20260722_000024 (head)` |
| Full backend | 1,104 passed, 0 failed/skipped/setup errors, 7 warnings, 749.54s |
| Focused H-D security | 230 passed, 1 Starlette test-client deprecation warning, 111.86s |
| PostgreSQL security file | 13 passed, 11.85s |
| Rotation race repetition | 20/20 process-isolated runs passed |
| Frontend contracts | 78 passed, 0 failed |
| Frontend lint/typecheck/build | all passed; existing large-chunk build warning only |
| Scanner/sanitizer tests | 16 passed |
| Frontend/worktree/diff source scans | all passed |
| Backend dependency audit | zero findings |
| Frontend runtime/full-tree audits | zero findings |

The seven full-backend warnings are six existing Alembic `path_separator` deprecation warnings and one Starlette test-client warning recommending the future `httpx2` test transport. Neither warning represents a failing production path. `httpx2` was not added solely to suppress a test-only warning.

## Deployment variable names

Required production names are documented without values:

- `ENVIRONMENT`
- `AUTH_MODE`
- `AUTH_TRANSPORT`
- `DATABASE_URL`
- `SYNC_DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY` or the supported backend anon-key alias
- `SUPABASE_SERVICE_ROLE_KEY`
- `MATA_SESSION_HASH_KEY`
- `MATA_SESSION_COOKIE_NAME`
- `MATA_STAFF_IDLE_TIMEOUT_SECONDS`
- `MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS`
- `MATA_RESIDENT_IDLE_TIMEOUT_SECONDS`
- `MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS`
- `MATA_SESSION_ROTATION_SECONDS`
- `MATA_SESSION_TOUCH_INTERVAL_SECONDS`
- `MATA_SESSION_CLEANUP_RETENTION_SECONDS`
- `MATA_SESSION_CLEANUP_BATCH_SIZE`
- `MATA_CSRF_HEADER_NAME`
- `MATA_ALLOWED_HOSTS`
- `CORS_ORIGINS`
- `RATE_LIMIT_STORE`
- `RATE_LIMIT_HASH_SECRET`
- `RATE_LIMIT_CLEANUP_RETENTION_SECONDS`
- `RATE_LIMIT_CLEANUP_BATCH_SIZE`

`MATA_ENABLE_PRODUCTION_BEARER_ROLLBACK` and `MATA_RESIDENT_SESSION_SECRET` are rollback-only. Frontend production configuration contains only `VITE_APP_ENV=production`, `VITE_AUTH_MODE=supabase`, and the relative API path; it requires no Supabase browser URL or key.

## Rollout and rollback

Deployment must be separately authorized and verified:

1. configure server-only values and exact origins/hosts;
2. deploy backend and same-origin proxy code capable of cookie sessions;
3. apply migrations through `20260722_000024` with the migration role;
4. verify the database revision and browser-role revocations;
5. deploy the frontend built for production/Supabase mode;
6. exercise all five identities and the post-deployment checklist below;
7. keep migration-owner recovery access separate from application runtime access.

Rollback must not restore raw production header trust, weaken CSRF/CORS/cookies, or broadly restore database grants. Prefer reverting application code and revoking/clearing H-D sessions. Emergency bearer compatibility requires explicit owner action, the rollback flag, a minimum 32-byte resident secret, strict JWT key checks, and renewed access restriction until cookie mode is restored.

## Post-deployment verification checklist

- Login and registration pages are reachable without exposing protected data.
- Master Admin, Programme PC, Secretary, NHG Resident, and Non-NHG Resident login/hydration/logout behave correctly.
- `Set-Cookie` has the exact `__Host-`, Secure, HttpOnly, Strict, host-only contract.
- No app token appears in local/session storage or routine request authorization headers.
- Production requests use relative `/api/v1`.
- For protected cookie-authenticated unsafe requests, missing/wrong/stale CSRF fails; current CSRF succeeds; rotation rejects old CSRF.
- Rotation yields one child and invalidates the parent; logout invalidates the family.
- Password reset, deactivation, and scope changes invalidate old sessions.
- Unapproved Origin and Host values fail closed.
- API/session responses are not cached by browser or CDN.
- Raw identity headers do not affect production identity.
- Database reports `20260722_000024`.
- `PUBLIC`, `anon`, and `authenticated` have no application-object privileges.
- No direct browser application-table call succeeds.
- Logs and error responses contain no credential, token, connection, SQL, or personal-row material.

## Known blockers and next phase

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED

MCR-only login remains a low-assurance resident identity mechanism. No second-factor source or delivery channel has been approved, and none was invented in H-D. Unrestricted real-data production approval remains blocked on that owner decision.

H-D code completion is not proof of deployed security. Phase 5B-H-E full PostgreSQL RLS is separate and must add the restricted runtime role, transaction-local trusted identity context, complete policies, and full-workflow testing without weakening FastAPI authorization or granting browser data access.

The later focused lifecycle assurance phase supersedes H-D's former
pre-validation touch behavior. Current requests resolve without touching;
only successful protected mutations qualify after CSRF/business validation,
and normal refresh extends neither the parent's idle deadline nor the family
absolute deadline.
