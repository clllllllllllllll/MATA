# 5B-H Vercel UAT Security Plan

Status: 5B-H-A and 5B-H-B complete; 5B-H-C checklist added; 5B-H-D pending

Last updated: 2026-07-06

## 1. Purpose

This plan defines the security work needed to deploy MATA to Vercel/Supabase for stakeholder UAT before Phase 6 compliance. It turns the completed 5B-G readiness docs into a deployment-focused security path: audit first, apply only necessary UAT blockers, smoke the protected deployment, then complete deeper session transport hardening before real production or public use.

Related 5B-H outputs:

- `docs/5b_h_uat_security_audit.md`
- `docs/5b_h_uat_security_fix_log.md`
- `docs/5b_h_vercel_supabase_uat_smoke.md`

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
- Later full session hardening.

## 3. Non-goals

- No Phase 6 compliance implementation.
- No RLS enablement in 5B-H-A/B/C.
- No RLS policy SQL.
- No broad dependency upgrades unless there is a high/critical security issue.
- No app-wide refactor.
- No real secrets in docs.
- No production data in screenshots, logs, docs, or copied command output.

## 4. Threat Model For Stakeholder UAT

Prioritize these risks:

- External unauthenticated access to the Vercel preview/prod URL.
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

This is the deeper follow-up after the deployment-safe cut. It must be completed before real production or public use.

Scope:

- Cookie/BFF transport.
- CSRF protection.
- `HttpOnly`, `Secure`, and `SameSite` cookies.
- Logout/session invalidation.
- Browser bearer-token replacement.
- Resident token storage replacement.
- Production hardening before public/real production use.

## 9. RLS/Grants Phase Boundary

RLS planning is complete from 5B-G-E. Full RLS enablement and policy SQL are not part of 5B-H-A/B/C.

A later dedicated RLS phase should use `docs/5b_g_rls_grants_matrix.md` and add a test harness before enabling RLS or changing grants. If 5B-H-A finds direct browser table access to sensitive tables, stop and treat that as a blocker requiring immediate grant/RLS/Data API mitigation before UAT.

## 10. Go/No-Go Criteria For Stakeholder UAT

Go only if:

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

## 11. Verification Commands/Checks

Placeholder commands/checks for future implementation phases:

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

Manual checks:

- Manual Vercel env review.
- Manual Supabase grants/Data API review.
- Manual Vercel deployment protection review.
- Manual deployed-origin CORS check.
- Manual frontend bundle/env inspection for backend-only secret names.

## 12. Explicit Deferrals

- Phase 6 compliance.
- Full RLS policies.
- Final close/freeze.
- Period snapshots.
- Clawback.
- Historical migration.
- Production email/export features.
- Long-term SSO/corporate identity replacement.
