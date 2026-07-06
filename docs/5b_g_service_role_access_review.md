# 5B-G-G Service-Role And Privileged Backend Access Review

Status: Ready

Last updated: 2026-07-06

## Purpose

This review identifies where MATA needs privileged backend authority in Supabase mode, where it does not, and which guardrails must remain in place before RLS, grants, Data API exposure, or production hardening work proceeds.

This is an audit artifact only. It does not add service-role usage, enable RLS, add RLS policy SQL, change session transport, create Supabase Auth users, modify uploads, implement compliance, or change frontend code.

## Review Principles

- `SUPABASE_SERVICE_ROLE_KEY` is backend-only. It must never appear in frontend code, Vite variables, browser bundles, logs, exports, or docs with a real value.
- Supabase staff authentication proves token validity only. MATA authorization is still derived from `users`: `role`, `admin_level`, `programme_scope`, `posting_code`, `is_active`, and staff actor metadata.
- Staff Supabase Auth `sub` maps to `users.supabase_user_id`.
- Master Admin is explicit through `users.admin_level = 'master'`. Null, empty, blank, or missing programme scope never grants master access.
- NHG Resident and Non-NHG Resident tokens are backend-signed MATA resident tokens, not Supabase Auth users.
- Non-NHG attendance remains in `external_attendance_records` and never enters NHG compliance, surplus, snapshots, or clawback.
- Backend application authorization remains mandatory even after future RLS or grant changes.

## Surface Review Matrix

| Surface | File / Endpoint | Privileged or service-role need | Current posture | Risk | Follow-up | Phase |
|---|---|---:|---|---|---|---|
| Supabase Admin client | `backend/app/services/supabase_admin.py::SupabaseAdminClient` | Yes, only for Supabase Auth Admin create/update-password calls | Acceptable. Reads `SUPABASE_SERVICE_ROLE_KEY` server-side, sends it only to Supabase Auth Admin endpoints, and returns safe generic errors. | If logging middleware ever records outbound headers, the service-role key could leak. If reused outside staff provisioning, blast radius grows. | Keep client narrowly scoped to staff Auth Admin operations. Ensure outbound request logging redacts `apikey` and `Authorization`. | 5B-G / 5B-H hardening |
| Staff account create | `POST /admin/staff-accounts`, `backend/app/services/staff_accounts.py::create_staff_account` | Yes in `AUTH_MODE=supabase` to create Supabase Auth user | Acceptable with Master Admin gate. Persists returned Auth user id to `users.supabase_user_id`; stores only a `supabase-managed:<uuid>` local hash marker. | Supabase Auth user can be created before local DB commit; a DB failure could leave an orphan Auth user. | Add operational orphan-check/reconciliation guidance before production bootstrap. Consider compensating cleanup after failed local insert. | 5B-G runbook / future ops |
| Staff password reset | `POST /admin/staff-accounts/{user_id}/reset-password`, `backend/app/services/staff_accounts.py::reset_staff_account_password` | Yes in `AUTH_MODE=supabase` to update Supabase Auth password | Acceptable with Master Admin gate. Requires existing `users.supabase_user_id`, clears current staff actor metadata, writes audit log. | Password reset failure returns generic error; operator may need audit correlation without seeing secret details. | Keep errors safe. Add operator-facing runbook steps for Supabase Auth failure triage without logging passwords. | 5B-G runbook / 5B-H ops |
| Staff account update/list | `GET/PATCH /admin/staff-accounts` | No Supabase service-role needed unless email/auth identity mutation is added later | Acceptable. Master Admin gated; update does not modify Supabase Auth email. Last active Master Admin guard exists. | Future email-change support would need coordinated Supabase Auth update and stronger rollback handling. | Keep email changes unsupported until a dedicated design exists. | Future staff ops |
| First Master Admin bootstrap | `docs/5b_g_staff_bootstrap_runbook.md` plus manual Supabase Auth / SQL step | Yes operationally, but not through browser or normal app flow | Acceptable as a documented manual or one-time controlled backend task. No bootstrap script added in this phase. | Manual mismatch between Auth user and `users.supabase_user_id`; accidental assumption that null scope means master. | Perform bootstrap with verification SQL and at least one active Master Admin guard. | Pre-UAT / production ops |
| Supabase JWT verification | `backend/app/services/supabase_jwt.py::SupabaseJwtVerifier` | No service-role key | Acceptable. Uses JWKS for asymmetric tokens; legacy HS256 fallback validates with Auth server using publishable/anon key, then validates claims shape. | Publishable/anon fallback remains compatibility behavior; misconfigured issuer/audience can reject real users or accept wrong project only if env is wrong. | Keep service-role out of JWT verification. Include issuer/audience checks in deployment smoke. | 5B-G / deployment |
| Central auth mapping | `backend/app/middleware/auth_stub.py`, `backend/app/dependencies/auth.py` | No service-role key | Acceptable. Supabase staff token `sub` maps to active `users.supabase_user_id`; resident families use MATA resident tokens and DB reload. Raw identity headers are rejected in Supabase/production modes. | OpenAPI may still show stub/demo headers, confusing operators. Browser bearer transport remains temporary. | Clean generated docs later. Move browser token transport to cookie/BFF in 5B-H. | 5B-H |
| Upload endpoints | `POST /admin/upload/rdb`, `/ttf`, `/form-f1`, `/public-holidays` | No Supabase service-role needed for app execution; needs privileged DB role on backend connection | Acceptable. Admin context gates endpoints; TTF checks programme scope; uploads write `upload_logs`, warning issues, and audit logs. | RDB/FormF1/public-holiday uploads are broad admin operations; service-role-like DB access must still be bounded by app authorization. Upload parser failures may contain workbook-derived text. | Keep all upload writes backend-only. Add production file hardening, malware/ZIP/XML guardrails, and stricter error redaction if required. | 5B-H / future upload hardening |
| Upload logs and warning issues | `GET /admin/upload-logs`, `/upload-warnings`, warning issue mutation endpoints | No Supabase service-role needed directly | Acceptable. Reads and mutations are scoped by `programme_scope` unless Master Admin. Audit log writes use DB session. | Raw upload summaries may contain workbook data; broad Master Admin read is expected but sensitive. | Keep raw summary hidden by default; review before exposing direct Data API. | 5B-H / RLS phase |
| Data revalidation and parsed-data corrections | `backend/app/services/data_revalidation_service.py`, `backend/app/services/parsed_data.py` | No Supabase service-role key; privileged backend DB operations required | Acceptable for backend-mediated admin actions. Current code states these flows do not calculate compliance, snapshots, surplus hibernation, or clawback. | Mutating revalidation has high data impact; future RLS could block server operations if policies are too narrow. | Keep explicit preview/apply flows and audit entries. Include in future RLS bypass/service-role DB access design. | Future RLS / admin ops |
| Native admin reports | Admin read-model endpoints under `backend/app/routers/admin.py` | No Supabase service-role key currently; likely backend privileged DB reads needed after RLS | Acceptable because app-level programme scope gates reads. | Future RLS/grants may break cross-resident PC reports if only resident-owned policies exist. | Model these as backend-only report reads with role/scope-aware app authorization. | RLS/grants phase |
| Non-NHG attendance list/export | `GET /admin/external-attendance`, `/external-attendance/export.xlsx`, `backend/app/services/admin_external_attendance.py` | No Supabase service-role key; backend privileged DB reads likely needed after RLS | Acceptable. Queries only `external_attendance_records` and related external/event/reference tables. PC scope is checked through catalogue programme context; export sanitizes spreadsheet cells. | Scope-by-catalogue may include broad posting visibility when TTF catalogue is broad; this is export context, not NHG compliance. | Re-check programme scoping with real TTF data before production. Keep Non-NHG export separate from native reports. | Before Phase 6 compliance / export UAT |
| Secretary and PC event attendance guards | `backend/app/services/secretary_events.py`, `admin_secretary_events.py`, `programme_teaching_events.py` | No Supabase service-role key; backend DB reads across native and external attendance | Acceptable. External attendance checks prevent destructive edits/deletes when Non-NHG submissions exist; they do not join external data into NHG compliance. | Future RLS could block these cross-table existence checks. | Add these guard reads to the future privileged backend access/RLS test plan. | RLS/grants phase |
| Resident submissions | `backend/app/services/resident_submission.py` | No Supabase service-role key | Acceptable. NHG submissions write `attendance_records`; Non-NHG submissions write `external_attendance_records`; response text says Non-NHG is export-only and not NHG compliance/clawback. | Browser bearer transport and resident token storage remain 5B-H risk. | Move token transport to 5B-H cookie/BFF design. Preserve storage split. | 5B-H |
| Audit log writes | `backend/app/services/audit.py::write_audit_log` | No Supabase service-role key; backend DB write | Acceptable. Parameterized SQL; staff account audit snapshots remove `supabase_user_id`. | Generic audit snapshots from other services may include sensitive workbook-derived metadata or personal data by design. | Define audit redaction rules before wider production usage. | 5B-H / audit hardening |
| Future period close/freeze | Future final-close workflow writing `period_snapshots`, `surplus_ledger`, `clawback_records` | No Supabase Auth service-role key expected, but backend privileged DB execution likely required | Not implemented in this phase. Must be backend-only and app-authorized. | RLS could block cross-programme snapshot/clawback jobs; accidental inclusion of Non-NHG records would violate core rule. | Design as backend job with explicit Master Admin or scheduled operator authority, native attendance only, and separate RLS/grants tests. | Future final close / Phase 10 |
| Frontend Supabase client | `frontend/src/api/supabaseClient.ts`, `frontend/src/config/frontendConfig.ts`, `frontend/Dockerfile` | Must never receive service-role key | Acceptable. Uses only `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and `VITE_SUPABASE_ANON_KEY` fallback. | Browser-visible bearer tokens remain temporary. Mislabeling a backend secret with `VITE_` would expose it. | Keep README/.env warnings. Enforce secret scans in CI where practical. Replace bearer transport in 5B-H. | 5B-H |
| Deployment/env docs | `.env.example`, `README.md`, `docs/5b_g_supabase_migration_smoke_plan.md` | Service-role key documented only as placeholder, backend-only | Acceptable. No real secrets; `.env` was not read. | Operators may paste real values into docs/issues/logs. | Keep placeholders only. Use secret manager/deployment secrets for real values. | Deployment ops |

## Findings

### Acceptable Current Uses

- `SUPABASE_SERVICE_ROLE_KEY` is only used by `SupabaseAdminClient` for Supabase Auth Admin create/reset flows.
- Supabase JWT verification does not use service-role credentials.
- Frontend Vite variables do not include service-role, database URL, resident-token secret, JWT signing secret, private key, or DB password names.
- Admin uploads, logs, warning issue flows, reports, and Non-NHG exports use backend DB access plus app-level authorization, not browser direct database access.

### Follow-Up Risks

- Staff create can leave an orphan Supabase Auth user if local DB insertion or commit fails after Auth user creation.
- Upload summaries, warning issue metadata, and audit logs can contain workbook-derived or operationally sensitive data; raw detail exposure must stay admin-scoped and backend-mediated.
- Future RLS policies and grants can easily break broad backend operations such as uploads, reports, warning revalidation, event delete guards, final close, snapshots, clawback, and exports if the policy design only models single-row ownership.
- Non-NHG export scoping should be tested with real TTF catalogue data before production because the current programme-scope join is catalogue-based.
- Browser bearer-token transport and session persistence are intentionally deferred to Phase 5B-H.

## RLS And Grants Implications

Future RLS/grant work should treat the backend API as the policy enforcement boundary for complex MATA workflows. Supabase grants and RLS should not be used as a substitute for:

- Master Admin checks.
- Programme PC `programme_scope` checks.
- Secretary posting-scope checks.
- Resident self-scope checks.
- Non-NHG vs NHG identity separation.
- Upload/reporting period state checks.
- Public holiday event creation blocks.
- Future final-close/snapshot/clawback workflow authority.

Supabase Data API exposure should be explicit, minimal, and separately reviewed. Tables containing residents, attendance, staff accounts, uploads, audit logs, snapshots, clawback, and warning issue data should not be directly browser-readable without a dedicated RLS/grant test suite.

## Logging And Error Handling Notes

- `SupabaseAdminClient` returns generic errors such as "Supabase Admin request failed" or "credentials were rejected"; it does not include the response body or service-role key in API errors.
- Do not add debug logging of Supabase Admin headers, request payload passwords, access tokens, database URLs, or `.env` values.
- Export code sanitizes user-controlled spreadsheet text through `sanitize_spreadsheet_cell`.
- Future production log aggregation should redact `Authorization`, `apikey`, cookies, database URLs, and all values named like secrets.

## Deferred Work

Deferred to 5B-H:

- Cookie/BFF session transport.
- CSRF protection.
- `HttpOnly`, `Secure`, and `SameSite` cookie migration.
- Server-side logout/session invalidation.
- Replacing browser-visible Supabase and MATA bearer token storage.
- Production CORS tightening beyond documentation.
- Rate-limit hardening beyond current baseline.
- Upload/XLSX/XML exploit hardening.
- Formula-injection export audit across every export surface.

Deferred beyond 5B-G:

- RLS enablement and policy SQL.
- Supabase exposed-schema grant changes.
- Production staff bootstrap execution.
- Clean Supabase migration rehearsal execution.
- Phase 6 compliance engine.
- Period final close/freeze.
- Period snapshots.
- Clawback generation.
- Historical migration.
- Email/export productivity features unless already implemented and separately tested.

## Recommended Next Task

Recommended next Codex task: execute Phase 5B-H auth/session hardening design and implementation plan, starting with cookie/BFF transport, CSRF, logout/session invalidation, and removal of browser-stored bearer-token reliance.

## Sources Consulted

- Supabase API security guide: https://supabase.com/docs/guides/api/securing-your-api
- Supabase RLS guide: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase changelog, explicit grants/Data API exposure changes: https://supabase.com/changelog
