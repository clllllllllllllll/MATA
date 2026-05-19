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
| Auth | Stubbed header middleware (Phase 1) → Supabase Auth (later) |

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
- Node.js 18+
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
cp .env.example .env
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
npm install

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
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost/mata` |
| `SECRET_KEY` | JWT signing secret | `your-secret-key` |
| `ENVIRONMENT` | `development` or `production` | `development` |

### Frontend (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API base URL | `http://localhost:8000/api/v1` |

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

### Auth (Phase 1)

Real JWT middleware is not yet wired in. Identity is passed via request headers for local development:

```
X-User-Role: admin | secretary | resident
X-User-Id: <uuid>
X-User-Site: <posting_code>        # secretary only
X-User-Programme: <programme_code> # admin/resident
```

### Running Tests

```bash
cd backend
pytest
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

MATA is currently in active development. The system is being built in phases — core data pipeline and compliance engine first, followed by reporting views, then the keyword-based teaching event matching layer (Phase 8a, pending PM-confirmed keyword catalogue across all 28 programmes).

**Open items pending PM confirmation:**
- LOA and Employed resident compliance treatment
- Refresher Training compliance treatment
- Dormant posting code canonicalisation (15 codes across GRM and DR)
- Dual posting main-posting rule

---

## Contributing

This is an internal NHG project. For questions or access, contact the MATA development team.
