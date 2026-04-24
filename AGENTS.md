# MATA — Medical Attendance Tracking Application

## Project Overview

MATA tracks medical resident attendance at teaching events across hospital postings, calculates compliance against programme-specific targets, and manages surplus session reallocation. It replaces a legacy system built on FormSG + R scripts.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.12+), SQLAlchemy 2.0 (async), Alembic |
| Frontend | React (Vite + TypeScript) |
| Database | PostgreSQL (local dev → Supabase hosted) |
| Auth | Stubbed middleware initially → Supabase Auth later |

## Repo Structure

```
mata/
├── AGENTS.md                  # This file
├── docs/
│   ├── schema.md              # Database schema — tables, columns, types, constraints
│   ├── api.md                 # API endpoints — routes, request/response shapes
│   ├── business-logic.md      # Compliance engine, surplus chain, reallocation rules
│   └── parsing.md             # RDB and TTF upload parsing rules and edge cases
├── backend/
│   ├── alembic/               # Database migrations
│   ├── app/
│   │   ├── main.py            # FastAPI app entry point
│   │   ├── config.py          # Settings (DB URL, env vars)
│   │   ├── database.py        # SQLAlchemy engine + session factory
│   │   ├── models/            # SQLAlchemy ORM models (one file per domain)
│   │   │   ├── resident.py
│   │   │   ├── posting.py
│   │   │   ├── programme.py
│   │   │   ├── teaching.py    # teaching_targets, session_types, teaching_events
│   │   │   ├── attendance.py
│   │   │   └── reporting.py   # reporting_periods, surplus_ledger
│   │   ├── routers/           # FastAPI routers (one file per domain)
│   │   │   ├── admin.py       # RDB upload, TTF upload, reporting views, period CRUD
│   │   │   ├── secretary.py   # Teaching event CRUD, CME dashboard
│   │   │   ├── resident.py    # Submission portal, dashboard, attendance CRUD
│   │   │   └── auth.py        # Auth stub (swap to Supabase Auth later)
│   │   ├── services/          # Business logic (no HTTP concerns)
│   │   │   ├── compliance.py  # 70% threshold, capping, traffic light
│   │   │   ├── surplus.py     # Surplus chain, tag-based reallocation
│   │   │   ├── rdb_parser.py  # RDB Excel upload parser
│   │   │   ├── ttf_parser.py  # TTF Excel upload parser
│   │   │   └── validation.py  # Duplicate/conflict detection, date checks
│   │   ├── schemas/           # Pydantic request/response models
│   │   └── middleware/        # Auth middleware, error handling
│   ├── tests/
│   ├── requirements.txt
│   └── alembic.ini
└── frontend/
    ├── src/
    │   ├── pages/             # Route-level page components
    │   ├── components/        # Shared UI components
    │   ├── hooks/             # Custom React hooks
    │   ├── api/               # API client functions
    │   ├── types/             # TypeScript type definitions
    │   └── utils/
    ├── package.json
    ├── vite.config.ts
    └── tsconfig.json
```

## Three System Roles

| Role | Auth Method | Scope |
|------|------------|-------|
| Admin (Programme Coordinator) | Email + password | Programme-scoped. Each account linked to one or more programmes via `programme_scope` field. Manages RDB, TTF, teaching targets, period close, all reporting views for their programmes only. |
| Department Secretary | Email + password | Scoped to ONE specific posting site (e.g. TTSHAnaes only). Creates teaching events, views CME Dashboard and Teaching Schedule. |
| Resident | MCR number only | Sees teachings for current posting only. Submission Portal + personal Dashboard. |

## Auth Stub (Phase 1)

Until Supabase Auth is integrated, use a simple middleware that reads role and identity from request headers:

```
X-User-Role: admin | secretary | resident
X-User-Id: <user_id or MCR>
X-User-Site: <posting_code>        # secretary only
X-User-Programme: <programme_code> # admin only, comma-separated for multiple e.g. DR,GRM
```

All endpoints check these headers for authorization. When Supabase Auth is wired in, the middleware is replaced — the rest of the app doesn't change.

## System Initialisation Order

This is a strict dependency chain. Each step requires the previous one to be complete.

1. **Admin uploads RDB** → residents, postings, rotation schedule created
2. **Admin uploads TTF** → session types, teaching targets, secretary dropdowns seeded
3. **Secretary creates teaching events** → events appear in resident portal
4. **Resident submits attendance** → compliance engine has data to calculate

## Key Architectural Rules

- **Session counts, not hours.** Compliance is measured in number of sessions attended. Duration is never a multiplier. 1 session = 1 session regardless of 0.5h or 3h.
- **70% threshold is at the POSTING level**, aggregated across all session types for that posting. Monthly percentages are display-only.
- **Surplus persists per (resident, department, session_type).** When a resident rotates away, surplus hibernates. When they return, it resumes. Surplus resets to zero at each reporting period boundary.
- **Tag-based reallocation flows top-down by duration only.** Longer-duration surplus can fill shorter-duration shortfall, never upward. One-for-one in session counts. Tag-group-only — surplus cannot flow across tag groups or across postings.
- **Teaching events are programme-neutral.** Secretary creates an event for a site; the compliance engine applies programme-specific TTF rules per resident.
- **UNIQUE constraint on (resident_id, event_id)** prevents duplicate attendance at the DB layer.
- **No STP in the system.** STP data ("Details of Training") is manually added to TTF before upload.
- **Admin accounts are programme-scoped.** A PC account only sees residents, targets, and reports for their assigned programmes.
- **LOA and Employed data is captured but not yet acted on.** LOA type/dates and employer_tag are stored at parse time. Compliance treatment pending PM confirmation — currently mirrors R system (status = 'active' only counts toward denominator).
- **Refresher Training data is captured but not yet acted on.** Annotation fields stored in resident_postings. Business logic pending PM confirmation.

## Reference Documents

Read these files in `docs/` before writing code for any domain:

| File | Read before working on |
|------|----------------------|
| `docs/schema.md` | Any model, migration, or database query |
| `docs/api.md` | Any router, endpoint, or Pydantic schema |
| `docs/business-logic.md` | Compliance engine, surplus chain, reallocation, any calculation |
| `docs/parsing.md` | RDB or TTF upload endpoints, Excel parsing |

## TBD — Awaiting PM Confirmation

The following features have placeholder logic pending PM decisions:

1. **Dormant posting codes** — canonical code correctness for sites not in current RDB pending PM confirmation. Handling confirmed: accept as-is, add to posting_codes with display_name = NULL. See `docs/parsing.md` § TBD-2.
2. **LOA compliance treatment** — whether LOA months reduce the compliance denominator. See `docs/business-logic.md` § TBD-7.
3. **Employed compliance treatment** — whether employed residents appear in compliance reporting. See `docs/business-logic.md` § TBD-7.
4. **Refresher Training compliance treatment** — active months denominator impact and Max Cand flag meaning. See `docs/business-logic.md` § TBD-6.
5. **Dual posting main posting rule** — formula determining main posting for dual-posted residents (e.g. IMHGrPsyc & TTSHPsychi). Compliance engine cannot handle dual postings correctly until this is confirmed.

## Confirmed Decisions (previously TBD)

| Item | Decision |
|------|----------|
| Admin scope | Programme-scoped via `users.programme_scope TEXT[]` |
| Surplus period boundary | Resets to zero at each reporting period boundary |
| Recurrence editing granularity | All three options: this event only / this and all following / all in series |
| Reallocation scope | Tag-group-only. No cross-tag or cross-posting flow. |
| Details of Training (TBD-1) | Keyword list confirmed by PMs (incoming). Matching logic: `teaching_name` primary key + `duration_hours` tiebreaker for edge cases. Session type resolved per-resident at attendance submission time using native programme TTF. `session_type_id` on `teaching_events` is display/prototype only. Resident sees events from both current posting and native programme posting. |