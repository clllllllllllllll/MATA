# MATA — Monitoring and Analysing of Teaching Attendances

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
| `MATA_DATABASE_RLS_ENABLED` | Enables the complete restricted-role/RLS contract; required in production | `false` |
| `MATA_DATABASE_RUNTIME_ROLE` | Stable protected-query capability group; must remain `mata_app_runtime` | `mata_app_runtime` |
| `MATA_DATABASE_AUTH_ROLE` | Stable narrow auth-helper capability group; must remain `mata_auth_internal` | `mata_auth_internal` |
| `DATABASE_URL` | Async PostgreSQL URL using the restricted runtime login when RLS is enabled | `postgresql+asyncpg://<runtime-login>:<runtime-password>@<database-host>/<database-name>` |
| `MATA_AUTH_DATABASE_URL` | Async PostgreSQL URL using the distinct auth-helper login when RLS is enabled | `postgresql+asyncpg://<auth-login>:<auth-password>@<database-host>/<database-name>` |
| `SYNC_DATABASE_URL` | Sync PostgreSQL URL using the distinct migration/ownership login | `postgresql://<owner-login>:<owner-password>@<database-host>/<database-name>` |
| `SUPABASE_URL` | Reviewed backend Supabase project origin; production requires exact HTTPS `*.supabase.co` origin syntax | `https://<project-ref>.supabase.co` |
| `SUPABASE_JWT_ISSUER` | Optional explicit JWT issuer; production requires the same project origin and `/auth/v1` | `https://<project-ref>.supabase.co/auth/v1` |
| `SUPABASE_JWKS_URL` | Optional explicit JWKS URL; production requires the same project origin and exact Auth JWKS path | `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` |
| `SUPABASE_PUBLISHABLE_KEY` | Backend-used key for mediated staff authentication and legacy verification | `<placeholder>` |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend-only Supabase Admin/service-role key | `<server-only-service-role-key>` |
| `MATA_SESSION_HASH_KEY` | Backend-only keyed-digest secret; minimum 32 characters | `<backend-only-random-value>` |
| `MATA_ALLOWED_HOSTS` | Explicit accepted Host values | `localhost,127.0.0.1,testserver` |
| `MATA_STAFF_IDLE_TIMEOUT_SECONDS` | Master Admin, Programme Coordinator, and Secretary idle timeout | `1800` |
| `MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS` | Master Admin, Programme Coordinator, and Secretary absolute timeout | `28800` |
| `MATA_RESIDENT_IDLE_TIMEOUT_SECONDS` | NHG and registered Non-NHG Resident idle timeout | `3600` |
| `MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS` | NHG and registered Non-NHG Resident absolute timeout | `43200` |
| `MATA_SESSION_ROTATION_SECONDS` | Refresh hint/rotation interval; rotation extends neither the current idle deadline nor absolute expiry | `900` |
| `MATA_SESSION_TOUCH_INTERVAL_SECONDS` | Minimum interval between qualifying-activity idle-expiry writes | `60` |
| `MATA_SESSION_CLEANUP_RETENTION_SECONDS` | Retention after revocation/effective expiry before cleanup eligibility | `604800` |
| `MATA_SESSION_CLEANUP_BATCH_SIZE` | Maximum rows deleted by one cleanup call | `500` |
| `MATA_CSRF_HEADER_NAME` | Synchronizer-token request header | `X-CSRF-Token` |
| `MAX_REQUEST_BODY_SIZE_MB` | Hard application cap for every HTTP request body | `4` |
| `MAX_UPLOAD_REQUEST_SIZE_MB` | Aggregate multipart cap for `/admin/upload/*` requests | `4` |
| `MAX_UPLOAD_SIZE_MB` | Per-file reader/workbook cap; must be lower than the upload-request cap | `3` |
| `RATE_LIMIT_STORE` | `postgres` is required in production | `memory` |
| `RATE_LIMIT_HASH_SECRET` | Backend-only HMAC secret; minimum 32 characters | `<backend-only-random-value>` |
| `MATA_RESIDENT_SESSION_SECRET` | Rollback-only bearer compatibility secret; minimum 32 UTF-8 bytes | `<rollback-only-placeholder>` |

The opaque application credential is intentionally issued as a
non-persistent browser-session cookie with no `Max-Age` or `Expires`.
PostgreSQL idle and absolute deadlines are the sole expiry authority.

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
| `docs/00_project_context.md` | Project orientation, documentation authority, and implementation status |
| `docs/schema.md` | Database schema — all tables, columns, constraints, and relationships |
| `docs/api.md` | API endpoints — routes, request/response shapes, auth requirements |
| `docs/business-logic.md` | Compliance engine, surplus chain, tag-based reallocation, exception handling |
| `docs/parsing.md` | RDB and TTF Excel upload parsing rules and edge cases |
| `docs/auth-account-contract.md` | Current identity, account, and session-lifecycle contract |
| `docs/security.md` | Current cross-cutting security contract, locally verified controls, deployment assumptions, and deferred debt |
| `docs/99_decision_log_and_gap_audit.md` | Architectural decisions, accepted trade-offs, unresolved gaps, and superseded history |
| `docs/archive/security/phase-5b/README.md` | Historical Phase 5B security, migration, UAT, and verification records |
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

Unsafe cookie-authenticated requests require the session-bound `X-CSRF-Token`.
Logout clears local identity, CSRF, protected state, and authenticated UI
immediately. Server revocation is described as confirmed only after the
backend returns its proof-positive confirmation field; otherwise the frontend
remains explicitly logout-pending/unconfirmed and blocks hydration and
protected requests. A successfully committed replacement login may resolve the
matching pending lifecycle, but does not confirm that the previous server
session was revoked. Rotation, proof-positive logout, password reset, account
changes, expiry, and revocation invalidate server-side session state.
Production bearer compatibility is disabled unless the narrowly scoped
rollback flag is explicitly enabled.

The effective session deadline is the earlier of its sliding inactivity
deadline and its fixed family absolute deadline; equality is expired. Only a
successful protected user mutation can qualify for interval-gated activity.
Refresh rotates the opaque credential and CSRF value but extends neither the
current idle deadline nor the family absolute deadline. Continuing after
either expiry requires a full login. The example durations above are not
approved production policy; the organisation and operations owner must
approve explicit deployed values.

With H-E RLS enabled, protected application SQL uses a credentialed login that inherits only the `mata_app_runtime` capability. Public authentication and registration helpers use a different login that inherits only `mata_auth_internal`; Alembic uses the separate table-owning migration credential. All three URLs must reach the same database, and startup fails closed unless the exact role, ownership, helper, policy, grant, sequence, default-ACL, `PUBLIC`, and browser-role catalogue is present.

Resident ad-hoc creation uses a narrow database function that derives the
verified native/Non-NHG subject, persists immutable creator ownership, and
creates the event plus matching attendance in the caller transaction. Removed
attendance rows are retained; resubmission creates a new active row so stale
removal identifiers cannot affect newer evidence.

Staff login, Resident login, registration options, and Non-NHG registration are intentionally public entry points. Application authentication, authorization, rate limiting, CSRF, and session controls protect them; a Vercel outer gate is not required by the H-D design.

Resident identity assurance remains separately governed product debt. Do not
invent a second factor or claim workflow outside an approved product scope.

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

MATA remains in active phased development. `docs/security.md` is the current
cross-cutting security contract. The Phase 5B security archive contains dated
implementation, migration, UAT, and audit evidence, not competing current
specifications. `docs/99_decision_log_and_gap_audit.md` remains the current
architectural decision and gap history.
The approved Vercel product contract caps each uploaded file at 3 MiB and the
complete multipart or other request body at 4 MiB, below the platform's
separate 4.5 MB Function ceiling. Larger-file support requires a separately
approved ingress and is not implemented here. Phase 6 compliance remains
separate. Local code completion is not proof that migrations, roles, policies,
grants, lifecycle settings, request limits, or configuration are deployed to
Vercel/Supabase.

---

## Contributing

This is an internal NHG project. For questions or access, contact the MATA development team.
