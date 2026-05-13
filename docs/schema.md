# Database Schema

All tables use UUID primary keys (`id UUID DEFAULT gen_random_uuid()`), `created_at TIMESTAMPTZ DEFAULT now()`, and `updated_at TIMESTAMPTZ DEFAULT now()` unless noted otherwise.

## Entity Relationship Summary

```
programmes ─1:N─ teaching_targets
programmes ─1:N─ residents (via programme_code)
programmes ─1:N─ multi_posting_rules
programmes ─1:N─ posting_groups

posting_codes ─1:N─ resident_postings
posting_codes ─1:N─ teaching_targets
posting_codes ─1:N─ teaching_events
posting_codes ─1:N─ multi_posting_rules
posting_codes ─1:N─ posting_groups

residents ─1:N─ resident_postings
residents ─1:N─ attendance_records
residents ─1:N─ surplus_ledger

teaching_events ─1:N─ attendance_records
teaching_events ─N:1─ event_series (nullable)

session_types ─1:N─ teaching_targets
session_types ─1:N─ teaching_events (display only)
session_types ─1:N─ teaching_name_catalogue

reporting_periods ─1:N─ teaching_targets
reporting_periods ─1:N─ resident_postings
reporting_periods ─1:N─ period_snapshots
reporting_periods ─1:N─ teaching_name_catalogue
reporting_periods ─1:N─ form_f1_records

posting_codes ─1:N─ teaching_name_catalogue
programmes ─1:N─ teaching_name_catalogue

users ─1:N─ upload_logs
```

---

## Table: `programmes`

Master list of residency programmes.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| code | VARCHAR(20) | UNIQUE, NOT NULL | e.g. `DR`, `GERI`, `ANAES`, `FM`, `IM` |
| name | VARCHAR(100) | NOT NULL | e.g. `Diagnostic Radiology`, `Geriatric Medicine` |
| classification | VARCHAR(20) | | `junior` or `senior` or `both` |
| r_year_required | BOOLEAN | DEFAULT true | If false, programme uses `r_year = 'ALL'` sentinel — TTF targets apply to all r_years equally |
| is_subspecialty | BOOLEAN | DEFAULT false | If true, RDB parser remaps R4→SS1, R5→SS2, R6→SS3 for this programme |
| rdb_alias | VARCHAR(100) | nullable | Alternative programme name that appears in RDB cells. Used for normalisation at RDB parse time. |

**Note:** FM uses the standard compliance engine. There is no `compliance_variant` column — FM compliance is handled through FM-specific rule annotations within the standard path. See `docs/business-logic.md` § BL-FM.

**Seed data (from Programme_ABBREV.xlsx — 28 programmes):**

| code | name | r_year_required | is_subspecialty | rdb_alias |
|------|------|----------------|----------------|-----------|
| AIM | Advanced Internal Medicine | false | false | NULL |
| ANAES | Anaesthesiology | true | false | NULL |
| CARDIO | Cardiology | false | false | NULL |
| DERM | Dermatology | true | false | NULL |
| DR | Diagnostic Radiology | true | false | NULL |
| EM | Emergency Medicine | false | false | NULL |
| ENDO | Endocrinology | false | false | NULL |
| ENT | Otorhinolaryngology | false | false | NULL |
| EYE | Ophthalmology | false | false | NULL |
| FM | Family Medicine | true | false | NULL |
| GASTRO | Gastroenterology | false | false | NULL |
| GERI | Geriatric Medicine | false | false | NULL |
| GS | General Surgery | false | false | NULL |
| ID | Infectious Diseases | false | false | Infectious Disease |
| IM | Internal Medicine | false | false | NULL |
| MEDONCO | Medical Oncology | false | false | NULL |
| ORTHO | Orthopaedic Surgery | false | false | NULL |
| PATH | Pathology | false | false | NULL |
| PSY | Psychiatry | true | false | NULL |
| REHAB | Rehabilitation Medicine | false | false | NULL |
| RENAL | Renal Medicine | false | false | Renal Medicine Extended |
| RESPI | Respiratory Medicine | true | false | NULL |
| RHEUM | Rheumatology | false | false | NULL |
| SPORTSMED | Sports Medicine | false | true | NULL |
| SIG | Surgery-In-General | false | false | Surgery-in-General |
| URO | Urology | false | false | NULL |
| MICROB | Pathology (Microbiology) | false | false | Microbiology |
| PALLMED | Palliative Medicine | false | true | NULL |

**r_year_required = false (22 programmes):** AIM, CARDIO, EM, ENDO, ENT, EYE, GASTRO, GERI, GS, ID, IM, MEDONCO, ORTHO, PATH, REHAB, RENAL, RHEUM, SPORTSMED, SIG, URO, MICROB, PALLMED

**r_year_required = true (6 programmes):** ANAES, DERM, DR, FM, PSY, RESPI

**is_subspecialty = true (2 programmes):** SPORTSMED, PALLMED — R4→SS1, R5→SS2, R6→SS3 remapping applied by RDB parser

---

## Table: `posting_codes`

Canonical registry of all posting sites. Seeded from both RDB (active sites) and TTF (full catalogue including dormant sites).

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| code | VARCHAR(50) | UNIQUE, NOT NULL | e.g. `TTSHAnaes`, `KTPHGerMed`, `AICAIC` |
| display_name | VARCHAR(100) | | Human-readable name, e.g. `TTSH Anaesthesiology` |
| institution | VARCHAR(50) | | e.g. `TTSH`, `KTPH`, `SGH`, `NNI` |
| department | VARCHAR(50) | | e.g. `Anaes`, `GerMed`, `DiagRd` |
| billing_dept | VARCHAR(50) | | For clawback (Phase 10) |
| is_emergency | BOOLEAN | DEFAULT false | Emergency postings accept weekend AND public holiday teachings |

**Important:** Posting codes are NOT derivable by regex from institution+department. Real codes like `MOHHGTG1`, `AICAIC`, `RenCiCommHosp`, `NHGPlyNHGPly` break any uniform pattern. This table is the source of truth — no string parsing.

---

## Table: `reporting_periods`

Six-month reporting windows.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| label | VARCHAR(30) | UNIQUE, NOT NULL | e.g. `Jan - June 2026`, `Jul - Dec 2025` |
| start_date | DATE | NOT NULL | |
| end_date | DATE | NOT NULL | |
| status | VARCHAR(10) | DEFAULT 'open' | `open`, `closed` |

---

## Table: `residents`

One row per resident. Created from RDB upload. Also serves as the **identity source for resident authentication** — MCR is the login credential and `programme_code` is embedded in the JWT at login time to scope all compliance lookups to the resident's native residency programme.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| employee_code | VARCHAR(20) | UNIQUE | From RDB column A |
| name | VARCHAR(100) | NOT NULL | From RDB column B |
| mcr | VARCHAR(20) | UNIQUE, NOT NULL | Primary identifier for resident login |
| classification | VARCHAR(20) | | `Junior Resident` or `Senior Resident` |
| programme_code | VARCHAR(20) | FK → programmes.code | Derived from RDB "Specialization" |
| r_year | VARCHAR(10) | | Current year: `R1`..`R7`. Display only — do NOT use for compliance target lookup. |
| reg_type | VARCHAR(20) | | `Full`, `Conditional` |
| base_institution | VARCHAR(50) | | RDB "Base Clinic / Institution & Department" |
| email | VARCHAR(100) | | |
| phone | VARCHAR(20) | | |
| status | VARCHAR(20) | DEFAULT 'active' | `active`, `inactive`, `loa`, `employed` |
| employer_tag | VARCHAR(20) | | NULL for normal residents, "SAF", "SCDF", "KTPH" etc. |

---

## Table: `resident_postings`

One row per (resident, posting, month-phase). The 12-month rotation schedule from the RDB.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | NULL for pure LOA months |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| start_date | DATE | NOT NULL | Phase start date from RDB column header |
| end_date | DATE | NOT NULL | Phase end date from RDB column header |
| day_part | VARCHAR(2) | nullable, CHECK NULL/`AM`/`PM` | AM/PM fragment marker for same-day multi-posting rows. NULL means full-day/no half-day marker. |
| month_label | VARCHAR(10) | | e.g. `Jul-25`, `Aug-25` |
| r_year | VARCHAR(10) | NOT NULL | Residency year at this phase. For programmes with `r_year_required = false`, this is set to `'ALL'`. For subspecialty programmes (SPORTSMED, PALLMED), R4→SS1/R5→SS2 remapping is applied. Copied from RDB column F at parse time. Used for teaching_target lookup — do NOT use residents.r_year for compliance. |
| status | VARCHAR(20) | DEFAULT 'active' | `active`, `loa`, `loa_working`, `employed` |
| loa_type | VARCHAR(50) | | e.g. `Maternity Leave`, `Annual Leaves`. Validated against loa_types table. |
| loa_start_date | DATE | | Parsed from LOA annotation |
| loa_end_date | DATE | | Parsed from LOA annotation |
| refresher_training_type | VARCHAR(50) | | `add to Max Cand` or `don't add to Max Cand`. Display only — no compliance impact. |
| refresher_training_start | DATE | | Parsed from Refresher Training annotation |
| refresher_training_end | DATE | | Parsed from Refresher Training annotation |
| active_months_weight | DECIMAL(3,1) | DEFAULT 1.0 | For half-month posting split (TTSHGas/NUHGas). Set to 0.5 when multi_posting_rules half_month rule applies. |
| working_days_in_month | INTEGER | | Computed at RDB parse time: calendar days in phase minus LOA days. Stored for future use — not currently used for compliance. |

**Unique constraint:** `UNIQUE NULLS NOT DISTINCT(resident_id, reporting_period_id, start_date, day_part)`

**RDB re-upload behaviour:** On re-upload, existing `resident_postings` rows for the period are deleted and re-inserted (delete-first within scope, not blind insert). This prevents duplicate-key errors and ensures corrections take effect cleanly. The scope for deletion is `(reporting_period_id)` across all residents found in the uploaded file. Residents not present in the new upload are left untouched.

**Cell parsing rules:**
- Simple posting: `TTSHAnaes` → status = `active`, posting_code = `TTSHAnaes`
- Empty cell: → skip, no row created
- Pure LOA: `LOA (Maternity Leave from DD-MMM-YYYY to DD-MMM-YYYY)` → status = `loa`, posting_code = NULL, loa fields populated
- Hybrid LOA (Continue working): `TTSHAnaes (Continue working during LOA from ...)` → status = `loa_working`, posting_code = `TTSHAnaes`, loa fields populated
- Multiline LOA: `TTSHGenMed\nLOA (Maternity Leave from ...)` → same as loa_working
- Refresher Training: `TTSHAnaes (Refresher Training (add to Max Cand) from ...)` → status = `active`, posting_code = `TTSHAnaes`, refresher fields populated
- Employed: `SAF-Employed` / `KTPH-Employed` etc. → status = `employed`, posting_code = NULL, employer_tag set on residents table, no resident_postings row created
- Multi-posting cell (FM): Multiple posting codes per cell with explicit date ranges and AM/PM half-day granularity — see `docs/parsing.md` § Multi-Posting Cell Variant

**Note on Employed cells:** XXX-Employed cells do not produce a resident_postings row. The employer_tag is set directly on the residents table on first encounter.

---

## Table: `loa_types`

Reference table for valid LOA type strings. Used by RDB parser for LOA type validation. Managed via admin CRUD UI.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| code | VARCHAR(50) | UNIQUE, NOT NULL | e.g. `Maternity Leave`, `Annual Leaves` |
| description | VARCHAR(100) | | Optional human-readable description |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Confirmed seed list (14 types):**
- Annual Leaves
- Childcare Leave
- Compassionate Leave
- Family Care Leave
- Hospitalisation Leave
- Marriage Leave
- Maternity Leave
- Medical Leave
- National Service (NS)
- No-Pay-Leave
- Paternity Leave
- Training Leave
- Unrecorded Leave
- Unpaid Infant Care Leave

**Note:** "Continue working during LOA", "Pending for SR Promotion", "Refresher Training (add to Max Cand)", and "Refresher Training (don't add to Max Cand)" are **cell annotation types** handled directly in the RDB parser — they are NOT `loa_types` seed rows.

**Parser behaviour:** Warns (does not reject) on unknown LOA types encountered in RDB cells. Unknown types are included in the `unknown_loa_types` array in the upload response.

---

## Table: `session_types`

Catalogue of all session types. Seeded from TTF upload.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| name | VARCHAR(100) | UNIQUE, NOT NULL | e.g. `Department/Programme Teaching [1h]` |
| duration_hours | DECIMAL(4,2) | NOT NULL | Extracted from name: `[1h]` → 1.0, `[0.75h]` → 0.75 |
| duration_label | VARCHAR(10) | | `[1h]`, `[2h]`, `[0.75h]`, `[3h]` etc. |

**Note:** Duration is embedded in the session type name as `[Xh]`. There is no separate duration column in the TTF — duration is extracted from the name via regex at upload time. Duration is stored for reallocation flow direction and as a tiebreaker only. Compliance counts sessions, never multiplies by duration.

---

## Table: `teaching_targets`

One row per (reporting_period, programme, residency_year, posting_code, session_type). The core compliance reference.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | |
| r_year | VARCHAR(10) | NOT NULL | `R1`..`R7`, `SS1`..`SS3`, or `'ALL'` for programmes with `r_year_required = false` |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| monthly_target | INTEGER | NOT NULL | Sessions per active month at 100% |
| is_tracked | BOOLEAN | DEFAULT true | If false, attendance is stored but excluded from compliance numerator and denominator. Row still seeded into teaching_name_catalogue for event visibility. |
| is_reallocatable | BOOLEAN | DEFAULT false | Whether surplus can be reallocated via tag |
| tag | VARCHAR(10) | | Reallocation group label. If set, must match at least one other row at the same posting. |
| details_of_training | TEXT | | Raw column K text. Comma-separated keywords. Parsed into teaching_name_catalogue at upload time. |

**Unique constraint:** `UNIQUE(reporting_period_id, programme_code, r_year, posting_code, session_type_id)`

---

## Table: `teaching_name_catalogue`

First-class keyword→session_type mapping table. Seeded from TTF column K at upload time. The single source of truth for event visibility and session type resolution.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| keyword | VARCHAR(200) | NOT NULL | Individual keyword e.g. `Journal Club` |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | |
| r_year | VARCHAR(10) | NOT NULL | `R1`..`R7`, `SS1`..`SS3`, or `'ALL'` |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| duration_hours | DECIMAL(4,2) | NOT NULL | Copied from session_types for tiebreaker |
| is_tracked | BOOLEAN | DEFAULT true | Copied from teaching_targets.is_tracked |

**Unique constraint:** `UNIQUE(keyword, posting_code, programme_code, r_year, reporting_period_id)`

**Usage:** Seeded at TTF upload time. Deleted and re-seeded on each TTF upload within scope. Also deleted and re-seeded for the specific row when `PUT /admin/teaching-targets/{id}` updates `details_of_training`.

---

## Table: `teaching_events`

Teaching sessions created by secretaries or ad-hoc submissions by residents.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | The posting that owns this event |
| teaching_name | VARCHAR(200) | NOT NULL | Free text name as entered by secretary or resident |
| event_date | DATE | NOT NULL | |
| start_time | TIME | NOT NULL | |
| end_time | TIME | | Server-computed from start_time + session_type.duration_hours at creation |
| duration_hours | DECIMAL(4,2) | | Copied from resolved session_type at creation time. Used as tiebreaker in catalogue lookup. |
| session_type_id | UUID | FK → session_types.id, nullable | **Display/prototype only.** Resolved at event creation from teaching_name_catalogue for the secretary's native programme. NEVER used for compliance — compliance always re-resolves per resident at read time. |
| series_id | UUID | FK → event_series.id, nullable | Set if this event is part of a recurring series |
| cme_points_awarded | BOOLEAN | DEFAULT false | |
| smc_event_code | VARCHAR(50) | | |
| is_adhoc | BOOLEAN | DEFAULT false | True for resident-submitted ad-hoc events, false for secretary-created events |
| created_by_role | VARCHAR(20) | | `secretary` or `resident` |

---

## Table: `event_series`

Metadata for recurring teaching event series.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| posting_code | VARCHAR(50) | FK → posting_codes.code | |
| recurrence_pattern | VARCHAR(20) | | `daily`, `weekly`, `monthly` |
| recurrence_interval | INTEGER | DEFAULT 1 | Every N days/weeks/months |
| days_of_week | TEXT[] | | e.g. `{mon, wed}` for weekly |
| end_type | VARCHAR(10) | | `by_date`, `by_count` |
| end_date | DATE | | |
| end_after_count | INTEGER | | |

---

## Table: `attendance_records`

One row per (resident, teaching_event) submission.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| teaching_event_id | UUID | FK → teaching_events.id, NOT NULL | |
| submitted_at | TIMESTAMPTZ | DEFAULT now() | |
| status | VARCHAR(20) | DEFAULT 'submitted' | `submitted`, `flagged`, `removed` |
| posting_code | VARCHAR(50) | | Audit copy of event posting at submission time. **Never used for compliance attribution** — compliance always uses teaching_events.posting_code. |

**Unique constraint:** `UNIQUE(resident_id, teaching_event_id)` — DB-level duplicate prevention.

**Session type is NOT stored here.** It is resolved at compliance read time from `teaching_name_catalogue` using the event's `teaching_name`, `posting_code`, and the resident's `programme_code` + `r_year`.

---

## Table: `surplus_ledger`

Pre-reallocation surplus values per (resident, posting, session_type). Written by the compliance engine at calculation time.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| surplus | INTEGER | DEFAULT 0 | Pre-reallocation surplus count |
| is_hibernating | BOOLEAN | DEFAULT false | True when resident is not actively posted here |

**Critical:** Surplus values stored here are PRE-reallocation. Tag-based reallocation is always a read-time computation — never written back to this table.

---

## Table: `form_f1_records`

Per-resident per-calendar-month active/inactive status parsed from the FormF1 file. This is the primary denominator gate for compliance calculations.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| mcr | VARCHAR(20) | NOT NULL | Join key to residents.mcr |
| month_label | VARCHAR(10) | NOT NULL | e.g. `Jul-25`, `Aug-25` — calendar month |
| status_raw | VARCHAR(50) | NOT NULL | Raw value from FormF1: `Active`, `Inactive`, `Extension` |
| is_active | BOOLEAN | NOT NULL | Derived: `Active` and `Extension` → true. `Inactive` → false. |
| upload_id | UUID | FK → upload_logs.id | Which upload produced this record |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Unique constraint:** `UNIQUE(reporting_period_id, mcr, month_label)`

**Status normalisation:**
- `Active` → is_active = true
- `Extension` → is_active = true (always track, funding not allocated, clawback not exercised — `clawback_suppressed_reason = 'Extension'`)
- `Inactive` → is_active = false (excluded from both numerator and denominator)

**Re-upload behaviour:** Full replace per `reporting_period_id` scope. Re-upload is allowed at any time (to handle unforeseen LOAs like maternity). Delete-and-reinsert within scope.

**Note:** FormF1 is the confirmed default active/inactive source. The formal architectural decision (FormF1 vs RDB) is still open. See `docs/business-logic.md` § TBD-7.

---

## Table: `public_holidays`

For PH detection and secretary/resident event creation blocking.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| holiday_date | DATE | UNIQUE, NOT NULL | |
| name | VARCHAR(100) | | e.g. `Deepavali`, `Chinese New Year` |
| day_of_week | VARCHAR(10) | | e.g. `Monday` — stored for display, derivable from date |
| year | INTEGER | | |

---

## Table: `multi_posting_rules`

Rules governing how multiple posting codes in a single RDB cell are interpreted. Seeded directly into the database and managed via admin CRUD UI. `Multiple postings per month.xlsx` is a seed/update source for this table, not a recurring upload slot.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | |
| posting_code_1 | VARCHAR(50) | FK → posting_codes.code, NOT NULL | First posting code in pair. For FM `main_posting` rows where `posting_code_2 IS NULL`, this is one entry in the recognised `RDB Posting #1` trigger list. |
| posting_code_2 | VARCHAR(50) | FK → posting_codes.code, nullable | Second posting code. NULL for FM trigger-list `main_posting` rows and other single-trigger rules. |
| rule_type | VARCHAR(20) | NOT NULL | `main_posting`, `combine`, `half_month` |
| combined_label | VARCHAR(100) | | For `combine` type: the canonical combined posting code (e.g. `IMHGrPsyc & TTSHPsychi`) |
| main_posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | For `main_posting` type: the posting to collapse to when the rule is selected |
| exclusion_code | VARCHAR(50) | FK → posting_codes.code, nullable | For FM `main_posting` trigger-list rows: fallback posting when zero recognised trigger-list codes appear in the multi-posting cell. Usually `NHGPlyNHGPly`, but read from configuration and not hardcoded globally. |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Unique constraint:** `UNIQUE(programme_code, posting_code_1, posting_code_2, rule_type)`

**Rule type behaviour:**
- `combine`: Two RDB lines in same cell match this rule → create one `resident_postings` row with `combined_label` as posting_code. Combined label must exist as a `posting_codes` row. Compliance follows the combined posting's TTF row.
- `half_month`: Two posting codes in same cell match this rule → create two `resident_postings` rows each with `active_months_weight = 0.5`. Both active_months and Target(mth) halved per posting. Numerator sessions count fully.
- explicit two-code `main_posting`: Two posting codes in the same cell match this rule → collapse to `main_posting_code`.
- FM trigger-list `main_posting`: Rows with `posting_code_2 IS NULL` define the recognised `RDB Posting #1` list. Exact one recognised code in the cell collapses to that row's `main_posting_code`; zero recognised codes collapse to the configured `exclusion_code`; two or more recognised codes remain independent and emit `unmatched_multi_posting` unless an explicit rule exists.

**Unmatched behaviour:** If no `multi_posting_rules` row applies, the parser preserves one `resident_postings` row per posting fragment and emits `unmatched_multi_posting`. This is intentional for PC review. It does not delete data or suppress the upload. A singular `NHGPlyNHGPly` cell is a valid standalone FM posting and is not an unmatched multi-posting case.

---

## Table: `posting_groups`

Groups multiple RDB posting codes under a single compliance aggregate. Seeded primarily from non-empty TTF Column E values (`dashboard_posting`). When a resident serves at two postings in the same group across a period (e.g. `TTSHRespi` and `TTSHRespi(MICU)`), their active months are pooled and target100 is calculated across the combined months. Each posting still has its own TTF rows and monthly targets — the group only affects how active_months and posting-level compliance aggregation are summed.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| group_code | VARCHAR(100) | NOT NULL | The canonical group name, e.g. `TTSHRespi`. Used as the compliance aggregation key. |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | A member posting code of this group |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | Groups are programme-specific |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Unique constraint:** `UNIQUE(posting_code, programme_code)`

**How compliance uses posting_groups:**
1. At compliance calculation time, for each `(resident, posting_code)`, look up `posting_groups` for that `(posting_code, programme_code)` pair
2. If a group is found, fetch ALL posting codes sharing the same `group_code` and `programme_code`
3. Sum `active_months` across ALL group members for that resident — using `form_f1_records.is_active` as the gate per calendar month (whole-month counting, no proration)
4. Each posting's own `monthly_target` applies per phase: `target_100 = sum(monthly_target_at_posting × months_at_posting)` across all group members
5. `target_70 = ceil(target_100 × 0.70)`
6. If no group is found for a posting code → calculate independently (posting stands alone)

**Important clarification:** Column E / `group_code` does not replace the posting's own `monthly_target`. Each posting_code still contributes its own `monthly_target × months_at_posting`; grouping only changes the final posting-level aggregation identity.

**Seeding sources:**
- **TTF upload (primary):** When TTF column E ("For Dashboard (RDB Posting/Subspeciality)") is non-empty for a posting code row, the parser automatically upserts a `posting_groups` row: `group_code = column_E_value`, `posting_code = column_D_value`, `programme_code = from TTF`
- **Admin CRUD (secondary):** Manual addition for groupings not captured by TTF column E

**Admin CRUD UI:** All `posting_groups` rows are manageable via admin CRUD UI. Applies globally to all programmes.

**Example:** For RESPI programme, `TTSHRespi` and `TTSHRespi(MICU)` share `group_code = 'TTSHRespi'`. A resident posting Jan–Mar at `TTSHRespi` and Apr–May at `TTSHRespi(MICU)` has 5 combined active months. Target100 = (6 × 3) + (6 × 2) = 30 for Dept Teaching [1h], and (5 × 3) + (5 × 2) = 25 for Respi Programme Teaching [2h]. Total target100 = 55, target70 = ceil(55 × 0.7) = 39.

**Unmatched posting (no group, no multi_posting_rule):** If a multi-posting cell has no matching rule and no matching group, each posting is calculated independently. Active months are counted independently per posting using whole-month counting (no proration). A calendar month is credited to a posting regardless of how many days within that month were spent there. An upload warning is generated.

---

## Table: `weekend_exceptions`

Programme-specific rules for accepting weekend teachings, and read-time mutation rules for session type remapping.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| programme_code | VARCHAR(20) | FK → programmes.code | NULL = applies to posting code only |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | NULL = applies to programme only |
| day_type | VARCHAR(3) | NOT NULL | `sat`, `sun`, `both` |
| start_time_min | TIME | | NULL = any time accepted |
| end_time_max | TIME | | NULL = any time accepted |
| session_type_id | UUID | FK → session_types.id, nullable | NULL = any session type accepted |
| session_name_pattern | VARCHAR(100) | | Optional: match specific session names (substring match) |
| mutates_to_session_type_id | UUID | FK → session_types.id, nullable | If set, compliance engine resolves this session_type instead of the original at read time |
| adjusted_duration_hours | DECIMAL(4,2) | nullable | If set, compliance engine uses this duration instead of the original at read time |

**Logic:** A weekend session is accepted for compliance if ANY row in this table matches `(programme_code OR posting_code) AND day_type AND time_window AND session_type AND session_name`. The OR logic for URO (which has two acceptance conditions) is represented as two separate rows.

**Mutation logic (ORTHO):** When `mutates_to_session_type_id` is set on a matched row, the compliance engine resolves the attendance against the mutated session type and duration — not the original. Raw attendance data is never modified. This is applied at compliance read time only.

**Confirmed seeded rows:**

| programme_code | posting_code | day_type | start_time_min | end_time_max | session_type_id | session_name_pattern | mutates_to | adjusted_duration |
|---|---|---|---|---|---|---|---|---|
| URO | NULL | sat | NULL | NULL | NULL | Urology National Teaching (Sat) | NULL | NULL |
| URO | NULL | sat | NULL | NULL | National Teaching [2h] | NULL | NULL | NULL |
| DERM | NULL | sat | NULL | NULL | NULL | NULL | NULL | NULL |
| ORTHO | NULL | sat | 08:30 | 10:30 | NULL | NULL | National Didactics & Department Teaching [1h] | 1.0 |

**Notes:**
- URO requires two rows — acceptance condition is an OR: session name `"Urology National Teaching (Sat)"` OR session type `"National Teaching [2h]"`. Two separate rows represent this OR logic.
- DERM accepts all Saturday sessions unconditionally — no time window, no session type filter.
- ORTHO time window 08:30–10:30. The original 3h session type is mutated to `National Didactics & Department Teaching [1h]` at compliance read time via `mutates_to_session_type_id` and `adjusted_duration_hours = 1.0`.
- SIG, FM, ANAES, and all emergency posting codes have been removed from this list per confirmed PC update. The previous list from the R script was outdated.

**Admin CRUD UI:** All `weekend_exceptions` rows are manageable via admin CRUD UI. New entries can be added when additional programmes confirm weekend session policies.

---

## Table: `users`

For admin and secretary authentication **only**. Residents are **not** stored here — they authenticate directly against the `residents` table using their MCR number.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| email | VARCHAR(100) | UNIQUE, NOT NULL | |
| password_hash | VARCHAR(255) | NOT NULL | Stubbed in Phase 1 |
| role | VARCHAR(20) | NOT NULL | `admin`, `secretary` — never `resident` |
| name | VARCHAR(100) | NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | Secretary's assigned site. NULL for admin. |
| programme_scope | TEXT[] | | Array of programme codes e.g. `{DR,GRM}`. Scopes the admin to specific programmes. NULL = no access (not all-access). |
| is_active | BOOLEAN | DEFAULT true | |

**Secretary provisioning:** At launch, one account per TTSH posting code (e.g. TTSHAnaes, TTSHGerMed, TTSHCardio). Architecture is flexible — when other institutions onboard, provision new secretary accounts scoped to their posting codes (e.g. KTPHAnaes, SGHGerMed) with no schema change required.

**Admin/PC provisioning:** Account count is flexible. `programme_scope TEXT[]` supports multiple programmes per account, allowing PCs who manage several programmes to use a single login.

---

## Table: `upload_logs`

Persistent audit trail of every RDB, TTF, and FormF1 upload.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| upload_type | VARCHAR(10) | NOT NULL | `rdb`, `ttf`, `form_f1`, `public_holidays` |
| uploaded_by | UUID | FK → users.id, NOT NULL | Admin who triggered the upload |
| uploaded_at | TIMESTAMPTZ | DEFAULT now() | |
| reporting_period_id | UUID | FK → reporting_periods.id, nullable | NULL only if period lookup fails |
| programme_code | VARCHAR(20) | | TTF uploads only — NULL for RDB and FormF1 |
| status | VARCHAR(10) | NOT NULL | `success`, `partial`, `failed` |
| summary | JSONB | NOT NULL | Full structured log of what was processed |

**`summary` JSONB shape for RDB uploads:**
```json
{
  "residents_created": 42,
  "residents_updated": 5,
  "postings_created": 504,
  "posting_codes_added": ["TTSHAnaes", "KTPHGerMed"],
  "loa_records": 12,
  "unknown_loa_types": ["Exam Leave"],
  "employed_residents_flagged": 3,
  "multi_posting_rules_applied": 8,
  "rows_skipped": 3,
  "skip_reasons": [],
  "warnings": []
}
```

**`summary` JSONB shape for TTF uploads:**
```json
{
  "targets_created": 29,
  "session_types_upserted": 5,
  "posting_codes_added": ["AICAIC", "DPPallia"],
  "catalogue_rows_seeded": 84,
  "rows_exploded": 3,
  "rows_skipped": 0,
  "skip_reasons": [],
  "errors": []
}
```

**`summary` JSONB shape for FormF1 uploads:**
```json
{
  "records_created": 312,
  "records_updated": 0,
  "mcr_not_found_warnings": ["M99999Z"],
  "month_labels_parsed": ["Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25", "Dec-25"],
  "active_count": 280,
  "inactive_count": 32,
  "errors": []
}
```

---

## Table: `period_snapshots`

Frozen compliance state captured at reporting period close.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| programme_code | VARCHAR(20) | NOT NULL | One snapshot per (period, programme) |
| snapshot_data | JSONB | NOT NULL | Full compliance state at period close |
| generated_at | TIMESTAMPTZ | DEFAULT now() | |
| generated_by | UUID | FK → users.id | Admin who triggered period close |

**Unique constraint:** `UNIQUE(reporting_period_id, programme_code)`

**`snapshot_data` JSONB shape:**
```json
{
  "period_label": "Jan - June 2026",
  "programme_code": "DR",
  "generated_at": "2026-07-01T00:00:00Z",
  "residents": [
    {
      "mcr": "M12345A",
      "name": "John Tan",
      "r_year": "R3",
      "postings": [
        {
          "posting_code": "TTSHDiagRd",
          "active_months": 3,
          "target_70": 21,
          "achieved_and_counted": 18,
          "percentage": 0.857,
          "met_70pct": true,
          "colour": "green",
          "session_types": [
            {
              "session_type": "Department Learning Events [1h]",
              "target_100": 21,
              "achieved": 20,
              "achieved_and_counted": 20,
              "surplus": 0,
              "shortage": 0
            }
          ]
        }
      ],
      "overall_met": true
    }
  ]
}
```

---

## Table: `clawback_records`

Generated at period close for residents who failed to meet the 70% PTT threshold.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| r_year | VARCHAR(10) | NOT NULL | Used for norm rate lookup |
| active_months | DECIMAL(4,1) | NOT NULL | May be fractional for GASTRO split months |
| compliance_percentage | DECIMAL(5,4) | NOT NULL | Posting-level percentage at period close |
| clawback_amount | DECIMAL(10,2) | NOT NULL | Calculated amount. 0.0 for exempted residents. |
| clawback_suppressed_reason | VARCHAR(50) | nullable | Reason row is shown but amount is 0. Values: `Extension`, `R7`, `SAF_Employed`, `SCDF_Employed`. NULL = standard clawback row. |
| billing_dept | VARCHAR(50) | | Copied from posting_codes.billing_dept at generation time |
| generated_at | TIMESTAMPTZ | DEFAULT now() | |

**Clawback display rule:** All rows are shown in the clawback tab regardless of `clawback_suppressed_reason`. Rows with a suppressed reason show `amount = 0` and display the reason to the admin. This ensures senior management can see that a resident failed 70% even when no financial action follows.

**Suppression conditions:**
- `Extension` — resident is on Extension status in FormF1. Compliance tracked, funding not allocated, clawback not exercised.
- `R7` — R7 residents are exempted from clawback (consistent with R script behaviour).
- `SAF_Employed` / `SCDF_Employed` — employer-funded residents excluded from clawback.

---

## Table: `global_session_types`

System-wide catalogue of session types that any secretary can use when creating events but which are **always excluded from PTT compliance** (both numerator and denominator). Managed by admin only via CRUD UI. No file upload needed.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| name | VARCHAR(100) | UNIQUE, NOT NULL | e.g. `Department Meeting [1h]`. Follows same `[Xh]` duration convention as session_types. |
| duration_hours | DECIMAL(4,2) | NOT NULL | Extracted from name bracket e.g. `[1h]` → 1.0 |
| is_active | BOOLEAN | DEFAULT true | Admin can deactivate without deleting. Inactive entries are hidden from secretary dropdown. |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Initial seed:**
- `Department Meeting [1h]` — duration_hours = 1.0

**How it interacts with the compliance engine:**
At compliance read time, before any `teaching_name_catalogue` lookup, the engine checks if `teaching_event.teaching_name` matches any active `global_session_types.name`. If a match is found, the attendance record is **immediately excluded** from both numerator and denominator — no catalogue lookup is performed. This takes priority over any TTF rows.

**How it interacts with secretary event creation:**
The `GET /secretary/teaching-name-options` endpoint returns a unified dropdown combining `teaching_name_catalogue` keywords (TTF-derived, programme/posting-specific) AND active `global_session_types` entries. The secretary sees one list — the distinction is transparent to them.

**How it interacts with resident event visibility:**
Visibility follows the same rule as all other events — residents only see events created at their current posting. A Department Meeting created by TTSHGerMed secretary is only visible to residents currently posted at TTSHGerMed.

**Admin CRUD UI:** Managed alongside `loa_types`, `weekend_exceptions`, `multi_posting_rules`, `posting_groups` in the admin configuration panel. Same access level, same UI pattern.

---

## Index Requirements

Indexes are part of the schema contract. Implement them in SQLAlchemy models and Alembic migrations, and keep index names stable so migrations remain readable.

### General rules

- Add indexes for all foreign-key columns that are used in joins or filters.
- Add composite indexes for high-frequency query paths; do not rely on single-column indexes when the query always filters by multiple fields.
- Do not add indexes for every column. Indexes improve reads but slow writes and increase storage, which matters for bulk uploads.
- Unique constraints already create indexes in PostgreSQL. Do not duplicate equivalent unique indexes unless a different column order is required for a known query path.
- Prefer partial indexes for active/status-filtered lookups where the predicate is stable, for example `status = 'submitted'` or `is_active = true`.
- Use PostgreSQL GIN indexes only where appropriate, especially array fields such as `users.programme_scope`.
- Revisit indexes after Phase 6 admin report/compliance SQL is implemented using `EXPLAIN ANALYZE` on real-ish sample data.

### Required indexes by table

#### `programmes`

```sql
-- UNIQUE(code) already covers direct programme lookup.
CREATE INDEX idx_programmes_rdb_alias
ON programmes(rdb_alias)
WHERE rdb_alias IS NOT NULL;
```

#### `posting_codes`

```sql
-- UNIQUE(code) already covers canonical posting lookup.
CREATE INDEX idx_posting_codes_institution_department
ON posting_codes(institution, department);
```

#### `reporting_periods`

```sql
-- Fast lookup of the current/open period.
CREATE INDEX idx_reporting_periods_status
ON reporting_periods(status);

CREATE INDEX idx_reporting_periods_date_range
ON reporting_periods(start_date, end_date);
```

#### `residents`

```sql
-- UNIQUE(mcr) and UNIQUE(employee_code) cover login/import identity lookups.
CREATE INDEX idx_residents_programme_status
ON residents(programme_code, status);

CREATE INDEX idx_residents_employer_tag
ON residents(employer_tag)
WHERE employer_tag IS NOT NULL;
```

#### `resident_postings`

```sql
-- RDB upload replacement, resident dashboard current-posting lookup, and compliance active phase lookup.
CREATE INDEX idx_resident_postings_period_resident
ON resident_postings(reporting_period_id, resident_id);

CREATE INDEX idx_resident_postings_resident_period_dates
ON resident_postings(resident_id, reporting_period_id, start_date, end_date);

CREATE INDEX idx_resident_postings_period_posting_status
ON resident_postings(reporting_period_id, posting_code, status);

CREATE INDEX idx_resident_postings_compliance_phase
ON resident_postings(reporting_period_id, resident_id, posting_code, r_year, status);

CREATE INDEX idx_resident_postings_month_label
ON resident_postings(reporting_period_id, month_label);
```

#### `teaching_targets`

```sql
-- UNIQUE(reporting_period_id, programme_code, r_year, posting_code, session_type_id) already exists.
-- This supports target lookup by posting/programme/year before grouping by session type.
CREATE INDEX idx_teaching_targets_lookup
ON teaching_targets(reporting_period_id, programme_code, posting_code, r_year);

CREATE INDEX idx_teaching_targets_reallocation
ON teaching_targets(reporting_period_id, programme_code, posting_code, tag)
WHERE is_reallocatable = true;
```

#### `teaching_name_catalogue`

```sql
-- Critical compliance/event-visibility lookup.
CREATE INDEX idx_teaching_name_catalogue_resolution
ON teaching_name_catalogue(reporting_period_id, programme_code, posting_code, r_year, keyword);

CREATE INDEX idx_teaching_name_catalogue_session_type
ON teaching_name_catalogue(session_type_id);

CREATE INDEX idx_teaching_name_catalogue_tracked
ON teaching_name_catalogue(reporting_period_id, programme_code, posting_code, r_year, is_tracked);
```

#### `teaching_events`

```sql
CREATE INDEX idx_teaching_events_posting_date
ON teaching_events(posting_code, event_date);

CREATE INDEX idx_teaching_events_series
ON teaching_events(series_id)
WHERE series_id IS NOT NULL;

CREATE INDEX idx_teaching_events_name_date
ON teaching_events(teaching_name, event_date);

CREATE INDEX idx_teaching_events_adhoc
ON teaching_events(is_adhoc, event_date)
WHERE is_adhoc = true;
```

#### `event_series`

```sql
CREATE INDEX idx_event_series_posting
ON event_series(posting_code);
```

#### `attendance_records`

```sql
-- UNIQUE(resident_id, teaching_event_id) already prevents duplicate submission.
CREATE INDEX idx_attendance_records_resident_status
ON attendance_records(resident_id, status);

CREATE INDEX idx_attendance_records_event_status
ON attendance_records(teaching_event_id, status);

CREATE INDEX idx_attendance_records_submitted_at
ON attendance_records(submitted_at);

CREATE INDEX idx_attendance_records_submitted_resident_event
ON attendance_records(resident_id, teaching_event_id)
WHERE status = 'submitted';
```

#### `surplus_ledger`

```sql
CREATE INDEX idx_surplus_ledger_lookup
ON surplus_ledger(reporting_period_id, resident_id, posting_code, session_type_id);

CREATE INDEX idx_surplus_ledger_hibernation
ON surplus_ledger(reporting_period_id, is_hibernating);
```

#### `form_f1_records`

```sql
-- UNIQUE(reporting_period_id, mcr, month_label) already exists.
CREATE INDEX idx_form_f1_records_active_lookup
ON form_f1_records(reporting_period_id, mcr, month_label, is_active);

CREATE INDEX idx_form_f1_records_upload
ON form_f1_records(upload_id)
WHERE upload_id IS NOT NULL;
```

#### `public_holidays`

```sql
-- UNIQUE(holiday_date) should exist for idempotent upsert.
CREATE INDEX idx_public_holidays_year
ON public_holidays(EXTRACT(YEAR FROM holiday_date));
```

#### `multi_posting_rules`

```sql
CREATE INDEX idx_multi_posting_rules_lookup
ON multi_posting_rules(programme_code, posting_code_1, posting_code_2, rule_type);

CREATE INDEX idx_multi_posting_rules_reverse_lookup
ON multi_posting_rules(programme_code, posting_code_2, posting_code_1, rule_type);
```

#### `posting_groups`

```sql
CREATE INDEX idx_posting_groups_posting_programme
ON posting_groups(posting_code, programme_code);

CREATE INDEX idx_posting_groups_group_programme
ON posting_groups(group_code, programme_code);
```

#### `weekend_exceptions`

```sql
CREATE INDEX idx_weekend_exceptions_lookup
ON weekend_exceptions(programme_code, posting_code, day_type);

CREATE INDEX idx_weekend_exceptions_session_type
ON weekend_exceptions(session_type_id)
WHERE session_type_id IS NOT NULL;
```

#### `users`

```sql
-- UNIQUE(email) should exist for admin/secretary login.
CREATE INDEX idx_users_role
ON users(role);

CREATE INDEX idx_users_posting_code
ON users(posting_code)
WHERE posting_code IS NOT NULL;

CREATE INDEX idx_users_programme_scope_gin
ON users USING GIN(programme_scope);
```

#### `upload_logs`

```sql
CREATE INDEX idx_upload_logs_type_created
ON upload_logs(upload_type, created_at DESC);

CREATE INDEX idx_upload_logs_period_programme
ON upload_logs(reporting_period_id, programme_code);

CREATE INDEX idx_upload_logs_uploaded_by
ON upload_logs(uploaded_by);
```

#### `period_snapshots`

```sql
CREATE INDEX idx_period_snapshots_period_programme
ON period_snapshots(reporting_period_id, programme_code);
```

#### `clawback_records`

```sql
CREATE INDEX idx_clawback_records_period_programme
ON clawback_records(reporting_period_id, programme_code);

CREATE INDEX idx_clawback_records_resident
ON clawback_records(resident_id);
```

#### `global_session_types`

```sql
CREATE INDEX idx_global_session_types_active_name
ON global_session_types(name)
WHERE is_active = true;
```

### Performance verification checklist

After Phase 6 reporting/compliance queries exist, verify the following query families with `EXPLAIN ANALYZE`:

- resident current-posting lookup by `(resident_id, reporting_period_id, today)`
- resident visible events by `(posting_code, event_date)`
- attendance lookup by `(resident_id, teaching_event_id)` and submitted status
- compliance catalogue resolution by `(reporting_period_id, programme_code, posting_code, r_year, keyword)`
- admin report batch query by `(reporting_period_id, programme_code)`
- upload log browsing by `upload_type`, `reporting_period_id`, `programme_code`, `created_at`

---
