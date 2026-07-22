# 5B-H-C Deployment Security and Functional UAT Audit

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

## 2. Evidence-status definitions

- `PASS` — directly verified through reproducible evidence.
- `FAIL` — direct evidence shows the requirement is not met.
- `MANUAL VERIFICATION REQUIRED` — repository code and the available command environment cannot verify the live requirement.
- `BLOCKED` — an approved prerequisite, account, fixture, URL capability, permission, or correct database target was unavailable.
- `NOT APPLICABLE` — the requirement genuinely does not apply, with an explanation.

Repository support is not treated as proof of deployed configuration. A committed migration is not treated as proof that Supabase is at head. Source absence of direct Supabase table calls is not treated as proof that the public Data API cannot read tables.

## 3. Executive verdict

`NO-GO — BLOCKERS MUST BE FIXED`

Two High findings were reproduced with synthetic local fixtures:

1. A Programme PC with blank/whitespace-only programme scope can reach the global RDB, FormF1, and Public Holidays upload mutations.
2. The native NHG Resident attendance path accepts a distinct event whose interval overlaps an earlier accepted event.

These violate the confirmed role-scope and distinct-event-overlap contracts. In addition, deployment protection, backend environment values, the Supabase database revision/schema, the live Data API boundary, deployed account workflows, and the valid-bearer conflicting-header case remain unverified or blocked. Phase 6 compliance must not begin on this baseline.

## 4. Findings table

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

## 5. Automated and safe deployed checks completed

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

Green automated suites do not override HC-AUTHZ-001 or HC-FUNCTIONAL-001: those paths lacked adequate regression coverage and were separately reproduced with synthetic fixtures.

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

Overall status: `FAIL`.

Supported controls:

- Master Admin is explicit through DB-owned `admin_level = master`; null/empty scope does not infer master.
- Master-only staff-account and force-delete dependencies exist and their local tests pass.
- Programme event, native attendance, submission, and external-attendance read tests enforce programme scope.
- Secretary services receive the verified posting; resident/external services receive the authenticated subject ID.

Blocking counter-evidence:

- `require_admin_context` accepts an admin identity with an empty normalized programme scope.
- TTF upload explicitly enforces programme scope.
- RDB, FormF1, and Public Holidays uploads do not require a non-empty scope or explicit Master Admin.
- A synthetic blank/whitespace-scope probe returned `200` for all three global mutation routes.

Live account-based Master Admin, Programme PC, Secretary, resident, and out-of-scope UUID checks are `BLOCKED` until approved fixtures are available and the High scope finding is resolved.

### 6.6 Raw-header rejection

- Raw identity headers alone against deployed `/api/v1/auth/me`: `PASS` (`401`, controlled unauthorized response, no role/user or internal-error markers).
- Conflicting raw headers against a valid deployed bearer identity: `BLOCKED` because no approved valid bearer fixture was available.
- Repository tests directly cover production/Supabase raw-header rejection, valid-bearer precedence, and rejection of authorization derived from Supabase user metadata.

### 6.7 Supabase migration and schema verification

Overall status: `BLOCKED — wrong database target`.

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

### 6.8 Supabase Data API exposure

Overall status: `MANUAL VERIFICATION REQUIRED`.

- Frontend source has no direct MATA application-table `.from(...)`, `.rpc(...)`, REST, GraphQL, Storage, or Functions calls.
- MATA application data is designed to go through FastAPI.
- The committed RLS migration covers selected reference tables, not all sensitive application tables; the later mapping table migration does not itself enable RLS. Deployed grants/exposed schemas remain decisive.
- Browser Network inspection was not available in a clean unauthenticated session, Supabase settings were not accessible, and no operator-approved browser-public key was supplied for a direct denial check.

If a public-key request returns any readable sensitive rows, stakeholder UAT is immediately `FAIL — STAKEHOLDER UAT NO-GO`. Do not change RLS or grants in this audit task.

### 6.9 Functional workflow evidence

The following evidence is local/synthetic unless explicitly labelled deployed.

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
| Distinct-event overlap | FAIL | External path rejects it; native path accepted the reproduced overlapping distinct event. |
| Programme PC native attendance overview, history read-only, external separation, out-of-scope UUID, source labels | PASS | `test_admin_resident_attendance.py`, `test_admin_resident_submissions.py`, and `test_admin_external_attendance.py` passed. |
| Ordinary Secretary/PC delete blocked with attendance | PASS | `test_secretary_events.py` and `test_programme_teaching_events.py` passed. |
| Force-delete split counts, exact `DELETE`, reason, and master-only route | PASS | `test_admin_secretary_events.py` passed. |
| Mixed-attendance force-delete atomicity, removal, audit, unrelated-event preservation | BLOCKED | Guarded PostgreSQL suite refused the non-disposable target; code support is not execution evidence. |
| Invalid extension and oversized upload rejection | PASS | The named validation cases in `test_upload_plumbing.py` passed. |
| Public-holiday event/ad-hoc creation block | PASS | `test_secretary_events.py`, `test_programme_teaching_events.py`, `test_resident_adhoc.py`, and `test_external_adhoc.py` passed. |
| Formula-leading export content neutralized | PASS | `test_admin_external_attendance.py` and the frontend `npm test` contract suite passed. |
| Deployed uploads and synthetic stakeholder workflow | BLOCKED | No approved deployed fixture/account was available; no destructive test was attempted. |

### 6.10 Reproduction commands for High findings

Both commands below use only synthetic local fixtures and mocks. They do not connect to a database or deployment.

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

## 7. Remaining manual checks

1. Verify Vercel deployment protection in an unauthenticated private/incognito session and review stakeholder access membership.
2. Verify deployed backend `ENV=production`, `AUTH_MODE=supabase`, and required backend-only variable-name presence without copying values.
3. Verify deployed frontend has public variables only and scan the deployed artifact for backend-only names.
4. Confirm the deployed frontend and backend revisions correspond to the audited commit or record their actual safe commit labels.
5. Run valid-bearer conflicting-header precedence against a synthetic deployed account.
6. Confirm the intended Supabase project label, correct the terminal target under operator control, and run `alembic current` plus the read-only schema/count SQL.
7. Inspect browser Network and Supabase exposed-schema/grants settings; run the approved public-key sensitive-table denial check.
8. After the High findings are fixed, run the full Master Admin/PC/Secretary/native/external account and out-of-scope UUID matrix.
9. Run deployed upload/event/submission/export workflows with approved synthetic fixtures.
10. Run the guarded PostgreSQL force-delete suite against the repository's named disposable database.

## 8. Blockers

- High: blank-scope Programme PC reaches global RDB, FormF1, and Public Holidays upload mutations.
- High: native distinct-event overlap is accepted.
- Supabase migration/schema verification is blocked by the wrong effective database target.
- Deployed account workflows are blocked by unavailable approved accounts/fixtures.
- Deployment protection, deployed env separation, and Data API exposure still require manual evidence.

## 9. Follow-up actions

1. Open a separate, reviewed application-code task for HC-AUTHZ-001. Confirm the intended authority for global uploads, enforce it server-side, and add null/empty/blank scope tests.
2. Open a separate application-code task for HC-FUNCTIONAL-001 to enforce native distinct-event overlap rejection and add a regression test matching the external path contract.
3. Re-run all targeted tests plus the guarded PostgreSQL suite after those fixes.
4. Complete the Vercel/Supabase manual evidence checklist with a named operator, safe project labels, dates, and non-secret artifacts.
5. Re-audit and return a GO verdict only when every GO criterion has direct evidence.

## 10. Explicit deferrals

- Phase 6 compliance implementation.
- Application-code fixes for the two High findings in this branch.
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
