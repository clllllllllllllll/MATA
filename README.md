# MATA — Medical Attendance Tracking Application

MATA is a web application that tracks medical resident attendance at teaching events across hospital postings, calculates compliance against programme-specific targets, and manages surplus session reallocation. It replaces a legacy system built on FormSG CSV exports and R scripts.

---

## Overview

Residents in medical training programmes are required to attend a minimum number of teaching sessions per posting to meet their 70% compliance threshold. MATA automates this tracking across 28 residency programmes, multiple hospital sites, and two six-month reporting periods per year.

**Key capabilities:**
- Upload resident posting schedules (RDB) and teaching targets (TTF) per programme
- Secretary-managed teaching event scheduling per posting site
- Resident attendance submission portal with automatic compliance calculation
- Programme Coordinator reporting views — monthly, posting-level, and attendance breakdown
- Tag-based surplus reallocation across session types within a posting

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.12+), SQLAlchemy 2.0 (async), Alembic |
| Frontend | React (Vite + TypeScript) |
| Database | PostgreSQL (local dev → Supabase hosted) |
| Auth | Backend-owned opaque PostgreSQL sessions; backend-mediated Supabase staff authentication |

---

## Getting Started

### Docker Compose (Full Stack)

From repo root:

```bash
docker compose up --build
docker compose exec backend alembic upgrade head
```

Open:
- Frontend (Nginx): `http://localhost:8080`
- Backend direct health: `http://localhost:8000/health`
- Backend proxied health via frontend/Nginx: `http://localhost:8080/health`

Notes:
- Docker frontend build uses `VITE_API_BASE_URL=/api/v1` and reaches backend via Nginx proxy.
- Local Vite development can still use `http://localhost:8000/api/v1` directly.

### Prerequisites

- Python 3.12+
- Node.js 22.22+
- PostgreSQL 15+ (or a Supabase project)

### Backend Setup

```bash
# Clone the repo
git clone <repo-url>
cd mata/backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp ../.env.example .env
# Edit .env with your DATABASE_URL and other settings

# Run migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd mata/frontend

# Install dependencies
npm ci

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your VITE_API_BASE_URL

# Start the development server
npm run dev
```

The backend runs on `http://localhost:8000` and the frontend on `http://localhost:5173` by default.

---

## Environment Variables

### Backend (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `ENV` | `development`, `test`, or `production` | `development` |
| `AUTH_MODE` | `stub`, `demo`, or `supabase` | `stub` |
| `AUTH_TRANSPORT` | Normal app transport; `cookie` is required for production | `cookie` |
| `DATABASE_URL` | Backend-only async PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost/mata` |
| `SYNC_DATABASE_URL` | Backend-only sync PostgreSQL URL for Alembic | `postgresql://user:pass@localhost/mata` |
| `SUPABASE_URL` | Backend Supabase project URL for Supabase mode | `https://<project-ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Backend-used key for mediated staff authentication and legacy verification | `<placeholder>` |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend-only Supabase Admin/service-role key | `<server-only-service-role-key>` |
| `MATA_SESSION_HASH_KEY` | Backend-only keyed-digest secret; minimum 32 characters | `<backend-only-random-value>` |
| `MATA_ALLOWED_HOSTS` | Explicit accepted Host values | `localhost,127.0.0.1,testserver` |
| `MATA_STAFF_IDLE_TIMEOUT_SECONDS` | Staff idle timeout | `1800` |
| `MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS` | Staff absolute timeout | `28800` |
| `MATA_RESIDENT_IDLE_TIMEOUT_SECONDS` | Resident idle timeout | `3600` |
| `MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS` | Resident absolute timeout | `43200` |
| `MATA_SESSION_ROTATION_SECONDS` | Refresh hint/rotation interval | `900` |
| `MATA_CSRF_HEADER_NAME` | Synchronizer-token request header | `X-CSRF-Token` |
| `RATE_LIMIT_STORE` | `postgres` is required in production | `memory` |
| `RATE_LIMIT_HASH_SECRET` | Backend-only HMAC secret; minimum 32 characters | `<backend-only-random-value>` |
| `MATA_RESIDENT_SESSION_SECRET` | Rollback-only bearer compatibility secret; minimum 32 UTF-8 bytes | `<rollback-only-placeholder>` |

### Frontend (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API base URL; production is same-origin | `/api/v1` |
| `VITE_AUTH_MODE` | Frontend auth mode | `stub` |

All `VITE_*` variables are public browser-exposed values. The production browser needs no Supabase URL/key. Never put backend secrets, database credentials, signing keys, or session/rate-limit secrets in frontend env files or Vite build args.

---

## System Roles

| Role | Auth | Scope |
|------|------|-------|
| **Admin (Programme Coordinator)** | Email + password | Programme-scoped. Manages RDB/TTF uploads, teaching targets, reporting views. |
| **Department Secretary** | Email + password | Scoped to one posting site. Creates and manages teaching events. |
| **Resident** | MCR number only (Phase 1) | Views and submits attendance for their current posting and native programme posting. |

---

## How the System Works

### Initialisation Order

Each step is a hard dependency on the previous:

1. **Admin uploads RDB** (Posting Schedule) → residents, postings, and rotation schedule are created
2. **Admin uploads TTF** (Teaching Target File) → session types, compliance targets, and secretary dropdowns are seeded per programme
3. **Secretary creates teaching events** → events become visible in the resident portal
4. **Resident submits attendance** → compliance engine calculates targets and traffic light status

### Compliance Model

- Compliance is measured in **session counts, not hours** — 1 session = 1 session regardless of duration
- The **70% threshold is at the posting level**, aggregated across all session types for that posting
- Session type is **not stored on attendance records**. It is resolved at compliance read time via teaching_name_catalogue using full context (posting, programme, r_year, reporting period).
- Surplus sessions accumulate per `(resident, posting, session_type)` and hibernate when the resident rotates away; they resume on return and reset at each reporting period boundary
- Tag-based reallocation allows longer-duration surplus to fill shorter-duration shortfall within the same tag group at a posting

---

## Project Documentation

All technical specifications live in `docs/`:

| File | Contents |
|------|----------|
| `docs/schema.md` | Database schema — all tables, columns, constraints, and relationships |
| `docs/api.md` | API endpoints — routes, request/response shapes, auth requirements |
| `docs/business-logic.md` | Compliance engine, surplus chain, tag-based reallocation, exception handling |
| `docs/parsing.md` | RDB and TTF Excel upload parsing rules and edge cases |
| `AGENTS.md` | Architectural rules, TBD items, confirmed decisions — read before coding |

---

## Development Notes

### Auth and session transport

In `AUTH_MODE=stub` or local `AUTH_MODE=demo`, identity is passed via request headers for local development and tests only:

```
X-User-Role: admin | secretary | resident | external_resident
X-User-Id: <users.id for admin/secretary> | <residents.id for resident> | <external_residents.id for external_resident>
X-User-Site: <posting_code>        # secretary only
X-User-Programme: <programme_code> # admin/resident
```

Normal Supabase/production operation uses `AUTH_TRANSPORT=cookie`. Staff credentials are submitted to the backend, which mediates Supabase Auth and maps the verified subject to database-owned role and scope. NHG Resident and Non-NHG Resident login is also backend-mediated. Every role receives a backend-owned opaque application session through an `HttpOnly` cookie; raw app access tokens and refresh tokens are not stored in browser storage or sent on normal application requests.

Unsafe cookie-authenticated requests require the session-bound `X-CSRF-Token`. Logout, rotation, password reset, account changes, expiry, and revocation invalidate server-side session state. Production bearer compatibility is disabled unless the narrowly scoped rollback flag is explicitly enabled.

Staff login, Resident login, registration options, and Non-NHG registration are intentionally public entry points. Application authentication, authorization, rate limiting, CSRF, and session controls protect them; a Vercel outer gate is not required by the H-D design.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED

Frontend route guards are UX only; backend authorization remains authoritative.

### Running Tests

```bash
cd backend
python -B -m compileall app tests
python -B -m pytest -q --tb=short -p no:cacheprovider
```

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

---

## Project Status

MATA remains in active phased development. Phase 5B-H-D session transport and production-security hardening is implemented and locally verified; see `docs/5b_h_d_production_security_implementation.md`. Full PostgreSQL RLS is Phase 5B-H-E, and Phase 6 compliance remains separate. Local code completion is not proof of deployed Vercel/Supabase controls.

---

## Contributing

This is an internal NHG project. For questions or access, contact the MATA development team.
