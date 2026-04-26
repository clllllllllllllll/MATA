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
  "programme_scope": ["DR", "GRM"],   // admin only — null means global (reserved)
  "posting_code": "TTSHGerMed"        // secretary only — their assigned site
}
```

### Path 2 — Residents (`residents` table)

Residents are **not** in the `users` table. They authenticate with their **MCR number only** — no password in Phase 1. The backend looks up the MCR in the `residents` table. If found and `status != 'inactive'`, a JWT is issued. The JWT payload carries:

```json
{
  "sub": "<residents.id>",
  "role": "resident",
  "mcr": "M12345A",
  "programme_code": "GRM"
}
```

`programme_code` is embedded in the token at login time, derived from `residents.programme_code` (set during RDB upload from the Specialization column). It does **not** change mid-session even if the RDB is re-uploaded — the resident must log in again for changes to take effect.

**`posting_code` is NOT embedded in the JWT.** Current posting is always derived at request time from `resident_postings` — this ensures the correct posting is used even if the schedule is corrected mid-period without requiring re-login.

### How the compliance chain resolves from login

When a resident logs in with MCR `M12345A`:

1. `residents` table lookup → `programme_code = 'GRM'`, `id = <resident_uuid>`
2. JWT issued with `programme_code = 'GRM'`
3. On `GET /resident/events` or `GET /resident/dashboard`:
   - Current posting derived from `resident_postings` WHERE `resident_id = <id>` AND today between `start_date` and `end_date` AND `status IN ('active', 'loa_working')` → e.g. `posting_code = 'KTPHGerMed'`
4. Compliance targets looked up from `teaching_targets` WHERE:
   - `programme_code = 'GRM'`  ← from JWT
   - `posting_code = 'KTPHGerMed'`  ← from current resident_postings row
   - `r_year = 'R3'`  ← from the **resident_postings row** (not residents.r_year)
   - `reporting_period_id = <active period>`  ← from reporting_periods WHERE status = 'open'

This means the TTF a resident "sees" is always their **native programme's** TTF (GRM, not DR) filtered to their **current posting**. A GRM resident and a DR resident at the same physical hospital see different compliance targets because they reference different TTF uploads.

### Request identity headers (Phase 1 stub)

Until real JWT middleware is in place, identity is passed via headers. These headers are set by the stub auth middleware after token validation — they are **not** set directly by the client in production:

```
X-User-Role: admin | secretary | resident
X-User-Id: <users.id for admin/secretary> | <residents.id for resident>
X-User-Programme: <programme_code>   # resident and admin only
X-User-Site: <posting_code>          # secretary only
```

For residents, `X-User-Programme` is populated from the JWT claim. `X-User-Site` (current posting) is **never** a fixed header for residents — it is always resolved per-request from `resident_postings`.

---

## Admin Endpoints

### POST `/admin/upload/rdb`

Upload RDB Posting Schedule Excel file. Creates/updates residents and their rotation schedule.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx)
- **Processing:** See `docs/parsing.md` § RDB Parser
- **Audit log:** On completion (success or partial), a row is written to `upload_logs` with `upload_type = 'rdb'` and the full summary JSONB. See `docs/schema.md` § `upload_logs`.
- **Response:**
```json
{
  "residents_created": 42,
  "residents_updated": 5,
  "postings_created": 504,
  "posting_codes_added": ["TTSHAnaes", "KTPHGerMed"],
  "loa_records": 12,
  "employed_residents_flagged": 3,
  "rows_skipped": 0,
  "skip_reasons": [],
  "errors": []
}
```

### POST `/admin/upload/ttf`

Upload Teaching Target File Excel. Seeds session types and teaching targets.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID), `programme_code` (string)
- **Processing:** See `docs/parsing.md` § TTF Parser
- **Behaviour:** Full replace within `(reporting_period_id, programme_code)` scope.
- **Re-upload guard:** Before the delete step, the endpoint checks whether any `attendance_records` exist that reference events whose `session_type_id` is present in the current scope's `teaching_targets`. If attendance exists and the new TTF removes or changes any of those session types, the upload returns `422` listing the affected session types. The admin must use the CRUD UI (`PUT /admin/teaching-targets/{id}`) for mid-period corrections to those rows instead. Purely additive re-uploads (new rows only, no changes to existing session types with attendance) are allowed.
- **Concurrency:** A scope-level PostgreSQL advisory lock (`pg_try_advisory_xact_lock`) is acquired at the start of the transaction. A second upload for the **same** scope while one is in progress returns `409`. Uploads for different scopes (e.g. DR vs GRM, or different periods) do not block each other. See `docs/parsing.md` § TTF Upload Behaviour for the lock key derivation.
- **Upserts:** `session_types` and `posting_codes` are written with `ON CONFLICT DO NOTHING` / `DO UPDATE` — safe to re-upload without duplicate errors in shared catalogue tables. See `docs/parsing.md` § TTF Upload Behaviour for the full SQL.
- **Audit log:** On completion (success or partial), a row is written to `upload_logs` with `upload_type = 'ttf'`, `programme_code`, and the full summary JSONB. See `docs/schema.md` § `upload_logs`.
- **Response:**
```json
{
  "targets_created": 29,
  "session_types_upserted": 5,
  "posting_codes_added": ["AICAIC", "DPPallia"],
  "rows_exploded": 3,
  "errors": []
}
```
- **Error responses:**
  - `409` — another TTF upload for this scope is already in progress (advisory lock contention)
  - `422` — validation errors in the uploaded file (returned before any writes)
  - `422` — re-upload would remove or change session types that already have attendance records; lists affected session types

### GET `/admin/teaching-targets`

List all teaching targets with filters.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `r_year` (all optional)
- **Response:** Array of teaching target objects

### PUT `/admin/teaching-targets/{id}`

Edit a single teaching target row (mid-period correction).

- **Auth:** admin only
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
- **Constraint:** Should warn if attendance records exist that reference this target's session type + posting.

### GET `/admin/reporting-periods`

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

Close a reporting period. Prevents further attendance submissions and freezes compliance state.

- **Auth:** admin only
- **Actions triggered at close (in order):**
  1. Set `reporting_periods.status = 'closed'`
  2. Set all `surplus_ledger.is_hibernating = true` for all non-hibernating rows in this period
  3. Generate one `period_snapshots` row per programme that has TTF data for this period — frozen compliance state as JSONB. See `docs/schema.md` § `period_snapshots`.
  4. If a snapshot already exists for a `(reporting_period_id, programme_code)` pair (period was previously closed, reopened, and is being closed again), the existing snapshot is replaced.
- **Response:**
```json
{
  "period_label": "Jan - June 2026",
  "snapshots_generated": 2,
  "programmes_snapshotted": ["DR", "GRM"]
}
```

### PUT `/admin/reporting-periods/{id}/reopen`

Reopen a closed reporting period.

- **Auth:** admin only
- **Note:** Reopening does NOT delete existing snapshots. New snapshots will be generated (and replace old ones) when the period is closed again.

---

### Upload Logs

### GET `/admin/upload-logs`

List past upload history for audit and troubleshooting. Replaces the legacy R script logfile.

- **Auth:** admin only
- **Query params:** `upload_type` (`rdb` | `ttf`), `programme_code`, `reporting_period_id`, `limit` (default 20)
- **Response:** Array of upload log entries ordered by `uploaded_at` descending:
```json
[
  {
    "id": "uuid",
    "upload_type": "ttf",
    "uploaded_by": "pc@nhg.com.sg",
    "uploaded_at": "2026-01-10T09:15:00Z",
    "reporting_period_id": "uuid",
    "programme_code": "DR",
    "status": "success",
    "summary": {
      "targets_created": 29,
      "session_types_upserted": 5,
      "posting_codes_added": ["AICAIC"],
      "rows_exploded": 3,
      "rows_skipped": 0,
      "errors": []
    }
  }
]
```

### GET `/admin/upload-logs/{id}`

Get a single upload log entry with full summary detail.

- **Auth:** admin only

---

### Admin Reporting Views and Exports

The `public_holidays` table drives PH detection in exception handling (BL-5). If it is empty, no teaching is ever flagged as falling on a public holiday — a silent failure. These endpoints allow admins to seed and maintain the table.

### GET `/admin/public-holidays`

List all public holidays.

- **Auth:** admin only
- **Query params:** `year` (optional)
- **Response:** Array of `{ id, holiday_date, name, year }`

### POST `/admin/public-holidays/bulk`

Seed public holidays for a year (e.g. from MOM's published list).

- **Auth:** admin only
- **Body:**
```json
{
  "holidays": [
    { "holiday_date": "2026-01-01", "name": "New Year's Day", "year": 2026 },
    { "holiday_date": "2026-01-29", "name": "Chinese New Year", "year": 2026 }
  ]
}
```
- **Behaviour:** `INSERT ... ON CONFLICT (holiday_date) DO NOTHING` — safe to re-run.
- **Response:** `{ "inserted": 11, "skipped": 0 }`

### DELETE `/admin/public-holidays/{id}`

Delete a single public holiday entry.

- **Auth:** admin only

---

### Admin Compliance Reports

> **Implementation note:** All four admin report endpoints compute compliance via a **SQL batch query** across all residents in the programme at once, then apply tag-based reallocation in Python over the result set. This keeps the DB round-trip count constant regardless of cohort size. See `docs/business-logic.md` § BL-6 for the query sketch and the rationale for splitting SQL (admin) vs Python JIT (resident dashboard).

> **Export format:** All four report endpoints support `?format=xlsx` in addition to the default JSON response. The Excel output mirrors the legacy Programme Reporting View format from the R scripts (MONTHLY VIEW, POSTING VIEW, TEACHING ATTENDANCE BREAKDOWN, RESIDENT'S SUBMITTED ATTENDANCE sheets). If `format` is omitted, JSON is returned.

### Admin Reporting Views

> **Implementation note:** All four admin report endpoints compute compliance via a **SQL batch query** across all residents in the programme at once, then apply tag-based reallocation in Python over the result set. This keeps the DB round-trip count constant regardless of cohort size. See `docs/business-logic.md` § BL-6 for the query sketch and the rationale for splitting SQL (admin) vs Python JIT (resident dashboard).

### GET `/admin/reports/monthly-view`

Monthly attendance summary per resident.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `month` (YYYY-MM)
- **Response:** Per-resident rows with: target per month, achieved this month, percentage, traffic light colour

### GET `/admin/reports/posting-view`

Posting-level compliance summary.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `format` (`json` | `xlsx`)
- **Response:** Per-resident, per-posting rows with: `target100`, `target70`, `achieved_and_counted`, `shortage`, `percentage`, `met_70pct`, `colour`, `compliance_unreliable`, `compliance_unreliable_reason`. Dual-posted residents have `compliance_unreliable = true`. See `docs/business-logic.md` § BL-7.

### GET `/admin/reports/attendance-breakdown`

Detailed breakdown by session type within each posting.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `resident_id` (optional), `format` (`json` | `xlsx`)
- **Response:** Per (resident, posting, session_type) rows with achieved, target, surplus, reallocation transfers

### GET `/admin/reports/submitted-attendances`

Raw flat export of all submitted attendance records. Equivalent to the legacy consolidated attendance Excel file from Script D1.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `resident_id`, `date_from`, `date_to` (all optional), `format` (`json` | `xlsx` | `csv`)
- **Response columns (xlsx/csv):** Resident Name, MCR, Programme, R Year, Posting (RDB), Posting Month, Event Date, Teaching Name, Session Type (resolved per resident), Duration, Tracked, Achieved, Target (monthly), Shortage, Tag, Submitted At, Status
- **Note:** The `session_type` column reflects the per-resident resolved session type from TTF keyword matching — not the `session_type_id` stored on the event.

### GET `/admin/exports/period-snapshot/{snapshot_id}`

Export a historical period snapshot as a formatted Excel file. Available for closed periods only. Replaces the need to keep legacy Programme Reporting View Excel files in a file system archive.

- **Auth:** admin only
- **Response:** Excel file (`.xlsx`) rendered from the frozen `period_snapshots.snapshot_data` JSONB. Same sheet structure as the live reporting view exports. Use this to retrieve historical compliance records for any closed period without re-running calculations.

---

## Secretary Endpoints

### GET `/secretary/teaching-events`

List teaching events for the secretary's posting site.

- **Auth:** secretary only
- **Scope:** Filtered to `X-User-Site` posting code
- **Query params:** `date_from`, `date_to`, `session_type_id` (all optional)
- **Response:** Array of teaching events

### POST `/secretary/teaching-events`

Create a new teaching event.

- **Auth:** secretary only
- **Body:**
```json
{
  "teaching_name": "Journal Club",
  "event_date": "2026-04-15",
  "start_time": "10:00",
  "duration_hours": 1.0,
  "cme_points_awarded": false,
  "smc_event_code": null
}
```
- **Backend auto-resolves:**
  - `posting_code` from `X-User-Site` header
  - `session_type_id` from `teaching_name` + `duration_hours` → TTF keyword lookup against the **secretary's native programme TTF** at that posting. Primary match on `teaching_name`; if multiple session types match, `duration_hours` is used as tiebreaker. Stored for display in the Teaching Type column (secretary UI / prototype validation). Does NOT drive compliance — compliance resolves independently per resident at attendance submission time. **(TBD-1)**
  - `end_time` from `start_time + duration_hours`

### POST `/secretary/teaching-events/duplicate`

Duplicate an existing event (editable during duplication).

- **Auth:** secretary only
- **Body:**
```json
{
  "source_event_id": "uuid",
  "event_date": "2026-04-22",
  "start_time": "10:00",
  "duration_hours": 1.0,
  "teaching_name": "Journal Club"
}
```

### DELETE `/secretary/teaching-events/{id}`

Delete a teaching event.

- **Auth:** secretary only
- **Constraint:** Returns 409 Conflict if any attendance records exist against this event.

### POST `/secretary/teaching-events/series`

Create a recurring event series.

- **Auth:** secretary only
- **Body:**
```json
{
  "teaching_name": "Journal Club",
  "start_time": "10:00",
  "duration_hours": 1.0,
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
- **Backend:** Materializes individual `teaching_events` rows for each occurrence.

### DELETE `/secretary/teaching-events/series/{series_id}`

Delete a series. Options: `scope=single&event_id=X`, `scope=following&event_id=X`, `scope=all`.

- **Auth:** secretary only
- **Constraint:** Cannot delete individual events that have attendance records.

### GET `/secretary/cme-dashboard`

CME summary view for the secretary's posting site.

- **Auth:** secretary only
- **Response:** Events with CME/SMC data, attendance counts

### GET `/secretary/residents`

List residents currently posted to or native to the secretary's site.

- **Auth:** secretary only
- **Scope:** Returns residents where `resident_postings.posting_code = X-User-Site` for the current reporting period.

### GET `/secretary/teaching-name-options`

Get available teaching name keywords for the dropdown.

- **Auth:** secretary only
- **Scope:** Queries `teaching_targets.details_of_training` for all rows matching `posting_code = X-User-Site` **(TBD-1)**
- **Response:**
```json
{
  "options": [
    {"keyword": "Journal Club", "session_type": "Department/Programme Teaching [1h]"},
    {"keyword": "Case discussions with supervisor", "session_type": "Case-based Teaching [2h]"}
  ]
}
```

---

## Resident Endpoints

### GET `/resident/events`

List teaching events available for submission.

- **Auth:** resident only
- **Scope:**
  1. Get resident's current posting from `resident_postings` where today falls within `start_date..end_date` and `status IN ('active', 'loa_working')`. Use `ORDER BY start_date DESC LIMIT 1` as a tie-breaker if today falls exactly on a phase changeover date where two rows share the boundary.
  2. Get resident's native programme posting code (the posting that matches their `programme_code` — may be the same as current posting if not on rotation).
  3. Get teaching events at **either** the current posting code **or** the native programme posting code (union of both).
  4. Filter to events where `event_date <= today` (no future events).
  5. Exclude events the resident has already submitted attendance for.
  6. **TBD-1:** Further filter by programme-specific TTF keyword matching — only show events whose `teaching_name` appears in the resident's native programme TTF `details_of_training` for the respective posting.
- **Query params:** `date_from`, `date_to` (custom date range picker)
- **Response:** Array of teaching events with checkboxes state

### POST `/resident/attendance`

Submit attendance for one or more events (bulk or single).

- **Auth:** resident only
- **Body:**
```json
{
  "event_ids": ["uuid1", "uuid2", "uuid3"]
}
```
- **Backend:**
  1. Validates each event exists and is at the resident's current posting or native programme posting
  2. Validates that `event_date` falls within a `resident_postings` row for this resident at that posting code with `status IN ('active', 'loa_working')`. Rejects with `422` if the event predates the resident's tenure at that posting — prevents back-dated submissions for postings the resident has left or not yet started.
  3. Validates no duplicate (UNIQUE constraint)
  4. Creates attendance records
  5. Triggers compliance recalculation (JIT)
- **Response:**
```json
{
  "submitted": 3,
  "errors": []
}
```

### DELETE `/resident/attendance/{attendance_id}`

Delete own submitted attendance (to fix mistakes).

- **Auth:** resident only
- **Constraint:** Can only delete own records.

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
      "submitted_at": "2026-04-10T14:30:00Z"
    }
  ]
}
```

---

## Auth Endpoints

### POST `/auth/login`

Unified login endpoint. Behaviour differs by `role`:

- **Body (admin / secretary):**
```json
{
  "role": "admin",
  "email": "pc@nhg.com.sg",
  "password": "password"
}
```
Looks up `users` table by email. Validates password hash. Returns JWT with `role`, `sub` (users.id), `programme_scope` (admin) or `posting_code` (secretary).

- **Body (resident):**
```json
{
  "role": "resident",
  "mcr": "M12345A"
}
```
Looks up `residents` table by MCR. Validates `status != 'inactive'`. **No password required in Phase 1.** Returns JWT with `role = 'resident'`, `sub` (residents.id), `programme_code`.

- **Response (all roles):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": "<uuid>",
    "role": "resident",
    "name": "John Tan",
    "programme_code": "GRM",   // resident only
    "mcr": "M12345A"           // resident only
  }
}
```

- **Error responses:**
  - `401` — MCR not found or resident is inactive
  - `401` — Invalid email or password (admin/secretary)
  - `403` — Resident account inactive (`residents.status = 'inactive'`)

### GET `/auth/me`

Return current identity from the validated JWT.

- **Response shape differs by role:**
  - Admin/Secretary: returns `users` row fields + `programme_scope` or `posting_code`
  - Resident: returns `residents` row fields + current posting (derived live from `resident_postings`)

### PUT `/auth/settings`

Update password. Resident accounts have no password so this endpoint is admin/secretary only.

- **Auth:** admin, secretary only
- **Body:** `{ "current_password": "old", "new_password": "new" }`

---

## Common Error Responses

```json
{ "detail": "Unauthorized" }                                           // 401
{ "detail": "Forbidden — admin role required" }                         // 403
{ "detail": "Teaching event not found" }                                // 404
{ "detail": "Cannot delete event with attendance" }                     // 409
{ "detail": "Duplicate attendance submission" }                         // 409
{ "detail": "Another TTF upload for this scope is in progress" }        // 409
{ "detail": "Reporting period is closed" }                              // 422
{ "detail": "TTF validation failed", "errors": [...] }                  // 422
{ "detail": "TTF re-upload blocked: session types with existing attendance cannot be removed or changed", "affected_session_types": [...] }  // 422
{ "detail": "Attendance submission invalid: event date is outside your tenure at this posting" }  // 422
```