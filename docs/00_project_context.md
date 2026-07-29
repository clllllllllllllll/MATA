# 00_project_context.md — MATA Dashboard Master Orientation Document

> **Purpose:** This is the master orientation and navigation document for the MATA (Medical Attendance Tracking Application) project. Read this file first before any of the six domain source-of-truth documents and `AGENTS.md`. It summarises, cross-references, and highlights critical rules — it does not duplicate full table definitions or code blocks that already exist in the source-of-truth files.
>
> **Authority:** This document is a navigation aid. If it conflicts with `schema.md`, `api.md`, `business-logic.md`, `parsing.md`, `auth-account-contract.md`, `security.md`, or `AGENTS.md`, trust the domain-specific source-of-truth file or repository instruction and flag this document for update.

---

## Section 1 — Project Summary

### What MATA Dashboard Is

MATA Dashboard is a domain-specific web application for tracking medical resident attendance at teaching events across hospital postings in Singapore's NHG (National Healthcare Group) residency programmes. It calculates compliance against programme-specific targets and manages surplus/session reallocation. Clawback remains a separate deferred specification area.

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
  → Programme PCs review native attendance for residents in their assigned programmes (read-only)
  → Future Phase 6 compliance engine calculates JIT (just-in-time) on every read
  → Future Admin/PC compliance dashboard requirements remain a separate phase
```

**5B-H-D current state (2026-07-26):** Production/Supabase mode uses backend-owned opaque PostgreSQL sessions. The browser receives the `HttpOnly`, `Secure`, `SameSite=Strict`, host-only `__Host-mata_session` cookie and retains only identity plus the non-secret CSRF synchronizer value in memory. Unsafe methods require `X-CSRF-Token` and an approved `Origin`; production frontend API traffic uses same-origin relative `/api/v1` requests with credentials.

Staff password authentication is backend-mediated through Supabase, and no Supabase access/refresh token is returned to or persisted by the browser. Login, Non-NHG registration, and registration-options routes are intentionally public application entry points; a Vercel outer gate is not an application-auth requirement.

Session rotation is serialized by subject, transaction-scoped family advisory lock, and locked/refreshed database row. Subject generation fencing invalidates sessions after authorization change, password reset, or deactivation. Revision `20260722_000024` revokes browser-role object privileges.

**5B-H-E/current lifecycle local state (2026-07-27):** Revisions `20260726_000025` and `20260726_000026` add separate non-owner runtime and auth-helper capabilities, database-revalidated signed transaction context, reviewed service helpers, database-enforced global MCR uniqueness, and the full policy/grant cutover. Revision `20260727_000027` narrows restricted session-helper results, adds interval-gated activity, and denies signed RLS context after session expiry/revocation. All 34 application tables have RLS enabled locally; 84 policies target only `mata_app_runtime`. The runtime, auth-helper, and migration/ownership credentials must be distinct, and startup attestation fails closed on unsafe roles, ownership, grants, helpers, policies, schema access, sequences, PUBLIC, or browser-role state. FastAPI authorization remains mandatory.

Local code and disposable-database verification are not proof of deployed Supabase behavior.

**AUD-M-06 reliable-logout local state (2026-07-28):** Logout clears local
identity, the in-memory CSRF value, protected read/upload state, and
authenticated UI state immediately, then remains explicitly
pending/unconfirmed unless either the matching server response returns
`server_logout_confirmed = true` or a successfully committed replacement login
resolves the matching lifecycle. Only the proof-positive response confirms
server revocation; replacement login does not make that claim. Pending state
blocks mount, focus/visibility hydration and protected requests. Durable state
is limited to a non-sensitive pending tombstone (format version, timestamp,
bounded retry state, and local request id) plus a fixed-size non-sensitive
resolution watermark used to order cross-tab/reload recovery; no copy of
token/cookie material, CSRF, identity, MCR, role, scope, credential, or
server-expiry data is written to application storage.
The browser-managed HttpOnly cookie may remain while server revocation is
unconfirmed, but it cannot bypass the pending fence. The original proof
remains in memory only for at most four attempts at nominal automatic offsets
0, 1, 3, and 7 seconds. Manual retry or an `online` event may advance one
eligible attempt, but triggers coalesce and never increase that bound. Reload
is proofless; cross-tab and stale-response handling is
revision/request-id/watermark fenced. A replacement login resolves the
matching lifecycle only after the new session is committed inside the same Web
Lock. Local gate evidence passed; deployed verification remains pending.

Resident identity assurance remains separately governed product debt. Do not
invent a factor outside an approved product scope.

### Three User Roles

| Role | Identity | Scope | Primary Actions |
|------|----------|-------|-----------------|
| **Master Admin / Programme Coordinator (PC)** | Backend-mediated Supabase email + password in production | Master Admin is the explicit persisted `role = admin`, `admin_level = master` tier. PCs are programme-scoped via `users.programme_scope TEXT[]`; missing, null, empty, and blank scopes grant no programme access and never imply Master Admin. | Master Admin may upload RDB, FormF1, Academic Calendar / PH, and any programme's TTF. A PC may upload TTF only for a normalized programme in scope; other actions remain programme-scoped. |
| **Secretary** | Backend-mediated Supabase email + password in production | Scoped to ONE posting site via `users.posting_code` | Create/manage teaching events; view CME dashboard; view teaching schedule |
| **NHG Resident** | MCR number only (no password in Phase 1) | Own data only; events filtered by assigned posting, native programme department, and native programme PC events | Submit attendance; submit ad-hoc teaching; view past attendance; future personal compliance dashboard remains Phase 6 |
| **Non-NHG Resident** | MCR number only after self-registration | Own external attendance only; upcoming NHG posting schedule selected/updated by resident | Submit attendance/ad-hoc teaching; view past attendance; no NHG compliance dashboard or clawback |

### Reporting Periods

Six-month windows (H1: Jan–June, H2: Jul–Dec) stored in the `reporting_periods` table. `status` is operational (`active` / `inactive`), with optional `activate_on` / `deactivate_on` scheduled transition dates resolved at read time. Deactivation blocks new resident submissions and hides unsubmitted events, but does not freeze the period, hibernate surplus, generate clawback, or create snapshots.

### The Four Upload Files

| File | Uploaded By | What It Contains | Tables Written |
|------|------------|-----------------|----------------|
| **RDB** (Resident Database / Posting Schedule) | Master Admin | Which resident is at which posting site by month | `residents`, `resident_postings`, `posting_codes` |
| **TTF** (Teaching Target File) | Master Admin, or Programme PC for a normalized programme in scope (PC creates from STP) | Compliance targets: session types, monthly targets, keywords, tags | `teaching_targets`, `session_types`, `teaching_name_catalogue`, `posting_codes`, `posting_groups` |
| **FormF1** | Master Admin | Active/inactive status per resident per calendar month | `form_f1_records` |
| **Academic Calendar / Public Holidays** | Master Admin | Public holiday dates plus AY date boundaries (`Public Holidays` + `AY Dates` sheets; `Fr RMT` ignored) | `public_holidays`, `academic_month_boundaries` |

**STP (Structured Teaching Plan):** Created by Secretary. A planning document only. **STP is never uploaded to the system.** The PC manually converts STP to TTF before a Master Admin or Programme PC for that normalized in-scope programme uploads it. Column K (Details of Training / tag info) is absent from STP and must be added manually by PC — this is why conversion cannot be automated.

### Legacy Cutover

Hard cutover at a period boundary. FormSG and Google Forms submission channels are closed at that date. No hybrid operation — all attendance flows through this system only after cutover.

> **⚠️ Most likely LLM mistake:** Assuming STP is uploaded to the system, or that an STP parser exists. STP is never uploaded. TTF is the compliance input. If an LLM builds an STP upload endpoint, it wastes effort and creates confusion. The silent consequence is that column K (Details of Training) — which is mandatory for `teaching_name_catalogue` seeding — would be missing, breaking event visibility and session type resolution for all residents.

---

## Section 2 — How to Use This Document and the Reference Files

### Conflict Resolution

If this document (`00_project_context.md`) or `99_decision_log_and_gap_audit.md` conflicts with `schema.md`, `api.md`, `business-logic.md`, `parsing.md`, `auth-account-contract.md`, `security.md`, or `AGENTS.md`, **trust the domain-specific source-of-truth file or repository instruction**. This document is navigation only. `99_decision_log_and_gap_audit.md` is an audit trail. Neither overrides the source-of-truth files.

### Reading Order for Generating Migration Documents

1. Read `00_project_context.md` (this file) first
2. Then read all six domain source-of-truth documents (`schema.md`, `api.md`, `business-logic.md`, `parsing.md`, `auth-account-contract.md`, and `security.md`) plus `AGENTS.md` before generating any output

### Reading Order for Coding Tasks

Before coding, always read `00_project_context.md` and `AGENTS.md`. Then read the relevant source-of-truth files:

| Task Type | Required Reading |
|-----------|-----------------|
| Schema changes, migrations, DB queries | `schema.md` |
| Endpoint, API, or Pydantic schema changes | `api.md` |
| Compliance, surplus, hibernation, reallocation, exceptions, thresholds | `business-logic.md` |
| RDB, TTF, FormF1, or PH upload parsing | `parsing.md` |
| Identity, account, or session-lifecycle behavior | `auth-account-contract.md` plus `security.md` |
| Authentication, authorization, sessions, CSRF, RLS, privacy, deployment, or security maintenance | `security.md` plus the applicable domain file |
| Cross-cutting changes | All relevant files before editing any code |

### Implementation Status of Source-of-Truth Files

The source-of-truth files began as build specifications, but substantial pre-compliance code is now implemented. Schema/auth/session/upload/event/attendance surfaces must be verified against current models, migrations, services, and tests. Phase 5B-H-E full RLS is locally implemented; deployed verification remains separate. Phase 6 compliance, final close, snapshots, and clawback remain separately bounded work.

### Domain-Specific Authority Mapping

| Source-of-Truth File | Authoritative For |
|---------------------|-------------------|
| `schema.md` | Database schema, table definitions, columns, types, constraints, relationships, indexes, seed data |
| `api.md` | FastAPI endpoints, request/response contracts, status codes, auth headers, API behaviour |
| `business-logic.md` | Non-clawback compliance engine (BL-1 through BL-11), surplus chain, raw-count reallocation, hibernation, exceptions, and an explicit deferred clawback register |
| `parsing.md` | RDB, TTF, FormF1, and PH Excel parsing rules, cell format handling, edge cases, validation rules |
| `auth-account-contract.md` | Identity, account, and session-lifecycle behavior |
| `security.md` | Cross-cutting authentication, authorization, sessions, CSRF, rate limits, RLS, privacy, deployment, CI, and rollback contracts |
| `AGENTS.md` | Coding-agent behaviour, repo structure, implementation conventions, tech stack, security rules, confirmed decisions |

### Hard Rules That Apply Everywhere

1. **Session counts, not hours.** Compliance is measured in number of sessions attended. Duration is never a multiplier. 1 session = 1 session regardless of 0.5h or 3h.
2. **Tag reallocation uses raw session counts before final capping and is read-time only.** Transfer one session credit at a time within a physical posting/R-year context/tag prefix; duration is never transferred or multiplied. Never write reallocated values to `surplus_ledger`.
3. **Use each phase's `resident_postings.r_year`, not `residents.r_year`**, for target lookup. Mid-period R-year contexts are targeted and capped separately before posting-level summation.
4. **Posting codes come from trusted database configuration only.** They are not derivable by regex or string pattern. Non-NHG registration resolves exact programme/institution pairs through `programme_institution_posting_map`; it must not reuse native teaching, Secretary, target, or posting metadata as a fallback.
5. **R scripts A–F are legacy reference only.** Do not port their logic unless explicitly listed in Section 4A of `99_decision_log_and_gap_audit.md`. Logic in Section 4B must not be re-implemented.
6. **Active/inactive source is resolved.** FormF1 is final. The AY bucket label selects the stored calendar-month FormF1 row that gates both numerator and denominator for the whole bucket; do not use an event's raw calendar month or split/prorate the bucket.
7. **TBD-MIGRATION (Historical data migration strategy) is open.** Do not build migration tooling until the option is confirmed.
8. **For full detail on any rule, go to the authoritative source-of-truth file.** Do not rely on this navigation document alone.
9. **Database performance, caching, and rate limiting are explicit implementation concerns.** Implement indexes from `schema.md`, cache only scoped derived/reference reads, invalidate caches on writes/uploads, and rate-limit auth/upload/mutation/report endpoints.
10. **Percentage is the canonical status predicate.** Use the unrounded posting percentage for `met_70pct` and colour. `target_70 = ceil(target_100 × 0.70)` is a displayed whole-session target.
11. **Persistent surplus is derived audit state.** Recompute and replace raw eligible attendance minus `target_100`; never add a stored value back to attendance.

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
| **Database schema design** (`schema.md`) | ✅ Implemented pre-compliance schema | `clawback_records` remains a deferred placeholder pending its final contract |
| **Alembic migrations** | ✅ Implemented | Linear history through `20260727_000027` |
| **FastAPI backend structure** | ✅ Implemented pre-compliance surfaces | Routers, services, middleware, models, schemas, and tests are present |
| **RDB parser** (`rdb_parser.py`) | ✅ Implemented | Contract and edge cases remain governed by `parsing.md` |
| **TTF parser** (`ttf_parser.py`) | ✅ Implemented | Contract and edge cases remain governed by `parsing.md` |
| **FormF1 parser** (`formf1_parser.py`) | ✅ Implemented | Contract and edge cases remain governed by `parsing.md` |
| **Compliance engine** (`compliance.py`) | ✅ Implemented | BL-1 through BL-11, grouping, global exclusions, ORTHO mutation, and FormF1 gate |
| **Surplus chain + reallocation** (`surplus.py`) | ✅ Implemented | BL-3 and BL-4 |
| **Clawback engine** (`clawback.py`) | ⏸ Deferred | Financial and final-close rules are not implementation-ready |
| **Validation service** (`validation.py`) | ✅ Implemented | Duplicate and later-distinct-event overlap rejection |
| **Frontend (React/Vite/TypeScript)** | ✅ Implemented pre-compliance surfaces | Cookie/CSRF transport and all current role workflows |
| **Auth: stub middleware** | ✅ Implemented local/demo only | Synthetic headers are rejected in production-like modes |
| **Auth: Supabase staff authentication** | ✅ Implemented | Backend-mediated password flow wrapped in MATA app sessions |
| **Security** | 🔧 H-E locally complete | Deployed role, policy, grant, migration, and workflow verification remains |

### Pre-Compliance Roadmap Orientation

This file is navigation only. Detailed contracts live in `99_decision_log_and_gap_audit.md`, `schema.md`, `api.md`, and `business-logic.md`.

- `3I-A` Unified Admin Logs backend contract: complete / committed.
- `3I-B` Unified Admin Logs backend endpoints: complete / committed.
- `3I-C` Unified Admin Logs frontend page: complete / committed.
- `4B` Programme PC Teaching Event CRUD is implemented: PCs manage scheduled, programme-owned teaching events through scoped admin endpoints.
- `5A` NHG Resident workflow hardening is implemented, including the date-first, catalogue-backed ad-hoc teaching flow. `details_of_session` remains separately pending where the schema contract still says so.
- `5B` Non-NHG Resident workflow and visibility are implemented: registration/login, upcoming posting schedule, event listing, attendance/ad-hoc submission, past attendance, admin/PC list/read, Excel export, native programme department visibility, and fixed ad-hoc attribution.
- `5B-G` Supabase readiness is complete as documentation/audit work: staff bootstrap runbook, RLS/grants/Data API planning matrix, Supabase migration smoke plan, service-role access review, and readiness audit. It did not enable RLS, write policy SQL, implement cookie/BFF/CSRF, or implement compliance.
- `5B-H-A`, `5B-H-B`, and `5B-H-C` are retained as historical deployment-security/UAT phases.
- `5B-H-D` is implemented and locally verified; see `docs/archive/security/phase-5b/5b_h_d_production_security_implementation.md`. Deployment smoke remains separate.
- `5B-H-E` is locally implemented and verified against the named disposable PostgreSQL database; see `docs/archive/security/phase-5b/5b_h_e_full_rls_implementation.md`. It reconciles `docs/archive/security/phase-5b/5b_g_rls_grants_matrix.md`; deployed verification remains separate.
- Programme PC NHG Resident Attendance is implemented as a pre-compliance, read-only overview plus a dedicated resident history page. Backend scope is `residents.programme_code IN users.programme_scope`; reads use native `attendance_records` only. Non-NHG Attendance remains separate, and no attendance mutation or compliance/target-progress UI is part of this feature.
- Phase 6 compliance remains the next major feature phase after the protected deployment/security baseline is acceptable. Phase 6 compliance must read native `attendance_records` only and never join `external_attendance_records`.

### Open TBDs

| TBD | Status | Summary |
|-----|--------|---------|
| TBD-7 | ✅ Resolved | FormF1 is the final authoritative active/inactive source for compliance. |
| TBD-MIGRATION | ❓ Open | Historical data migration strategy: archive only / summary / full migration |

### Resolved TBDs

All other TBDs (TBD-1 mechanism, TBD-2, TBD-3, TBD-4/PH, TBD-5, TBD-5b, TBD-6, TBD-FM) are resolved and documented in `AGENTS.md` confirmed decisions table and `business-logic.md`. See Section 9 of this document for the full register summary.

> **⚠️ Most likely LLM mistake:** Treating a design contract or roadmap label as proof of current implementation. Verify current models, migrations, services, routes, and tests before changing a domain, and keep explicitly deferred compliance/final-close/RLS work bounded.

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
| Auth (local/demo) | Stub middleware | Synthetic headers are local/demo only and never trusted in production |
| Auth (production) | Backend-owned opaque PostgreSQL sessions + backend-mediated Supabase staff authentication | Strict cookie/CSRF transport; current subject and generation reloaded server-side |
| Cache / rate limiting | In-memory local compatibility; PostgreSQL persistent rate limiting in production | Scoped TTL caching and HMAC-keyed atomic rate-limit buckets |
| Hosting | Supabase (DB) + Vercel (frontend) | [Assumed — AGENTS.md mentions Vercel for HTTPS] |

**[Assumed — standard/org choice]:** The selection of FastAPI, React/Vite/TypeScript, and PostgreSQL/Supabase was not documented with explicit alternatives-considered reasoning. These are standard technology choices for this type of application.

**Resident auth:** Residents currently authenticate with MCR number only. This
assurance decision is separately governed product debt. Do not invent a second
factor or claim workflow outside an approved product scope.

> **⚠️ Most likely LLM mistake:** Assuming Tailwind JIT is available and using dynamic class generation (e.g., `bg-[#custom]`). Only pre-defined core utility classes are available. The silent consequence is unstyled elements in the rendered UI.

---

## Section 5 — Architecture Overview

### Three-Role Access Model

```
Admin/PC ──→ programme-scoped via users.programme_scope TEXT[]
             Can only see/manage data for assigned programmes

Secretary ──→ posting-scoped via users.posting_code
              Can only create events at their assigned posting site

NHG Resident ──→ identity-scoped via residents.id (from validated app session and current subject-row reload)
             Sees assigned posting secretary events + native programme TTSH department secretary events + native programme PC events
             All DB queries filtered to own resident_id
```

### Backend Structure

- **Routers** (`app/routers/`): Handle HTTP concerns only — request parsing, session/auth dependency validation, response formatting
- **Services** (`app/services/`): Contain ALL business logic with zero HTTP concerns. Routers call services.
- **Models** (`app/models/`): SQLAlchemy ORM models, one file per domain
- **Schemas** (`app/schemas/`): Pydantic request/response models for API validation

### Data Flow

```
RDB Excel upload
  → rdb_parser.py (uses programmes.rdb_alias and r_year_required; no SS remapping)
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

NHG Resident logs in (MCR only) → sees assigned posting secretary events, native programme TTSH department secretary events, and native programme PC events
  [only visible AFTER RDB posting schedule is uploaded]
  → submits attendance via POST /resident/attendance
    [weekend sessions without matching weekend_exceptions → stored + compliance_warning returned]
  → OR submits ad-hoc teaching via POST /resident/adhoc-teaching
    [PH dates hard-blocked (422); countable ad-hoc maps to Department/Programme Teaching [1h] under assigned posting]
  → attendance_records table (session_type_id is NOT stored)

Compliance read (GET /resident/dashboard, GET /admin/reports/*)
  → compliance.py BL-6 steps:
    1. Resolve physical posting, phase R-year, AY bucket label, and that label's FormF1 gate
    2. Project approved out-of-posting native-programme events to one assigned-posting Department/Programme Teaching [1h] session
    3. global_session_types check → exclude before catalogue lookup (PRIORITY)
    4. Exact canonical teaching_name_catalogue lookup in resident/period/posting/R-year scope
    5. Apply exact-type ORTHO adjusted-time Saturday mutation if applicable
    6. Count raw eligible sessions; compute correctly weighted targets by R-year context
    7. Recompute/replace BL-4 surplus as cumulative raw eligible attendance minus cumulative target_100
    8. Apply BL-3 raw-count tag reallocation within physical posting and R-year context, then cap each R-year context separately
    9. Aggregate configured posting_groups only after physical-posting reallocation/capping
    10. Use unrounded posting percentage for the canonical 70% predicate; target_70 is display-oriented

Reporting period deactivate (PUT /admin/reporting-periods/{id}/deactivate)
  → Set reporting_periods.status = 'inactive'
  → Block new resident attendance/ad-hoc submissions
  → Hide unsubmitted resident events from the submission flow
  → Do not hibernate surplus, generate clawback_records, or generate period_snapshots
```

### Auth Flow

**Local/demo:** Middleware may read the documented synthetic headers. They are never trusted in production-like modes.

**Production/Supabase:** The browser submits staff credentials to the backend, which performs the bounded Supabase password exchange and discards the upstream tokens after verification. Resident MCR login is backend-owned. All identities receive an opaque MATA application session through `__Host-mata_session`; unsafe requests also require the session-bound CSRF value and approved Origin. The cookie contains no role or scope. The backend resolves `app_sessions`, reloads the current subject row, and checks `session_generation` on every protected request. H-E then installs database-revalidated, signed transaction-local identity before protected SQL executes. Ordinary queries use the non-owner `mata_app_runtime` capability; public authentication/session helpers use the separate `mata_auth_internal` capability; migrations and ownership use neither application credential.

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
│   ├── alembic/               # Implemented database migrations
│   ├── app/
│   │   ├── main.py            # FastAPI app entry point
│   │   ├── config.py          # Settings (DB URL, env vars)
│   │   ├── database.py        # SQLAlchemy engine + session factory
│   │   ├── models/            # SQLAlchemy ORM models
│   │   │   ├── resident.py    # residents table
│   │   │   ├── posting.py     # posting_codes, resident_postings
│   │   │   ├── programme.py   # programmes, posting_groups, multi_posting_rules
│   │   │   ├── teaching.py    # teaching_targets, session_types, teaching_events, teaching_name_catalogue
│   │   │   ├── attendance.py  # attendance_records
│   │   │   └── reporting.py   # reporting_periods, surplus_ledger, form_f1_records, period_snapshots, clawback_records
│   │   ├── routers/           # FastAPI routers (one file per domain)
│   │   │   ├── admin.py       # All admin endpoints
│   │   │   ├── secretary.py   # Teaching event CRUD, CME dashboard
│   │   │   ├── resident.py    # Submission portal, dashboard, attendance, ad-hoc teaching
│   │   │   └── auth.py        # Backend-owned app-session auth and local/demo compatibility
│   │   ├── services/          # Business logic (no HTTP concerns)
│   │   │   ├── compliance.py  # BL-1 through BL-11, posting_groups, global_session_types
│   │   │   ├── surplus.py     # Surplus chain, tag-based reallocation, hibernation
│   │   │   ├── clawback.py    # Deferred Phase 10 placeholder; BL-10 has no financial contract yet
│   │   │   ├── rdb_parser.py  # RDB Excel upload parser
│   │   │   ├── ttf_parser.py  # TTF Excel upload parser
│   │   │   ├── formf1_parser.py  # FormF1 Excel upload parser
│   │   │   └── validation.py  # Duplicate/conflict detection, date checks
│   │   ├── schemas/           # Pydantic request/response models
│   │   └── middleware/        # Auth, security, rate-limit, and error middleware
│   ├── tests/                 # Backend test suite
│   ├── requirements.txt       # Pinned backend dependencies
│   └── alembic.ini            # Alembic configuration
└── frontend/
    ├── src/
    │   ├── pages/             # Route-level page components
    │   ├── components/        # Shared UI components
    │   ├── hooks/             # Custom React hooks
    │   ├── api/               # Cookie/CSRF API transport and domain clients
    │   ├── types/             # TypeScript type definitions
    │   └── utils/             # Shared utilities
    ├── package.json           # Frontend dependencies and gates
    ├── vite.config.ts         # Vite configuration
    └── tsconfig.json          # TypeScript configuration
```

**`AGENTS.md`** is the LLM coding-agent entry point. It defines: repo structure, implementation conventions, three system roles, auth stub, system initialisation order, key architectural rules, confirmed decisions, and security rules. Do not modify it without understanding its role.

> **⚠️ Most likely LLM mistake:** Creating files outside the defined structure (e.g., putting parser logic in routers, or creating a separate `stp_parser.py`). The silent consequence is code that doesn't follow the project's architectural conventions and becomes harder to maintain.

---

## Section 7 — Reference Documents

| File | Covers | Implementation Status | Read Before | Most Dangerous Rule to Miss |
|------|--------|----------------------|-------------|----------------------------|
| `schema.md` | Current schema contract plus explicitly deferred tables | Implemented contract; verify current migrations/models | Any model, migration, or database query | `session_type_id` is NOT stored on `attendance_records` — it is resolved at compliance read time. If stored, compliance becomes stale when TTF is re-uploaded. |
| `api.md` | Current FastAPI endpoints, request/response shapes, auth model, error codes | Implemented pre-compliance contract with explicit future items | Any router, endpoint, or Pydantic schema | Three separate server-owned identity tables converge on one opaque application-session envelope; role/scope is reloaded from the current subject row. |
| `business-logic.md` | Non-clawback engine (BL-1–BL-11), surplus, raw-count reallocation, exceptions, FM rules, and deferred clawback register | Implemented non-clawback rules plus explicit deferrals | Compliance engine, surplus chain, reallocation, any calculation | Reallocation sorts alphabetically by tag and transfers raw session counts before final capping; duration never drives the arithmetic. |
| `parsing.md` | RDB, TTF, FormF1, and Academic Calendar / PH upload parsing rules, cell format variants, edge cases, validation rules | Implemented parser contract | Any upload endpoint or Excel parsing work | RDB posting columns are NOT at a fixed column range (I–T). The parser must detect them dynamically by scanning row 2 for date-range headers. Hardcoding column positions silently misses months. |
| `security.md` | Current cross-cutting security contract, local/deployed evidence boundary, and deferred debt | Implemented local contract; deployed verification remains separate | Any authentication, authorization, session, CSRF, RLS, privacy, deployment, CI, or rollback change | Local passing tests do not prove the deployed database, proxy, cookie, environment, or role catalogue. |
| `AGENTS.md` | Coding-agent behaviour, repo structure, tech stack, roles, initialisation order, key architectural rules, confirmed decisions, security rules | Current project instructions and architecture authority | Every coding task (alongside this document) | Multi-posting cell with explicit date ranges applies to ALL RDB sheets, not FM only. Assuming it's FM-only causes silent parsing failures for non-FM programmes. |

> **⚠️ Most likely LLM mistake:** Assuming every documented future or deferred field is already implemented. Cross-check the current model, migration, route, and test before changing code, while treating the domain contracts as the authority for intended behavior.

---

## Section 8 — Three User Roles and Workflows

### Non-NHG Resident Flow (Phase 5B)

Non-NHG Residents are NUH or SingHealth residents posted to NHG departments. They self-register with `name`, `mcr`, `home_cluster`, and repeatable upcoming NHG posting rows, then log in with MCR only. They are stored in `external_residents`, forecast/date-specific postings are stored in `external_resident_postings`, submissions are stored in `external_attendance_records`, and programme/institution resolution is configured in `programme_institution_posting_map`.

Non-NHG Residents are excluded from NHG compliance, numerator, denominator, surplus, snapshots, and clawback. Their attendance is recording/export-only and must be exportable to Excel for forwarding to NUH/SingHealth PCs before Phase 6 compliance.

Upcoming NHG posting rows capture `start_date`, `end_date`, programme, and an institution supplied by the backend options response. Rows may cross calendar months, must not overlap for the same Non-NHG Resident, and may have gaps. The backend persists the validated `programme_code` on each `external_resident_postings` row and resolves/stores its canonical `posting_code`; the client neither requests nor submits a posting code. Event/ad-hoc options for a date in a gap return unavailable/no posting for selected date.

`external_resident_postings.programme_code` is nullable only so unresolved legacy rows remain intact. Backfill a legacy row only when its programme is uniquely and safely resolvable; never select the first mapping candidate. Ambiguous shared postings such as `TTSHGenMed` (AIM/IM) and `TTSHGenSrg` (GS/SIG) remain null and do not grant Programme PC-event visibility. New registration, schedule replacement, and compatibility writes always retain the validated programme.

Posting codes are never generated by concatenating strings or regex and are never derived from native teaching fields, Secretary pools, teaching targets, posting prefixes, or metadata. The backend requires one exact active `programme_institution_posting_map` row; pending, inactive, missing, or malformed pairs fail closed.

Phase 5B uses a confirmed two-stage rollout. Stage 1 implemented the generic mapping service/API/frontend and seeded exactly 28 TTSH rows as a pending/null safety baseline. The approved Stage 2 state is exactly 24 active TTSH mapping rows, four inactive TTSH mapping rows (`FM`, `PATH`, `SPORTSMED`, and `PALLMED`) with null posting codes, and zero pending TTSH rows. Public Non-NHG registration exposes only the 24 active programme choices. The four inactive statuses apply exclusively to Non-NHG programme/institution registration and posting-schedule selection; they do not deactivate those programmes or alter their availability elsewhere in MATA. `GERI + TTSH -> TTSHGerMed` is an ordinary configured mapping, not a runtime exception. Future KTPH, WH, and other institutions require configuration rows only.

External-registration mappings are isolated from native teaching visibility, `supports_secretary_events`, Secretary event creation/visibility, and compliance attribution.

For each event date, Non-NHG scheduled-event listing and attendance submission authorize against the matching external posting row. Secretary-created events require the exact schedule `posting_code`, a null `created_for_programme_code`, and `posting_codes.supports_secretary_events = true`. Programme PC-created events require exact equality with both the schedule `programme_code` and `posting_code`; an unresolved/null schedule programme fails closed for this source. Both sources remain subject to the normal scheduled-event, date-range, reporting-period, status, and already-submitted rules. Programme identity is never inferred from a posting code, institution, target, catalogue row, native teaching mapping, fuzzy match, or first candidate. Ad-hoc submission remains available even when secretary-created event lists are not supported, and all Non-NHG attendance remains recording/export-only.


### Admin / Programme Coordinator (PC)

**Scope:** Master Admin is an explicit persisted tier (`role = admin`, `admin_level = master`). Programme Coordinators are scoped via `users.programme_scope TEXT[]`; missing, `NULL`, empty, and blank scopes grant no programme access (not all-access) and never imply Master Admin.

**RDB Upload Flow:**
1. Master Admin selects reporting period and uploads `.xlsx` via `POST /admin/upload/rdb`
2. `rdb_parser.py` detects sheets dynamically (not by name — by scanning for date-range headers in row 2 and MCR patterns in column C)
3. Parser looks up `programmes` table for each resident's specialization:
   - `rdb_alias` normalisation (e.g., `Infectious Disease` → `ID`, `Surgery-in-General` → `SIG`)
   - `r_year_required` flag: if `false`, sets `r_year = 'ALL'` sentinel on `resident_postings`
   - SPORTSMED/PALLMED have `r_year_required = true`, `is_subspecialty = false`, and preserve R4–R6 unchanged
4. For each posting cell: parses the cell and applies distinct `main_posting`, `combine`, or `half_month` persistence semantics. Half-month sets `active_months_weight = 0.5` once and never halves the TTF target.
5. Writes to: `residents` (upsert by MCR), `resident_postings` (full replace within selected `reporting_period_id` after successful parse/validation), `posting_codes` (upsert)
6. Calls `hibernate_stale_surplus()` after insert
7. Writes `upload_logs` row with `upload_type = 'rdb'`
8. Re-upload: safe — treats upload as complete snapshot and replaces all `resident_postings` within the selected `reporting_period_id` after successful parse/validation

**TTF Upload Flow:**
1. Master Admin selects any programme, or a Programme PC selects a normalized programme in their scope, then uploads `.xlsx` via `POST /admin/upload/ttf`
2. Acquires scope-level PostgreSQL advisory lock (returns 409 if contended)
3. `ttf_parser.py` validates all rows before any writes
4. Full replace within `(reporting_period_id, programme_code)` scope: deletes existing `teaching_targets` and `teaching_name_catalogue` rows, then inserts new ones
5. Seeds `teaching_name_catalogue` from column K (Details of Training) — one row per keyword per TTF row
6. Seeds `posting_groups` from column E when non-empty
7. Non-tracked rows (`is_tracked = false`) are still seeded into `teaching_name_catalogue` for event visibility
8. **No 422 attendance guard on re-upload.** If existing attendance records reference teaching names that no longer map to a catalogue row, they are returned as warnings — upload still returns 200
9. Admin uses `PUT /admin/teaching-targets/{id}` CRUD for mid-period corrections (updates `details_of_training` and re-seeds catalogue rows for that specific target)

**FormF1 Upload Flow:**
1. Master Admin selects reporting period and uploads `.xlsx` via `POST /admin/upload/form-f1`
2. `form_f1_parser.py` reads `Table 1`, detects header row/columns dynamically where possible (with current-template fallback E for MCR, M–X for monthly statuses, Y for promotion date)
3. Persists only MCR, monthly statuses (`status_raw` + `is_active` by month), and promotion date; other FormF1 profile columns are non-authoritative
4. Status normalisation: `Active`/`Extension` → `is_active = true`; `Inactive` → `is_active = false`
5. Full replace per `reporting_period_id` scope; re-upload allowed at any time
6. Compliance uses the status selected by the AY bucket label for the entire bucket, including dates that cross a raw calendar-month boundary

**Academic Calendar / Public Holidays Upload Flow:**
1. Master Admin uploads workbook via `POST /admin/upload/public-holidays` (endpoint name unchanged)
2. Parser reads `Public Holidays` sheet into `public_holidays`
3. Parser reads `AY Dates` sheet into `academic_month_boundaries`
4. `Fr RMT` sheet is ignored
5. Upload summary includes both PH and AY-boundary results (`public_holidays_created`, `academic_month_boundaries_created`, `ay_categories_parsed`, `academic_year_label`, `ignored_sheets`)

**Reporting Periods:** CRUD via `/admin/reporting-periods`. Status values are `active` and `inactive`; admins can also set `activate_on` and `deactivate_on` scheduled transition dates. `PUT /admin/reporting-periods/{id}/activate` and `/deactivate` update operational status only and return Data Revalidation impact summaries. Final close/freeze with surplus hibernation, clawback, and snapshots is separate future work.

**Programme PC Teaching Event CRUD (implemented 4B):** PCs manage scheduled teaching events for their own programmes through `/admin/programme-teaching-events` endpoints. PC-created events are programme-owned through `teaching_events.created_for_programme_code`; secretary-created events remain posting-owned/programme-neutral. See `api.md` and `business-logic.md` for authorization, visibility, PH block, and delete-with-attendance rules.

**Master Admin Secretary/PC Events:** The user-facing Master Admin review surface is **Secretary/PC Events** while the existing `/admin/secretary-events` route remains stable. It lists both Secretary-created and Programme PC-created scheduled events, excludes resident ad-hoc events, and provides an explicit Master Admin-only force-delete override. The override permanently removes linked native and Non-NHG attendance plus the selected event in one audited transaction; ordinary Secretary/PC delete-with-attendance guards remain unchanged.

**Compliance Reporting Views — 4 specified tabs plus one deferred placeholder:**
1. Monthly View — per-resident monthly attendance summary
2. Posting View — posting-level compliance with traffic light
3. Attendance Breakdown — by session type within each posting
4. Submitted Attendances — raw flat export
5. Clawback — deferred placeholder; no implementation-ready response, financial, or final-close contract

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

**STP Ownership:** Secretary creates STP as a planning document. STP is never uploaded to the system. PC manually converts STP → TTF before a Master Admin or Programme PC for that normalized in-scope programme uploads it. Column K (Details of Training) must be added manually.

**Provisioning:** TTSH-only at launch — 1 account per TTSH posting code. No schema change needed for other institutions.

> **⚠️ Most likely LLM mistake:** Building `end_time` as a request field on the secretary event creation endpoint. `end_time` is always server-computed from `start_time + duration_hours`. Accepting client-provided `end_time` creates inconsistency between stored duration and actual end time, causing incorrect compliance window calculations.

---

### NHG Resident

**Scope:** All DB queries are filtered to the current `resident_id` resolved from the validated opaque application session and reloaded resident row.

**Submission Portal:**
- Resident logs in with MCR → backend creates an opaque cookie-backed app session; current `programme_code` is reloaded from `residents`
- `GET /resident/events` returns teaching events for:
  - Assigned/current posting secretary events: derived from `resident_postings` for the selected/current date
  - Native programme TTSH department secretary events: derived from explicit native-programme-to-TTSH-posting mapping
  - Native programme PC-created events: `created_for_programme_code = resident.programme_code`
- **Critical gating rule:** Assigned-posting visibility exists only after the resident's posting schedule has been uploaded via RDB. No RDB upload = no assigned-posting visibility. Enforced by `resident_postings` lookup at request time.
- Example: a native GRM resident posted to TTSH Rehab sees TTSH Rehab secretary events, TTSH GRM secretary events, and GRM PC events. A native Rehab resident posted to TTSH GRM sees TTSH GRM secretary events, TTSH Rehab secretary events, and Rehab PC events.
- Events filtered by `teaching_name_catalogue` — only shows events whose `teaching_name` exists in the resident's catalogue for their `(posting_code, programme_code, r_year, reporting_period_id)`
- Only past/today events shown (`event_date <= today`)
- Already-submitted events excluded

**Attendance Submission:**
- `POST /resident/attendance` with `{ "event_ids": ["uuid1", "uuid2"] }`
- Weekend sessions with no matching `weekend_exceptions` rule: stored, but `compliance_warning` returned in response
- Active duplicate prevention uses a submitted-only unique index on
  `(resident_id, teaching_event_id)`; removed history is retained and a later
  resubmission receives a new row.

**Ad-hoc Teaching:**
- Date-first dropdown flow: resident selects teaching date, backend derives assigned posting, resident selects attended TTSH department/programme, then selects catalogue-backed teaching evidence from TTF Column K / `teaching_name_catalogue`
- `POST /resident/adhoc-teaching` — resident submits selected teaching not pre-created by secretary
- A narrow database function derives the authenticated creator/family and
  creates the immutable-owned `teaching_events` row plus matching attendance
  row in the same caller transaction.
- `details_of_session` is display/audit-only and has no compliance use
- PH dates hard-blocked (422)
- Countable ad-hoc compliance maps to `Department/Programme Teaching [1h]` under the assigned posting for the selected date, not the attended TTSH department unless it is also the assigned posting
- If the assigned-posting `Department/Programme Teaching [1h]` target cannot be resolved, return unavailable/not-countable rather than guessing
- UI helper copy: `Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.`

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
| TBD-7 | Active/inactive source (resolved) | FormF1 is the final authoritative source for active/inactive status. `Active` and `Extension` are active; `Inactive` is inactive. The status selected by the AY bucket label gates both numerator and denominator for the whole bucket. | Keep FormF1 parser/upload + AY-label selection of `form_f1_records.is_active` as the final path. Do not implement RDB-derived denominator logic. |
| TBD-MIGRATION | Historical data migration strategy | Three options: archive only / summary migration / full migration. decision needed before future final close/freeze. | Do NOT build migration tooling until option is confirmed. Add TODO: `# TBD-MIGRATION: awaiting stakeholder decision` |

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
| Reallocation scope | Raw session counts before final capping; one-for-one within physical posting/R-year context/tag prefix; alphabetical tag order; no duration or cross-posting transfer | PM approval |
| Compliance unit | Session counts, never hours | PM approval |
| Reallocation write | Read-time only via `reallocate_by_tag()`; never written to `surplus_ledger` | PM approval |
| TTF upload behaviour | Full replace within `(reporting_period_id, programme_code)` scope; warn (not 422) if attendance exists | PM approval |
| RDB re-upload | Full replace within selected `reporting_period_id` after successful parse/validation | PM approval |
| FormF1 re-upload | Full replace within `reporting_period_id` scope; allowed at any time | PM approval |
| Posting code source | `posting_codes` table only; never derived by regex or string pattern | PM approval |
| Resident event visibility | Assigned posting secretary events + native programme TTSH department secretary events + native programme PC-created events; assigned-posting source requires RDB `resident_postings` | PM approval |
| Compliance target lookup | Use `resident_postings.r_year`, not `residents.r_year` | PM approval |
| TTF is compliance input | STP is planning only; never uploaded to system | PM approval |
| `teaching_events.session_type_id` | Display/prototype only; does NOT drive compliance | PM approval |
| CME/SMC points | Informational only; do NOT feed compliance | PM approval |
| Active/inactive source | `form_f1_records.is_active` (final authoritative source) | Confirmed |
| R year configuration | 20 programmes use `r_year = 'ALL'`; 8 require R-year. SPORTSMED/PALLMED use R4–R6 and `is_subspecialty = false` | PM approval |
| `global_session_types` priority | Matched events excluded from compliance BEFORE `teaching_name_catalogue` lookup | PM approval |
| ORTHO weekend mutation | Exact original 3h type only; subtract two hours from end, project to the 1h type, then apply Saturday 08:30–10:30 to adjusted time; raw rows unchanged | PM approval |
| Compliance predicate | Unrounded posting percentage is canonical; `target_70` is a displayed whole-session target | PM approval |
| Persistent surplus | Idempotently recomputed raw eligible attendance minus target; derived audit state, never added back to attendance | PM approval |
| Native-programme attribution | Approved out-of-posting native events project to one 1h session under the assigned posting and target | PM approval |
| FM compliance | Standard engine; no `compliance_variant`; two FM annotations only | PM approval |
| FM Saturday exception | **Removed from confirmed weekend_exceptions list.** No FM row in seed data. Final. | PM approval |
| Public holiday block | Secretary and resident ad-hoc creation on PH dates hard-blocked (422) | PM approval |
| Multi-posting rules source | Seeded in DB; managed via admin CRUD; no file upload | PM approval |
| Ad-hoc teaching | `POST /resident/adhoc-teaching`; `is_adhoc = true`; countable NHG ad-hoc maps to `Department/Programme Teaching [1h]` under assigned posting | PM approval |
| Duration in TTF | Embedded in session type name as `[Xh]`; no separate duration column | PM approval |
| Non-tracked events | Seeded into `teaching_name_catalogue` for visibility; excluded from compliance | PM approval |
| Clawback tab | Future/deferred placeholder; ordinary compliance does not depend on its unresolved contract | Deferred |
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

- **Owner:** Master Admin uploads
- **Format:** `.xlsx`
- **Sheets:** Dynamic — detected by scanning for date-range headers in row 2 and MCR patterns in column C. Known sheets: `Phase 1 & 2`, `Phase 3`, `Phase 1 & 2 (FM)`, `SSR`. Do NOT hardcode sheet names.
- **Key columns:** A (employee_code), B (name), C (MCR), D (classification), E (base_institution), F (r_year), G (specialization → programme_code), H (reg_type), I+ (posting per month — dynamic range)
- **Programme resolution at parse time:** `rdb_parser.py` queries `programmes` for `rdb_alias` normalisation and `r_year_required`; R-year-required programmes preserve normalized R values without subspecialty remapping
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

- **Owner:** Master Admin uploads for any programme; Programme PC uploads only for a normalized programme in scope and manually creates it from STP
- **Format:** `.xlsx`
- **Columns:** A (reporting_period), B (programme_code), C (r_year — may be comma-separated), D (posting_code), E (dashboard_posting → seeds `posting_groups`), F (session_type with `[Xh]` duration), G (monthly_target), H (is_tracked), I (is_reallocatable), J (tag), K (details_of_training — comma-separated keywords, **mandatory**)
- **Column K is mandatory.** Absent from STP — PC adds manually. Without it, `teaching_name_catalogue` is empty and residents see zero events.
- **Duration:** Embedded in session type name as `[Xh]`. No separate column. Secretary picks `start_time` only; `end_time` server-computed.
- **Multi-year rows:** "R1,R2,R3" exploded into separate `teaching_targets` rows. `r_year = 'ALL'` for 20 programmes; SPORTSMED/PALLMED use R4–R6 unchanged.
- **Column E → `posting_groups`:** When non-empty, upserts a `posting_groups` row linking the posting code to the group.
- **Writes to:** `teaching_targets`, `session_types`, `teaching_name_catalogue`, `posting_codes`, `posting_groups`
- **Upload:** Full replace within `(reporting_period_id, programme_code)`. No 422 re-upload guard — warns if attendance exists.
- **Concurrency:** Scope-level advisory lock; 409 if contended.

### FormF1

- **Owner:** Master Admin uploads
- **Format:** `.xlsx`
- **Sheet:** `Table 1`; detect header row and required columns dynamically where practical (current template often has row 28 headers and row 29+ data)
- **Columns used for persistence:** MCR, monthly status columns, promotion date/senior promotion date only
- **Current-template fallback positions:** E (MCR), M–X (monthly status), Y (promotion date)
- **Status normalisation:** `Active`/`Extension` → `is_active = true`; `Inactive` → `is_active = false`
- **Extension:** Treated as Active for ordinary compliance; financial treatment remains deferred
- **Employed residents:** FormF1 remains the ordinary-compliance active/inactive authority; financial treatment remains deferred
- **FormF1 is per-resident per-calendar-month** — not per posting code. A month cannot be Active for one posting and Inactive for another.
- **AY gate:** The AY bucket's `month_label` selects that calendar-month FormF1 row for the whole bucket. Do not switch on the event's raw month or split/prorate the bucket.
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

- ⚠️ **Raw reallocation then capping (BL-1/BL-3):** Transfer raw achieved session counts one-for-one within a physical posting/R-year context/tag prefix before final session-type/R-year-context caps. Duration is never a multiplier.
  *Silent consequence:* Capping before transfer or transferring hours changes donor supply and compliance results.

- ⚠️ **70% threshold at POSTING level (BL-2)**, aggregated across all session types. The unrounded `percentage >= 0.70` predicate is canonical; `ceil(target_100 × 0.70)` is display-oriented.
  *Silent consequence:* Applying the displayed ceiling as the predicate makes capped fractional targets fail incorrectly.

- ⚠️ **`resident_postings.r_year` for target lookup**, NOT `residents.r_year`. Target and cap each mid-period R-year context separately, then sum.
  *Silent consequence:* Merging raw attendance before capping or duplicating posting-wide active months reproduces a legacy defect.

- ⚠️ **Tag-based reallocation (`reallocate_by_tag()`, BL-3) is read-time only.** Within one physical posting/R-year context/tag prefix, use raw session-count donor supply above the type's 70% target, decrement it after every transfer, and cap only after all transfers. Never write to `surplus_ledger`; sort tags alphabetically, not by duration.
  *Silent consequence:* Writing back corrupts audit trail and causes double-counting.

- ⚠️ **`teaching_events.session_type_id` is display only.** Compliance session type resolved per-resident at read time via `teaching_name_catalogue` using `(teaching_name, r_year, posting_code, programme_code, reporting_period_id)`.
  *Silent consequence:* Using `teaching_events.session_type_id` produces wrong session type for cross-programme residents.

- ⚠️ **`form_f1_records.is_active` gates the AY bucket.** The bucket label selects the FormF1 month for both denominator and numerator, even when the event's raw date crosses into the next calendar month.
  *Silent consequence:* Ignoring gate inflates active_months, deflates compliance percentages.

- ⚠️ **`r_year = 'ALL'` sentinel.** 20 programmes use it. SPORTSMED/PALLMED require R4–R6 and are not subspecialty-remapped.

- ⚠️ **ORTHO mutation is exact-type and read-time only.** Only `NHG Orthopaedic Surgery Residency Teaching [3h]` is projected: subtract two hours from original end time, map to `National Didactics & Department Teaching [1h]`, then test the adjusted Saturday interval against 08:30–10:30. Sunday is excluded; other ORTHO types are not mutated and require any separately applicable acceptance rule.
  *Silent consequence:* Writing mutation to DB corrupts audit trail.

- ⚠️ **`posting_groups` aggregation.** When `posting_code` belongs to a group, `active_months` and `target_100` summed across ALL group members. Each posting's own `monthly_target` applies per phase.
  *Silent consequence:* Calculating independently per-posting produces wrong compliance for grouped postings.

### Supporting Rules

- Traffic light: green ≥ 70%, amber 50–69%, red < 50%
- Surplus resets to zero at each `reporting_periods` boundary
- Persistent surplus is derived pre-tag state: `max(cumulative raw eligible attendance - cumulative target_100, 0)`. Replace idempotently; never add it back as attendance or directly consume it during tag transfer.
- Hibernation reflects that no active phase remains at the physical posting and is refreshed with posting lifecycle/recomputation. Period-boundary reset is confirmed; final-close transaction mechanics remain deferred.
- Weekend teaching: session stored regardless. `compliance_warning` returned if no matching `weekend_exceptions` rule. Confirmed exceptions: URO (2 rows — OR logic), DERM (all Saturday), ORTHO (08:30–10:30 with mutation). FM: **removed from confirmed list; no seed row.**
- Public holidays: event creation hard-blocked (422). No compliance denominator impact.
- CME/SMC points: informational only. Do NOT feed compliance.
- Non-tracked events (`is_tracked = false`): seeded into `teaching_name_catalogue` for visibility. Excluded from both numerator and denominator.
- Zero-target TTF rows (`monthly_target = 0`): seeded into `teaching_name_catalogue` for visibility and attendance capture. Excluded from both numerator and denominator and from shortage, surplus, reallocation, percentage, and clawback calculations.
- FormF1 status: `Active` and `Extension` are active; `Inactive`, blank, `NULL`, and whitespace-only monthly cells are inactive. A valid MCR row persists an inactive record for each blank in-scope month.
- Clawback (BL-10): explicitly deferred. Rates, funding-year selection, classification, suppressions, grouping/billing, rounding, and final-close behavior are not implementation-ready.
- Ad-hoc teaching (BL-9): `is_adhoc = true` on `teaching_events`. Countable NHG ad-hoc maps to `Department/Programme Teaching [1h]` under assigned posting; selected teaching name is catalogue-backed evidence, not the compliance session type.

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
| `GET/POST /admin/programme-teaching-events` | Implemented 4B PC event CRUD | Programme-owned scheduled events via `created_for_programme_code` |
| `GET /admin/secretary-events` | Secretary/PC Events | Master Admin review of both scheduled event sources; stable legacy route |
| `POST /admin/secretary-events/{id}/force-delete` | Force-delete one scheduled event | Explicit Master Admin only; atomically deletes linked native/Non-NHG attendance, event, and writes audit |
| `GET /admin/external-attendance/export.xlsx` | Implemented external Excel export | Recording/export-only; never enters compliance |
| `GET /admin/reports/clawback` | Deferred clawback placeholder | No implementation-ready response or calculation contract |
| `PUT /admin/reporting-periods/{id}/activate` | Activate period | Allows new resident submissions |
| `PUT /admin/reporting-periods/{id}/deactivate` | Deactivate period | Blocks new resident submissions; no snapshots/clawback/surplus hibernation |

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
| `GET /resident/events` | Available events | NHG: assigned posting secretary + native programme department secretary + native PC events; gated by `resident_postings`, explicit native mapping, and catalogue rules |
| `POST /resident/attendance` | Submit attendance | Returns `compliance_warning` for unmatched weekend sessions |
| `GET /resident/adhoc-teaching-options` | Planned ad-hoc dropdown options | Date-first; derives assigned/date-matched posting; attended TTSH department dropdown; catalogue-backed options |
| `POST /resident/adhoc-teaching` | Ad-hoc submission | 422 on PH; `is_adhoc = true`; no CME points; NHG counts as `Department/Programme Teaching [1h]` under assigned posting, Non-NHG is export-only |
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
| `r_year = 'ALL'` | `resident_postings`, `teaching_targets`, `teaching_name_catalogue` | Catalogue lookup fails silently for 20 programmes; SPORTSMED/PALLMED instead use R4–R6 |
| `is_tracked` | `teaching_targets` | Untracked sessions must not feed `achieved_and_counted` |
| `is_reallocatable` + `tag` | `teaching_targets` | Missing tag = no reallocation; surplus silently stays unallocated |
| `is_hibernating` | `surplus_ledger` | Lifecycle annotation only; the ledger is recomputed from raw attendance/target and is not a reallocation input |
| `session_type_id` | `teaching_events` | Display only — NOT for compliance |
| `created_for_programme_code` | `teaching_events` | PC-created scheduled events are programme-owned; null secretary events remain programme-neutral |
| `details_of_session` | `teaching_events` (planned) | Display/audit-only for ad-hoc sessions; no compliance use |
| `achieved_and_counted` | Computed value | Final post-reallocation, post-context-cap value; raw achieved drives donor supply |
| `programme_scope` | `users` | `TEXT[]` — Admin sees only listed programmes. NULL = no access. |
| `code` | `posting_codes` | Source of truth; never derive by regex |
| `is_active` | `form_f1_records` | FormF1 gate for compliance denominator |
| `is_active` | `global_session_types` | Inactive = hidden from dropdown + no compliance exclusion |
| `mutates_to_session_type_id` | `weekend_exceptions` | Read-time ORTHO mutation; never write to DB |
| `group_code` | `posting_groups` | Must aggregate compliance across group, not calculate independently |
| `active_months_weight` | `resident_postings` | Default 1.0; set to 0.5 for half_month rule. Affects target calculation. |
| `posting_code` | `attendance_records` | Audit copy only — never used for compliance attribution |

> **⚠️ Most likely LLM mistake:** Using `attendance_records.posting_code` for compliance attribution. It is an audit-only copy. Compliance always uses `teaching_events.posting_code`. The silent consequence is misattributed attendance when a resident's posting changes.

---

## Section 16 — Frontend Architecture

**Status:** Current pre-compliance staff, NHG Resident, and Non-NHG Resident surfaces are implemented. Phase 6 compliance/final-close UI remains separate.

### Pages and Routes (Per Role)

**Admin:**
- Upload pages: Master Admin has RDB, TTF, FormF1, and PH; Programme PC has TTF only for a normalized programme in scope (each with file select + POST + result display)
- Configuration panel: CRUD for `loa_types`, `weekend_exceptions`, `multi_posting_rules`, `posting_groups`, `global_session_types`, `programmes`
- Programme teaching event management: scheduled PC-created events scoped by programme
- Secretary/PC Events: Master Admin review of Secretary and Programme PC scheduled events with an audited force-delete confirmation flow
- Phase 6 reporting dashboard remains deferred: Monthly View, Posting View, Attendance Breakdown, Submitted Attendances, and the clawback placeholder
- Non-NHG attendance export preview/download for forwarding to NUH/SingHealth PCs
- Reporting period management: list, create, update, activate, deactivate, delete
- Upload log viewer

**Secretary:**
- Teaching event CRUD (create, duplicate, series, delete)
- Teaching schedule calendar view
- CME dashboard
- Resident list (current posting)

**Resident:**
- Submission portal: event list filtered by posting + catalogue
- Ad-hoc teaching form: date-first → catalogue-backed teaching option dropdown + optional `details_of_session`
- Personal compliance dashboard remains Phase 6 work
- Submitted attendances list

**Non-NHG Resident:**
- Self-registration/login with `name`, MCR, `home_cluster`, and upcoming NHG posting schedule
- Submission portal and past attendance backed by `external_attendance_records`
- Event/ad-hoc derivation uses date-matched `external_resident_postings`; gaps return unavailable/no posting for selected date
- No NHG compliance dashboard; attendance is recording/export-only

### Key UI Patterns

- **Upload flow:** File select → POST to upload endpoint → parse JSON response → display results/warnings/errors
- **Secretary dropdown:** Unified list from `GET /secretary/teaching-name-options` (includes `is_global` flag for visual distinction)
- **NHG Resident ad-hoc:** Date-first input → assigned posting derivation → attended TTSH department dropdown → catalogue-backed teaching option dropdown → fixed `Department/Programme Teaching [1h]` attribution under assigned posting
- **Non-NHG ad-hoc:** Date-first input → date-matched forecast posting → attended TTSH department dropdown for option filtering/export context; recording/export-only, no NHG compliance
- **Non-NHG export:** Admin/PC preview + Excel download for forwarding Non-NHG attendance to NUH/SingHealth PCs
- **Weekend compliance warning:** Display warning text after `POST /resident/attendance` when `compliance_warning` is non-null
- **Traffic light:** Green (≥70%), Amber (50–69%), Red (<50%) colour indicators on compliance views

- **Warning issue review:** Upload warnings are persisted as first-class review issues with manual resolve/dismiss/supersede status actions. These actions do not mutate upload summaries or source data.

### Technical Constraints

- Tailwind CSS: core utility classes only — no JIT compiler
- TypeScript type definitions: `src/types/`
- API client functions: `src/api/`
- Auth state: local/demo may use synthetic headers; production uses backend-owned opaque cookies, memory-only identity/CSRF state, and backend-mediated Supabase staff authentication

> **⚠️ Most likely LLM mistake:** Building the resident ad-hoc teaching form with teaching name first and date second, or allowing arbitrary free-text teaching names to drive mapping. The confirmed UX flow is date-first, then assigned/date-matched posting derivation, attended TTSH department dropdown, and catalogue-backed teaching option dropdown. For NHG Residents, compliance attribution is fixed to `Department/Programme Teaching [1h]` under the assigned posting. The silent consequence is a broken dropdown, wrong attribution, or bypassed TTF Column K evidence.

---

## Section 17 — Environment Variables and Local Development

### Environment Variables

| Name | Layer | Purpose | Example | Required |
|------|-------|---------|---------|----------|
| `DATABASE_URL` | Backend (server-only) | Restricted runtime async PostgreSQL connection when H-E is enabled | `postgresql+asyncpg://runtime-user:placeholder@localhost:5432/mata` | Yes |
| `MATA_AUTH_DATABASE_URL` | Backend (server-only) | Distinct restricted auth-helper async PostgreSQL connection | `postgresql+asyncpg://auth-user:placeholder@localhost:5432/mata` | H-E / production |
| `SYNC_DATABASE_URL` | Backend (server-only) | Distinct migration/ownership sync PostgreSQL connection | `postgresql://migration-user:placeholder@localhost:5432/mata` | Migrations |
| `MATA_DATABASE_RLS_ENABLED` | Backend | Enables the H-E database boundary; production requires `true` | `false` locally / `true` in production | Production |
| `MATA_DATABASE_RUNTIME_ROLE` | Backend | Stable runtime capability group | `mata_app_runtime` | H-E |
| `MATA_DATABASE_AUTH_ROLE` | Backend | Stable auth-helper capability group | `mata_auth_internal` | H-E |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend (server-only) | Bounded Supabase admin operations | placeholder only | Only where required |
| `SUPABASE_PUBLISHABLE_KEY` | Backend (server-only in H-D) | Backend-mediated staff password authentication | placeholder only | Supabase mode |
| `MATA_SESSION_HASH_KEY` | Backend (server-only) | Keyed session/CSRF/user-agent digests | placeholder only | Production cookie mode |
| `RATE_LIMIT_HASH_SECRET` | Backend (server-only) | Keyed rate-limit identifiers | placeholder only | Production PostgreSQL limiter |
| `VITE_API_BASE_URL` | Frontend | Same-origin API base | `/api/v1` | Yes |

**Server-only variables and credentials must never be exposed to the frontend.** The production browser has no Supabase client configuration and uses relative `/api/v1`.

### Local Development

| Setting | Default |
|---------|---------|
| Backend port | 8000 |
| Frontend port | 5173 |
| API base URL | `http://localhost:8000/api/v1` |
| CORS | Explicit allowlist — no wildcard `*` in production |

### Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm ci
npm run dev
```

### `.env.example` Pattern

Provide only placeholder values. Real secrets must not be committed. `.env` files must be in `.gitignore`.

> **⚠️ Most likely LLM mistake:** Hardcoding `DATABASE_URL` or `JWT_SECRET` in source code or committing `.env` files. The silent consequence is credential exposure in version control.

---

## Section 18 — Security

**For the current cross-cutting security contract, see `security.md`.**

### Key Rules (Summary)

- **All security checks enforced server-side.** Frontend checks are UX convenience only — never security boundaries.
- **Identity derives from the validated opaque app session plus a current subject-row reload.** Never trust client-provided user IDs, roles, programme codes, cookie claims, or raw identity headers.
- **Admin endpoints:** Check current `role`, explicit `admin_level`, and normalized programme scope; empty scope grants nothing.
- **Secretary endpoints:** Check current `role = 'secretary'` and exact database-owned posting scope.
- **Resident endpoints:** Scope all queries to the current database-owned resident subject.
- **SQL injection:** SQLAlchemy ORM or parameterized raw SQL only. Never interpolate user input into SQL strings.
- **Mass assignment:** Never pass `**request.dict()` to ORM. Explicitly allowlist fields in Pydantic schemas.
- **File uploads:** Type/MIME/size validation plus ZIP/XML preflight, compression-ratio and workbook-resource bounds server-side. `.xlsx` only (`.csv` additionally for PH).
- **CORS:** Explicit allowlist of trusted origins. No wildcard in production.
- **Error responses:** No stack traces, SQL errors, or internals.
- **Rate limiting:** PostgreSQL-backed in production with atomic counters and HMAC-only identifiers.
- **Security headers:** HSTS, X-Frame-Options: DENY, X-Content-Type-Options: nosniff, Referrer-Policy, CSP
- **Supabase service role key:** Server-only. Never exposed to frontend or client-side env vars.
- **Browser/Data API grants:** `PUBLIC`, optional `anon`, and optional `authenticated` application-object privileges are revoked by `20260722_000024`.
- **RLS:** H-E locally implements 34 RLS-enabled application tables, 84 runtime-targeted policies, exact helper/table/column grants, and a restricted non-owner runtime. Grant revocation alone was not RLS, and local implementation is not deployed proof.
- **Ad-hoc ownership:** Revision `20260728_000028` adds immutable typed native
  or Non-NHG creator identity to every Resident-created ad-hoc event. Only a
  narrow runtime helper may create the matching event/attendance pair;
  ordinary direct ad-hoc insertion, another Resident, and the opposite storage
  family are denied. See
  `docs/archive/security/phase-5b/5b_h_aud_m04_atomic_attendance.md`.
- **Session management:** Opaque 256-bit session and CSRF credentials; only keyed digests persist. Strict host-only cookie, synchronized CSRF, one-winner rotation, family logout, and generation fencing are implemented.
- **Reliable logout:** AUD-M-06 distinguishes immediate local sign-out from
  proof-positive server revocation. Pending/unconfirmed state blocks hydration
  and protected requests; only a non-sensitive pending tombstone and resolution
  watermark persist, while retry proof remains in memory and is bounded to
  four attempts with nominal automatic offsets of 0/1/3/7 seconds. Matching
  request ids, authentication revisions, and monotonic lifecycle ordering
  protect cross-tab, reload, stale-response, and newer-login transitions. See
  `docs/archive/security/phase-5b/5b_h_m06_reliable_logout.md`.
- **Request-body perimeter:** AUD-M-05 adds a pure ASGI 4 MiB global body
  cap and the same 4 MiB aggregate cap on same-origin
  `/api/v1/admin/upload/*` before authentication or multipart parsing. Files
  are capped at 3 MiB, leaving room for multipart framing;
  multipart requests accept one file, route-specific field counts, 4 KiB
  non-file parts, and 255-byte UTF-8 filenames. The Docker Nginx path mirrors
  the aggregate limits and streams uploads. This approved contract remains
  below the current Vercel Function path's separate 4.5 MB platform ceiling.
  Larger-file support requires a separately approved upload ingress. See
  `docs/archive/security/phase-5b/5b_h_m05_upload_preparser_limits.md`.

> **⚠️ Most likely LLM mistake:** Storing JWT tokens in `localStorage`. The confirmed approach is `HttpOnly` cookies. The silent consequence is XSS vulnerability — any script injection can steal the token.

---

## Section 19 — Known Risks and Blind Spots Summary

| Risk | Impact | Mitigation |
|------|--------|------------|
| Active/inactive source resolved | FormF1 is final; no RDB pivot for denominator logic | Gate on `form_f1_records.is_active`; keep RDB LOA/refresher/employed fields as parser/audit/display data only |
| TBD-MIGRATION open | No historical data migration plan | Do not build tooling until decision confirmed |
| Posting code patterns | Regex-based code generation silently produces wrong codes | Always query `posting_codes` table |
| `r_year = 'ALL'` sentinel | 20 programmes affected; lookup with actual r_year returns zero results | TTF matcher handles `ALL`; SPORTSMED/PALLMED preserve R4–R6 |
| TTF mid-period correction | Warn-on-reupload, not 422 | CRUD endpoint for corrections |
| Multi-posting fallback | No rule + no group → independent compliance, upload warning | Add `multi_posting_rules` or `posting_groups` entry |
| Implementation status ambiguity | Source-of-truth files are design specs | Verify against actual codebase before assuming live |
| ORTHO mutation | Over-broad predicate would mutate unrelated sessions | Match exact original type, adjust end time, and check Saturday window at read time |
| Clawback specification | Financial and final-close rules remain deferred | Do not implement or infer them from legacy evidence |
| FormF1 year suffix | Parser sample hardcodes '25'/'26' | Must be dynamic based on reporting period |
| FM Saturday exception | Removed from confirmed list | No FM row in `weekend_exceptions` seed data |
| Resident identity assurance | Separately governed product debt | Do not invent a factor; reopen only under an approved product scope |
| Local verification versus deployment | Passing code/tests do not prove deployed environment, migrations, grants, or cookie behavior | Run the documented post-deployment smoke against the approved target |
| Local H-E/lifecycle versus deployed RLS | A locally verified role/policy/session catalogue can be mistaken for deployed Supabase protection | Independently verify revision `20260727_000027`, lifecycle settings, credentials, ownership, policies, grants, helpers, PUBLIC/browser roles, expiry behavior, and five-role workflows on the approved target |
| Local AUD-M-04 versus deployed RLS | Immutable ad-hoc ownership and atomic helper behavior may be mistaken for deployed protection | Independently verify revision `20260728_000028`, strict populated backfill, creator/family RLS, helper ACLs, rollback, and concurrency on the approved target |
| Local AUD-M-05 versus deployed ingress | Application tests may be mistaken for proof that a provider enforces the same body limits before buffering | Verify the approved 3 MiB file and 4 MiB request contract, ingress buffering, timeout, same-origin path, response-cache behavior, and advertised upload size |
| Local AUD-M-06 versus deployed logout behavior | Local state-machine tests may be mistaken for proof of real network, browser-cookie, reload, or cross-tab behavior | Verify immediate local clearing, explicit pending state, proof-positive `server_logout_confirmed`, bounded retry, proofless reload, Web Lock replacement login, and storage/evidence hygiene on the approved target |
| Emergency bearer compatibility | Routine enablement would reintroduce browser-token risk | Keep double opt-in, time-bounded, and rollback-only |

See `99_decision_log_and_gap_audit.md` for the full risk register.

> **⚠️ Most likely LLM mistake:** Hardcoding a FormF1 year suffix. Derive every `month_label` dynamically from the selected reporting period dates so it matches `academic_month_boundaries.month_label`; a hardcoded year silently breaks the AY-label active/inactive gate.

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
clawback, deferred financial rules, deferred suppression precedence,
MCR, programme coordinator, admin, secretary, resident portal,
submission portal, duplicate detection, weekend_exceptions, public_holidays,
advisory lock, programme_scope, dual posting, multi_posting_rules,
dormant posting code, LOA, LOA types, employed, refresher training,
TBD-1, TBD-MIGRATION, placeholder logic,
X-User-Role, X-User-Id, X-User-Programme, X-User-MCR, X-User-Site,
KEEP PORT discard legacy R script, Codex specification, implementation status,
ORTHO mutation, mutates_to_session_type_id, adjusted_duration_hours,
posting_groups aggregation, group_code, global_session_types, is_global,
compliance_warning, ad-hoc teaching, is_adhoc, secretary provisioning,
PC provisioning, RLS, row-level security, security headers, HSTS,
rate limiting, service role key, CORS, JWT, Supabase Auth,
rdb_alias, is_subspecialty, SPORTSMED PALLMED R4 R5 R6,
FM standard engine, NHGPlyNHGPly, Department Teaching 5h,
clawback tab, reporting period activate, reporting period deactivate, future final close/freeze, period_snapshots, hard cutover
```
