# API Endpoints

Base URL: `http://localhost:8000/api/v1`

---

## Authentication Model

There are separate identity paths. They share the JWT infrastructure but resolve identity from different tables and carry different claims.

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

### Path 3 — External Residents (`external_residents` table)

External/cross-cluster residents are **not** in the `users` table and are **not** native `residents`. They self-register first, then authenticate with their **MCR number only**. Allowed `home_cluster` values are strictly `NUH` and `SingHealth`. The JWT payload carries:

```json
{
  "sub": "<external_residents.id>",
  "role": "external_resident",
  "mcr": "M12345A",
  "home_cluster": "NUH"
}
```

`current_nhg_posting_code` is not trusted from JWT for authorization-sensitive reads; fetch it from `external_residents` at request time. External residents do not receive NHG compliance or clawback surfaces.

**Global MCR uniqueness:** `POST /external-residents/register` must reject an MCR that already exists in either native `residents` or `external_residents`.

### How the compliance chain resolves from login

1. Resident logs in with MCR → JWT issued with `programme_code = 'GRM'`
2. On `GET /resident/events` or `GET /resident/dashboard`:
   - Current posting derived from `resident_postings` WHERE today falls within `start_date..end_date` AND `status IN ('active', 'loa_working')`
   - Compliance targets from `teaching_targets` WHERE `programme_code = 'GRM'` AND `posting_code` from current phase AND `r_year` from **resident_postings row** (not residents.r_year) AND `reporting_period_id` from the active/effectively active period

### Request identity headers (Phase 1 stub)

```
X-User-Role: admin | secretary | resident | external_resident
X-User-Id: <users.id for admin/secretary> | <residents.id for resident> | <external_residents.id for external_resident>
Resident login accepts MCR only. Protected resident requests use residents.id as the authenticated subject. The resident MCR may be carried as a claim/header for convenience, but it is not used as X-User-Id.
X-User-Programme: <programme_code>   # resident and admin only
X-User-Site: <posting_code>          # secretary only
```

---

## Cross-Cutting API Security, Validation, Rate Limiting, and Caching

These rules apply to every endpoint unless a stricter endpoint-specific rule is documented.

### Request validation and sanitisation

- Validate all request bodies, query parameters, path parameters, and uploaded files with Pydantic schemas or explicit parser validation before any database write.
- Reject unknown enum values with `422` unless the relevant parser spec explicitly says the value is stored with a warning.
- Normalize user-controlled string inputs by trimming leading/trailing whitespace and rejecting control characters where not meaningful.
- Do not use client-provided filenames for storage paths or parser selection. Upload slot determines parser selection; filename is audit-only.
- Enforce server-side file validation on upload endpoints:
  - allowed extensions: `.xlsx` for RDB, TTF, FormF1; `.xlsx` or `.csv` for public holidays
  - validate MIME/content where practical
  - enforce maximum upload size from config
  - reject password-protected or unreadable workbooks with `422`
- All write endpoints must be idempotent only where explicitly documented. Otherwise duplicate/conflict cases return `409`.

### SQL injection protection

- Use SQLAlchemy ORM/query builder or parameterised raw SQL only.
- Never interpolate user input into SQL strings, including identifiers, sort fields, filters, search terms, or `ORDER BY` clauses.
- For dynamic sorting/filtering, map accepted public field names to hardcoded model columns.
- PostgreSQL advisory-lock keys must be derived from validated internal IDs or deterministic hashes, not raw concatenated user strings.

### XSS and response safety

- API responses are JSON by default and must not intentionally return executable HTML.
- Do not trust stored free-text fields such as `teaching_name`, `details_of_training`, `posting_code`, `display_name`, or uploaded filename. They must be treated as plain text by the frontend.
- Backend-generated export files must escape spreadsheet formula injection. Any exported cell beginning with `=`, `+`, `-`, or `@` from user-controlled data must be prefixed safely before writing CSV/XLSX.
- Error responses must not leak stack traces, SQL errors, internal paths, environment variables, secrets, or raw parser internals.
- Security headers middleware should set at least:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - a restrictive `Content-Security-Policy` for any non-API responses

### Authentication and authorization

- All non-auth endpoints require authenticated identity from middleware.
- Authorization is server-side only. Frontend role checks are UX only.
- Admin access is programme-scoped via `users.programme_scope`; `NULL` means no access, not all-access.
- Secretary access is posting-scoped via `users.posting_code` / `X-User-Site`.
- Resident access is identity-scoped via `residents.id`; current posting is derived from `resident_postings` at request time.
- Do not expose resources across roles even when IDs are guessed correctly.

### Rate limiting

Implement rate limiting middleware before public/UAT use. In local Phase 1 it may be an in-memory implementation; production should use Redis or the deployment platform equivalent.

Required default limits, configurable via environment variables:

| Endpoint group | Suggested default | Key |
|---|---:|---|
| `POST /auth/login` | 5 attempts / minute | IP + role + identifier where available |
| `POST /admin/upload/*` | 10 uploads / hour | authenticated admin id + upload type |
| mutation endpoints (`POST`, `PUT`, `DELETE`) | 60 requests / minute | authenticated user id + route group |
| report/export endpoints | 20 requests / minute | authenticated user id + report type |
| resident attendance submission | 30 requests / minute | resident id |
| general authenticated `GET` endpoints | 300 requests / minute | authenticated user id |

When a limit is exceeded, return:

```json
{ "detail": "Too many requests" }
```

with HTTP `429` and `Retry-After` where possible.

### Caching policy

Caching is allowed only where it cannot violate role scope, freshness expectations, or auditability.

Required cache rules:

- Use a small cache abstraction/service rather than ad hoc module globals.
- Cache keys must include all scope-defining inputs, especially `role`, `user_id`, `programme_scope`, `programme_code`, `posting_code`, `resident_id`, `reporting_period_id`, and query params where relevant.
- Never cache authentication responses, raw uploaded files, mutation responses, or error responses containing validation details.
- Short-TTL cache is recommended for low-risk reference/config reads:
  - `programmes`
  - `loa_types`
  - `global_session_types`
  - `public_holidays`
  - `posting_groups`
  - `multi_posting_rules`
  - `weekend_exceptions`
  - `reporting_periods`
- Compliance/report cache is allowed only with scoped keys and explicit invalidation. Suggested TTL: 30–120 seconds during normal operation.
- Invalidate relevant cache entries after:
  - any RDB, TTF, FormF1, or public holiday upload
  - admin CRUD changes to config tables
  - secretary teaching event create/update/delete
  - resident attendance submit/delete
  - reporting period create/update/delete/activate/deactivate or scheduled transition edits
- Period snapshots remain future final-close artifacts; normal reporting-period activation/deactivation does not generate snapshots.
- If distributed deployment is used, replace in-memory cache with Redis or the platform cache so invalidation works across workers.

### Data Revalidation contract

Data Revalidation is the shared backend concept for assessing the impact of Admin/PC Live Data and Config mutations. The backend service boundary is `data_revalidation_service`; user-facing actions should use names such as `Revalidate data` and `Data revalidation impact summary`.

3H-B defines only the service contract and default response shape. 3H-C wires Admin Live Data correction mutations to that service and adds a `data_revalidation` impact summary to successful mutation responses and correction audit metadata. 3H-D wires Admin/PC Config CRUD mutations to the same service and adds the same `data_revalidation` impact summary to successful mutation responses and config audit metadata.

The current 3H-C wiring covers:
- `PATCH /admin/parsed-data/residents/{id}`
- `PATCH /admin/parsed-data/resident-postings/{id}`
- `POST /admin/parsed-data/resident-postings/source-cell-replace`
- `PATCH /admin/parsed-data/teaching-targets/{id}`
- `PATCH /admin/parsed-data/form-f1-records/{id}`
- `PATCH /admin/parsed-data/academic-month-boundaries/{id}`

The current 3H-D Config wiring covers successful creates, updates, deletes, and reporting-period activate/deactivate mutations for reporting periods, public holidays, programmes, LOA types, multi-posting rules, posting groups, weekend exceptions, and global session types. Create/update/activate/deactivate responses preserve the entity fields and add `data_revalidation`. Delete responses return `{ "entity_type": "...", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

3H-D still does not mutate warnings, run RDB source-cell parsing, re-resolve existing multi-posting rows, regenerate `resident_postings`, generate period snapshots, hibernate surplus, generate clawback rows, or perform compliance calculation. Multi-posting rule changes return `manual_revalidation_required` to indicate existing RDB source cells/warnings need an explicit later revalidation or future RDB re-upload. Reporting-period mutations return the default `future_compliance_impact` summary. Successful Data Revalidation summaries use one of these canonical outcomes:

- `no_op`
- `warning_only`
- `targeted_revalidation`
- `future_compliance_impact`
- `manual_revalidation_required`

Normal Refresh buttons remain read-only refetch actions. Any mutating recalculation must be exposed as a separate explicit Data Revalidation action. Use `reparse` only for low-level RDB source-cell parsing, not as the broad system concept. 3H-E2 adds first-class warning issue persistence and manual issue status actions only; concrete source-cell reparse, multi-posting re-resolution, resident posting regeneration, and compliance recalculation remain later handlers.

---

## Admin Endpoints

### POST `/admin/upload/rdb`

Upload RDB Posting Schedule Excel file.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID)
- **Processing:** See `docs/parsing.md` § RDB Parser
- **Re-upload semantics:** RDB uploads are complete snapshots for the selected reporting period. After successful parse/validation, existing `resident_postings` for the selected `reporting_period_id` are fully replaced in one transaction. If parse/validation fails, existing rows are left unchanged.
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

- **`unmatched_multi_posting` warning payload (when applicable):**
```json
{
  "type": "unmatched_multi_posting",
  "mcr": "M12345A",
  "resident_name": "Resident Name",
  "programme_code": "CARDIO",
  "month_label": "Aug-25",
  "sheet_name": "Phase 3",
  "row_number": 42,
  "cell_ref": "J42",
  "posting_codes": ["NHCCardio", "TTSHCardio"],
  "message": "No matching multi-posting rule found. Postings were persisted independently. Add a multi_posting_rule or correct the RDB source if needed."
}
```

- **`empty_posting_cell` warning payload (when applicable):**
```json
{
  "type": "empty_posting_cell",
  "severity": "info",
  "reporting_period_id": "<period_uuid>",
  "mcr": "M12345A",
  "resident_name": "Resident Name",
  "programme_code": "DR",
  "month_label": "Jul-25",
  "sheet_name": "Phase 1",
  "row_number": 3,
  "cell_ref": "I3",
  "source_payload": { "raw_value": null },
  "message": "No posting value found for this resident/month cell. No resident posting row was created.",
  "suggested_action": "Check whether the RDB source cell is intentionally blank. If not, update the RDB source file and re-upload."
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
- **Parsed/persisted fields only:** MCR, monthly status columns, and promotion date/senior promotion date. Other FormF1 profile/identity columns are non-authoritative and are not persisted from FormF1.
- **Column detection:** Dynamic header/column detection is preferred. Current-template fallback positions remain supported: column E = MCR, columns M–X = monthly statuses, column Y = promotion date.
- **Behaviour:** Full replace per `reporting_period_id` scope. Re-upload allowed at any time (e.g. to update for unforeseen LOAs). Promotion date is parsed and persisted but is not used by compliance yet.
- **422 fail-fast with no replacement:** If duplicate MCR validation fails, or if header/month-column detection is unsafe, return `422` and preserve existing `form_f1_records` rows for the period.
- **Audit log:** Writes `upload_logs` row with `upload_type = 'form_f1'`
- **Response:**
```json
{
  "records_created": 312,
  "records_updated": 0,
  "mcr_not_found_warnings": [],
  "skipped_mcr_warnings": [],
  "duplicate_mcr_errors": [],
  "month_labels_parsed": ["Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25", "Dec-25"],
  "active_count": 280,
  "inactive_count": 32,
  "promotion_dates_parsed": 74,
  "promotion_date_warnings": [],
  "errors": []
}
```

### GET `/admin/upload-warnings`

List first-class warning issues derived from `upload_logs.summary`.

- **Auth:** admin only
- **Query params:** `upload_log_id`, `upload_type`, `reporting_period_id`, `programme_code`, `warning_type`, `severity`, `status`, `mcr`, `month_label`, `search`, `limit`, `offset`
- **Scope:** Programme-scoped admins only see issues whose `programme_code` is in their scope. Master admins may see all issues.
- **Response:** Issue-centric rows. Existing upload-warning row fields are preserved where possible and enriched with `issue_id`, `status`, `latest_upload_warning_id`, and `latest_source_trace`.
- **Notes:** Upload warning issues are derived after successful upload-log creation. `upload_logs.summary` remains immutable; resolving/dismissing/superseding an issue does not edit historical upload summaries.

```json
[
  {
    "issue_id": "<warning_issue_uuid>",
    "status": "unresolved",
    "warning_id": "<latest_upload_warning_uuid>",
    "dedupe_key": "empty_posting_cell|<period>|DR|M12345A|Jul-25",
    "upload_log_id": "<latest_upload_log_uuid>",
    "upload_type": "rdb",
    "uploaded_at": "2026-06-17T09:00:00Z",
    "reporting_period_id": "<period_uuid>",
    "programme_code": "DR",
    "warning_type": "empty_posting_cell",
    "severity": "info",
    "message": "No posting value found for this resident/month cell. No resident posting row was created.",
    "mcr": "M12345A",
    "month_label": "Jul-25",
    "sheet_name": "Phase 1",
    "row_number": 3,
    "cell_ref": "I3",
    "seen_count": 1,
    "latest_upload_warning_id": "<upload_warning_uuid>",
    "latest_source_trace": {
      "sheet_name": "Phase 1",
      "row_number": 3,
      "cell_ref": "I3"
    },
    "reappeared": false
  }
]
```

### GET `/admin/upload-warnings/{warning_issue_id}`

Return one warning issue plus all upload warning occurrences that have the same deterministic fingerprint.

- **Auth:** admin only
- **Scope:** Same programme-scope rules as the list endpoint
- **Response:** Issue metadata, resolution metadata, and `occurrences[]`

### POST `/admin/upload-warnings/{warning_issue_id}/resolve`
### POST `/admin/upload-warnings/{warning_issue_id}/dismiss`
### POST `/admin/upload-warnings/{warning_issue_id}/supersede`

Manually update a warning issue status.

- **Auth:** admin only
- **Body:** `{ "note": "optional admin note" }`
- **Audit:** Writes an audit log row with actor, action, before/after status, and warning scope metadata.
- **Behaviour:** Does not mutate `upload_logs.summary`, does not run RDB source-cell parsing, does not regenerate `resident_postings`, and does not calculate compliance.
- **Reappearance:** If the same fingerprint appears in a later upload after an issue was `resolved`, `dismissed`, or `superseded`, its status becomes `reappeared` while preserving the previous resolution note/actor/timestamp.

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

List all multi-posting rules. The Admin configuration UI presents these rows in three logical tabs:
- Main Posting (`rule_type = "main_posting"`)
- To Combine Posting (`rule_type = "combine"`)
- Half Month Posting (`rule_type = "half_month"`)

- **Auth:** admin only
- **Query params:** `programme_code`, `rule_type` (optional)
- **Authorization:** `programme_code`, when supplied, must be within the admin's `programme_scope`. If omitted, return only rows for programmes in scope.
- **Ordering:** Stable order by `programme_code`, `rule_type`, `posting_code_1`, `posting_code_2`.

### POST `/admin/multi-posting-rules`

Add a new multi-posting rule. This is the long-term PC workflow for maintaining rules after the initial seed/update from `Multiple postings per month.xlsx`; that workbook is not a recurring upload endpoint.

- **Auth:** admin only
- **Authorization:** `programme_code` must be within the admin's `programme_scope`.
- **Duplicate handling:** Return `409` if a row already exists for `(programme_code, posting_code_1, posting_code_2, rule_type)`. Pair matching should also check the reverse pair for `combine` and `half_month` unless order is explicitly meaningful for the rule.
- **Conflict validation:** Return `422` when the output fields do not match the rule type, for example `combine` without `combined_label`, `half_month` with output fields set, or `main_posting` without `main_posting_code`.
- **Posting validation:** All posting codes referenced by `posting_code_1`, `posting_code_2`, `combined_label`, `main_posting_code`, and `exclusion_code` must exist in `posting_codes` or be created as dormant posting codes before insertion.
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
- **Authorization:** The existing row's `programme_code` and any replacement `programme_code` must be within the admin's `programme_scope`.
- **Duplicate/conflict handling:** Same validation as create. Return `409` if the update would duplicate another row's `(programme_code, posting_code_1, posting_code_2, rule_type)`.
- **Scope safety:** Do not allow a PC to move a rule into or out of a programme they cannot administer.

### DELETE `/admin/multi-posting-rules/{id}`

Delete a multi-posting rule.

- **Auth:** admin only
- **Authorization:** The row's `programme_code` must be within the admin's `programme_scope`.
- **Behaviour:** Deleting a rule does not delete existing `resident_postings`. The effect is seen on the next RDB re-upload or future parse.
- **Response:** `200` with `{ "entity_type": "multi_posting_rule", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

**Rule-specific API semantics:**
- `main_posting`: Used by FM Main Posting tab. Rows with `posting_code_2 = null` define the recognised `RDB Posting #1` trigger list. `exclusion_code` is the configured zero-match fallback, usually `NHGPlyNHGPly`.
- `combine`: Used by To Combine Posting tab. Two posting codes collapse to `combined_label`.
- `half_month`: Used by Half Month Posting tab. Two posting codes split into independent rows with `active_months_weight = 0.5`.

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
- **Response:** `200` with `{ "entity_type": "posting_group", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

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
- **Response:** `200` with `{ "entity_type": "weekend_exception", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

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
- **Response:** `200` with `{ "entity_type": "loa_type", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

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
- **Response:** `200` with `{ "entity_type": "global_session_type", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

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
  "end_date": "2026-07-06",
  "status": "active",
  "activate_on": null,
  "deactivate_on": null
}
```

`status` is optional on create and defaults to `active`. Only `active` and `inactive` are accepted; legacy `open`/`closed` values are rejected. `activate_on` and `deactivate_on` are optional scheduled transition dates. If both are supplied, `activate_on <= deactivate_on` is required.

### PUT `/admin/reporting-periods/{id}`

Update a reporting period label, date range, stored status, or scheduled transition dates.

- **Auth:** admin only
- **Body:** any subset of `label`, `start_date`, `end_date`, `status`, `activate_on`, `deactivate_on`.
- **Validation:** `start_date <= end_date`, `status` is `active` or `inactive`, and the resolved `activate_on/deactivate_on` pair must satisfy `activate_on <= deactivate_on` when both are set.
- **Response:** existing reporting-period entity fields plus `data_revalidation`.

### PUT `/admin/reporting-periods/{id}/activate`

Set `reporting_periods.status = 'active'`.

- **Auth:** admin only
- **Response:** existing reporting-period entity fields plus `data_revalidation`.

### PUT `/admin/reporting-periods/{id}/deactivate`

Set `reporting_periods.status = 'inactive'`.

- **Auth:** admin only
- **Important:** Deactivation is an operational status change only. It does not generate snapshots, clawback rows, or surplus hibernation.
- **Response:** existing reporting-period entity fields plus `data_revalidation`.

### DELETE `/admin/reporting-periods/{id}`

Delete an unused reporting period.

- **Auth:** admin only
- **Response:** `200` with `{ "entity_type": "reporting_period", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

### Reporting-period effective status

Resident-facing default period resolution uses the effective status, not only the stored `status` column:

```json
{
  "status": "active",
  "activate_on": "2026-01-06",
  "deactivate_on": "2026-07-06"
}
```

The stored status remains `active` or `inactive`; due scheduled dates are resolved at read time and do not mutate the row. When both scheduled dates are due, the later scheduled date wins; if both are due on the same date, deactivation wins. With no active/effectively active period, resident event listing returns an empty list with `reason = "active_reporting_period_unavailable"` and ad-hoc disabled; attendance and ad-hoc submission endpoints reject with `422`.

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

Upload the Academic Calendar / Public Holiday workbook to seed:
- `public_holidays` (from `Public Holidays` sheet)
- `academic_month_boundaries` (from `AY Dates` sheet)

Endpoint name remains unchanged for backward compatibility.

- **Auth:** admin only
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx or csv)
- **Parser selection:** endpoint/upload slot determines parser; filename is audit-only
- **Sheet handling:**
  - parse `Public Holidays`
  - parse `AY Dates`
  - ignore `Fr RMT`
- **Public Holidays behaviour:** Upsert on `holiday_date` — safe to re-run. Day-of-week mismatch returns a warning but does not fail.
- **AY Dates behaviour:** Requires both `im_subspec` and `non_im_subspec` category tables; header SR/SRs wording is accepted and ignored semantically.
- **Audit log:** Writes `upload_logs` row with `upload_type = 'public_holidays'`
- **Response:**
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

### DELETE `/admin/public-holidays/{id}`

Delete a single public holiday entry.

- **Auth:** admin only
- **Response:** `200` with `{ "entity_type": "public_holiday", "entity_id": "...", "deleted": true, "data_revalidation": {...} }`.

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
- **Scope:** Reads from `clawback_records` table generated by a future final close/freeze flow. All rows shown — including suppressed rows (Extension, R7) with `clawback_amount = 0` and `clawback_suppressed_reason` displayed.
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

Export a historical period snapshot as Excel. Available for finalized/frozen period snapshots only. Final close/freeze behavior is deferred and is separate from active/inactive operational status.

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

Get available teaching name keywords for the secretary event-creation dropdown.

- **Auth:** secretary only
- **Scope:** Returns a unified, deduplicated list combining:
  1. Keywords from `teaching_name_catalogue` for the secretary’s **native programme teaching pool**, not only the exact `posting_code = X-User-Site`.
  2. Active entries from `global_session_types` (compliance-exempt, available to all secretaries).

For the TTSH pilot workflow, a secretary assigned to a native department/site such as `TTSHGerMed` should be able to create teaching events using the deduplicated teaching-name pool from the relevant native programme TTF, e.g. `GERI`, across that programme’s applicable postings.

This allows one secretary-created event list to support residents from the same native programme who may currently be posted to different sites/postings, while resident visibility and compliance counting remain resolved per resident context.

- **Resident visibility/compliance:** Event creation only stores the selected `teaching_name`. Whether a resident sees or counts that event is still resolved later using the resident’s own:
  - `programme_code`
  - current `resident_postings.posting_code`
  - `resident_postings.r_year`
  - `reporting_period_id`
  - matching `teaching_name_catalogue` rows

- **Response:**

```json
{
  "options": [
    {
      "keyword": "Journal Club",
      "session_type": "Department/Programme Teaching [1h]",
      "duration_hours": 1.0,
      "is_tracked": true,
      "is_global": false,
      "posting_codes": ["TTSHGerMed", "TTSHContCC"]
    },
    {
      "keyword": "Case discussions with supervisor",
      "session_type": "Case-based Teaching [2h]",
      "duration_hours": 2.0,
      "is_tracked": true,
      "is_global": false,
      "posting_codes": ["TTSHGerMed"]
    },
    {
      "keyword": "Department Meeting",
      "session_type": "Department Meeting [1h]",
      "duration_hours": 1.0,
      "is_tracked": false,
      "is_global": true,
      "posting_codes": []
    }
  ]
}
```
Deduplication: If the same keyword appears in multiple teaching_name_catalogue rows within the secretary’s native programme teaching pool, return it once. Where useful, include the contributing posting_codes.

Session type ambiguity: If the same keyword maps to multiple session_type values across postings, the endpoint may return one option with the keyword and omit or null ambiguous session-type metadata. Compliance must not rely on the secretary dropdown’s displayed session type; compliance is resolved per resident at read time from teaching_name_catalogue.

Note: is_global = true entries come from global_session_types and are always excluded from PTT compliance. is_tracked = false entries from the TTF are also shown but excluded from compliance. Secretary sees a unified list — the compliance distinction is transparent to them.

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

## External Resident Endpoints

External residents are future Phase 5B scope. They use separate identity and attendance tables. They are never stored in `users`, never stored in native `residents`, and never represented through `resident_postings`.

### POST `/external-residents/register`

Self-register an external/cross-cluster resident.

- **Auth:** public/self-service with rate limiting
- **Body:**
```json
{
  "name": "Resident Name",
  "mcr": "M12345A",
  "home_cluster": "NUH",
  "current_nhg_posting_code": "TTSHGerMed"
}
```
- **Validation:**
  1. `home_cluster` must be `NUH` or `SingHealth`.
  2. `mcr` must not exist in native `residents`.
  3. `mcr` must not exist in `external_residents`.
  4. `current_nhg_posting_code` must exist in `posting_codes`.
- **Writes:** `external_residents` only. Do not create `users`, native `residents`, or `resident_postings` rows.
- **Duplicate/conflict:** `409` when MCR already exists.

### PUT `/external-residents/me/posting`

Update the external resident's current NHG posting.

- **Auth:** external resident only
- **Body:**
```json
{
  "current_nhg_posting_code": "KTPHGerMed"
}
```
- **Validation:** posting code must exist in `posting_codes`.
- **Behaviour:** updates `external_residents.current_nhg_posting_code`. No native `resident_postings` rows are created.

### GET `/resident/events` for external residents

The same route may support native and external residents through identity branching.

- For native `role = resident`, use native Phase 5A behaviour from `resident_postings`.
- For `role = external_resident`, derive current posting from `external_residents.current_nhg_posting_code`.
- If the posting's `posting_codes.supports_secretary_events = true`, return eligible secretary-created events for that posting.
- If `supports_secretary_events = false`, return no secretary-created event list but keep ad-hoc submission available in the frontend.
- Filter `event_date <= today`.
- Exclude events already submitted by that external resident in `external_attendance_records`.
- Do not apply native NHG compliance catalogue/denominator logic to external residents.

### POST `/resident/attendance` for external residents

The same route may support native and external residents through identity branching.

- For `role = external_resident`, validate the event belongs to the external resident's current NHG posting.
- Create `external_attendance_records`, not native `attendance_records`.
- Duplicate protected by `UNIQUE(external_resident_id, teaching_event_id)`.
- Weekend non-exception attendance is stored and returns `compliance_warning`.
- Do not store `session_type_id`.
- Do not include the row in NHG compliance.

### POST `/resident/adhoc-teaching` for external residents

The same route may support native and external residents through identity branching.

- For `role = external_resident`, derive posting from `external_residents.current_nhg_posting_code`.
- PH hard-block with `422`.
- Create `teaching_events` with `is_adhoc = true`, `created_by_role = 'external_resident'`, and `posting_code = current_nhg_posting_code`.
- Create `external_attendance_records` in the same transaction.
- Weekend non-exception attendance is stored and returns `compliance_warning`.
- Do not create native `attendance_records`.

### GET `/resident/attendance-history`

Return the authenticated resident's past submitted attendance.

- **Auth:** native resident or external resident
- **Native resident:** read from `attendance_records` scoped by `resident_id`.
- **External resident:** read from `external_attendance_records` scoped by `external_resident_id`.
- **Filters:** `date_from`, `date_to`, `status` optional.

### GET `/resident/dashboard` for external residents

External residents do not receive an NHG compliance dashboard.

- **Auth:** external resident only
- **Response:**
```json
{
  "compliance_status": "not_applicable",
  "reason": "external_resident_excluded_from_nhg_compliance",
  "message": "External resident attendance is stored for future export to the home cluster PC. NHG compliance and clawback do not apply."
}
```

### External attendance export

External attendance export for NHG PCs is **TBD/deferred** until dashboard/export requirements are confirmed. Do not implement CSV/XLSX/email/export endpoints yet. Ensure `external_attendance_records` remains queryable for future export work.

---

## Common Error Responses

```json
{ "detail": "Unauthorized" }                                                    // 401
{ "detail": "Forbidden — admin role required" }                                  // 403
{ "detail": "Teaching event not found" }                                         // 404
{ "detail": "Cannot delete event with attendance" }                              // 409
{ "detail": "Duplicate attendance submission" }                                  // 409
{ "detail": "Another TTF upload for this scope is in progress" }                 // 409
{ "detail": "No active reporting period is available" }                          // 422
{ "detail": "TTF validation failed", "errors": [...] }                           // 422
{ "detail": "Event date is a public holiday — event creation not allowed" }      // 422
{ "detail": "Attendance submission invalid: event date is outside your tenure at this posting" }  // 422
{ "detail": "Teaching name not found in catalogue for your programme and posting" }  // 422
```
