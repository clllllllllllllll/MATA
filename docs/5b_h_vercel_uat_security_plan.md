# 5B-H Vercel UAT Security Plan

Status: 5B-H-A/B/C retained as historical UAT work; 5B-H-D implemented and locally verified; deployment verification and 5B-H-E RLS pending

Last updated: 2026-07-26

## 1. Purpose

This plan records the security path from the historical protected H-C UAT posture through H-D session hardening. H-D intentionally keeps staff login, Resident login, registration options, and Non-NHG registration public as application entry points; a Vercel outer gate is not an application-auth requirement. Application authentication, exact-origin/CSRF handling, persistent rate limiting, secure cookie transport, and authorization remain mandatory.

Related 5B-H outputs:

- `docs/5b_h_uat_security_audit.md`
- `docs/5b_h_uat_security_fix_log.md`
- `docs/5b_h_vercel_supabase_uat_smoke.md`
- `docs/5b_h_session_transport_hardening_plan.md`
- `docs/5b_h_d_production_security_implementation.md`

## 2. Scope

5B-H covers:

- Vercel deployment protection.
- Frontend environment safety.
- Backend production auth mode.
- CORS allowlist.
- Supabase table/Data API exposure review.
- Clean Supabase migration smoke.
- First Master Admin bootstrap.
- Deployment smoke tests.
- Minimal UAT security fixes.
- Implemented H-D session hardening and browser-role privilege revocation.
- Dedicated H-E full RLS implementation and verification.

## 3. Non-goals

- No Phase 6 compliance implementation.
- No full RLS enablement in 5B-H-A/B/C/D.
- Full RLS policy SQL belongs to Phase 5B-H-E.
- No broad dependency upgrades unless there is a high/critical security issue.
- No app-wide refactor.
- No real secrets in docs.
- No production data in screenshots, logs, docs, or copied command output.

## 4. Threat Model For Stakeholder UAT

Prioritize these risks:

- Abuse of intentionally public authentication and registration entry points.
- Stolen or browser-exposed bearer tokens.
- Raw header spoofing.
- CORS misconfiguration.
- Leaked environment secrets.
- Direct Supabase table/Data API exposure.
- Role/scope escalation.
- IDOR across Master Admin, Programme PC, secretary, NHG Resident, and Non-NHG Resident endpoints.
- Upload parser abuse, oversized workbooks, or malicious workbook payloads.
- Formula injection in exports.
- Sensitive error or log leakage.
- Brute-force login or registration abuse.

## 5. 5B-H-A - Vercel UAT Security Audit And Minimal Deployment Hardening Plan

Expected output:

- Findings table.
- Severity.
- Affected file/config.
- Risk.
- Recommended minimal fix.
- Verification.
- Go/no-go decision for stakeholder UAT.

Audit checklist:

- Authentication and session handling.
- Authorization and scope enforcement.
- Raw header rejection in production.
- Secrets and env separation.
- CORS and security headers.
- Rate limiting.
- Upload validation and resource exhaustion.
- Error/log redaction.
- Dependency scan.
- XSS/output encoding.
- Formula-injection export protection.
- CSRF readiness.
- Supabase Data API/grants exposure.
- Vercel deployment protection.
- Deployment smoke test coverage.

## 6. 5B-H-B - Minimal UAT Security Fixes

This subphase fixes only blockers found in 5B-H-A. It should stay small and deployment-focused so stakeholder UAT is not delayed by unrelated refactors.

Likely candidates:

- Production CORS allowlist.
- Security headers.
- Rate-limit config hardening.
- Error/log redaction.
- Upload size/type guardrails.
- Formula-injection export protection.
- Frontend env cleanup.
- Backend production auth guardrails.

## 7. 5B-H-C - Supabase/Vercel UAT Deployment Smoke

This checklist is historical for the 2026-07-22 H-C deployment posture. Its mandatory outer-gate and bearer-era observations are preserved as point-in-time evidence and do not define the current H-D application boundary.

Smoke test list:

- Vercel protected deployment is enabled.
- Frontend loads from deployed URL.
- Backend health check works.
- Backend `ENV=production` and `AUTH_MODE=supabase`.
- `/auth/login` and `/auth/me` work for staff.
- Master Admin login works after bootstrap.
- Programme PC scope works.
- Secretary scope works.
- NHG Resident MCR login works.
- Non-NHG Resident registration/login works.
- Raw `X-User-*` headers are rejected.
- CORS blocks unapproved origins.
- No backend secrets are visible in frontend bundle/env.
- Supabase app tables are not directly queried from frontend.
- One upload flow is tested if staging fixtures are available.
- Resident submission flow is tested if staging data is available.

## 8. 5B-H-D - Full Session Transport Hardening

H-D is implemented in code and locally verified. It does not prove deployed Vercel or Supabase behavior.

Scope:

- Backend-owned opaque PostgreSQL sessions with keyed session and CSRF digests.
- Host-only `__Host-mata_session` with `HttpOnly`, `Secure`, `SameSite=Strict`, and `Path=/`.
- Exact production Origin checks and synchronizer CSRF on unsafe methods.
- One-winner rotation, session-family logout, idle/absolute expiry, and subject-generation fencing.
- Backend-mediated Supabase staff login; no upstream token returned to the browser.
- Same-origin relative `/api/v1`, credentialed requests, memory-only identity/CSRF, and removal of routine browser bearer transport.
- PostgreSQL persistent rate limiting, upload ZIP/XML hardening, and sensitive error/log redaction.
- Migration `20260722_000024` revocation of application-object privileges from `PUBLIC` and optional browser roles.

## 9. RLS/Grants Phase Boundary

RLS planning is complete from 5B-G-E. Full RLS enablement and policy SQL are not part of 5B-H-A/B/C/D.

Phase 5B-H-E must use `docs/5b_g_rls_grants_matrix.md`, a restricted non-owner runtime role, trusted transaction-local identity context, and a PostgreSQL policy test harness. Migration `20260722_000024` is grant hardening, not RLS.

## 10. Go/No-Go Criteria For Stakeholder UAT

The following list is retained as the historical H-C stakeholder-UAT criterion:

- Deployment URL is protected or otherwise intentionally access-controlled.
- Backend uses production Supabase auth mode.
- CORS is restricted.
- Frontend env has no backend-only secrets.
- Raw identity headers are rejected.
- First Master Admin bootstrap is complete in staging/UAT.
- Clean migration smoke passes or a controlled existing staging DB is verified.
- No direct browser access to sensitive app tables is found.
- High/critical security findings are fixed or explicitly accepted with documented mitigation.
- No compliance claims are presented as final.

For the current H-D design, intentionally public authentication entry points do not require an outer gate. Local H-D completion is not a claim that deployed cookie, origin, environment, migration, grant, or session behavior has been verified.

## 11. Verification Commands/Checks

The exact H-D commands, counts, migration verification, dependency audits, and source scans are recorded in `docs/5b_h_d_production_security_implementation.md`. Representative repository checks remain:

```powershell
git status --short --branch
git diff --check
python -m compileall app tests
python -m pytest <targeted-auth-security-tests> -q --tb=short
npm run typecheck
npm run build
rg -n "SUPABASE_SERVICE_ROLE_KEY|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|PRIVATE_KEY|DB_PASSWORD" frontend .github docker-compose.yml frontend\Dockerfile
rg -n "VITE_.*(SERVICE_ROLE|MATA_RESIDENT_SESSION_SECRET|DATABASE_URL|SYNC_DATABASE_URL|JWT_SECRET|PRIVATE_KEY|DB_PASSWORD)" .
```

Historical H-C manual checks:

- Manual Vercel env review.
- Manual Supabase grants/Data API review.
- Manual Vercel deployment protection review.
- Manual deployed-origin CORS check.
- Manual frontend bundle/env inspection for backend-only secret names.

Current H-D post-deployment checks instead verify that intentionally public entry points expose no protected data, the exact cookie/CSRF/Origin contract is active, no browser token is persisted or injected, production uses relative `/api/v1`, database revision/grant revocation is correct, and every protected workflow still requires authenticated application authorization. Deployment protection may be used operationally, but it is not an H-D application-auth requirement.

## 12. Explicit Deferrals

- Phase 6 compliance.
- Phase 5B-H-E full RLS policies and restricted runtime-role integration.
- Deployed cookie/origin/grant/session smoke.
- Resident second-factor approval.
- Final close/freeze.
- Period snapshots.
- Clawback.
- Historical migration.
- Production email/export features.
- Long-term SSO/corporate identity replacement.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED
