# Phase K Regression and Security Audit

<!-- Phase K completion evidence is recorded below; the earlier preflight snapshot is retained for traceability. -->

## Final completion evidence

**Verdict: COMPLETE.** All Phase K local regression, PostgreSQL/RLS, migration,
security, and frontend gates passed against a fresh disposable database.

| Item | Value |
| --- | --- |
| Integration branch / starting SHA | `CL/evolved-ttf-integration` / `1bf583798a19b7130d91b613ee2fc2a449f24a0b` |
| Phase K branch | `CL/evolved-ttf-k-regression-security` |
| `main` / `origin/main` at start | `3f396101f6184175450e8d5c83662c25813fb330` |
| Alembic source head | one head: `20260806_000038` |
| Initial worktree | clean |

The audit used the project schema, API, business-logic, parsing, security,
account, decision-log, UI, responsive, and Phase R readiness contracts as the
authoritative baseline. It covered authentication/session and CSRF boundaries,
Secretary capability enforcement, PC programme scope, Master/native/external
Resident boundaries, A-J TTF parsing and upload, Teaching Name lifecycle,
mapping revisions, event provenance, attendance, resolver outcomes,
audit/cache behavior, migration `20260806_000038`, RLS/grants/helper ACLs, and
protected frontend state.

### Corrections

1. The local RLS harness and fixed-target PostgreSQL tests now allow the exact
   Phase K disposable target and K runtime/auth role namespace only when
   explicitly selected. `tests.run_phase_k_postgres_verify` reuses the tested
   Phase R lifecycle with an isolated configuration and restores it afterward.
2. The Secretary Teaching Name options query cast its optional programme bind
   to `text`. PostgreSQL can now type the omitted programme filter; the
   existing authorization and scope condition is unchanged.
3. The first Sol xhigh review found that six independently runnable PostgreSQL
   modules trusted arbitrary `MATA_RLS_DISPOSABLE_DATABASE_NAME` values. A
   shared allowlist now permits only the known E2B2, Phase R, and Phase K
   disposable targets, and regression coverage rejects `postgres` and an
   arbitrary name before any database connection is opened.

### PostgreSQL, RLS, migration, and cleanup

With the ignored `backend/.env` loaded only into the verifier process, the
following clean local command passed:

```text
venv\Scripts\python.exe -B -m tests.run_phase_k_postgres_verify -q --tb=short -p no:cacheprovider tests
1928 passed, 30 warnings in 482.96s (0:08:02)
```

It cleanly migrated to `20260806_000038`, verified current/head alignment,
ran migration attestation/mutation and supported rollback/re-upgrade checks,
provisioned and removed restricted roles, and covered RLS, grants, helper ACLs,
fixed search paths, `PUBLIC` revocation, explicit `000038` regression,
cross-role/cross-programme SQL denials, transaction/locking/rollback,
cache-after-commit, and the broad PostgreSQL-backed backend suite.

The fixed nullable-filter path also passed in isolation after a clean migration:

```text
venv\Scripts\python.exe -B -m tests.run_phase_k_postgres_verify -q --tb=short -p no:cacheprovider tests\test_teaching_event_options_postgres.py
1 passed in 2.43s
```

The verifier/migration harness suite plus the new target-rejection coverage
passed **59 tests in 0.88s**. The source
head command returned `20260806_000038 (head)`. The historical date-sensitive
external Resident forecast coverage passed in the final run without any
business-logic adjustment.

The final maintenance-database read-only attestation was:

```text
target_database_exists=0
target_session_count=0
phase_k_generated_role_count=0
mata_test_role_count=0
phase_k_owner_retained=1
```

Only the disposable target and generated test roles were removed. The dedicated
local owner role remains intentionally for manual removal by the local
PostgreSQL superuser.

### Evolved-TTF, frontend, and security gates

Earlier focused evolved-TTF/parser/upload/resolver/event/all-28 suites passed
**439 tests**; focused auth/authorization/attendance/audit/cache/SQL suites
passed **440 tests**. The fresh 1928-test PostgreSQL run subsequently covered
those backend paths under actual RLS and role enforcement.

| Gate | Result |
| --- | --- |
| `npm test -- --run` | **220 passed, 0 failed** |
| `npm run typecheck`, `npm run lint`, local/stub `npm run build` | passed |
| `python -B -m compileall -q app tests` | passed |
| `python -m pip check` | `No broken requirements found.` |
| `.github/scripts/test_security_scripts.py` | **27 tests passed** |
| frontend, emitted artifact, worktree, and integration-diff source scans | all passed |
| `npm audit --omit=dev --audit-level=high` | `found 0 vulnerabilities` |

`backend/.env` was confirmed ignored and absent from Git status. Its contents,
credentials, and connection URLs are intentionally not recorded. `git diff
--check` and `git diff --cached --check` are rerun after this record is final.

The backend produced existing Starlette/TestClient and Alembic configuration
deprecation warnings. The local frontend build produced its existing
over-500-kB bundle advisory. Neither is a Phase K security or release blocker.

### Sol xhigh review

The first independent read-only Sol xhigh review reported one **MATERIAL**
test-safety issue: an arbitrary environment-selected local database could be
used by six independently runnable PostgreSQL modules. The issue is corrected
by the shared allowlist and its four new helper tests, including two negative
rejection cases. The affected harness suite passed 59 tests and the fresh broad
PostgreSQL suite passed 1928 tests. The permitted follow-up Sol xhigh review
approved the correction with no remaining BLOCKING or MATERIAL finding. No
third review was requested or run.

### Phase L handoff

Phase L was not started. Its planned browser-level smoke work remains separate.

## Superseded preflight snapshot

**BLOCKED — local PostgreSQL authentication is unavailable for the required fresh disposable-database validation.** This is a progress record, not a Phase K completion record.

### Starting checkpoint

| Item | Value |
| --- | --- |
| Integration branch | `CL/evolved-ttf-integration` |
| Starting SHA | `1bf583798a19b7130d91b613ee2fc2a449f24a0b` |
| Phase K branch | `CL/evolved-ttf-k-regression-security` |
| `main` / `origin/main` | `3f396101f6184175450e8d5c83662c25813fb330` |
| Starting Alembic head | One head: `20260806_000038` |
| Initial worktree | Clean |

Initial verification also confirmed that `backend/.env` is ignored, Phase R (`b244607`) is contained by the integration branch, there were no untracked files, and `git diff --check` passed.

### Read-only audit

The audit inspected authentication/session transport, role dependencies, Secretary capability routes and services, PC scope and mapping/event services, Master Admin boundaries, native and external Resident routes, TTF/RDB parsing, Teaching Name lifecycle, mappings, scheduled event provenance, attendance, the Phase H resolver, audit/cache services, migration `20260806_000038`, RLS harnesses, frontend route guards/protected state, and Secretary/PC UI contracts. The authoritative project, schema, API, business-logic, parsing, security, account, decision-log, UI, responsive, and Phase R readiness documents supplied the audit contract.

| Severity | Finding | Scope and decision |
| --- | --- | --- |
| BLOCKING (environment) | The configured local maintenance credential is rejected on both `localhost` (IPv6) and `127.0.0.1` before the required identity query. | Blocks clean migration, restricted-role/RLS, migration mutation, rollback/re-upgrade, and live concurrency validation. No application data was accessed. Do not weaken credentials or reuse Phase R/remote data. |
| MATERIAL (corrected) | RLS helpers allowed only older E2+B2/Phase R database names, and some PostgreSQL suites fixed the older target. | They could not exercise `mata_evolved_ttf_k_verify`. A narrow test-harness correction now permits the exact K target only when explicitly selected. |
| INFORMATIONAL | Vite reports one JavaScript bundle above 500 kB after minification. | Non-security performance follow-up; no Phase K correction. |

No unresolved application-code authorization, parser, event-source, cache, or frontend protected-state defect was found in the completed audit/test evidence.

### Corrected defect

The test-only correction adds `tests.run_phase_k_postgres_verify`, a K-scoped generated-role namespace, and explicit K-target support in the affected local PostgreSQL harnesses. Formerly fixed-target PostgreSQL tests now use `MATA_RLS_DISPOSABLE_DATABASE_NAME` when supplied, while retaining their existing defaults. No runtime authorization, RLS policy, migration, or application schema changed.

```text
venv\Scripts\python.exe -B -m pytest -q --tb=short -p no:cacheprovider \
  tests/test_run_phase_k_postgres_verify.py \
  tests/test_run_phase_r_postgres_verify.py \
  tests/test_rls_restricted_pytest_runner.py \
  tests/test_migration_database_attestation.py \
  tests/test_migration_mutation_guards.py

54 passed in 0.77s
```

### Regression results

| Gate | Result |
| --- | --- |
| Python environment | Python 3.12.10; `venv\Scripts\python.exe -m pip check` passed. |
| Python syntax | `backend\venv\Scripts\python.exe -B -m compileall -q backend\app backend\tests` passed. |
| Alembic source head | `venv\Scripts\python.exe -m alembic heads` returned one head, `20260806_000038`. |
| Parser/upload/resolver/events/all-28 | Focused TTF parser, workbook safety, resolver, event interval, and Phase R suites: **439 passed**, one existing Starlette deprecation warning. |
| Auth/authorization/attendance/audit/cache/SQL | Focused session, role, Resident/external Resident, Secretary, PC, mapping, event, attendance, Data Revalidation, audit, rate-limit, redaction, and SQL-composition suites: **440 passed**, one existing Starlette deprecation warning. |
| Broad backend and real PostgreSQL partitions | Blocked before execution by the unavailable local credential. Direct collection with the stale local file correctly fails settings validation because its runtime/auth URLs share one owner identity. Focused non-database tests used process-only synthetic settings. |
| Frontend contracts | `npm test`: **220 passed, 0 failed**. |
| Typecheck / lint | `npm run typecheck` and `npm run lint` passed. |
| Local/stub production build | `VITE_APP_ENV=local`, `VITE_AUTH_MODE=stub`, `VITE_API_BASE_URL=/api/v1`, `npm run build` passed. |

### Evolved-TTF and all-28 contract

Completed coverage confirms final A–J parsing, populated Column K rejection, formula/sparse workbook safety, stable target and mapping identities, pending mapping operation, source-provenance event behavior, deterministic resolver outcomes, and generic all-28 readiness. The 20 sentinel programmes retain `ALL`; SPORTSMED and PALLMED retain actual R4–R6. The removed Teaching Name catalogue and Details of Training are not reintroduced, and no full compliance engine was added.

### Authentication and authorization

The completed focused suites cover unauthenticated rejection, cookie/CSRF transport, session invalidation, generic errors, native Resident ownership, external Resident separation, Secretary capability scope, PC persisted programme scope, Master Admin distinctions, cross-role denials, Teaching Name lifecycle/revisions, mapping scope, event provenance, and attendance duplicate/ownership controls. Frontend contracts confirm memory-only protected state, no bearer/browser credential persistence, and backend-derived Secretary/PC authority presentation.

The database-enforced counterparts remain blocked; frontend guards are not treated as a security boundary.

### PostgreSQL, RLS, migration, and cleanup

The intended local target is `mata_evolved_ttf_k_verify`, with an ephemeral `mata_phase_k_owner` and K-scoped runtime/auth roles. The verifier preflights maintenance database, current user, address, port, target absence, and owner absence before mutation. Both permitted loopback forms rejected the configured password; therefore no K database, owner role, generated role, or `mata_test_*` role was created. No retained Phase R data was reused.

Static audit of `20260806_000038` confirms fixed helper search paths, `PUBLIC`/browser-role execution revocation, runtime-only helper grants, and persisted PC programme scope plus exact Teaching Name mapping scope for pool-backed events. Its clean migration and restricted regression are still required.

### Audit, cache, concurrency, and security gates

The 440-test focused suite covers audit metadata/redaction, Data Revalidation, cache/session fencing, mutation behavior, and attendance integrity. Live lock, rollback, cache-after-commit, migration-mutation, policy/grant/helper ACL, and rollback/re-upgrade tests remain blocked pending a working local credential.

```text
backend\venv\Scripts\python.exe -B .github\scripts\test_security_scripts.py
27 passed

backend\venv\Scripts\python.exe -B .github\scripts\security_source_scan.py --frontend
backend\venv\Scripts\python.exe -B .github\scripts\security_source_scan.py --frontend-dist
backend\venv\Scripts\python.exe -B .github\scripts\security_source_scan.py --worktree
backend\venv\Scripts\python.exe -B .github\scripts\security_source_scan.py --diff-base CL/evolved-ttf-integration
all passed

npm audit --omit=dev --audit-level=high
found 0 vulnerabilities
```

The security scans cover frontend source, generated artifacts, worktree and diff secret/personal-data rules, and unsafe browser-auth paths. This record contains no credentials, database URLs, personal data, or resident identities.

### Known unrelated failures and residual risk

- The historical date-sensitive external-resident forecast test was not reached in a clean PostgreSQL run, so its current status is **not yet known**.
- Completed focused backend groups emitted the existing Starlette/TestClient deprecation warning; it is non-blocking and unrelated to the correction.
- The unavailable local credential is an unresolved blocking environment condition, not an accepted residual risk.

### Sol review and Phase L handoff

No Sol review has been launched. The required independent review is deferred until real PostgreSQL validation, affected reruns, and the complete Phase K gate set pass.

Phase L remains untouched. After Phase K is unblocked, it retains only the planned end-to-end smoke work: representative accounts, A–J upload, Teaching Name lifecycle/pending/mapped work, scheduled/fixed/global events, native Resident visibility and attendance, resolver outcomes, all-28 smoke, and browser-level release-candidate assessment.

### Resume checklist

1. Provide a working explicitly local maintenance credential that may create/drop only the K disposable database and owner role.
2. Re-run the K verifier; confirm it removes the K database, generated roles, and `mata_phase_k_owner`.
3. Run migration mutation, rollback/re-upgrade, restricted RLS, policy/grant/helper ACL, live cache/concurrency, and broad backend tests.
4. Rerun affected gates, update this record with exact totals, obtain exactly one Sol xhigh review, and address any blocking/material finding.
5. Commit and merge locally only after every Phase K completion criterion passes.
