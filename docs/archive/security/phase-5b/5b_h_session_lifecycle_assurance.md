# Phase 5B-H Session Lifecycle Assurance

> **Current contract:** `docs/security.md`. This file is retained as dated
> implementation evidence and does not override the current security contract.

Status: implemented and locally verified on
`CL/5b-h-session-lifecycle-assurance`; not deployed or verified against live
Vercel/Supabase.

This phase is a focused descendant of H-D session transport and H-E full RLS.
It keeps backend-owned opaque PostgreSQL sessions and does not introduce JWT
browser sessions, a new identity provider, or a parallel expiry model.

## Security outcome

Every authenticated session has two server-authoritative deadlines:

- `idle_expires_at` is a sliding inactivity deadline.
- `absolute_expires_at` is fixed at the most recent successful full login and
  applies to the complete rotation family.

The effective expiry is the earlier deadline. A session is invalid when
PostgreSQL or the non-RLS test fallback observes:

```text
current_time >= idle_expires_at
OR
current_time >= absolute_expires_at
```

Cleanup is not part of this decision. An expired row is rejected
synchronously even if it remains in `app_sessions`.

Normal refresh rotates the opaque credential and CSRF state but extends
neither the current idle deadline nor the original family absolute deadline.
Only qualifying activity can slide idle expiry, and only full authentication
creates a new family and new absolute deadline.

Absolute expiry limits the maximum lifetime of a stolen opaque session. It
does not prevent session theft; secure cookie handling, CSRF protection,
logout/revocation, generation fencing, and full reauthentication remain
necessary controls.

## Pre-change audit

The H-D/H-E baseline already provided the required session columns,
strict-before-deadline checks, database-clock issuance, subject-generation
validation, family locking, one-child rotation fencing, bounded cleanup,
opaque cookies, CSRF, and full RLS table denial for `app_sessions`.

Confirmed defects were:

- every unsafe request touched the row before CSRF or business validation;
- no configurable touch interval suppressed redundant writes;
- the shared resolver and issuance/rotation helpers returned full
  `app_sessions` rows to restricted backend capabilities;
- signed transaction context did not re-check its backing session after
  installation, so a later statement in the same transaction could retain
  context after expiry;
- a relative cookie lifetime calculated before commit/delivery could not be
  proven to end by the server absolute deadline;
- in-flight frontend reads could refill a cleared cache, and upload metadata
  persisted across authentication loss;
- an RDB programme change updated Resident authority without incrementing the
  Resident session generation;
- logout depended on an already-hydrated active session, so a refresh that
  committed first could invalidate the presented parent before logout reached
  family revocation;
- cleanup could remove a rotated parent using its old revocation timestamp
  before that row's still-valid token/CSRF pair had finished serving as
  termination proof for a raced logout;
- a self authorization change could invalidate its own signed database
  context before the audit append, rolling back both the change and audit;
- documentation did not state the complete five-role timeout mapping or the
  pending production-duration decision.

No duplicate expiry column, new session table, or broad RLS policy was needed.

The recovery audit also confirmed and corrected narrowly scoped defects:

- cookie-mode logout still passed through normal active-session hydration and
  middleware CSRF validation before reaching the termination-only route, so a
  rotated or raced proof could be rejected too early;
- a stale tab could hold the current child cookie after another tab refreshed
  while retaining the rotated parent's CSRF value; the termination helper did
  not yet accept that same-family mixed proof;
- concurrent staff PATCH transactions could independently remove the final two
  active Master Admins, and a display-only PATCH could restore authorization
  fields read before a concurrent authorization change;
- startup attestation checked helper names and grants but did not prove every
  executable RLS helper was `SECURITY DEFINER`, had the exact fixed
  `search_path`, was owned by its schema owner, or that the exact named policy
  catalogue and helper-backed predicate shape remained intact;
- hydration failure could emit a second local auth-store change after the HTTP
  401 interceptor had already terminated the current session;
- rotation was not announced to other tabs, and focus/visibility fallback did
  not hydrate a tab whose local memory was empty;
- several protected page completions and cache rejection paths could still
  publish state after an authentication, authority, scope, or request change;
- predicate-based cache invalidation initially cancelled unrelated in-flight
  resources; the final implementation fences only matching keys while a full
  authentication clear remains global.

Test-only recovery fixes aligned all local PostgreSQL guards with the approved
IPv4, hostname, and IPv6-loopback endpoints and corrected one source-contract
slice that searched before the handler under test.

## Timeout configuration

The following backend-only settings are explicit and validated:

| Setting | Local/test example |
|---|---:|
| `MATA_STAFF_IDLE_TIMEOUT_SECONDS` | `1800` |
| `MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS` | `28800` |
| `MATA_RESIDENT_IDLE_TIMEOUT_SECONDS` | `3600` |
| `MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS` | `43200` |
| `MATA_SESSION_ROTATION_SECONDS` | `900` |
| `MATA_SESSION_TOUCH_INTERVAL_SECONDS` | `60` |
| `MATA_SESSION_CLEANUP_RETENTION_SECONDS` | `604800` |
| `MATA_SESSION_CLEANUP_BATCH_SIZE` | `500` |

These are examples and application defaults, not approved production policy.
The organisation and operations owner must approve the final production
durations and deploy them explicitly.

Validation requires:

- every duration and batch size to be positive;
- each idle timeout to be no greater than its absolute timeout;
- the touch interval to be shorter than both idle timeouts;
- the rotation threshold to be shorter than both absolute timeouts;
- idle timeouts to be at most 86,400 seconds;
- absolute timeouts to be at most 604,800 seconds;
- cleanup retention to be at most 31,536,000 seconds;
- cleanup batches to be at most 1,000 rows.

These upper bounds match the reviewed PostgreSQL helpers, so a value accepted
at startup is not later rejected at login or cleanup.

No frontend expiry-warning interval exists. No countdown was added; the
frontend is not an expiry authority.

## Role mapping

Timeout selection uses the trusted database subject type, never a request role
or browser-controlled value.

| System role | Trusted subject | Timeout class |
|---|---|---|
| Master Admin | `staff` | staff |
| Programme Coordinator | `staff` | staff |
| Department Secretary | `staff` | staff |
| NHG Resident | `resident` | Resident |
| Registered Non-NHG Resident | `external_resident` | Resident |

## Login and cookie issuance

A successful full login:

1. validates the current subject and session generation;
2. captures one PostgreSQL `clock_timestamp()` on the restricted-helper path;
3. creates a new root where `session_family_id = id`;
4. sets `absolute_expires_at = authentication_time + absolute_timeout`;
5. sets `idle_expires_at` to the lesser of the idle and absolute deadlines;
6. stores only keyed session and CSRF digests;
7. returns the opaque credential and memory-only CSRF value through the
   existing application contract.

Restricted issuance/rotation helpers do not return token digests, CSRF
digests, stored expiry fields, or a derived client lifetime. A relative
`Max-Age` calculated before cleanup, transaction commit, response
construction, and delivery cannot be proven to end by the PostgreSQL absolute
deadline. MATA therefore intentionally issues a non-persistent browser-session
cookie with neither `Max-Age` nor `Expires`. Synchronous server-side idle and
absolute checks remain the sole expiry authority.

Production retains:

- `__Host-mata_session`;
- `Secure`;
- `HttpOnly`;
- `SameSite=Strict`;
- `Path=/`;
- no `Domain`;
- no persistent `Max-Age` or `Expires`.

The cookie contains no role, subject ID, MCR, scope, posting, expiry, CSRF, or
personal data. Browser-session restoration behavior is not an authorization
boundary: server-side rejection remains authoritative even if a user agent
retains or restores a stale cookie.

## Hydration, CSRF, activity, and RLS

Protected requests first resolve the credential without touching the row.
Hydration validates digest binding, revocation, both deadlines, subject
activation, subject generation, family binding, and current role/scope.

Unsafe requests then validate CSRF through a helper that returns only:

- `true` for a valid active session and matching CSRF digest;
- `false` for an active session with a mismatch;
- `NULL` when the session itself is no longer valid.

No digest is returned.

Qualifying activity is deliberately narrow: a protected unsafe request that
passes session and CSRF validation and completes with a 2xx response.
Health checks, static/open routes, safe reads, failed CSRF, 401, 403, 409, 422,
automatic polling, refresh, and logout do not perform the post-response touch.
Refresh creates the replacement row itself while preserving or tightening the
parent idle deadline and carrying forward the last qualifying-activity
timestamp; logout revokes the family. If the final post-response touch reports
that the session expired, was revoked, or became stale—or if the lifecycle
store fails—the middleware replaces the pending protected 2xx payload with a
controlled `401` that leaves the shared session cookie unchanged. Generic or
stale failure paths must not delete a newer valid cookie; cookie deletion
remains limited to reviewed proof-positive logout.

The touch helper:

- uses PostgreSQL time;
- follows the reviewed subject → shared family → session-row lock order;
- re-checks revocation and both deadlines after blocking locks;
- writes only when `last_seen_at + touch_interval <= current_time`;
- sets idle expiry to
  `min(current_time + class_idle_timeout, absolute_expires_at)`;
- returns false rather than reviving an expired or stale session.

The restricted resolver returns only the session/subject binding, current
identity context, authorization fingerprint, and a boolean refresh hint. The
old full-row resolver and old full-row issuance/rotation entry points remain
owner-internal for migration compatibility but lose execution grants from
both restricted application capabilities.

`app_sessions` remains helper-only: it has no direct runtime table grant or
permissive table policy. Every callable lifecycle helper is
`SECURITY DEFINER`, owned outside application/browser capabilities, has fixed
`search_path = pg_catalog, pg_temp`, and denies `PUBLIC`, `anon`,
`authenticated`, and `service_role`.

`install_request_context` still hydrates before setting any transaction-local
identity. In addition, the signed-context function now verifies that the
backing session row is unrevoked and strictly before both deadlines. Therefore
an expired session cannot install context, and later protected statements in
an already-open transaction cannot satisfy RLS through stale signed context.
Transaction-local GUCs remain bound to transaction ID, backend PID, database,
session user, session ID, and authorization fingerprint; commit/rollback and
pool reuse do not carry identity forward.

## Rotation and reauthentication

Rotation retains the H-D/H-E lock order and unique
`rotated_from_session_id` constraint:

- the parent must still be active after locks;
- at most one concurrent caller creates a child;
- the winner revokes the parent;
- the child keeps the parent family and exact absolute deadline;
- child idle expiry is no later than the parent's idle deadline, its configured
  class timeout, or the family absolute deadline;
- the child carries forward the parent's `last_seen_at`, so refresh neither
  impersonates activity nor delays eligibility for the next real touch;
- the old credential and old CSRF state fail for authentication, hydration,
  refresh, rotation, and authorization;
- the new pair works only while the preserved deadlines remain valid.

Repeated rotation cannot extend either deadline. An expired, revoked,
stale-generation, or invalid-family parent cannot refresh or rotate. Full
login is required after absolute expiry.

## Revocation and authority changes

The existing controls remain:

- logout revokes the current device/session family;
- logout uses the narrow auth database boundary and an exact keyed
  token-digest plus CSRF-digest proof derived from the presented opaque cookie
  and CSRF header. Normally both digests identify the same active row, or the
  same row revoked only as `rotated`. A stale tab may instead present the
  current active child token with a rotated ancestor's CSRF value; that mixed
  proof is accepted only when both rows have the same immutable subject,
  subject generation, family, and authentication source, the child remains
  before both deadlines, and the rotated proof remains before the family
  absolute deadline. The auth-only termination helper derives the subject and
  family server-side. A row revoked specifically as `rotated` remains
  termination-only proof until the immutable family absolute deadline even
  when its superseded idle deadline has passed. The helper cannot consume
  another revoked state,
  returns only the affected-row count, grants no
  hydration, signed-context, touch, rotation, or refresh authority, and is not
  executable by the runtime capability. This closes the refresh-first race:
  the original pair, or the tightly bound active-child/rotated-ancestor pair,
  remains bounded termination proof for its family after a committed refresh;
- after production origin and raw-authorization guards, the exact cookie-mode
  logout route bypasses normal middleware hydration and active-session CSRF
  handling so only the termination helper evaluates the bounded proof;
- malformed, missing, or mismatched logout proof revokes nothing. The
  server-side revocation effect remains idempotent and leaves the shared browser
  cookie unchanged; the cookie is cleared only after the reviewed proof revokes
  its presented family;
- the HTTP response remains successful and includes only the non-sensitive
  outcome `server_logout_confirmed`: it is `true` only on that same
  proof-positive revocation and cookie-clear branch, and `false` for every
  zero-result case. A false value is not an assertion that a server session
  exists, and the response exposes no count, reason, session/family identifier,
  or identity;
- password reset and observable upstream credential reset fence applicable
  staff sessions;
- account deactivation, role, admin-level, programme-scope, and posting-scope
  changes increment generation and revoke/fence stale staff authority;
- staff PATCH operations take one transaction-scoped invariant lock before
  re-reading the target row `FOR UPDATE`, so final-Master checks and
  display-only updates serialize against concurrent authorization changes;
- when the target is the acting staff account, the service appends an audit of
  the planned final state while the request-start actor is still valid, applies
  the account mutation, and makes subject-wide invalidation the final protected
  database statement before commit. All three effects are atomic. Because no
  protected count read can safely follow self-invalidation, the audit records
  `revoked_session_count = null`,
  `revoked_session_count_is_exact = false`, the all-subject-session scope, and
  final-statement timing. Non-self changes retain the exact integer count;
- Resident and Non-NHG Resident invalidation use their subject generation;
- RDB updates increment a native Resident generation when `programme_code`
  changes, forcing reauthentication before the new scope can be used;
- administrative subject revocation and family compromise use the existing
  subject/family primitives.

MATA has no public logout-all, staff-delete, or generic compromise endpoint.
This phase does not invent endpoints for unsupported product behavior.

## Frontend termination behavior

The opaque credential remains inaccessible to JavaScript. A current-session
401 clears in-memory identity, CSRF, and protected read caches, emits one
authentication-state change, and lets route guards redirect to login. There is
no automatic refresh retry loop. A 401 from a request that began without an
authenticated memory session cannot clear state or broadcast authentication
loss, and a stale authenticated request cannot terminate a newer session.

Cache generation fencing prevents an in-flight protected read from repopulating
memory after a session clear. A full authentication clear globally invalidates
in-flight reads; a predicate-based resource clear invalidates only matching
cached or in-flight keys. Upload metadata is memory-only, legacy `localStorage`
residue is removed, and authentication loss or an identity/scope switch clears
it. Protected list, detail, history, mutation, error, and loading completions
are fenced by session revision/epoch, normalized authority scope, and the
latest page request.

AUD-M-06 supersedes the earlier best-effort logout-completion behavior.
Logout captures the current CSRF/revision/session-epoch proof only in memory,
records a non-sensitive durable pending marker, and clears local identity,
CSRF, protected caches, upload state, and authenticated UI immediately. Mount,
focus/visibility hydration, and protected requests remain blocked while that
state is pending or unconfirmed. Only
`server_logout_confirmed = true` establishes server revocation; an ordinary
successful response, false confirmation, ambiguous transport outcome, or
proofless reload does not.

Automatic retry uses nominal offsets of 0, 1, 3, and 7 seconds and never
exceeds four attempts while the original proof remains in memory. An explicit
retry or `online` event may advance one eligible attempt, but concurrent
triggers coalesce and cannot raise that bound. A successful replacement login
may release the matching pending lifecycle only after the new session commits
inside the same origin-scoped Web Lock; a failed login retains it.

`BroadcastChannel` synchronizes the typed pending and resolution lifecycle,
unauthorized loss, and new-session epochs across tabs where available.
Non-sensitive durable ordering state prevents stale fallback replicas or
responses from resurrecting an older logout or affecting a newer login.
Rotation emits a same-epoch message so peer tabs immediately discard stale
memory and rehydrate without creating a new login epoch. Focus/visibility
forces server hydration only when the logout fence is clear, including when
local auth memory is empty, as the fallback when channel delivery is
unavailable. The backend remains authoritative. An equivalent hydration
preserves the current revision and in-flight fences; CSRF rotation or an
identity/authority change advances them. An authenticated hydration 401
terminates the store exactly once even though both the HTTP layer and context
observe the failure.

Supabase-cookie frontends additionally use a versioned browser coordination
protocol. Every frontend request carries
`X-MATA-Session-Coordination: web-locks-v1`; in production the backend rejects
a missing/wrong protocol before protected hydration and emits no cookie
mutation.
Login, refresh, and logout acquire one same-origin exclusive Web Lock and hold
it until the HTTP response completes, after the browser has applied any
`Set-Cookie`. This orders fixed-name cookie responses across tabs. There is no
`BroadcastChannel` or `localStorage` mutex fallback: an insecure context or
missing Web Locks support fails before dispatch and clears local protected
state. Generic 401/503/final-touch failures leave an inert or current shared
cookie untouched. Refresh conflicts return a non-clearing 409. Logout clears
only after the exact presented proof revokes its family, so an older logout
cannot delete a newer login cookie.

## Cleanup

Cleanup remains bounded, deterministic, retention-based, and independent of
authentication:

- a batch contains at most the configured limit;
- only revoked or effectively expired rows at or before the retention cutoff
  are eligible;
- a row revoked specifically as `rotated` is retained as logout termination
  proof until its immutable family `absolute_expires_at`, even when its
  superseded idle deadline has passed or configured retention is shorter or
  zero. At the absolute boundary it may follow the normal bounded retention
  selection;
- selection is deterministic and uses `FOR UPDATE SKIP LOCKED`;
- an unrevoked child whose idle and absolute deadlines are still valid is
  ineligible, so preserving the rotated proof parent never deletes or
  invalidates the usable child;
- concurrent family operations retain the existing locking protections;
- cleanup returns a count and logs no credential, digest, CSRF, MCR, or
  personal row data.

## Migration

Revision `20260727_000027` is narrowly scoped to functions and grants. It adds
no table, column, index, or permissive RLS policy. Upgrade:

- installs the minimal lifecycle helper surface;
- revokes restricted execution of superseded full-row helpers;
- adds atomic interval-gated touch and digest-internal CSRF validation;
- installs exactly eight revision-owned minimal lifecycle helpers: three
  auth-only issuance wrappers, one shared resolver, one shared touch helper,
  one shared CSRF validator, one runtime-only rotation helper, and one
  auth-only termination helper;
- grants `revoke_app_session_family_for_logout(bytea,bytea,text)` only to
  `mata_auth_internal`, for deterministic refresh/logout ordering without a
  caller-supplied subject, session, or family identifier;
- makes signed RLS context lifecycle-aware;
- asserts safe ownership, `search_path`, and browser/PUBLIC denial.

Startup attestation additionally proves the exact named 34-table/84-policy
catalogue, command-appropriate helper-backed policy predicates, and that every
executable `mata_rls` helper is `SECURITY DEFINER`, owned by its reviewed
owner, and configured with exactly `search_path=pg_catalog, pg_temp`. The
ad-hoc atomic helper is the narrow exception to schema-owner ownership: it is
owned by the dedicated, non-login `mata_adhoc_attendance_definer` role whose
attributes, zero-membership posture, and exact privileges are attested.

Downgrade drops the new wrappers, restores the earlier helper grants and
context-signature behavior, and leaves session evidence untouched. Clean
installation, populated downgrade, and re-upgrade must be tested only in the
named disposable verification database.

## Local verification target

Historical lifecycle-commit PostgreSQL evidence used exactly:

```text
mata_phase5b_session_lifecycle_verify
```

The descendant combined integration audit uses only
`mata_phase5b_security_integration_audit`; see
`docs/archive/security/phase-5b/5b_h_def_security_integration_audit.md`.

Use fresh child processes, three distinct local credentials, and verify
`current_database()` before every migration or destructive command. Never use
`mata_db`, a remote URL, or live Supabase.

The restricted suite must cover expiry versus hydration/touch/rotation/logout,
refresh/logout, one-winner rotation, generation/family invalidation, expired
RLS context, commit/rollback and pool-size-one reuse, and cleanup concurrency.

## Local verification evidence

All PostgreSQL commands used a fresh process and the exact local disposable
database above. Connection credentials are intentionally omitted.

| Gate | Exact command | Result |
|---|---|---|
| Accepted pre-recovery focused baseline | `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_app_sessions.py tests/test_session_lifecycle_assurance.py tests/test_cookie_session_transport.py tests/test_rls_application_integration.py tests/test_rdb_parser_integration.py tests/test_session_lifecycle_migration_contract.py tests/test_admin_staff_accounts.py` | 136 passed; one known Starlette deprecation warning; reconciled rather than rerun unchanged |
| Recovery affected backend | `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_session_lifecycle_migration_contract.py tests/test_cookie_session_transport.py tests/test_admin_staff_accounts.py` | 54 passed; one known Starlette deprecation warning |
| Accepted pre-recovery PostgreSQL baseline | `python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests/test_security_postgres_integration.py tests/test_rls_foundation_postgres.py` | 58 passed; reconciled, with new recovery cases separately rerun and included below |
| Recovery PostgreSQL regressions | `python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests/test_security_postgres_integration.py::test_refresh_first_logout_without_hydrated_parent_revokes_late_child tests/test_security_postgres_integration.py::test_local_cleanup_retains_rotated_proof_for_delayed_family_logout tests/test_security_postgres_integration.py::test_local_rotated_logout_proof_expires_at_absolute_boundary tests/test_security_postgres_integration.py::test_child_cookie_with_rotated_parent_csrf_revokes_only_its_family tests/test_security_postgres_integration.py::test_concurrent_distinct_master_deactivations_preserve_one_active_master tests/test_security_postgres_integration.py::test_display_only_staff_patch_cannot_restore_stale_authorization` | 6 passed |
| Complete restricted backend | `python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests` | 1,228 passed; ten known Starlette/Alembic deprecation warnings |
| Populated migration lifecycle | `python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests/test_external_registration_migrations_postgres.py::test_full_rls_cutover_clean_populated_downgrade_and_reupgrade_lifecycle` | 1 passed; one known Alembic warning; clean install, populated downgrade, and re-upgrade ended at `20260727_000027` |
| Focused frontend lifecycle | `node --experimental-strip-types --test src/authSession.contract.test.ts src/api/httpTransport.contract.test.ts src/utils/memoryReadCache.contract.test.ts src/utils/storage.contract.test.ts` | 39 passed |
| Complete frontend | `npm test` | 100 passed |
| Frontend static/build | `npm run lint`; `npm run typecheck`; production `npm run build` with `VITE_APP_ENV=production` and `VITE_AUTH_MODE=supabase` | Passed; the pre-existing chunk-size warning remains non-blocking |
| Source and likely-secret scans | `python -B .github/scripts/security_source_scan.py --frontend`; `python -B .github/scripts/security_source_scan.py --worktree` | Both passed |
| Alembic topology | `python -B -m alembic -c alembic.ini heads`; `python -B -m alembic -c alembic.ini current` | One head; database current at `20260727_000027` |
| Whitespace/scope | `git diff --check` | Passed |

Final read-only catalogue checks reported revision `20260727_000027`, zero
ephemeral `mata_test_*` roles, 34/34 application tables with RLS, zero forced
RLS tables, 84 policies, no direct `SELECT` on `app_sessions` for either
restricted capability, eight minimal lifecycle helpers with `SECURITY
DEFINER`, fixed `search_path`, and schema-owner ownership, and five retired
full-row helpers with zero restricted-role execute paths. The complete
restricted suite proves the exact owner/capability ACL split.

The first isolated invocation of the populated lifecycle command encountered a
PostgreSQL deadlock while revision `000026` was disabling a legacy table's RLS.
The fixture restored the disposable database to head with no residual session;
an immediate clean rerun passed, and the same lifecycle test passed again
inside the uninterrupted pre-recovery 1,219-test restricted suite. The recovery
rerun also passed independently and inside the final uninterrupted 1,228-test
restricted suite.

## Deployment smoke checks

Before an approved production release, an operator must record:

1. deployed Alembic revision `20260727_000027`;
2. explicit approved values for all lifecycle settings above;
3. distinct migration, runtime, and auth-helper credentials targeting the same
   database;
4. lifecycle helper ownership, ACL, `search_path`, minimal result columns, and
   old-helper denial;
5. no direct/browser access to `app_sessions`;
6. exact-boundary idle and absolute rejection for staff, NHG Resident, and
   registered Non-NHG Resident;
7. rotation preserving the family deadline and replacing CSRF;
8. expired context denial and pool reuse without residual identity;
9. current-session 401 local-state clearing/redirect behavior in the production
   frontend without server-side cookie deletion;
10. exact cookie flags, no persistent lifetime directive, and controlled
    proof-conditional cookie clearing on logout.

Local evidence is not deployed evidence.

## Separate blocker

`PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED`

Resident second factor remains out of scope and unresolved.
