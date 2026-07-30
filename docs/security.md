# Security Contract

Status: current repository security source of truth. This document describes
the implemented local contract at Alembic revision `20260728_000028`. Local
source, test, and disposable-database evidence is not proof of a deployed
Vercel or Supabase environment.

This document is authoritative for cross-cutting security behavior. Use it
alongside:

- `schema.md` for persistence, constraints, migrations, and database objects;
- `api.md` for routes and request/response contracts;
- `business-logic.md` for domain calculations and invariants;
- `parsing.md` for upload formats and parser behavior; and
- `auth-account-contract.md` for identity and account lifecycle details; and
- `99_decision_log_and_gap_audit.md` for architectural decisions, accepted
  trade-offs, unresolved gaps, and superseded decision history.

Historical Phase 5B security reports are retained in the
[Phase 5B security archive](archive/security/phase-5b/README.md) as dated
implementation, migration, UAT, and audit evidence. When a historical
statement conflicts with this document, this document and the current domain
contract take precedence.

## 1. Security objectives and threat model

MATA protects:

- opaque application-session credentials and CSRF values;
- staff credentials and Supabase privileged keys;
- runtime, authentication-helper, and migration database credentials;
- Resident identifiers and personal data;
- attendance, submission, upload, configuration, and audit records;
- programme, posting, subject-family, and administrative authority; and
- deployment configuration and security evidence.

The implemented controls assume attacks or failures from:

- unauthenticated internet clients;
- authenticated users attempting cross-subject, cross-family, cross-programme,
  or cross-posting access;
- stolen, replayed, expired, rotated, or revoked session credentials;
- stale tabs, late responses, failed logout networks, and concurrent requests;
- malicious multipart, spreadsheet, ZIP, XML, archive, and formula payloads;
- forged forwarding, identity, role, scope, Origin, CSRF, and request metadata;
- compromised low-privilege application or database credentials;
- connection-pool context leakage and transaction-boundary failures;
- accidental browser exposure of privileged environment values;
- dependency, workflow, and deployment supply-chain compromise; and
- leakage through errors, logs, caches, filenames, URLs, exports, source maps,
  or generated artifacts.

Security controls fail closed. Unsupported states do not receive compatibility
fallbacks, broader roles, inferred posting codes, or client-supplied authority.

## 2. Trust boundaries and invariants

The normal production path is:

```text
Browser
  -> approved HTTPS same-origin frontend/proxy
  -> FastAPI authentication, CSRF, authorization, and request limits
  -> restricted PostgreSQL runtime or authentication-helper credential
  -> database-owned subject context, grants, helpers, and RLS
```

The following are invariants:

1. Frontend route guards are user-experience controls, never the sole
   authorization boundary.
2. Protected authority is reloaded from trusted database state. Raw headers,
   request bodies, cookie claims, browser state, and Supabase user metadata do
   not supply trusted MATA roles or scope.
3. Production browser requests use the backend-owned opaque cookie transport.
   Browser bearer tokens are not the normal production contract.
4. Protected SQL uses a credentialed non-owner member of
   `mata_app_runtime`. Public authentication/session helpers use a separate
   credentialed member of `mata_auth_internal`. Migrations use a third,
   table-owning credential.
5. All three database credentials target the same database but use distinct
   login roles. Application credentials are `NOSUPERUSER` and `NOBYPASSRLS`.
6. Browser Supabase roles and `PUBLIC` receive no application-object access.
7. Sensitive identifiers and secrets must not be placed in browser storage,
   URLs, logs, exception text, build arguments, or frontend environment names.

## 3. Frontend and browser security

- Production uses same-origin relative `/api/v1` requests with credentials.
- Production and Supabase-mode builds require
  `VITE_API_BASE_URL=/api/v1` exactly. Missing, absolute, scheme-relative,
  credentialed, or differently rooted values fail the build.
- The browser does not construct a Supabase client or call Supabase Auth,
  REST, GraphQL, or RPC endpoints directly.
- The opaque session credential exists only in an `HttpOnly` cookie. The
  frontend holds current identity and the non-secret CSRF synchronizer value in
  module memory.
- Session credentials, CSRF values, and protected response data are not stored
  in `localStorage`, `sessionStorage`, or IndexedDB.
- Central protected caches and upload state are scoped to the current
  authentication generation and cleared on authentication loss.
- Stale `401` responses cannot clear a newer authenticated generation.
- Logout and cross-tab messages contain bounded epochs/request identifiers, not
  credentials or personal identifiers.
- Login return navigation accepts only exact role-allowed application routes;
  arbitrary external redirect targets are rejected.
- React escaping remains the rendering boundary. Production source must not add
  raw-HTML, dynamic-script, `eval`, `document.write`, or `javascript:` sinks
  without an approved design and sanitization contract.
- Sensitive personal-data filters and navigation context remain in protected
  component memory rather than browser query strings or fragments.
- Production builds must omit source maps and be scanned for privileged
  configuration names, secrets, local paths, test identities, and personal
  data before deployment.
- Startup removes only the exact historical `mata.auth.session.v1` entry from
  browser persistence. It reads no stored value, preserves unrelated keys, and
  is defense-in-depth only; current authentication never depends on that
  cleanup. The repository does not carry a trustworthy exact legacy Supabase
  project reference, so wildcard `sb-*` cleanup is forbidden. Users exposed to
  the browser-token deployment must clear site data once after remediation.

## 4. Backend authentication and authorization

The intentionally public production routes are:

- `GET /health`;
- `POST /api/v1/auth/login`;
- `GET /api/v1/external-residents/registration-options`;
- `POST /api/v1/external-residents/register`; and
- CORS preflight handling.

FastAPI documentation, ReDoc, and OpenAPI routes are disabled in production.
All other API surfaces require an application identity or an explicitly
documented authentication-boundary proof.

Authorization rules include:

- Master Admin authority requires the current staff role and explicit persisted
  master level.
- Programme PC access requires normalized non-empty programme scope; empty
  scope grants nothing.
- Secretary access requires the current exact posting code.
- Native and Non-NHG Resident access is typed and scoped to the current
  database-owned subject. The two storage families cannot cross-access.
- Object identifiers are always combined with subject, programme, posting, or
  administrative predicates as required by the endpoint contract.

Production rejects raw `X-User-*` authority and ordinary bearer fallback.
Stub/demo identity headers remain local/test-only.

Staff passwords are sent only to the MATA backend. The backend mediates the
reviewed Supabase password endpoint and never returns Supabase access or
refresh tokens to the browser. Production Supabase project, issuer, and JWKS
configuration must use HTTPS, contain no userinfo/query/fragment, and resolve
to the same explicitly reviewed project origin and expected Auth paths.
Service-role operations use only that reviewed origin.

Resident authentication assurance remains separately governed product debt.
This security contract does not invent or imply an unapproved second factor.

## 5. Opaque sessions, expiry, rotation, and logout

The production cookie is host-only, named `__Host-mata_session`, `Secure`,
`HttpOnly`, `SameSite=Strict`, and has no browser-controlled identity claims.
Only a keyed digest of the raw credential is stored in `app_sessions`.

Each session is bound to:

- an exact typed subject and subject generation;
- one session family;
- an idle-expiry deadline;
- a fixed family absolute-expiry deadline; and
- a session-bound CSRF digest.

Equality with either deadline is expired. Refresh rotates the credential and
CSRF value but does not extend the current idle or family absolute deadline.
Rotation uses subject locking, a transaction-scoped family advisory lock, and a
fresh locked row so only one concurrent winner succeeds.

Password reset, deactivation, issuance blocking, role/scope changes, generation
changes, explicit revocation, expiry, or family replacement invalidate session
authority as documented by the account contract.

Logout clears browser identity, CSRF, protected cache/upload state, and
authenticated UI immediately. Server logout is described as confirmed only
after the response carries the proof-positive confirmation field. Otherwise a
bounded, non-sensitive tombstone keeps logout pending, blocks hydration and
protected requests, and retries on the documented finite schedule. A stale
logout response cannot revoke or clear a newer login.

## 6. CSRF and request-origin controls

Unsafe cookie-authenticated requests require:

- an exact approved production `Origin`;
- the cookie-coordination protocol header where required; and
- the current session-bound `X-CSRF-Token`.

The synchronizer value is held in memory and rotated with the opaque session.
Missing, malformed, stale, or mismatched proof receives a generic denial and
does not reveal subject or session existence. CORS uses explicit HTTPS origins
with credentials; production wildcards, local origins, userinfo, paths,
queries, and fragments are rejected.

## 7. Rate limiting and abuse controls

Production requires `RATE_LIMIT_STORE=postgres`. Rate-limit identifiers are
normalized then transformed with keyed HMAC-SHA256 before persistence; raw IP,
email, MCR, subject, cookie, or CSRF values are not stored.

Protected classes include:

- login and external registration;
- general reads and mutations;
- attendance mutations;
- staff-account mutations;
- reports and exports; and
- upload routes before parser work.

PostgreSQL fixed-window increments are atomic and persist across workers and
process restarts. Cleanup is retention- and batch-bounded. Application code
uses the ASGI server's trusted `request.client` value and does not parse
caller-supplied forwarding headers. The deployed proxy must be configured so
that value represents the reviewed client-network boundary.

Changes to middleware order must prove that rejected authentication/session/
CSRF traffic is bounded without double-counting the normal authenticated route
limit. Generic `429` responses include `Retry-After` and reveal no account or
session existence.

The current route limiter executes after authentication. Repeated invalid
session or CSRF requests can therefore consume authentication-database work
without incrementing the normal route bucket. A correct outer limiter needs a
non-consuming RLS-safe precheck plus failure recording, or a separately
verified ingress control; simply moving the current consuming helper would
double-count valid requests.

## 8. Upload and parser hardening

The approved ingress contract is:

- 4 MiB maximum complete request body;
- 4 MiB maximum aggregate upload request;
- 3 MiB maximum file;
- one route-appropriate file;
- 4 KiB maximum non-file multipart field; and
- 255-byte maximum decoded UTF-8 filename.

The pure ASGI body limiter counts streamed bytes independently of
`Content-Length` and stops the first crossing chunk before authentication or
multipart parsing. Conflicting, malformed, negative, or oversized lengths fail
safely. Nginx mirrors the 4 MiB boundary and disables upload request buffering.

Workbook preflight rejects unsupported extensions, invalid ZIP signatures,
ZIP64, traversal, duplicate members, symlinks, encrypted entries, external
relationships, DTD/entity declarations, oversized members/archives, excessive
entry counts, and suspicious compression ratios. Parser-specific structural
and cell limits remain authoritative after preflight. Spreadsheet exports
sanitize formula-leading cells.

Upload business rows, upload evidence, warnings, and audit rows currently have
separate transaction boundaries. Their unification is deferred because it
requires a coordinated workflow redesign and failure-evidence decision.

## 9. PostgreSQL roles, RLS, grants, and helpers

At revision `20260728_000028`:

- 34 application tables have RLS enabled;
- 84 action policies target only `mata_app_runtime`;
- application policies do not target `PUBLIC`, `anon`, `authenticated`, or a
  service role;
- application login roles are non-owner and `NOBYPASSRLS`;
- `app_sessions`, rate-limit infrastructure, and other helper-only resources
  have no direct runtime table grant;
- table, column, sequence, schema, and function access is explicitly
  allowlisted; and
- browser/Data API and `PUBLIC` application-object privileges are revoked.

`mata_app_runtime` and `mata_auth_internal` are stable `NOLOGIN`,
`NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`,
`NOREPLICATION`, `NOBYPASSRLS` capability groups. Credentialed application
logins inherit only the required group. Migrations and application objects use
a distinct owner.

Revision `20260726_000025` normalizes the reviewed `pgcrypto` dependency
before it creates any H-E helper. It accepts the extension only in `public` or
Supabase's standard `extensions` schema, requires the migration user to own
the extension, verifies the exact four C-language extension-member functions
and requires relocation support when needed. An installation in `extensions`
is moved transactionally to `public`, after which the exact `public.*`
functions and their ACLs are revalidated. Execution on every `pgcrypto`
extension-member routine is revoked from `PUBLIC`, the application
capabilities, and optional Supabase browser/service roles before any reviewed
grant is installed. This is a bounded Supabase-baseline normalization, not a
dynamic search-path or arbitrary-schema fallback.

Revision `20260726_000026` likewise enables RLS on `public.users`
idempotently before asserting the reviewed pre-cutover inventory. This
converges a clean local database and the approved Supabase baseline, where
`users` was already protected, on the same 15 pre-existing and 19 newly
enabled RLS tables. It does not accept an arbitrary policy or grant inventory;
the final 34-table, 84-policy and exact-ACL assertions remain unchanged.

Production `SYNC_DATABASE_URL` must use `postgresql://` or
`postgresql+psycopg2://`; the backend packages psycopg2 and rejects the
unbundled psycopg 3 scheme `postgresql+psycopg://` at settings validation.
`get_settings()` converts Pydantic validation failures to a startup-safe
configuration exception built without the validation input or context. The
message may identify the failed configuration contract, but must never render
environment values, URLs, passwords, tokens, or key material in function
logs.

Security-definer helpers have reviewed owners, fixed `pg_catalog,pg_temp`
search paths, exact signatures and ACLs, and no ambient `PUBLIC` execution.
The narrow definer used for database-owned context has a separately attested
surface. Every current function explicitly revokes ambient `PUBLIC` execution.
The database does not yet have an effective owner-scoped default ACL overriding
PostgreSQL's built-in `PUBLIC` execute default for future functions, so every
new function must continue to revoke it explicitly until that debt is closed.

PostgreSQL 16 automatically records a creator membership when a hosted
Supabase migration owner that is not a superuser but has `CREATEROLE` creates
the narrow `mata_adhoc_attendance_definer` role. In
`pg_catalog.pg_auth_members`, the new definer is the granted role, the
`mata_rls` schema owner is the member, the grantor is a superuser, and the edge
has `ADMIN OPTION` but has both `INHERIT OPTION` and `SET OPTION` disabled.
Revision `20260728_000028` therefore accepts either no membership edge or
exactly that bounded PostgreSQL 16 creator edge, and only when the member owns
`mata_rls` and has both `CREATEROLE` and `BYPASSRLS`. It rejects any membership
where the definer is the member, any additional or foreign member, any
non-superuser grantor, and any edge with `INHERIT OPTION` or `SET OPTION`.
Startup attestation applies the same exact alternatives; this compatibility
does not permit an application login or capability group to inherit, set, or
administer the definer.

Signed transaction-local context is bound to the transaction, backend PID,
database, session user, application session and authorization fingerprint.
Lifecycle-sensitive statements revalidate expiry/revocation. Root transaction
hooks clear or expire context so pooled connections cannot reuse prior
authority.

Table owners intentionally bypass their own non-forced RLS; application traffic
never uses an owner credential. `FORCE ROW LEVEL SECURITY` is therefore not
part of the current application-role contract.

## 10. Atomic attendance and concurrency guarantees

Attendance creation, overlap checks, deletion, and ad-hoc creation use
transaction-scoped advisory or row locks, uniqueness constraints, typed
ownership, and one caller-owned transaction.

Resident-created ad-hoc events preserve immutable native/Non-NHG creator
identity. The narrow creation helper derives the current subject from database
context and creates the event and matching attendance atomically. Native and
Non-NHG storage families cannot associate with the wrong creator type.

Removed attendance is retained as history. Resubmission creates a new active
row, so a stale removal identifier cannot affect newer evidence.

## 11. Errors, logging, privacy, and redaction

- Validation responses omit submitted values and sensitive input echoes.
- Unexpected errors do not return exception text, SQL, stack traces,
  filesystem paths, identities, session state, or credentials.
- Structured redaction covers authorization/cookie/CSRF/password/token/key
  material, database URLs, email, IP, MCR, and related identifier fields.
- Raw rate-limit identifiers are neither logged nor stored.
- Protected responses are private/no-store and deployment proxies must not
  cache API responses.
- MCRs and other personal identifiers must not appear in route segments,
  browser query strings, fragments, filenames, saved audit filenames, or
  access-log URLs.
- Production source must not add debug logging of protected payloads, identity
  objects, headers, environment values, or parser contents.

## 12. Supabase public configuration and privileged secrets

Supabase publishable/anon keys identify a project and are not backend
privileged credentials. Even so, MATA's production browser does not need a
Supabase client, URL, or key because application data access is backend
mediated.

The following remain backend-only secrets:

- `SUPABASE_SERVICE_ROLE_KEY`;
- runtime, authentication-helper, and migration database credentials;
- application session hash keys;
- rate-limit hash keys;
- any bearer-compatibility signing secret; and
- private keys or provider credentials.

No backend secret may use a `VITE_*` name, frontend build argument, public
runtime configuration, browser storage, source-controlled `.env`, client log,
or generated bundle. Example files contain placeholders or local disposable
values only.

## 13. Deployment perimeter

Production assumes:

- HTTPS termination at the approved public origin;
- an exact trusted-host allowlist;
- exact HTTPS CORS origins;
- same-origin `/api/v1` proxying;
- correct trusted-proxy/client-IP configuration;
- no API response caching;
- 4 MiB ingress request enforcement; and
- secure cookie preservation through the proxy.

The frontend Vercel route is an external rewrite, not a redirect. It preserves
the `/api/v1/:path*` suffix and must preserve the method, query, request body,
response status, `Set-Cookie`, CSRF, correlation, and cache-control headers.
It must not synthesize `Authorization`. API caching is explicitly opted out
with browser, CDN, Vercel-CDN, and rewrite-caching controls.

Production public mutations accept browser Fetch Metadata only when
`Sec-Fetch-Site: same-origin`. A direct browser call to the backend deployment
therefore fails even when the frontend and backend share the `vercel.app`
site. Missing Fetch Metadata remains supported for approved non-browser
operational checks that independently satisfy Origin, content-type, rate-limit,
and session-coordination controls.

Required headers include CSP, HSTS, `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, a strict referrer policy, a restrictive
permissions policy, COOP/CORP where supported, and cache denial for API and
authentication responses. CSP keeps scripts same-origin and denies framing,
objects, and base-URI changes.

Repository configuration is not deployment evidence. Deployed environment
names/values, TLS, headers, cookies, cache behavior, proxy identity, migration
revision, roles, grants, policies, helper ACLs, and five-role workflows require
separate evidence against an approved target.

## 14. CI and dependency controls

GitHub Actions receive read-only repository contents by default. Every external
action is pinned to a reviewed full commit SHA; version comments record the
maintained major line without making it executable. Changes to pinned SHAs
require a source/release review.

CI runs:

- backend compilation, migrations, tests, and dependency audit;
- frontend tests, lint, type-check, production build, and dependency audit;
- security-scanner unit tests;
- frontend browser-auth/secret-boundary scans; and
- post-build frontend artifact and source-map scans; and
- redacted added-diff secret scanning.

Every CI production frontend build explicitly supplies the public, non-secret
contract `VITE_APP_ENV=production`, `VITE_AUTH_MODE=supabase`, and
`VITE_API_BASE_URL=/api/v1`. The build-time environment validator remains
fail-closed for all three variables and rejects every other production API
base; no browser Supabase URL or key is needed.

GitHub Actions variables do not populate Vercel project settings. The frontend
Vercel Preview and Production scopes must each supply the same three-value
contract. Branch-specific Preview overrides must remain consistent, and any
Vercel environment change requires a new deployment before it can affect a
build.

Backend CI starts PostgreSQL on its maintenance database, then a shared local
workflow action creates and attests exactly
`mata_phase5b_final_security_review`. The workflow owns that provisioning and
applies the single Alembic head before tests. The `migration_mutation` cases
run first in one serial direct-owner pytest process;
their fail-closed fixtures require the exact local database, direct owner, and
zero competing sessions before every mutation. CI then verifies that the
database returned to head and uses a bounded direct-owner attestation to require
zero competing sessions and zero residual `mata_test_*` roles before reuse. The
later complete restricted suite selects the complementary
`not migration_mutation` partition, so it does not repeat those schema lifecycle
cases. A collection invariant requires every test using a reviewed mutation
fixture to carry the marker and forbids the marker elsewhere; the Alembic
primitive independently refuses an unmarked caller.

Complete and PostgreSQL-containing focused suites run through
`tests.run_rls_restricted_pytest`, which derives distinct ephemeral
runtime/auth logins, enables RLS, retains cookie transport, and removes every
generated `mata_test_*` role. A dedicated restricted integration step
exercises `RATE_LIMIT_STORE=postgres`; broad regression steps override only
that setting to `memory` because their unit fixtures explicitly test the
in-memory middleware. The RLS, database-role, and cookie contracts stay
enabled in both modes. The local harness deliberately uses `ENV=test` and stub
application identities; production Settings reject localhost. Session and
rate-limit secrets are synthetic CI-only placeholders, and the jobs contain
no live Supabase configuration.

Dependency lockfiles and exact Python requirement versions are committed.
Saved advisory artifacts contain only approved package/advisory metadata; raw
registry output is temporary. Dependency audit success means only that the
queried advisory sources reported no known issue at that time.

## 15. Migrations, rollback, and recovery

Forward migrations are the authoritative production path. Before applying a
migration, verify the exact target, backup/recovery plan, credential role and
maintenance window. Application traffic must use a compatible application and
database revision.

For a staging rehearsal or approved production change, the phase-neutral
migration smoke sequence is:

1. record the intended commit, expected Alembic head, safe target label,
   maintenance approval, backup/recovery owner, and rollback revision;
2. prove that the effective synchronous and asynchronous URLs name the same
   exact target without displaying their credentials;
3. run `alembic heads` and `alembic current` before the change, then use only
   the reviewed migration/ownership credential for `alembic upgrade head`;
4. verify the resulting revision, required seed/catalogue invariants from
   `schema.md`, and the complete role, ownership, helper, RLS, policy, grant,
   sequence, default-ACL, `PUBLIC`, and browser-role catalogue;
5. run the application startup attestation and the approved role/workflow
   smoke without inserting production personal data into evidence; and
6. retain only redacted commands, safe target identifiers, revisions, counts,
   outcomes, timestamps, and reviewer attribution.

An ambiguous target, missing backup/recovery owner, catalogue mismatch, or
failed startup attestation is a stop condition. Historical Phase 5B migration
plans remain evidence of earlier rehearsals and do not replace this sequence.

A Supabase upgrade attempt that began at revision `20260721_000022` exposed the
PostgreSQL 16 creator edge above. The former revision-`000028` assertion
rejected every membership edge, so the assertion failed and the migration
transaction rolled back atomically to `000022`. Before retrying, operators must
rerun the full rollback preflight, including the exact target and revision,
recovery point and authorized recovery owner/window, and complete pre-upgrade
catalogue checks without displaying connection values or credentials. That
failed attempt is not evidence that revision `000028` or its startup
attestation has succeeded on the deployed target.

Security migrations may restore historically compatible but weaker behavior
during downgrade. A generic `alembic downgrade -1` is not an online production
security procedure. Downgrade of session, RLS, helper, role/grant, or ad-hoc
ownership revisions requires:

1. an approved rollback revision and impact review;
2. drained application traffic;
3. coordinated application rollback;
4. post-migration role/grant/policy/helper attestation; and
5. forced reauthentication before traffic resumes.

The `pgcrypto` move to `public` and the pre-existing classification of
`public.users` RLS are retained hardening. Downgrade does not move the
extension back to `extensions` or disable RLS on `users`, and operators must
not attempt either action as an ad-hoc rollback. A rollback therefore does not
recreate the byte-for-byte pre-cutover Supabase catalogue; it requires the
same drained, coordinated review and attestation as the other retained role,
ACL, and browser-denial hardening.

Disposable verification must use an exact explicitly approved local database,
print and assert its name and local host before mutation, set synchronous and
asynchronous URLs in fresh child processes, and remove every ephemeral
`mata_test_*` role. Tests must not drop a retained review database without
separate authorization.

## 16. Locally verified controls

Current repository evidence includes:

- source-contract tests for migration chain, RLS policy/grant inventory,
  lifecycle helpers, and restricted-role harness safety;
- focused session, CSRF, rotation, logout, cross-tab, rate-limit, request-body,
  multipart, workbook, RLS, attendance, and concurrency tests;
- full backend and frontend regression gates;
- a fresh production frontend build and artifact scan;
- a clean local base-to-head migration plus reviewed downgrade/re-upgrade;
- live local catalogue attestation for roles, grants, helpers, policies,
  ownership, `PUBLIC`, browser roles, and residual test roles;
- frontend, worktree, cumulative-diff, likely-secret, personal-data, npm, and
  pip dependency scans; and
- GitHub Actions pinning and workflow-permission tests.

The final-review handoff records the exact commands, counts, durations,
failures, and reruns for this evidence. Historical report totals are not
silently reused.

## 17. Deployed checks still required

Before UAT or production approval, verify against the explicitly approved
target:

- the frontend and backend aliases resolve to the same reviewed remediation
  commit and expected project roots;
- browser staff login contacts only the frontend-origin
  `/api/v1/auth/login`; no browser request reaches a Supabase Auth endpoint or
  the backend origin directly;
- `/auth/me`, refresh, logout, and protected API traffic remain same-origin,
  carry no `Authorization` header, and cause no authentication-related CORS
  preflight;
- `__Host-mata_session` is host-only, `Secure`, `HttpOnly`,
  `SameSite=Strict`, `Path=/`, and has no `Domain`, `Max-Age`, or `Expires`;
- no Supabase access/refresh token exists in browser storage, IndexedDB, URL,
  log, source map, or application state;
- `/health` and controlled auth errors are application responses rather than
  `FUNCTION_INVOCATION_FAILED`;
- exact environment configuration without disclosing values;
- reviewed Supabase origin, issuer, JWKS and service-role destination;
- TLS, HSTS, CORS, Host, cookie, CSRF, proxy-IP and cache behavior;
- deployed Alembic revision and the complete role/RLS/grant/helper/default-ACL
  catalogue;
- absence of browser/Data API and `PUBLIC` application privileges;
- session rotation, expiry, revocation, password-reset, authority-change and
  reliable-logout behavior under real network/browser conditions;
- rate-limit threshold, concurrency, persistence and cleanup behavior across
  deployed workers;
- request and upload limits at every ingress;
- access-log/query-string redaction and protected export handling; and
- Master Admin, Programme PC, Secretary, native Resident, and Non-NHG Resident
  workflow isolation.

For each deployed check, record the reviewed target label, application commit,
database revision, time, operator/reviewer, safe command or observation, and
one of `PASS`, `FAIL`, `BLOCKED`, or `MANUAL VERIFICATION REQUIRED`. Evidence
must contain no credential, session/CSRF value, MCR, personal record, raw
protected response, or connection string. Current results belong in a new
approved deployment record; archived Phase 5B verdicts and evidence rows are
never edited to imply a later deployment result.

No local test result should be relabelled as deployed evidence.
Use `docs/deployed_auth_transport_uat.md` for the current bounded deployment
configuration and verification record.

## 18. Deferred security debt

| Severity | Item | Required follow-up |
|---|---|---|
| Medium | Invalid session and CSRF failures occur before the current application route limiter. | Add a non-consuming RLS-safe outer precheck plus failure-recording helper, or prove an ingress limiter, without double-counting valid requests. |
| Medium | Admin Logs keeps its MCR-capable free-text search and record identifiers out of SPA history, but the compatible GET API still places them in a request URL. | Introduce an authorized POST search contract or prove query omission/redaction at every access-log layer. |
| Medium | Upload domain changes, upload logs, warnings, and audit rows commit separately. | Design one transaction owner and explicit failed-upload evidence semantics; add failure-injection tests for every upload family. |
| Medium | Most audited configuration mutations commit before revalidation and audit evidence. | Extend the existing non-committing service pattern and prove rollback on audit/revalidation failure. |
| Medium | Security migration downgrades can temporarily restore weaker historical authorization. | Design security-monotone compatibility or mandate the drained rollback procedure above. |
| Low | RLS policy attestation checks exact inventory but not a canonical hash of every predicate. | Add normalized expression/hash attestation and a negative drift test. |
| Low | Current function ACLs are safe, but the attempted schema-scoped default-privilege revoke did not override PostgreSQL's built-in `PUBLIC` execute default for future functions. | Add global owner-scoped default-ACL revokes for every permitted function creator, then attest exact `pg_default_acl` entries and add a negative future-function test. |
| Low | A stub/demo login helper can expose a password verifier to the narrow auth capability. | Remove or narrow the production helper output while retaining local demo behavior. |
| Low | Containers use mutable base-image tags and the backend runtime user is root. | Review digest pinning and non-root runtime images as bounded operations work. |
| Low | Python requirements are exact-version pinned but do not use hashes. | Adopt reviewed hash-locked production dependencies when the packaging workflow is approved. |

Resident identity assurance is tracked as separate product debt and is not
redesigned by this security-maintenance contract.

## 19. Document maintenance

Update this document whenever a change affects authentication, authorization,
session lifecycle, CSRF, rate limiting, uploads, RLS, grants, helpers,
concurrency, privacy/redaction, deployment security, CI, dependencies, or
rollback.

Every such change must:

1. update the applicable domain contract;
2. update this cross-cutting contract;
3. add or update observable regression coverage;
4. record what is locally verified versus still deployment-dependent;
5. preserve reports in the
   [Phase 5B security archive](archive/security/phase-5b/README.md) as dated
   evidence rather than rewriting their results; and
6. avoid real secrets, credentials, MCRs, personal data, or production
   connection strings.
