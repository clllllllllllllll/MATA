# Database Schema

All tables use UUID primary keys (`id UUID DEFAULT gen_random_uuid()`), `created_at TIMESTAMPTZ DEFAULT now()`, and `updated_at TIMESTAMPTZ DEFAULT now()` unless noted otherwise.

## Entity Relationship Summary

```
programmes ─1:N─ teaching_targets
programmes ─1:N─ residents (via programme_code)

posting_codes ─1:N─ resident_postings
posting_codes ─1:N─ teaching_targets
posting_codes ─1:N─ teaching_events

residents ─1:N─ resident_postings
residents ─1:N─ attendance_records
residents ─1:N─ surplus_ledger

teaching_events ─1:N─ attendance_records
teaching_events ─N:1─ event_series (nullable)

session_types ─1:N─ teaching_targets
session_types ─1:N─ teaching_events (display only)

reporting_periods ─1:N─ teaching_targets
reporting_periods ─1:N─ resident_postings
reporting_periods ─1:N─ period_snapshots

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
| compliance_variant | VARCHAR(20) | DEFAULT 'standard' | `standard` or `fm`. Controls which compliance calculation path is used. See `docs/business-logic.md` § BL-FM for FM-specific rules. |

Seeded from RDB "Specialization" column. Programme code derived from abbreviation lookup table.

**Important:** Do NOT apply standard compliance logic to FM without first reading `docs/business-logic.md` § BL-FM. FM has confirmed special arrangements that differ structurally from other programmes. Set `compliance_variant = 'fm'` for the FM programme row at seed time.

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
| billing_dept | VARCHAR(50) | | For clawback (Phase 2) |
| is_emergency | BOOLEAN | DEFAULT false | Emergency postings accept weekend teachings |

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
| r_year | VARCHAR(10) | | Current year: `R1`..`R7` |
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
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable  | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| start_date | DATE | NOT NULL | Phase start date from RDB column header |
| end_date | DATE | NOT NULL | Phase end date from RDB column header |
| month_label | VARCHAR(10) | | e.g. `Jul-25`, `Aug-25` |
| r_year | VARCHAR(10) | NOT NULL | Residency year at this phase, e.g. `R3`. Copied from RDB column F at parse time. Used for teaching_target lookup — do NOT use residents.r_year for compliance, as a resident may cross a year boundary mid-period. |
| status | VARCHAR(20) | DEFAULT 'active' | `active`, `loa`, `loa_working`, `employed ` |
| loa_type | VARCHAR(50) | | e.g. `Maternity Leave`, `Annual Leaves`, `No-Pay-Leave` |
| loa_start_date | DATE | | Parsed from LOA annotation |
| loa_end_date | DATE | | Parsed from LOA annotation |
| refresher_training_type | VARCHAR(50) | | `add to Max Cand` or `don't add to Max Cand` |
| refresher_training_start | DATE | | Parsed from Refresher Training annotation |
| refresher_training_end | DATE | | Parsed from Refresher Training annotation |

**Unique constraint:** `UNIQUE(resident_id, reporting_period_id, start_date)`

**RDB re-upload behaviour:** On re-upload, existing `resident_postings` rows for the period are deleted and re-inserted (delete-first within scope, not blind insert). This prevents duplicate-key errors and ensures corrections take effect cleanly. The scope for deletion is `(reporting_period_id)` across all residents found in the uploaded file. Residents not present in the new upload are left untouched.

**Cell parsing rules:**
- Simple posting: `TTSHAnaes` → status = `active`, posting_code = `TTSHAnaes`
- Empty cell: → skip, no row created
- Pure LOA: `LOA (Maternity Leave from DD-MMM-YYYY to DD-MMM-YYYY)` → status = `loa`, posting_code = NULL, loa fields populated
- Hybrid LOA (Continue working): `TTSHAnaes (Continue working during LOA from ...)` → status = `loa_working`, posting_code = `TTSHAnaes`, loa fields populated
- Multiline LOA: `TTSHGenMed\nLOA (Maternity Leave from ...)` → same as loa_working
- Refresher Training: `TTSHAnaes (Refresher Training (add to Max Cand) from ...)` → status = `active`, posting_code = `TTSHAnaes`, refresher fields populated
- Employed: `SAF-Employed` / `KTPH-Employed` etc. → status = `employed`, posting_code = NULL, employer_tag set on residents table, no resident_postings row created

**Note on Employed cells:** XXX-Employed cells do not produce a resident_postings row. The employer_tag is set directly on the residents table on first encounter.

---

## Table: `session_types`

Catalogue of all session types. Seeded from TTF upload.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| name | VARCHAR(100) | UNIQUE, NOT NULL | e.g. `Department/Programme Teaching [1h]` |
| duration_hours | DECIMAL(4,2) | NOT NULL | Extracted from name: `[1h]` → 1.0, `[0.75h]` → 0.75 |
| duration_label | VARCHAR(10) | | `[1h]`, `[2h]`, `[0.75h]`, `[3h]` etc. |

**Note:** Duration is stored for reallocation flow direction only. Compliance counts sessions, never multiplies by duration.

---

## Table: `teaching_targets`

One row per (reporting_period, programme, residency_year, posting_code, session_type). The core compliance reference.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| programme_code | VARCHAR(20) | FK → programmes.code, NOT NULL | |
| r_year | VARCHAR(10) | NOT NULL | `R1`..`R7` (multi-year rows exploded) |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| monthly_target | INTEGER | NOT NULL | Frequency target (100%) from TTF column G |
| is_tracked | BOOLEAN | NOT NULL | Only tracked sessions feed compliance |
| is_reallocatable | BOOLEAN | DEFAULT false | Column I "Y" → true |
| tag | VARCHAR(10) | | Reallocation group label, e.g. `A`, `B` |
| details_of_training | TEXT | | **TBD-1:** Comma-separated keywords from STP. Pending PM confirmation. |

**Unique constraint:** `UNIQUE(reporting_period_id, programme_code, r_year, posting_code, session_type_id)`

**Upload behaviour:** Full replace within `(reporting_period_id, programme_code)` scope. Mid-period corrections via admin CRUD UI.

---

## Table: `teaching_events`

Secretary-created teaching events. Shared across all residents at that posting site.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | Resolved at creation from the secretary's native programme TTF. **Display/prototype only** — does NOT drive compliance. |
| teaching_name | VARCHAR(200) | NOT NULL | Secretary-selected name from dropdown (Details of Training keyword) |
| event_date | DATE | NOT NULL | |
| start_time | TIME | NOT NULL | |
| end_time | TIME | NOT NULL | |
| duration_hours | DECIMAL(4,2) | NOT NULL | |
| cme_points_awarded | BOOLEAN | DEFAULT false | Informational only |
| smc_event_code | VARCHAR(50) | | Informational only |
| series_id | UUID | FK → event_series.id, nullable | NULL for standalone events |
| created_by | UUID | NOT NULL | Secretary user ID |
| creation_date | TIMESTAMPTZ | DEFAULT now() | |

**Deletion rule:** Cannot delete if any attendance_record references this event.

**Session type resolution — two layers:**
- **At event creation (secretary):** `session_type_id` is resolved from the **secretary's native programme TTF** using `teaching_name` as the primary key and `duration_hours` as a tiebreaker when `teaching_name` alone matches multiple session types at the same posting. Stored on the event for display in the secretary's Teaching Type column. Prototype/stakeholder validation only.
- **At attendance submission (per resident):** Session type is re-resolved independently per resident using their own native programme TTF (`posting_code + teaching_name → teaching_targets WHERE programme_code = resident.programme_code`), with `duration_hours` as tiebreaker for edge cases. This is the authoritative resolution for compliance. The same event may map to **different session types for residents of different programmes** — a GRM resident and an Anaes resident attending the same event will have their attendance counted under different session types according to their respective TTFs. The `session_type_id` stored on the event is never used for compliance calculations.

---

## Table: `event_series`

Recurrence metadata for repeating teaching events.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| recurrence_pattern | VARCHAR(20) | NOT NULL | `daily`, `weekly`, `monthly` |
| recurrence_interval | INTEGER | DEFAULT 1 | Every N days/weeks/months |
| days_of_week | VARCHAR(20) | | Comma-separated: `mon,wed,fri` |
| end_type | VARCHAR(20) | NOT NULL | `by_date`, `after_count`, `no_end` |
| end_date | DATE | | For `by_date` |
| end_after_count | INTEGER | | For `after_count` |
| template_teaching_name | VARCHAR(200) | | |
| template_start_time | TIME | | |
| template_end_time | TIME | | |
| template_duration_hours | DECIMAL(4,2) | | |
| created_by | UUID | NOT NULL | |

Individual occurrences are materialized as rows in `teaching_events` with `series_id` pointing back here.

---

## Table: `attendance_records`

One row per (resident, event) submission.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| teaching_event_id | UUID | FK → teaching_events.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | Resident's posting at time of submission — **audit/display only**. Compliance joins must use `teaching_events.posting_code`, not this column. If an admin re-uploads the RDB and corrects a posting, this column will reflect the old value; the event's posting_code is the authoritative attribution. |
| submitted_at | TIMESTAMPTZ | DEFAULT now() | |
| status | VARCHAR(20) | DEFAULT 'submitted' | `submitted`, `excluded`, `withdrawn` |

**Unique constraint:** `UNIQUE(resident_id, teaching_event_id)` — prevents duplicate submissions at DB layer.

**Deletion:** Resident can set status to `withdrawn` (soft delete) then resubmit (new record). Or hard delete + resubmit.

---

## Table: `surplus_ledger`

Running surplus per (resident, posting_code, session_type). Updated by compliance engine after each attendance submission or period calculation.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| resident_id | UUID | FK → residents.id, NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, NOT NULL | |
| session_type_id | UUID | FK → session_types.id, NOT NULL | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| achieved_count | INTEGER | DEFAULT 0 | Raw count of attended sessions |
| target_count | INTEGER | | From teaching_targets.monthly_target |
| surplus | INTEGER | DEFAULT 0 | achieved - target (if positive) |
| is_hibernating | BOOLEAN | DEFAULT false | True when resident is rotated away |

**Unique constraint:** `UNIQUE(resident_id, posting_code, session_type_id, reporting_period_id)`

**Behaviour:**
- When resident is posted to a department: `is_hibernating = false`, surplus accumulates
- When resident rotates away: `is_hibernating = true`, surplus preserved
- When resident returns: `is_hibernating = false`, surplus resumes
- At reporting period boundary: surplus resets to 0

---

## Table: `users`

For admin and secretary authentication **only**. Residents are **not** stored here — they authenticate directly against the `residents` table using their MCR number. See `docs/api.md` § Authentication Model for the full auth flow.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| email | VARCHAR(100) | UNIQUE, NOT NULL | |
| password_hash | VARCHAR(255) | NOT NULL | Stubbed in Phase 1 |
| role | VARCHAR(20) | NOT NULL | `admin`, `secretary` — never `resident` |
| name | VARCHAR(100) | NOT NULL | |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | Secretary's assigned site. NULL for admin. |
| programme_scope | TEXT[] | | Array of programme codes e.g. `{DR,GRM}`. Scopes the admin to specific programmes. NULL means global access (reserved for future use — currently all admins are programme-scoped). |
| is_active | BOOLEAN | DEFAULT true | |

---

## Table: `public_holidays`

For exception handling — PH detection.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| holiday_date | DATE | UNIQUE, NOT NULL | |
| name | VARCHAR(100) | | |
| year | INTEGER | | |

---

## Table: `weekend_exceptions`

Programme-specific rules for accepting weekend teachings.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| programme_code | VARCHAR(20) | FK → programmes.code | NULL = applies to posting code only |
| posting_code | VARCHAR(50) | FK → posting_codes.code, nullable | |
| day_type | VARCHAR(3) | NOT NULL | `sat`, `sun`, `both` |
| start_time_min | TIME | | NULL = any time accepted |
| end_time_max | TIME | | NULL = any time accepted |
| session_type_id | UUID | FK → session_types.id, nullable | NULL = any session type |
| session_name_pattern | VARCHAR(100) | | Optional: match specific session names |

**Examples from audit:**
- Emergency postings: `posting_code IN (TTSHEmgMed, KTPHAccEmg, ...)`, `day_type = 'both'`
- DERM: `programme_code = 'DERM'`, `day_type = 'sat'`
- ORTHO: `programme_code = 'ORTHO'`, `day_type = 'sat'`, `start_time_min = 08:30`, `end_time_max = 10:30`
- ANAES: `programme_code = 'ANAES'`, `day_type = 'sat'`, `start_time_min = 08:30`, `end_time_max = 12:30`
- FM: `programme_code = 'FM'`, `day_type = 'sat'`, `start_time_min = 08:00`, `end_time_max = 13:00`

---

## Table: `upload_logs`

Persistent audit trail of every RDB and TTF upload. Written by the upload endpoints at completion — success or failure. Replaces the legacy R script logfile.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| upload_type | VARCHAR(10) | NOT NULL | `rdb` or `ttf` |
| uploaded_by | UUID | FK → users.id, NOT NULL | Admin who triggered the upload |
| uploaded_at | TIMESTAMPTZ | DEFAULT now() | |
| reporting_period_id | UUID | FK → reporting_periods.id, nullable | NULL only if period lookup fails |
| programme_code | VARCHAR(20) | | TTF uploads only — NULL for RDB |
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
  "employed_residents_flagged": 3,
  "rows_skipped": 3,
  "skip_reasons": [
    { "row": 12, "mcr": "M12345A", "reason": "missing posting code" },
    { "row": 47, "mcr": "M99999Z", "reason": "unknown programme" }
  ],
  "warnings": []
}
```

**`summary` JSONB shape for TTF uploads:**
```json
{
  "targets_created": 29,
  "session_types_upserted": 5,
  "posting_codes_added": ["AICAIC", "DPPallia"],
  "rows_exploded": 3,
  "rows_skipped": 0,
  "skip_reasons": [],
  "errors": []
}
```

**Note:** The upload endpoint response body and the `upload_logs.summary` field contain identical data. The response is for the immediate API caller; the log record is for historical auditability. Both are written in the same transaction — if the write to `upload_logs` fails, the upload is still considered complete (log write is best-effort, non-blocking).

---

## Table: `period_snapshots`

Frozen compliance state captured at reporting period close. Replaces the legacy file-based archiving of Programme Reporting View Excel files.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| reporting_period_id | UUID | FK → reporting_periods.id, NOT NULL | |
| programme_code | VARCHAR(20) | NOT NULL | One snapshot per (period, programme) |
| snapshot_data | JSONB | NOT NULL | Full compliance state at period close — see shape below |
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

**Usage:** Snapshots are the historical record for closed periods. The live `attendance_records` and `surplus_ledger` tables remain untouched — snapshots are additive. Snapshots can be rendered into Excel exports at any time after period close via `GET /admin/exports/period-snapshot/{id}`. They are never updated after creation — if a period is reopened and reclosed, a new snapshot is generated and replaces the old one.

---

## Indexes

```sql
-- High-frequency lookups
CREATE INDEX idx_resident_postings_resident ON resident_postings(resident_id);
CREATE INDEX idx_resident_postings_posting ON resident_postings(posting_code);
CREATE INDEX idx_resident_postings_period ON resident_postings(reporting_period_id);
CREATE INDEX idx_attendance_resident ON attendance_records(resident_id);
CREATE INDEX idx_attendance_event ON attendance_records(teaching_event_id);
CREATE INDEX idx_teaching_events_posting ON teaching_events(posting_code);
CREATE INDEX idx_teaching_events_date ON teaching_events(event_date);
CREATE INDEX idx_teaching_targets_lookup ON teaching_targets(reporting_period_id, programme_code, posting_code);
CREATE INDEX idx_surplus_resident ON surplus_ledger(resident_id, posting_code, session_type_id);
```