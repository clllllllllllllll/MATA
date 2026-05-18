# Development Setup (Docker)

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
docker compose exec backend pytest -q
```

## 5. Run manual upload + view smoke verification

From repo root:

```bash
python backend/scripts/smoke_upload_and_view.py
```

This smoke flow verifies:
- backend upload endpoints for Academic Calendar / Public Holidays, RDB, TTF (DR + GRM), and FormF1
- persisted upload outputs are readable from admin view endpoints (`residents`, `resident_postings`, `posting_codes`, `session_types`, `teaching_targets`, `teaching_name_catalogue`, `form_f1_records`, `public_holidays`, `academic_month_boundaries`, `upload_logs`)
