# 5B-I Local Security Fixes

> **Current contract:** `docs/security.md`. This file is retained as dated local
> fix evidence and does not override the current security contract.

## Summary

Phase 5B-I-B resolved the local frontend dependency blockers before the Vercel/Supabase POC deployment setup. The backend was also checked for Vercel compatibility and given a minimal backend-root Vercel entrypoint that reuses the existing FastAPI app.

## Dependency Advisory Fixes

Initial `npm audit --audit-level=high` reported high advisories in:

- `axios`
- `form-data`
- `react-router`
- `vite`

The same audit output also showed a low `@babel/core` advisory and a moderate `brace-expansion` advisory, both of which were cleared by narrow lockfile refreshes.

Updated direct frontend dependencies:

- `axios`: `^1.15.2` to `^1.16.0`
- `react-router-dom`: `^7.14.2` to `^7.15.1`
- `vite`: `^8.0.10` to `^8.0.16`

Updated advisory-related transitive packages in `package-lock.json`:

- `form-data`: `4.0.5` to `4.0.6`
- `react-router`: `7.14.2` to `7.15.1`
- `@babel/core`: `7.29.0` to `7.29.7`
- `brace-expansion`: `5.0.5` to `5.0.7`

Final advisory status:

- `npm audit --audit-level=high`: `found 0 vulnerabilities`
- `npm audit --json --audit-level=high`: `total: 0`, `high: 0`, `critical: 0`

## Vercel Backend Compatibility

No existing Vercel config or Vercel API entrypoint was found for the backend.

Added:

- `backend/api/index.py`
- `backend/vercel.json`

The Vercel entrypoint imports `app` from `app.main`, so it uses the same FastAPI instance created by `create_app()` with the existing auth, security-header, rate-limit, upload-guard, CORS, error-handler, and router setup. It does not create a second FastAPI app and does not run Alembic migrations.

The backend Vercel project should use `backend` as its project root so Vercel sees `backend/requirements.txt`, `backend/api/index.py`, and `backend/vercel.json`.

## Files Changed

- `frontend/package.json`
- `frontend/package-lock.json`
- `backend/api/index.py`
- `backend/vercel.json`
- `docs/5b_i_local_security_fixes.md`

## Tests And Checks Run

- `cd frontend && npm audit --audit-level=high`
- `cd frontend && npm audit --json --audit-level=high`
- `cd frontend && npm install`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- `cd frontend && npm run lint`
- `cd frontend && node --experimental-strip-types src/authSession.contract.test.ts`
- `cd backend && python -m compileall app tests`
- `cd backend && python -m compileall api`
- `cd backend && python -m pytest tests/test_auth_modes.py tests/test_auth_supabase.py tests/test_auth_resident.py tests/test_external_auth.py -q --tb=short`
- `cd backend && python -m pytest tests/test_upload_plumbing.py -q --tb=short`
- `cd backend && python -m pytest -q --tb=short` was attempted as an extra check but timed out after 244 seconds; focused backend security/upload suites passed.

## Explicit Non-Actions

- No deployment performed.
- No Vercel dashboard configured.
- No Supabase dashboard configured.
- No RLS enabled.
- No policy SQL added.
- No real secrets added.
- Phase 6 compliance not started.
