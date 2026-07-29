# 5B-H-A Vercel/Supabase UAT Security Audit

> **Current contract:** `docs/security.md`. This file is retained as dated UAT
> audit evidence and does not override the current security contract.

Status: 5B-H-A audit complete; 5B-H-B code fixes verified
Last updated: 2026-07-06

## 1. Executive Summary

UAT readiness verdict: CONDITIONAL GO.

No critical or high local-code finding was found that proves auth bypass, committed backend-secret exposure, or direct frontend Supabase app-table access. The current implementation already has the major 5B-G guardrails: production/Supabase mode rejects raw `X-User-*` identity headers, staff Supabase JWTs map through `users.supabase_user_id`, staff role/scope comes from DB-owned `users` rows, and NHG/Non-NHG Resident sessions are backend-signed MATA resident tokens.

Top blockers identified before stakeholder UAT:

- H-UPLOAD-001: fixed in 5B-H-B with per-file byte-size validation after upload read and before workbook/CSV parsing.
- H-EXPORT-001: fixed in 5B-H-B with formula-prefix sanitization for browser-generated secretary CSV cells.
- H-RLSBOUNDARY-001: manually verify the actual Supabase UAT project does not expose sensitive MATA app tables to direct browser/Data API access.
- H-DEPLOY-001: manually enable and verify Vercel deployment protection, exact CORS origins, UAT `ENV=production` plus `AUTH_MODE=supabase`, first Master Admin bootstrap, and migration/staging DB smoke.

Stakeholder UAT should still wait until 5B-H-C smoke evidence confirms the deployment controls.

## 2. Scope Reviewed

This is a targeted UAT security audit for a protected Vercel/Supabase stakeholder deployment. It is not a full penetration test, not a full RLS implementation, not a Supabase project configuration inspection, and not an implementation of Phase 6 compliance.

Source-of-truth docs reviewed:

- `AGENTS.md`
- `docs/00_project_context.md`
- `docs/auth-account-contract.md`
- `docs/api.md`
- `docs/schema.md`
- `docs/business-logic.md`
- `docs/99_decision_log_and_gap_audit.md`
- `docs/5b_g_supabase_readiness_audit.md`
- `docs/5b_g_staff_bootstrap_runbook.md`
- `docs/5b_g_rls_grants_matrix.md`
- `docs/5b_g_supabase_migration_smoke_plan.md`
- `docs/5b_g_service_role_access_review.md`
- `docs/5b_h_vercel_uat_security_plan.md`

Implementation/config files reviewed:

- Backend auth/config/middleware: `backend/app/config.py`, `backend/app/main.py`, `backend/app/middleware/auth_stub.py`, `backend/app/middleware/rate_limit.py`, `backend/app/middleware/security.py`, `backend/app/middleware/upload_guard.py`, `backend/app/middleware/errors.py`, `backend/app/dependencies/auth.py`, `backend/app/dependencies/staff_actor.py`
- Backend routers/services: `backend/app/routers/auth.py`, `backend/app/routers/admin.py`, `backend/app/routers/resident.py`, `backend/app/routers/external_residents.py`, `backend/app/routers/secretary.py`, `backend/app/services/auth.py`, `backend/app/services/mata_resident_token.py`, `backend/app/services/supabase_jwt.py`, `backend/app/services/supabase_admin.py`, `backend/app/services/external_residents.py`, `backend/app/services/resident_submission.py`, `backend/app/services/admin_external_attendance.py`, `backend/app/services/audit.py`, `backend/app/services/parser_common.py`, `backend/app/services/upload_validation.py`, plus targeted parser import/readability paths
- Frontend auth/env/session: `frontend/src/api/http.ts`, `frontend/src/api/auth.ts`, `frontend/src/api/authHeaders.ts`, `frontend/src/api/authSessionStore.ts`, `frontend/src/api/supabaseClient.ts`, `frontend/src/config/frontendConfig.ts`, `frontend/src/types/auth.ts`, `frontend/src/App.tsx`
- Frontend export surface: `frontend/src/pages/secretary/SecretaryTeachingSchedulePage.tsx`
- Env/deployment/dependency files: `.env.example`, `README.md`, `docs/dev_setup.md`, `frontend/README.md`, `docker-compose.yml`, `frontend/Dockerfile`, `backend/Dockerfile`, `.github/workflows/backend-ci.yml`, `backend/requirements.txt`, `frontend/package.json`, `frontend/package-lock.json`

## 3. Threat Model

Prioritized attacker and failure scenarios:

- Anonymous internet user reaches an unprotected Vercel UAT URL.
- Stakeholder testing URL leaks outside the intended group.
- Browser-visible Supabase or MATA bearer token is stolen through XSS, compromised browser, copied logs, or shared machine state.
- Caller spoofs raw `X-User-*` headers to become admin, secretary, NHG Resident, or Non-NHG Resident.
- CORS allows unapproved origins to call the API with credentials or bearer tokens.
- Backend-only secrets are accidentally placed in Vercel frontend `VITE_*` variables or frontend Docker build args.
- Browser code queries sensitive Supabase app tables directly without RLS/grants coverage.
- Master Admin, Programme PC, secretary, NHG Resident, or Non-NHG Resident attempts IDOR or role/scope escalation.
- Non-NHG attendance is accidentally joined into NHG compliance/report paths.
- Uploaded workbooks are oversized, malformed, password-protected, or resource-exhausting XLSX/XML payloads.
- Exported CSV/XLSX cells trigger spreadsheet formulas.
- API errors/logs leak SQL, filesystem paths, secrets, tokens, service-role keys, or raw internal traces.
- Login, registration, upload, submission, and export routes are abused by repeated requests.
- Manifest-visible dependency issues are missed before UAT.

## 4. Findings Table

| ID | Severity | Area | File/function/config | Risk | Evidence | Recommended fix | Proposed 5B-H-B action | Verification |
|---|---|---|---|---|---|---|---|---|
| H-AUTH-001 | Medium | Session transport | `frontend/src/api/authSessionStore.ts`, `frontend/src/api/http.ts`, `frontend/src/api/supabaseClient.ts` | Browser-visible bearer tokens can be stolen if the browser context is compromised or XSS is introduced. | MATA resident tokens are persisted in `sessionStorage`; Supabase staff sessions are fetched from the browser Supabase client and sent as `Authorization: Bearer`. | Accept only for protected stakeholder UAT with deployment protection and exact CORS; replace with cookie/BFF/CSRF plan before real production/public use. | Defer to 5B-H-D plan. | Confirm 5B-H-D document captures cookie, HttpOnly, Secure, SameSite, CSRF, logout, and rotation work. |
| H-AUTH-002 | Low | Logout/session invalidation | `frontend/src/api/supabaseClient.ts::signOutFromSupabase`, `frontend/src/api/authSessionStore.ts` | Logout clears local state and calls local Supabase sign-out, but full server-side invalidation/refresh-token strategy is not complete. | `signOut({ scope: 'local' })` and `sessionStorage.removeItem(...)` are used. | Include server-side/session invalidation in full transport-hardening plan. | Defer to 5B-H-D plan. | Plan includes logout/session invalidation acceptance criteria. |
| H-AUTHZ-001 | Low | Raw header documentation surface | `backend/app/dependencies/staff_actor.py`, `backend/app/routers/admin.py`, OpenAPI generated from `Header(...)` params | Operators may see raw header parameters in generated docs and misunderstand them as production auth. | Production/Supabase branches reject header fallback, but dependency signatures still include `X-User-*` header params for stub/demo. | Keep local/demo fallback, document production rejection in UAT smoke; clean OpenAPI later if needed. | No code fix required for protected UAT. | Supabase/production smoke must prove raw headers alone receive `401`. |
| H-AUTHZ-002 | None found | Authorization choke points | `backend/app/middleware/auth_stub.py`, `backend/app/dependencies/auth.py`, `backend/app/routers/admin.py`, `backend/app/routers/resident.py` | No local authz bypass finding from source review. | Production/Supabase mode requires bearer auth; Master Admin is `admin_level = master`; Programme PC rejects empty scope; resident/external routes use authenticated subject id. | Keep central identity dependencies as the authorization boundary. | No B action. | Existing auth tests plus UAT role smoke. |
| H-SECRETS-001 | Low | Env exposure | `.env.example`, `README.md`, `docker-compose.yml`, `frontend/Dockerfile`, `frontend/src/config/frontendConfig.ts` | Backend-only secrets could be exposed by operator mistake in Vercel frontend env. No committed secret exposure found in reviewed files. | Secret-name scans found backend-only names only in backend/env/docs placeholders; frontend config reads only `VITE_*` public values. | UAT checklist must explicitly review Vercel frontend/backend env separation. | No code fix. | Search commands plus manual Vercel env review. |
| H-CORS-001 | Medium | CORS/deployment config | `backend/app/middleware/security.py`, `.env.example`, Vercel backend env | Incorrect UAT CORS can either block UAT or overexpose API origins. | Production rejects `*` origins and uses configured allowlist; actual Vercel URL is not known locally. | Set `CORS_ORIGINS` to exact UAT frontend origin(s); smoke approved and unapproved origins. | No code fix unless smoke finds a gap. | 5B-H-C CORS/security smoke. |
| H-RATE-001 | Medium | Abuse controls | `backend/app/middleware/rate_limit.py`, `backend/app/config.py` | In-memory rate limiting is per-process and not durable across multi-worker/serverless instances. | Login, upload, resident attendance, mutations, report/export, and GET paths have limits; bucket uses verified identity when available and raw headers only in stub/demo. | Accept for protected UAT; plan Redis/platform store before real production/public use. | No B code fix required for protected UAT. | Targeted middleware tests if rate-limit code changes; UAT smoke for `429` where practical. |
| H-UPLOAD-001 | Medium | Upload size/resource control | `backend/app/middleware/upload_guard.py`, `backend/app/routers/admin.py`, `backend/app/services/parser_common.py` | A missing or misleading `Content-Length` could let an oversized file reach parser validation because routers did not recheck `len(file_bytes)` after `await file.read()`. | 5B-H-B added `max_size_bytes` validation in `validate_upload_payload`; all four admin upload routes pass `settings.max_upload_size_bytes`. | Fixed in 5B-H-B. | Complete. | `python -m pytest tests/test_upload_plumbing.py -q --tb=short`; `python -m compileall app tests`. |
| H-UPLOAD-002 | Medium | XLSX/XML hardening | `backend/app/services/parser_common.py`, `rdb_parser.py`, `ttf_parser.py`, `formf1_parser.py`, `public_holiday_parser.py` | XLSX ZIP/XML bombs or pathological workbooks can consume parser resources. | Readability check uses `openpyxl.load_workbook(read_only=True, data_only=True)` and parser routes are admin-only/rate-limited/size-limited. No deep ZIP/XML member inspection found. | Accept for protected UAT after H-UPLOAD-001; plan deeper workbook scanning/resource controls before broader public use. | Defer unless UAT fixtures expose failure. | Upload smoke with valid, invalid, unreadable, and oversize files. |
| H-EXPORT-001 | Medium | Formula injection | `backend/app/services/admin_external_attendance.py`, `frontend/src/pages/secretary/SecretaryTeachingSchedulePage.tsx` | User-controlled values starting with `=`, `+`, `-`, or `@` can execute as formulas when CSV/XLSX is opened. | 5B-H-B added secretary CSV formula-prefix sanitization before quoting; backend Non-NHG XLSX export already calls `sanitize_spreadsheet_cell`. | Fixed in 5B-H-B. | Complete. | `node --experimental-strip-types src/authSession.contract.test.ts`; `npm run typecheck`; `npm run build`. |
| H-LOG-001 | Low | Error/log redaction | `backend/app/middleware/errors.py`, `backend/app/routers/admin.py`, parser services, `backend/app/services/supabase_admin.py` | Parser/user-facing errors may include workbook-derived messages; unexpected server errors are generic. | SQLAlchemy/unhandled errors log class names and return generic 500; upload metadata strips internal keys; Supabase Admin errors are generic. Upload validation still returns controlled parser error strings. | Keep parser responses scoped to admin; avoid tokens/secrets in logs; revisit production log redaction for `Authorization`, `apikey`, cookies, DB URLs. | No B action unless new code adds logging. | UAT smoke errors should not show stack traces, SQL, paths, tokens, or service-role values. |
| H-DEPS-001 | Low | Dependency/supply chain | `backend/requirements.txt`, `frontend/package.json`, `frontend/package-lock.json` | Known vulnerabilities could exist but were not audited via networked advisory tooling in this run. | Frontend lockfile exists; backend requirements are pinned but no Python lock/audit report was found. | Run advisory scans in a networked environment; do not upgrade broadly unless high/critical issue is confirmed. | No B dependency change. | Suggested: `npm audit`; suggested Python: `pip-audit -r backend/requirements.txt` in approved environment. |
| H-RLSBOUNDARY-001 | Medium | Supabase Data API/RLS boundary | `frontend/src/api/supabaseClient.ts`, frontend `rg` search, `docs/5b_g_rls_grants_matrix.md` | Direct browser access to sensitive app tables would be a UAT blocker without RLS/grants mitigation. | Frontend search found `createClient(...)` only; no `supabase.from(...)` or `supabase.rpc(...)` app-table calls. Actual Supabase project grants/Data API exposure cannot be verified locally. | Keep app data backend-mediated; manually inspect Supabase UAT exposed schemas/grants/Data API before stakeholder access. | No local code fix. Stop before UAT if direct sensitive table access is found. | 5B-H-C Data API boundary smoke. |
| H-DEPLOY-001 | Medium | Vercel/Supabase UAT operation | Vercel project config, backend env, Supabase staging project | Local code can be ready while deployment remains unsafe or unverified. | Exact frontend/backend URLs, deployment protection method, Master Admin bootstrap execution, and migration smoke are not available locally. | Use 5B-H-C smoke checklist; do not claim deployment success until executed. | No B code fix. | UAT evidence table with operator/date/pass/fail/not-run. |

## 5. Authentication and Session Handling

Staff Supabase auth:

- `backend/app/middleware/auth_stub.py` requires bearer-token auth whenever `ENV=production` or `AUTH_MODE=supabase`.
- Supabase staff JWT verification is centralized in `backend/app/services/supabase_jwt.py`, with issuer, audience, signature/algorithm, expiry, and issued-at checks.
- Supabase Auth token `sub` maps to `users.supabase_user_id`. Role, admin level, programme scope, posting scope, active state, and staff actor metadata come from the `users` row.
- Supabase `user_metadata` is not used by reviewed frontend/backend auth paths.
- Supabase Admin service-role credentials are not used for JWT verification.

MATA resident auth:

- NHG and Non-NHG Residents do not get Supabase Auth users in Supabase mode.
- `backend/app/services/mata_resident_token.py` signs backend-owned resident tokens with issuer `mata-api`, audience `mata-resident-session`, `sub`, `role/app_role`, MCR, `iat`, and `exp`.
- Token verification requires issuer, audience, subject, expiry, issued-at, role/app_role consistency, and active DB row reload.
- Non-NHG tokens reject trusted posting/schedule/programme/admin/staff claims.

Session transport:

- Supabase staff and MATA resident access tokens are browser-visible bearer tokens for the immediate UAT cut.
- MATA resident sessions are stored in `sessionStorage`; Supabase sessions are handled by the Supabase browser client.
- This is acceptable only for protected stakeholder UAT if deployment protection, CORS, and manual smoke checks pass.
- Full cookie/BFF/CSRF transport is deferred to 5B-H-D and should be required before real production or broader public use.

## 6. Authorization and Scope Enforcement

Master Admin and Programme PC:

- Master Admin is explicit: `role = admin` plus `admin_level = master`.
- `programme_scope = NULL`, empty, blank, or whitespace-only grants no Programme PC access.
- Programme PC access rejects explicit Master Admin accounts and rejects empty scope.
- Admin context in `backend/app/routers/admin.py` prefers verified `request.state.identity`; raw fallback is disabled outside stub/demo.

Secretary:

- Secretary identity requires `role = secretary` and a non-empty DB-owned `posting_code`.
- Secretary routes derive `posting_code` from the verified identity and pass it into service calls.

NHG Resident:

- Resident routes use `require_resident_or_external`, parse the authenticated subject id, and pass that id into service queries.
- Native attendance list/remove/submit paths scope queries by `resident_id`.
- Current posting is derived from `resident_postings` in service logic, not trusted from a token posting claim.

Non-NHG Resident:

- Non-NHG registration enforces `home_cluster` in `NUH` or `SingHealth`, cross-table MCR uniqueness, and posting schedule validation.
- Non-NHG event, submission, ad-hoc, history, and dashboard paths use `external_resident_id` from the authenticated subject.
- Non-NHG submissions write `external_attendance_records`, not native `attendance_records`.
- Non-NHG dashboard returns `not_applicable`, not NHG compliance metrics.

Admin external attendance export:

- Export reads `external_attendance_records` joined to external resident/event context.
- Programme PC scope is checked through catalogue programme context; Master Admin can access all.
- Export notes mark records `compliance_included = false` and `export_only = true`.

## 7. Secrets and Environment Exposure

Searches reviewed committed frontend, CI, Docker, README, docs, and `.env.example` paths for backend-only names:

- `SUPABASE_SERVICE_ROLE_KEY`
- `MATA_RESIDENT_SESSION_SECRET`
- `DATABASE_URL`
- `SYNC_DATABASE_URL`
- `JWT_SECRET` / `SECRET_KEY`
- `SERVICE_ROLE`
- `PRIVATE_KEY`
- `DB_PASSWORD`

No real committed secret was found. Backend-only names appear in docs/placeholders or backend deployment context. Frontend code reads only public `VITE_*` values:

- `VITE_APP_ENV`
- `VITE_AUTH_MODE`
- `VITE_API_BASE_URL`
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`
- `VITE_SUPABASE_ANON_KEY`
- local/demo placeholder IDs and labels

`frontend/Dockerfile` build args are limited to public Vite values and local/demo placeholders. `.env.example` warns that all `VITE_*` values are browser-exposed and forbids service-role keys, resident session secrets, database URLs/passwords, JWT/private secrets, and backend-only keys in frontend env.

The ignored local `.env` file was not read.

## 8. CORS and Security Headers

CORS:

- `backend/app/middleware/security.py` configures `CORSMiddleware` with `settings.cors_origins`, credentials enabled, explicit methods, and wildcard request headers.
- Production rejects `*` in `settings.cors_origins`.
- Default origins are local-only; UAT must explicitly set exact deployed frontend origin(s).
- Actual Vercel URL and production CORS behavior require 5B-H-C smoke.

Security headers:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin` by default
- `Content-Security-Policy: default-src 'self'` by default

HSTS is meaningful only over HTTPS; Vercel/backend deployment must terminate HTTPS correctly.

## 9. Rate Limiting and Abuse Controls

`backend/app/middleware/rate_limit.py` applies:

- `POST /auth/login`: `rate_limit_auth_per_minute`, default 5/min.
- `POST /admin/upload/*`: `rate_limit_upload_per_hour`, default 10/hour.
- `POST /resident/attendance`: `rate_limit_resident_attendance_per_minute`, default 30/min.
- Other unsafe mutations, including `POST /resident/adhoc-teaching` and public Non-NHG registration: `rate_limit_mutation_per_minute`, default 60/min.
- Admin reports/exports GET prefixes: `rate_limit_report_per_minute`, default 20/min.
- Other GETs: `rate_limit_get_per_minute`, default 300/min.

Bucket keys use verified `request.state.identity` when present. Raw headers influence rate-limit bucketing only in stub/demo fallback and not in production/Supabase mode.

Residual risk: the store is in-memory and per process. This is acceptable for protected UAT but not enough for a multi-worker or public production threat model.

## 10. Upload and XLSX/XML Hardening

Current controls:

- Upload endpoints are admin-only.
- The AUD-M-05 descendant adds a pure ASGI boundary that enforces a 4 MiB
  global and aggregate upload-request cap before
  authentication or multipart parsing. It validates every observable
  `Content-Length` value and independently counts streamed bytes, including
  requests with absent or falsely small lengths.
- `UploadGuardMiddleware` retains the upload-route multipart content-type
  check. The per-file reader limit is 3 MiB, leaving multipart framing
  headroom.
- `parser_common.validate_upload_payload` enforces endpoint-specific extensions: RDB, TTF, and FormF1 accept `.xlsx`; Public Holidays accepts `.xlsx` and `.csv`.
- `.xlsx` payloads go through an `openpyxl.load_workbook(read_only=True, data_only=True)` readability check before parser dispatch.
- Password-protected/unreadable workbooks return a safe validation message.

Historical 5B-H-B finding, now superseded:

- The audit required an actual-byte recheck after `await file.read()` and
  before workbook/CSV parsing. The bounded streaming reader now performs this
  check and rejects above 3 MiB before parser dispatch.

Historical archive finding, now superseded:

- At that audit point, no deep ZIP member/XML bomb scanning was found. The
  H-D descendant now enforces the compressed file cap, 100 MiB aggregate
  expansion, 2,048 members, 20 MiB per expanded member, a 100:1 ratio ceiling,
  and nested-archive, encrypted-entry, unsafe-name/relationship, and unsafe-XML
  rejection. These controls remain in force under AUD-M-05.

## 11. Export and Formula-Injection Review

Backend XLSX:

- `backend/app/services/admin_external_attendance.py` calls `sanitize_spreadsheet_cell` for string values before writing Non-NHG attendance XLSX rows.
- `sanitize_spreadsheet_cell` prefixes values starting with `=`, `+`, `-`, or `@`.

Frontend CSV:

- `frontend/src/pages/secretary/SecretaryTeachingSchedulePage.tsx` builds a browser-side CSV and quotes values, but does not prefix formula-leading characters.
- Teaching names and SMC codes can be user-controlled enough to warrant formula hardening.

Required 5B-H-B fix:

- Add formula-safe CSV cell normalization before quoting secretary schedule CSV cells.

## 12. Error Handling and Logging

Current posture:

- `backend/app/middleware/errors.py` returns generic `Internal server error` for SQLAlchemy and unhandled exceptions.
- Server logs record exception class names, not full details in response bodies.
- Upload response metadata strips internal keys such as `exception`, `traceback`, `stack`, and `stacktrace`.
- Supabase Admin errors return generic messages such as `Supabase Admin request failed`, `credentials were rejected`, or `validation failed`.
- Passwords are not returned by staff account create/reset docs and service flow.

Residual risk:

- Parser validation errors intentionally expose workbook-derived messages to authorized admins. This is expected for PC correction workflow, but UAT operators should avoid real sensitive data unless approved.
- Production log aggregation must redact `Authorization`, `apikey`, cookies, database URLs, service-role keys, and resident-token secrets.

## 13. Dependency and Supply Chain Review

Dependency posture from manifests:

- Frontend has `package-lock.json`.
- `@supabase/supabase-js` is pinned exactly at `2.110.0`.
- Several frontend dependencies use caret ranges in `package.json`; the lockfile controls installed versions.
- Backend `requirements.txt` pins exact versions.
- No Python lockfile or dependency-audit report was found.

No dependency upgrade was performed because the task forbids broad upgrades and this local run did not use networked advisory tooling.

Recommended scan commands in an approved networked environment:

```powershell
cd frontend
npm audit

cd ..\backend
pip-audit -r requirements.txt
```

If either scan finds a high/critical vulnerability affecting UAT-exposed code paths, address it as a narrow follow-up rather than a broad upgrade.

## 14. Supabase Data API / RLS Boundary Review

Frontend Supabase use appears Auth-only:

- `frontend/src/api/supabaseClient.ts` creates a Supabase browser client and calls `client.auth.signInWithPassword`, `client.auth.getSession`, and `client.auth.signOut`.
- Search found no frontend `supabase.from(...)` or `supabase.rpc(...)` calls.
- MATA app-table access is mediated through the FastAPI backend.

RLS/grants boundary:

- Full RLS implementation remains deferred to a dedicated later phase.
- `docs/5b_g_rls_grants_matrix.md` classifies sensitive app tables as backend-only for now.
- Actual Supabase project exposed schema/grants/Data API settings were not inspectable locally.

UAT rule:

- If manual Supabase UAT smoke finds direct browser access to sensitive MATA app tables, stakeholder UAT is NO-GO until Data API/grants/RLS exposure is mitigated or the deployment is otherwise blocked.

## 15. Vercel UAT Deployment Checklist

Before stakeholder UAT:

- Vercel Deployment Protection, Vercel Authentication, password protection, or equivalent project-approved access control is enabled.
- Exact frontend Vercel URL is known.
- Exact backend URL is known.
- Backend `CORS_ORIGINS` includes only exact approved frontend origin(s).
- Frontend env contains browser-safe `VITE_*` variables only.
- Backend env uses `ENV=production` and `AUTH_MODE=supabase`.
- Backend env includes backend-only Supabase/database/session secrets only in backend secret storage.
- First Master Admin bootstrap is complete in UAT/staging and maps Supabase Auth `auth.users.id` to `users.supabase_user_id`.
- Clean Supabase migration smoke is complete, or an existing staging DB is verified against the migration smoke invariants.
- Supabase app table/Data API exposure is reviewed.
- No production resident data is used unless explicitly approved.
- Stakeholder accounts and synthetic/approved test data are prepared.
- Compliance surfaces are clearly labelled unavailable/not final before Phase 6.

## 16. Go/No-Go Decision

Decision: CONDITIONAL GO for continuing the 5B-H sequence; not yet GO for stakeholder traffic.

Reasoning:

- No high/critical local code blocker was found for auth bypass, direct frontend table access, or committed real secret exposure.
- Two medium local-code findings from 5B-H-A, H-UPLOAD-001 and H-EXPORT-001, are fixed and verified in 5B-H-B.
- Operational controls cannot be verified locally and must be completed by 5B-H-C smoke: deployment protection, exact CORS, production/Supabase env, first Master Admin bootstrap, migration/staging DB smoke, and Supabase Data API boundary review.

Stakeholder UAT should wait until 5B-H-C smoke evidence is filled in.

## 17. 5B-H-B Minimal Fix Plan

| Fix | Severity | Files likely affected | Why needed | Verification |
|---|---:|---|---|---|
| Enforce per-file upload byte-size after router read and before parser/readability validation. | Medium | `backend/app/services/parser_common.py`, `backend/app/routers/admin.py`, `backend/tests/test_upload_plumbing.py` | Prevent missing/misleading `Content-Length` from letting oversized upload bytes reach workbook/CSV parsing. | Completed in 5B-H-B. |
| Sanitize secretary schedule CSV cells before quoting. | Medium | `frontend/src/pages/secretary/SecretaryTeachingSchedulePage.tsx`, `frontend/src/authSession.contract.test.ts` | Prevent spreadsheet formula injection in browser-generated CSV. | Completed in 5B-H-B. |
| Record manual deployment controls that remain outside local code. | Medium | `docs/5b_h_uat_security_fix_log.md`, `docs/5b_h_vercel_supabase_uat_smoke.md` | B fixes do not prove Vercel/Supabase deployment controls. | 5B-H-B fix log created; 5B-H-C smoke checklist required. |

## 18. Explicit Deferrals

Deferred out of 5B-H-A/B/C or to later approved phases:

- Full cookie/BFF/CSRF implementation.
- Full RLS policies.
- RLS enablement.
- Supabase grant/Data API implementation changes.
- Phase 6 compliance.
- Final close/freeze.
- Period snapshots.
- Clawback.
- Historical migration.
- Production email/export productivity features.
- Broad dependency upgrades.
- Redis/platform rate-limit store unless UAT threat model changes.
- Historical deferral, superseded by H-D: deep XLSX ZIP/XML/archive scanning
  was outside this audit, but the descendant protections listed in Section 10
  are now implemented.

## Verification Performed For This Audit

Commands/checks run locally:

- `git status --short --branch`
- Read required source-of-truth docs and targeted implementation files listed in Scope Reviewed.
- `rg -n "SUPABASE_SERVICE_ROLE_KEY|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|SECRET_KEY|SERVICE_ROLE|PRIVATE_KEY|DB_PASSWORD" frontend .github docker-compose.yml frontend/Dockerfile backend/Dockerfile .env.example README.md docs/dev_setup.md frontend/README.md`
- `rg -n "VITE_.*(SERVICE_ROLE|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|SECRET_KEY|PRIVATE_KEY|DB_PASSWORD)|VITE_SUPABASE_SERVICE|VITE_.*SERVICE_ROLE|VITE_.*PRIVATE|VITE_.*SECRET|VITE_.*DATABASE" .env.example README.md docs frontend .github docker-compose.yml frontend/Dockerfile backend/Dockerfile`
- `rg -n "X-User-Role|X-User-Id|X-User-Programme|X-User-Site|X-Admin-Level" backend/app frontend/src`
- `rg -n "sessionStorage|localStorage|Authorization|Bearer" frontend/src backend/app`
- `rg -n "allow_origins|CORS|CORSMiddleware|Access-Control-Allow-Origin" backend/app .env.example README.md docs`
- `rg -n "rate.?limit|Retry-After|Too many requests" backend/app`
- `rg -n "UploadFile|File\(|max.*upload|content_type|\.xlsx|\.csv|openpyxl|zip" backend/app`
- `rg -n "sanitize_spreadsheet_cell|export|xlsx|csv|formula|worksheet|cell.value" backend/app frontend/src`
- `rg -n "supabase\.from\(|supabase\.rpc\(|createClient" frontend/src`
- `git diff --check`

Full tests were not required for 5B-H-A because this subphase created an audit document only and did not change app code.
