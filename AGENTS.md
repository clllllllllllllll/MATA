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
| Cache / rate limit store | In-memory for local dev → Redis or platform equivalent for production |

## Repo Structure

```
mata/
├── AGENTS.md                  # This file
├── docs/
│   ├── schema.md              # Database schema — tables, columns, types, constraints
│   ├── api.md                 # API endpoints — routes, request/response shapes
│   ├── business-logic.md      # Compliance engine, surplus chain, reallocation rules
│   └── parsing.md             # RDB, TTF, FormF1, and Academic Calendar / Public Holidays upload parsing rules and edge cases
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
│   │   │   └── reporting.py   # reporting_periods, surplus_ledger, form_f1_records
│   │   ├── routers/           # FastAPI routers (one file per domain)
│   │   │   ├── admin.py       # RDB upload, TTF upload, FormF1 upload, Academic Calendar / Public Holidays upload, reporting views, period CRUD, multi-posting rules CRUD, weekend_exceptions CRUD, loa_types CRUD, programmes CRUD
│   │   │   ├── secretary.py   # Teaching event CRUD, CME dashboard
│   │   │   ├── resident.py    # Submission portal, dashboard, attendance CRUD, ad-hoc teaching
│   │   │   └── auth.py        # Auth stub (swap to Supabase Auth later)
│   │   ├── services/          # Business logic (no HTTP concerns)
│   │   │   ├── compliance.py  # 70% threshold, capping, traffic light
│   │   │   ├── surplus.py     # Surplus chain, tag-based reallocation
│   │   │   ├── clawback.py    # Clawback calculation engine (Phase 10)
│   │   │   ├── rdb_parser.py  # RDB Excel upload parser
│   │   │   ├── ttf_parser.py  # TTF Excel upload parser
│   │   │   ├── formf1_parser.py  # FormF1 Excel upload parser
│   │   │   ├── public_holiday_parser.py  # Academic Calendar / Public Holidays workbook parser (Public Holidays + AY Dates; Fr RMT ignored)
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
| Admin (Programme Coordinator) | Email + password | Programme-scoped via `programme_scope TEXT[]`. Each account linked to one or more programmes. Manages RDB, TTF, FormF1, and Academic Calendar / Public Holidays uploads, teaching targets, period close, multi-posting rules, weekend exceptions, all reporting views for their programmes only. |
| Department Secretary | Email + password | Scoped to ONE specific posting site (e.g. TTSHAnaes only). Creates teaching events, views CME Dashboard and Teaching Schedule. Cannot create events on public holidays. |
| Resident | MCR number only | Sees teachings for current posting and native programme posting. Submission Portal + personal Dashboard + ad-hoc teaching submission. |
| External Resident | MCR number only after self-registration | NUH/SingHealth residents posted to NHG/TTSH departments. Uses separate external resident tables, can submit attendance/ad-hoc teaching, excluded from NHG compliance and clawback. |

## Auth Stub (Phase 1)

Until Supabase Auth is integrated, local `AUTH_MODE=stub` and non-production `AUTH_MODE=demo` use a simple middleware that reads role and identity from request headers:

```
X-User-Role: admin | secretary | resident | external_resident
X-User-Id: <users.id for admin/secretary> | <residents.id for resident> | <external_residents.id for external_resident> 
Residents log in using MCR only. After login, protected-route identity uses residents.id as the subject. MCR is a resident login credential and JWT/header claim, not the X-User-Id value.
X-User-Site: <posting_code>        # secretary only
X-User-Programme: <programme_code> # admin only, comma-separated for multiple e.g. DR,GRM
```

These headers are local stub/demo only and must not be trusted in `AUTH_MODE=supabase` or production-like modes. When Supabase Auth is wired in, the middleware derives the same identity shape from verified JWT/server-side state — the rest of the app doesn't change.

## System Initialisation Order

This is a strict dependency chain. Each step requires the previous one to be complete.

1. **Admin seeds multi-posting rules** → database seeded with combine/half_month/main_posting rules (one-time setup, managed via CRUD UI)
2. **Admin uploads Academic Calendar / Public Holidays** → `POST /admin/upload/public-holidays` parses `Public Holidays` + `AY Dates`, ignores `Fr RMT`, and populates `public_holidays` + `academic_month_boundaries` (PH event-creation block active)
3. **Admin uploads RDB** → residents, postings, rotation schedule created. Multi-posting rules applied at parse time to FM and combined posting cells. - Always apply RDB cell normalisation before posting cell classification (see docs/parsing.md)
4. **Admin uploads TTF** → session types, teaching targets, secretary dropdowns seeded
5. **Admin uploads FormF1** → active/inactive status per resident per calendar month seeded (denominator gate for compliance)
6. **Secretary creates teaching events** → events appear in resident portal
7. **Resident submits attendance** → compliance engine has data to calculate

## Key Architectural Rules

- **Session counts, not hours.** Compliance is measured in number of sessions attended. Duration is never a multiplier. 1 session = 1 session regardless of 0.5h or 3h.
- **70% threshold is at the POSTING level**, aggregated across all session types for that posting. Monthly percentages are display-only.
- **Surplus persists per (resident, department, session_type).** When a resident rotates away, surplus hibernates. When they return, it resumes. Surplus resets to zero at each reporting period boundary.
- **Tag-based reallocation flows top-down by duration only.** Longer-duration surplus can fill shorter-duration shortfall, never upward. One-for-one in session counts. Tag-group-only — surplus cannot flow across tag groups or across postings.
- **Teaching events are programme-neutral.** Secretary creates an event for a site; the compliance engine applies programme-specific TTF rules per resident.
- **UNIQUE constraint on (resident_id, event_id)** prevents duplicate attendance at the DB layer.
- **Session type is NEVER stored on attendance_records.** It is always resolved at compliance read time from `teaching_name_catalogue` using `(keyword = teaching_event.teaching_name, posting_code, programme_code, r_year, reporting_period_id)`. This means compliance always reflects the current TTF state — if a PC corrects the TTF, compliance recalculates automatically on the next read. The `session_type_id` on `teaching_events` is display/prototype only and is never used for compliance.
- **teaching_name_catalogue is the single source of truth for keyword→session_type mapping.** Seeded from TTF column K at upload time. One row per (keyword, posting, programme, r_year, period). Also serves as the event visibility gate — residents only see events whose teaching_name exists in their catalogue row.
- **TTF re-upload is always a full replace within scope, regardless of existing attendance.** There is no attendance guard blocking re-uploads. PCs may re-upload a revised TTF at any point in the period. Attendance records for events whose teaching_name no longer maps to a catalogue row will be silently excluded from compliance on the next read. The re-upload response warns the PC with counts of affected attendance.
- **No STP in the system.** STP data ("Details of Training") is manually added to TTF column K before upload. Column K is a mandatory field — without it, resident event visibility and session type resolution are non-functional.
- **Admin accounts are programme-scoped.** A PC account only sees residents, targets, and reports for their assigned programmes.
- **FormF1 is the final authoritative active/inactive source for compliance.** FormF1 active/inactive is calculated on a calendar month basis, which aligns with compliance targets. RDB posting phases use academic months — using RDB phases to derive active/inactive creates date boundary inconsistencies. FormF1 is final.
- **TTF zero targets are valid.** `monthly_target = 0` remains persisted and catalogue-seeded for event visibility and attendance capture, but contributes to neither compliance numerator nor denominator, and creates no shortage, surplus, reallocation, percentage, or clawback contribution.
- **Active/inactive from FormF1 gates the compliance denominator.** A resident-month is excluded from both numerator and denominator when `form_f1_records.is_active = false` for that month. `Active` and `Extension` are active; `Inactive`, blank, `NULL`, and whitespace-only monthly cells are inactive and valid resident rows persist those blank-month records. Employed residents are Active in FormF1.
- **LOA and Refresher Training data is captured in resident_postings** for audit/display. The compliance denominator is governed by FormF1, not by RDB LOA annotations. RDB LOA annotations are not acted on by the compliance engine — they are stored for display and future use only.
- **Secretary and resident event creation/submission on public holiday dates is hard-blocked.** `POST /secretary/teaching-events` and `POST /resident/adhoc-teaching` validate the event date against the `public_holidays` table and return 422 if the date matches.
- **Public holiday dates do not directly affect the compliance denominator.** Denominator impact is moot because secretary event creation and resident ad-hoc teaching are hard-blocked on PH dates.
- **AY Dates drive attendance/compliance month bucketing via `academic_month_boundaries`.** Resolver path: `resident.programme_code` → `programmes.ay_date_category` → `academic_month_boundaries` where `event_date BETWEEN start_date AND end_date`.
- **AY-date category resolution is programme-code-only and not header-text semantics.** It does not branch by JR/SR, r_year, or resident classification. Workbook SR/SRs wording is detection-only and must not be persisted. Internal categories are `im_subspec` and `non_im_subspec`.
- **Multi-posting rules are seeded in the database and managed through Admin CRUD.** `Multiple postings per month.xlsx` is a seed/update source, not a recurring upload. PCs maintain three logical tabs long-term: Main Posting, To Combine Posting, and Half Month Posting. Rules are looked up at RDB parse time to correctly collapse or split resident_postings rows.
- **FM main_posting semantics use the Main Posting `RDB Posting #1` trigger list.** If an FM multi-posting cell contains exactly one recognised trigger posting, collapse to that row's `Main posting`. If it contains zero recognised trigger postings, collapse to the configured `Exclusion (Only for FM)` value, usually `NHGPlyNHGPly`. If it contains two or more recognised trigger postings, do not infer; persist independently and emit `unmatched_multi_posting` unless an explicit rule exists. A singular `NHGPlyNHGPly` cell is a valid standalone posting and does not require a multi-posting rule.
- **FM uses the standard compliance engine.** FM is not a special compliance variant. There is no programmes.compliance_variant column and no separate FM branch or engine. The FM Saturday exception has been removed from the confirmed weekend_exceptions list. Do not seed any FM-specific weekend exception.
- **Ad-hoc teaching submissions are supported.** Residents can submit ad-hoc teachings not pre-created by secretaries. The system derives the posting from `resident_postings` at the given date and creates a `teaching_events` row (is_adhoc = true) and attendance record in the same transaction. PH block applies. Compliance treatment is identical to secretary-created sessions.
- **All uploads are audit-logged.** Every RDB, TTF, FormF1, and Academic Calendar / Public Holidays upload writes a row to `upload_logs` with full summary JSONB.
- **Period close generates frozen snapshots.** Closing a reporting period writes one `period_snapshots` row per programme. Historical compliance is served from snapshots, not by re-querying live tables.
- **Legacy system cutover.** FormSG and Google Forms submission channels must be closed at a confirmed cutover date aligning with a period boundary. In-flight submissions at cutover are processed one final time through the legacy R scripts. After cutover, all attendance flows through this system only. No hybrid operation.
- **R year required flag drives TTF matching.** Programmes where `r_year_required = false` use `r_year = 'ALL'` as a sentinel value in both `resident_postings` and `teaching_targets`. The TTF matcher checks `r_year == 'ALL' OR r_year == resident_r_year`. See `docs/business-logic.md` § BL-11.
- **Weekend session compliance warning.** When a resident submits attendance for a session on a Saturday or Sunday and no matching `weekend_exceptions` rule is found, the submission response includes a `compliance_warning` field. The session is stored; the resident is informed it will not count toward PTT compliance.
- **ORTHO weekend session mutation is read-time only.** ORTHO Saturday sessions of type `NHG Orthopaedic Surgery Residency Teaching [3h]` are mutated to `National Didactics & Department Teaching [1h]` at compliance read time via `mutates_to_session_type_id` and `adjusted_duration_hours` on the `weekend_exceptions` row. Raw attendance is stored as submitted — never mutated in the database.
- **Global session types are always excluded from PTT compliance.** `global_session_types` is a system-wide catalogue of attendance-trackable but compliance-exempt session types (e.g. Department Meeting). At compliance read time, if `teaching_event.teaching_name` matches any active `global_session_types.name`, the attendance record is excluded from both numerator and denominator — this check takes priority over the TTF catalogue. Secretary dropdown combines TTF keywords and global session types into one unified list. Visibility follows normal posting rules.
- **Tag-based reallocation sorts by tag label alphabetically, not by duration.** The R script sorts by tag string (e.g. `A1` before `A2`). By convention, PCs assign earlier tags to longer-duration session types. Flow is always from alphabetically earlier tag → later tag only. One-for-one in session counts regardless of duration difference. The TTF upload validator warns when tag alphabetical order does not align with duration descending.
- **Multi-posting cell with explicit date ranges applies to ALL sheets**, not FM only. Any sheet in the RDB may contain cells with multiple posting codes and explicit `(from DD-MMM-YYYY to DD-MMM-YYYY)` date ranges.
- **Unmatched multi-posting cells fall back to independent calculation.** If a multi-posting cell has no matching `multi_posting_rules` entry and no matching `posting_groups` entry, each posting is calculated independently. Active months use whole-month counting (no proration). An upload warning is generated.
- **Posting groups aggregate compliance across related posting codes.** When a resident serves at multiple postings sharing the same `posting_groups.group_code`, active_months and target_100 are summed across all group members. Each posting's own TTF monthly_target applies. Seeded from non-empty TTF Column E values at upload time and manageable via admin CRUD UI. If Column E is empty, the posting stands alone and compliance is calculated independently under its own posting_code. Applies globally to all programmes.
- **External residents use separate tables.** External/cross-cluster residents from `NUH` or `SingHealth` live in `external_residents`; their submissions live in `external_attendance_records`. Do not store them in `users`, native `residents`, `programme_scope`, or native `resident_postings`.
- **MCR is globally unique.** Registration/login logic must reject an MCR already present in either `residents` or `external_residents`.
- **External residents are excluded from NHG compliance.** External attendance is stored only for future export/forwarding to their home-cluster PCs. It never enters NHG numerator, denominator, surplus, snapshots, or clawback.
- **Secretary-created event visibility uses `posting_codes.supports_secretary_events`.** Do not hardcode TTSH. Current TTSH pilot postings can be enabled via data; future hospitals such as KTPH can be onboarded by setting the same flag. Ad-hoc submission remains available even when secretary-created event lists are not supported.
- **External attendance export is deferred.** Keep external attendance queryable/auditable, but do not implement CSV/XLSX/email/dashboard export until requirements are confirmed.

## Reference Documents

Read these files in `docs/` before writing code for any domain:

| File | Read before working on |
|------|----------------------|
| `docs/schema.md` | Any model, migration, or database query |
| `docs/api.md` | Any router, endpoint, or Pydantic schema |
| `docs/business-logic.md` | Compliance engine, surplus chain, reallocation, any calculation |
| `docs/parsing.md` | RDB, TTF, FormF1, and Academic Calendar / Public Holidays upload endpoints, Excel parsing |

## TBD — Awaiting Confirmation

1. **Historical data migration strategy** — Three options: archive only / summary migration / full migration. Decision needed before first period close. See `docs/business-logic.md` § TBD-MIGRATION.

## Confirmed Decisions (previously TBD)

| Item | Decision |
|------|----------|
| Admin scope | Programme-scoped via `users.programme_scope TEXT[]` |
| Surplus period boundary | Resets to zero at each reporting period boundary |
| Recurrence editing granularity | All three options: this event only / this and all following / all in series |
| Reallocation scope | Tag-group-only. No cross-tag or cross-posting flow. Tag sort is alphabetical by label (A1→A2→A3), not by duration. One-for-one session count transfers. |
| Details of Training (TBD-1) | Resolved. Keywords stored in `teaching_name_catalogue` (first-class table, seeded from TTF column K at upload). Session type resolved at compliance read time — never stored on attendance_records. r_year is part of the catalogue key. |
| Upload audit logging | Every RDB, TTF, FormF1, and Academic Calendar / Public Holidays upload persists an `upload_logs` row with full JSONB summary. |
| Period close behaviour | Triggers surplus hibernation + `period_snapshots` generation per programme. |
| Legacy cutover | Hard cutover at a period boundary. FormSG/Google Forms closed at that date. No hybrid operation. |
| Dormant posting codes (TBD-2) | RDB posting code is the canonical standard for TTF as well. Last `[]` bracket in TTF posting column = RDB posting code. Dormant codes accepted with display_name = NULL. |
| Combined posting event ownership | For combine-type postings (e.g. IMHGrPsyc & TTSHPsychi), secretaries at both individual sites create events under their own posting codes. Compliance = total attended across both / total sessions created by both secretaries combined. Order of posting codes in combined label indicates which site the resident starts at — no compliance impact. |
| Multi-posting rules source | Rules seeded directly into database from `Multiple postings per month.xlsx` as a seed/update source, not a recurring upload. Managed via admin CRUD UI in three tabs: Main Posting, To Combine Posting, Half Month Posting. |
| FM compliance variant | FM uses the standard compliance engine — same 70%, same capping, same reallocation, same R year path. No separate variant. FM-specific annotations are Department Teaching [5h] posting override to NHGPlyNHGPly and FM main-posting parser semantics. FM Saturday exception is removed from the confirmed weekend exception list. |
| Public holiday event creation | Secretary and resident ad-hoc teaching creation on PH dates is hard-blocked (422). PH impact on compliance denominator is moot — no events created on PH dates. |
| Academic Calendar / AY Dates month bucketing | `POST /admin/upload/public-holidays` parses `Public Holidays` + `AY Dates`, ignores `Fr RMT`, and writes `public_holidays` + `academic_month_boundaries`. Compliance month bucketing resolves by `resident.programme_code` → `programmes.ay_date_category` (`im_subspec` / `non_im_subspec`) → boundary row by `event_date`. JR/SR/SRs wording is detection-only and not persisted. |
| Active/inactive source | FormF1 is the final authoritative source. `form_f1_records.is_active` is the compliance denominator gate. |
| Ad-hoc teaching | Residents can submit ad-hoc teachings via dedicated endpoint. is_adhoc = true on teaching_events. Same compliance treatment as secretary-created events. |
| Duration in TTF | Duration stays embedded in session type name as [Xh]. No separate TTF duration column. Secretary picks start_time only; end_time is server-computed. |
| Non-tracked events | Non-tracked TTF rows (Tracked? = "No") are seeded into teaching_name_catalogue for event visibility. Attendance stored normally but excluded from compliance numerator and denominator. |
| LOA types confirmed list | Full confirmed list: Annual Leaves, Childcare Leave, Compassionate Leave, Family Care Leave, Hospitalisation Leave, Marriage Leave, Maternity Leave, Medical Leave, National Service (NS), No-Pay-Leave, Paternity Leave, Training Leave, Unrecorded Leave, Unpaid Infant Care Leave. 14 types total. Parser warns (does not reject) on unknown LOA types. |
| Refresher Training compliance treatment (TBD-6) | Closed. Refresher Training months handled automatically by FormF1 active/inactive gate. No separate compliance logic needed. `add to Max Cand` / `don't add to Max Cand` stored as display annotation only on `resident_postings`. |
| R year not needed programmes (BL-11) | Resolved. 22 programmes have `r_year_required = false` and use `r_year = 'ALL'` sentinel. 6 programmes have `r_year_required = true`. 2 programmes (SPORTSMED, PALLMED) have `is_subspecialty = true` with R4→SS1, R5→SS2 remapping. 4 programmes have `rdb_alias` for RDB name normalisation. See `docs/business-logic.md` § BL-11. |
| ORTHO weekend mutation | Option B confirmed. Read-time mutation via `mutates_to_session_type_id` + `adjusted_duration_hours` on `weekend_exceptions`. Raw data preserved. |
| Weekend submission warning | Option B confirmed. Submission response includes `compliance_warning` field when weekend session has no matching exception rule. Session is stored; resident is informed. |
| Clawback tab | 5th tab in admin/PC dashboard alongside Monthly View, Posting View, Attendance Breakdown, Submitted Attendances. Visible to admin/PC role only. Generated at period close. |
| Secretary provisioning | TTSH-only at launch — 1 account per TTSH posting code (e.g. TTSHAnaes, TTSHGerMed). Architecture supports other institutions when they onboard — no schema change needed, just provision new accounts scoped to their posting codes. |
| PC provisioning | Flexible — account count TBD. `users.programme_scope TEXT[]` supports multiple programmes per account. |
| Weekend exceptions confirmed list | URO (2 rows: session name OR session type), DERM (all Saturday sessions, no time condition), ORTHO (Saturday 08:30–10:30, read-time mutation to 1h). SIG, FM, ANAES, and all emergency posting exceptions removed per PC confirmation. |
| Tag-based reallocation sort | Sort by tag label alphabetically (A1→A2→A3). By convention A1 = longest duration, A2 = shorter, A3 = shortest. TTF upload validator warns if tag order doesn't align with duration descending. |
| Multi-posting cell applies to all sheets | Not FM-specific. Any RDB sheet may contain multi-posting cells with explicit date ranges. |
| FM main-posting semantics | FM `main_posting` rows use `RDB Posting #1` as the recognised trigger list: exact-one match collapses to `Main posting`, zero-match collapses to configured `Exclusion (Only for FM)`, two-or-more matches warn and persist independently unless an explicit rule exists. Singular `NHGPlyNHGPly` is valid standalone. |
| Posting groups | `posting_groups` table groups related posting codes for compliance aggregation. Seeded from TTF column E at upload; admin CRUD for manual additions. Active months summed across group, whole-month counting, no proration. Applies globally to all programmes. |
| Global session types | `global_session_types` table holds compliance-exempt session types (e.g. Department Meeting [1h]). Admin-managed via CRUD UI. Secretary dropdown shows unified list of TTF keywords + global types. Compliance engine excludes global type matches before TTF catalogue lookup. Visibility follows normal posting rules. |

---

## Security Rules

**All security-relevant checks must be enforced server-side. Frontend checks are UX convenience only — never security boundaries.**

### Authentication & Authorization

- Identity is derived exclusively from the verified JWT on the server. Never trust client-provided user IDs, roles, or programme codes.
- All protected endpoints validate the JWT and check role + scope before any DB operation.
- Admin endpoints check `role = 'admin'` AND `programme_code IN programme_scope`.
- Secretary endpoints check `role = 'secretary'` AND the verified identity posting code; in local stub/demo this comes from `X-User-Site`.
- Resident endpoints check `role = 'resident'` AND all DB queries are scoped to `resident_id` from JWT `sub`.
- Residents authenticate with MCR only (Phase 1). This is an intentional design choice for this system — no upgrade path needed.

### Row-Level Security (RLS) — Supabase

When Supabase Auth is wired in (Phase 9), enable RLS on all sensitive tables. Policy patterns:

```sql
-- attendance_records: residents can only read/write their own records
CREATE POLICY "resident_own_attendance" ON attendance_records
  FOR ALL USING (resident_id = auth.uid());

-- resident_postings: residents can only read their own postings
CREATE POLICY "resident_own_postings" ON resident_postings
  FOR SELECT USING (resident_id = auth.uid());

-- teaching_targets: admin read scoped to programme_scope
-- (implement via service role in backend, not direct client access)

-- form_f1_records: admin only, no resident access
-- teaching_events: residents read only (no write except via attendance endpoint)
```

Backend API operations that span multiple residents (admin reporting, clawback generation) must use the Supabase **service role key** — never the anon key. The service role key is **server-only** and must never be exposed to the frontend or included in client-side environment variables.

### SQL Injection Protection

- All DB queries must use SQLAlchemy ORM or parameterized raw SQL with `:param` binding. Never interpolate user input into SQL strings.
- Pydantic schemas validate all request bodies at the API boundary before any DB access.

```python
# NEVER
session.execute(f"SELECT * FROM residents WHERE mcr = '{mcr}'")

# ALWAYS
session.execute(text("SELECT * FROM residents WHERE mcr = :mcr"), {"mcr": mcr})
```

### Mass Assignment Protection

- Never pass `**request.dict()` or raw request bodies directly to ORM create/update methods.
- Explicitly allowlist permitted fields in every Pydantic schema. Fields like `role`, `programme_scope`, `employer_tag`, `is_active` must never be settable by end users.

### API Security

- All request bodies, query params, route params, and uploaded files are validated via Pydantic before any processing.
- Error responses must never leak stack traces, SQL errors, internal paths, or sensitive object structures. Return safe generic messages for unexpected errors.
- Rate limiting required on: `POST /auth/login`, all `POST /admin/upload/*` endpoints, `POST /resident/adhoc-teaching`.
- CORS must be configured with an explicit allowlist of trusted origins. Never use wildcard `*` in production.

### Security Headers

Configure on all responses via FastAPI middleware:

```python
# Required headers
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'
```

Use `slowapi` for rate limiting and configure security headers via middleware. Vercel handles HTTPS enforcement at the CDN layer.

### Session Management

- Access tokens: short-lived (15–60 minutes).
- Refresh tokens: longer-lived with rotation on each use.
- Logout must invalidate the token server-side — do not rely solely on expiry.
- Tokens stored in `HttpOnly`, `Secure`, `SameSite=Strict` cookies where possible. Avoid `localStorage` for tokens.

### File Upload Security

- Validate file type, MIME type, and file size server-side on all `POST /admin/upload/*` endpoints. Reject files that fail validation before any parsing.
- Accepted file types: `.xlsx` only (`.csv` additionally for public holidays).
- Maximum file size: 10MB per upload.
- Never use client-provided filenames. Generate server-side filenames for any stored files.
- Upload endpoints are admin-only. No resident or secretary file upload paths exist.


### Database Performance, Indexing, Caching, and Rate Limits

- Implement all indexes documented in `docs/schema.md` in SQLAlchemy models and Alembic migrations.
- Add indexes for all high-frequency foreign-key joins and composite query paths used by resident dashboards, uploads, event visibility, compliance, and reports.
- Do not invent indexes blindly for every column. Indexes must support documented query paths and should be revisited with `EXPLAIN ANALYZE` after Phase 6 reports exist.
- Use a cache abstraction for reference/config reads and report/compliance reads where safe. In-memory TTL cache is acceptable for local/early phases; production or multi-worker deployment must use Redis or a platform cache.
- Cache keys must include role and scope inputs. Never share cached admin/resident/secretary data across scopes.
- Invalidate cache after uploads, admin config CRUD, teaching event mutations, attendance mutations, and reporting period close/reopen.
- Implement rate limiting middleware before public/UAT use. Auth, upload, mutation, report/export, and resident attendance endpoints must have separate configurable limits.

### Secrets & Environment Variables

```
# SERVER-ONLY — never expose to frontend
DATABASE_URL=postgresql+asyncpg://...
SUPABASE_SERVICE_ROLE_KEY=...
JWT_SECRET=...

# Safe for frontend (Vite prefix)
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_API_BASE_URL=https://api.your-domain.com
```

Never hardcode credentials. `.env` files must be in `.gitignore`. Provide only placeholder values in `.env.example`.

### Frontend Security

- Never store sensitive data in `localStorage`. Use `HttpOnly` cookies for auth tokens.
- Never use `dangerouslySetInnerHTML` without explicit DOMPurify sanitisation.
- All frontend role/scope checks are UX only. The backend enforces all access control.

### Pending Security Decision Format

When a security decision cannot be determined from existing documentation, insert this marker:

```
<!-- Pending Security Decision: [describe what needs to be decided]
     Example: It is unclear whether non-owner users in the same programme
     can view this resource. RLS policy and API authorization logic must be
     confirmed before implementation. -->
```

Do not invent authorization logic. Block implementation until the decision is documented.
