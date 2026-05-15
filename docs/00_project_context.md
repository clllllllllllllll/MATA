# 00_project_context.md — MATA Dashboard Master Orientation Document

> **Purpose:** This is the master orientation and navigation document for the MATA (Medical Attendance Tracking Application) project. Read this file first before any of the five source-of-truth files. It summarises, cross-references, and highlights critical rules — it does not duplicate full table definitions or code blocks that already exist in the source-of-truth files.
>
> **Authority:** This document is a navigation aid. If it conflicts with `schema.md`, `api.md`, `business-logic.md`, `parsing.md`, or `AGENTS.md`, trust the domain-specific source-of-truth file and flag this document for update.

---

## Section 1 — Project Summary

### What MATA Dashboard Is

MATA Dashboard is a domain-specific web application for tracking medical resident attendance at teaching events across hospital postings in Singapore's NHG (National Healthcare Group) residency programmes. It calculates compliance against programme-specific targets, manages surplus session reallocation, and generates clawback reports for residents who fail to meet attendance thresholds.

### The Legacy System It Replaces

The previous system worked as follows:

```
Residents submit attendance via FormSG / Google Forms
  → CSV exports downloaded manually
  → R scripts A through F process the CSVs:
      Script A: Posting site resolution
      Script B: FormSG CSV ingestion, parsing, cleaning
      Script C: Compliance calculation, surplus chain, reallocation
      Script D: Report generation (Excel output)
      Script E: FM-specific report variant
      Script F: Clawback calculation
  → Output Excel files distributed manually to Programme Coordinators
```

**Why it is being replaced:** The legacy system relies on free-text form submissions requiring extensive string matching, manual CSV export, and batch R script processing. It is fragile, error-prone, and cannot scale. The new system eliminates free-text input via structured web forms, processes compliance in real time, and persists all data in a relational database.

### The New Architecture

```
Residents log in via React frontend (MCR-only auth in Phase 1)
  → See teaching events for their current posting(s) via the Submission Portal
  → Submit attendance directly via POST /resident/attendance
  → OR submit ad-hoc teaching via POST /resident/adhoc-teaching
  → FastAPI backend validates, persists to PostgreSQL
  → Compliance engine calculates JIT (just-in-time) on every read
  → Admin/PC views compliance reports via 5-tab dashboard
```

### Three User Roles

| Role | Identity | Scope | Primary Actions |
|------|----------|-------|-----------------|
| **Admin / Programme Coordinator (PC)** | Email + password (Phase 1 stub) | Programme-scoped via `users.programme_scope TEXT[]` | Upload RDB, TTF, FormF1, PH files; manage configuration; view compliance reports; close/reopen reporting periods |
| **Secretary** | Email + password (Phase 1 stub) | Scoped to ONE posting site via `users.posting_code` | Create/manage teaching events; view CME dashboard; view teaching schedule |
| **Resident** | MCR number only (no password in Phase 1) | Own data only; events filtered by current posting(s) | Submit attendance; submit ad-hoc teaching; view personal compliance dashboard |

### Reporting Periods

Six-month windows (H1: Jan–June, H2: Jul–Dec) stored in the `reporting_periods` table. Surplus resets to zero at each period boundary. Period close triggers hibernation, clawback generation, and frozen snapshot creation.

### The Four Upload Files

| File | Uploaded By | What It Contains | Tables Written |
|------|------------|-----------------|----------------|
| **RDB** (Resident Database / Posting Schedule) | Admin | Which resident is at which posting site by month | `residents`, `resident_postings`, `posting_codes` |
| **TTF** (Teaching Target File) | Admin (PC creates from STP) | Compliance targets: session types, monthly targets, keywords, tags | `teaching_targets`, `session_types`, `teaching_name_catalogue`, `posting_codes`, `posting_groups` |
| **FormF1** | Admin | Active/inactive status per resident per calendar month | `form_f1_records` |
| **Academic Calendar / Public Holidays** | Admin | Public holiday dates plus AY date boundaries (`Public Holidays` + `AY Dates` sheets; `Fr RMT` ignored) | `public_holidays`, `academic_month_boundaries` |

**STP (Structured Teaching Plan):** Created by Secretary. A planning document only. **STP is never uploaded to the system.** The PC manually converts STP to TTF before Admin uploads TTF. Column K (Details of Training / tag info) is absent from STP and must be added manually by PC — this is why conversion cannot be automated.

### Legacy Cutover

Hard cutover at a period boundary. FormSG and Google Forms submission channels are closed at that date. No hybrid operation — all attendance flows through this system only after cutover.

> **⚠️ Most likely LLM mistake:** Assuming STP is uploaded to the system, or that an STP parser exists. STP is never uploaded. TTF is the compliance input. If an LLM builds an STP upload endpoint, it wastes effort and creates confusion. The silent consequence is that column K (Details of Training) — which is mandatory for `teaching_name_catalogue` seeding — would be missing, breaking event visibility and session type resolution for all residents.

---

## Section 2 — How to Use This Document and the Reference Files

### Conflict Resolution

If this document (`00_project_context.md`) or `99_decision_log_and_gap_audit.md` conflicts with `schema.md`, `api.md`, `business-logic.md`, `parsing.md`, or `AGENTS.md`, **trust the domain-specific source-of-truth file**. This document is navigation only. `99_decision_log_and_gap_audit.md` is an audit trail. Neither overrides the source-of-truth files.

### Reading Order for Generating Migration Documents

1. Read `00_project_context.md` (this file) first
2. Then read all five source-of-truth files (`schema.md`, `api.md`, `business-logic.md`, `parsing.md`, `AGENTS.md`) before generating any output

### Reading Order for Coding Tasks

Before coding, always read `00_project_context.md` and `AGENTS.md`. Then read the relevant source-of-truth files:

| Task Type | Required Reading |
|-----------|-----------------|
| Schema changes, migrations, DB queries | `schema.md` |
| Endpoint, API, or Pydantic schema changes | `api.md` |
| Compliance, surplus, hibernation, reallocation, exceptions, thresholds | `business-logic.md` |
| RDB, TTF, FormF1, or PH upload parsing | `parsing.md` |
| Cross-cutting changes | All relevant files before editing any code |

### Implementation Status of Source-of-Truth Files

All five source-of-truth files (`schema.md`, `api.md`, `business-logic.md`, `parsing.md`, `AGENTS.md`) are **design-only specifications** — they were written as Codex build specifications to guide implementation. They describe the intended system design, not necessarily implemented code. Before assuming any spec is live code, verify against the actual codebase. See Section 3 for per-component status.

### Domain-Specific Authority Mapping

| Source-of-Truth File | Authoritative For |
|---------------------|-------------------|
| `schema.md` | Database schema, table definitions, columns, types, constraints, relationships, indexes, seed data |
| `api.md` | FastAPI endpoints, request/response contracts, status codes, auth headers, API behaviour |
| `business-logic.md` | Compliance engine (BL-1 through BL-11), surplus chain, tag-based reallocation, hibernation, exception handling, clawback, TBD placeholder logic |
| `parsing.md` | RDB, TTF, FormF1, and PH Excel parsing rules, cell format handling, edge cases, validation rules |
| `AGENTS.md` | Coding-agent behaviour, repo structure, implementation conventions, tech stack, security rules, confirmed decisions |

### Hard Rules That Apply Everywhere

1. **Session counts, not hours.** Compliance is measured in number of sessions attended. Duration is never a multiplier. 1 session = 1 session regardless of 0.5h or 3h.
2. **Surplus reallocation (`reallocate_by_tag()`) is read-time only.** Never write reallocated values back to `surplus_ledger`.
3. **Use `resident_postings.r_year`, not `residents.r_year`**, for compliance target lookups. A resident may cross a residency year boundary mid-period.
4. **Posting codes come from the `posting_codes` table only.** They are not derivable by regex or string pattern. Codes like `AICAIC`, `MOHHGTG1`, `NHGPlyNHGPly`, `RenCiCommHosp` break any pattern.
5. **R scripts A–F are legacy reference only.** Do not port their logic unless explicitly listed in Section 4A of `99_decision_log_and_gap_audit.md`. Logic in Section 4B must not be re-implemented.
6. **TBD-7 (FormF1 vs RDB as active/inactive source) is an open architectural decision.** FormF1 is the confirmed default. Do NOT resolve in code. Gate on `form_f1_records.is_active`. Add: `# TBD-7: active/inactive source — FormF1 is default, RDB pivot held open`
7. **TBD-MIGRATION (Historical data migration strategy) is open.** Do not build migration tooling until the option is confirmed.
8. **For full detail on any rule, go to the authoritative source-of-truth file.** Do not rely on this navigation document alone.
9. **Database performance, caching, and rate limiting are explicit implementation concerns.** Implement indexes from `schema.md`, cache only scoped derived/reference reads, invalidate caches on writes/uploads, and rate-limit auth/upload/mutation/report endpoints.

> **⚠️ Most likely LLM mistake:** Treating these source-of-truth files as describing already-implemented code and trying to "fix" or "refactor" existing code that doesn't yet exist. The silent consequence is wasted effort building patches for non-existent code, or worse, generating code that assumes other modules are already functional when they are not.

---

## Section 3 — Current Project Status

### Status Legend

- ✅ Confirmed / Implemented
- 🔧 Partially implemented
- 📋 Planned (design-only specification exists)
- ❓ Needs verification
- ❌ Deprecated / Rejected

### Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Database schema design** (`schema.md`) | 📋 Planned | Full schema specified. Tables include: `programmes`, `posting_codes`, `reporting_periods`, `residents`, `resident_postings`, `loa_types`, `session_types`, `teaching_targets`, `teaching_name_catalogue`, `teaching_events`, `event_series`, `attendance_records`, `surplus_ledger`, `form_f1_records`, `public_holidays`, `academic_month_boundaries`, `multi_posting_rules`, `posting_groups`, `weekend_exceptions`, `users`, `upload_logs`, `period_snapshots`, `clawback_records`, `global_session_types` |
| **Alembic migrations** | 📋 Planned | Structure defined in `AGENTS.md` repo layout |
| **FastAPI backend structure** | 📋 Planned | Routers: `admin.py`, `secretary.py`, `resident.py`, `auth.py`. Services: `compliance.py`, `surplus.py`, `clawback.py`, `rdb_parser.py`, `ttf_parser.py`, `formf1_parser.py`, `validation.py` |
| **RDB parser** (`rdb_parser.py`) | 📋 Planned | Full spec in `parsing.md` |
| **TTF parser** (`ttf_parser.py`) | 📋 Planned | Full spec in `parsing.md` |
| **FormF1 parser** (`formf1_parser.py`) | 📋 Planned | Full spec in `parsing.md` |
| **Compliance engine** (`compliance.py`) | 📋 Planned | BL-1 through BL-11 specified in `business-logic.md`. Includes `posting_groups` aggregation, `global_session_types` exclusion, ORTHO read-time mutation, FormF1 gate |
| **Surplus chain + reallocation** (`surplus.py`) | 📋 Planned | BL-3 and BL-4 specified |
| **Clawback engine** (`clawback.py`) | 📋 Planned | BL-10 specified; generated at period close |
| **Validation service** (`validation.py`) | 📋 Planned | BL-5 duplicate/conflict detection specified |
| **Frontend (React/Vite/TypeScript)** | 📋 Planned | Structure defined in `AGENTS.md` |
| **Auth: stub middleware** (Phase 1) | 📋 Planned | Header-based auth specified in `AGENTS.md` and `api.md` |
| **Auth: Supabase Auth** (Phase 2) | 📋 Planned | RLS policies outlined in `AGENTS.md` |
| **Security** (headers, RLS, rate limiting) | 📋 Planned | Specified in `AGENTS.md` Security section |

### Open TBDs

| TBD | Status | Summary |
|-----|--------|---------|
| TBD-7 | ❓ Open | FormF1 vs RDB as active/inactive source. FormF1 is confirmed default. |
| TBD-MIGRATION | ❓ Open | Historical data migration strategy: archive only / summary / full migration |

### Resolved TBDs

All other TBDs (TBD-1 mechanism, TBD-2, TBD-3, TBD-4/PH, TBD-5, TBD-5b, TBD-6, TBD-FM) are resolved and documented in `AGENTS.md` confirmed decisions table and `business-logic.md`. See Section 9 of this document for the full register summary.

> **⚠️ Most likely LLM mistake:** Assuming components marked 📋 Planned are already implemented and trying to import or call them. The silent consequence is runtime import errors during development, or worse, building a dependent module against an API surface that doesn't yet exist.

---

## Section 4 — Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend | FastAPI (Python 3.12+) | Async framework |
| ORM | SQLAlchemy 2.0 (async) | All queries via ORM or parameterized raw SQL |
| Migrations | Alembic | Database version control |
| Database | PostgreSQL | Local dev; Supabase-hosted in production |
| Frontend | React + Vite + TypeScript | SPA |
| Styling | Tailwind CSS | Core utility classes only — no JIT compiler assumed |
| Excel parsing | openpyxl | [Assumed — verify in `requirements.txt`] |
| Auth (Phase 1) | Stub middleware | Headers: `X-User-Role`, `X-User-Id`, `X-User-Programme`, `X-User-Site` |
| Auth (Phase 2) | Supabase Auth | JWT-based; RLS on sensitive tables |
| Cache / rate limiting | In-memory local dev → Redis/platform store for production | Scoped TTL caching and rate-limit state |
| Hosting | Supabase (DB) + Vercel (frontend) | [Assumed — AGENTS.md mentions Vercel for HTTPS] |

**[Assumed — standard/org choice]:** The selection of FastAPI, React/Vite/TypeScript, and PostgreSQL/Supabase was not documented with explicit alternatives-considered reasoning. These are standard technology choices for this type of application.

**Resident auth:** Residents authenticate with MCR number only — no password required in Phase 1. This is an intentional design choice for this system, not a temporary shortcut. No upgrade path is planned.

> **⚠️ Most likely LLM mistake:** Assuming Tailwind JIT is available and using dynamic class generation (e.g., `bg-[#custom]`). Only pre-defined core utility classes are available. The silent consequence is unstyled elements in the rendered UI.

---

## Section 5 — Architecture Overview

### Three-Role Access Model

```
Admin/PC ──→ programme-scoped via users.programme_scope TEXT[]
             Can only see/manage data for assigned programmes

Secretary ──→ posting-scoped via users.posting_code
              Can only create events at their assigned posting site

Resident ──→ identity-scoped via residents.id (from JWT sub)
             Sees events for current posting(s) + native programme posting
             All DB queries filtered to own resident_id
```

### Backend Structure

- **Routers** (`app/routers/`): Handle HTTP concerns only — request parsing, auth header validation, response formatting
- **Services** (`app/services/`): Contain ALL business logic with zero HTTP concerns. Routers call services.
- **Models** (`app/models/`): SQLAlchemy ORM models, one file per domain
- **Schemas** (`app/schemas/`): Pydantic request/response models for API validation

### Data Flow

```
RDB Excel upload
  → rdb_parser.py (uses programmes.rdb_alias, r_year_required, is_subspecialty)
  → residents, resident_postings, posting_codes tables

TTF Excel upload
  → ttf_parser.py (seeds teaching_name_catalogue from col K, posting_groups from col E)
  → teaching_targets, session_types, teaching_name_catalogue, posting_codes tables

FormF1 Excel upload
  → form_f1_parser.py
  → form_f1_records table (is_active gate for compliance denominator)

Secretary creates teaching_events via /secretary/teaching-events endpoints
  → teaching_name resolved against teaching_name_catalogue for display session_type_id
  → end_time = start_time + session_type.duration_hours (server-computed)
  → PH dates hard-blocked (422)

Resident logs in (MCR only) → sees events for current posting(s) AND native programme posting
  [only visible AFTER RDB posting schedule is uploaded]
  → submits attendance via POST /resident/attendance
    [weekend sessions without matching weekend_exceptions → stored + compliance_warning returned]
  → OR submits ad-hoc teaching via POST /resident/adhoc-teaching
    [PH dates hard-blocked (422)]
  → attendance_records table (session_type_id is NOT stored)

Compliance read (GET /resident/dashboard, GET /admin/reports/*)
  → compliance.py BL-6 steps:
    1. global_session_types check → exclude before catalogue lookup (PRIORITY)
    2. teaching_name_catalogue lookup (keyword + r_year + posting_code + programme_code)
       If no match → silently exclude from compliance
    3. ORTHO weekend mutation applied if applicable (read-time only via weekend_exceptions)
    4. BL-1 capping: achieved_and_counted = min(raw_achieved, monthly_target × active_months)
       active_months gated by form_f1_records.is_active (FormF1 default; TBD-7)
    5. posting_groups aggregation (if applicable — sum active_months and target across group)
    6. BL-4 surplus update (pre-reallocation values written to surplus_ledger)
    7. BL-3 tag-based reallocation (read-time only — never written back)
    8. BL-2 70% threshold at POSTING level (not session-type, not monthly)
    9. BL-7 dual-posting reliability flag annotation

Period close (PUT /admin/reporting-periods/{id}/close)
  → Set reporting_periods.status = 'closed'
  → Hibernate all non-hibernating surplus_ledger rows for the period
  → Generate clawback_records (BL-10) for residents failing 70%
  → Generate period_snapshots (one per programme)
```

### Auth Flow

**Phase 1 (stub):** Middleware reads identity from request headers set after token validation. Headers: `X-User-Role`, `X-User-Id`, `X-User-Programme`, `X-User-Site`. The rest of the app checks these headers for authorization. When Supabase Auth replaces the stub, only the middleware changes — endpoints stay the same.

**Phase 2 (Supabase Auth):** JWT-based. Admin/secretary login via email + password against `users` table. Resident login via MCR against `residents` table. JWT carries `role`, `programme_scope` (admin), `posting_code` (secretary), or `mcr` + `programme_code` (resident). RLS enabled on all sensitive tables.

### Error Handling

- All request bodies validated by Pydantic before any DB access
- Error responses never leak stack traces, SQL errors, or internal paths
- Standard error codes: 401 (unauthorized), 403 (forbidden), 404 (not found), 409 (conflict/duplicate/concurrent), 422 (validation failure)
- See `api.md` Common Error Responses for the full list

> **⚠️ Most likely LLM mistake:** Placing business logic in routers instead of services, or importing HTTP concerns (Request, Response objects) into service functions. The silent consequence is that the compliance engine becomes untestable in isolation and tightly coupled to the web framework.

---

## Section 6 — Repository and File Structure

```
mata/
├── AGENTS.md                  # LLM coding-agent entry point — DO NOT modify without understanding its role
├── docs/
│   ├── schema.md              # Database schema — tables, columns, types, constraints
│   ├── api.md                 # API endpoints — routes, request/response shapes
│   ├── business-logic.md      # Compliance engine, surplus chain, reallocation rules
│   └── parsing.md             # RDB, TTF, FormF1, PH upload parsing rules and edge cases
├── backend/
│   ├── alembic/               # Database migrations [Planned]
│   ├── app/
│   │   ├── main.py            # FastAPI app entry point [Planned]
│   │   ├── config.py          # Settings (DB URL, env vars) [Planned]
│   │   ├── database.py        # SQLAlchemy engine + session factory [Planned]
│   │   ├── models/            # SQLAlchemy ORM models (one file per domain) [Planned]
│   │   │   ├── resident.py    # residents table
│   │   │   ├── posting.py     # posting_codes, resident_postings
│   │   │   ├── programme.py   # programmes, posting_groups, multi_posting_rules
│   │   │   ├── teaching.py    # teaching_targets, session_types, teaching_events, teaching_name_catalogue
│   │   │   ├── attendance.py  # attendance_records
│   │   │   └── reporting.py   # reporting_periods, surplus_ledger, form_f1_records, period_snapshots, clawback_records
│   │   ├── routers/           # FastAPI routers (one file per domain) [Planned]
│   │   │   ├── admin.py       # All admin endpoints
│   │   │   ├── secretary.py   # Teaching event CRUD, CME dashboard
│   │   │   ├── resident.py    # Submission portal, dashboard, attendance, ad-hoc teaching
│   │   │   └── auth.py        # Auth stub (Phase 1) → Supabase Auth (Phase 2)
│   │   ├── services/          # Business logic (no HTTP concerns) [Planned]
│   │   │   ├── compliance.py  # BL-1 through BL-11, posting_groups, global_session_types
│   │   │   ├── surplus.py     # Surplus chain, tag-based reallocation, hibernation
│   │   │   ├── clawback.py    # Clawback calculation engine (BL-10)
│   │   │   ├── rdb_parser.py  # RDB Excel upload parser
│   │   │   ├── ttf_parser.py  # TTF Excel upload parser
│   │   │   ├── formf1_parser.py  # FormF1 Excel upload parser
│   │   │   └── validation.py  # Duplicate/conflict detection, date checks
│   │   ├── schemas/           # Pydantic request/response models [Planned]
│   │   └── middleware/        # Auth middleware, error handling [Planned]
│   ├── tests/                 # [Planned]
│   ├── requirements.txt       # [Planned]
│   └── alembic.ini            # [Planned]
└── frontend/
    ├── src/
    │   ├── pages/             # Route-level page components [Planned]
    │   ├── components/        # Shared UI components [Planned]
    │   ├── hooks/             # Custom React hooks [Planned]
    │   ├── api/               # API client functions [Planned]
    │   ├── types/             # TypeScript type definitions [Planned]
    │   └── utils/             # [Planned]
    ├── package.json           # [Planned]
    ├── vite.config.ts         # [Planned]
    └── tsconfig.json          # [Planned]
```

**`AGENTS.md`** is the LLM coding-agent entry point. It defines: repo structure, implementation conventions, three system roles, auth stub, system initialisation order, key architectural rules, confirmed decisions, and security rules. Do not modify it without understanding its role.

> **⚠️ Most likely LLM mistake:** Creating files outside the defined structure (e.g., putting parser logic in routers, or creating a separate `stp_parser.py`). The silent consequence is code that doesn't follow the project's architectural conventions and becomes harder to maintain.

---

## Section 7 — Reference Documents

| File | Covers | Implementation Status | Read Before | Most Dangerous Rule to Miss |
|------|--------|----------------------|-------------|----------------------------|
| `schema.md` | All 23 tables, columns, types, constraints, relationships, indexes, seed data | 📋 Design-only specification | Any model, migration, or database query | `session_type_id` is NOT stored on `attendance_records` — it is resolved at compliance read time. If stored, compliance becomes stale when TTF is re-uploaded. |
| `api.md` | All FastAPI endpoints, request/response shapes, auth model (two identity paths), error codes | 📋 Design-only specification | Any router, endpoint, or Pydantic schema | Two completely separate identity paths: admin/secretary authenticate via `users` table; residents authenticate via `residents` table with MCR only. They share JWT infrastructure but resolve identity from different tables. |
| `business-logic.md` | Compliance engine (BL-1–BL-11), surplus chain, reallocation, hibernation, weekend/PH exceptions, clawback, FM rules, all TBD logic | 📋 Design-only specification | Compliance engine, surplus chain, reallocation, any calculation | Tag-based reallocation sorts alphabetically by tag label (A1→A2→A3), NOT by duration. The R script sorts by tag string. Convention: A1 = longest, A2 = shorter. Sorting by duration instead of alphabetically produces different reallocation results with no error. |
| `parsing.md` | RDB, TTF, FormF1, and Academic Calendar / PH upload parsing rules, cell format variants (10 types), edge cases, validation rules | 📋 Design-only specification | Any upload endpoint or Excel parsing work | RDB posting columns are NOT at a fixed column range (I–T). The parser must detect them dynamically by scanning row 2 for date-range headers. Hardcoding column positions silently misses months. |
| `AGENTS.md` | Coding-agent behaviour, repo structure, tech stack, three roles, auth stub, initialisation order, key architectural rules, confirmed decisions, security rules | 📋 Design-only specification | Every coding task (alongside this document) | Multi-posting cell with explicit date ranges applies to ALL RDB sheets, not FM only. Assuming it's FM-only causes silent parsing failures for non-FM programmes. |

> **⚠️ Most likely LLM mistake:** Treating these specification files as documenting implemented code and trying to "fix bugs" in them. They are design specs. The silent consequence is generating patches or refactors for code that doesn't exist yet, wasting effort and creating confusion about what is actually implemented.

---

## Section 8 — Three User Roles and Workflows

### Admin / Programme Coordinator (PC)

**Scope:** Programme-scoped via `users.programme_scope TEXT[]`. An admin account only sees residents, targets, and reports for their assigned programmes. `NULL` = no access (not all-access).

**RDB Upload Flow:**
1. Admin selects reporting period and uploads `.xlsx` via `POST /admin/upload/rdb`
2. `rdb_parser.py` detects sheets dynamically (not by name — by scanning for date-range headers in row 2 and MCR patterns in column C)
3. Parser looks up `programmes` table for each resident's specialization:
   - `rdb_alias` normalisation (e.g., `Infectious Disease` → `ID`, `Surgery-in-General` → `SIG`)
   - `r_year_required` flag: if `false`, sets `r_year = 'ALL'` sentinel on `resident_postings`
   - `is_subspecialty` flag: if `true` (SPORTSMED, PALLMED), remaps R4→SS1, R5→SS2, R6→SS3
4. For each posting cell: parses cell variant (10 types — see Section 11), looks up `multi_posting_rules` for combine/half_month/main_posting handling
5. Writes to: `residents` (upsert by MCR), `resident_postings` (full replace within selected `reporting_period_id` after successful parse/validation), `posting_codes` (upsert)
6. Calls `hibernate_stale_surplus()` after insert
7. Writes `upload_logs` row with `upload_type = 'rdb'`
8. Re-upload: safe — treats upload as complete snapshot and replaces all `resident_postings` within the selected `reporting_period_id` after successful parse/validation

**TTF Upload Flow:**
1. Admin selects reporting period AND programme code, then uploads `.xlsx` via `POST /admin/upload/ttf`
2. Acquires scope-level PostgreSQL advisory lock (returns 409 if contended)
3. `ttf_parser.py` validates all rows before any writes
4. Full replace within `(reporting_period_id, programme_code)` scope: deletes existing `teaching_targets` and `teaching_name_catalogue` rows, then inserts new ones
5. Seeds `teaching_name_catalogue` from column K (Details of Training) — one row per keyword per TTF row
6. Seeds `posting_groups` from column E when non-empty
7. Non-tracked rows (`is_tracked = false`) are still seeded into `teaching_name_catalogue` for event visibility
8. **No 422 attendance guard on re-upload.** If existing attendance records reference teaching names that no longer map to a catalogue row, they are returned as warnings — upload still returns 200
9. Admin uses `PUT /admin/teaching-targets/{id}` CRUD for mid-period corrections (updates `details_of_training` and re-seeds catalogue rows for that specific target)

**FormF1 Upload Flow:**
1. Admin selects reporting period and uploads `.xlsx` via `POST /admin/upload/form-f1`
2. `form_f1_parser.py` reads `Table 1`, detects header row/columns dynamically where possible (with current-template fallback E for MCR, M–X for monthly statuses, Y for promotion date)
3. Persists only MCR, monthly statuses (`status_raw` + `is_active` by month), and promotion date; other FormF1 profile columns are non-authoritative
4. Status normalisation: `Active`/`Extension` → `is_active = true`; `Inactive` → `is_active = false`
5. Full replace per `reporting_period_id` scope; re-upload allowed at any time

**Academic Calendar / Public Holidays Upload Flow:**
1. Admin uploads workbook via `POST /admin/upload/public-holidays` (endpoint name unchanged)
2. Parser reads `Public Holidays` sheet into `public_holidays`
3. Parser reads `AY Dates` sheet into `academic_month_boundaries`
4. `Fr RMT` sheet is ignored
5. Upload summary includes both PH and AY-boundary results (`public_holidays_created`, `academic_month_boundaries_created`, `ay_categories_parsed`, `academic_year_label`, `ignored_sheets`)

**Reporting Periods:** CRUD via `/admin/reporting-periods`. Close triggers: (1) set status = 'closed', (2) hibernate surplus, (3) generate `clawback_records` (BL-10), (4) generate `period_snapshots`. Reopen clears snapshot, allows new submissions.

**Compliance Reporting Views — 5 Tabs:**
1. Monthly View — per-resident monthly attendance summary
2. Posting View — posting-level compliance with traffic light
3. Attendance Breakdown — by session type within each posting
4. Submitted Attendances — raw flat export
5. Clawback — read-only, generated at period close, visible to admin/PC only

**Admin Configuration Panel — CRUD for:**
- `loa_types` — LOA type reference table
- `weekend_exceptions` — programme-specific weekend rules
- `multi_posting_rules` — combine/half_month/main_posting rules
- `posting_groups` — compliance aggregation groups
- `global_session_types` — compliance-exempt session types
- `programmes` — programme configuration flags

> **⚠️ Most likely LLM mistake:** Building a 422 guard that blocks TTF re-upload when attendance exists. The confirmed behaviour is warn-on-reupload (not 422). The silent consequence is that admins cannot correct TTF errors mid-period, forcing manual database intervention.

---

### Secretary

**Scope:** Scoped to ONE posting site via `users.posting_code` (e.g., `TTSHGerMed`).

**Teaching Event CRUD:**
- Create events via `POST /secretary/teaching-events`
- Teaching name picked from unified dropdown populated by `GET /secretary/teaching-name-options` — combines `teaching_name_catalogue` keywords (TTF-derived) AND active `global_session_types` entries
- `session_type_id` auto-resolved from `teaching_name_catalogue` at event creation (display/prototype only — never used for compliance)
- `end_time` = `start_time + session_type.duration_hours` (server-computed — NOT a request field)
- Event creation on public holiday dates is hard-blocked (422)
- Recurrence: `POST /secretary/teaching-events/series` materialises individual event rows. PH occurrences skipped with warning. Three edit granularities: "this event only", "this and all following", "all events in the series"
- Cannot delete events that have attendance records (409)

**STP Ownership:** Secretary creates STP as a planning document. STP is never uploaded to the system. PC manually converts STP → TTF before Admin uploads. Column K (Details of Training) must be added manually.

**Provisioning:** TTSH-only at launch — 1 account per TTSH posting code. No schema change needed for other institutions.

> **⚠️ Most likely LLM mistake:** Building `end_time` as a request field on the secretary event creation endpoint. `end_time` is always server-computed from `start_time + duration_hours`. Accepting client-provided `end_time` creates inconsistency between stored duration and actual end time, causing incorrect compliance window calculations.

---

### Resident

**Scope:** All DB queries filtered to own `resident_id` from JWT `sub`.

**Submission Portal:**
- Resident logs in with MCR → JWT issued with `programme_code`
- `GET /resident/events` returns teaching events for:
  - Current posting: derived from `resident_postings` where today falls within `start_date..end_date` AND `status IN ('active', 'loa_working')`
  - Native programme posting: posting(s) associated with resident's `programme_code`
- **Critical gating rule:** Resident only sees events AFTER their posting schedule has been uploaded via RDB. No RDB upload = no visible events. Enforced by `resident_postings` lookup at request time.
- Events filtered by `teaching_name_catalogue` — only shows events whose `teaching_name` exists in the resident's catalogue for their `(posting_code, programme_code, r_year, reporting_period_id)`
- Only past/today events shown (`event_date <= today`)
- Already-submitted events excluded

**Attendance Submission:**
- `POST /resident/attendance` with `{ "event_ids": ["uuid1", "uuid2"] }`
- Weekend sessions with no matching `weekend_exceptions` rule: stored, but `compliance_warning` returned in response
- Duplicate prevention via `UNIQUE(resident_id, teaching_event_id)` at DB level

**Ad-hoc Teaching:**
- `POST /resident/adhoc-teaching` — resident submits teaching not pre-created by secretary
- Creates `teaching_events` row (`is_adhoc = true`) and `attendance_records` row in same transaction
- PH dates hard-blocked (422)
- Same compliance treatment as secretary-created events

**Dashboard:**
- `GET /resident/dashboard` — personal compliance view per posting per session type
- Shows traffic light (green/amber/red), achieved vs target, shortage

**Attendance status values:** `submitted`, `flagged`, `removed` (per `schema.md` `attendance_records.status`). [Note: no `pending`/`approved`/`rejected` states exist in the current schema.]

> **⚠️ Most likely LLM mistake:** Hardcoding `X-User-Site` for resident requests. Residents do NOT have a fixed posting site — it is always derived per-request from `resident_postings`. Hardcoding it breaks multi-posting event visibility silently, causing residents to see only one posting's events when they should see two.

---

## Section 9 — TBD Register Summary

### Open TBDs — Do NOT Resolve in Code

| TBD | Title | Summary | Instruction |
|-----|-------|---------|-------------|
| TBD-7 | FormF1 vs RDB as active/inactive source | FormF1 is confirmed default. Architectural decision formally still open. If flipped to RDB → compliance engine code change only; schema already ready (`loa_types`, `working_days_in_month`). | Do NOT resolve. Gate on `form_f1_records.is_active`. Add TODO: `# TBD-7: active/inactive source — FormF1 is default, RDB pivot held open` |
| TBD-MIGRATION | Historical data migration strategy | Three options: archive only / summary migration / full migration. Decision needed before first period close. | Do NOT build migration tooling until option is confirmed. Add TODO: `# TBD-MIGRATION: awaiting stakeholder decision` |

### Resolved TBDs — Do NOT Reopen

| TBD | Resolution | Reference |
|-----|-----------|-----------|
| TBD-1 (mechanism) | `teaching_name_catalogue` seeded from TTF col K. Session type resolved at compliance read time via `(keyword, r_year, posting_code, programme_code)`. Keyword data comes from TTF upload. | `business-logic.md` BL-6, BL-11; `schema.md` `teaching_name_catalogue` |
| TBD-2 | LOA types: 14 confirmed. Parser warns on unknown. Dormant posting codes: accepted with `display_name = NULL`. | `parsing.md` § LOA Type Validation; `schema.md` `loa_types` |
| TBD-3 | Admin scope: `users.programme_scope TEXT[]` | `schema.md` `users` table |
| TBD-4/PH | PH event creation hard-blocked (422) for secretary and resident. | `business-logic.md` BL-5 |
| TBD-5 | Recurrence editing: all three granularities required. | `api.md` series endpoints |
| TBD-5b | Combined posting event ownership: secretaries at both sites create events under own codes. | `business-logic.md` BL-8 |
| TBD-6 | Refresher Training: handled by FormF1 gate. No separate compliance logic. | `business-logic.md` TBD-6 |
| TBD-FM | FM uses standard engine. No `compliance_variant`. Two FM annotations only. | `business-logic.md` BL-FM |

See `99_decision_log_and_gap_audit.md` for the full TBD register with placeholder logic details.

> **⚠️ Most likely LLM mistake:** Reopening a resolved TBD (especially TBD-FM) and building a separate FM compliance code path. FM uses the standard engine with two annotations only. Building a separate path wastes effort, creates divergent logic, and is explicitly rejected.

---

## Section 10 — Confirmed Decisions Summary

| Decision | What was decided | Do not change without |
|---|---|---|
| Admin scope | Programme-scoped via `users.programme_scope TEXT[]` | PM approval |
| Surplus period boundary | Resets to zero at each `reporting_periods` boundary; does not carry across H1/H2 | PM approval |
| Recurrence editing | All three granularities required | PM approval |
| Reallocation scope | Tag-group-only; no cross-tag or cross-posting flow; sort alphabetical by tag label | PM approval |
| Compliance unit | Session counts, never hours | PM approval |
| Reallocation write | Read-time only via `reallocate_by_tag()`; never written to `surplus_ledger` | PM approval |
| TTF upload behaviour | Full replace within `(reporting_period_id, programme_code)` scope; warn (not 422) if attendance exists | PM approval |
| RDB re-upload | Full replace within selected `reporting_period_id` after successful parse/validation | PM approval |
| FormF1 re-upload | Full replace within `reporting_period_id` scope; allowed at any time | PM approval |
| Posting code source | `posting_codes` table only; never derived by regex or string pattern | PM approval |
| Resident event visibility | Only after RDB posting schedule upload; enforced via `resident_postings` lookup | PM approval |
| Compliance target lookup | Use `resident_postings.r_year`, not `residents.r_year` | PM approval |
| TTF is compliance input | STP is planning only; never uploaded to system | PM approval |
| `teaching_events.session_type_id` | Display/prototype only; does NOT drive compliance | PM approval |
| CME/SMC points | Informational only; do NOT feed compliance | PM approval |
| Active/inactive source | `form_f1_records.is_active` (FormF1 default); TBD-7 formally open | PM approval |
| R year sentinel | 22 programmes use `r_year = 'ALL'`; 6 `r_year_required = true`; 2 subspecialty with SS remapping | PM approval |
| `global_session_types` priority | Matched events excluded from compliance BEFORE `teaching_name_catalogue` lookup | PM approval |
| ORTHO weekend mutation | Read-time only via `mutates_to_session_type_id` + `adjusted_duration_hours`; raw DB never mutated | PM approval |
| FM compliance | Standard engine; no `compliance_variant`; two FM annotations only | PM approval |
| FM Saturday exception | **Removed from confirmed weekend_exceptions list.** No FM row in seed data. Final. | PM approval |
| Public holiday block | Secretary and resident ad-hoc creation on PH dates hard-blocked (422) | PM approval |
| Multi-posting rules source | Seeded in DB; managed via admin CRUD; no file upload | PM approval |
| Ad-hoc teaching | `POST /resident/adhoc-teaching`; `is_adhoc = true`; same compliance treatment | PM approval |
| Duration in TTF | Embedded in session type name as `[Xh]`; no separate duration column | PM approval |
| Non-tracked events | Seeded into `teaching_name_catalogue` for visibility; excluded from compliance | PM approval |
| Clawback tab | 5th tab in admin/PC dashboard; read-only; generated at period close | PM approval |
| Weekend submission | Session stored; `compliance_warning` returned if no matching exception | PM approval |
| Secretary provisioning | TTSH-only at launch; 1 account per posting code; no schema change for others | PM approval |
| Legacy cutover | Hard cutover at period boundary; no hybrid operation | PM approval |
| `posting_groups` aggregation | `active_months` and `target_100` summed across all posting codes in group | PM approval |
| `posting_groups` independence | Independent from `multi_posting_rules` (which governs RDB parsing) | PM approval |
| Tag sort order | Alphabetical by tag label (A1→A2→A3), not by duration | PM approval |

See `99_decision_log_and_gap_audit.md` for the full decision log with reasoning and alternatives considered.

> **⚠️ Most likely LLM mistake:** Changing a confirmed decision (e.g., adding duration-based tag sorting, or building a 422 TTF re-upload guard) without realising it contradicts a PM-approved decision. The silent consequence depends on the decision changed — ranging from wrong compliance numbers to blocked admin workflows.

---

## Section 11 — Excel File Formats Summary

**For full parsing rules, see `parsing.md`.**

### RDB (Resident Database / Posting Schedule)

- **Owner:** Admin uploads
- **Format:** `.xlsx`
- **Sheets:** Dynamic — detected by scanning for date-range headers in row 2 and MCR patterns in column C. Known sheets: `Phase 1 & 2`, `Phase 3`, `Phase 1 & 2 (FM)`, `SSR`. Do NOT hardcode sheet names.
- **Key columns:** A (employee_code), B (name), C (MCR), D (classification), E (base_institution), F (r_year), G (specialization → programme_code), H (reg_type), I+ (posting per month — dynamic range)
- **Programme resolution at parse time:** `rdb_parser.py` queries `programmes` table for `rdb_alias` normalisation, `r_year_required`, `is_subspecialty`
- **Cell format variants:**

```
Simple posting code        → status = 'active',        posting_code = <code>
Empty cell                 → skip, no row created
LOA only                   → status = 'loa',            posting_code = NULL,   loa fields populated
Hybrid LOA (Continue working) → status = 'loa_working', posting_code = <code>, loa fields populated
Multiline (posting + LOA)  → status = 'loa_working',    posting_code = <code>, loa fields from LOA line
Pending SR Promotion       → status = 'active',         posting_code = <code>, promotion annotation stored
Employed (XXX-Employed)    → NO resident_postings row;  employer_tag set on residents table only
Numeric (FM polyclinics)   → posting_code = string of number (e.g. "270")
Refresher Training         → status = 'active',         posting_code = <code>, refresher fields populated
Multi-posting (all sheets) → variant 10: explicit date ranges with AM/PM granularity
                             → apply multi_posting_rules (combine, main_posting, half_month)
                             → fallback if no rule + no group: separate rows, independent compliance,
                               whole-month counting, upload warning emitted
```

- **LOA types:** 14 confirmed types. Parser warns (does not reject) on unknown. "Continue working during LOA", "Pending for SR Promotion", "Refresher Training" are cell annotations — NOT `loa_types` seed rows.
- **Writes to:** `residents`, `resident_postings`, `posting_codes`
- **Re-upload:** complete snapshot full replace within selected `reporting_period_id` after successful parse/validation

### TTF (Teaching Target File)

- **Owner:** Admin uploads; PC manually created from STP
- **Format:** `.xlsx`
- **Columns:** A (reporting_period), B (programme_code), C (r_year — may be comma-separated), D (posting_code), E (dashboard_posting → seeds `posting_groups`), F (session_type with `[Xh]` duration), G (monthly_target), H (is_tracked), I (is_reallocatable), J (tag), K (details_of_training — comma-separated keywords, **mandatory**)
- **Column K is mandatory.** Absent from STP — PC adds manually. Without it, `teaching_name_catalogue` is empty and residents see zero events.
- **Duration:** Embedded in session type name as `[Xh]`. No separate column. Secretary picks `start_time` only; `end_time` server-computed.
- **Multi-year rows:** "R1,R2,R3" exploded into separate `teaching_targets` rows. `r_year = 'ALL'` for 22 programmes.
- **Column E → `posting_groups`:** When non-empty, upserts a `posting_groups` row linking the posting code to the group.
- **Writes to:** `teaching_targets`, `session_types`, `teaching_name_catalogue`, `posting_codes`, `posting_groups`
- **Upload:** Full replace within `(reporting_period_id, programme_code)`. No 422 re-upload guard — warns if attendance exists.
- **Concurrency:** Scope-level advisory lock; 409 if contended.

### FormF1

- **Owner:** Admin uploads
- **Format:** `.xlsx`
- **Sheet:** `Table 1`; detect header row and required columns dynamically where practical (current template often has row 28 headers and row 29+ data)
- **Columns used for persistence:** MCR, monthly status columns, promotion date/senior promotion date only
- **Current-template fallback positions:** E (MCR), M–X (monthly status), Y (promotion date)
- **Status normalisation:** `Active`/`Extension` → `is_active = true`; `Inactive` → `is_active = false`
- **Extension:** Always treated as Active (teaching tracked, clawback not exercised — `clawback_suppressed_reason = 'Extension'`)
- **Employed residents:** Active in FormF1 (real posting, no clawback)
- **FormF1 is per-resident per-calendar-month** — not per posting code. A month cannot be Active for one posting and Inactive for another.
- **Full replace per `reporting_period_id` scope; re-upload allowed at any time**
- **promotion_date capture:** Parsed/stored when possible for future R3→R4/senior-promotion logic; not used by compliance yet
- **Year suffix in `month_label`:** [Needs verification] — sample parser hardcodes `'25'`/`'26'`; should be dynamic based on reporting period dates

### STP (Structured Teaching Plan)

- **Owner:** Secretary creates
- **Never uploaded to the system** — no STP parser exists
- PC manually converts STP → TTF. Column K absent from STP; must be added before upload. Conversion cannot be automated.

> **⚠️ Most likely LLM mistake:** Building a TTF parser that hardcodes column positions without accounting for the dynamic sheet detection and the multi-year row explosion. The silent consequence is missing target rows for specific r_years, causing zero compliance targets for affected residents.

---

## Section 12 — Core Business Logic: High-Risk Rules

**For full logic, see `business-logic.md`.**

### Priority-Order Compliance Rules (Get These Right First)

- ⚠️ **`global_session_types` check comes FIRST.** At compliance read time, before any `teaching_name_catalogue` lookup, check if `teaching_event.teaching_name` matches any active `global_session_types.name`. If matched → exclude from compliance entirely (both numerator and denominator). Do NOT proceed to catalogue lookup.
  *Silent consequence if skipped:* Excluded events (e.g. Department Meeting) incorrectly feed compliance numbers.

- ⚠️ **Session capping (BL-1):** `achieved_and_counted = min(raw_achieved, monthly_target × active_months)`. `achieved` is display-only. `achieved_and_counted` feeds compliance.
  *Silent consequence:* Using raw `achieved` inflates compliance percentages with no exception thrown.

- ⚠️ **70% threshold at POSTING level (BL-2)**, aggregated across ALL session types for that posting. NOT per month. NOT per session type. Uses `math.ceil()` on `target_100 × 0.70`.
  *Silent consequence:* Applying per session type produces wrong traffic light colours with no error.

- ⚠️ **`resident_postings.r_year` for target lookup**, NOT `residents.r_year`. A resident may cross a year boundary mid-period.
  *Silent consequence:* Wrong `teaching_targets` row matched; wrong compliance target.

- ⚠️ **Tag-based reallocation (`reallocate_by_tag()`, BL-3) is read-time only.** Never write to `surplus_ledger`. Sort alphabetically by tag label — NOT by duration.
  *Silent consequence:* Writing back corrupts audit trail and causes double-counting.

- ⚠️ **`teaching_events.session_type_id` is display only.** Compliance session type resolved per-resident at read time via `teaching_name_catalogue` using `(teaching_name, r_year, posting_code, programme_code, reporting_period_id)`.
  *Silent consequence:* Using `teaching_events.session_type_id` produces wrong session type for cross-programme residents.

- ⚠️ **`form_f1_records.is_active` gates `active_months`.** For each calendar month, if `is_active = false` → exclude from both denominator and numerator. FormF1 is per-resident per-month — not per posting.
  *Silent consequence:* Ignoring gate inflates active_months, deflates compliance percentages.

- ⚠️ **`r_year = 'ALL'` sentinel.** 22 programmes use it. Catalogue lookup with actual r_year silently returns no results for these programmes.

- ⚠️ **ORTHO mutation is read-time only.** `mutates_to_session_type_id` and `adjusted_duration_hours` from `weekend_exceptions` applied at compliance read time. Raw `attendance_records` row never updated.
  *Silent consequence:* Writing mutation to DB corrupts audit trail.

- ⚠️ **`posting_groups` aggregation.** When `posting_code` belongs to a group, `active_months` and `target_100` summed across ALL group members. Each posting's own `monthly_target` applies per phase.
  *Silent consequence:* Calculating independently per-posting produces wrong compliance for grouped postings.

### Supporting Rules

- Traffic light: green ≥ 70%, amber 50–69%, red < 50%
- Surplus resets to zero at each `reporting_periods` boundary
- Hibernation triggered at two points: (1) RDB upload, (2) period close. Not lazily on compliance read.
- Weekend teaching: session stored regardless. `compliance_warning` returned if no matching `weekend_exceptions` rule. Confirmed exceptions: URO (2 rows — OR logic), DERM (all Saturday), ORTHO (08:30–10:30 with mutation). FM: **removed from confirmed list; no seed row.**
- Public holidays: event creation hard-blocked (422). No compliance denominator impact.
- CME/SMC points: informational only. Do NOT feed compliance.
- Non-tracked events (`is_tracked = false`): seeded into `teaching_name_catalogue` for visibility. Excluded from both numerator and denominator.
- Clawback (BL-10): generated at period close. SAF/SCDF excluded entirely. Extension: `clawback_suppressed_reason = 'Extension'`, amount = 0, row shown. R7: same pattern.
- Ad-hoc teaching (BL-9): `is_adhoc = true` on `teaching_events`. Same compliance treatment as secretary-created.

> **⚠️ Most likely LLM mistake:** Applying the 70% threshold per session type or per month, which is the intuitive but wrong approach. The threshold is at the POSTING level — sum all session types' `achieved_and_counted` and all session types' `target_100` for that posting, THEN check 70%. The silent consequence is wrong traffic light colours for every resident.

---

## Section 13 — Backend API: Critical Contracts

**For full endpoint specifications, see `api.md`.**

### Auth Headers (Phase 1 Stub)

| Header | Set For | Value |
|--------|---------|-------|
| `X-User-Role` | All roles | `admin`, `secretary`, `resident` |
| `X-User-Id` | All roles | `users.id` (admin/secretary) or `residents.id` (resident) |
| `X-User-Programme` | Admin + Resident | `programme_code` (comma-separated for admin multi-programme) |
| `X-User-Site` | Secretary only | `posting_code` of assigned site |

⚠️ **`X-User-Site` is NEVER set for residents.** Resident's current posting is always derived per-request from `resident_postings`. Fixing it breaks multi-posting visibility.

### Key Admin Endpoints

| Endpoint | Purpose | Key Behaviour |
|----------|---------|---------------|
| `POST /admin/upload/rdb` | RDB upload | Calls `rdb_parser.py`; complete snapshot full-period replacement |
| `POST /admin/upload/ttf` | TTF upload | Calls `ttf_parser.py`; 409 advisory lock; warns on existing attendance |
| `POST /admin/upload/form-f1` | FormF1 upload | Calls `form_f1_parser.py`; full replace |
| `POST /admin/upload/public-holidays` | Academic Calendar + PH upload | Upsert `public_holidays` and replace/seed `academic_month_boundaries` from AY Dates workbook content |
| `PUT /admin/teaching-targets/{id}` | Mid-period TTF correction | Re-seeds `teaching_name_catalogue` for that specific target |
| `GET /admin/reports/clawback` | Clawback 5th tab | Read-only; generated at period close |
| `PUT /admin/reporting-periods/{id}/close` | Close period | Hibernation → clawback → snapshots |
| `PUT /admin/reporting-periods/{id}/reopen` | Reopen period | Allows new submissions |

### Key Secretary Endpoints

| Endpoint | Purpose | Key Behaviour |
|----------|---------|---------------|
| `POST /secretary/teaching-events` | Create event | 422 on PH dates; `end_time` server-computed |
| `GET /secretary/teaching-name-options` | Dropdown options | Unified: TTF keywords + active `global_session_types`; includes `is_global` flag |
| `POST /secretary/teaching-events/series` | Recurring series | PH occurrences skipped with warning |
| `DELETE /secretary/teaching-events/series/{series_id}` | Delete series | Three edit scopes: `single`, `following`, `all` |

### Key Resident Endpoints

| Endpoint | Purpose | Key Behaviour |
|----------|---------|---------------|
| `GET /resident/events` | Available events | Filtered by current + native posting; gated by `resident_postings` + `teaching_name_catalogue` |
| `POST /resident/attendance` | Submit attendance | Returns `compliance_warning` for unmatched weekend sessions |
| `POST /resident/adhoc-teaching` | Ad-hoc submission | 422 on PH; `is_adhoc = true`; same compliance treatment |
| `GET /resident/dashboard` | Compliance view | JIT calculation per BL-6 |

> **⚠️ Most likely LLM mistake:** Using `POST /admin/upload/form_f1` (underscore) instead of `POST /admin/upload/form-f1` (hyphen). The endpoint path uses a hyphen. The silent consequence is a 404 that may not be caught until integration testing.

---

## Section 14 — Discarded R Script Logic (Do Not Re-implement)

**For the full audit, see `99_decision_log_and_gap_audit.md` Sections 4A and 4B.**

| R Script Logic | Replaced By |
|---|---|
| FormSG CSV column detection via regex | Structured POST body from React portal |
| Date/timestamp format normalisation (dd-MMM-yy, dd/MM/yy, etc.) | ISO-8601 from portal submission |
| MCR extraction from free-text name string | Session-authenticated identity |
| Fuzzy posting-site string matching via `tolower(gsub())` | `posting_codes` FK relationship |
| R year derivation from date-range mapping file | `resident_postings.r_year` DB field |
| Consecutive teaching row duplication (`_consec2`, `_consec3` suffixes) | Each `teaching_events` row is a discrete DB record |
| Non-resident filtering via 'I am a' column | Portal auth role |
| `responseIDwithproblemALL` error-code feedback loop | `status` field on `attendance_records` |
| Multiple-posting resolution via string matching (`multipleposting_main`) | `resident_postings` FK + `multi_posting_rules` table |
| MASTER07 posting site replacement file | Admin UI edits `posting_codes` directly |
| Changeover date hard-coded period logic (1H/2H, IM/non-IM) | `reporting_periods` table with `start_date`, `end_date` |
| `programmes.compliance_variant = 'fm'` + NotImplementedError | FM uses standard engine; two FM annotations only |

> **⚠️ Most likely LLM mistake:** Porting R script string-matching logic for posting site resolution. The new system uses `posting_codes` FK relationships — no string matching is needed or wanted. Porting it creates fragile, redundant code that silently fails on non-pattern posting codes.

---

## Section 15 — Data Models: Key Fields to Get Right

**For full schema, see `schema.md`.**

| Field | Table | Risk If Wrong |
|---|---|---|
| `r_year` | Use `resident_postings.r_year` for compliance; never `residents.r_year` | Silent wrong compliance target |
| `r_year = 'ALL'` | `resident_postings`, `teaching_targets`, `teaching_name_catalogue` | Catalogue lookup fails silently for 22 programmes |
| `is_tracked` | `teaching_targets` | Untracked sessions must not feed `achieved_and_counted` |
| `is_reallocatable` + `tag` | `teaching_targets` | Missing tag = no reallocation; surplus silently stays unallocated |
| `is_hibernating` | `surplus_ledger` | Hibernated rows must be excluded from reallocation reads |
| `session_type_id` | `teaching_events` | Display only — NOT for compliance |
| `achieved_and_counted` | Computed value | Post-cap, pre-reallocation; feeds compliance. Not raw `achieved`. |
| `programme_scope` | `users` | `TEXT[]` — Admin sees only listed programmes. NULL = no access. |
| `code` | `posting_codes` | Source of truth; never derive by regex |
| `is_active` | `form_f1_records` | FormF1 gate for compliance denominator |
| `is_active` | `global_session_types` | Inactive = hidden from dropdown + no compliance exclusion |
| `mutates_to_session_type_id` | `weekend_exceptions` | Read-time ORTHO mutation; never write to DB |
| `group_code` | `posting_groups` | Must aggregate compliance across group, not calculate independently |
| `clawback_suppressed_reason` | `clawback_records` | Extension/R7 rows shown with amount = 0; must not be omitted |
| `active_months_weight` | `resident_postings` | Default 1.0; set to 0.5 for half_month rule. Affects target calculation. |
| `posting_code` | `attendance_records` | Audit copy only — never used for compliance attribution |

> **⚠️ Most likely LLM mistake:** Using `attendance_records.posting_code` for compliance attribution. It is an audit-only copy. Compliance always uses `teaching_events.posting_code`. The silent consequence is misattributed attendance when a resident's posting changes.

---

## Section 16 — Frontend Architecture

**Status: 📋 Planned — no implementation exists yet.**

### Pages and Routes (Per Role)

**Admin:**
- Upload pages: RDB, TTF, FormF1, PH (each with file select + POST + result display)
- Configuration panel: CRUD for `loa_types`, `weekend_exceptions`, `multi_posting_rules`, `posting_groups`, `global_session_types`, `programmes`
- Reporting dashboard: 5 tabs — Monthly View, Posting View, Attendance Breakdown, Submitted Attendances, Clawback
- Reporting period management: list, create, close, reopen
- Upload log viewer

**Secretary:**
- Teaching event CRUD (create, duplicate, series, delete)
- Teaching schedule calendar view
- CME dashboard
- Resident list (current posting)

**Resident:**
- Submission portal: event list filtered by posting + catalogue
- Ad-hoc teaching form: date-first → time/session name from dropdown
- Personal compliance dashboard
- Submitted attendances list

### Key UI Patterns

- **Upload flow:** File select → POST to upload endpoint → parse JSON response → display results/warnings/errors
- **Secretary dropdown:** Unified list from `GET /secretary/teaching-name-options` (includes `is_global` flag for visual distinction)
- **Resident ad-hoc:** Date-first input → time + session name dropdown (filtered by posting for that date)
- **Weekend compliance warning:** Display warning text after `POST /resident/attendance` when `compliance_warning` is non-null
- **Traffic light:** Green (≥70%), Amber (50–69%), Red (<50%) colour indicators on compliance views

### Technical Constraints

- Tailwind CSS: core utility classes only — no JIT compiler
- TypeScript type definitions: `src/types/`
- API client functions: `src/api/`
- Auth state: Phase 1 stub headers set by middleware; Phase 2 Supabase JWT

> **⚠️ Most likely LLM mistake:** Building the resident ad-hoc teaching form with session name first and date second. The confirmed UX flow is date-first, then time/session name from dropdown (because the dropdown depends on the resident's posting at that date). The silent consequence is a broken dropdown that shows wrong session names for the selected date.

---

## Section 17 — Environment Variables and Local Development

### Environment Variables

| Name | Layer | Purpose | Example | Required |
|------|-------|---------|---------|----------|
| `DATABASE_URL` | Backend (server-only) | PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost:5432/mata` | Yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend (server-only) | Supabase admin operations | `eyJ...` (placeholder) | Phase 2 |
| `JWT_SECRET` | Backend (server-only) | JWT signing key | `your-jwt-secret-here` | Yes |
| `VITE_SUPABASE_URL` | Frontend | Supabase project URL | `https://your-project.supabase.co` | Phase 2 |
| `VITE_SUPABASE_ANON_KEY` | Frontend | Supabase anonymous key | `eyJ...` (placeholder) | Phase 2 |
| `VITE_API_BASE_URL` | Frontend | Backend API base URL | `http://localhost:8000/api/v1` | Yes |

**Server-only variables (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `JWT_SECRET`) must NEVER be exposed to the frontend** or included in client-side environment variables.

### Local Development

| Setting | Default |
|---------|---------|
| Backend port | 8000 |
| Frontend port | 5173 |
| API base URL | `http://localhost:8000/api/v1` |
| CORS | Explicit allowlist — no wildcard `*` in production |

### Commands [Planned]

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

### `.env.example` Pattern

Provide only placeholder values. Real secrets must not be committed. `.env` files must be in `.gitignore`.

> **⚠️ Most likely LLM mistake:** Hardcoding `DATABASE_URL` or `JWT_SECRET` in source code or committing `.env` files. The silent consequence is credential exposure in version control.

---

## Section 18 — Security

**For full security rules, see `AGENTS.md` Security section.**

### Key Rules (Summary)

- **All security checks enforced server-side.** Frontend checks are UX convenience only — never security boundaries.
- **Identity derived exclusively from verified JWT.** Never trust client-provided user IDs, roles, or programme codes.
- **Admin endpoints:** Check `role = 'admin'` AND `programme_code IN programme_scope`
- **Secretary endpoints:** Check `role = 'secretary'` AND `posting_code = X-User-Site`
- **Resident endpoints:** All DB queries scoped to `resident_id` from JWT `sub`
- **SQL injection:** SQLAlchemy ORM or parameterized raw SQL only. Never interpolate user input into SQL strings.
- **Mass assignment:** Never pass `**request.dict()` to ORM. Explicitly allowlist fields in Pydantic schemas.
- **File uploads:** Type/MIME/size validation server-side. `.xlsx` only (`.csv` additionally for PH). Max 10MB. Server-generated filenames.
- **CORS:** Explicit allowlist of trusted origins. No wildcard in production.
- **Error responses:** No stack traces, SQL errors, or internals.
- **Rate limiting:** Required on `POST /auth/login`, all upload endpoints, `POST /resident/adhoc-teaching`
- **Security headers:** HSTS, X-Frame-Options: DENY, X-Content-Type-Options: nosniff, Referrer-Policy, CSP
- **Supabase service role key:** Server-only. Never exposed to frontend or client-side env vars.
- **RLS:** Enabled on all sensitive tables at Phase 9 (Supabase Auth integration). See `AGENTS.md` for policy patterns.
- **Session management:** Access tokens short-lived (15–60 min). Refresh tokens with rotation. HttpOnly, Secure, SameSite=Strict cookies preferred over localStorage.

> **⚠️ Most likely LLM mistake:** Storing JWT tokens in `localStorage`. The confirmed approach is `HttpOnly` cookies. The silent consequence is XSS vulnerability — any script injection can steal the token.

---

## Section 19 — Known Risks and Blind Spots Summary

| Risk | Impact | Mitigation |
|------|--------|------------|
| TBD-7 open | If FormF1→RDB flip happens, compliance engine code change needed | Gate on `form_f1_records.is_active`; schema already ready for RDB path |
| TBD-MIGRATION open | No historical data migration plan | Do not build tooling until decision confirmed |
| Posting code patterns | Regex-based code generation silently produces wrong codes | Always query `posting_codes` table |
| `r_year = 'ALL'` sentinel | 22 programmes affected; lookup with actual r_year returns zero results | TTF matcher must handle `'ALL'` sentinel |
| TTF mid-period correction | Warn-on-reupload, not 422 | CRUD endpoint for corrections |
| Multi-posting fallback | No rule + no group → independent compliance, upload warning | Add `multi_posting_rules` or `posting_groups` entry |
| Implementation status ambiguity | Source-of-truth files are design specs | Verify against actual codebase before assuming live |
| ORTHO mutation | Must be read-time only | Never write to DB; test for data immutability |
| FormF1 year suffix | Parser sample hardcodes '25'/'26' | Must be dynamic based on reporting period |
| FM Saturday exception | Removed from confirmed list | No FM row in `weekend_exceptions` seed data |

See `99_decision_log_and_gap_audit.md` for the full risk register.

> **⚠️ Most likely LLM mistake:** Assuming the FormF1 year suffix derivation in `parse_formf1()` is correct as-is. The sample code hardcodes `'25'`/`'26'` — this must be made dynamic based on the reporting period's actual dates. The silent consequence is wrong `month_label` values that fail to join with `resident_postings.month_label`, silently excluding months from the active/inactive gate.

---

## Section 20 — Retrieval Keywords

```
MATA, MATA Dashboard, Medical Attendance Tracking Application, FastAPI, React,
TypeScript, Vite, Tailwind CSS, PostgreSQL, Supabase, SQLAlchemy, Alembic,
rdb_parser.py, ttf_parser.py, form_f1_parser.py, compliance.py, surplus.py,
clawback.py, validation.py,
AGENTS.md, schema.md, api.md, business-logic.md, parsing.md,
RDB, Resident Database, Posting Schedule, TTF, Teaching Target File,
STP, Structured Teaching Plan, FormF1, form_f1_records,
teaching_events, attendance_records, resident_postings, teaching_targets,
surplus_ledger, posting_codes, session_types, reporting_periods, residents,
programmes, users, teaching_name_catalogue, global_session_types, posting_groups,
clawback_records, loa_types, multi_posting_rules, period_snapshots, upload_logs,
weekend_exceptions, public_holidays,
compliance engine, 70% threshold, traffic light, session count, session type,
surplus chain, tag group, reallocate_by_tag, hibernation, is_hibernating,
reporting period, H1 H2, posting code, r_year, r_year_required, r_year ALL sentinel,
active_months, achieved_and_counted, is_active, form_f1_records,
Details of Training, FormSG migration, R script migration,
clawback, clawback_suppressed_reason, Extension suppression, R7 suppression,
MCR, programme coordinator, admin, secretary, resident portal,
submission portal, duplicate detection, weekend_exceptions, public_holidays,
advisory lock, programme_scope, dual posting, multi_posting_rules,
dormant posting code, LOA, LOA types, employed, refresher training,
TBD-1, TBD-7, TBD-MIGRATION, placeholder logic,
X-User-Role, X-User-Id, X-User-Programme, X-User-MCR, X-User-Site,
KEEP PORT discard legacy R script, Codex specification, implementation status,
ORTHO mutation, mutates_to_session_type_id, adjusted_duration_hours,
posting_groups aggregation, group_code, global_session_types, is_global,
compliance_warning, ad-hoc teaching, is_adhoc, secretary provisioning,
PC provisioning, RLS, row-level security, security headers, HSTS,
rate limiting, service role key, CORS, JWT, Supabase Auth,
rdb_alias, is_subspecialty, SS1 SS2 remapping, SPORTSMED PALLMED,
FM standard engine, NHGPlyNHGPly, Department Teaching 5h,
clawback tab, period close, period reopen, period_snapshots, hard cutover
```
