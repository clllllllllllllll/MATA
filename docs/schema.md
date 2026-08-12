# Database Schema

`security.md` is authoritative for cross-cutting database roles, RLS, grants,
helper ownership, default ACLs, credential separation, and local-versus-deployed
security evidence. This file remains authoritative for schema objects and
persistence behavior.

All tables use UUID primary keys (`id UUID DEFAULT gen_random_uuid()`), `created_at TIMESTAMPTZ DEFAULT now()`, and `updated_at TIMESTAMPTZ DEFAULT now()` unless noted otherwise. `app_sessions` is an explicit exception: it has `created_at` and `last_seen_at`, but no `updated_at`.

Unless a section explicitly describes an independently implemented
pre-compliance workflow, references below to compliance calculation, surplus,
or a compliance engine are future Phase 6 specification. They do not claim that
a full `compliance.py` or surplus engine is currently implemented.

## Evolved TTF final A-J contract

E2+B2 is implemented by revision `20260805_000036`. The legacy A-K parser,
`teaching_name_catalogue`, and `teaching_targets.details_of_training` are no
longer current schema or runtime objects. The migration removes them after
fail-closed dependency checks; it preserves Teaching Names, mappings, targets,
events, attendance, upload/warning/audit history, and immutable source/display
evidence. Historical A-K references below are retained only as pre-cutover
evidence and downgrade context.

Revision `20260802_000029` introduced the additive B1 persistence foundation.
Revision `20260803_000030` changed the optional event identity FK to `SET NULL`.
Revision `20260803_000031` activates the shared-pool name lifecycle: it
reconciles pending mapping rows through private owner triggers and exposes the
name-only API. These revisions do not change the parser, create pool-backed
events, expose mapping DML, or activate compliance resolution.
Revision `20260803_000032` adds only the narrow E1 TTF mapping-reconciliation
helper used by the existing upload transaction.
Revision `20260804_000033` adds the narrow scheduled-event source insert helper
and uses it only for non-ad-hoc `teaching_events` writes under runtime RLS.
Revision `20260804_000034` replaces Resident/Non-NHG scheduled-event selection
and attendance authorization with explicit source identities where present,
keeps deterministic both-null legacy evidence, exposes only authorised pool
source scope to the runtime, and fixes atomic ad-hoc creation to the one-hour
record without a catalogue or target lookup.
Revision `20260804_000035` adds immutable pool-source programme/reporting-period
snapshots, safely backfills only rows with an explicit Teaching Name ID, and
replaces the affected event and attendance authorization with row-local,
full-datetime rules.

Revision `20260805_000036` removes the catalogue and target details column,
retires their policies/grants/helper inventory, and sets SPORTSMED/PALLMED to
`r_year_required = true` and `is_subspecialty = false`. It deliberately does
not rekey existing targets or mappings. Downgrade can restore only an empty
catalogue structure and nullable details column; it cannot recreate deleted
Column K text or catalogue rows.

Revision `20260806_000038` keeps the same table and policy inventory while
tightening the existing runtime-only pool-event helpers. A Programme PC's
pool-backed insert or update now requires an exact persisted Teaching Name
mapping for the source reporting period, source programme, and event posting.
Pending mappings are valid; a missing mapping scope is not. Secretary and
Master branches are unchanged.

The current final model uses `teaching_name` as the canonical term:

- The `teaching_names` relation is scoped by
  `(reporting_period_id, programme_code)`, has a display name, a server-owned
  normalized name, active/deactivated state, revision, and normal actor/time
  audit fields. A new reporting period starts with an empty pool; there is no
  copy-forward, while prior-period names remain historical.
- Normalization uses Unicode canonical normalization, trims outer whitespace,
  collapses repeated internal whitespace, and enforces case-insensitive
  uniqueness within that pool. It preserves punctuation and wording; it does
  not apply fuzzy matching, abbreviation expansion, synonyms, or semantic
  matching.
- The `teaching_name_mappings` relation has exactly one identity per
  `(teaching_name_id, reporting_period_id, programme_code, posting_code,
  r_year)`. It may select only the exact `teaching_targets` row from that same
  scope. A null target is **pending** and a non-null target is **mapped**; no
  duplicate status column or manual `excluded` state is permitted.
- Both an explicitly authorized Department Secretary and Programme PC may
  create, rename, deactivate, and reactivate names in their shared pool. Phase
  D exposes a separate Programme-PC mapping queue and mutation API: a PC may
  assign, change, or explicitly clear only an in-scope mapping, while a Master
  Admin is read-only and a Secretary has no mapping route. A Secretary/PC may
  delete only an unused name;
  Master Admin may delete a used name only with current revision, explicit
  force flag, nonblank reason, and `DELETE` confirmation. Secretary management
  authority is a separate explicit
  Secretary-to-programme capability (the pilot is TTSH GERI), never an
  inference from `programmes.native_teaching_posting_code` or event visibility.
- Mapping-scope provisioning is deterministic: name creation creates pending
  mappings for existing distinct posting/R-year scopes and reactivation fills
  only missing rows introduced while inactive. Existing mapping IDs and mapped
  targets are preserved; adding a session type to an existing scope never
  duplicates a mapping.
- A Phase F pool-backed `teaching_events` row has `teaching_name_id` populated
  and `global_session_type_id` null. A global row has the reverse. Transitional
  legacy rows may have neither, but no row may have both. Source identity is
  never inferred from display text. Pool-backed events belong to exactly one
  programme through their Teaching Name; PC event programme must match it, and
  snapshot-text fan-out across programme pools is forbidden.
- A Programme PC may write a pool-backed event only when a
  `teaching_name_mappings` row exists for that exact Teaching Name, source
  reporting period, source programme, and event posting. This is an event
  authorization scope check, not a target-state check: both pending and mapped
  rows qualify, while Secretary and Master event authority retains its separate
  documented boundary.
- A pool-backed scheduled event derives duration from the exact Teaching Name,
  reporting-period, programme, posting, and R-year mappings. Each exact
  Teaching Name/posting/R-year identity selects at most one target. Different
  R-years may select session types with different durations; the longest
  effective R-year duration is stored as the staff event envelope. A pending
  R-year contributes a temporary one hour. The client supplies `start_time`
  only, the server computes `end_time`, and a start later than 23:00 is a
  controlled `422`.
  Assigning, changing, clearing, or invalidating a mapping recalculates stored
  `duration_hours` and `end_time` for existing events in that exact scope.

In the implemented Phase F/G model, pending names remain selectable,
event-capable, visible, attendance-submittable, and auditable. A mapped target
supplies scheduling duration only; it does not change the immutable display or
source snapshots and is not a compliance multiplier.
Native Resident runtime uses persisted source identity plus the Resident's
date-specific R-year to derive resident-facing duration and end time. Non-NHG
runtime uses exact date-matched posting visibility and the staff event envelope;
it does not resolve NHG compliance or R-year mappings. Neither path uses a
catalogue value or display-text inference. Native attendance is excluded from
future compliance until an exact R-year mapping exists; the next JIT read
resolves a newly mapped name without rewriting attendance rows.
`global_session_types` remain
Admin-managed, outside this queue, and are handled before ordinary Teaching
Name mapping. Resident ad-hoc teaching remains fixed to
`Department/Programme Teaching [1h]`; Non-NHG attendance remains outside NHG
compliance.

The final TTF is A-J only: reporting period, programme, R-year, posting,
dashboard posting/posting group, session type, monthly target, tracked,
reallocatable, and tag. Column K is removed. An upload with a
populated legacy Column K must return controlled `422`; there is no dual-format
support, Column K backfill, or historical-data migration. A TTF creates no
Teaching Name and no mapping from workbook text. Existing mappings are
provisioned only from distinct posting/R-year target scopes and active shared
pool names. Actual all-28 operational onboarding remains Phase R.

## Entity Relationship Summary

```
programmes ─1:N─ teaching_targets
programmes ─1:N─ residents (via programme_code)
programmes ─1:N─ multi_posting_rules
programmes ─1:N─ posting_groups
programmes ─1:N─ academic_month_boundaries (via ay_date_category)

posting_codes ─1:N─ resident_postings
posting_codes ─1:N─ teaching_targets
posting_codes ─1:N─ teaching_events
posting_codes ─1:N─ external_residents (current_nhg_posting_code)
posting_codes ─1:N─ external_resident_postings
posting_codes ─1:N─ multi_posting_rules
posting_codes ─1:N─ posting_groups

residents ─1:N─ resident_postings
residents ─1:N─ attendance_records
residents ─1:N─ surplus_ledger
residents ─logical 1:N─ app_sessions (subject_type = resident)

external_residents ─1:N─ external_attendance_records
external_residents ─1:N─ external_resident_postings
external_residents ─logical 1:N─ app_sessions (subject_type = external_resident)
teaching_events ─1:N─ external_attendance_records

teaching_events ─1:N─ attendance_records
teaching_events ─N:1─ event_series (nullable)

session_types ─1:N─ teaching_targets
session_types ─1:N─ teaching_events (display only)

reporting_periods ─1:N─ teaching_targets
reporting_periods ─1:N─ resident_postings
reporting_periods ─1:N─ period_snapshots
reporting_periods ─1:N─ teaching_names
reporting_periods ─1:N─ teaching_name_mappings
reporting_periods ─1:N─ form_f1_records

posting_codes ─1:N─ teaching_name_mappings
programmes ─1:N─ teaching_names
programmes ─1:N─ teaching_name_mappings

teaching_names ─1:N─ teaching_name_mappings
teaching_names ─1:N─ teaching_events (nullable B1 identity)
teaching_targets ─1:N─ teaching_name_mappings (nullable exact-scope target)
global_session_types ─1:N─ teaching_events (nullable B1 identity)

users ─1:N─ upload_logs
users ─logical 1:N─ app_sessions (subject_type = staff)
upload_logs ─1:N─ academic_month_boundaries

rate_limit_buckets (standalone security infrastructure)
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
| ay_date_category | VARCHAR(30) | NOT NULL, CHECK IN (`im_subspec`, `non_im_subspec`) | Selects which AY month-boundary category is used for attendance month bucketing in compliance (`academic_month_boundaries`) |
| r_year_required | BOOLEAN | DEFAULT true | If false, programme uses `r_year = 'ALL'` sentinel — TTF targets apply to all r_years equally |
| is_subspecialty | BOOLEAN | DEFAULT false | Programme classification/configuration flag. It does not trigger R-year remapping. |
| rdb_alias | VARCHAR(100) | nullable | Alternative programme name that appears in RDB cells. Used for normalisation at RDB parse time. |

**Note:** FM uses the standard compliance engine. There is no `compliance_variant` column — FM compliance is handled through FM-specific rule annotations within the standard path. See `docs/business-logic.md` § BL-FM.

**Native teaching posting mapping:** NHG Resident visibility for native programme department secretary events uses the nullable `programmes.native_teaching_posting_code` FK. This native visibility field is independent from `programme_institution_posting_map`, which is exclusively for Non-NHG registration and posting-schedule resolution. Activating an external-registration mapping must not populate or change `native_teaching_posting_code`.

**Seed data (from Programme_ABBREV.xlsx — 28 programmes):**

| code | name | ay_date_category | r_year_required | is_subspecialty | rdb_alias |
|------|------|------------------|----------------|----------------|-----------|
| AIM | Advanced Internal Medicine | im_subspec | false | false | NULL |
| ANAES | Anaesthesiology | non_im_subspec | true | false | NULL |
| CARDIO | Cardiology | im_subspec | false | false | NULL |
| DERM | Dermatology | im_subspec | true | false | NULL |
| DR | Diagnostic Radiology | non_im_subspec | true | false | NULL |
| EM | Emergency Medicine | non_im_subspec | false | false | NULL |
| ENDO | Endocrinology | im_subspec | false | false | NULL |
| ENT | Otorhinolaryngology | non_im_subspec | false | false | NULL |
| EYE | Ophthalmology | non_im_subspec | false | false | NULL |
| FM | Family Medicine | non_im_subspec | true | false | NULL |
| GASTRO | Gastroenterology | im_subspec | false | false | NULL |
| GERI | Geriatric Medicine | im_subspec | false | false | NULL |
| GS | General Surgery | non_im_subspec | false | false | NULL |
| ID | Infectious Diseases | im_subspec | false | false | Infectious Disease |
| IM | Internal Medicine | im_subspec | false | false | NULL |
| MEDONCO | Medical Oncology | im_subspec | false | false | NULL |
| ORTHO | Orthopaedic Surgery | non_im_subspec | false | false | NULL |
| PATH | Pathology | non_im_subspec | false | false | NULL |
| PSY | Psychiatry | non_im_subspec | true | false | NULL |
| REHAB | Rehabilitation Medicine | im_subspec | false | false | NULL |
| RENAL | Renal Medicine | im_subspec | false | false | Renal Medicine Extended |
| RESPI | Respiratory Medicine | im_subspec | true | false | NULL |
| RHEUM | Rheumatology | im_subspec | false | false | NULL |
| SPORTSMED | Sports Medicine | non_im_subspec | true | false | NULL |
| SIG | Surgery-In-General | non_im_subspec | false | false | Surgery-in-General |
| URO | Urology | non_im_subspec | false | false | NULL |
| MICROB | Pathology (Microbiology) | non_im_subspec | false | false | Microbiology |
| PALLMED | Palliative Medicine | im_subspec | true | false | NULL |

**r_year_required = false (20 programmes):** AIM, CARDIO, EM, ENDO, ENT, EYE, GASTRO, GERI, GS, ID, IM, MEDONCO, ORTHO, PATH, REHAB, RENAL, RHEUM, SIG, URO, MICROB

**r_year_required = true (8 programmes):** ANAES, DERM, DR, FM, PSY, RESPI, SPORTSMED, PALLMED

**SPORTSMED/PALLMED R-year rule:** both have `is_subspecialty = false`; RDB and TTF use R4, R5, and R6 unchanged. Neither uses `ALL` or SS1–SS3 remapping.

**ay_date_category = im_subspec (14 programmes):** AIM, CARDIO, DERM, ENDO, GASTRO, GERI, ID, IM, MEDONCO, PALLMED, REHAB, RENAL, RESPI, RHEUM

**ay_date_category = non_im_subspec (14 programmes):** ANAES, DR, EM, ENT, EYE, FM, GS, MICROB, ORTHO, PATH, PSY, SIG, SPORTSMED, URO

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
| billing_dept | VARCHAR(50) | | Legacy/planned billing metadata. Any future clawback attribution source and time grain remain deferred. |
| is_emergency | BOOLEAN | DEFAULT false | Emergency-posting classification for audit/display. It does not bypass public-holiday blocking or create an automatic weekend exception. |
| supports_secretary_events | BOOLEAN | DEFAULT false | Posting capability hint for secretary-event onboarding. It is not a Resident or Non-NHG Resident visibility/submission authorization clamp. |

**Important:** Posting codes are NOT derivable by regex from institution+department. Real codes like `MOHHGTG1`, `AICAIC`, `RenCiCommHosp`, `NHGPlyNHGPly` break any uniform pattern. This table is the source of truth — no string parsing.

**Secretary-event visibility capability:** `supports_secretary_events` is a scalable onboarding/capability signal and useful UI metadata. NHG Resident event visibility must stay data-driven (assigned/native source context plus valid event-date and persisted-source evidence) and must not be hardcoded to institution names.

---

## Table: `programme_institution_posting_map`

Authoritative configuration for resolving a Non-NHG Resident's selected programme and institution to one canonical RDB posting code. It is not used for native teaching visibility, Secretary capabilities, event ownership, or compliance attribution.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | Exact normalized programme code |
| institution_code | VARCHAR(20) | NOT NULL | Open configuration value; no database enum, so later institutions require data only |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | Canonical posting returned only by the trusted backend resolver |
| status | VARCHAR(20) | NOT NULL, CHECK IN (`pending`, `active`, `inactive`) | `active` requires non-null `posting_code` |
| display_order | INTEGER | NOT NULL, DEFAULT 0 | Stable public programme ordering |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Constraints and public behavior:**

- `UNIQUE(programme_code, institution_code)` permits only one authoritative row for a pair.
- `CHECK (status <> 'active' OR posting_code IS NOT NULL)` prevents unsafe activation.
- `pending` rows are visible in public registration options with `available = false` and may have `posting_code = NULL`.
- `active` rows are visible with `available = true` only when both foreign keys resolve.
- `inactive` rows may retain their prior posting code for audit/restoration and are omitted from public registration options.
- Services trim and uppercase institution/programme codes and reject blanks or control characters. They never construct or infer posting codes.

**Two-stage TTSH rollout and current seeded state:**

1. Stage 1 creates the generic table and seeds exactly one TTSH row for each of the 28 baseline programmes. Every row is `pending`, every `posting_code` is `NULL`, and no GERI exception exists.
2. The approved Stage 2 data-only migration validates the complete 28-row baseline before updating anything, then sets exactly 24 rows to `active` with their approved posting codes and sets `FM`, `PATH`, `SPORTSMED`, and `PALLMED` to `inactive` with `posting_code = NULL`. Display order remains deterministic and consistent with programme seed order.

The Stage 2 migration must reject duplicate/missing mapping rows, programme entries, blank approved values, missing programme/posting FK targets, overlaps between the 24-code active set and four-code inactive set, or any union other than the exact 28-programme TTSH baseline. Posting codes are explicit approved values and are never inferred or validated by institution-name/prefix assumptions; more than one programme may validly target the same posting code because uniqueness is by `(programme_code, institution_code)`. After its update it must verify `active = 24`, `inactive = 4`, `pending = 0`, no active row has a null posting code, every active pair exactly matches the approved mapping, and no other institution row changed. Any failure rolls back the whole migration. No manual production SQL is permitted.

The four inactive rows affect only Non-NHG registration and posting-schedule selection through this table. They do not change the corresponding `programmes` rows or disable `FM`, `PATH`, `SPORTSMED`, or `PALLMED` anywhere else in MATA.

**Configuration isolation:** This table must never update or grant `programmes.native_teaching_posting_code`, `posting_codes.supports_secretary_events`, Secretary programme pools, native resident visibility, event-creation rights, or compliance posting attribution.

---

## Table: `reporting_periods`

Six-month reporting windows.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| label | VARCHAR(30) | UNIQUE, NOT NULL | e.g. `Jan - June 2026`, `Jul - Dec 2025` |
| start_date | DATE | NOT NULL | |
| end_date | DATE | NOT NULL | |
| status | VARCHAR(10) | DEFAULT 'active' | `active`, `inactive` only. `open`/`closed` are legacy values and must be migrated/rejected at the API boundary. |
| activate_on | DATE | nullable | Optional scheduled activation date. Effective status is resolved at read time. |
| deactivate_on | DATE | nullable | Optional scheduled deactivation date. Effective status is resolved at read time. |

**Effective status:** `status` is the stored manual state. `activate_on` and `deactivate_on` are read-time scheduling hints; due dates do not mutate the row by themselves. When both scheduled dates are due, the later scheduled date wins; if both are due on the same date, deactivation wins.

**Resolution and administration:** Multiple rows may be administratively active at the same time; there is no single-active-period constraint. Operational resolution additionally requires the relevant date to fall within `start_date..end_date`, and must fail closed if more than one effectively active period contains that date. The reporting-period create service defaults an omitted `deactivate_on` to `end_date + 14 calendar days`; this is application behaviour, not a database column default. A new immediate or scheduled reopening of a past period requires a bounded future `deactivate_on`; a scheduled reopen must end strictly after `activate_on`.

---

## Table: `residents`

One row per resident. Created from RDB upload. Also serves as the **identity source for resident authentication**: MCR is the login credential, while `programme_code` is reloaded from this row for cookie-session identity and compliance scope. Only emergency `bearer_compat` embeds it in a MATA JWT.

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
| session_generation | BIGINT | NOT NULL, DEFAULT 0, CHECK >= 0 | Subject-wide application-session invalidation generation |

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
| r_year | VARCHAR(10) | NOT NULL | Residency year at this phase. For programmes with `r_year_required = false`, this is set to `'ALL'`; otherwise preserve the normalized RDB R-year. SPORTSMED/PALLMED use R4–R6 unchanged. Copied from RDB column F at parse time and used for target lookup — do NOT use `residents.r_year` for compliance. |
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

**RDB re-upload behaviour:** RDB uploads are complete snapshots for the selected reporting period. On re-upload, existing `resident_postings` for the selected `reporting_period_id` are deleted after successful parse/validation and then replaced with rows parsed from the uploaded RDB. `residents` are upserted by MCR and are never deleted by RDB upload; residents absent from a new RDB remain in `residents` for history but have no `resident_postings` for that `reporting_period_id`.

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

**Note:** Duration is embedded in the session type name as `[Xh]`. There is no separate duration column in the TTF — duration is extracted from the name via regex at upload time for display and validation. Reallocation order is the alphabetical tag label, not duration. Compliance transfers and counts sessions one-for-one; duration is never a multiplier.

---

## B1 foundation and Phase C Teaching Name lifecycle

Revision `20260802_000029` created the additive objects below. Before E2+B2,
the legacy parser/configuration workflow also retained
`teaching_name_catalogue`; revision `20260805_000036` removes it. Phase F and
Phase G scheduled-event creation, discovery, and attendance use persisted
source identities instead. The deferred compliance resolver must use a scoped
mapping rather than event display text. The pool is never seeded from TTF text.

### Table: `teaching_names`

Canonical Teaching Name pool, scoped to one reporting period and programme.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | Immutable pool scope. |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | Immutable pool scope. |
| display_name | VARCHAR(200) | NOT NULL, trimmed value cannot be blank | Display/audit form. |
| normalized_name | VARCHAR(200) | NOT NULL, trimmed value cannot be blank | Stored canonical key for the later mutation boundary. |
| is_active | BOOLEAN | NOT NULL, DEFAULT true | Deactivation is additive state, not deletion. |
| revision | INTEGER | NOT NULL, DEFAULT 1, CHECK (`revision > 0`) | Future mutation fencing. |
| created_by_user_id / updated_by_user_id / deactivated_by_user_id | UUID | nullable FK → users.id | Actor audit fields. |
| deactivated_at | TIMESTAMPTZ | nullable | Deactivation audit time. |

**Unique constraints:** `UNIQUE(reporting_period_id, programme_code,
normalized_name)` and the candidate key `UNIQUE(id, reporting_period_id,
programme_code)` used by mappings. A trigger rejects later changes to the
reporting-period/programme scope.

### Table: `teaching_name_mappings`

One optional exact-target mapping for a Teaching Name and posting/R-year scope.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| teaching_name_id | UUID | NOT NULL; composite FK to its Teaching Name pool, `ON DELETE CASCADE` | Keeps the mapping in the name's reporting-period/programme pool and removes configuration-only mappings with the name. |
| reporting_period_id | UUID | NOT NULL | Pool scope, checked by the composite Teaching Name FK. |
| programme_code | VARCHAR(20) | NOT NULL | Pool scope, checked by the composite Teaching Name FK. |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | Mapping scope. |
| r_year | VARCHAR(10) | NOT NULL | Mapping scope. |
| teaching_target_id | UUID | nullable; composite FK to teaching_targets | Null is pending; a value must be a target in the same period/programme/posting/R-year scope. |
| revision | INTEGER | NOT NULL, DEFAULT 1, CHECK (`revision > 0`) | Future mutation fencing. |
| created_by_user_id / updated_by_user_id | UUID | nullable FK → users.id | Actor audit fields. |

**Unique constraint:** `UNIQUE(teaching_name_id, posting_code, r_year)`. The
target foreign key uses the additive candidate key `(id, reporting_period_id,
programme_code, posting_code, r_year)`. It deliberately does **not** make that
  four-part target scope globally unique: targets may have several
session types in the same scope.

### Related B1 / Phase C additions

- `teaching_events.teaching_name_id` is a nullable `SET NULL`-referenced stable
  identity, while `global_session_type_id` remains nullable and `RESTRICT`-
  referenced. Deleting a Teaching Name clears only the optional identity; the
  immutable event `teaching_name` snapshot, event metadata, and native and
  Non-NHG attendance remain intact. The database permits legacy rows with
  neither but rejects rows with both; B1 neither backfills nor changes the
  legacy `teaching_name` text workflow.
- `secretary_programme_pools.can_manage_teaching_names` is non-null and defaults
  to false. Migration preflight enables it only for the single active approved
  `TTSHGerMed`/`GERI` pilot pool.
- The private owner-only `reconcile_teaching_name_pending_mappings` trigger
  inserts one pending mapping per distinct existing target `(posting_code,
  r_year)` scope on active-name creation and inactive-to-active reactivation.
  It never replaces a mapped target or duplicates an existing mapping identity.
- The private owner-only used-name delete guard prevents Secretary/PC direct SQL
  from deleting a name referenced by an event, including where event RLS would
  otherwise hide the reference. The application service supplies the separate
  Master Admin force-delete confirmation, reason, audit, and count-only response.
- The runtime-only, Master-checked `mata_rls.lock_master_teaching_name_delete`
  helper returns no row data and locks one requested name before the service
  counts used-name references. It does not grant Master Admin ordinary name
  update authority.

---

## Current final A-J TTF persistence

`teaching_targets` contains only the stable natural identity
`(reporting_period_id, programme_code, r_year, posting_code, session_type_id)`
and these mutable target fields: `monthly_target`, `is_tracked`,
`is_reallocatable`, and `tag`. Structural fields require TTF re-upload. A
successful upload preserves unchanged target IDs, updates mutable fields in
place, makes stale mappings pending before deleting stale targets, and creates
pending mappings only for active shared-pool Teaching Names in newly introduced
posting/R-year scopes. Adding another session type to an existing scope does not
create another mapping.

`teaching_name_catalogue` does not exist. No current model, API route, helper,
policy, grant, cache domain, parser, or event/attendance path may depend on it.
Historical warning/audit rows that mention the retired type remain immutable
evidence. Non-NHG availability remains independently configured by
`programme_institution_posting_map` and is never activated or inferred by TTF.

## Historical legacy A-K TTF catalogue path (removed by E2+B2)

The following target, catalogue, and event fields are pre-`20260805_000036`
schema evidence. References to `details_of_training` or Column K in this
section are historical only and do not describe the final evolved TTF contract
or any current runtime path.

## Table: `teaching_targets`

One row per (reporting_period, programme, residency_year, posting_code, session_type). The core compliance reference.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | |
| r_year | VARCHAR(10) | NOT NULL | `R1`..`R7`, or `'ALL'` for programmes with `r_year_required = false`; SPORTSMED/PALLMED use R4–R6 |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| monthly_target | INTEGER | NOT NULL, CHECK (`monthly_target >= 0`) | Non-negative sessions per active month at 100%. `0` is valid and remains catalogue-seeded for the physical parser path; it does not change Phase G runtime eligibility. |
| is_tracked | BOOLEAN | DEFAULT true | If false, future compliance excludes the target. The row remains seeded into `teaching_name_catalogue` for the physical transition path, not Phase G event visibility. |
| is_reallocatable | BOOLEAN | DEFAULT false | Whether surplus can be reallocated via tag |
| tag | VARCHAR(10) | | Reallocation tier label. If set, its prefix must have at least one other reallocatable row at the same physical posting and R-year context. |
| details_of_training | TEXT | | Raw column K text. Comma-separated keywords. Parsed into teaching_name_catalogue at upload time. |

**Unique constraint:** `UNIQUE(reporting_period_id, programme_code, r_year, posting_code, session_type_id)`

---

## Table: `teaching_name_catalogue`

Legacy keyword→session-type mapping table seeded from TTF Column K at upload
time. It remains a parser/configuration artifact; Phase G does not use it for
Resident/Non-NHG event visibility, attendance authorization, or ad-hoc input.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| keyword | VARCHAR(200) | NOT NULL | Individual keyword e.g. `Journal Club` |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | |
| r_year | VARCHAR(10) | NOT NULL | `R1`..`R7`, or `'ALL'`; SPORTSMED/PALLMED use R4–R6 |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| duration_hours | DECIMAL(4,2) | NOT NULL | Copied from `session_types` for event-option display/timing metadata only; never used to choose the compliance mapping |
| is_tracked | BOOLEAN | DEFAULT true | Copied from teaching_targets.is_tracked |

**Unique constraint:** `UNIQUE(keyword, posting_code, programme_code, r_year, reporting_period_id)`

**Usage:** Regenerated at TTF upload time within scope. Also regenerated for the specific target when `PATCH /admin/parsed-data/teaching-targets/{id}` updates transitional `details_of_training`.

The same canonical `keyword` may legitimately appear at different postings and
map to different session types. This remains legacy upload/configuration data;
it must not be used as a Phase G runtime fallback, text-inference source, or
cross-programme fan-out mechanism. Do not use fuzzy matching.

---

## Table: `teaching_events`

Teaching sessions created by secretaries, Programme PC CRUD, or ad-hoc submissions by residents.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | Posting/site context for the event. Secretary-created events are posting-owned; PC-created events also carry explicit programme ownership in `created_for_programme_code`. For NHG Resident ad-hoc submissions, this is the assigned/compliance posting for the selected date, not necessarily the attended TTSH department. |
| created_for_programme_code | VARCHAR(20) | FK → programmes.code, nullable | Explicit programme ownership for PC-created scheduled events. Required for PC-created programme-owned events. Null for secretary-created posting-owned/programme-neutral events unless explicitly set by a future workflow. |
| teaching_name | VARCHAR(200) | NOT NULL | Immutable display snapshot for scheduled events, taken from the selected source identity. It is not used to infer or replace that identity. Phase G ad-hoc rows use the fixed `Department/Programme Teaching [1h]` snapshot only; clients do not select a teaching name. |
| details_of_session | TEXT | nullable | Display/audit-only free text for ad-hoc session context. It has no operational or compliance use and is stored on the shared event row for both NHG and Non-NHG Residents. |
| event_date | DATE | NOT NULL | |
| start_time | TIME | NOT NULL | |
| end_time | TIME | | Server-computed from the explicit scheduled-event source duration at creation/update. Pool sources use their posting-specific mapped TTF duration, temporarily defaulting to one hour while unmapped, and cannot start after 23:00; global sources use their configured duration. |
| duration_hours | DECIMAL(4,2) | | Server-owned scheduling duration: the consistent exact-scope mapped TTF duration for a pool source, temporary `1.00` while unmapped, or the active global source duration. Mapping changes recalculate this field and `end_time` for exact-scope pool events. Never used as a compliance multiplier or text inference input. |
| session_type_id | UUID | FK → session_types.id, nullable | Legacy display/prototype field. It is null for Phase G ad-hoc rows and must not be used to infer a scheduled-event source, Resident/Non-NHG visibility, attendance eligibility, or ad-hoc classification. |
| teaching_name_id | UUID | FK → teaching_names.id, nullable, `SET NULL` | Additive B1 stable pool identity. Deleting the referenced name clears this optional link only; the event snapshot and attendance remain. Legacy rows remain null until a later cutover. Cannot coexist with `global_session_type_id`. |
| global_session_type_id | UUID | FK → global_session_types.id, nullable, `RESTRICT` | Additive B1 stable global identity. Legacy rows remain null until a later cutover. Cannot coexist with `teaching_name_id`. |
| source_programme_code | VARCHAR(20) | FK → programmes.code, nullable, `RESTRICT` | Immutable programme snapshot for a pool-backed scheduled source. Paired with `source_reporting_period_id`; remains populated if `teaching_name_id` is later cleared. Null for global, true legacy, and ad-hoc rows. |
| source_reporting_period_id | UUID | FK → reporting_periods.id, nullable, `RESTRICT` | Immutable reporting-period snapshot for a pool-backed scheduled source. Paired with `source_programme_code`. |
| series_id | UUID | FK → event_series.id, nullable | Set if this event is part of a recurring series |
| cme_points_awarded | BOOLEAN | DEFAULT false | |
| smc_event_code | VARCHAR(50) | | |
| is_adhoc | BOOLEAN | DEFAULT false | True for resident-submitted ad-hoc events, false for secretary-created events |
| created_by_role | VARCHAR(20) | | `secretary`, `programme_pc`, `resident`, or `external_resident` depending on creator/source role. This is role/source metadata only, not an actor-name field. |
| created_by_resident_id | UUID | FK → residents.id, nullable | Immutable native creator identity for `is_adhoc = true AND created_by_role = 'resident'`; null for every other event family. |
| created_by_external_resident_id | UUID | FK → external_residents.id, nullable | Immutable Non-NHG creator identity for `is_adhoc = true AND created_by_role = 'external_resident'`; null for every other event family. |

**Phase F scheduled-event source invariant:** Every newly written scheduled row
has exactly one source identity: a pool-backed row has `teaching_name_id` and a
global row has `global_session_type_id`. Both-null rows are transitional legacy
data, remain readable, and are never resolved from their display text. A used
Teaching Name deletion clears only the optional ID (`SET NULL`) and preserves
the display snapshot, immutable source programme/period snapshots, and native
or Non-NHG attendance. Source and programme-owner snapshots cannot be updated.
This invariant does not apply to ad-hoc
rows. Phase G ad-hoc rows use neither scheduled-event source ID and instead
carry the fixed one-hour record under their typed creator/attendance family.

For source-backed scheduled writes, `session_type_id` is retained only as a
nullable legacy display field and is not resolved from
`teaching_name_catalogue`. Phase G uses the persisted source IDs for discovery
and attendance where present, with deterministic both-null legacy evidence and
no display-text fallback.

Pool snapshots are both null or both populated. A non-null `teaching_name_id`
requires both snapshots and must resolve to that exact programme and period.
Global and ad-hoc rows cannot carry pool snapshots. New global writes require an
active type; later deactivation affects choices only and does not hide or
invalidate an existing event or eligible attendance.

**Ad-hoc ownership constraint:** Scheduled events carry neither creator foreign
key. A Resident-created ad-hoc event carries exactly one creator foreign key,
and the populated family must agree with `created_by_role`. Ad-hoc rows cannot
carry scheduled programme/series ownership. The event kind, creator role, and
both creator foreign keys are immutable. Migration `20260728_000028` backfills
only a role-consistent event with exactly one distinct same-family attendance
subject across all statuses and no opposite-family subject; an ambiguous,
orphaned, mixed-family, or role-mismatched event aborts the upgrade.

**Programme ownership visibility rule:**
- `created_for_programme_code IS NULL` → treat the event as normal posting-owned/programme-neutral secretary/ad-hoc visibility. For NHG Residents, secretary-created events may qualify through assigned posting visibility or through the resident's explicit native-programme TTSH department posting mapping. Scheduled-event source eligibility is then evaluated from persisted IDs (or both-null legacy evidence), never the catalogue.
- `created_for_programme_code IS NOT NULL` → show only to residents whose `programme_code` equals that value, and only if the event also passes normal date and persisted-source eligibility checks. PC-created events are programme-owned, not TTSH site-owned.

**PC-created event contract:** Programme PC CRUD creates scheduled teaching events, not ad-hoc submissions. PC-created rows must set `created_for_programme_code`, select one active in-scope Teaching Name or Global Session Type ID, be public-holiday blocked, and be edit/delete-blocked when native or external attendance exists. Phase G applies persisted-source eligibility without a catalogue runtime gate.

**Master Admin transactional hard-delete exception:** No schema migration, cascade constraint, soft-delete column, or deletion-history table is required for the **Secretary/PC Events** operational override. The dedicated Master Admin service locks the selected scheduled `teaching_events` row, verifies that linked native/external counts still match the confirmed impact, explicitly deletes every linked native `attendance_records` row and every linked `external_attendance_records` row, deletes only that event occurrence, and writes the immutable audit record before the single transaction commits. Foreign keys retain their existing non-cascade behaviour and remain the final integrity guard. Ad-hoc events are not eligible; series siblings and the `event_series` row are preserved.

**Ad-hoc detail contract:** `details_of_session` is optional context text only. It must not participate in event visibility, session type resolution, denominator/numerator calculation, surplus, snapshots, or clawback.

**Phase G ad-hoc posting contract:** The server derives exactly one posting from
the teaching date. The API exposes and accepts only that value as an optional
confirmation; it does not permit a separate attended department/programme
selection or persist an attended-posting field. It must not replace
`posting_code` for NHG compliance attribution.

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

TODO: If Programme PC recurrence support is added later, decide whether `event_series` also needs explicit programme ownership (for example `created_for_programme_code`) or whether recurrence scope is derived only from child `teaching_events`. The implementation must prevent cross-programme recurrence edits/deletes.

---

## Table: `attendance_records`

One immutable row per native attendance submission cycle. A removed cycle is
retained and a later resubmission receives a new row.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| teaching_event_id | UUID | FK → teaching_events.id, NOT NULL | |
| submitted_at | TIMESTAMPTZ | DEFAULT now() | |
| status | VARCHAR(20) | DEFAULT 'submitted' | `submitted`, `flagged`, `removed` |
| posting_code | VARCHAR(50) | | Audit copy of event posting at submission time. **Never used for compliance attribution** — compliance always uses teaching_events.posting_code. |

**Active uniqueness and history:** A submitted-only unique index on
`(resident_id, teaching_event_id)` prevents two active submissions while
allowing each removed row to remain immutable history. Resubmission inserts a
new row with a new identifier; it does not restore or overwrite the removed
row. `status` is constrained to `submitted`, `flagged`, or `removed`, subject
and event identifiers cannot be retargeted, and a removed row cannot be
resurrected in place.

**Distinct-event overlap invariant:** Before inserting a later submission, the
attendance service and database reject it if its full datetime interval overlaps
an already accepted distinct event for the same resident. An `end_time` less
than or equal to `start_time` belongs to the following date, so `23:00–00:00`
is valid and is compared against rows on both dates. Exact boundary contact is
not overlap. The earlier accepted attendance is preserved unchanged. This rule
is separate from same-event uniqueness and applies to native and Non-NHG rows.

**Session type is NOT stored here.** The Phase 6 compliance resolver is deferred. When implemented, it must resolve through the event's persisted source identity and a scoped mapping for the resident/posting/r-year context; the immutable `teaching_name` display snapshot is never a matching input.


---

## Table: `external_residents`

One row per Non-NHG/cross-cluster resident who self-registers to submit attendance for NHG-posted teaching. Backend/internal table names use `external_residents`; user-facing text should say Non-NHG Resident. Non-NHG Residents are **not** native NHG residents, are **not** `users`, and are **not** RDB-backed.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| name | VARCHAR(100) | NOT NULL | Self-registered display name |
| mcr | VARCHAR(20) | UNIQUE, NOT NULL | MCR is the login credential. Service layer must also reject MCRs already present in native `residents`. |
| home_cluster | VARCHAR(20) | NOT NULL, CHECK IN (`NUH`, `SingHealth`) | External home cluster only. No other values accepted. |
| current_nhg_posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | Current/cache/backward-compatibility pointer derived by the backend from the trusted programme/institution mapping. It is never client-selected and is not derived from native `resident_postings`. |
| status | VARCHAR(20) | DEFAULT 'active' | `active`, `inactive` |
| session_generation | BIGINT | NOT NULL, DEFAULT 0, CHECK >= 0 | Subject-wide application-session invalidation generation |

**Global MCR uniqueness:** MCR is a unique identifier for every doctor. Migration `20260726_000025` normalizes existing native and external MCR values, rejects blank or cross-table duplicate values before cutover, and installs `BEFORE INSERT OR UPDATE OF mcr` triggers on both identity tables. The triggers serialize equal normalized MCR writes with a transaction-scoped advisory lock and reject a value already present in the other identity table. Global-identity writes require `READ COMMITTED` and fail closed at stronger snapshot isolation. Service checks remain for controlled API errors, but they are not the race boundary.

**Compliance exclusion:** Non-NHG Residents are excluded from NHG compliance, NHG numerator/denominator, surplus, period snapshots, and clawback. Do not join this table into native compliance queries.

**Non-NHG date-specific derivation:** `current_nhg_posting_code` is not an authorization source for Phase 5B event/ad-hoc derivation. Use the `external_resident_postings` row matching the selected event/ad-hoc date. If no row matches, return unavailable/no posting for selected date.

**Implementation-pending external option fields:** Current models/migrations do not contain `attended_posting_code`. For Phase 5B, attended department/programme selection should resolve to a real `posting_codes.code` through validated lookup/config and can remain request/audit context until a dedicated storage field is approved. Do not create posting codes by concatenating strings or regex.

---

## Table: `external_resident_postings`

Confirmed Phase 5B source for Non-NHG forecasted/date-specific posting derivation. Date-bounded rows are created during registration and editable by the Non-NHG Resident. They are used to derive posting for event listing and ad-hoc options by selected date.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| external_resident_id | UUID | FK → external_residents.id, NOT NULL | |
| programme_code | VARCHAR(20) | FK → programmes.code, nullable for legacy rows | Validated programme provenance for this date range. New registration, schedule-replacement, and compatibility writes always populate it. A null unresolved legacy value grants no Programme PC-event visibility. |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | Resolved posting code only after backend validation against `posting_codes` and configured mapping from selected institution/programme/department. No string-derived codes. |
| start_date | DATE | NOT NULL | |
| end_date | DATE | nullable | |
| is_current | BOOLEAN | DEFAULT true | |

**Phase 5B schedule rules:**
- Rows for the same `external_resident_id` must not overlap in date range. Enforce in service validation and preferably with a DB exclusion/constraint when migrations are added.
- Gaps are allowed. Event/ad-hoc options for a date in a gap return unavailable/no posting for selected date.
- Date ranges may cross calendar months.
- Registration/update UI collects configured institutions and programmes from the public mapping-options endpoint. Current TTSH configuration exposes only the 24 active Non-NHG registration choices; the four inactive TTSH mappings for `FM`, `PATH`, `SPORTSMED`, and `PALLMED` are omitted. Future KTPH/WH rows appear automatically from configuration. Each stored row retains both the validated `programme_code` and backend-resolved `posting_code`; institution remains request/configuration context rather than duplicated schedule state.
- A composite scope/date index on (`external_resident_id`, `posting_code`, `programme_code`, `start_date`, `end_date`) supports exact programme/posting authorization while retaining the existing resident/date lookup indexes.
- A migration may backfill a legacy row only when its posting resolves to exactly one programme through authoritative mapping data. It must leave ambiguous rows null rather than pick the first candidate; `TTSHGenMed` may represent AIM or IM, and `TTSHGenSrg` may represent GS or SIG. Unique cases such as `TTSHGerMed` may be backfilled to GERI when the authoritative mapping data proves that resolution. Unrelated residents, schedules, and attendance remain unchanged.
- For a date-matched schedule row, every normal scheduled Department Secretary or Programme PC event is eligible when its `posting_code` matches exactly. Teaching Name source programme, `created_for_programme_code`, and `posting_codes.supports_secretary_events` are not Non-NHG Resident visibility/submission gates. Another posting, an event outside the schedule dates, an ad-hoc event owned by another resident, or an already-submitted event remains ineligible.

---

## Table: `external_attendance_records`

One immutable row per Non-NHG Resident attendance submission cycle. Removed
cycles are retained and a later resubmission receives a new row. Storage stays
separate from native `attendance_records` so external attendance cannot enter
NHG compliance joins accidentally.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| external_resident_id | UUID | FK → external_residents.id, NOT NULL | |
| teaching_event_id | UUID | FK → teaching_events.id, NOT NULL | |
| submitted_at | TIMESTAMPTZ | DEFAULT now() | |
| status | VARCHAR(20) | DEFAULT 'submitted' | `submitted`, `flagged`, `removed` |
| posting_code | VARCHAR(50) | | Audit copy of event posting at submission time. Not used for NHG compliance. |

**Active uniqueness and history:** A submitted-only unique index on
`(external_resident_id, teaching_event_id)` prevents two active submissions
while preserving removed rows. The same immutable-history and no-resurrection
rules used for native attendance apply here. `status` is constrained to
`submitted`, `flagged`, or `removed`.

**Session type is NOT stored here.** External attendance can be viewed/exported for the resident's home-cluster PC, but it does not participate in NHG PTT compliance.

**Export status:** External attendance is recording/export-only and must be exportable to Excel for forwarding to NUH/SingHealth PCs before Phase 6 compliance. It must remain excluded from native compliance joins, native resident reports, surplus, snapshots, and clawback.

---

## Table: `surplus_ledger`

Pre-tag-reallocation derived audit state per resident, physical posting, session type, and reporting period. Written by the compliance engine at calculation time.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| surplus | NUMERIC | DEFAULT 0 | `max(cumulative raw eligible attendance - cumulative target_100, 0)` before tag reallocation; must preserve fractional target differences |
| is_hibernating | BOOLEAN | DEFAULT false | True when resident is not actively posted here |

**Unique constraint:** `UNIQUE(resident_id, posting_code, session_type_id, reporting_period_id)`.

**Critical lifecycle:** Recompute from raw eligible attendance and cumulative target, then replace the existing value idempotently; never increment it. The stored value is not carry-in attendance and must never be added back to raw attendance. Returning to a physical posting in the same period recomputes across all its phases, so expanded target can reduce the prior ledger value to zero. Mark the row hibernating when no active phase remains, unhibernate/recompute on return, reset at a reporting-period boundary, and preserve closed-period rows as historical evidence where supported. Tag reallocation is read-time only and never mutates this table.

---

## Table: `form_f1_records`

Per-resident per-calendar-month active/inactive status parsed from the FormF1 file. This is the primary denominator gate for compliance calculations.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| mcr | VARCHAR(20) | NOT NULL | The only resident identifier read from FormF1. Join key to residents.mcr |
| month_label | VARCHAR(10) | NOT NULL | e.g. `Jul-25`, `Aug-25` — calendar month |
| status_raw | VARCHAR(50) | NOT NULL | Raw value from FormF1; blank monthly cells persist as an empty string |
| is_active | BOOLEAN | NOT NULL | Derived: `Active` and `Extension` → true; `Inactive`, blank, `NULL`, and whitespace-only → false. |
| promotion_date | DATE | NULL | Parsed from FormF1 promotion date / senior promotion date column (current template column Y). Stored for future R3→R4/senior-promotion compliance handling only. Not used by compliance in this phase. |
| upload_id | UUID | FK → upload_logs.id | Which upload produced this record |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Unique constraint:** `UNIQUE(reporting_period_id, mcr, month_label)`

**Status normalisation:**
- `Active` → is_active = true
- `Extension` → is_active = true for ordinary compliance; any future financial treatment remains deferred
- `Inactive` → is_active = false (excluded from both numerator and denominator)
- blank/`NULL`/whitespace-only monthly cell → is_active = false (excluded from both numerator and denominator; the record is still persisted)

**Re-upload behaviour:** Full replace per `reporting_period_id` scope. Re-upload is allowed at any time (to handle unforeseen LOAs like maternity). Delete-and-reinsert within scope.

**FormF1 persistence scope (authoritative):**
- Persist only FormF1-derived fields: `mcr`, `month_label`, `status_raw`, `is_active`, `promotion_date`, and upload/reporting-period metadata (`reporting_period_id`, `upload_id`, timestamps).
- FormF1 identity/profile columns outside MCR are non-authoritative and must not overwrite resident identity/programme/r_year/posting data from RDB-backed tables.

**Note:** FormF1 is the final authoritative active/inactive source for compliance. It remains calendar-month keyed, but the resolved `academic_month_boundaries.month_label` selects the FormF1 row that gates both numerator and denominator for the entire AY bucket. Do not split/prorate a bucket or use an event's raw calendar month when it differs from the bucket label. RDB LOA/refresher/employed annotations are parser/audit/display data and are not used to derive active/inactive status.

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

## Table: `academic_month_boundaries`

Academic-calendar month boundary ranges parsed from the **AY Dates** sheet in the Academic Calendar / Public Holiday workbook. Used to bucket attendance/event dates into AY months for compliance calculations.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| academic_year_label | VARCHAR(20) | NOT NULL | e.g. `AY2026` |
| ay_date_category | VARCHAR(30) | NOT NULL, CHECK IN (`im_subspec`, `non_im_subspec`) | Category selected from `programmes.ay_date_category` |
| month_label | VARCHAR(10) | NOT NULL | e.g. `Jul-26`, `Aug-26` |
| start_date | DATE | NOT NULL | Inclusive |
| end_date | DATE | NOT NULL | Inclusive |
| upload_id | UUID | FK → upload_logs.id, NOT NULL | Upload log row from `POST /admin/upload/public-holidays` |
| created_at | TIMESTAMPTZ | DEFAULT now() | |
| updated_at | TIMESTAMPTZ | DEFAULT now() | |

**Check constraints:**
- `CHECK (ay_date_category IN ('im_subspec', 'non_im_subspec'))`
- `CHECK (start_date <= end_date)`

**Unique constraint:** `UNIQUE(academic_year_label, ay_date_category, month_label)`

The `month_label` is also the FormF1 lookup key for every attendance and denominator contribution in the inclusive date range. For example, if `Jul-26` ends on 3 August, 3 August still uses July FormF1; the next AY bucket uses August FormF1.

**Validation and safety rules (parser-level):**
- No overlapping ranges within the same `(academic_year_label, ay_date_category)`.
- Missing category tables or missing month ranges are treated as unsafe and fail the upload (422).
- Duplicate category tables with conflicting rows fail the upload (422).
- Exact duplicate category tables are accepted deterministically by keeping the first parsed table and ignoring subsequent exact duplicates with a warning.

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
| combined_label | VARCHAR(50) | FK → posting_codes.code, nullable | For `combine` type: the canonical existing combined posting code (e.g. `IMHGrPsyc & TTSHPsychi`) |
| main_posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | For `main_posting` type: the posting to collapse to when the rule is selected |
| exclusion_code | VARCHAR(50) | FK → posting_codes.code, nullable | For FM `main_posting` trigger-list rows: fallback posting when zero recognised trigger-list codes appear in the multi-posting cell. Usually `NHGPlyNHGPly`, but read from configuration and not hardcoded globally. |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Unique constraint:** `UNIQUE(programme_code, posting_code_1, posting_code_2, rule_type)`

**Rule type behaviour:**
- `combine`: Source postings resolve to one configured canonical combined posting code in `combined_label`. It must already exist in `posting_codes` and have corresponding TTF rows. Persist one `resident_postings` row using it; target lookup uses it and no component compliance results are created.
- `half_month`: Keep both source postings as separate `resident_postings` rows with their own codes, targets, and compliance identities. Set `active_months_weight = 0.5` on each and keep the uploaded TTF `monthly_target` unchanged; the factor is applied exactly once. Numerator sessions count fully. Separately configured posting groups may aggregate later.
- explicit two-code `main_posting`: Collapse the sources to one configured existing `main_posting_code`, which becomes the compliance identity. Do not create a combined identity.
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
3. Within each physical member posting and R-year context, apply the FormF1 status selected by each AY bucket label as the whole-bucket gate (no split or proration), calculate its own target, transfer raw tag counts only within that context, and cap it separately
4. Sum the already capped achievements and correctly weighted targets across all member contexts. Each posting's own `monthly_target` applies per phase: grouped `target_100 = sum(monthly_target_at_posting × active_months_weight_at_posting)`
5. Calculate the group/posting-level unrounded percentage as the canonical compliance predicate; expose `target_70 = ceil(target_100 × 0.70)` as the displayed whole-session target
6. If no group is found for a posting code → calculate independently (posting stands alone)

**Important clarification:** Column E / `group_code` does not replace the posting's own `monthly_target`. Each posting_code still contributes its own `monthly_target × months_at_posting`; grouping only changes the final posting-level aggregation identity.

Posting-group membership is not a reallocation boundary override. Tag transfers remain inside one physical posting and R-year context and may never cross between group members or R-year contexts.

**Seeding sources:**
- **TTF upload (primary):** The parser replaces the complete `posting_groups` set for the uploaded programme (including rows omitted or blank in column E), then upserts every non-empty TTF column E ("For Dashboard (RDB Posting/Subspeciality)") value as `group_code = column_E_value`, `posting_code = column_D_value`, `programme_code = from TTF`.
- **Admin CRUD (secondary):** Manual addition for groupings not captured by TTF column E. Every manual writer shares the same programme-level transaction advisory lock as TTF replacement and returns `409` on contention.

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

**Mutation logic (ORTHO):** Mutation and weekend acceptance are two ordered predicates. Only the exact original session type `NHG Orthopaedic Surgery Residency Teaching [3h]` is eligible for mutation. Preserve raw rows, subtract two hours from the original end time, project the compliance type to `National Didactics & Department Teaching [1h]`, then evaluate the Saturday 08:30–10:30 window against the adjusted interval. Sunday remains excluded and all other ORTHO session types remain unmutated.

**Confirmed seeded rows:**

| programme_code | posting_code | day_type | start_time_min | end_time_max | session_type_id | session_name_pattern | mutates_to | adjusted_duration |
|---|---|---|---|---|---|---|---|---|
| URO | NULL | sat | NULL | NULL | NULL | Urology National Teaching (Sat) | NULL | NULL |
| URO | NULL | sat | NULL | NULL | National Teaching [2h] | NULL | NULL | NULL |
| DERM | NULL | sat | NULL | NULL | NULL | NULL | NULL | NULL |
| ORTHO | NULL | sat | 08:30 | 10:30 | NHG Orthopaedic Surgery Residency Teaching [3h] | NULL | National Didactics & Department Teaching [1h] | 1.0 |

**Notes:**
- URO requires two rows — acceptance condition is an OR: session name `"Urology National Teaching (Sat)"` OR session type `"National Teaching [2h]"`. Two separate rows represent this OR logic.
- DERM accepts all Saturday sessions unconditionally — no time window, no session type filter.
- The ORTHO row's `session_type_id` is mandatory and names the exact original 3h type; it must not be replaced by a programme-wide wildcard. `adjusted_duration_hours = 1.0` represents the read-time two-hour end-time subtraction before the Saturday acceptance check.
- SIG, FM, ANAES, and all emergency posting codes have been removed from this list per confirmed PC update. The previous list from the R script was outdated.

**Admin CRUD UI:** All `weekend_exceptions` rows are manageable via admin CRUD UI. New entries can be added when additional programmes confirm weekend session policies.

---

## Table: `users`

For admin and secretary authentication **only**. Residents are **not** stored here — they authenticate directly against the `residents` table using their MCR number.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| email | VARCHAR(100) | UNIQUE, NOT NULL | |
| supabase_user_id | UUID | UNIQUE, nullable | Supabase Auth `auth.users.id` / access-token `sub` mapping for staff accounts in `AUTH_MODE=supabase`. Nullable so local stub/demo accounts and not-yet-provisioned staff rows remain valid. |
| password_hash | VARCHAR(255) | NOT NULL | Stubbed in Phase 1 |
| role | VARCHAR(20) | NOT NULL | `admin`, `secretary` — never `resident` |
| name | VARCHAR(100) | NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | Secretary's assigned site. NULL for admin. |
| programme_scope | TEXT[] | | Array of programme codes e.g. `{DR,GRM}`. Scopes the admin to specific programmes. NULL = no access (not all-access). |
| admin_level | VARCHAR(20) | NOT NULL DEFAULT `programme`, CHECK IN (`programme`, `master`) | Explicit admin level marker. Master admin access is `role = admin` and `admin_level = master`; never infer it from `programme_scope = NULL`. |
| is_active | BOOLEAN | DEFAULT true | |
| current_staff_actor_name | TEXT | nullable | Self-declared current human using this shared staff role account. Audit/display metadata only; never an authorization source. |
| staff_actor_name_updated_at | TIMESTAMPTZ | nullable | Last time the saved staff actor name was changed. |
| staff_actor_name_updated_by_user_id | UUID | FK -> users.id, nullable | Staff account that last updated the saved actor name. Usually the same role account. |
| session_generation | BIGINT | NOT NULL, DEFAULT 0, CHECK >= 0 | Subject-wide application-session invalidation generation |
| session_issuance_blocked | BOOLEAN | NOT NULL, DEFAULT false | Fail-closed staff login/session-creation fence during password reset |

**Secretary provisioning:** At launch, one account per TTSH posting code (e.g. TTSHAnaes, TTSHGerMed, TTSHCardio). Architecture is flexible — when other institutions onboard, provision new secretary accounts scoped to their posting codes (e.g. KTPHAnaes, SGHGerMed) with no schema change required.

**Admin/PC provisioning:** Account count is flexible. `programme_scope TEXT[]` supports multiple programmes per account, allowing PCs who manage several programmes to use a single login.

**5B-E role-account note:** Staff accounts are generic pass-down role accounts. `users.name` remains the generic account display name (for example `Programme PC - DR`), while `current_staff_actor_name` stores the current human's self-declared name for audit context. Password reset/handover clears the saved actor name. Master Admin is explicit via `admin_level = 'master'`; Programme PC access requires `admin_level = 'programme'` and non-empty `programme_scope`; Secretary access requires `posting_code`.

**Self authorization mutation ordering:** A self role/admin-level/scope/posting/deactivation change is allowed when the last-active-Master-Admin guard permits it. The service writes an audit of the planned final state before mutating `users`, then performs subject-wide generation/session invalidation as the final protected statement in the same transaction. The self-change audit marks `revoked_session_count` as null/non-exact because the invalidated signed context cannot perform a follow-up count read; non-self changes continue to record the exact count.

---

## Table: `app_sessions`

Backend-owned opaque browser-session state added by migration `20260722_000023`. `subject_id` is deliberately polymorphic and has no database foreign key; the session service validates it against the table selected by `subject_type`. Raw session and CSRF tokens are never stored.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| token_digest | BYTEA(32) | UNIQUE, NOT NULL, exact 32-byte check | Keyed digest only |
| subject_type | VARCHAR(30) | NOT NULL, CHECK | `staff`, `resident`, or `external_resident` |
| subject_id | UUID | NOT NULL | Logical identity reference |
| subject_session_generation | BIGINT | NOT NULL, CHECK >= 0 | Generation snapshot at issuance |
| session_family_id | UUID | NOT NULL | Root identifier for the rotation/device family |
| auth_source | VARCHAR(30) | NOT NULL, CHECK | `supabase_staff` or `mata_resident`, constrained to subject type |
| csrf_token_digest | BYTEA(32) | NOT NULL, exact 32-byte check | Keyed digest only |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Session-child creation time |
| last_seen_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Last qualifying successful protected mutation recorded after the configured touch interval |
| idle_expires_at | TIMESTAMPTZ | NOT NULL, <= absolute expiry | Sliding idle bound |
| absolute_expires_at | TIMESTAMPTZ | NOT NULL | Preserved across rotation |
| revoked_at | TIMESTAMPTZ | nullable | |
| revoked_reason | TEXT | nullable | |
| rotated_from_session_id | UUID | nullable, UNIQUE | At most one child per parent |
| user_agent_hash | BYTEA(32) | nullable, exact 32-byte check | Optional keyed digest; no raw user agent |

Root rows satisfy `session_family_id = id`; child rows have `rotated_from_session_id`. Rotation locks in global order: subject row, transaction-scoped family advisory lock, then fresh `SELECT ... FOR UPDATE` session reload. Under the H-E restricted-role path, `app_sessions` has no direct runtime table privilege and reviewed `mata_rls` helpers perform the authoritative fresh database lookup. The non-RLS ORM fallback retains `populate_existing=True`, so an existing SQLAlchemy identity-map object cannot bypass the locked row. Transaction-scoped advisory locks disappear on commit, rollback, cancellation, or connection loss, so pooled connections cannot retain them.

The effective expiry is `min(idle_expires_at, absolute_expires_at)`, and
equality is invalid. Touch uses PostgreSQL time, is interval-gated, and caps
idle expiry at the immutable family absolute deadline. Rotation initializes a
new row but preserves or tightens the parent's idle deadline as well as the
family absolute deadline and carries forward `last_seen_at`; refresh is not an
idle-expiry extension and cannot postpone eligibility for a later qualifying
touch. Revision `20260727_000027` makes restricted lifecycle helpers return
minimum identity/context material rather than full rows; stored token/CSRF
digests, expiry fields, and derived client lifetimes remain private. The HTTP
layer issues an intentional browser-session cookie with no `Max-Age` or
`Expires`; signed RLS context ceases to validate when the backing session is
revoked or reaches either deadline.

Logout does not hydrate a session through this table. The auth-only
`revoke_app_session_family_for_logout(bytea,bytea,text)` helper accepts keyed
token and CSRF digests and derives the subject/family from the matching row.
Active proof must be before both deadlines. A parent revoked specifically as
`rotated` remains termination-only proof until the immutable family absolute
deadline even when its superseded idle deadline has passed. The helper grants
no identity/context/refresh authority and lets a logout that started first
revoke a child when refresh commits first.

Cleanup preserves a `rotated` parent as termination proof until
`absolute_expires_at`, regardless of its superseded idle deadline or a shorter
retention interval. Once that immutable family absolute deadline is reached,
normal bounded retention rules apply. An unrevoked child with both deadlines
still in the future is never selected by that proof-row exception.

---

## Table: `rate_limit_buckets`

Persistent atomic fixed-window counters added by migration `20260709_000016`.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| scope | TEXT | NOT NULL | Route/policy group |
| key_hash | TEXT | NOT NULL | HMAC-SHA256 hex digest; never a raw identifier |
| window_start | TIMESTAMPTZ | NOT NULL | Fixed-window boundary |
| window_seconds | INTEGER | NOT NULL, CHECK > 0 | |
| request_count | INTEGER | NOT NULL, CHECK >= 1 | |
| expires_at | TIMESTAMPTZ | NOT NULL | Cleanup boundary |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

The unique constraint is `(scope, key_hash, window_start, window_seconds)`. Atomic `INSERT ... ON CONFLICT DO UPDATE` prevents concurrent lost updates. This table is helper-only under H-E: `mata_app_runtime` and `mata_auth_internal` have no direct table privilege, and the reviewed `mata_rls.consume_rate_limit` function is the only application access path.

---

## Table: `audit_logs`

Append-only application audit events for staff and administrative workflows.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, DEFAULT `gen_random_uuid()` | |
| actor_user_id | UUID | FK → users.id, nullable | Current database-owned staff subject where available |
| actor_role | VARCHAR(30) | NOT NULL | |
| actor_name | VARCHAR(120) | NOT NULL | Audit/display value, never an authorization source |
| actor_site | VARCHAR(50) | nullable | |
| actor_programme | VARCHAR(50) | nullable | |
| actor_admin_level | VARCHAR(30) | nullable | |
| action | VARCHAR(80) | NOT NULL | Stable action identifier |
| entity_type | VARCHAR(80) | NOT NULL | Stable entity family |
| entity_id | TEXT | nullable | UUID text or another stable application identifier, such as a programme code |
| before_json | JSONB | nullable | Sanitized pre-mutation snapshot |
| after_json | JSONB | nullable | Sanitized post-mutation snapshot |
| metadata_json | JSONB | nullable | Sanitized action metadata |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

Migration `20260726_000025` changes `entity_id` from UUID to text so audited configuration entities with non-UUID stable keys can use the same append path. Its downgrade checks every populated value before removing H-E helpers and fails without partial downgrade if any value cannot be losslessly restored to UUID. Under H-E, normal runtime reads are RLS-scoped and writes use the reviewed `mata_rls.append_audit_log` helper.

---

## Table: `upload_logs`

Persistent audit trail of every RDB, TTF, FormF1, and Academic Calendar / Public Holidays upload.

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
  "targets_inserted": 4,
  "targets_updated": 17,
  "targets_removed": 2,
  "targets_unchanged": 6,
  "mappings_preserved": 11,
  "mappings_invalidated": 2,
  "mappings_with_target_semantics_changed": 3,
  "pending_mappings_created": 4,
  "affected_event_count": 3,
  "affected_attendance_count": 7,
  "session_types_upserted": 5,
  "posting_codes_added": ["AICAIC", "DPPallia"],
  "posting_groups_upserted": 5,
  "posting_groups_removed": 2,
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
  "skipped_mcr_warnings": ["row 41: blank MCR"],
  "duplicate_mcr_errors": [],
  "month_labels_parsed": ["Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25", "Dec-25"],
  "active_count": 280,
  "inactive_count": 32,
  "promotion_dates_parsed": 74,
  "promotion_date_warnings": ["M12345A: unparseable promotion date text"],
  "errors": []
}
```

**`summary` JSONB shape for Academic Calendar / Public Holidays uploads:**
```json
{
  "public_holidays_created": 11,
  "academic_month_boundaries_created": 24,
  "ay_categories_parsed": ["im_subspec", "non_im_subspec"],
  "academic_year_label": "AY2026",
  "ignored_sheets": ["Fr RMT"],
  "warnings": [],
  "errors": []
}
```

---

## Table: `warning_issues`

Durable issue-level records for upload warnings derived from `upload_logs.summary`.
One issue represents one deterministic warning fingerprint across uploads.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| fingerprint | TEXT | UNIQUE, NOT NULL | Deterministic key derived from warning type and stable scope fields |
| warning_type | VARCHAR(100) | NOT NULL | e.g. `unmatched_multi_posting`, `empty_posting_cell`, `mcr_not_found` |
| severity | VARCHAR(20) | NOT NULL | `critical`, `warning`, `info` |
| status | VARCHAR(20) | NOT NULL | `unresolved`, `resolved`, `dismissed`, `superseded`, `reappeared` |
| first_seen_upload_log_id | UUID | FK -> upload_logs.id | First upload where this issue appeared |
| last_seen_upload_log_id | UUID | FK -> upload_logs.id | Most recent upload where this issue appeared |
| first_seen_at | TIMESTAMPTZ | | Copied from upload time |
| last_seen_at | TIMESTAMPTZ | | Copied from latest upload time |
| reporting_period_id | UUID | FK -> reporting_periods.id, nullable | Warning scope when available |
| programme_code | VARCHAR(20) | nullable | Used for admin programme scoping |
| resident_id | UUID | FK -> residents.id, nullable | Populated only when a warning can be tied to a resident row |
| mcr | VARCHAR(20) | nullable | MCR from upload warning payload |
| month_label | VARCHAR(20) | nullable | Month/phase label when available |
| resolution_note | TEXT | nullable | Admin note from resolve/dismiss/supersede action |
| resolution_source_type | VARCHAR(50) | nullable | e.g. `admin_warning_action` |
| resolution_source_id | UUID | nullable | Actor/action source identifier |
| resolved_by | UUID | FK -> users.id, nullable | Staff actor user id |
| resolved_at | TIMESTAMPTZ | nullable | Status action timestamp |
| created_at | TIMESTAMPTZ | DEFAULT now() | |
| updated_at | TIMESTAMPTZ | DEFAULT now() | |

**Indexes:** `status`, `warning_type`, `(reporting_period_id, programme_code)`.

**Lifecycle:** New fingerprints create `unresolved` issues. If the same fingerprint appears again, `last_seen_*` fields are updated. If the prior status was `resolved`, `dismissed`, or `superseded`, the status becomes `reappeared` and the prior resolution metadata is preserved.

---

## Table: `upload_warnings`

Occurrence-level records for a warning issue within a specific upload.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| issue_id | UUID | FK -> warning_issues.id, NOT NULL | Durable issue this occurrence belongs to |
| upload_log_id | UUID | FK -> upload_logs.id, NOT NULL | Upload that produced the occurrence |
| warning_type | VARCHAR(100) | NOT NULL | Normalized warning type |
| severity | VARCHAR(20) | NOT NULL | `critical`, `warning`, `info` |
| reporting_period_id | UUID | FK -> reporting_periods.id, nullable | Warning scope when available |
| programme_code | VARCHAR(20) | nullable | Used for admin programme scoping |
| resident_id | UUID | FK -> residents.id, nullable | Populated only when known |
| mcr | VARCHAR(20) | nullable | |
| resident_name | VARCHAR(200) | nullable | |
| month_label | VARCHAR(20) | nullable | |
| sheet_name | VARCHAR(200) | nullable | Workbook trace |
| row_number | INTEGER | nullable | Workbook trace |
| cell_ref | VARCHAR(20) | nullable | Workbook trace |
| source_table | VARCHAR(100) | nullable | Future source-cell/action linking |
| source_record_id | UUID | nullable | Future source-cell/action linking |
| source_payload | JSONB | NOT NULL, DEFAULT `{}` | Original normalized warning payload |
| message | TEXT | NOT NULL | User-facing warning text |
| suggested_action | TEXT | nullable | Operational hint only |
| fingerprint | TEXT | NOT NULL | Same key as the parent issue |
| created_at | TIMESTAMPTZ | DEFAULT now() | |

**Unique constraint:** `UNIQUE(upload_log_id, fingerprint)`.

**Indexes:** `upload_log_id`, `issue_id`, `warning_type`, `(reporting_period_id, programme_code)`, `mcr`.

`upload_warnings` is append-only by upload occurrence. It does not mutate `upload_logs.summary`; historical upload summaries remain the immutable raw audit record.

---

## Table: `period_snapshots`

Frozen compliance state captured by the future final close/freeze flow.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| programme_code | VARCHAR(20) | NOT NULL | One snapshot per (period, programme) |
| snapshot_data | JSONB | NOT NULL | Full compliance state at future final close/freeze |
| generated_at | TIMESTAMPTZ | DEFAULT now() | |
| generated_by | UUID | FK → users.id | Admin who triggered future final close/freeze |

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
          "target_100": 21,
          "target_70": 15,
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

## Table: `clawback_records` — DEFERRED

No implementation-ready persistence contract is confirmed for clawback. Do not infer final fields, constraints, row identities, suppression values, or generation behavior from earlier drafts or legacy exports. Norm-rate persistence/effective dating, funding R-year, financial programme classification, Extension/R7/SAF/SCDF precedence, grouped-posting identity, billing attribution, missing-rate behavior, precision/rounding, and final-close transaction/rerun behavior all remain deferred. Any existing code or migration with this name must be audited against future confirmed decisions before use.

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
For a source-backed scheduled event, `global_session_type_id` is the global
evidence and takes priority over an ordinary Teaching Name mapping. It is
excluded from numerator and denominator in the future compliance engine.
Both-null legacy rows remain auditable persisted evidence; no global identity
is inferred from `teaching_event.teaching_name` text.

**How it interacts with secretary event creation:**
The catalogue-keyword dropdown is pre-Phase-F history only. Current
secretary/PC source-option endpoints return active `teaching_names` identities
and active global identities, not catalogue-name choices. A global event carries
`global_session_type_id` and its configured scheduling duration. Phase G uses
that explicit global identity in Resident/Non-NHG discovery and attendance
without a catalogue fallback.

**How it interacts with resident event visibility:**
Visibility follows the same rule as all other events. A global session type does not bypass source eligibility: NHG Residents only see secretary-created events from their assigned/current posting or their explicit native-programme TTSH department posting mapping, plus PC-created events for their native programme. A Department Meeting created by TTSHGerMed secretary is visible only to residents for whom TTSHGerMed is an allowed source.

**Admin CRUD UI:** Managed alongside `loa_types`, `weekend_exceptions`, `multi_posting_rules`, `posting_groups` in the admin configuration panel. Same access level, same UI pattern.

---

## Browser/Data API Privilege Boundary

Migration `20260722_000024` revokes all existing table, sequence, and function privileges in `public` from `PUBLIC` and, when present, Supabase browser roles `anon` and `authenticated`. It also revokes corresponding default privileges for future objects created by the migration owner. Its downgrade intentionally does not recreate unknowable broad grants.

Migrations `20260726_000025` and `20260726_000026` add the separate full-RLS layer. The capability groups `mata_app_runtime` and `mata_auth_internal` are `NOLOGIN`, `NOINHERIT`, non-owner, `NOSUPERUSER`, and `NOBYPASSRLS`; credentialed runtime, auth-helper, and migration/ownership logins must be distinct. H-E enables RLS on all 34 application tables, installs 84 policies targeted only to `mata_app_runtime`, and keeps all application tables without `FORCE ROW LEVEL SECURITY` because normal application traffic is required to use a non-owner role.

Before creating the H-E helper foundation, revision `20260726_000025`
normalizes Supabase's standard `extensions`-schema `pgcrypto` installation to
the repository's reviewed `public` namespace. The operation is transactional
and fail-closed: only `public` and `extensions` are supported, the migration
user must own the extension, relocation must be supported when required, and
the exact `digest`, `hmac`, `gen_random_bytes`, and `gen_random_uuid`
C-language extension members are verified before and after normalization.
Existing object identities and dependent defaults remain attached to the
extension; no replacement wrapper or search-path fallback is introduced.
Execution is revoked from `PUBLIC`, application capabilities, and optional
Supabase browser/service roles for every `pgcrypto` member routine before the
four-function dependency contract is retained. Only `public.gen_random_uuid()`
is granted directly to `mata_app_runtime`; the other reviewed functions remain
available only through the narrowly owned helper boundaries that require them.

The approved revision-`20260721_000022` Supabase baseline also has RLS already
enabled on `users`, while the original disposable-local inventory counted only
14 pre-existing RLS tables. Revision `20260726_000026` enables `users` RLS
idempotently before its exact preflight and then requires 15 pre-existing plus
19 newly protected tables. `users` is treated as pre-existing hardening, so
the revision's downgrade removes its own policies and grants but does not
disable `users` RLS. The `pgcrypto` namespace normalization is likewise not
reversed by downgrade.

Production `SYNC_DATABASE_URL` uses the packaged synchronous driver through
`postgresql://` or `postgresql+psycopg2://`. The unbundled psycopg 3 form
`postgresql+psycopg://` is rejected during settings validation.

Normal runtime access is explicit: 27 tables receive reviewed table actions, `users` additionally receives `INSERT`/`UPDATE` and column-limited `SELECT` that excludes `password_hash`, and six tables remain helper-only with no direct runtime table privilege: `app_sessions`, `clawback_records`, `period_snapshots`, `programme_institution_posting_map`, `rate_limit_buckets`, and `surplus_ledger`. `mata_auth_internal` has no direct application-table or sequence privileges.

`PUBLIC` and optional `anon`, `authenticated`, and `service_role` roles receive no application relation, H-E helper, or schema-creation authority. Default privileges do not grant future tables, sequences, or functions to runtime, auth, browser, or PUBLIC roles. A future application table is therefore inaccessible by default and still requires explicit RLS, policy, grant, helper, ownership, and test review.

Revision `20260727_000027` preserves the 34-table/84-policy posture and changes
only session helper functions/grants plus signed-context validation. The
superseded full-row resolve/issue/rotate functions are no longer executable by
either restricted application capability.

That revision owns exactly eight minimal lifecycle helpers: three auth-only
issuance wrappers; shared resolve, touch, and CSRF helpers; one runtime-only
rotation helper; and one auth-only logout termination helper. Runtime cannot
execute `revoke_app_session_family_for_logout(bytea,bytea,text)`.

Revision `20260728_000028` creates the dedicated
`mata_adhoc_attendance_definer` role for its narrow atomic helper. On
PostgreSQL 16, a hosted Supabase migration owner that is a non-superuser with
`CREATEROLE` automatically receives a `pg_auth_members` creator edge for a
role it creates. The accepted catalogue is therefore either zero edges or
exactly one row in which the definer is the granted role, the member is the
`mata_rls` schema owner with `CREATEROLE` and `BYPASSRLS`, the grantor is a
superuser, `admin_option` is true, and `inherit_option` and `set_option` are
false. An outgoing definer membership, an additional or foreign member, a
non-superuser grantor, or any edge with `inherit_option` or `set_option` is
forbidden. Migration and startup attestations enforce the same bounded
alternative.

These statements describe the local source and disposable-PostgreSQL implementation. They do not establish the revision, role catalogue, grants, policies, or behavior of a deployed Supabase project.

Resident identity assurance remains separately governed product debt. Do not
invent a second factor or claim workflow outside an approved product scope.

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

CREATE INDEX idx_posting_codes_supports_secretary_events
ON posting_codes(supports_secretary_events);
```

#### `programme_institution_posting_map`

```sql
-- UNIQUE(programme_code, institution_code) covers exact resolver lookup.
CREATE INDEX idx_programme_institution_posting_map_institution_status
ON programme_institution_posting_map(institution_code, status);

CREATE INDEX idx_programme_institution_posting_map_programme_status
ON programme_institution_posting_map(programme_code, status);

CREATE INDEX idx_programme_institution_posting_map_posting
ON programme_institution_posting_map(posting_code)
WHERE posting_code IS NOT NULL;
```

#### `reporting_periods`

```sql
-- Fast lookup of the active/effectively active period.
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

#### `teaching_name_catalogue` (historical, removed by E2+B2)

```sql
-- Critical compliance/event-visibility lookup.
CREATE INDEX idx_teaching_name_catalogue_resolution
ON teaching_name_catalogue(reporting_period_id, programme_code, posting_code, r_year, keyword);

CREATE INDEX idx_teaching_name_catalogue_session_type
ON teaching_name_catalogue(session_type_id);

CREATE INDEX idx_teaching_name_catalogue_tracked
ON teaching_name_catalogue(reporting_period_id, programme_code, posting_code, r_year, is_tracked);
```

#### `teaching_names` and `teaching_name_mappings`

```sql
CREATE INDEX idx_teaching_names_active_pool
ON teaching_names(reporting_period_id, programme_code, display_name)
WHERE is_active = true;

CREATE INDEX idx_teaching_names_normalized_lookup
ON teaching_names(reporting_period_id, programme_code, normalized_name);

CREATE INDEX idx_teaching_name_mappings_pending_scope
ON teaching_name_mappings(reporting_period_id, programme_code, posting_code, r_year)
WHERE teaching_target_id IS NULL;

CREATE INDEX idx_teaching_name_mappings_mapped_scope
ON teaching_name_mappings(reporting_period_id, programme_code, posting_code, r_year, teaching_target_id)
WHERE teaching_target_id IS NOT NULL;
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

CREATE INDEX idx_teaching_events_programme_date
ON teaching_events(created_for_programme_code, event_date)
WHERE created_for_programme_code IS NOT NULL;

CREATE INDEX idx_teaching_events_teaching_name
ON teaching_events(teaching_name_id)
WHERE teaching_name_id IS NOT NULL;

CREATE INDEX idx_teaching_events_global_session_type
ON teaching_events(global_session_type_id)
WHERE global_session_type_id IS NOT NULL;

CREATE INDEX idx_teaching_events_source_scope
ON teaching_events(source_reporting_period_id, source_programme_code)
WHERE source_reporting_period_id IS NOT NULL;
```

#### `event_series`

```sql
CREATE INDEX idx_event_series_posting
ON event_series(posting_code);
```

#### `attendance_records`

```sql
-- The submitted-only unique index prevents duplicate active submissions while
-- preserving removed history.
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


#### `external_residents`

```sql
CREATE UNIQUE INDEX idx_external_residents_mcr
ON external_residents(mcr);

CREATE INDEX idx_external_residents_current_posting
ON external_residents(current_nhg_posting_code, status);

CREATE INDEX idx_external_residents_home_cluster
ON external_residents(home_cluster);
```

#### `external_resident_postings`

```sql
CREATE INDEX idx_external_resident_postings_external_current
ON external_resident_postings(external_resident_id, is_current);

CREATE INDEX idx_external_resident_postings_external_dates
ON external_resident_postings(external_resident_id, start_date, end_date);

CREATE INDEX idx_external_resident_postings_external_scope_dates
ON external_resident_postings(
    external_resident_id,
    posting_code,
    programme_code,
    start_date,
    end_date
);
```

#### `external_attendance_records`

```sql
CREATE INDEX idx_external_attendance_external_status
ON external_attendance_records(external_resident_id, status);

CREATE INDEX idx_external_attendance_event_status
ON external_attendance_records(teaching_event_id, status);

CREATE UNIQUE INDEX idx_external_attendance_submitted_external_event
ON external_attendance_records(external_resident_id, teaching_event_id)
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

#### `academic_month_boundaries`

```sql
CREATE INDEX idx_academic_month_boundaries_lookup
ON academic_month_boundaries(academic_year_label, ay_date_category, start_date, end_date);

CREATE INDEX idx_academic_month_boundaries_upload
ON academic_month_boundaries(upload_id);
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

#### `app_sessions`

```sql
CREATE INDEX idx_app_sessions_active_expiry
ON app_sessions(revoked_at, idle_expires_at, absolute_expires_at);

CREATE INDEX idx_app_sessions_subject
ON app_sessions(subject_type, subject_id);

CREATE INDEX idx_app_sessions_family_revoked
ON app_sessions(session_family_id, revoked_at);

CREATE INDEX idx_app_sessions_revoked_at
ON app_sessions(revoked_at);

CREATE INDEX idx_app_sessions_absolute_expires_at
ON app_sessions(absolute_expires_at);

CREATE INDEX idx_app_sessions_idle_expires_at
ON app_sessions(idle_expires_at);
```

#### `rate_limit_buckets`

```sql
CREATE INDEX idx_rate_limit_buckets_scope_key_window
ON rate_limit_buckets(scope, key_hash, window_start);

CREATE INDEX idx_rate_limit_buckets_expires_at
ON rate_limit_buckets(expires_at);
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

#### `clawback_records` — DEFERRED

No final index contract is documented until the clawback row identity and fields are confirmed.

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
- deferred compliance source/mapping resolution by `(source identity, reporting_period_id, programme_code, posting_code, r_year)`
- admin report batch query by `(reporting_period_id, programme_code)`
- upload log browsing by `upload_type`, `reporting_period_id`, `programme_code`, `created_at`

---
