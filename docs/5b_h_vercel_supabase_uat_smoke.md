# 5B-H-C Supabase/Vercel UAT Smoke Checklist

Status: Final audit executed; stakeholder UAT and Phase 6 are NO-GO pending High findings and remaining deployment evidence
Last updated: 2026-07-22

## 1. Purpose

This checklist is the required evidence template before stakeholder UAT on Vercel/Supabase. It confirms the protected deployment posture, Supabase auth wiring, first Master Admin bootstrap, migration smoke status, role-scoped API behavior, CORS behavior, no-secret exposure, and no direct browser access to sensitive MATA app tables.

Historical baseline: when this checklist was created on 2026-07-06, every evidence row was `Not run`. The 2026-07-22 results below preserve unsupported deployed checks as `MANUAL VERIFICATION REQUIRED` or `BLOCKED`; local automated evidence is labelled as such. Full findings are in `docs/5b_h_c_deployment_security_audit.md`.

## 2. Preconditions

- 5B-G docs are available: `docs/5b_g_staff_bootstrap_runbook.md`, `docs/5b_g_supabase_migration_smoke_plan.md`, `docs/5b_g_rls_grants_matrix.md`, and `docs/5b_g_service_role_access_review.md`.
- 5B-H-A audit exists: `docs/5b_h_uat_security_audit.md`.
- 5B-H-B fixes are committed or explicitly accepted in `docs/5b_h_uat_security_fix_log.md`.
- A staging/disposable Supabase project or approved UAT database is selected.
- Vercel frontend and backend UAT URLs are known.
- The deployment protection method is selected before sharing URLs.
- The first Master Admin bootstrap operator is identified.
- No production data is used unless separately approved and documented.
- No screenshots, copied logs, docs, or command output include secrets, tokens, service-role keys, database URLs, or real personal data.

## 3. Environment Checklist

Backend/server-only variables to verify in the backend deployment environment:

- `ENV=production`
- `AUTH_MODE=supabase`
- `DATABASE_URL`
- `SYNC_DATABASE_URL` if migration tooling needs it
- `SUPABASE_URL`
- `SUPABASE_JWKS_URL` or `SUPABASE_JWT_ISSUER` according to configured verification path
- `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_ANON_KEY` only if needed by backend verifier fallback
- `SUPABASE_SERVICE_ROLE_KEY`
- `MATA_RESIDENT_SESSION_SECRET`
- `CORS_ORIGINS` set to the exact frontend UAT origin list
- Rate-limit settings if overridden from defaults

Frontend/public variables to verify in the frontend deployment environment:

- `VITE_AUTH_MODE=supabase`
- `VITE_API_BASE_URL` set to the backend UAT API base URL
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY` or `VITE_SUPABASE_ANON_KEY`

Forbidden in frontend variables, frontend build args, frontend bundle output, and browser-readable config:

- `SUPABASE_SERVICE_ROLE_KEY`
- `DATABASE_URL`
- `SYNC_DATABASE_URL`
- `MATA_RESIDENT_SESSION_SECRET`
- `JWT_SECRET`
- Any password, private key, service account JSON, access token, or refresh token

Evidence:

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Backend env reviewed with no copied secret values in evidence | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | No safe deployed settings/diagnostics access. |
| Frontend env reviewed and contains public `VITE_*` values only | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Repository inputs passed; deployed Vercel env was not inspectable. |
| Frontend bundle/config search found no backend-only secret names | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Fresh local build names-only scan passed; deployed artifact still requires review. |

## 4. Deployment Protection Checklist

Stakeholder UAT is GO only if the URL is intentionally access-controlled. Acceptable controls include Vercel deployment protection, SSO/password protection, IP allowlisting, or another documented access gate approved for this UAT.

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Frontend UAT URL requires the chosen access gate before app load | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Existing browser state was authenticated; cookie-free curl hit Vercel bot mitigation, not a verifiable stakeholder gate. |
| Backend UAT API URL is not broadly usable without app auth | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Token-free `/api/v1/auth/me` passed with controlled `401`; that single protected endpoint does not prove the entire deployed API surface. |
| Shared links and access list are limited to intended stakeholders | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Requires Vercel settings/access-list review. |
| Access gate failure does not reveal app data | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Requires an unauthenticated private/incognito attempt. |

## 5. Supabase Database And Migration Smoke

Use `docs/5b_g_supabase_migration_smoke_plan.md` as the source checklist. Do not run RLS enablement, RLS policy SQL, broad grants changes, or production-data migration as part of 5B-H-C.

Required evidence:

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Target database confirmed as staging/disposable UAT or otherwise approved | BLOCKED | Codex | 2026-07-22 | Effective target was `localhost/mata_db`; intended Supabase project label unavailable. |
| Alembic migration smoke completed or existing schema verified against head | BLOCKED | Codex | 2026-07-22 | `alembic current` not run against the wrong target; expected head is `20260721_000022`. |
| Seed smoke completed where required for UAT | BLOCKED | Codex | 2026-07-22 | Correct approved database target unavailable. |
| `external_residents` and `external_attendance_records` exist | BLOCKED | Codex | 2026-07-22 | Committed migrations support them; deployed schema not queried. |
| `users.supabase_user_id` uniqueness exists | BLOCKED | Codex | 2026-07-22 | Committed migration supports it; deployed constraint not queried. |
| `programmes.compliance_variant` remains absent | BLOCKED | Codex | 2026-07-22 | Migration history supports absence; deployed schema not queried. |
| `attendance_records.session_type_id` remains absent | BLOCKED | Codex | 2026-07-22 | Migration history supports absence; deployed schema not queried. |
| Native resident auth mapping path is present | BLOCKED | Codex | 2026-07-22 | Repository path exists; deployed schema/account mapping not verified. |
| No 5B-H migration was introduced for this smoke | PASS | Codex | 2026-07-22 | Audit branch changes documentation only. |

## 6. First Master Admin Bootstrap Smoke

Use `docs/5b_g_staff_bootstrap_runbook.md`. The bootstrap operator must not paste passwords, service-role keys, or Supabase Auth tokens into this document.

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| First Supabase Auth staff user created or selected for UAT | BLOCKED | Codex | 2026-07-22 | No approved UAT account fixture supplied. |
| Matching `users` row linked by `supabase_user_id` | BLOCKED | Codex | 2026-07-22 | No approved database/account access. |
| `role='admin'`, `admin_level='master'`, `programme_scope=[]`, and active state verified | BLOCKED | Codex | 2026-07-22 | No approved database/account access. |
| Master Admin can sign in from deployed frontend | BLOCKED | Codex | 2026-07-22 | Approved credentials unavailable. |
| Master Admin can reach staff-account bootstrap UI/API | BLOCKED | Codex | 2026-07-22 | Approved credentials unavailable. |
| Failed or non-master staff account cannot access Master Admin-only surfaces | BLOCKED | Codex | 2026-07-22 | Approved role fixtures unavailable; local authorization tests pass. |

## 7. Auth Role Smoke Tests

Use UAT-safe test accounts and resident records only.

| Role/path | Check | Result | Operator | Date | Notes |
|---|---|---|---|---|---|
| Staff | Supabase email/password sign-in succeeds for linked active staff user | BLOCKED | Codex | 2026-07-22 | Approved UAT credentials unavailable. |
| Staff | `/auth/me` returns role/scope from backend DB, not Supabase `user_metadata` | BLOCKED | Codex | 2026-07-22 | Local tests pass; deployed account fixture unavailable. |
| Master Admin | Can access Master Admin-only config/staff surfaces | BLOCKED | Codex | 2026-07-22 | Local tests pass; deployed account fixture unavailable. |
| Programme PC | Can access only programme-scoped admin data | FAIL | Codex | 2026-07-22 | Blank-scope synthetic PC reached global RDB, FormF1, and Public Holidays upload mutations. |
| Programme PC | Cannot access programmes outside `programme_scope` | FAIL | Codex | 2026-07-22 | The three global upload routes do not enforce non-empty scope or explicit Master Admin. |
| Secretary | Can manage only the verified posting scope | BLOCKED | Codex | 2026-07-22 | Local posting-scope tests pass; deployed account fixture unavailable. |
| Secretary | Cannot create an event outside posting scope | BLOCKED | Codex | 2026-07-22 | Local posting-scope tests pass; deployed account fixture unavailable. |
| NHG Resident | MCR-only login returns a backend-signed MATA resident session | BLOCKED | Codex | 2026-07-22 | Local auth tests pass; deployed resident fixture unavailable. |
| NHG Resident | Resident APIs are scoped to authenticated resident id | BLOCKED | Codex | 2026-07-22 | Local identity-scope tests pass; deployed fixture unavailable. |
| Non-NHG Resident | Registration rejects duplicate MCR present in native or external table | BLOCKED | Codex | 2026-07-22 | Local tests pass; deployed synthetic fixture unavailable. |
| Non-NHG Resident | Login/submission uses external tables and is excluded from NHG compliance | BLOCKED | Codex | 2026-07-22 | Local tests pass; deployed synthetic fixture unavailable. |
| Raw headers | Raw `X-User-*` identity headers alone are rejected in production/Supabase mode | PASS | Codex | 2026-07-22 | Deployed request returned `401` with no role/user/internal detail markers. |

## 8. CORS And Security Header Smoke

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Approved frontend UAT origin can call backend API | PASS | Codex | 2026-07-22 | CORS preflight `200`; ACAO exactly `https://mata-aine.vercel.app`; credentials enabled. |
| Unapproved origin does not receive permissive CORS response | PASS | Codex | 2026-07-22 | Named unapproved, localhost, and synthetic representative preview origins returned `400` without ACAO. |
| Exact deployed `CORS_ORIGINS` membership contains no additional origin | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Runtime probes passed, but the deployed environment list was not safely inspectable. |
| Production backend rejects wildcard `CORS_ORIGINS=*` configuration | PASS | Codex | 2026-07-22 | Repository production source guard rejects `*`; deployed controls also received no ACAO. |
| Responses include HSTS, frame denial, content-type nosniff, referrer policy, and CSP headers | PASS | Codex | 2026-07-22 | Verified on deployed `/health` response. |
| Tested deployed auth failure does not expose stack traces, SQL, paths, tokens, or secrets | PASS | Codex | 2026-07-22 | Token-free `/api/v1/auth/me` passed the safe marker check. |
| Deployed 5xx/error paths do not expose internal details | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Local safe-error tests passed; no safe deployed 5xx fixture was available. |

## 9. Supabase Data API Boundary Smoke

The frontend must stay backend-mediated for MATA app data during this protected UAT cut. If direct browser access to sensitive Supabase app tables is found, stakeholder UAT is NO-GO until exposure is mitigated.

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Frontend source/bundle has no `supabase.from(...)` or `supabase.rpc(...)` app-table calls | PASS | Codex | 2026-07-22 | Exact source scan returned no match; broader endpoint scan also returned no app-table client path. |
| Browser devtools/network shows no direct Supabase Data API calls to sensitive MATA tables | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Clean-session browser Network evidence unavailable. |
| Supabase project exposed schemas/API settings reviewed for app-table exposure | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | Supabase settings access unavailable. |
| Direct table query with browser/public key cannot read sensitive app data | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | No operator-approved public-key test input supplied. |
| Any exception or accepted exposure is documented with owner-approved mitigation | NOT APPLICABLE | Codex | 2026-07-22 | No exception or accepted exposure was presented; exposure itself remains unverified. |

## 10. Functional UAT Smoke

Run only against UAT-safe fixtures.

| Workflow | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Backend health endpoint responds without sensitive details | PASS | Codex | 2026-07-22 | Deployed `200`, body `{"status":"ok"}`. |
| Admin upload rejects invalid extension | PASS | Codex | 2026-07-22 | Direct local upload tests passed. |
| Admin upload rejects oversized payload | PASS | Codex | 2026-07-22 | Direct local upload tests passed. |
| Public holiday upload populates expected public holiday/month boundary data if fixture is available | BLOCKED | Codex | 2026-07-22 | No approved deployed fixture/account. |
| RDB upload smoke completes if fixture is available | BLOCKED | Codex | 2026-07-22 | No approved deployed fixture/account; scope blocker remains. |
| TTF upload smoke completes if fixture is available | BLOCKED | Codex | 2026-07-22 | No approved deployed fixture/account. |
| FormF1 upload smoke completes if fixture is available | BLOCKED | Codex | 2026-07-22 | No approved deployed fixture/account; scope blocker remains. |
| Secretary teaching event creation works on non-public-holiday date | PASS | Codex | 2026-07-22 | Direct local synthetic service/API tests passed. |
| Secretary teaching event creation is blocked on public holiday date | PASS | Codex | 2026-07-22 | Direct local synthetic tests passed. |
| Resident scheduled attendance submission stores one native record and blocks duplicate | PASS | Codex | 2026-07-22 | Direct local synthetic tests passed; distinct-event overlap separately fails below. |
| Resident distinct-event overlap is rejected | FAIL | Codex | 2026-07-22 | Reproduced native path accepted a distinct event with the same interval and added one row. |
| Resident ad-hoc submission is blocked on public holiday date | PASS | Codex | 2026-07-22 | Direct local synthetic tests passed. |
| Non-NHG submission stores external attendance only | PASS | Codex | 2026-07-22 | Direct local synthetic tests passed. |
| Secretary CSV export opens as text and formula-leading teaching names are neutralized | PASS | Codex | 2026-07-22 | Frontend export contract test passed. |

Expanded final-audit workflow checks:

| Workflow | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Registration options expose 24 active TTSH programmes | PASS | Codex | 2026-07-22 | Local API/migration contract tests passed; deployed row counts remain blocked. |
| FM, PATH, SPORTSMED, and PALLMED are omitted | PASS | Codex | 2026-07-22 | Local API/migration contract tests passed. |
| Public options expose no posting code; GERI + TTSH resolves internally to `TTSHGerMed` | PASS | Codex | 2026-07-22 | Local mapping tests passed. |
| External schedule stores exact programme provenance and does not create a native resident | PASS | Codex | 2026-07-22 | Local service/API tests passed. |
| NHG Resident sees an eligible scheduled event | PASS | Codex | 2026-07-22 | Local resident-event tests passed. |
| Non-NHG GERI/TTSHGerMed Resident sees eligible Secretary and GERI PC events | PASS | Codex | 2026-07-22 | Local external-event tests passed. |
| Non-NHG Resident cannot see another programme's PC event | PASS | Codex | 2026-07-22 | Local external-event test passed. |
| Native and Non-NHG attendance remain in their separate tables | PASS | Codex | 2026-07-22 | Local native/external storage tests passed. |
| Programme PC native overview is scoped and personal history is read-only | PASS | Codex | 2026-07-22 | Local read-model/authorization tests passed. |
| Non-NHG Attendance remains separate and out-of-scope native UUID fails safely | PASS | Codex | 2026-07-22 | Local authorization tests passed. |
| Source labels distinguish Department Secretary, Programme PC, and Ad-hoc | PASS | Codex | 2026-07-22 | Local read-model tests passed. |
| Ordinary Secretary/PC deletion is blocked when attendance exists | PASS | Codex | 2026-07-22 | Local service tests passed. |
| Master force-delete shows split counts and requires exact `DELETE`, reason, and expected counts | PASS | Codex | 2026-07-22 | Local route/service tests passed. |
| Mixed force-delete is atomic, removes all linked rows, records audit, and preserves unrelated events | BLOCKED | Codex | 2026-07-22 | Guarded PostgreSQL suite refused the non-disposable target; no mutation ran. |
| Conflicting raw headers cannot override a valid deployed identity | BLOCKED | Codex | 2026-07-22 | Local automated test passes; approved deployed bearer fixture unavailable. |

## 11. Evidence Template

Use this table for each smoke command or manual action. Do not include secret values.

| Evidence ID | Area | Command/action | Result | Operator | Date/time | Artifact/link | Notes |
|---|---|---|---|---|---|---|---|
| HC-DEPLOY-001 | Deployment protection | Private/incognito and settings review | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Bot challenge is not proof of stakeholder access control. |
| HC-ENV-001 | Env separation | Safe deployed env review | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Repository support only. |
| HC-MIGRATION-001 | Migration smoke | `alembic heads`; target safety check | BLOCKED | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Wrong effective database target; expected head `20260721_000022`. |
| HC-AUTHZ-001 | Auth role smoke | Synthetic blank-scope upload probe | FAIL | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Three global upload routes returned `200`. |
| HC-HEADERS-001 | Raw headers | Token-free deployed request | PASS | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | `401`, no identity/internal details. |
| HC-CORS-001 | Exact CORS allowlist | Approved/rejected preflights plus deployed-list review | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Four runtime probes passed; exact deployed membership was not inspectable. |
| HC-DATAAPI-001 | Supabase Data API boundary | Source scan only | MANUAL VERIFICATION REQUIRED | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Live grants/network/public-key denial unverified. |
| HC-FUNCTIONAL-001 | Functional smoke | Synthetic native overlap probe | FAIL | Codex | 2026-07-22 | `docs/5b_h_c_deployment_security_audit.md` | Native distinct overlap accepted. |

## 12. Go/No-Go For Stakeholder UAT

GO only when all are true:

- 5B-H-B fixes are committed or explicitly accepted with mitigation.
- Deployment access protection is active and tested.
- Backend is running with production Supabase auth settings.
- CORS is restricted to approved origins.
- First Master Admin bootstrap is complete.
- Migration/schema smoke is complete on the approved UAT database.
- Raw `X-User-*` headers alone are rejected.
- No backend-only secrets are visible to the frontend or browser.
- No direct browser access to sensitive MATA app tables is found.
- No high/critical finding remains open without owner-approved mitigation.

Final 2026-07-22 result: `NO-GO — BLOCKERS MUST BE FIXED`.

High blockers:

- blank-scope Programme PC access to global RDB, FormF1, and Public Holidays upload mutations;
- native distinct-event overlap accepted instead of rejected.

Deployment protection, backend production/Supabase modes, migration/schema state, Data API exposure, and approved deployed account workflows also remain manual or blocked. Phase 6 is not approved.

## 13. Rollback

- Disable or restrict the Vercel deployment link.
- Revoke stakeholder access to the protected deployment gate.
- Rotate any credential suspected to have been exposed.
- Disable affected Supabase Auth test users if account linkage is wrong.
- Revert the Vercel deployment to the previous known-safe build if app behavior regresses.
- Restore the UAT database from a known-safe snapshot if smoke data corrupts the database.
- Document the rollback trigger, operator, time, and follow-up owner without pasting secrets.
