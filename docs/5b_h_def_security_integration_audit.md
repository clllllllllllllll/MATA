# Phase 5B-H-D/E/Lifecycle Combined Security Integration Audit

Date: 27 July 2026 (Asia/Singapore)

Status: **PARTIAL AUDIT COMPLETE — CONTINUATION REQUIRED**

The cumulative H-D transport, H-E PostgreSQL RLS, and session-lifecycle work
was audited locally. No Critical finding remains. One High cross-account
cookie-response race was confirmed, corrected, and covered by deterministic
regressions. Three bounded Medium corrections were also completed. Confirmed
design-heavy Medium findings remain documented for a later, separately scoped
change.

This audit did not push, merge, deploy, access live Supabase, access Vercel,
run a remote migration, or change a live system. Local evidence is not
production verification.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED

Absolute expiry limits the maximum usable lifetime of a stolen session but
does not prevent session theft.

## Audited commits and ancestry

- Main and merge-base:
  `ef33956b44e889a70dcc8f2dda4a1d6a2ef5f99a`
- H-D:
  `06b976bc4e3dc3f45d9a110a750bba4402d56b3e`
  (`feat(security): harden production session transport`)
- H-E:
  `5a9934505856f25c94f2b1590b8b85b49643e981`
  (`enforce full PostgreSQL row-level security`)
- Session lifecycle:
  `ac6ed465e3d4fdbd9a7577b2d71a339caf4694f9`
  (`feat(security): enforce bounded session lifecycle expiry`)
- Audit branch:
  `CL/5b-h-def-security-integration-audit`
- Audit-branch starting commit:
  `ac6ed465e3d4fdbd9a7577b2d71a339caf4694f9`

Git verified that H-D and H-E are ancestors of the audit starting commit.
`main..HEAD` contains exactly H-D, H-E, and the lifecycle commit in that
order. The committed cumulative scope at audit start was 165 files,
36,974 insertions, and 4,286 deletions against `main`.

The session-lifecycle commit itself contains 64 files, 9,087 insertions, and
1,076 deletions. Its source branch was clean after commit. The audit fixes in
this document intentionally remain uncommitted.

## Audit method

Six independent read-only streams were consolidated before editing:

1. H-D authentication, cookie/CSRF transport, rate limits, uploads, redaction,
   and dependencies.
2. H-E roles, ownership, RLS helpers/policies, grants/default ACLs, signed
   transaction context, and pool isolation.
3. Idle/absolute expiry, rotation, logout proof, revocation, cleanup, frontend
   session/cache/upload fences, 401 handling, and cross-tab behavior.
4. Combined race traces across login, refresh, logout, reset/deactivation,
   authority changes, RLS transactions, pooled connections, and identity
   families.
5. Complexity, duplicated invariants, dead compatibility, state truth, and
   defense-in-depth boundaries.
6. Tests, fake/real transaction drift, migration topology/lifecycle, source
   scope, documentation, and likely-secret/personal-data review.

The coordinator then reproduced each accepted path from source, reconciled
overlapping reports, rejected unsupported theoretical concerns, applied only
the authorized bounded fixes, and ran focused plus complete integrated
verification.

Web Locks were selected because they provide an origin-scoped exclusive lock
held across an asynchronous operation in a secure context. There is
deliberately no `BroadcastChannel` or `localStorage` mutex fallback: neither
can fence browser-applied `Set-Cookie` response headers. The relevant platform
references are the [W3C Web Locks specification](https://www.w3.org/TR/web-locks/)
and [MDN Web Locks API reference](https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API).
Both `preview:supabase` and `production:supabase` deliberately share this
frontend requirement. Preview must use HTTPS (or localhost) and a browser with
Web Locks; unsupported HTTP preview origins and embedded browsers fail closed
before dispatch. This is a documented availability constraint, not an
uncoordinated-cookie fallback.

## Findings

### Critical

None confirmed.

### High — fixed

#### AUD-H-01 — late lifecycle response could roll a newer login back to another identity

- Classification: confirmed concurrency, authentication, and frontend-state
  defect.
- Origin: H-D fixed-name cookie transport combined with lifecycle
  revision/epoch fences.
- Affected symbols:
  `backend/app/routers/auth.py::{login,refresh_session,logout}`,
  `backend/app/services/session_transport.py::{set_session_cookie,clear_session_cookie}`,
  `backend/app/middleware/auth_stub.py::AuthStubMiddleware`,
  `frontend/src/api/authCookie.ts`, `frontend/src/api/http.ts`, and
  `frontend/src/context/AuthContext.tsx`.
- Execution path: tab A began a valid refresh for identity/family A; tab B
  completed a newer full login for identity B; A's response arrived last and
  the browser unconditionally applied its fixed-name HttpOnly `Set-Cookie`.
  JavaScript revision checks could reject A's response body but could not
  reject the cookie header. A later safe protected request was fenced as B in
  frontend memory while authenticating server-side as A.
- Impact: cross-account/cross-role protected-read disclosure and session
  rollback in one browser profile, including staff role changes and
  native/Non-NHG identity changes. CSRF normally prevented unsafe writes, but
  safe reads did not require CSRF.
- Reproducible evidence: login and successful refresh both wrote the same
  cookie after commit, while frontend fences ran only after the HTTP response.
  Existing tests covered memory ordering and one-winner database rotation
  separately, not the browser cookie jar.
- Prior test gap: the test suite never delayed an older successful response
  past a newer login and then applied both responses to one shared cookie jar.
- Smallest safe correction: serialize login, refresh, and logout through HTTP
  response completion with one same-origin exclusive Web Lock; version-gate
  all production browser requests; stop uncoordinated/generic responses from
  changing the cookie; and make logout deletion conditional on a matching
  proof actually revoking the presented family.
- Regression evidence:
  `frontend/src/api/authCookieCoordination.contract.test.ts`,
  the new static contract in `frontend/src/authSession.contract.test.ts`, and
  production protocol/conditional-cookie cases in
  `backend/tests/test_cookie_session_transport.py`.
- Resolution: fixed. Production requests now require
  `X-MATA-Session-Coordination: web-locks-v1`. Missing or unsupported
  coordination fails before protected dispatch and without `Set-Cookie`.

### Medium — fixed

#### AUD-M-01 — refresh loser or stale failure could delete the winning/new cookie

- Classification: confirmed concurrency and session-availability defect.
- Origin: H-D/lifecycle refresh loser behavior.
- Affected symbols:
  `backend/app/routers/auth.py::refresh_session`,
  `backend/app/middleware/auth_stub.py::AuthStubMiddleware`,
  `frontend/src/api/http.ts`, and the former
  `test_concurrent_refresh_failure_is_generic_and_clears_cookie`.
- Execution path: two tabs refreshed one parent; PostgreSQL allowed one child;
  a later loser 401 emitted `Max-Age=0` and could delete the winner's child.
  The same deletion could follow a stale protected 401, store failure, final
  touch failure, or proof-mismatched logout.
- Impact: forced browser-wide logout and an unreachable but active child until
  timeout; no privilege gain.
- Evidence/test gap: existing tests explicitly required loser deletion while
  database tests proved one winner/loser only at service level.
- Correction: refresh conflicts are non-clearing 409 responses; generic
  authentication/store/touch failures no longer emit cookie deletion; logout
  clears only for a positive family-revocation result. The High fix's exclusive
  response lock prevents updated tabs from issuing concurrent lifecycle cookie
  mutations.
- Regression: focused cookie transport, RLS application, PostgreSQL logout
  proof, frontend response-lock, and complete suites all pass.

#### AUD-M-02 — staff role aliases split the persistent account rate-limit bucket

- Classification: confirmed authentication-control defect.
- Origin: H-D persistent login rate limiting.
- Affected symbol:
  `backend/app/dependencies/persistent_rate_limit.py::_login_identifier`.
- Execution path: one email could alternate `staff`, `admin`, and `secretary`
  role hints. The backend accepts those compatibility hints, but they formerly
  produced separate persistent identifiers.
- Impact: the intended 10/hour per-account bound could be multiplied across
  aliases.
- Prior test gap: resident/native-external alias aggregation was tested; staff
  aliases were not.
- Correction: `staff`, `admin`, and `secretary` now normalize to one
  `staff:email:<lowercase>` bucket.
- Regression:
  `backend/tests/test_persistent_rate_limits.py` alternates all three aliases
  and proves the eleventh attempt is 429.

#### AUD-M-03 — documented production bearer rollback was unreachable

- Classification: confirmed operational correctness and documentation drift.
- Origin: H-D rollback text superseded by H-E.
- Affected symbols/docs:
  `backend/app/config.py` production/RLS validators, `.env.example`,
  `docs/api.md`, `docs/auth-account-contract.md`,
  `docs/5b_h_d_production_security_implementation.md`, and
  `docs/5b_h_session_transport_hardening_plan.md`.
- Execution path: production requires RLS; RLS requires cookie transport;
  therefore `bearer_compat` is rejected before the legacy production rollback
  flag can make it usable. A test already proves rejection even with the flag.
- Impact: the documented incident rollback could not be executed on the
  current binary.
- Correction: documentation and environment guidance now state that
  `bearer_compat` is non-production/historical compatibility. Production
  rollback requires a coordinated application/database version rollback and
  forced reauthentication. RLS and cookie/CSRF requirements were not weakened.
- Regression: settings rejection remains covered; source/documentation scans
  find no remaining current claim that the flag alone enables production
  bearer transport.

### Medium — deferred

#### AUD-M-04 — RLS does not bind ad-hoc events to creator identity/storage family

- Classification: confirmed database authorization defect.
- Origin: H-E.
- Affected symbols:
  migration `20260726_000026` functions
  `mata_rls.can_select_teaching_event`,
  `mata_rls.can_submit_native_attendance`, and
  `mata_rls.can_submit_external_attendance`.
- Execution path: the ad-hoc visibility branches do not persist/check creator
  subject type/id. An otherwise eligible resident can select another
  resident's ad-hoc event and attach attendance through normal policy paths;
  the native and external helpers reuse that visibility without an exact
  storage-family owner binding.
- Impact: restricted SQL can create/read cross-resident ad-hoc associations,
  including native/external type confusion. FastAPI performs additional checks,
  so the defect is in database defense in depth rather than the normal router
  path.
- Evidence: PostgreSQL policy fixtures seed only `is_adhoc = false`. Current
  H-E documentation overstates owner/type isolation.
- Prior test gap: no own/cross-resident native/external ad-hoc matrix exists.
- Smallest safe correction: persist immutable creator subject type/id or add a
  dedicated atomic event-plus-attendance helper; reject ad-hoc rows through
  ordinary scheduled-attendance insert policies; require exact creator and
  native/external table family in visibility.
- Required regression: restricted-runtime own/cross-resident native/external
  ad-hoc SELECT/INSERT matrix plus normal FastAPI transaction tests.
- Deferral reason: this requires a new ownership model, migration, helper
  transaction shape, and populated downgrade/re-upgrade proof. It is not a
  low-risk bounded Medium patch.

#### AUD-M-05 — multipart upload limit is enforced after framework spooling

- Classification: confirmed resource-exhaustion defense gap.
- Origin: H-D upload hardening.
- Affected symbols: upload guard/multipart endpoints in the backend and the
  Nginx request-size/rate-limit configuration.
- Execution path: `Content-Length` is checked when present, but Starlette may
  parse/spool multipart bodies before the handler's 10 MiB reader. Chunked or
  missing-length requests and multipart part counts can consume disk/I/O before
  the inner size check.
- Impact: bounded but real local resource pressure. The 25 MiB proxy limit and
  10/hour rate limit reduce, but do not remove, the risk.
- Prior test gap: tests begin after framework multipart parsing and do not
  exercise aggregate streaming bytes/parts.
- Smallest safe correction: an outer streaming ASGI aggregate-byte/part guard
  that aborts before multipart spooling, reconciled with the proxy limit.
- Required regression: chunked/missing-length, many-part, exactly-at-limit,
  over-limit, disconnect, and normal upload cases.
- Deferral reason: middleware streaming semantics and deployment proxy
  compatibility require a separately verified design.

#### AUD-M-06 — failed server logout is silently presented as complete

- Classification: confirmed session-termination correctness/UX gap.
- Origin: H-D/lifecycle best-effort logout contract.
- Affected symbols:
  `frontend/src/context/AuthContext.tsx::logout` and
  `frontend/src/api/authCookie.ts::logoutAuthSession`.
- Execution path: local state clears immediately and the request error is
  swallowed. If the request never reaches the server, the cookie/session remain
  valid; later forced focus/visibility hydration can restore the session.
- Impact: a user can believe logout completed when server revocation did not.
  This is not a privilege escalation and the server still enforces expiry.
- Prior test gap: tests prove immediate local termination but intentionally do
  not define retry/tombstone/error UX.
- Smallest safe correction: an explicit termination-pending state with bounded
  retry and a product-approved failure screen/tombstone that prevents silent
  rehydration until the user chooses retry or full reload.
- Required regression: offline/network-failure, retry success, relogin, stale
  completion, cross-tab, and accessibility/UX cases.
- Deferral reason: changing the documented immediate/best-effort behavior needs
  product semantics and broader frontend verification.

### Low

- **AUD-L-01 — policy-attestation shape is permissive.** Startup requires a
  `mata_rls.` reference but does not hash/compare the exact policy predicate;
  an accidentally broader helper-backed predicate could pass. A future change
  should attest exact canonical expressions and add negative catalogue cases.
- **AUD-L-02 — future-function/default-ACL closure is incomplete.** Current
  grants are correct, but startup does not prove every future public function
  or alternate-owner default ACL remains closed. Add an owner matrix without
  weakening present grants.
- **AUD-L-03 — stub/demo auth helper can return `password_hash`.** The
  development-only staff helper returns a broader row than production needs.
  Narrow its projection after test/demo compatibility is inventoried.
- **AUD-L-04 — ad-hoc documentation/fixtures overstate coverage.** Correct the
  H-E claims together with AUD-M-04 and add real ad-hoc policy fixtures.
- **AUD-L-05 — local-host guard unit coverage is incomplete.** Runtime guards
  accept `localhost`, `127.0.0.1`, and `::1`, but the focused unit table does not
  positively cover all three. Add table-driven acceptance and remote-host
  rejection.
- **AUD-L-06 — backend cache invalidation is dead scaffolding.** Production
  calls invalidation hooks, but no production code reads/writes the backend
  cache. Decide later whether to implement distributed caching or remove the
  hooks and spy-only tests.
- **AUD-L-07 — downstream header identity compatibility is duplicated.**
  Middleware and isolated router dependencies reconstruct similar identity
  fields for different test/dev boundaries. Migrate harnesses to typed
  middleware identity before removing any fallback.
- **AUD-L-08 — frontend has several synchronized auth mirrors.** Module
  session/revision/epoch, React session, role, identity, cache scope, and upload
  state are coordinated. Consolidation could use one external-store snapshot,
  but revision, epoch, cache-generation, request, and page fences are distinct
  and must remain.
- **AUD-L-09 — lifecycle commit included broad `AGENTS.md` churn.** It replaced
  substantial domain guidance with generic contributor guidance and was not
  required for session expiry. Preserve/reconcile authoritative domain rules
  in a separately reviewed documentation change; do not rewrite the committed
  lifecycle history.

These Low items were not implemented under the overnight boundary.

### Informational

- The production frontend build retains the pre-existing warning that one
  minified JavaScript chunk exceeds 500 kB. It is not an authentication defect
  and no performance/code-splitting work was authorized.
- The retained non-production bearer implementation is technical debt, but
  Supabase JWT verification is still used for backend-mediated staff password
  authentication and is not wholly obsolete.

### Rejected theoretical concerns

- Expired, revoked, rotated, or generation-stale credentials cannot hydrate,
  refresh, touch, rotate, validate CSRF, or establish signed RLS context.
- Activity and repeated rotation cannot extend the immutable family absolute
  deadline; equality at idle or absolute expiry is rejected.
- Refresh racing valid logout does not leave an escaped child. The
  termination-only helper accepts tightly bound child-cookie/rotated-parent
  proof and family locking serializes the race.
- Rotation racing password reset, deactivation, role/scope changes, or subject
  invalidation does not preserve stale authority. Generation and advisory lock
  ordering fail closed.
- Transaction-local RLS identity does not survive commit, rollback, failed
  transaction, or pool reuse. Context is reinstalled from a currently valid
  backing session for every new root transaction.
- Runtime/auth roles cannot forge signed context, read full `app_sessions`, or
  use retired helpers. PUBLIC/browser/service roles retain no reviewed helper
  or table path.
- Server-side native/external login identity is type-bound. The confirmed
  exception is the direct-RLS ad-hoc association gap in AUD-M-04.
- Repeated expiry checks, RLS plus FastAPI authorization, session revalidation,
  lock-specific database dependencies, and frontend revision/epoch/cache/page
  fences are not redundant; they protect distinct transitions/trust boundaries.

## Combined edge-case matrix

| Interaction | Result |
|---|---|
| Stolen/replayed opaque credential | Usable only while server-valid; idle/absolute/generation/revocation checks apply. Theft itself is not prevented. |
| Expired credential with cookie present | Synchronously rejected; inert cookie may remain, but cannot establish identity or RLS context. |
| Expiry during protected unsafe request | Final touch/revalidation replaces the success with 401 and releases no protected success payload; it does not delete a possibly newer cookie. |
| Expiry during refresh | Rotation fails closed with a non-clearing conflict; no new absolute lifetime is created. |
| Older refresh versus newer login | Exclusive response lock orders the complete HTTP responses; the newer login remains last. |
| Refresh winner versus loser | Updated tabs cannot overlap lifecycle mutations; a conflict cannot delete the winning child. |
| Delayed generic 401/503 versus login | Generic failures emit no `Set-Cookie`; frontend revision fences protect memory. |
| Delayed logout versus login | Lifecycle responses are locked; proof-mismatched logout cannot clear the newer cookie. |
| Refresh versus logout | Fixed database lock order and mixed rotated proof revoke the family; no escaped child. |
| Rotation versus reset/deactivation | Subject generation/advisory locks prevent a usable stale child. |
| Authority change during request | Request-start authority cannot survive the next root transaction; self-change invalidation is the final protected statement. |
| Commit/rollback/failed transaction | Signed transaction-local context is cleared and freshly reinstalled/revalidated. |
| Pool reuse | Pool-size-one and backend-PID tests prove no previous identity survives. |
| Parallel tabs | Version gate plus Web Lock protects the shared cookie; BroadcastChannel remains a state-revalidation aid, not the cookie mutex. |
| Unauthenticated 401 during valid session | Request metadata prevents clearing/broadcasting loss of the current authenticated session. |
| Cleanup versus logout/hydration | Rotated proof is retained to the immutable absolute boundary; valid children are not cleanup-eligible. |
| Native versus Non-NHG scheduled flow | Typed subject/storage separation remains enforced. |
| Native versus Non-NHG ad-hoc direct RLS | Deferred defect AUD-M-04; normal FastAPI checks are stronger than the direct policy. |
| Master/PC/Secretary transitions | Database row/advisory locks preserve one Master and generation invalidation prevents stale scope/role use. |

## Redundancy and overengineering assessment

No code was simplified merely to reduce line count.

Intentionally retained defense in depth:

- FastAPI authorization and PostgreSQL RLS;
- middleware resolution and per-root-transaction PostgreSQL session reload;
- lifecycle checks in resolve, CSRF, touch, rotate, logout proof, signed
  context, and cleanup;
- shared/exclusive/auth-only database dependencies;
- current and historical migration helper separation required for downgrade
  evidence;
- frontend revision, epoch, cache generation, key generation, operation fence,
  and page request ID;
- source-contract tests plus real restricted-role PostgreSQL tests.

Deferred simplification opportunities are AUD-L-06 through AUD-L-09. Their
trust boundaries and regression dependencies must be removed before any
consolidation, not inferred from similar syntax.

## Fixes applied

- Added Supabase-cookie, secure-context Web Lock coordination:
  `frontend/src/api/authCookieCoordination.ts`.
- Wrapped login, refresh, and logout response lifetimes:
  `frontend/src/api/authCookie.ts`.
- Added the exact protocol header centrally and fail-closed local cleanup:
  `frontend/src/api/http.ts`.
- Added backend protocol constants/checks:
  `backend/app/services/session_transport.py`.
- Enforced the version gate before production login/protected hydration and
  removed generic cookie deletion:
  `backend/app/middleware/auth_stub.py`.
- Allowed the exact CORS header:
  `backend/app/middleware/security.py`.
- Made refresh conflict non-clearing and logout cookie deletion
  proof-conditional:
  `backend/app/routers/auth.py`.
- Aggregated staff/admin/secretary login identifiers:
  `backend/app/dependencies/persistent_rate_limit.py`.
- Added/updated deterministic frontend, middleware, router, RLS, PostgreSQL,
  rate-limit, and source-contract tests.
- Retargeted all restricted PostgreSQL guards to the one authorized audit
  database.
- Corrected bearer rollback and session-coordination documentation without
  enabling bearer transport or weakening RLS/CSRF.

## Verification evidence

### Session-lifecycle commit gate

Before commit, the lifecycle branch passed:

- focused backend: 54 passed, one known Starlette warning;
- six targeted PostgreSQL recovery/concurrency regressions: 6 passed;
- populated migration lifecycle: 1 passed, one known Alembic warning;
- complete restricted backend: 1,228 passed, 10 known warnings;
- focused frontend: 39 passed;
- complete frontend: 100 passed;
- lint, type-check, production build, security scans, secret scans, Alembic
  topology, catalogue checks, and `git diff --check`.

The branch was committed locally as
`ac6ed465e3d4fdbd9a7577b2d71a339caf4694f9` and verified clean. The complete
recovery evidence and its transient failed attempts are preserved in
`docs/5b_h_session_lifecycle_assurance.md`.

### Audit-fix gate

| Gate | Command | Result |
|---|---|---|
| New response-lock behavior | `node --experimental-strip-types --test src/api/authCookieCoordination.contract.test.ts` | 5 passed |
| Initial focused backend | `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_cookie_session_transport.py tests/test_persistent_rate_limits.py tests/test_auth_modes.py tests/test_rls_application_integration.py` | 65 passed; one known Starlette warning |
| Focused H-D/H-E/lifecycle backend | `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_session_lifecycle_migration_contract.py tests/test_cookie_session_transport.py tests/test_persistent_rate_limits.py tests/test_admin_staff_accounts.py tests/test_rls_application_integration.py tests/test_auth_modes.py` | 90 passed; one known Starlette warning |
| Focused frontend | `node --experimental-strip-types --test src/authSession.contract.test.ts src/api/httpTransport.contract.test.ts src/api/authCookieCoordination.contract.test.ts src/utils/memoryReadCache.contract.test.ts src/utils/storage.contract.test.ts` | 44 passed |
| Frontend type-check | `npm run typecheck` | passed |
| Frontend lint | `npm run lint` | passed |
| Focused restricted PostgreSQL | `python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests/test_security_postgres_integration.py tests/test_rls_foundation_postgres.py tests/test_rls_policy_postgres.py` | 76 passed; roles removed |
| Complete frontend | `npm test` | 106 passed |
| Production frontend build | `VITE_APP_ENV=production`, `VITE_AUTH_MODE=supabase`, `npm run build` | passed; existing >500 kB chunk warning only |
| Complete restricted backend | `python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests` | 1,230 passed; 10 known Starlette/Alembic warnings in 683.31 s; roles removed |
| Clean migration | `python -B -m alembic upgrade head` on the empty named audit database | passed from base through `20260727_000027` |
| Post-suite database/topology | `psql` catalogue assertions; `python -B -m alembic -c alembic.ini heads`; `current` | `20260727_000027 (head)`; 34/34 RLS tables; 84 policies; zero `mata_test_*` roles |

Final gates after including this report:

- `python -B .github/scripts/security_source_scan.py --frontend`: passed;
- `python -B .github/scripts/security_source_scan.py --worktree`: passed;
- `python -B .github/scripts/security_source_scan.py --diff-base main`:
  passed;
- added-line personal-data-shape review: one synthetic `example.com` address
  and one allowlisted test MCR shape, zero unexpected personal identifiers;
- `git diff --check`: passed;
- Alembic `heads`/`current`: one head and current at `20260727_000027`.

### Failed attempts and accepted reruns

- The first database host assertion expected `::1`; PostgreSQL returned the
  equally local canonical `::1/128`. It stopped before mutation. The exact
  assertion was corrected and passed.
- The first `createdb` invocation waited for an interactive password because
  it did not receive a credentialed URI. The exact `createdb.exe` process was
  stopped; no database was created by it. A guarded credentialed `psql CREATE
  DATABASE` rerun passed.
- The first fresh-database read expected zero `mata_%` cluster roles. The two
  intended cluster-wide capability roles already existed; the target database
  was still empty. The assertion was corrected to distinguish persistent
  capability roles from zero ephemeral `mata_test_*` roles.
- The first sandboxed Node test invocation failed with `spawn EPERM`; the
  approved worker-spawn rerun passed 5/5.
- One read-only `rg` command had a PowerShell quote terminator error; a simpler
  read-only search reran successfully.
- No failed or interrupted test run is counted as passing.

## Migration and database status

- Disposable database:
  `mata_phase5b_security_integration_audit`
- Host observed by PostgreSQL: local `::1/128`
- Current revision: `20260727_000027`
- Alembic topology: one head, `20260727_000027`
- Application tables: 34
- RLS-enabled application tables: 34
- Policies: 84
- Persistent capability roles:
  `mata_app_runtime`, `mata_auth_internal`
- Residual ephemeral `mata_test_*` roles: 0

The full suite's migration fixture received explicit approval to drop/recreate
only this named disposable database and restored it to head. The database was
not dropped after verification.

No local `mata_db`, remote database, live Supabase project, Vercel deployment,
or live user data was accessed.

## Production verification still required

Local evidence is not production verification.

An approved rollout must use a maintenance/drain window:

1. restrict interactive access;
2. let pre-cutover requests drain for at least the existing 60-second client
   request bound;
3. deploy the coordinated backend and frontend as one versioned protocol;
4. force old tabs to reload or reauthenticate; old clients receive a
   non-cookie-mutating 409;
5. exercise login, hydration, refresh, logout, concurrent tabs, role/scope
   changes, password reset, idle/absolute boundaries, and restricted RLS
   catalogue checks;
6. record cookie attributes, protocol header, response ordering, revision,
   grants, policies, and log redaction from the approved production system.

This document does not authorize that rollout.

## Continuation checkpoint

The next implementation should address one design-heavy Medium at a time,
starting with AUD-M-04. Do not combine the RLS ownership migration, streaming
upload middleware, and logout UX redesign in one change.

```text
Continue the MATA Phase 5B-H combined security audit from:

Repository:
C:\Users\limch\OneDrive\Desktop\Internship\github repos\MATA

Branch:
CL/5b-h-def-security-integration-audit

Committed HEAD/audit base:
ac6ed465e3d4fdbd9a7577b2d71a339caf4694f9

The worktree intentionally contains verified, uncommitted audit fixes. Read
docs/5b_h_def_security_integration_audit.md and AGENTS.md first. Do not reset,
clean, stash, overwrite, commit, push, merge, deploy, access live Supabase, or
run remote migrations unless separately authorized.

Primary scope: design and implement only AUD-M-04, the H-E ad-hoc RLS
creator/storage-family isolation defect.

Required preparation:
1. Reconcile docs/schema.md, docs/api.md, docs/business-logic.md, and the
   current 000026/000027 policy/helper contracts.
2. Preserve the existing verified Web-Lock/session-cookie audit fixes.
3. Use only the explicitly approved named local disposable database and assert
   database/host before mutation. Do not drop it without explicit approval.

Required design:
- choose and document immutable ad-hoc creator subject type/id or a dedicated
  atomic event-plus-attendance helper;
- ensure native and external creator/attendance storage families cannot cross;
- reject ad-hoc events through normal scheduled-attendance insert policies;
- retain normal FastAPI authorization and transaction atomicity;
- preserve RLS, least privilege, function ownership, fixed search_path,
  restricted EXECUTE grants, session expiry, and signed context.

Required regressions:
- own versus another resident's native ad-hoc visibility/attendance;
- own versus another resident's external ad-hoc visibility/attendance;
- native-to-external and external-to-native attachment rejection;
- scheduled events remain unaffected;
- FastAPI atomic create/attendance rollback;
- runtime/auth/PUBLIC/browser/service-role grant matrix;
- clean install, populated upgrade, downgrade, re-upgrade, one Alembic head,
  exact catalogue assertions, and complete restricted backend suite.

Stop for a user decision before implementing if creator persistence or helper
transaction shape has more than one materially different product outcome.
Record AUD-M-05 and AUD-M-06 but do not implement them in the same run.
Leave all new audit-branch work uncommitted unless explicitly authorized.
```

## Repository status

The active branch is `CL/5b-h-def-security-integration-audit` at committed
HEAD `ac6ed465e3d4fdbd9a7577b2d71a339caf4694f9`. Audit fixes and this report are
intentionally unstaged and uncommitted. The final audit delta has 32 paths:
29 modified tracked files and three untracked files, with 1,230 insertions and
93 deletions. No push, merge, deployment, live-system operation, or remote
migration occurred.
