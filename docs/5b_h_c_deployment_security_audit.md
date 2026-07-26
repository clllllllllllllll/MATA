# 5B-H-C Deployment Security and Functional UAT Audit

> **Historical evidence boundary — 2026-07-22:** This document is a point-in-time Phase 5B-H-C record. Its commit identifiers, migration revision, test counts, live observations, and `BLOCKED` / `MANUAL VERIFICATION REQUIRED` results must remain unchanged. Phase 5B-H-D later replaced the browser-bearer transport described here; current implementation and local verification evidence is recorded in `docs/5b_h_d_production_security_implementation.md`. That later local evidence does not retroactively change any deployed result in this document.

## 1. Audit metadata

| Field | Value |
|---|---|
| Audit date | 2026-07-22 |
| Git commit audited | `138812aab616baf8a384d79947e97e29e9f86495` |
| Audit branch | `CL/5b-h-c-deployment-security-audit` |
| Frontend deployment label | `mata-aine.vercel.app` (from committed deployment configuration; deployed revision not verified) |
| Backend deployment label | `mata-backend.vercel.app` (referenced by committed frontend deployment configuration; deployed revision not verified) |
| Supabase project label | Unavailable; intended project was not confirmed in the approved command environment |
| Operator | Codex (repository/evidence audit; live systems read-only) |

The requested `docs/5b_h_vercel_supabase_uat_security_plan.md` file is not present. The repository's apparent current equivalent, `docs/5b_h_vercel_uat_security_plan.md`, was reviewed. This audit did not implement Phase 6 compliance or change application code, deployment settings, authentication, CORS, RLS, grants, environment variables, database rows, accounts, or deployed data.

## Post-remediation update — 2026-07-22

| Field | Evidence |
|---|---|
| Remediation evidence date | 2026-07-22 |
| Current `main` commit reviewed | `eaa3d7f1b1329030c88064c81f6fff7999d5fc86` |
| Authorization remediation commit | `e0efb0db6a163f4b6e82b726deba96ba9f82cef6`, merged by `9f10d587b3ddfe4f49fc10f37b956c689745fe31` |
| Native overlap remediation commit | `a0c4bd11bd67351c5b47274715328c09efc19791`, merged by `eaa3d7f1b1329030c88064c81f6fff7999d5fc86` |
| Source commit ancestry | Authorization source `e0efb0d` is an ancestor of `main`. Original overlap source `94bc0c4f320011580be7199b87c24e78fb62688f` is a historical non-ancestor source hash with the same stable patch ID as merged commit `a0c4bd1`. |
| Post-remediation status | Both High local-code findings are resolved in merged code. Local post-merge disposable PostgreSQL verification passed. Deployment evidence remains pending. |

The authorization fix requires explicit Master Admin authority for RDB, FormF1, and Public Holidays / AY Dates uploads while preserving scoped TTF access for any non-master admin (the Programme PC tier under the provisioning contract). Middleware-backed requests derive Master Admin authority from persisted/verified admin level; the existing local header shim remains limited to non-production stub/demo mode. The native attendance fix rejects submitted distinct-event overlaps across scheduled and native ad-hoc paths, preserves the earlier attendance, and uses transaction-scoped PostgreSQL advisory locks to serialize same-resident/date submissions.

The operator migrated a disposable PostgreSQL database cleanly from baseline through `20260721_000022 (head)`, then recorded `66 passed, 1 warning` for the focused attendance/PostgreSQL command and `1009 passed, 6 warnings` for the full backend suite. Native overlap concurrency and all five force-delete PostgreSQL cases passed. The temporary database was successfully dropped. No live database, Supabase project, Vercel deployment, account, environment, or persistent configuration was accessed or changed.

This is `PASS — local automated` and `PASS — local disposable PostgreSQL` evidence only. It is not proof of deployed Supabase/Vercel state.

## 2. Evidence-status definitions

- `PASS` — directly verified through reproducible evidence.
- `FAIL` — direct evidence shows the requirement is not met.
- `MANUAL VERIFICATION REQUIRED` — repository code and the available command environment cannot verify the live requirement.
- `BLOCKED` — an approved prerequisite, account, fixture, URL capability, permission, or correct database target was unavailable.
- `NOT APPLICABLE` — the requirement genuinely does not apply, with an explanation.
- `Historical FAIL` — a preserved failure at the originally audited commit; it is not a claim about current merged code.
- `Resolved in merged code` — the remediation is present in current `main`; deployment is not implied.
- `PASS — local automated` — maintained local tests or direct source/history inspection passed without proving deployed state.
- `PASS — local disposable PostgreSQL` — integration verification passed against a temporary local PostgreSQL database that was subsequently dropped.
- `BLOCKED — deployed fixture unavailable` — the local contract may pass, but the deployed account or fixture needed for confirmation was unavailable.
- `Not proof of deployed Supabase/Vercel state` — local evidence must not be used to infer deployment, environment, Supabase project, account, grant, RLS, or Data API state.

Repository support is not treated as proof of deployed configuration. A committed migration is not treated as proof that Supabase is at head. Source absence of direct Supabase table calls is not treated as proof that the public Data API cannot read tables.

## 3. Executive verdict

`NO-GO — CODE BLOCKERS RESOLVED; DEPLOYMENT EVIDENCE PENDING`

The original audit verdict at commit `138812aab616baf8a384d79947e97e29e9f86495` was `NO-GO — BLOCKERS MUST BE FIXED`. That audit correctly reproduced two High findings with synthetic local fixtures:

1. A Programme PC with blank/whitespace-only programme scope can reach the global RDB, FormF1, and Public Holidays upload mutations.
2. The native NHG Resident attendance path accepts a distinct event whose interval overlaps an earlier accepted event.

Those historical results are preserved below. Both defects were subsequently fixed, independently reviewed, merged into `main`, and verified through maintained tests, including a disposable PostgreSQL concurrency run. The audit is not upgraded to GO because deployment protection, backend environment values, exact CORS membership, deployed secret separation, the Supabase database revision/schema/seed state, the live Data API boundary, deployed account workflows, and the valid-bearer conflicting-header case remain unverified or blocked. Stakeholder UAT remains NO-GO and Phase 6 is not approved.

## 4. Historical findings table at the audited commit

The statuses in this table preserve the original 2026-07-22 audit against `138812aab616baf8a384d79947e97e29e9f86495`; they are not rewritten as though the failures never existed.

| ID | Area | Status | Evidence | Risk | Required action | Owner |
|---|---|---|---|---|---|---|
| HC-DEPLOY-001 | Deployment protection | MANUAL VERIFICATION REQUIRED | Existing browser state loaded MATA content; a cookie-free request received Vercel bot mitigation (`429`, `X-Vercel-Mitigated: challenge`), which does not prove an intentional stakeholder access gate. No committed setting proves Deployment Protection. | High | Verify the gate and stakeholder access list in a private/incognito session and Vercel settings. | Deployment owner |
| HC-ENV-001 | Backend production environment | MANUAL VERIFICATION REQUIRED | No safe deployed diagnostics or Vercel settings access exposed both `ENV` and `AUTH_MODE`. Raw-header rejection proves only that production **or** Supabase enforcement is active. | High | Review backend environment names/values safely and record only modes and presence. | Deployment owner |
| HC-CORS-001 | Exact CORS allowlist | MANUAL VERIFICATION REQUIRED | Runtime probes passed for the approved origin and three named controls, but the deployed `CORS_ORIGINS` membership was not safely inspectable; those probes cannot rule out an additional allowlisted origin. | High | Review the deployed allowlist without copying values, record only approved hostnames, and retain the runtime probes. | Backend/deployment owner |
| HC-SECRETS-001 | Repository/build secret separation | PASS | Scoped secret-name scans found no backend-only names in frontend code/build inputs; forbidden `VITE_*` variants were absent from code/config; a fresh bundle names-only scan returned no match. | Informational | Keep the scan in release checks. | Frontend owner |
| HC-SECRETS-002 | Deployed secret separation | MANUAL VERIFICATION REQUIRED | Frontend and backend Vercel environment settings and the deployed artifact were not safely inspectable. | High | Verify frontend has public `VITE_*` variables only and backend-only values remain backend-only. | Deployment owner |
| HC-AUTHZ-001 | Programme PC scope enforcement | FAIL | Synthetic blank-scope admin requests returned `200` from RDB, FormF1, and Public Holidays upload routes; only TTF applies an explicit programme-scope check. | High | Resolve the intended authority for global uploads, enforce it server-side, and add null/empty/blank scope regression tests. | Backend/security owner |
| HC-AUTHZ-002 | Deployed role/account UAT | BLOCKED | No approved Master Admin, Programme PC, Secretary, NHG Resident, Non-NHG Resident, or out-of-scope UUID fixture was available. | High | Run the account matrix using UAT-safe accounts and synthetic data after HC-AUTHZ-001 is fixed. | UAT operator |
| HC-HEADERS-001 | Token-free raw-header rejection | PASS | Deployed `/api/v1/auth/me` returned `401`; body classification found the controlled unauthorized marker and no role/user, SQL, stack, or path markers. | Informational | Retain as a deployment smoke check. | Backend/deployment owner |
| HC-HEADERS-002 | Conflicting headers with valid bearer | BLOCKED | Automated tests pass, but no approved deployed bearer fixture was available. | Medium | Repeat against the deployed backend with a synthetic valid account; record only status and generic identity outcome. | UAT operator |
| HC-MIGRATION-001 | Supabase migration/schema | BLOCKED | Repository head is `20260721_000022`; the effective backend target was `localhost/mata_db`, not an approved Supabase project, so `alembic current` and read-only schema SQL were not run. | High | Point an approved terminal at the confirmed UAT Supabase project and run read-only revision/schema checks. | Database/deployment owner |
| HC-DATAAPI-001 | Supabase Data API exposure | MANUAL VERIFICATION REQUIRED | Source has no direct MATA table/RPC calls, but browser network, exposed schemas, grants, RLS, and a public-key denial request were not verified. | High | Inspect browser Network and Supabase API/grants; perform the approved public-key denial test without retaining a body. | Supabase/security owner |
| HC-FUNCTIONAL-001 | Native distinct-event overlap | FAIL | A synthetic native resident submitted a second distinct event with the same interval; one native row was added instead of returning the required conflict. | High | Add server-side native overlap enforcement and regression coverage in a separate application-code task. | Backend owner |
| HC-FUNCTIONAL-002 | Deployed functional workflows | BLOCKED | Health and selected perimeter checks ran, but approved accounts, upload fixtures, and a guarded disposable PostgreSQL database were unavailable. | High | Execute the remaining workflow matrix after the High code findings are fixed. | UAT operator |

### Remediation status

| Finding | Historical status | Current code status | Evidence | Remaining deployed check |
|---|---|---|---|---|
| HC-AUTHZ-001 | Historical FAIL | Resolved in merged code / PASS — local automated | Explicit Master Admin dependency on all three global uploads; TTF retains normalized scoped access for non-master admins (the provisioned Programme PC tier); blank-scope result changed from `200/200/200` to `403/403/403`; fix `e0efb0d`, merge `9f10d58`. | BLOCKED — deployed fixture unavailable: run the account-based Master Admin/Programme PC role smoke. |
| HC-FUNCTIONAL-001 | Historical FAIL | Resolved in merged code / PASS — local disposable PostgreSQL | Submitted-only native conflict query, half-open interval guard, request-order atomicity, shared scheduled/ad-hoc guard, transaction-scoped advisory lock, and real concurrency test; fix `a0c4bd1`, merge `eaa3d7f`. | Optional deployed synthetic workflow only after an approved fixture; no live fixture was used here. |
| HC-FUNCTIONAL-002 guarded PostgreSQL evidence | BLOCKED | PASS — local disposable PostgreSQL | Native-only, external-only, mixed, stale-impact, and injected-failure rollback force-delete cases passed in the disposable database; full suite `1009 passed, 6 warnings`. | Do not run destructive live UAT unless separately approved with a disposable/synthetic fixture. |

## 5. Original-audit automated and safe deployed checks completed

The counts and statuses in this subsection belong to the original audit baseline at `138812aab616baf8a384d79947e97e29e9f86495`.

| Check | Result | Evidence |
|---|---|---|
| Git prerequisite gate | PASS | Started from clean `main`; `main...origin/main` was `0 0`; audited commit `138812aab616baf8a384d79947e97e29e9f86495`. |
| `python -m compileall app tests` | PASS | Completed without errors. |
| Required auth test group | PASS | `73 passed`. |
| Required Non-NHG resident suite | PASS | `70 passed`. |
| Additional directly relevant backend suite | PASS | Exact 19-module command below: `254 passed`; authorization, resident/external workflows, events, uploads, export, and migration contracts. |
| Secretary event suite | PASS | `tests/test_secretary_events.py`: `33 passed`. |
| Safe error/config/health suites | PASS | Exact three-module command below: `20 passed`. |
| Guarded PostgreSQL force-delete suite | BLOCKED | All five cases stopped at the repository guard because the configured database was not a named disposable test database; no connection/mutation proceeded. |
| `alembic heads` | PASS | `20260721_000022 (head)`. |
| `npm run lint` | PASS | No lint errors. |
| `npm run typecheck` | PASS | No TypeScript errors. |
| `npm run build` | PASS | Production bundle created; existing large-chunk warning only. |
| `npm test` | PASS | `51 passed`. |
| Fresh bundle backend-secret-name scan | PASS | No match; only names were searched, never values. |
| Frontend direct Supabase table/RPC scan | PASS | No `supabase.from(...)` or `supabase.rpc(...)` match. |
| Deployed backend health | PASS | `200`, body `{"status":"ok"}`. |
| Deployed backend security headers | PASS | HSTS, frame denial, nosniff, referrer policy, and CSP present. |

At the originally audited commit, green automated suites did not override HC-AUTHZ-001 or HC-FUNCTIONAL-001: those paths lacked adequate regression coverage and were separately reproduced with synthetic fixtures.

Reproducible backend commands (run from `backend/`):

```powershell
python -m compileall app tests
pytest tests/test_auth_modes.py tests/test_auth_supabase.py tests/test_auth_resident.py tests/test_external_auth.py -q --tb=short
pytest tests/test_admin_secretary_events_postgres.py -q --tb=short
pytest tests/test_external_residents.py -q --tb=short
pytest tests/test_auth_identity_dependency.py tests/test_auth_staff_actor_name.py tests/test_admin_staff_accounts.py tests/test_admin_secretary_events.py tests/test_admin_resident_submissions.py tests/test_admin_resident_attendance.py tests/test_admin_external_attendance.py tests/test_programme_teaching_events.py tests/test_resident_events.py tests/test_resident_attendance.py tests/test_resident_adhoc.py tests/test_external_attendance.py tests/test_external_scheduled_events.py tests/test_external_attendance_history.py tests/test_external_adhoc.py tests/test_upload_plumbing.py tests/test_admin_upload_output_reads.py tests/test_rls_migration.py tests/test_programme_institution_posting_map.py -q --tb=short
pytest tests/test_secretary_events.py -q --tb=short
pytest tests/test_admin_config_endpoints.py tests/test_error_responses.py tests/test_health.py -q --tb=short
```

### Post-remediation automated verification — 2026-07-22

The operator ran this verification after both fixes were merged into `main`, using disposable database `mata_phase5b_verify_71cd78fbe29b`. Results are local evidence only.

| Check | Result | Evidence |
|---|---|---|
| Clean Alembic migration from baseline | PASS — local disposable PostgreSQL | Migrated through `20260721_000022 (head)` without a migration failure. |
| Revision confirmation | PASS — local disposable PostgreSQL | `alembic current` and `alembic heads` both reported `20260721_000022 (head)`. |
| `python -m compileall app tests` | PASS — local automated | Compilation completed before the focused tests. |
| Focused attendance/PostgreSQL command | PASS — local disposable PostgreSQL | `66 passed, 1 warning in 4.78s`. |
| Full backend suite | PASS — local disposable PostgreSQL | `1009 passed, 6 warnings in 224.91s`. |
| Native overlap concurrency | PASS — local disposable PostgreSQL | Two concurrent same-resident/date overlapping submissions could not both succeed; one submitted row remained. |
| Five force-delete PostgreSQL cases | PASS — local disposable PostgreSQL | Native-only, external-only, mixed native/external, stale expected counts, and injected transactional failure all passed. |
| Temporary database cleanup | PASS — local disposable PostgreSQL | The disposable database was successfully dropped after verification. |
| Live-system access | NOT APPLICABLE | No live database, Supabase project, Vercel deployment, account, or deployed API was accessed or mutated. |

All six full-suite warnings, and the single focused warning, were the existing non-blocking Alembic configuration deprecation: `No path_separator found in configuration; falling back to legacy prepend_sys_path splitting.` The warning is unrelated to either remediation.

This run confirms the migration chain and PostgreSQL integration behavior. It is not proof of the deployed Supabase UAT revision, project selection, schema, seed state, grants, RLS, environment, accounts, or Vercel deployment state.

## 6. Detailed evidence by audit area

### 6.1 Deployment protection

Overall status: `MANUAL VERIFICATION REQUIRED`.

- `frontend/vercel.json` and `backend/vercel.json` contain routing/header configuration but no evidence of Vercel Deployment Protection, SSO, password protection, or an IP allowlist.
- Normal MATA login/route guards are application authentication, not deployment protection.
- The in-app browser had pre-existing authenticated state and loaded MATA content directly. That cannot be used as an unauthenticated/private-session result.
- A cookie-free request was intercepted by a Vercel bot challenge (`429`), which neither proves nor disproves the required stakeholder access gate.
- The deployed backend did reject a protected token-free request with `401` and returned no app identity data.

Required manual steps:

1. Open the frontend URL in a new private/incognito browser that is not signed into Vercel and has no MATA state.
2. Confirm the approved deployment access gate appears before any MATA application content.
3. Attempt a failed gate login and confirm no MATA data, app shell, or protected asset content is shown.
4. Review the Vercel protection method and stakeholder access list; record only the method, approved group, operator, and date.
5. Repeat from a second non-authorized session or network if IP/SSO policy is used.

### 6.2 Backend production environment

Overall status: `MANUAL VERIFICATION REQUIRED`.

Repository settings support `ENV`, `AUTH_MODE`, database URLs, Supabase URL/JWKS/issuer/audience/publishable/service-role variables, the resident session secret, and CORS. That does not prove deployed values. The production middleware rejects raw headers when `ENV=production` **or** `AUTH_MODE=supabase`, so the deployed `401` cannot prove both required settings.

The operator must verify, without copying values:

- `ENV=production`
- `AUTH_MODE=supabase`
- presence of `DATABASE_URL`
- presence of `SYNC_DATABASE_URL` where migration tooling uses it
- presence of `SUPABASE_URL`
- presence of `SUPABASE_JWKS_URL` or `SUPABASE_JWT_ISSUER`
- configured `SUPABASE_JWT_AUDIENCE`
- presence of `SUPABASE_PUBLISHABLE_KEY` or the supported fallback where needed
- presence of `SUPABASE_SERVICE_ROLE_KEY`
- presence of `MATA_RESIDENT_SESSION_SECRET`
- presence of exact `CORS_ORIGINS`

### 6.3 Exact CORS allowlist

Overall status: `MANUAL VERIFICATION REQUIRED` for exact deployed allowlist membership. The four recorded runtime probes passed.

| Tested origin | HTTP status | `Access-Control-Allow-Origin` | Result |
|---|---:|---|---|
| `https://mata-aine.vercel.app` | 200 | Exact same origin | PASS |
| `https://unapproved.example` | 400 | Absent | PASS |
| `http://localhost:5173` | 400 | Absent | PASS |
| `https://mata-aine-git-preview.vercel.app` (synthetic representative preview hostname) | 400 | Absent | PASS |

The approved response also returned `Access-Control-Allow-Credentials: true`, matching the current backend contract. Repository configuration rejects wildcard CORS in production. No token was sent. Because the deployed environment list itself was not inspected, these origin probes do not prove that no additional preview or unrelated origin is configured.

### 6.4 Frontend/backend secret separation

Repository/build status: `PASS`. Deployed environment status: `MANUAL VERIFICATION REQUIRED`.

- Frontend configuration uses browser-safe `VITE_AUTH_MODE`, `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and the supported public anon-key fallback.
- Frontend Supabase usage is Auth-only.
- Backend-only names appeared only in backend/local/CI placeholders and documentation warnings, not frontend code or build inputs.
- Forbidden `VITE_*` backend-secret variants were absent from application/config assignments.
- A fresh local production build contained none of the searched backend-only secret names.
- Deployed frontend Vercel environment names and deployed bundle contents still require manual review. Any `VITE_DEMO_*` values must also be confirmed absent or strictly synthetic because every `VITE_*` value is public.

### 6.5 Master Admin and role-scope enforcement

Historical status at the audited commit: `Historical FAIL`.

Supported controls:

- Master Admin is explicit through DB-owned `admin_level = master`; null/empty scope does not infer master.
- Master-only staff-account and force-delete dependencies exist and their local tests pass.
- Programme event, native attendance, submission, and external-attendance read tests enforce programme scope.
- Secretary services receive the verified posting; resident/external services receive the authenticated subject ID.

Historical blocking counter-evidence, preserved as the original finding:

- At the audited commit, `require_admin_context` accepted an admin identity with an empty normalized programme scope.
- TTF upload explicitly enforced programme scope.
- RDB, FormF1, and Public Holidays uploads did not require a non-empty scope or explicit Master Admin.
- A synthetic blank/whitespace-scope probe returned `200` for all three global mutation routes.

Post-remediation status: `Resolved in merged code` / `PASS — local automated`.

- RDB, FormF1, and Public Holidays / AY Dates uploads now depend on explicit Master Admin authority and return `403` to a Programme PC regardless of blank, null, empty, whitespace-only, or non-empty programme scope. Middleware-backed requests use persisted/verified admin level; the non-production stub/demo shim is not a deployed authorization source.
- TTF retains the intended dual authorization rule: Master Admin may upload for any programme; any non-master admin must match a normalized programme against normalized non-empty scope. Under the provisioning contract, that non-master scoped admin tier is Programme PC.
- The historical blank-scope reproduction changed from `200/200/200` to `403/403/403`, with regression coverage confirming no upload parser runs for the denied requests.
- Authorization fix `e0efb0d` was merged by `9f10d58`. Operator-reported pre-merge branch verification included 44 upload tests, 46 auth tests, 127 affected parser/rate-limit tests, and a full backend result of `992 passed, 5 warnings`.

Live account-based Master Admin, Programme PC, Secretary, resident, and out-of-scope UUID checks remain `BLOCKED — deployed fixture unavailable`. No deployed Programme PC or Master Admin account was tested, so the local result is not proof of deployed account behavior.

### 6.6 Raw-header rejection

- Raw identity headers alone against deployed `/api/v1/auth/me`: `PASS` (`401`, controlled unauthorized response, no role/user or internal-error markers).
- Conflicting raw headers against a valid deployed bearer identity: `BLOCKED` because no approved valid bearer fixture was available.
- Repository tests directly cover production/Supabase raw-header rejection, valid-bearer precedence, and rejection of authorization derived from Supabase user metadata.

### 6.7 Supabase migration and schema verification

Historical Supabase-target status at the audited commit: `BLOCKED — wrong database target`.

The repository Alembic history is linear and the expected head is `20260721_000022`. The effective backend target resolved to local `localhost/mata_db`, not an approved Supabase project. Per the stop condition, `alembic current` and all database SQL were skipped, and environment variables were not changed.

Committed migration evidence supports the expected shape only:

- `external_residents`, `external_resident_postings`, and `external_attendance_records`: baseline external flow migration.
- `external_resident_postings.programme_code`: revision `20260721_000022`.
- nullable unique `users.supabase_user_id`: revision `20260702_000012`.
- `teaching_events.created_for_programme_code`: revision `20260626_000009`.
- `programme_institution_posting_map`: revision `20260717_000019`.
- exact intended TTSH state 24 active / 4 inactive / 0 pending with no active null posting: revision `20260721_000021`.
- migration history contains no `programmes.compliance_variant` or `attendance_records.session_type_id` addition.

These are not deployed PASS claims.

Post-remediation local status: `PASS — local disposable PostgreSQL`. The operator subsequently migrated a clean disposable PostgreSQL database through `20260721_000022 (head)` and confirmed the same revision with both `alembic current` and `alembic heads`. This closes the earlier local PostgreSQL integration evidence gap only. The approved Supabase UAT project selection, deployed revision, schema, seed state, grants, RLS, and Data API boundary remain `BLOCKED` or `MANUAL VERIFICATION REQUIRED`; the local run is not proof of deployed Supabase/Vercel state.

### 6.8 Supabase Data API exposure

Overall status: `MANUAL VERIFICATION REQUIRED`.

- Frontend source has no direct MATA application-table `.from(...)`, `.rpc(...)`, REST, GraphQL, Storage, or Functions calls.
- MATA application data is designed to go through FastAPI.
- The committed RLS migration covers selected reference tables, not all sensitive application tables; the later mapping table migration does not itself enable RLS. Deployed grants/exposed schemas remain decisive.
- Browser Network inspection was not available in a clean unauthenticated session, Supabase settings were not accessible, and no operator-approved browser-public key was supplied for a direct denial check.

If a public-key request returns any readable sensitive rows, stakeholder UAT is immediately `FAIL — STAKEHOLDER UAT NO-GO`. Do not change RLS or grants in this audit task.

### 6.9 Functional workflow evidence

The following table preserves the original audit evidence. It is local/synthetic unless explicitly labelled deployed.

| Workflow group | Status | Evidence |
|---|---|---|
| Backend health | PASS | Deployed `200` with non-sensitive `status=ok`. |
| Master Admin, Programme PC, Secretary, NHG Resident, Non-NHG Resident deployed login | BLOCKED | Approved UAT accounts were unavailable. |
| Registration options: 24 active TTSH, four omissions, no posting code, GERI mapping | PASS | `test_external_residents.py` and `test_programme_institution_posting_map.py` passed. Deployed data remains blocked by HC-MIGRATION-001. |
| External schedule programme provenance and native-table isolation | PASS | `test_external_residents.py`, `test_external_attendance.py`, and `test_external_adhoc.py` passed. |
| Eligible native/external Secretary and Programme PC event visibility | PASS | `test_resident_events.py`, `test_external_attendance.py`, and `test_external_scheduled_events.py` passed. |
| Another programme's PC event denied to Non-NHG Resident | PASS | The programme-provenance cases in `test_external_attendance.py` passed. |
| Native attendance writes native-only; external attendance writes external-only | PASS | `test_resident_attendance.py`, `test_external_attendance.py`, and `test_external_adhoc.py` passed. |
| Same-event duplicate submission | PASS | Duplicate cases in `test_resident_attendance.py` and `test_external_attendance.py` passed. |
| Distinct-event overlap | Historical FAIL | External path rejected it; the native path at the audited commit accepted the reproduced overlapping distinct event. |
| Programme PC native attendance overview, history read-only, external separation, out-of-scope UUID, source labels | PASS | `test_admin_resident_attendance.py`, `test_admin_resident_submissions.py`, and `test_admin_external_attendance.py` passed. |
| Ordinary Secretary/PC delete blocked with attendance | PASS | `test_secretary_events.py` and `test_programme_teaching_events.py` passed. |
| Force-delete split counts, exact `DELETE`, reason, and master-only route | PASS | `test_admin_secretary_events.py` passed. |
| Mixed-attendance force-delete atomicity, removal, audit, unrelated-event preservation | BLOCKED | Guarded PostgreSQL suite refused the non-disposable target; code support was not execution evidence at the audited commit. |
| Invalid extension and oversized upload rejection | PASS | The named validation cases in `test_upload_plumbing.py` passed. |
| Public-holiday event/ad-hoc creation block | PASS | `test_secretary_events.py`, `test_programme_teaching_events.py`, `test_resident_adhoc.py`, and `test_external_adhoc.py` passed. |
| Formula-leading export content neutralized | PASS | `test_admin_external_attendance.py` and the frontend `npm test` contract suite passed. |
| Deployed uploads and synthetic stakeholder workflow | BLOCKED | No approved deployed fixture/account was available; no destructive test was attempted. |

### 6.10 Post-remediation functional evidence

| Contract | Current local status | Evidence |
|---|---|---|
| Native distinct-event overlap | Resolved in merged code / PASS — local automated | The same resident/date submitted-only conflict query excludes the same event ID and rejects half-open interval overlap while preserving the earlier accepted attendance. |
| Same-event duplicate and adjacency | PASS — local automated | Same-event uniqueness remains separate; both endpoint-touching adjacency directions remain allowed. |
| Attendance status scope | PASS — local automated | Only native attendance with `status = 'submitted'` blocks a later distinct overlap. Removed and legacy flagged rows retain their existing inactive behavior. |
| Request-order and batch atomicity | PASS — local automated | Later overlapping events in one request are rejected before writes; request order and the earlier accepted record are preserved. |
| Scheduled and native ad-hoc paths | PASS — local automated | Both paths use the same native overlap guard before insertion. |
| Same-resident/date concurrency | PASS — local disposable PostgreSQL | A deterministic transaction-scoped advisory lock ensures two overlapping concurrent submissions cannot both succeed. |
| External attendance path | PASS — local automated | External storage and overlap behavior remain separate and unchanged by the native remediation. |
| Native-only force-delete | PASS — local disposable PostgreSQL | Linked native attendance and the selected Secretary event were removed with audit evidence. |
| External-only force-delete | PASS — local disposable PostgreSQL | Linked external attendance and the selected Programme PC event were removed with audit evidence. |
| Mixed native/external force-delete | PASS — local disposable PostgreSQL | Both attendance types and the selected event were removed atomically; unrelated events, series siblings, and their attendance were preserved. |
| Stale expected force-delete impact | PASS — local disposable PostgreSQL | Returned conflict before deletion and preserved the event, both attendance rows, and audit state. |
| Injected transactional failure | PASS — local disposable PostgreSQL | Rolled back the event, native attendance, external attendance, and audit effects. |

The native conflict query is scoped to one resident and event date, filters existing attendance to `status = 'submitted'`, and excludes the same `teaching_event_id` so duplicate handling remains distinct. For normal ended events, its interval predicate is half-open (`left_start < right_end` and `right_start < left_end`), so adjacent sessions remain valid; equal starts are always overlapping, and a missing end is normalized to its start. Scheduled batches prevalidate request-order overlaps before mutation, while native ad-hoc uses the same guard. Transaction-scoped PostgreSQL advisory locks serialize each resident/date key. The external branch remains on its separate tables and behavior.

Overlap fix `a0c4bd1` was merged by `eaa3d7f`. Original source hash `94bc0c4` is not an ancestor of current `main`, but its stable patch ID matches `a0c4bd1`. Operator-reported pre-merge branch verification included 156 focused tests, 2 exact reproductions, 1 PostgreSQL concurrency test, and a full backend result of `993 passed, 6 warnings`.

The five force-delete cases passed only in the disposable PostgreSQL verification. No live Supabase database or deployed API was mutated, and destructive live UAT must not be attempted without separate approval and a safe synthetic fixture.

### 6.11 Historical pre-remediation reproduction commands

Both commands below were executed against the originally audited commit and are preserved as proof of the historical failures. They use only synthetic local fixtures and mocks and did not connect to a database or deployment. They are not current post-remediation verification instructions.

Blank/whitespace programme-scope upload probe:

```powershell
python -B -c "from types import SimpleNamespace; from unittest.mock import AsyncMock; from uuid import uuid4; from tests.test_upload_plumbing import _build_client; from app.routers import admin; from app.services import rdb_parser; from app.services.parser_common import ParserResult; admin.validate_upload_payload=lambda **kwargs: SimpleNamespace(file_bytes=kwargs['file_bytes'], original_filename=kwargs['filename']); rdb_parser.parse_rdb_upload=AsyncMock(return_value=ParserResult(upload_type='rdb')); admin.parse_formf1_upload=AsyncMock(return_value=ParserResult(upload_type='form_f1')); admin.parse_public_holiday_upload=AsyncMock(return_value=ParserResult(upload_type='public_holidays')); client=_build_client(); headers={'X-User-Role':'admin','X-User-Id':str(uuid4()),'X-User-Programme':' , '}; period=str(uuid4()); mk=lambda name:(name,b'synthetic','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'); responses={'rdb':client.post('/admin/upload/rdb',headers=headers,data={'reporting_period_id':period},files={'file':mk('rdb.xlsx')}),'form_f1':client.post('/admin/upload/form-f1',headers=headers,data={'reporting_period_id':period},files={'file':mk('formf1.xlsx')}),'public_holidays':client.post('/admin/upload/public-holidays',headers=headers,files={'file':mk('calendar.xlsx')})}; print({name:response.status_code for name,response in responses.items()})"
```

Observed: `{'rdb': 200, 'form_f1': 200, 'public_holidays': 200}`.

Native distinct-event overlap probe:

```powershell
python -B -c "import asyncio; from uuid import UUID, uuid4; from tests.resident_fakes import FakeResidentSession; from app.services import resident_submission; db=FakeResidentSession(); existing=next(row for row in db.events if row['id']==db.second_event_id); new_event=db._event(str(uuid4()), existing['posting_code'], existing['teaching_name'], existing['event_date'], start_time=existing['start_time']); db.events.append(new_event); before=len(db.attendance); result=asyncio.run(resident_submission.submit_attendance(db, resident_id=UUID(db.resident_id), event_ids=[UUID(new_event['id'])], today=db.today)); print({'accepted': result['submitted'], 'native_rows_added': len(db.attendance)-before, 'same_interval_as_existing': (new_event['event_date'], new_event['start_time'], new_event['end_time']) == (existing['event_date'], existing['start_time'], existing['end_time'])})"
```

Observed: `{'accepted': 1, 'native_rows_added': 1, 'same_interval_as_existing': True}`.

### 6.12 Post-remediation maintained-test verification

The focused post-merge command used maintained native scheduled, native ad-hoc, and PostgreSQL concurrency tests:

```powershell
python -m compileall app tests
pytest tests/test_resident_attendance.py tests/test_resident_adhoc.py tests/test_resident_attendance_postgres.py -q --tb=short
```

Result: `66 passed, 1 warning in 4.78s`. The full backend result was `1009 passed, 6 warnings in 224.91s`. The concurrency case in `tests/test_resident_attendance_postgres.py` and the five force-delete cases in `tests/test_admin_secretary_events_postgres.py` passed against the disposable PostgreSQL database. These are local-only results and not proof of a deployed UAT workflow.

## 7. Remaining manual checks

1. Verify Vercel deployment protection in an unauthenticated private/incognito session and review stakeholder access membership.
2. Verify deployed backend `ENV=production`, `AUTH_MODE=supabase`, and required backend-only variable-name presence without copying values.
3. Review exact deployed `CORS_ORIGINS` membership, even though the recorded runtime probes passed.
4. Verify deployed frontend/backend environment separation and scan the deployed frontend artifact for backend-only secret names.
5. Confirm the intended Supabase UAT project and run the approved revision, schema, and seed-state checks; do not treat the local disposable migration as Supabase evidence.
6. Complete first Master Admin bootstrap and the deployed Master Admin/Programme PC/Secretary/native/external account-role matrix with approved fixtures.
7. Inspect browser Network plus Supabase exposed-schema, grants, RLS, and Data API settings; run the approved public-key sensitive-table denial check.
8. Run valid-bearer conflicting-header precedence against a synthetic deployed account.
9. Run the remaining deployed upload, login, account, event, submission, and export workflows with approved synthetic fixtures.

Do not run destructive force-delete against a live or shared UAT database unless separately approved. The local disposable PostgreSQL suite already supplies the non-live integration evidence.

## 8. Remaining NO-GO evidence gaps

- Vercel deployment protection and stakeholder access membership are not verified.
- Deployed backend `ENV=production` and `AUTH_MODE=supabase` are not safely verified.
- Exact deployed CORS membership has not been manually reviewed.
- Deployed frontend/backend secret and environment separation has not been manually confirmed.
- The approved Supabase UAT project, migration revision, schema, and seed state are not verified.
- First Master Admin bootstrap and the deployed account-role workflow matrix are not verified.
- Supabase Data API, grants, RLS, and exposed-schema boundaries are not verified.
- The deployed valid-bearer conflicting-header case has not been executed.
- The deployed role and functional workflow matrix remains incomplete.

HC-AUTHZ-001 and HC-FUNCTIONAL-001 are no longer open code blockers. Their historical failures remain part of the audit record, while their current status is resolved in merged code with local automated/PostgreSQL evidence.

## 9. Follow-up actions

1. Complete the Vercel access-protection, deployed environment, exact CORS, and deployed secret-separation reviews with non-secret evidence.
2. Complete the approved Supabase revision/schema/seed and Data API/grants/exposed-schema checks against the confirmed UAT project.
3. Complete first Master Admin bootstrap, the deployed role/account matrix, and the valid-bearer conflicting-header test with approved synthetic accounts.
4. Execute the remaining non-destructive deployed workflow matrix with approved synthetic fixtures; require separate approval before any destructive live UAT action.
5. Re-audit and return a GO verdict only when every GO criterion has direct evidence.

## 10. Explicit deferrals

- Phase 6 compliance implementation.
- Deployment or live-system confirmation of the two merged remediations; this branch records documentation evidence only.
- RLS/grant changes and Data API configuration changes.
- Environment, CORS, authentication, deployment protection, DNS, or staff-account changes.
- Database migrations or live data changes.
- Full cookie/BFF/CSRF session transport implementation.
- Final close/freeze, snapshots, clawback, and historical migration.

## 11. Files changed

- `docs/5b_h_c_deployment_security_audit.md`
- `docs/5b_h_vercel_supabase_uat_smoke.md`

No application, migration, deployment configuration, environment, or test file was changed.

## 12. Review result

`PASS` — the complete documentation diff was reviewed independently and by the audit operator. No secrets, tokens, connection strings, Authorization headers, personal data, unsupported deployed PASS claims, application changes, live-system mutations, or Phase 6 implementation were found. Only the two intended documentation files changed, and `git diff --check` passed.
