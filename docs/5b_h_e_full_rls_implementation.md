# 5B-H-E Full PostgreSQL RLS Implementation

Status: locally implemented and verified against disposable PostgreSQL on 2026-07-27. This is not a deployment record.

**PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED**

## Later session-lifecycle addendum

This document preserves the H-E point-in-time evidence at revision
`20260726_000026` and database `mata_phase5b_verify_5bhe`. The focused
descendant in `docs/5b_h_session_lifecycle_assurance.md` adds revision
`20260727_000027` on a new disposable database. It preserves the 34-table,
84-policy, non-owner/NOBYPASSRLS posture while:

- replacing restricted full-row session helper grants with minimal lifecycle
  wrappers;
- adding atomic interval-gated touch;
- keeping stored token/CSRF digests and expiry fields private;
- denying signed RLS context after the backing session expires or is revoked.

Do not rewrite the H-E revision, counts, commands, incident record, or evidence
below as session-lifecycle evidence.

## Later AUD-M-04 addendum

Revision `20260728_000028` closes the ad-hoc owner/storage-family gap identified
after the H-E point-in-time audit. It adds two typed creator foreign keys to
`teaching_events`, strict and immutable native/external family constraints, and
a narrow runtime-only `mata_rls.create_adhoc_attendance(...)` boundary that
derives the verified subject and creates the event/attendance pair in the
caller's transaction. Ordinary table policies reject Resident ad-hoc event and
attendance insertion; exact-owner update policies preserve the reviewed
removal path. Another Resident and the opposite storage family cannot select
or reuse the ad-hoc association.

The populated upgrade refuses ambiguous ownership instead of inventing it.
Scheduled event behavior and the existing 34-table runtime-action boundary
remain unchanged. See `docs/5b_h_aud_m04_atomic_attendance.md` for the
transaction matrix, migration rule, and descendant verification evidence. Do
not rewrite the original `20260726_000026` counts or commands below as
AUD-M-04 evidence.

This report records the bounded Phase 5B-H-E implementation on
`CL/5b-h-e-full-rls`. All accepted H-E database evidence used only the named
local disposable database `mata_phase5b_verify_5bhe`. No live Supabase or
Vercel resource was read or changed, and no migration was applied to a live
database. A separate local-target incident is recorded transparently below and
is not counted as H-E verification evidence.

The implementation adds database-enforced row isolation beneath the existing
FastAPI authorization layer. It does not replace or weaken endpoint
authorization, make browser roles trusted, merge native and Non-NHG Resident
identity domains, or claim that locally verified controls are active in
production.

## Implemented boundary

Normal application traffic is split across three PostgreSQL credentials:

```text
protected FastAPI request
  -> restricted runtime LOGIN
  -> mata_app_runtime capability group
  -> signed transaction-local identity context
  -> direct table grants filtered by RLS
     plus reviewed runtime helpers

unauthenticated login, registration, session and rate-limit work
  -> distinct restricted auth LOGIN
  -> mata_auth_internal capability group
  -> reviewed SECURITY DEFINER helpers only
  -> no direct application-table privileges

Alembic and controlled database administration
  -> separate migration/ownership credential
  -> owns schemas, tables, policies and helper functions
  -> never used for normal FastAPI traffic
```

Migration `20260726_000025` creates the stable capability groups
`mata_app_runtime` and `mata_auth_internal`. Both are `NOLOGIN`, `NOINHERIT`,
`NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE` and
`NOREPLICATION`. A deployment supplies two distinct credentialed LOGIN roles,
each inheriting exactly one capability group. Neither capability group may own
an application relation, inherit another privilege-bearing role, grant its
membership with `ADMIN OPTION`, or be reachable through a browser role.

Migration `20260726_000026` performs the policy and grant cutover. The local
catalogue owner is `postgres`; neither restricted capability group owns any
application object. A production migration owner may have a different name,
but it must remain separate from both application credentials.

RLS is enabled without `FORCE ROW LEVEL SECURITY`. This is deliberate: the
migration owner retains controlled owner access for migrations and recovery,
while application traffic is constrained by non-owner, `NOBYPASSRLS`
credentials. Consequently, using the owner or migration credential for normal
application traffic is forbidden.

## Trusted transaction-local identity

The browser does not supply PostgreSQL authorization context. Raw
`X-User-*` headers, request JSON, frontend state, Supabase `user_metadata` and
unverified token claims are not accepted as RLS inputs.

For a protected request, middleware first resolves a backend-owned
`app_sessions` row and reloads the trusted subject. Before the runtime session
starts its first root transaction, FastAPI seeds only expected server-side
bindings:

- keyed session-token digest;
- expected subject type and subject UUID;
- expected application-session UUID;
- expected authorization fingerprint;
- shared or exclusive session-family lock mode.

`mata_rls.install_request_context(...)` then hydrates the authoritative
database session and subject state. It validates activity, revocation, idle and
absolute expiry, subject generation, issuance blocking, identity type,
application role and current authorization fingerprint. It derives:

- `subject_type`;
- `subject_id`;
- `app_role`;
- `admin_level`;
- normalized `programme_scope`;
- `posting_code`;
- `app_session_id`;
- authorization fingerprint.

The installer writes these values with transaction-local `set_config(...,
true)`. A private HMAC signature binds the context to the current transaction
ID, backend PID, database OID and `SESSION_USER`, using a random signing key in
`mata_private.context_signing_key`. The key and all `mata_private` functions
are inaccessible to runtime, auth, PUBLIC and browser roles. Forged GUCs,
copied signatures, cross-transaction replay, database/connection replay and
binding mismatches therefore fail closed.

FastAPI compares the installed database context back to the already verified
middleware identity. Subject, role, admin level, normalized programme scope,
posting, application-session ID and authorization fingerprint must all match.
RLS is an additional enforcement layer; this comparison does not remove any
router or service authorization check.

### Commit, rollback, identity-map and pool safety

SQLAlchemy installs the trusted context in the `after_begin` hook for every
new root transaction. The request seed remains available for the duration of
the request, so a service that commits or rolls back mid-request must begin a
new transaction and rehydrate the context from PostgreSQL before another
protected query.

At the end of every root transaction, the hook:

- removes the installed context from `Session.info`;
- calls `expire_all()` so authority-sensitive ORM objects cannot survive in
  the identity map;
- relies on PostgreSQL transaction-local GUC cleanup before the connection is
  returned to the pool.

Tests cover commit, rollback, a failed transaction, reuse of the same backend
PID from the connection pool, authorization changes between transactions and
fresh reinstallation after each new root transaction. A stale SQLAlchemy
object or pooled connection cannot preserve a prior request's authority.

Normal protected reads take the reviewed shared session-family advisory lock.
Refresh uses an exclusive protected-session dependency and follows the
subject -> family -> row lock order. Revision `20260727_000027` moves logout
to an auth-only, token/CSRF-digest termination helper instead of hydration or
signed-context installation. That helper derives the family server-side. An
active proof must be before both deadlines; a parent revoked specifically as
`rotated` remains termination-only proof until the immutable family absolute
deadline even if its superseded idle deadline has passed. The helper takes the
same lock order, so a refresh that commits first cannot escape a logout already
holding the original proof.

## Reviewed helper boundary

Revision `20260726_000025` installs narrowly scoped `SECURITY DEFINER`
functions with fixed `search_path=pg_catalog, pg_temp` and fully qualified
object references. Revision `20260726_000026` adds the relationship predicates
used by RLS policies. The helper surface covers only demonstrated application
requirements:

- application-session issue, resolve, rotate, revoke, family revoke,
  subject-wide invalidation and bounded cleanup;
- staff, native Resident and Non-NHG Resident login;
- public external-registration options and atomic external registration;
- external schedule replacement/current-posting compatibility;
- persistent PostgreSQL rate limiting;
- TTF posting and session-type operations;
- append-only audit work, reporting-period dependency counts and surplus
  hibernation;
- global MCR uniqueness across native and external identity tables;
- policy predicates for programme, posting, native owner, external owner,
  event, catalogue and attendance relationships.

`app_sessions` and `rate_limit_buckets` have no direct runtime or auth table
privilege. Their reviewed helpers serialize and validate the relevant
operation. The auth capability group similarly receives no direct table
access for login, registration or session issuance.

Six application tables are helper-only and have no direct runtime policy or
table grant:

- `app_sessions`;
- `clawback_records`;
- `period_snapshots`;
- `programme_institution_posting_map`;
- `rate_limit_buckets`;
- `surplus_ledger`.

No speculative helper was added for a hypothetical future workflow. A future
operation must first demonstrate a concrete policy or workflow requirement,
then receive a separately reviewed helper or policy change.

### Revision `20260727_000027` lifecycle ACL delta

The current lifecycle revision owns exactly eight minimal helpers: three
auth-only issuance wrappers, three shared resolve/touch/CSRF helpers, one
runtime-only rotation helper, and the auth-only
`revoke_app_session_family_for_logout(bytea,bytea,text)` helper. The runtime
capability has no execute grant on the logout helper, which returns only an
affected-row count and grants no hydration, context, touch, rotation, or
refresh authority. Cleanup also preserves a `rotated` parent as termination
proof until the immutable family absolute deadline without deleting a valid
child.

The exact catalogue table below is retained as historical
post-`20260726_000026` evidence. Its total function/executable counts are not a
claim about the later `20260727_000027` catalogue; the lifecycle delta above
and the dedicated lifecycle assurance evidence supersede only the session
helper subset.

## Exact local role, RLS and grant catalogue

The post-`20260726_000026` catalogue was queried directly after migration
replay and lifecycle restoration:

| Catalogue property | Verified local result |
|---|---|
| Alembic revision | `20260726_000026` |
| Stable capability roles | 2; both NOLOGIN, NOINHERIT, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, NOREPLICATION |
| Application relations | 34 |
| Relations with RLS enabled | 34 |
| Relations with FORCE RLS | 0 |
| Application relation owner | `postgres` for all 34 |
| Restricted-role-owned application objects | 0 |
| Policies | 84, all assigned only to `mata_app_runtime` |
| Unexpected/unsafe policies | 0 |
| Runtime direct table action grants | 83 |
| Auth direct application-table action grants | 0 |
| Runtime-readable `users` columns | 16; `password_hash` is excluded |
| Public sequence privileges for runtime/auth | 0 |
| `mata_rls` functions | 52 |
| `mata_private` functions | 10 |
| Runtime executable `mata_rls` functions | 43 |
| Auth executable `mata_rls` functions | 13 |
| Runtime/auth executable `mata_private` functions | 0 |
| PUBLIC application-relation ACLs | 0 |
| PUBLIC H-E helper EXECUTE ACLs | 0 |
| PUBLIC CREATE on schema `public` | denied |
| Restricted/default ACL grants | 0 |
| Capability membership `ADMIN OPTION` | 0 |

The 43-function runtime surface is 28 runtime-only foundation helpers, 11
policy helpers and 4 shared service helpers. The 13-function auth surface is 9
auth-only helpers and the same 4 shared service helpers. The only separately
reviewed public-schema function granted to runtime is
`public.gen_random_uuid()`; the auth capability does not receive it.

All 34 application tables have RLS enabled:

```text
academic_month_boundaries  app_sessions
attendance_records         audit_logs
clawback_records           event_series
external_attendance_records
external_resident_postings external_residents
form_f1_records            global_session_types
loa_types                  multi_posting_rules
period_snapshots           posting_codes
posting_groups             programme_institution_posting_map
programmes                 public_holidays
rate_limit_buckets         reporting_periods
resident_postings          residents
secretary_programme_pools  session_types
surplus_ledger             teaching_events
teaching_name_catalogue    teaching_targets
upload_logs                upload_warnings
users                      warning_issues
weekend_exceptions
```

The remaining 28 tables have an exact direct-grant and RLS-policy
combination. Absence of a policy or privilege is intentional. New tables do
not inherit broad access: owner default ACLs grant nothing to PUBLIC,
runtime, auth or browser roles. A future compliance table therefore starts
deny-by-default and requires an explicit migration to enable RLS, add reviewed
policies and add only the required grants.

The local server did not define optional Supabase roles `anon`,
`authenticated` or `service_role`. Both migrations nevertheless revoke their
table, column, sequence, function, schema and default privileges when those
roles exist, and reject membership in either H-E capability group. Startup
attestation also fails if an existing browser/service role can reach a public
application relation, H-E helper, capability group, or `CREATE` on schema
`public`. The local result must not be represented as a live Supabase
catalogue check.

## Direct five-role PostgreSQL policy matrix

The direct matrix uses distinct synthetic database-backed application
sessions and a restricted non-owner runtime LOGIN. It tests row visibility
and mutation at SQL level, independently of endpoint routing:

| Identity | Verified policy boundary |
|---|---|
| Master Admin | Reads global and programme-scoped rows and performs approved master mutations; still cannot directly read helper-only tables |
| Programme Coordinator | Reads and mutates only normalized in-scope programme rows; can join only in-scope external schedule/identity rows; null, empty and blank scopes grant nothing |
| Department Secretary | Reads and mutates events only for its posting, sees only its posting's resident/attendance rows, and receives catalogue rows through the reviewed secretary programme pool |
| Native Resident | Reads only its native identity, posting, eligible event/catalogue and attendance rows; native attendance mutation remains owner- and event-bound |
| Non-NHG Resident | Reads only its separate external identity and exact date/programme/posting schedule rows; external attendance mutation remains owner- and event-bound and cannot enter native tables |

A sixth context-free baseline confirms that direct tables return no rows and
helper-only relations return permission denied. Cross-programme,
cross-posting, cross-resident, native/external and out-of-scope mutations are
hidden or rejected. The database matrix supplements, rather than duplicates,
the existing full application suite.

## Migration structure and lifecycle

### `20260726_000025` — role, context and helper foundation

This revision:

- creates and hardens the two stable capability roles;
- creates owner-only `mata_private` and callable `mata_rls` schemas;
- creates the signing-key store and signed transaction-context installer;
- creates the exact runtime/auth/shared helper ACLs;
- creates global native/external MCR uniqueness triggers using a canonical MCR
  advisory lock;
- adds the reviewed session, login, registration, rate-limit, TTF, audit,
  dependency and surplus helpers;
- changes `audit_logs.entity_id` from UUID to text so bounded non-UUID audit
  identifiers can be recorded;
- grants no direct application-table access.

The foundation was replayed from `20260722_000024` before the policy cutover.
Its catalogue assertions fail the migration if roles, helper ownership,
security-definer configuration, search paths, pgcrypto dependencies or ACLs
are unsafe.

### `20260726_000026` — policy and grant cutover

This revision:

- asserts the complete foundation catalogue;
- creates 11 relationship predicates;
- enables RLS on all 34 application tables;
- creates the exact 84-policy set;
- revokes existing application, PUBLIC and optional browser/service grants;
- grants the 83 reviewed runtime table actions and 16-column `users` read
  surface;
- leaves six sensitive relations helper-only;
- grants no sequence access;
- revokes schema `public` CREATE from PUBLIC and restricted/browser roles;
- installs deny-by-default owner ACLs;
- transactionally asserts the final relation, policy, function, ownership,
  PUBLIC, browser-role and default-ACL catalogue.

After final migration edits, the named database successfully replayed
`20260726_000026 -> 20260726_000025 -> 20260726_000026`; both Alembic commands
exited zero and `alembic current` returned `20260726_000026`.

The lifecycle test additionally:

1. created an empty disposable database and upgraded the complete chain
   through `20260726_000026`;
2. verified the clean cutover catalogue;
3. downgraded to `20260726_000025`;
4. inserted sentinel programme and staff rows;
5. upgraded the populated database to `20260726_000026`;
6. downgraded to `20260726_000025`;
7. re-upgraded to `20260726_000026`;
8. verified the sentinel rows were unchanged at every populated transition.

### Downgrade constraints

Downgrade is intentionally asymmetric:

- `000026 -> 000025` drops H-E policies and policy helpers, revokes runtime
  application grants and disables RLS only on tables whose RLS was introduced
  by `000026`;
- the 15 tables that already had RLS at `000024` retain it;
- PUBLIC/browser/schema/default-ACL hardening is never broadened during
  downgrade;
- `000025` retains the two stable capability roles because external LOGIN
  roles may already depend on them;
- `000025 -> 000024` refuses to convert `audit_logs.entity_id` back to UUID if
  any non-UUID value exists, then drops the H-E helper schemas only when that
  conversion is lossless.

Application code configured for H-E must not continue serving through an
intermediate downgrade. Rollback must be coordinated with application
shutdown or compatible code, use the migration owner, preserve FastAPI
authorization, and never restore broad PUBLIC, browser or `service_role`
access.

## Concrete compatibility corrections

### Concurrent session rotation

The remaining rotation failure was a test-classification and test-transaction
problem, not a production double-rotation defect.

An earlier race allowed one worker to resolve the old token only after the
winner committed. That worker correctly observed no active session, but the
test exited through `assert loaded is not None` rather than recording the
approved `AppSessionInvalidError` loser. During H-E adaptation, retaining a
shared family lock from resolution and then attempting an exclusive rotation
in the same transaction also reproduced a shared-to-exclusive advisory-lock
upgrade deadlock. Production does not use that transaction shape: middleware
resolution completes before refresh/logout enters a fresh exclusive protected
database dependency.

The test-only correction now:

1. resolves two independent old-session snapshots in completed auth-boundary
   transactions;
2. synchronizes both workers;
3. rotates each snapshot in a fresh runtime helper transaction;
4. accepts only one created session and one controlled
   `AppSessionInvalidError`;
5. allows unexpected assertions, SQLAlchemy, transaction and connection
   errors to remain test failures.

No production session-rotation code was weakened or changed for this race.
The production helper retains its subject/family locks, locked database-row
reload, `populate_existing` refresh, parent revocation and unique
`rotated_from_session_id` constraint.

Verified evidence from 10 independent process-isolated repetitions, the
focused race run and the complete PostgreSQL security module:

- exactly one rotation succeeded;
- exactly one controlled invalid-session loser occurred;
- exactly one active replacement child existed;
- the original parent was revoked with reason `rotated`;
- the old session token no longer resolved;
- the winning session token resolved;
- the old CSRF value failed for both parent and replacement;
- the winning replacement's rotated CSRF succeeded;
- the loser created no second replacement;
- no identity-map or pooled-connection state revived the parent.

Only 10 independent repetitions are counted. An attempted repeated-node
collection that pytest collected once is deliberately excluded from the
repeat total.

### Staff self-password reset

A concrete staff-account boundary defect was corrected in production code:
Master Admins may not reset their own password through the staff-account
management endpoint. The service rejects the request before loading or
changing the target, revoking sessions, calling Supabase, committing or
writing an audit record. The focused test verifies controlled `422` handling
and zero side effects. It does not remove any approved separate credential
recovery path.

## Configuration and restricted-role runbook

No secret values or database URLs are recorded here. H-E requires these
server-side names:

- `DATABASE_RLS_ENABLED=true`;
- `DATABASE_RUNTIME_ROLE=mata_app_runtime`;
- `DATABASE_AUTH_ROLE=mata_auth_internal`;
- `DATABASE_URL` — asyncpg URL for the restricted runtime LOGIN;
- `AUTH_DATABASE_URL` — asyncpg URL for the distinct restricted auth LOGIN;
- `SYNC_DATABASE_URL` — synchronous URL for the distinct migration owner;
- `AUTH_TRANSPORT=cookie`.

The three URLs must target the same PostgreSQL host, port and database and use
three distinct usernames. RLS mode rejects missing or malformed URLs, a
runtime/auth username collision, a migration credential reused by either
application boundary, an unexpected capability-group name, or non-cookie
transport. Production retains the existing requirements for
`ENVIRONMENT=production` and `AUTH_MODE=supabase`.

Before application traffic is enabled:

1. stop or keep application traffic off the target database;
2. use only the migration credential to apply `000025`, inspect its exact
   role/helper catalogue, then apply `000026`;
3. provision two non-owner, `INHERIT`, `NOSUPERUSER`, `NOBYPASSRLS` LOGIN
   roles, each as a non-delegable member of exactly one stable capability
   group;
4. configure the runtime and auth URLs without exposing their values;
5. start FastAPI and require both database-boundary attestations to pass;
6. run the direct policy matrix and representative workflows with restricted
   credentials;
7. run the complete backend suite through the restricted-role runner;
8. perform separately authorized deployment verification before claiming any
   production control.

FastAPI startup attestation checks login and capability attributes,
membership and `ADMIN OPTION`, forbidden cross-capability access, object
ownership, grant options, exact table/column/sequence/function privileges,
executable-helper `SECURITY DEFINER` posture, schema ownership and fixed search
paths, PUBLIC/browser reachability, schema CREATE, `row_security`, and the
named 34-table/84-policy structural catalogue. Policy attestation also rejects
the wrong role/permissiveness, command-inappropriate `USING`/`WITH CHECK`
shape, or a predicate that no longer uses the reviewed `mata_rls` boundary.
Exact predicate-expression review remains part of migration-source and
restricted catalogue verification. Startup fails closed on the structural
deviations above. The focused negative test injects 16 different privilege,
helper-posture, and policy defects transactionally; every injection must be
rejected and rolled back.

For local verification, set `SYNC_DATABASE_URL` only to an owner URL whose
database name is exactly `mata_phase5b_verify_5bhe`, then run from `backend`:

```powershell
python -B -m tests.run_rls_restricted_pytest -q --tb=short -p no:cacheprovider tests
```

The runner refuses a non-local host, another database name, URL query options,
an unexpected revision, unsafe capability roles or a non-owner credential. It
creates random ephemeral runtime/auth LOGIN members before pytest collection,
sets the child process to RLS-enabled test mode, and removes both generated
roles after success, failure or interruption. Generated credentials are not
written to repository files.

Targeted migration replay must likewise use a fresh process and the exact
named disposable database:

```powershell
python -B -m alembic downgrade 20260726_000025
python -B -m alembic upgrade 20260726_000026
python -B -m alembic current
```

Do not use these commands against live Supabase without a separate deployment
authorization, approved migration credential, backup/recovery plan and
production change window.

## Local verification evidence

| Gate | Local result |
|---|---|
| Foundation, helper integration, direct policy matrix and PostgreSQL security gate | 45 passed in 56.26s |
| Direct role matrix | Master, Programme Coordinator, Secretary, native Resident, Non-NHG Resident and no-context isolation passed |
| Startup attestation baseline | Passed |
| Startup attestation negative catalogue/privilege injections | 16/16 rejected as expected |
| H-E migration lifecycle | 1 passed, 1 existing Alembic deprecation warning, 20.60s |
| Named `000026 -> 000025 -> 000026` replay | Both transitions exited 0; current revision `20260726_000026` |
| External Resident PostgreSQL workflows | 42 passed |
| PostgreSQL security module | 13 passed |
| Session-rotation process repetitions | 10/10 passed |
| Admin/Secretary event workflows | 5 passed |
| Resident event workflow | 1 passed |
| Teaching-event options workflow | 1 passed |
| Focused staff-account workflows | 14 passed |
| Restricted-runner compatibility correction | 100 passed, 1 warning |
| Complete backend suite under restricted runtime/auth roles with RLS active | 1,162 passed, 10 warnings in 699.16s (11m39s) |
| Alembic topology | One head: `20260726_000026` |
| Final post-suite catalogue checkpoint | Revision `20260726_000026`; 34/34 RLS, 0 forced, 84 policies/0 wrong target roles, owners only `postgres`, 52 `mata_rls` and 10 `mata_private` functions, 0 leftover ephemeral logins |
| Repository security source scan | Frontend plus complete tracked/untracked worktree passed |
| Whitespace/diff validation | `git diff --check` passed; untracked-file trailing-whitespace scan found no matches |
| Added-data review | No real secret, token, database credential, MCR, session/CSRF value, or personal record; matches were limited to reserved `.invalid` addresses and explicit synthetic test identifiers |

The first complete restricted-role run produced `1,089 passed, 73 failed,
10 warnings`. All 73 failures were localized test-fixture compatibility drift:
the runner correctly exported RLS/cookie settings into fake bearer and
transport unit tests, and one fake staff endpoint still overrode the old shared
database dependency rather than the new exclusive dependency. Production
configuration validation, middleware, database dependencies, policies and the
restricted runner were not weakened. After the test-only settings/dependency
correction, the six affected modules passed `100 passed, 1 warning`, followed
by the complete passing result above.

Warnings are not hidden and a failed or interrupted full-suite run is not a
pass. Any demonstrated compatibility failure must be corrected narrowly and
the affected gate rerun before final H-E completion.

The ten final warnings are one existing Starlette test-client deprecation
warning and nine Alembic `path_separator` deprecation warnings emitted by tests
that intentionally exercise migration workflows. They remain visible and did
not mask a failure.

## Local verification incident

An earlier in-process Alembic invocation reused cached application settings and
targeted the local default `mata_db` instead of the named H-E database. A later
accidental replay left that local default database at revision
`20260726_000025`; its previously observed revision was `20260722_000024`.
This did not reach Supabase or any remote database.

No further inspection or restoration was performed because the user authorized
database mutation only for `mata_phase5b_verify_5bhe`, and the safety reviewer
rejected expanding that authority to `mata_db`. All accepted H-E migration,
catalogue, policy, workflow and full-suite evidence used fresh child-process
configuration explicitly targeting `mata_phase5b_verify_5bhe`. Future Alembic
verification must retain that fresh-process pattern and re-check the target
database name before execution.

## Scope and assurance limits

- This is local source and disposable-database evidence only.
- RLS is not recorded as deployed.
- Production role provisioning, migration, startup attestation and policy
  behavior remain unverified until a separately authorized deployment.
- Browser roles remain denied direct application-table and H-E helper access.
- The normal backend must never use `service_role` or the migration owner as a
  workaround.
- FastAPI authorization remains mandatory even when an RLS policy permits a
  row.
- Native and Non-NHG Resident identities, schedules and attendance remain
  separate.
- New compliance tables remain deny-by-default until an explicit reviewed
  RLS migration exists.
- No commit, push, merge or deployment is part of this report.

**PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED**
