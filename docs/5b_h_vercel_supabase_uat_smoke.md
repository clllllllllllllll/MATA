# 5B-H-C Supabase/Vercel UAT Smoke Checklist

Status: Checklist ready; deployment smoke not yet run
Last updated: 2026-07-06

## 1. Purpose

This checklist is the required evidence template before stakeholder UAT on Vercel/Supabase. It confirms the protected deployment posture, Supabase auth wiring, first Master Admin bootstrap, migration smoke status, role-scoped API behavior, CORS behavior, no-secret exposure, and no direct browser access to sensitive MATA app tables.

This document does not claim that Vercel or Supabase UAT has been deployed or tested. Fill the evidence fields only after running the checks against the actual protected UAT deployment.

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
| Backend env reviewed with no copied secret values in evidence | Not run |  |  |  |
| Frontend env reviewed and contains public `VITE_*` values only | Not run |  |  |  |
| Frontend bundle/config search found no backend-only secret names or values | Not run |  |  |  |

## 4. Deployment Protection Checklist

Stakeholder UAT is GO only if the URL is intentionally access-controlled. Acceptable controls include Vercel deployment protection, SSO/password protection, IP allowlisting, or another documented access gate approved for this UAT.

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Frontend UAT URL requires the chosen access gate before app load | Not run |  |  |  |
| Backend UAT API URL is not broadly usable without app auth | Not run |  |  |  |
| Shared links and access list are limited to intended stakeholders | Not run |  |  |  |
| Access gate failure does not reveal app data | Not run |  |  |  |

## 5. Supabase Database And Migration Smoke

Use `docs/5b_g_supabase_migration_smoke_plan.md` as the source checklist. Do not run RLS enablement, RLS policy SQL, broad grants changes, or production-data migration as part of 5B-H-C.

Required evidence:

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Target database confirmed as staging/disposable UAT or otherwise approved | Not run |  |  |  |
| Alembic migration smoke completed or existing schema verified against head | Not run |  |  |  |
| Seed smoke completed where required for UAT | Not run |  |  |  |
| `external_residents` and `external_attendance_records` exist | Not run |  |  |  |
| `users.supabase_user_id` uniqueness exists | Not run |  |  |  |
| `programmes.compliance_variant` remains absent | Not run |  |  |  |
| `attendance_records.session_type_id` remains absent | Not run |  |  |  |
| Native resident auth mapping path is present | Not run |  |  |  |
| No 5B-H migration was introduced for this smoke | Not run |  |  |  |

## 6. First Master Admin Bootstrap Smoke

Use `docs/5b_g_staff_bootstrap_runbook.md`. The bootstrap operator must not paste passwords, service-role keys, or Supabase Auth tokens into this document.

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| First Supabase Auth staff user created or selected for UAT | Not run |  |  |  |
| Matching `users` row linked by `supabase_user_id` | Not run |  |  |  |
| `role='admin'`, `admin_level='master'`, `programme_scope=[]`, and active state verified | Not run |  |  |  |
| Master Admin can sign in from deployed frontend | Not run |  |  |  |
| Master Admin can reach staff-account bootstrap UI/API | Not run |  |  |  |
| Failed or non-master staff account cannot access Master Admin-only surfaces | Not run |  |  |  |

## 7. Auth Role Smoke Tests

Use UAT-safe test accounts and resident records only.

| Role/path | Check | Result | Operator | Date | Notes |
|---|---|---|---|---|---|
| Staff | Supabase email/password sign-in succeeds for linked active staff user | Not run |  |  |  |
| Staff | `/auth/me` returns role/scope from backend DB, not Supabase `user_metadata` | Not run |  |  |  |
| Master Admin | Can access Master Admin-only config/staff surfaces | Not run |  |  |  |
| Programme PC | Can access only programme-scoped admin data | Not run |  |  |  |
| Programme PC | Cannot access programmes outside `programme_scope` | Not run |  |  |  |
| Secretary | Can manage only the verified posting scope | Not run |  |  |  |
| Secretary | Cannot create an event outside posting scope | Not run |  |  |  |
| NHG Resident | MCR-only login returns a backend-signed MATA resident session | Not run |  |  |  |
| NHG Resident | Resident APIs are scoped to authenticated resident id | Not run |  |  |  |
| Non-NHG Resident | Registration rejects duplicate MCR present in native or external table | Not run |  |  |  |
| Non-NHG Resident | Login/submission uses external tables and is excluded from NHG compliance | Not run |  |  |  |
| Raw headers | Raw `X-User-*` identity headers alone are rejected in production/Supabase mode | Not run |  |  |  |

## 8. CORS And Security Header Smoke

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Approved frontend UAT origin can call backend API | Not run |  |  |  |
| Unapproved origin does not receive permissive CORS response | Not run |  |  |  |
| Production backend rejects wildcard `CORS_ORIGINS=*` configuration | Not run |  |  |  |
| Responses include HSTS, frame denial, content-type nosniff, referrer policy, and CSP headers | Not run |  |  |  |
| Auth failures and server errors do not expose stack traces, SQL, paths, tokens, or secrets | Not run |  |  |  |

## 9. Supabase Data API Boundary Smoke

The frontend must stay backend-mediated for MATA app data during this protected UAT cut. If direct browser access to sensitive Supabase app tables is found, stakeholder UAT is NO-GO until exposure is mitigated.

| Check | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Frontend source/bundle has no `supabase.from(...)` or `supabase.rpc(...)` app-table calls | Not run |  |  |  |
| Browser devtools/network shows no direct Supabase Data API calls to sensitive MATA tables | Not run |  |  |  |
| Supabase project exposed schemas/API settings reviewed for app-table exposure | Not run |  |  |  |
| Direct table query with browser/public key cannot read sensitive app data | Not run |  |  |  |
| Any exception or accepted exposure is documented with owner-approved mitigation | Not run |  |  |  |

## 10. Functional UAT Smoke

Run only against UAT-safe fixtures.

| Workflow | Result | Operator | Date | Notes |
|---|---|---|---|---|
| Backend health endpoint responds without sensitive details | Not run |  |  |  |
| Admin upload rejects invalid extension | Not run |  |  |  |
| Admin upload rejects oversized payload | Not run |  |  |  |
| Public holiday upload populates expected public holiday/month boundary data if fixture is available | Not run |  |  |  |
| RDB upload smoke completes if fixture is available | Not run |  |  |  |
| TTF upload smoke completes if fixture is available | Not run |  |  |  |
| FormF1 upload smoke completes if fixture is available | Not run |  |  |  |
| Secretary teaching event creation works on non-public-holiday date | Not run |  |  |  |
| Secretary teaching event creation is blocked on public holiday date | Not run |  |  |  |
| Resident scheduled attendance submission stores one native record and blocks duplicate | Not run |  |  |  |
| Resident ad-hoc submission is blocked on public holiday date | Not run |  |  |  |
| Non-NHG submission stores external attendance only | Not run |  |  |  |
| Secretary CSV export opens as text and formula-leading teaching names are neutralized | Not run |  |  |  |

## 11. Evidence Template

Use this table for each smoke command or manual action. Do not include secret values.

| Evidence ID | Area | Command/action | Result | Operator | Date/time | Artifact/link | Notes |
|---|---|---|---|---|---|---|---|
|  | Deployment protection |  | Not run |  |  |  |  |
|  | Env separation |  | Not run |  |  |  |  |
|  | Migration smoke |  | Not run |  |  |  |  |
|  | Master Admin bootstrap |  | Not run |  |  |  |  |
|  | Auth role smoke |  | Not run |  |  |  |  |
|  | CORS/security headers |  | Not run |  |  |  |  |
|  | Supabase Data API boundary |  | Not run |  |  |  |  |
|  | Functional smoke |  | Not run |  |  |  |  |

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

NO-GO if any of the above is false, unknown, or not run.

## 13. Rollback

- Disable or restrict the Vercel deployment link.
- Revoke stakeholder access to the protected deployment gate.
- Rotate any credential suspected to have been exposed.
- Disable affected Supabase Auth test users if account linkage is wrong.
- Revert the Vercel deployment to the previous known-safe build if app behavior regresses.
- Restore the UAT database from a known-safe snapshot if smoke data corrupts the database.
- Document the rollback trigger, operator, time, and follow-up owner without pasting secrets.
