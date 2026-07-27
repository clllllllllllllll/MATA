# 5B-G-G Service-Role And Privileged Backend Access Review

Status: historical 5B-G review reconciled with locally implemented 5B-H-D/H-E controls; deployed verification pending

Last updated: 2026-07-27

## Purpose

This review identifies where MATA needs privileged backend authority in Supabase mode, where it does not, and which guardrails must remain in place around RLS, grants, Data API exposure, and production hardening.

This began as a 5B-G audit artifact and did not itself change code. H-D and H-E later implemented the session and database boundaries described in the current-state reconciliation below. Historical surface assessments remain for traceability; current behavior is governed by the implementation and its tests.

## H-E Current Privileged-Access Disposition

- `SUPABASE_SERVICE_ROLE_KEY` remains limited to backend Supabase Auth Admin create/reset operations. It is not a PostgreSQL application runtime credential.
- Ordinary application SQL does not use Supabase `service_role`, a table owner, a superuser, or a `BYPASSRLS` role.
- Protected SQL uses a distinct credentialed login with only the `mata_app_runtime` capability. Public login/registration/session infrastructure uses a second credential with only `mata_auth_internal`. Alembic and application-object ownership use a third credential.
- `mata_auth_internal` has no direct application-table or sequence privileges. It can execute only the exact auth/shared reviewed helper set.
- `app_sessions`, `rate_limit_buckets`, `programme_institution_posting_map`, `surplus_ledger`, `period_snapshots`, and `clawback_records` receive no direct runtime table privilege. Existing authorized operations use reviewed helpers; unimplemented future workflows remain denied.
- Upload, report, warning, event-guard, external-attendance, and other cross-row operations use scoped runtime policies or concrete reviewed helpers demonstrated by existing workflows. H-E did not create speculative helpers for hypothetical future work.
- PUBLIC and optional browser/service roles have no application relation, H-E helper, or `CREATE` authority in `public`.
- Startup attestation fails closed if either application credential is privileged, owns relevant objects, can assume/delegate an unsafe role or grant, or has a catalogue different from the reviewed H-E contract.

This is local source/disposable-database evidence. The approved deployed Supabase target requires independent verification.

## Review Principles

- `SUPABASE_SERVICE_ROLE_KEY` is backend-only. It must never appear in frontend code, Vite variables, browser bundles, logs, exports, or docs with a real value.
- Supabase staff authentication proves token validity only. MATA authorization is still derived from `users`: `role`, `admin_level`, `programme_scope`, `posting_code`, `is_active`, and staff actor metadata.
- Staff Supabase Auth `sub` maps to `users.supabase_user_id`.
- Master Admin is explicit through `users.admin_level = 'master'`. Null, empty, blank, or missing programme scope never grants master access.
- NHG Resident and Non-NHG Resident tokens are backend-signed MATA resident tokens, not Supabase Auth users.
- Non-NHG attendance remains in `external_attendance_records` and never enters NHG compliance, surplus, snapshots, or clawback.
- Backend application authorization remains mandatory with H-E RLS and grant controls.

## Surface Review Matrix

| Surface | File / Endpoint | Privileged or service-role need | Current posture | Risk | Follow-up | Phase |
|---|---|---:|---|---|---|---|
| Supabase Admin client | `backend/app/services/supabase_admin.py::SupabaseAdminClient` | Yes, only for Supabase Auth Admin create/update-password calls | Acceptable. Reads `SUPABASE_SERVICE_ROLE_KEY` server-side, sends it only to Supabase Auth Admin endpoints, and returns safe generic errors. | If logging middleware ever records outbound headers, the service-role key could leak. If reused outside staff provisioning, blast radius grows. | Keep client narrowly scoped to staff Auth Admin operations. Ensure outbound request logging redacts `apikey` and `Authorization`. | 5B-G / 5B-H hardening |
| Staff account create | `POST /admin/staff-accounts`, `backend/app/services/staff_accounts.py::create_staff_account` | Yes in `AUTH_MODE=supabase` to create Supabase Auth user | Acceptable with Master Admin gate. Persists returned Auth user id to `users.supabase_user_id`; stores only a `supabase-managed:<uuid>` local hash marker. | Supabase Auth user can be created before local DB commit; a DB failure could leave an orphan Auth user. | Add operational orphan-check/reconciliation guidance before production bootstrap. Consider compensating cleanup after failed local insert. | 5B-G runbook / future ops |
| Staff password reset | `POST /admin/staff-accounts/{user_id}/reset-password`, `backend/app/services/staff_accounts.py::reset_staff_account_password` | Yes in `AUTH_MODE=supabase` to update Supabase Auth password | Acceptable with Master Admin gate. Requires existing `users.supabase_user_id`, clears current staff actor metadata, writes audit log. | Password reset failure returns generic error; operator may need audit correlation without seeing secret details. | Keep errors safe. Add operator-facing runbook steps for Supabase Auth failure triage without logging passwords. | 5B-G runbook / 5B-H ops |
| Staff account update/list | `GET/PATCH /admin/staff-accounts` | No Supabase service-role needed unless email/auth identity mutation is added later | Acceptable. Master Admin gated; update does not modify Supabase Auth email. Last active Master Admin guard exists. | Future email-change support would need coordinated Supabase Auth update and stronger rollback handling. | Keep email changes unsupported until a dedicated design exists. | Future staff ops |
| First Master Admin bootstrap | `docs/5b_g_staff_bootstrap_runbook.md` plus manual Supabase Auth / SQL step | Yes operationally, but not through browser or normal app flow | Acceptable as a documented manual or one-time controlled backend task. No bootstrap script added in this phase. | Manual mismatch between Auth user and `users.supabase_user_id`; accidental assumption that null scope means master. | Perform bootstrap with verification SQL and at least one active Master Admin guard. | Pre-UAT / production ops |
| Supabase JWT verification | `backend/app/services/supabase_jwt.py::SupabaseJwtVerifier` | No service-role key | Acceptable. Uses JWKS for asymmetric tokens; legacy HS256 fallback validates with Auth server using publishable/anon key, then validates claims shape. | Publishable/anon fallback remains compatibility behavior; misconfigured issuer/audience can reject real users or accept wrong project only if env is wrong. | Keep service-role out of JWT verification. Include issuer/audience checks in deployment smoke. | 5B-G / deployment |
| Central auth mapping | `backend/app/middleware/auth_stub.py`, `backend/app/dependencies/auth.py`, `backend/app/services/database_context.py` | No service-role key | H-D/H-E current state: Supabase staff `sub` maps to active `users.supabase_user_id`; all roles use opaque MATA sessions; raw identity headers are rejected in Supabase/production modes; protected SQL receives database-revalidated transaction context. | A future alternate auth path could bypass the session/context binding if added outside these choke points. | Keep cookie/session and database-context resolution centralized and startup-attested. | 5B-H-D/H-E |
| Upload endpoints | `POST /admin/upload/rdb`, `/ttf`, `/form-f1`, `/public-holidays` | No Supabase service-role needed for app execution; needs privileged DB role on backend connection | Acceptable. Admin context gates endpoints; TTF checks programme scope; uploads write `upload_logs`, warning issues, and audit logs. | RDB/FormF1/public-holiday uploads are broad admin operations; service-role-like DB access must still be bounded by app authorization. Upload parser failures may contain workbook-derived text. | Keep all upload writes backend-only. Add production file hardening, malware/ZIP/XML guardrails, and stricter error redaction if required. | 5B-H / future upload hardening |
| Upload logs and warning issues | `GET /admin/upload-logs`, `/upload-warnings`, warning issue mutation endpoints | No Supabase service-role needed directly | H-E preserves programme-scoped reads/mutations under runtime policies and reviewed audit writes. | Raw upload summaries may contain workbook data; broad Master Admin read is expected but sensitive. | Keep raw summary hidden by default; review before exposing direct Data API. | H-E / admin ops |
| Data revalidation and parsed-data corrections | `backend/app/services/data_revalidation_service.py`, `backend/app/services/parsed_data.py` | No Supabase service-role key | Existing backend-mediated actions run under the scoped H-E runtime; they do not calculate compliance, snapshots, surplus hibernation, or clawback. | Mutating revalidation remains high impact and must not gain an owner/bypass path. | Keep explicit preview/apply, RLS scope, and audit entries; add a helper only if a concrete test proves one necessary. | H-E / admin ops |
| Native admin reports | Admin read-model endpoints under `backend/app/routers/admin.py` | No Supabase service-role key or owner bypass | H-E policies permit the existing Master/PC scoped joins under the restricted runtime. | A new report join can still be over-filtered or over-broad if its relationships are not covered by policy tests. | Retain app authorization and add focused policy coverage for genuinely new relationships. | H-E / future reports |
| Non-NHG attendance list/export | `GET /admin/external-attendance`, `/external-attendance/export.xlsx`, `backend/app/services/admin_external_attendance.py` | No Supabase service-role key or owner bypass | Existing list/export runs under H-E programme-scoped policies and keeps external attendance separate. | Scope-by-catalogue may include broad posting visibility when TTF catalogue is broad; this is export context, not NHG compliance. | Re-check programme scoping with approved UAT data before production. Keep Non-NHG export separate from native reports. | H-E / export UAT |
| Secretary and PC event attendance guards | `backend/app/services/secretary_events.py`, `admin_secretary_events.py`, `programme_teaching_events.py` | No Supabase service-role key or owner bypass | H-E relationship policies preserve existing native/external attendance guard reads under the restricted runtime. | A new cross-row guard can still require focused policy coverage. | Preserve direct guard tests when relationships change; do not add broad helper access speculatively. | H-E |
| Resident submissions | `backend/app/services/resident_submission.py` | No Supabase service-role key | H-D cookie transport and H-E row policies preserve separate native and Non-NHG write paths. | A policy or service regression could cross identity families. | Preserve storage split, exact subject context, and direct five-role matrix tests. | H-D/H-E |
| Audit log writes | `backend/app/services/audit.py::write_audit_log` | No Supabase service-role key; backend DB write | Acceptable. Parameterized SQL; staff account audit snapshots remove `supabase_user_id`. | Generic audit snapshots from other services may include sensitive workbook-derived metadata or personal data by design. | Define audit redaction rules before wider production usage. | 5B-H / audit hardening |
| Future period close/freeze | Future final-close workflow writing `period_snapshots`, `surplus_ledger`, `clawback_records` | No Supabase Auth service-role key expected, but backend privileged DB execution likely required | Not implemented in this phase. Must be backend-only and app-authorized. | RLS could block cross-programme snapshot/clawback jobs; accidental inclusion of Non-NHG records would violate core rule. | Design as backend job with explicit Master Admin or scheduled operator authority, native attendance only, and separate RLS/grants tests. | Future final close / Phase 10 |
| Frontend credential boundary | Frontend auth/API configuration and build | Must never receive service-role or database credentials | H-D removed the normal browser Supabase client/session and routine bearer storage. Production uses the backend cookie and relative `/api/v1`. | Mislabeling a backend secret with `VITE_` would expose it. | Keep environment warnings and source/bundle secret scans. | H-D current |
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
- Future policy or workflow changes can break broad backend operations such as uploads, reports, warning revalidation, event delete guards, final close, snapshots, clawback, and exports if their cross-row relationships are not explicitly tested.
- Non-NHG export scoping should be tested with real TTF catalogue data before production because the current programme-scope join is catalogue-based.
- H-D removed normal browser bearer-token transport and persistence; emergency bearer compatibility remains explicitly gated and rollback-only.

## RLS And Grants Implications

The H-E RLS/grant implementation treats the backend API as the primary policy enforcement boundary for complex MATA workflows. PostgreSQL grants and RLS are defense in depth and are not a substitute for:

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

## Historical Deferred Work And Current Disposition

H-D subsequently completed the cookie/BFF-style session owner, CSRF, strict cookie, server-side logout/revocation, browser bearer removal, CORS/rate-limit/upload hardening, and export review work listed by the original 5B-G audit.

H-E subsequently completed the local restricted-role, trusted-context, RLS policy, exact grant, helper, and disposable PostgreSQL migration-verification work. No live Supabase migration or grant change was performed.

Still deferred or separately authorized:

- deployed Supabase migration and exact role/policy/grant verification;
- production staff bootstrap execution;
- Phase 6 compliance changes not already present;
- period final close/freeze and immutable snapshot generation;
- clawback generation;
- historical migration;
- email/export productivity features unless already implemented and separately tested.

## Current Follow-Up

The next security action is deployed verification on an approved target: confirm revision `20260726_000026`, three distinct database credentials, non-owner/NOBYPASSRLS runtime behavior, exact ownership/policy/helper/grant/default-ACL catalogue, PUBLIC/browser denial, startup attestation, and all five role workflows. Local completion must not be presented as deployed security.

## Sources Consulted

- Supabase API security guide: https://supabase.com/docs/guides/api/securing-your-api
- Supabase RLS guide: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase changelog, explicit grants/Data API exposure changes: https://supabase.com/changelog
