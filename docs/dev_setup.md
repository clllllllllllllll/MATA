# Development Setup (Docker)

Prerequisites: Python 3.12+, Node.js 22.22+, and PostgreSQL 15+.

## 1. Create local env file

```bash
cp .env.example .env
```

`.env` is local-only and must never be committed.

## 2. Start backend and database

```bash
docker compose up --build
```

## 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

## 4. Run backend tests

```bash
docker compose exec backend python -B -m compileall app tests
docker compose exec backend python -B -m pytest -q --tb=short -p no:cacheprovider
```

For local non-container verification, run the same commands from `backend/`.

## 5. Run frontend gates

From `frontend/`:

```bash
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

## 6. Run manual upload + view smoke verification

From repo root:

```bash
python backend/scripts/smoke_upload_and_view.py
```

This smoke flow verifies:
- backend upload endpoints for Academic Calendar / Public Holidays, RDB, TTF (DR + GRM), and FormF1
- persisted upload outputs are readable from admin view endpoints (`residents`, `resident_postings`, `posting_codes`, `session_types`, `teaching_targets`, `teaching_name_catalogue`, `form_f1_records`, `public_holidays`, `academic_month_boundaries`, `upload_logs`)

## 7. Run Phase 5A native resident flow smoke verification

From backend directory:

```bash
python scripts/smoke_phase5a_resident_flow.py
```

## 8. Run Phase 5B native resident UI smoke verification

Follow the browser checklist at:

`docs/manual_smoke_phase5b_native_resident_ui.md`

## 9. Security verification boundaries

Disposable PostgreSQL security and migration verification must use an explicitly named local database. Never load live credentials or point destructive verification at Supabase. Phase 5B-H-D used only `mata_phase5b_verify_5bhd`.

Registry-backed dependency audits are:

```bash
cd backend
python -m pip_audit -r requirements.txt --no-deps --disable-pip --strict

cd ../frontend
npm audit --omit=dev --audit-level=high
npm audit --audit-level=high
```

Use `.github/scripts/sanitize_dependency_audit.py` and the workflow contract in `.github/workflows/production-security.yml` for saved evidence. Raw registry JSON is temporary and must be deleted after the bounded sanitized report is produced.

Production configuration validation requires cookie transport, non-local PostgreSQL URLs, explicit HTTPS CORS origins, explicit allowed hosts, `RATE_LIMIT_STORE=postgres`, and backend-only session/rate-limit secrets of at least 32 characters. The production browser uses relative `/api/v1` and has no Supabase client configuration.

The implemented architecture, exact local verification counts, dependency disposition, rollback, and post-deployment checklist are in `docs/5b_h_d_production_security_implementation.md`. Local completion does not prove deployed behavior.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED
