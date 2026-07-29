# 5B-H-B UAT Security Fix Log

> **Current contract:** `docs/security.md`. This file is retained as dated fix
> evidence and does not override the current security contract.

Status: 5B-H-B fixes implemented and verified locally
Last updated: 2026-07-06

## Scope

This log records the minimal high-priority local-code fixes from `docs/archive/security/phase-5b/5b_h_uat_security_audit.md`. It does not claim that Vercel or Supabase UAT has been deployed, protected, migrated, or manually smoke-tested.

No RLS enablement, RLS policy SQL, database migrations, Phase 6 compliance logic, final close, snapshots, clawback, dependency upgrades, or secret changes were made.

## Fixed Findings

| Finding | Status | Files changed | What changed | Residual risk |
|---|---|---|---|---|
| H-UPLOAD-001 | Fixed | `backend/app/services/parser_common.py`, `backend/app/routers/admin.py`, `backend/tests/test_upload_plumbing.py` | `validate_upload_payload` now accepts `max_size_bytes` and rejects oversized bytes before workbook readability checks or parser execution. RDB, TTF, FormF1, and public holiday upload routes pass `settings.max_upload_size_bytes`. A regression test verifies the route rejects an oversized body even when the middleware `Content-Length` guard is not part of the test app. | Deep XLSX ZIP/XML bomb hardening remains deferred for a later, explicit task. |
| H-EXPORT-001 | Fixed | `frontend/src/pages/secretary/SecretaryTeachingSchedulePage.tsx`, `frontend/src/authSession.contract.test.ts` | Secretary schedule CSV export now sanitizes values whose trimmed leading character is `=`, `+`, `-`, or `@` by prefixing an apostrophe before CSV quoting. The frontend contract test asserts the sanitizer remains present. | Other future browser-generated exports must use the same pattern when added. |

## Verification

Commands run locally:

| Command | Working directory | Result |
|---|---|---|
| `git diff --check` | repo root | Passed |
| `python -m pytest tests/test_upload_plumbing.py -q --tb=short` | `backend` | Passed: 26 tests |
| `python -m compileall app tests` | `backend` | Passed |
| `npm run typecheck` | `frontend` | Passed |
| `npm run build` | `frontend` | Passed; Vite reported the existing large-chunk warning |
| `node --experimental-strip-types src/authSession.contract.test.ts` | `frontend` | Passed |

## Remaining UAT Blockers

The following items still require 5B-H-C manual smoke evidence before stakeholder UAT:

- Vercel deployment protection is enabled and tested.
- Backend UAT runs with `ENV=production` and `AUTH_MODE=supabase`.
- CORS is set to exact approved frontend origins only.
- First Master Admin bootstrap is executed according to the 5B-G runbook.
- Supabase migration smoke is executed against the staging/disposable UAT database.
- Supabase browser/Data API exposure is manually checked; stakeholder UAT must stop if direct sensitive app-table access is found.

## Explicit Deferrals

- Cookie/BFF/CSRF session transport hardening is deferred to 5B-H-D planning and a later implementation task.
- Full RLS policies, RLS enablement, and Supabase grants changes remain deferred.
- Redis/platform-backed rate limiting remains deferred for broader production/public use.
- Dependency advisory scans and broad dependency upgrades remain deferred unless a high/critical issue is confirmed.
