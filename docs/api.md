# API Endpoints

Base URL: `http://localhost:8000/api/v1`

---

## Authentication Model

There are **two completely separate identity paths**. They share the JWT infrastructure but resolve identity from different tables and carry different claims.

### Path 1 — Admin and Secretary (`users` table)

Admin and secretary accounts are managed in the `users` table (email + password). Login via `POST /auth/login` with email and password. The JWT payload carries:

```json
{
  "sub": "<users.id>",
  "role": "admin" | "secretary",
  "programme_scope": ["DR", "GRM"],   // admin only
  "posting_code": "TTSHGerMed"        // secretary only
}
```

### Path 2 — Residents (`residents` table)

Residents are **not** in the `users` table. They authenticate with their **MCR number only** — no password in Phase 1. The JWT payload carries:

```json
{
  "sub": "<residents.id>",
  "role": "resident",
  "mcr": "M12345A",
  "programme_code": "GRM"
}
```

`programme_code` is embedded at login time from `residents.programme_code`. It scopes all compliance lookups to the resident's native programme. **`posting_code` is NOT in the JWT** — current posting is always derived at request time from `resident_postings`.

### How the compliance chain resolves from login

1. Resident logs in with MCR → JWT issued with `programme_code = 'GRM'`
2. On `GET /resident/events` or `GET /resident/dashboard`:
   - Current posting derived from `resident_postings` WHERE today falls within `start_date..end_date` AND `status IN ('active', 'loa_working')`
   - Compliance targets from `teaching_targets` WHERE `programme_code = 'GRM'` AND `posting_code` from current phase AND `r_year` from **resident_postings row** (not residents.r_year) AND `reporting_period_id` from open period

### Request identity headers (Phase 1 stub)

```
X-User-Role: admin | secretary | resident
X-User-Id: <users.id for admin/secretary> | <residents.id for resident>
X-User-Programme: <programme_code>   # resident and admin only
X-User-Site: <posting_code>          # secretary only
```

---

## Admin Endpoints

### POST `/admin/upload/rdb`

Upload RDB Posting Schedule Excel file.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID)
- **Processing:** See `docs/parsing.md` § RDB Parser
- **Audit log:** Writes `upload_logs` row with `upload_type = 'rdb'`
- **Response:**
```json
{
  "residents_created": 42,
  "residents_updated": 5,
  "postings_created": 504,
  "posting_codes_added": ["TTSHAnaes", "KTPHGerMed"],
  "loa_records": 12,
  "unknown_loa_types": [],
  "employed_residents_flagged": 3,
  "multi_posting_rules_applied": 8,
  "rows_skipped": 0,
  "skip_reasons": [],
  "warnings": [],
  "errors": []
}
```

### POST `/admin/upload/ttf`

Upload Teaching Target File Excel.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID), `programme_code` (string)
- **Processing:** See `docs/parsing.md` § TTF Parser
- **Behaviour:** Full replace within `(reporting_period_id, programme_code)` scope. Re-upload always allowed regardless of existing attendance.
- **Orphan detection:** After replace, checks for attendance records whose `teaching_name` no longer has a `teaching_name_catalogue` row. These are returned as warnings — upload still returns `200`.
- **Concurrency:** Scope-level PostgreSQL advisory lock. A second upload for the same scope returns `409`.
- **Audit log:** Writes `upload_logs` row with `upload_type = 'ttf'`
- **Response:**
```json
{
  "targets_created": 29,
  "session_types_upserted": 5,
  "posting_codes_added": ["AICAIC", "DPPallia"],
  "catalogue_rows_seeded": 84,
  "rows_exploded": 3,
  "warnings": [
    {
      "type": "orphaned_attendance",
      "session_type": "Case-based Teaching [1h]",
      "posting_code": "KTPHGerMed",
      "count": 3,
      "message": "3 attendance records no longer map to any teaching target and will not count toward compliance"
    }
  ],
  "errors": []
}
```
- **Error responses:**
  - `409` — concurrent upload for same scope (advisory lock)
  - `422` — file validation errors (returned before any writes)

### POST `/admin/upload/form-f1`

Upload FormF1 Excel file for active/inactive status per resident per calendar month.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID)
- **Processing:** See `docs/parsing.md` § FormF1 Parser
- **Behaviour:** Full replace per `reporting_period_id` scope. Re-upload allowed at any time (e.g. to update for unforeseen LOAs).
- **Audit log:** Writes `upload_logs` row with `upload_type = 'form_f1'`
- **Response:**
```json
{
  "records_created": 312,
  "records_updated": 0,
  "mcr_not_found_warnings": [],
  "month_labels_parsed": ["Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25", "Dec-25"],
  "active_count": 280,
  "inactive_count": 32,
  "errors": []
}
```

### GET `/admin/teaching-targets`

List all teaching targets with filters.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `r_year` (all optional)
- **Response:** Array of teaching target objects

### PUT `/admin/teaching-targets/{id}`

Edit a single teaching target row (mid-period correction).

- **Auth:** admin only
- **Editable fields:** `monthly_target`, `is_tracked`, `is_reallocatable`, `tag`, `details_of_training`
- **Identity columns (locked):** `session_type_id`, `posting_code`, `programme_code`, `r_year` — cannot be changed via CRUD. Full TTF re-upload required for structural changes.
- **Side effect:** When `details_of_training` is updated, the system deletes and re-inserts the corresponding `teaching_name_catalogue` rows for this `(reporting_period_id, programme_code, posting_code, session_type_id)` scope. Keyword changes take effect immediately for compliance and event visibility on the next read — no TTF re-upload needed.
- **Body:**
```json
{
  "monthly_target": 15,
  "is_tracked": true,
  "is_reallocatable": false,
  "tag": "A",
  "details_of_training": "Lectures, Journal Club, Tutorials"
}
```

### DELETE `/admin/teaching-targets/{id}`

Delete a single teaching target row.

- **Auth:** admin only
- **Constraint:** Returns warning (not block) if attendance records reference this target's session type + posting.

### GET `/admin/multi-posting-rules`

List all multi-posting rules.

- **Auth:** admin only
- **Query params:** `programme_code`, `rule_type` (optional)

### POST `/admin/multi-posting-rules`

Add a new multi-posting rule.

- **Auth:** admin only
- **Body:**
```json
{
  "programme_code": "GRM",
  "posting_code_1": "IMHGrPsyc",
  "posting_code_2": "TTSHPsychi",
  "rule_type": "combine",
  "combined_label": "IMHGrPsyc & TTSHPsychi",
  "main_posting_code": null,
  "exclusion_code": null
}
```

### PUT `/admin/multi-posting-rules/{id}`

Update an existing multi-posting rule.

- **Auth:** admin only

### DELETE `/admin/multi-posting-rules/{id}`

Delete a multi-posting rule.

- **Auth:** admin only

### GET `/admin/posting-groups`

List all posting group entries.

- **Auth:** admin only
- **Query params:** `programme_code`, `group_code` (optional)

### POST `/admin/posting-groups`

Add a new posting group entry.

- **Auth:** admin only
- **Body:**
```json
{
  "group_code": "TTSHRespi",
  "posting_code": "TTSHRespi(MICU)",
  "programme_code": "RESPI"
}
```
- **Notes:** `group_code` is the canonical aggregation key. Add one row per posting code that belongs to the group. A posting code may only belong to one group per programme.

### PUT `/admin/posting-groups/{id}`

Update an existing posting group entry.

- **Auth:** admin only

### DELETE `/admin/posting-groups/{id}`

Delete a posting group entry.

- **Auth:** admin only

List all weekend exception rules.

- **Auth:** admin only
- **Query params:** `programme_code`, `posting_code` (optional)

### POST `/admin/weekend-exceptions`

Add a new weekend exception rule.

- **Auth:** admin only
- **Body:**
```json
{
  "programme_code": "DERM",
  "posting_code": null,
  "day_type": "sat",
  "start_time_min": null,
  "end_time_max": null,
  "session_type_id": null,
  "session_name_pattern": null,
  "mutates_to_session_type_id": null,
  "adjusted_duration_hours": null
}
```

### PUT `/admin/weekend-exceptions/{id}`

Update an existing weekend exception rule.

- **Auth:** admin only

### DELETE `/admin/weekend-exceptions/{id}`

Delete a weekend exception rule.

- **Auth:** admin only

### GET `/admin/programmes`

List all programmes with their configuration flags.

- **Auth:** admin only

### PUT `/admin/programmes/{code}`

Update programme configuration (r_year_required, is_subspecialty, rdb_alias).

- **Auth:** admin only
- **Editable fields:** `r_year_required`, `is_subspecialty`, `rdb_alias`
- **Body:**
```json
{
  "r_year_required": false,
  "is_subspecialty": true,
  "rdb_alias": "Surgery-in-General"
}
```

### GET `/admin/loa-types`

List all LOA types.

- **Auth:** admin only

### POST `/admin/loa-types`

Add a new LOA type.

- **Auth:** admin only
- **Body:** `{ "code": "Study Leave", "description": "Academic study leave" }`

### DELETE `/admin/loa-types/{id}`

Delete a LOA type.

- **Auth:** admin only

### GET `/admin/global-session-types`

List all global (non-tracked, compliance-exempt) session types.

- **Auth:** admin only
- **Query params:** `is_active` (optional, default returns all)

### POST `/admin/global-session-types`

Add a new global session type.

- **Auth:** admin only
- **Body:** `{ "name": "Department Meeting [1h]", "duration_hours": 1.0 }`
- **Note:** Name must include duration bracket `[Xh]` — same convention as `session_types`.

### PUT `/admin/global-session-types/{id}`

Update a global session type (e.g. deactivate it).

- **Auth:** admin only
- **Body:** `{ "name": "Department Meeting [1h]", "duration_hours": 1.0, "is_active": false }`

### DELETE `/admin/global-session-types/{id}`

Delete a global session type.

- **Auth:** admin only
- **Note:** Returns `409` if any `teaching_events` rows reference this session type name. Deactivate instead of deleting in that case.

List all reporting periods.

- **Auth:** admin only

### POST `/admin/reporting-periods`

Create a new reporting period.

- **Auth:** admin only
- **Body:**
```json
{
  "label": "Jan - June 2026",
  "start_date": "2026-01-06",
  "end_date": "2026-07-06"
}
```

### PUT `/admin/reporting-periods/{id}/close`

Close a reporting period.

- **Auth:** admin only
- **Actions triggered at close (in order):**
  1. Set `reporting_periods.status = 'closed'`
  2. Set all `surplus_ledger.is_hibernating = true` for all non-hibernating rows in this period
  3. Generate one `period_snapshots` row per programme that has TTF data for this period
  4. Generate `clawback_records` rows for all residents who failed 70% PTT (excluding SAF/SCDF-Employed; setting `clawback_suppressed_reason` for Extension and R7)
  5. If a snapshot already exists (period was previously closed and reopened), the existing snapshot is replaced
- **Response:**
```json
{
  "period_label": "Jan - June 2026",
  "snapshots_generated": 2,
  "programmes_snapshotted": ["DR", "GRM"],
  "clawback_rows_generated": 14,
  "clawback_rows_suppressed": 2
}
```

### PUT `/admin/reporting-periods/{id}/reopen`

Reopen a closed reporting period. Does NOT delete existing snapshots — new snapshots generated on next close.

- **Auth:** admin only

---

### Upload Logs

### GET `/admin/upload-logs`

List upload history.

- **Auth:** admin only
- **Query params:** `upload_type` (`rdb` | `ttf` | `form_f1` | `public_holidays`), `programme_code`, `reporting_period_id`, `limit` (default 20)

### GET `/admin/upload-logs/{id}`

Get a single upload log entry.

- **Auth:** admin only

---

### Public Holidays

### GET `/admin/public-holidays`

List all public holidays.

- **Auth:** admin only
- **Query params:** `year` (optional)

### POST `/admin/upload/public-holidays`

Upload a public holiday file to seed the `public_holidays` table.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx or csv)
- **File format:** Three columns: `Date (dd-mmm-yy)` | `Day of Week` | `Public Holiday name`
- **Behaviour:** Upsert on `holiday_date` — safe to re-run. Day-of-week mismatch returns a warning but does not fail.
- **Audit log:** Writes `upload_logs` row with `upload_type = 'public_holidays'`
- **Response:** `{ "inserted": 11, "skipped": 0, "warnings": [] }`

### DELETE `/admin/public-holidays/{id}`

Delete a single public holiday entry.

- **Auth:** admin only

---

### Admin Compliance Reports

> **Implementation note:** All four admin report endpoints compute compliance via a **SQL batch query** across all residents in the programme at once, then apply tag-based reallocation in Python over the result set. The SQL query joins `form_f1_records` as the active/inactive gate. See `docs/business-logic.md` § BL-6.

> **Export format:** All four report endpoints support `?format=xlsx` in addition to JSON. Excel output mirrors the legacy Programme Reporting View format.

### GET `/admin/reports/monthly-view`

Monthly attendance summary per resident.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `month` (YYYY-MM)
- **Response:** Per-resident rows with target per month, achieved, percentage, traffic light colour

### GET `/admin/reports/posting-view`

Posting-level compliance summary.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `format` (`json` | `xlsx`)
- **Response:** Per-resident, per-posting rows with: `target100`, `target70`, `achieved_and_counted`, `shortage`, `percentage`, `met_70pct`, `colour`, `compliance_unreliable`, `compliance_unreliable_reason`

### GET `/admin/reports/attendance-breakdown`

Detailed breakdown by session type within each posting.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `resident_id` (optional), `format` (`json` | `xlsx`)

### GET `/admin/reports/submitted-attendances`

Raw flat export of all submitted attendance records.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `resident_id`, `date_from`, `date_to`, `format` (`json` | `xlsx` | `csv`)
- **Response columns:** Resident Name, MCR, Programme, R Year, Posting (RDB), Posting Month, Event Date, Teaching Name, Session Type (resolved per resident), Duration, Tracked, Is Adhoc, Achieved, Target (monthly), Shortage, Tag, Submitted At, Status

### GET `/admin/reports/clawback`

Clawback report for the reporting period. This is the **5th tab** in the admin/PC dashboard alongside Monthly View, Posting View, Attendance Breakdown, Submitted Attendances.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `format` (`json` | `xlsx`)
- **Scope:** Reads from `clawback_records` table generated at period close. All rows shown — including suppressed rows (Extension, R7) with `clawback_amount = 0` and `clawback_suppressed_reason` displayed.
- **Response:**
```json
{
  "clawback_rows": [
    {
      "mcr": "M12345A",
      "name": "John Tan",
      "programme": "Geriatric Medicine",
      "r_year": "R3",
      "posting_code": "TTSHGerMed",
      "active_months": 3.0,
      "compliance_percentage": 0.62,
      "clawback_amount": 1250.00,
      "clawback_suppressed_reason": null,
      "billing_dept": "TTSH Geriatric Medicine"
    },
    {
      "mcr": "M67890B",
      "name": "Jane Lim",
      "programme": "Geriatric Medicine",
      "r_year": "R2",
      "posting_code": "KTPHGerMed",
      "active_months": 2.0,
      "compliance_percentage": 0.55,
      "clawback_amount": 0.00,
      "clawback_suppressed_reason": "Extension",
      "billing_dept": "KTPH Geriatric Medicine"
    }
  ],
  "total_clawback_amount": 1250.00,
  "period_label": "Jan - June 2026",
  "programme_code": "GERI"
}
```

### GET `/admin/exports/period-snapshot/{snapshot_id}`

Export a historical period snapshot as Excel. Available for closed periods only.

- **Auth:** admin only

### GET `/admin/form-f1-records`

List FormF1 active/inactive records.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `mcr`, `month_label`, `is_active` (all optional)

---

## Secretary Endpoints

### GET `/secretary/teaching-events`

List teaching events for the secretary's posting site.

- **Auth:** secretary only
- **Scope:** Filtered to `X-User-Site` posting code
- **Query params:** `date_from`, `date_to`, `session_type_id` (all optional)

### POST `/secretary/teaching-events`

Create a new teaching event.

- **Auth:** secretary only
- **Validation:** Returns `422` if `event_date` is in the `public_holidays` table.
- **Body:**
```json
{
  "teaching_name": "Journal Club",
  "event_date": "2026-04-15",
  "start_time": "10:00",
  "cme_points_awarded": false,
  "smc_event_code": null
}
```
- **Backend auto-resolves:**
  - `posting_code` from `X-User-Site` header
  - `session_type_id` from `teaching_name` → lookup against `teaching_name_catalogue` for the secretary's posting across all programmes. If multiple matches (same keyword, different duration), use `duration_hours` tiebreaker. Stored for display in Teaching Type column (display/prototype only — never used for compliance).
  - `end_time` = `start_time + session_type.duration_hours` (server-computed — NOT a request field)
  - `duration_hours` copied from session_type for future tiebreaker use
- **Returns 422 if:** `teaching_name` has no match in `teaching_name_catalogue` for this posting

### POST `/secretary/teaching-events/duplicate`

Duplicate an existing event.

- **Auth:** secretary only
- **Body:**
```json
{
  "source_event_id": "uuid",
  "event_date": "2026-04-22",
  "start_time": "10:00",
  "teaching_name": "Journal Club"
}
```
- **Validation:** Returns `422` if `event_date` is a public holiday.

### DELETE `/secretary/teaching-events/{id}`

Delete a teaching event.

- **Auth:** secretary only
- **Constraint:** Returns `409` if any attendance records exist against this event.

### POST `/secretary/teaching-events/series`

Create a recurring event series.

- **Auth:** secretary only
- **Validation:** Any occurrence that falls on a public holiday is skipped and included in the response as a warning. Other occurrences are created normally.
- **Body:**
```json
{
  "teaching_name": "Journal Club",
  "start_time": "10:00",
  "cme_points_awarded": false,
  "smc_event_code": null,
  "recurrence_pattern": "weekly",
  "recurrence_interval": 1,
  "days_of_week": ["tue"],
  "end_type": "by_date",
  "end_date": "2026-06-30",
  "end_after_count": null
}
```
- **Backend:** Materialises individual `teaching_events` rows per occurrence.

### DELETE `/secretary/teaching-events/series/{series_id}`

Delete a series. Options: `scope=single&event_id=X`, `scope=following&event_id=X`, `scope=all`.

- **Auth:** secretary only
- **Constraint:** Cannot delete occurrences that have attendance records.

### GET `/secretary/cme-dashboard`

CME summary view for the secretary's posting site.

- **Auth:** secretary only

### GET `/secretary/residents`

List residents currently posted to the secretary's site.

- **Auth:** secretary only

### GET `/secretary/teaching-name-options`

Get available teaching name keywords for the dropdown.

- **Auth:** secretary only
- **Scope:** Returns a unified list combining:
  1. Keywords from `teaching_name_catalogue` for `posting_code = X-User-Site` across ALL programmes
  2. Active entries from `global_session_types` (compliance-exempt, available to all secretaries)
- **Response:**
```json
{
  "options": [
    {"keyword": "Journal Club", "session_type": "Department/Programme Teaching [1h]", "duration_hours": 1.0, "is_tracked": true, "is_global": false},
    {"keyword": "Case discussions with supervisor", "session_type": "Case-based Teaching [2h]", "duration_hours": 2.0, "is_tracked": true, "is_global": false},
    {"keyword": "Department Meeting", "session_type": "Department Meeting [1h]", "duration_hours": 1.0, "is_tracked": false, "is_global": true}
  ]
}
```
- **Note:** `is_global = true` entries come from `global_session_types` and are always excluded from PTT compliance. `is_tracked = false` entries from the TTF are also shown but excluded from compliance. Secretary sees a unified list — the compliance distinction is transparent to them.

---

## Resident Endpoints

### GET `/resident/events`

List teaching events available for submission.

- **Auth:** resident only
- **Visibility gating:**
  1. If resident has no `resident_postings` rows for the current period → return empty list with `reason: "posting_schedule_unavailable"`
  2. Current posting: from `resident_postings` where today falls within `start_date..end_date` AND `status IN ('active', 'loa_working')`. Use `ORDER BY start_date DESC LIMIT 1` as tie-breaker.
  3. Native programme posting: posting(s) associated with the resident's `programme_code`
  4. Fetch events from the UNION of both posting codes
  5. Filter to `event_date <= today` (no future events)
  6. Exclude events already submitted by this resident
  7. Filter by `teaching_name_catalogue` for the resident's `(posting_code, programme_code, r_year, reporting_period_id)` — only show events whose `teaching_name` exists in their catalogue
- **Query params:** `date_from`, `date_to`

### POST `/resident/attendance`

Submit attendance for one or more events.

- **Auth:** resident only
- **Body:** `{ "event_ids": ["uuid1", "uuid2"] }`
- **Backend:**
  1. Validates event exists and is at resident's current or native posting
  2. Validates `event_date` falls within a `resident_postings` row with `status IN ('active', 'loa_working')` → `422` if outside tenure
  3. Validates `teaching_name` exists in `teaching_name_catalogue` for resident's `(posting_code, programme_code, r_year, reporting_period_id)` → `422` if no match
  4. Validates no duplicate (`UNIQUE(resident_id, teaching_event_id)`)
  5. Creates `attendance_records` rows — **does NOT store `session_type_id`**
  6. Checks each submitted event against `weekend_exceptions` — if a weekend session has no matching rule, adds a `compliance_warning` to the response
- **Response:**
```json
{
  "submitted": 3,
  "errors": [],
  "compliance_warning": "1 session(s) submitted on a weekend will not count toward your PTT compliance as they do not meet the weekend exception rules for your programme."
}
```
`compliance_warning` is `null` when all submitted sessions are either weekdays or match a weekend exception rule.

### DELETE `/resident/attendance/{attendance_id}`

Delete own submitted attendance.

- **Auth:** resident only
- **Constraint:** Can only delete own records.

### POST `/resident/adhoc-teaching`

Submit an ad-hoc teaching not pre-created by a secretary.

- **Auth:** resident only
- **Body:**
```json
{
  "date": "2026-04-15",
  "start_time": "10:00",
  "teaching_name": "Journal Club"
}
```
- **Backend:**
  1. Validates `date` is not a public holiday → `422` if PH
  2. Derives `posting_code` from `resident_postings` for the given date
  3. Resolves `session_type_id` from `teaching_name_catalogue` → `422` if no match
  4. Creates `teaching_events` row with `is_adhoc = true`
  5. Creates `attendance_records` row in the same transaction
  6. `end_time` = `start_time + session_type.duration_hours`
  7. Checks weekend exception — returns `compliance_warning` if session will not count
- **Compliance treatment:** Identical to secretary-created sessions

### GET `/resident/dashboard`

Resident's personal compliance dashboard.

- **Auth:** resident only
- **Response:**
```json
{
  "current_posting": {
    "posting_code": "TTSHGerMed",
    "start_date": "2026-04-06",
    "end_date": "2026-05-03"
  },
  "upcoming_postings": [],
  "compliance_summary": [
    {
      "posting_code": "TTSHGerMed",
      "session_type": "Department/Programme Teaching [1h]",
      "target_70pct": 10,
      "achieved": 7,
      "shortfall": 3,
      "percentage": 0.54,
      "colour": "amber",
      "compliance_unreliable": false,
      "compliance_unreliable_reason": null
    }
  ],
  "submitted_attendances": [
    {
      "id": "uuid",
      "event_name": "Journal Club",
      "event_date": "2026-04-10",
      "session_type": "Department/Programme Teaching [1h]",
      "is_adhoc": false,
      "submitted_at": "2026-04-10T14:30:00Z"
    }
  ]
}
```

---

## Auth Endpoints

### POST `/auth/login`

Unified login endpoint.

- **Body (admin / secretary):**
```json
{ "role": "admin", "email": "pc@nhg.com.sg", "password": "password" }
```

- **Body (resident):**
```json
{ "role": "resident", "mcr": "M12345A" }
```
Looks up `residents` table by MCR. Validates `status != 'inactive'`. **No password required in Phase 1.**

- **Response:**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": "<uuid>",
    "role": "resident",
    "name": "John Tan",
    "programme_code": "GRM",
    "mcr": "M12345A"
  }
}
```

- **Error responses:**
  - `401` — MCR not found or resident inactive
  - `401` — Invalid email or password (admin/secretary)

### GET `/auth/me`

Return current identity from validated JWT.

- Resident: returns `residents` row fields + current posting (derived live from `resident_postings`)
- Admin/Secretary: returns `users` row fields + scope

### PUT `/auth/settings`

Update password. Admin/secretary only.

---

## Common Error Responses

```json
{ "detail": "Unauthorized" }                                                    // 401
{ "detail": "Forbidden — admin role required" }                                  // 403
{ "detail": "Teaching event not found" }                                         // 404
{ "detail": "Cannot delete event with attendance" }                              // 409
{ "detail": "Duplicate attendance submission" }                                  // 409
{ "detail": "Another TTF upload for this scope is in progress" }                 // 409
{ "detail": "Reporting period is closed" }                                       // 409
{ "detail": "TTF validation failed", "errors": [...] }                           // 422
{ "detail": "Event date is a public holiday — event creation not allowed" }      // 422
{ "detail": "Attendance submission invalid: event date is outside your tenure at this posting" }  // 422
{ "detail": "Teaching name not found in catalogue for your programme and posting" }  // 422
```