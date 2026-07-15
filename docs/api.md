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
  "iss": "mata-api",
  "aud": "mata-resident-session",
  "sub": "<residents.id>",
  "role": "resident",
  "app_role": "resident",
  "mcr": "M12345A",
  "programme_code": "GRM",
  "iat": 12345678,
  "exp": 12345678
}
```

In stub/demo mode this is represented by the local session/header shim. In `AUTH_MODE=supabase`, NHG Residents still do not get Supabase Auth accounts; backend `/auth/login` validates MCR against active `residents` rows and issues a backend-signed MATA resident session token using server-only `MATA_RESIDENT_SESSION_SECRET`. The MATA resident token must not include current posting, staff actor name, `admin_level`, or `programme_scope`.

`programme_code` is embedded at login time from `residents.programme_code`. It scopes all compliance lookups to the resident's native programme. **`posting_code` is NOT in the JWT** — current posting is always derived at request time from `resident_postings`.

### Path 3 — Non-NHG Residents (`external_residents` table)

Non-NHG/cross-cluster residents are **not** in the `users` table and are **not** native `residents`. They self-register first, then authenticate with their **MCR number only**. Allowed `home_cluster` values are strictly `NUH` and `SingHealth`. The JWT payload carries:

```json
{
  "iss": "mata-api",
  "aud": "mata-resident-session",
  "sub": "<external_residents.id>",
  "role": "external_resident",
  "app_role": "external_resident",
  "mcr": "E12345A",
  "home_cluster": "NUH",
  "iat": 12345678,
  "exp": 12345678
}
```

In `AUTH_MODE=supabase`, Non-NHG Residents do not get Supabase Auth accounts. Backend `/auth/login` validates MCR against active `external_residents` rows and issues a backend-signed MATA resident session token using server-only `MATA_RESIDENT_SESSION_SECRET`. The token must not include current posting, posting schedule, staff actor name, `admin_level`, `programme_code`, `programme_scope`, or `posting_code`.

Posting state and posting schedule are not trusted from JWT for authorization-sensitive reads. Fetch the Non-NHG Resident from `external_residents` and derive date-specific posting from `external_resident_postings` where relevant. `external_residents.current_nhg_posting_code` may remain a current/cache/backward-compatibility pointer, but schedule-aware resident flows use `external_resident_postings`. Non-NHG Residents do not receive NHG compliance or clawback surfaces.

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
- `POST /admin/upload-warnings/{warning_issue_id}/source-cell-replace/preview`
- `POST /admin/upload-warnings/{warning_issue_id}/source-cell-replace/apply`
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

Frontend-facing `data_revalidation` responses expose stable summary fields at the top level and preserve the richer service payload under `details`. Top-level fields may be `null` or empty when the handler has no warning/config enrichment to report.

```json
{
  "outcome": "manual_revalidation_required",
  "trigger_source": "admin_config_change",
  "changed_entity": "multi_posting_rule",
  "action": "create",
  "scope": "programme_reporting_period",
  "summary": "1 durable upload warning issue may be affected by this config change.",
  "reason": "1 durable upload warning issue may be affected by this config change.",
  "affected_scope": {
    "programme_code": "DR",
    "reporting_period_id": "00000000-0000-0000-0000-000000000001"
  },
  "affected_warning_count": 1,
  "affected_warning_issue_ids": ["10000000-0000-0000-0000-000000000001"],
  "affected_warning_summaries": [
    {
      "warning_issue_id": "10000000-0000-0000-0000-000000000001",
      "latest_upload_warning_id": "20000000-0000-0000-0000-000000000001",
      "warning_type": "unmatched_multi_posting",
      "status": "unresolved",
      "programme_code": "DR",
      "message": "No matching multi-posting rule found."
    }
  ],
  "affected_warning_count_is_partial": false,
  "affected_warning_details_are_partial": false,
  "warning_candidate_limit": 200,
  "warning_candidate_limit_reached": false,
  "affected_entity_counts": {},
  "next_actions": [
    "Review affected durable upload warnings; use source-cell preview/apply where appropriate."
  ],
  "enrichment_version": "3H-E4",
  "details": {
    "affected_warning_count": 1,
    "warning_candidate_limit": 200,
    "warning_candidate_limit_reached": false
  }
}
```

In `AUTH_MODE=supabase`, protected staff requests use a Supabase Auth access token. The Supabase token `sub` is `auth.users.id` and maps to `users.supabase_user_id`; the backend then derives `role`, `admin_level`, `programme_scope`, `posting_code`, and saved staff actor metadata from the active `users` row. Protected NHG Resident requests use the backend-signed MATA resident token issued by `/auth/login`; the backend verifies its MATA issuer/audience/signature/expiry, reloads the active `residents` row by `sub`, and derives resident identity from that row. Protected Non-NHG Resident requests use the same MATA issuer/audience/signature/expiry path with `role/app_role = external_resident`; the backend reloads the active `external_residents` row by `sub` and derives external resident identity from that row. Raw client headers and Supabase `user_metadata` are not authorization sources.

5B-E staff accounts are generic role accounts. `users.name` is the account display name. `current_staff_actor_name` is a self-declared current human name used for audit/display context only; it never grants role, programme scope, admin level, or posting scope. Browser-visible `Authorization: Bearer <Supabase access token>` and `Authorization: Bearer <MATA resident token>` transport remains the temporary 5B-D2/5B-F-B implementation. TODO 5B-H: replace browser-visible bearer transport with backend-managed `HttpOnly`, `Secure`, `SameSite` cookies/BFF flow plus CSRF protection.

When `warning_candidate_limit_reached = true`, the backend has capped the warning candidate scan. `affected_warning_count_is_partial = true` means `affected_warning_count` is the capped count, not an exact total. `affected_warning_details_are_partial = true` means `affected_warning_issue_ids` and `affected_warning_summaries` are intentionally bounded for response size.

Config mutation responses keep the entity fields at the top level and add `data_revalidation`:

```json
{
  "id": "30000000-0000-0000-0000-000000000001",
  "programme_code": "DR",
  "posting_code_1": "TTSHDR",
  "posting_code_2": "KTPHDR",
  "rule_type": "combine",
  "combined_label": "TTSHDR-KTPHDR",
  "main_posting_code": null,
  "exclusion_code": null,
  "data_revalidation": {
    "outcome": "manual_revalidation_required",
    "affected_warning_count": 1,
    "affected_warning_issue_ids": ["10000000-0000-0000-0000-000000000001"],
    "affected_warning_count_is_partial": false,
    "affected_warning_details_are_partial": false,
    "warning_candidate_limit": 200,
    "warning_candidate_limit_reached": false,
    "next_actions": [
      "Review affected durable upload warnings; use source-cell preview/apply where appropriate."
    ],
    "details": {
      "affected_warning_count": 1,
      "affected_warning_details_are_partial": false
    }
  }
}
```

Normal Refresh buttons remain read-only refetch actions. Any mutating recalculation must be exposed as a separate explicit Data Revalidation action. Use `reparse` only for low-level RDB source-cell parsing, not as the broad system concept. 3H-E2 adds first-class warning issue persistence and manual issue status actions only. 3H-E3 adds explicit admin-triggered preview/apply for one RDB source cell linked to a durable warning issue. It does not mutate `upload_logs.summary`, run a full RDB re-upload, re-resolve impacted multi-posting rules globally, regenerate all `resident_postings`, calculate compliance, generate snapshots, hibernate surplus, or generate clawback.

### Cache-aware frontend refetch guidance

No push/live-update channel is implied in the current backend. After successful mutations, the frontend should refetch the affected views:

- After warning resolve/dismiss/supersede: refetch warning list/counts and the affected warning detail.
- After source-cell apply: refetch warning list/detail, parsed-data resident posting views, and relevant report/dashboard reads when those views exist.
- After source-cell preview: do not refetch for cache invalidation; preview is read-only.
- After config CRUD: refetch the config table and any visible Data Revalidation or warning-impact summaries.
- After uploads: refetch upload logs, warning lists, parsed data, and affected config/reference views.

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
- **Target validation:** `monthly_target` must be a non-negative whole number. `0` is accepted and remains catalogue-seeded, event-visible, and attendance-capable, but is excluded from compliance aggregation.
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
- **Monthly-status normalisation:** `Active` and `Extension` persist as active. `Inactive`, blank, `NULL`, and whitespace-only cells persist as inactive records for valid MCR rows. Unknown non-blank values preserve their raw value, retain the active fallback, do not fail the upload, and emit a persisted `unknown_formf1_status` warning containing the value and Excel cell reference. Blank values do not generate this warning.
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
- **Response:** Issue-centric rows. `issue_id` and `warning_issue_id` are the durable issue id. `warning_id` is a backwards-compatible alias for the latest occurrence id; new frontend code should prefer `upload_warning_id` / `latest_upload_warning_id`.
- **Notes:** Upload warning issues are derived after successful upload-log creation. `upload_logs.summary` remains immutable; resolving/dismissing/superseding an issue does not edit historical upload summaries.

```json
[
  {
    "issue_id": "<warning_issue_uuid>",
    "warning_issue_id": "<warning_issue_uuid>",
    "status": "unresolved",
    "warning_id": "<latest_upload_warning_uuid>",
    "upload_warning_id": "<latest_upload_warning_uuid>",
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
    "latest_upload_warning_id": "<latest_upload_warning_uuid>",
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

```json
{
  "issue_id": "<warning_issue_uuid>",
  "warning_issue_id": "<warning_issue_uuid>",
  "fingerprint": "empty_posting_cell|<period>|DR|M12345A|Jul-25",
  "warning_type": "empty_posting_cell",
  "severity": "info",
  "status": "unresolved",
  "reappeared": false,
  "latest_upload_warning_id": "<latest_upload_warning_uuid>",
  "latest_source_trace": {
    "sheet_name": "Phase 1",
    "row_number": 3,
    "cell_ref": "I3"
  },
  "latest_source_payload": {
    "type": "empty_posting_cell",
    "raw_value": null
  },
  "message": "No posting value found for this resident/month cell. No resident posting row was created.",
  "suggested_action": "Check whether the RDB source cell is intentionally blank.",
  "resolution_note": null,
  "resolved_by": null,
  "resolved_at": null,
  "occurrences": [
    {
      "id": "<latest_upload_warning_uuid>",
      "issue_id": "<warning_issue_uuid>",
      "upload_log_id": "<upload_log_uuid>",
      "source_trace": {
        "sheet_name": "Phase 1",
        "row_number": 3,
        "cell_ref": "I3"
      },
      "source_payload": {
        "type": "empty_posting_cell",
        "raw_value": null
      },
      "message": "No posting value found for this resident/month cell. No resident posting row was created."
    }
  ]
}
```

### POST `/admin/upload-warnings/{warning_issue_id}/resolve`
### POST `/admin/upload-warnings/{warning_issue_id}/dismiss`
### POST `/admin/upload-warnings/{warning_issue_id}/supersede`

Manually update a warning issue status.

- **Auth:** admin only
- **Body:** `{ "note": "optional admin note" }`
- **Audit:** Writes an audit log row with actor, action, before/after status, and warning scope metadata.
- **Behaviour:** Does not mutate `upload_logs.summary`, does not run RDB source-cell parsing, does not regenerate `resident_postings`, and does not calculate compliance.
- **Reappearance:** If the same fingerprint appears in a later upload after an issue was `resolved`, `dismissed`, or `superseded`, its status becomes `reappeared` while preserving the previous resolution note/actor/timestamp.
- **Response:**
```json
{
  "issue_id": "<warning_issue_uuid>",
  "status": "resolved",
  "previous_status": "unresolved",
  "new_status": "resolved",
  "resolution_note": "Resolved after source correction.",
  "note": "Resolved after source correction.",
  "resolved_by": "<actor_user_uuid>",
  "actor_user_id": "<actor_user_uuid>",
  "resolved_at": "2026-06-19T09:00:00Z",
  "updated_at": "2026-06-19T09:00:00Z"
}
```

### POST `/admin/upload-warnings/{warning_issue_id}/source-cell-replace/preview`

Preview a single RDB source-cell replacement linked to a durable upload warning issue.

- **Auth:** admin only
- **Scope:** Same programme-scope rules as the warning issue endpoints. Non-master admins with null/empty programme scope have no access. Master admin access is explicit via admin level.
- **Allowed warnings:** RDB `empty_posting_cell` and `unmatched_multi_posting` source-cell warning issues.
- **Body:**
```json
{
  "replacement_raw_cell_value": "TTSHAnaes",
  "upload_warning_id": "<optional latest occurrence uuid>",
  "expected_latest_upload_warning_id": "<optional stale-context guard>",
  "expected_fingerprint": "<optional stale-context guard>"
}
```
- **Behaviour:** Parses the replacement with RDB cell normalisation, LOA parsing, and multi-posting rule handling. Does not write `resident_postings`, `posting_codes`, `upload_logs`, `upload_warnings`, or `warning_issues`.
- **Response:** Includes warning identifiers, source trace, normalized value, parsed candidate rows, parser warnings/errors, `apply_allowed`, `data_revalidation`, and a manual resolve/dismiss next-action hint.

The `data_revalidation` object below is abbreviated to the fields most relevant to this flow; the full object follows the Data Revalidation contract above.

```json
{
  "warning_issue_id": "<warning_issue_uuid>",
  "upload_warning_id": "<latest_upload_warning_uuid>",
  "latest_upload_warning_id": "<latest_upload_warning_uuid>",
  "fingerprint": "empty_posting_cell|<period>|DR|M12345A|Jul-25",
  "source_trace": {
    "reporting_period_id": "<period_uuid>",
    "programme_code": "DR",
    "mcr": "M12345A",
    "month_label": "Jul-25",
    "sheet_name": "Phase 1",
    "row_number": 3,
    "cell_ref": "I3",
    "source_payload": { "type": "empty_posting_cell", "raw_value": null }
  },
  "source_payload": { "type": "empty_posting_cell", "raw_value": null },
  "original_warning_type": "empty_posting_cell",
  "original_warning_status": "unresolved",
  "replacement_raw_cell_value": "TTSHAnaes",
  "normalized_cell_value": "TTSHAnaes",
  "parsed_candidate_rows": [
    { "posting_code": "TTSHAnaes", "status": "active", "month_label": "Jul-25" }
  ],
  "parser_warnings": [],
  "parser_errors": [],
  "apply_allowed": true,
  "data_revalidation": { "outcome": "warning_only" },
  "suggested_next_action": "Review the preview/apply result, then manually resolve the warning if the source issue is fixed.",
  "next_actions": [
    "Review the preview/apply result, then manually resolve the warning if the source issue is fixed."
  ]
}
```

### POST `/admin/upload-warnings/{warning_issue_id}/source-cell-replace/apply`

Apply a single previewed RDB source-cell replacement linked to a durable upload warning issue.

- **Auth:** admin only
- **Scope:** Same as preview.
- **Body:** Same as preview plus required `correction_reason`.
- **Behaviour:** Re-loads latest warning context, checks optional stale-context guards, parses the replacement, locks the resident/month scope where practical, deletes only matching scoped `resident_postings` rows, inserts only parsed replacement rows, upserts produced `posting_codes`, and writes correction audit metadata linking `warning_issue_id`, `upload_warning_id`, and fingerprint.
- **Warning history:** Does not mutate `upload_logs.summary`, does not append fake `upload_warnings`, and does not auto-resolve the warning issue. Response includes `warning_issue_status` and a manual next-action hint.
- **Data Revalidation:** Successful apply returns `targeted_revalidation`. It does not calculate compliance, generate snapshots, hibernate surplus, or generate clawback.

The `data_revalidation` object below is abbreviated to the fields most relevant to this flow; the full object follows the Data Revalidation contract above.

```json
{
  "warning_issue_id": "<warning_issue_uuid>",
  "upload_warning_id": "<latest_upload_warning_uuid>",
  "latest_upload_warning_id": "<latest_upload_warning_uuid>",
  "fingerprint": "empty_posting_cell|<period>|DR|M12345A|Jul-25",
  "source_trace": {
    "reporting_period_id": "<period_uuid>",
    "programme_code": "DR",
    "mcr": "M12345A",
    "month_label": "Jul-25",
    "sheet_name": "Phase 1",
    "row_number": 3,
    "cell_ref": "I3",
    "source_payload": { "type": "empty_posting_cell", "raw_value": null }
  },
  "source_payload": { "type": "empty_posting_cell", "raw_value": null },
  "original_warning_type": "empty_posting_cell",
  "warning_issue_status": "unresolved",
  "replacement_raw_cell_value": "TTSHAnaes",
  "normalized_cell_value": "TTSHAnaes",
  "before_rows": [],
  "after_rows": [
    { "posting_code": "TTSHAnaes", "status": "active", "month_label": "Jul-25" }
  ],
  "replacement_summary": {
    "rows_deleted": 0,
    "rows_inserted": 1
  },
  "parser_warnings": [],
  "parser_errors": [],
  "data_revalidation": { "outcome": "targeted_revalidation" },
  "suggested_next_action": "Review the preview/apply result, then manually resolve the warning if the source issue is fixed.",
  "next_actions": [
    "Review the preview/apply result, then manually resolve the warning if the source issue is fixed."
  ]
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
- **Target validation:** `monthly_target` accepts non-negative whole numbers including `0`; negative and fractional values are rejected.
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

- **Auth:** Master Admin and scoped Programme PC, read-only. Programme PC access is for selecting a reporting period for programme-scoped flows such as TTF upload; empty/null `programme_scope` is not all-access.

### POST `/admin/reporting-periods`

Create a new reporting period.

- **Auth:** Master Admin only
- **Body:**
```json
{
  "label": "Jan - June 2026",
  "start_date": "2026-01-06",
  "end_date": "2026-07-06",
  "status": "active",
  "activate_on": null
}
```

`status` is optional on create and defaults to `active`. Only `active` and `inactive` are accepted; legacy `open`/`closed` values are rejected. `activate_on` and `deactivate_on` are optional scheduled transition dates. If `deactivate_on` is omitted, it defaults to `end_date + 14 calendar days`; an explicitly supplied value is preserved. If both transition dates are supplied, `activate_on <= deactivate_on` is required.

### PUT `/admin/reporting-periods/{id}`

Update a reporting period label, date range, stored status, or scheduled transition dates.

- **Auth:** Master Admin only
- **Body:** any subset of `label`, `start_date`, `end_date`, `status`, `activate_on`, `deactivate_on`.
- **Validation:** `start_date <= end_date`, `status` is `active` or `inactive`, and the resolved `activate_on/deactivate_on` pair must satisfy `activate_on <= deactivate_on` when both are set. A past period requires an explicitly supplied `deactivate_on` after today for a new immediate or scheduled inactive-to-active transition. For a future scheduled reopening, `deactivate_on` must be strictly later than `activate_on`; a same-day pair is not a valid reopen window. Ordinary edits to an already reopened period preserve its existing date.
- **Response:** existing reporting-period entity fields plus `data_revalidation`.

### PUT `/admin/reporting-periods/{id}/activate`

Set `reporting_periods.status = 'active'`. A past period can be activated only when it already has a future `deactivate_on`; otherwise use the full reporting-period update endpoint to explicitly create a bounded historical reopen window.

- **Auth:** Master Admin only
- **Consistency:** the status update, read-after-write verification, data revalidation summary, and audit row commit as one transaction. On an API timeout or `5xx`, callers must re-read the period before retrying.
- **Response:** existing reporting-period entity fields plus `data_revalidation`.

### PUT `/admin/reporting-periods/{id}/deactivate`

Set `reporting_periods.status = 'inactive'`.

- **Auth:** Master Admin only
- **Important:** Deactivation is an operational status change only. It does not generate snapshots, clawback rows, or surplus hibernation.
- **Response:** existing reporting-period entity fields plus `data_revalidation`.

### DELETE `/admin/reporting-periods/{id}`

Delete an unused reporting period.

- **Auth:** Master Admin only
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

The stored status remains `active` or `inactive`; due scheduled dates are resolved at read time and do not mutate the row. When both scheduled dates are due, the later scheduled date wins; if both are due on the same date, deactivation wins. Multiple periods may be administratively active, but a current-date workflow must resolve exactly one effectively active period containing today and a dated workflow must resolve exactly one containing its relevant date. A future active period is not a current default, and overlapping active date windows return a safe configuration conflict. With no matching period, resident event listing returns an empty list with `reason = "active_reporting_period_unavailable"` and ad-hoc disabled; attendance and ad-hoc submission endpoints reject with `422`.

---

### Upload Logs

### GET `/admin/upload-logs`

List upload history.

- **Auth:** admin only
- **Query params:** `upload_type` (`rdb` | `ttf` | `form_f1` | `public_holidays`), `programme_code`, `reporting_period_id`, `limit` (default 20)

### GET `/admin/upload-logs/{id}`

Get a single upload log entry.

- **Auth:** admin only

### Planned 3I-B Admin Logs endpoints - not implemented

The unified Admin Logs surface is planned as a read-only aggregation over existing upload, warning, correction, config mutation, and Data Revalidation audit sources. See `docs/admin-logs-contract.md` for the full backend contract.

Planned endpoints:

- `GET /admin/logs`
- `GET /admin/logs/{id}`

Planned rules:

- Use the page/API name **Admin Logs** and route namespace `/admin/logs`.
- Preserve `GET /admin/upload-logs` and `GET /admin/upload-logs/{id}` for compatibility.
- Preserve existing warning, parsed-data, and config endpoints as the canonical mutation surfaces.
- `GET /admin/logs` is read-only. It must not mutate source tables, create fake persisted log records, rewrite `upload_logs.summary`, auto-resolve warnings, reparse RDB broadly, regenerate `resident_postings`, or run compliance/snapshot/clawback/surplus work.
- List rows must be compact and paginated. The default list/detail flow must not fetch or render full raw `upload_logs.summary`.
- Full raw upload summary access, if added later, must be explicit through `include_raw_summary=true`, export/download, or a dedicated raw audit endpoint.

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

## `4B` Programme PC Teaching Event CRUD endpoints

Programme PCs manage scheduled teaching events for their own programmes before Phase 6 compliance. PC-created rows use `teaching_events.created_for_programme_code` for explicit programme ownership; secretary-created rows normally leave that field null and remain posting-owned/programme-neutral.

### GET `/admin/programme-teaching-events`

List scheduled teaching events visible to the Programme PC's programme scope.

- **Auth:** admin/PC only
- **Scope:** `programme_code IN programme_scope`. Null or empty `programme_scope` means no access. Master admin access is rejected on these PC CRUD endpoints.
- **Query params:** `programme_code`, `reporting_period_id`, `date_from`, `date_to`, `posting_code` optional.
- **Visibility contract:** Resolve the selected period, or the effectively active period containing today when none is selected. Return only events whose dates fall in that period. PC-created rows must be in scope; secretary-created/null-owner scheduled rows match the selected programme through `secretary_programme_pools` or `teaching_name_catalogue` in that same reporting-period scope. If an explicit period is supplied with `date_from` or `date_to`, each supplied date must fall inside it or the API returns `422`.

### GET `/admin/programme-teaching-name-options`

Return teaching-name options for PC event creation.

- **Auth:** admin/PC only
- **Query params:** `programme_code` required; `reporting_period_id` or `event_date` optional. An explicit period must be effectively active. When both are supplied, `event_date` must belong to the explicit period or the API returns `422`. With neither option, the backend resolves the single effectively active period containing today. TTF-derived options are scoped to that resolved period.
- **Scope:** `programme_code IN programme_scope`.
- **Source:** TTF Column K via `teaching_name_catalogue` for the selected programme, plus active `global_session_types`.

### POST `/admin/programme-teaching-events`

Create a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`.
- **Validation:** Returns `422` if `event_date` is in `public_holidays`. Returns `422` if `teaching_name` is not available from that programme's `teaching_name_catalogue` for the selected posting/r_year/period context.
- **Body:**
```json
{
  "programme_code": "DR",
  "posting_code": "KTPHDiagRd",
  "teaching_name": "Journal Club",
  "event_date": "2026-04-15",
  "start_time": "10:00",
  "cme_points_awarded": false,
  "smc_event_code": null
}
```
- **Backend writes:** `teaching_events.created_for_programme_code = programme_code`, `created_by_role = 'programme_pc'`, `is_adhoc = false`, and normal event fields. `created_by_role` is role/source metadata only; actor names are not stored on the event.
- **Resident visibility:** Residents can see the event only when their `programme_code` matches `created_for_programme_code` and the event also passes posting/date/catalogue visibility rules.

### PUT `/admin/programme-teaching-events/{id}`

Edit a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`, and event must be programme-owned for that programme or a secretary-created/null-owner scheduled row visible to that programme.
- **Validation:** Public holiday block and catalogue option validation apply to changed event date/name/posting fields.
- **Constraint:** Returns `409` if any native `attendance_records` or `external_attendance_records` exist for the event. `created_by_role` is preserved.

### POST `/admin/programme-teaching-events/{id}/duplicate`

Duplicate a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`, and source event must be programme-owned for that programme or a secretary-created/null-owner scheduled row visible to that programme.
- **Validation:** Public holiday block applies to the duplicate date. The duplicated event sets `created_for_programme_code = programme_code` and `created_by_role = 'programme_pc'`.

### DELETE `/admin/programme-teaching-events/{id}`

Delete a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`, and event must be programme-owned for that programme or a secretary-created/null-owner scheduled row visible to that programme.
- **Constraint:** Returns `409` if any native `attendance_records` or `external_attendance_records` exist for the event.

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
- **Query params:** `reporting_period_id` or `event_date` optional. An explicit period must be effectively active. When both are supplied, `event_date` must belong to the explicit period or the API returns `422`. With neither option, the backend resolves the single effectively active period containing today. TTF-derived options are scoped to that resolved period.
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
  1. If resident has no `resident_postings` rows for the current/effectively active period → no assigned-posting visibility; return empty list with `reason: "posting_schedule_unavailable"` if no other allowed source can produce events.
  2. Assigned/current posting secretary events: derive assigned posting from `resident_postings` for the selected/current date with `status IN ('active', 'loa_working')`. Secretary-created events at that `posting_code` are eligible.
  3. Native programme TTSH department secretary events: derive the native programme teaching posting from explicit config/mapping, for example `programmes.native_teaching_posting_code` or `programme_teaching_posting_map`. Do not infer this mapping by string manipulation.
  4. Native programme PC-created events: include events where `teaching_events.created_for_programme_code = resident.programme_code`.
  5. Deduplicate rows by `teaching_events.id` across all sources.
  6. Filter to `event_date <= today` (no future events).
  7. Exclude events already submitted by this resident.
  8. Apply active/effectively active reporting-period checks.
  9. Apply `teaching_name_catalogue` / global-session matching. For catalogue-backed events, only show events whose `teaching_name` exists in the resident's catalogue for `(event posting context, resident.programme_code, resident_postings.r_year, reporting_period_id)`. Global session type exclusion/visibility follows the same source eligibility rules.
  10. Do not show PC-created events for non-native programmes.
  11. Do not show secretary-created events from arbitrary TTSH departments unless they are either the resident's assigned/current posting or the resident's native programme department.
- **Query params:** `date_from`, `date_to`

**Native visibility examples:**
- **Scenario A:** Native GRM Resident John is posted to TTSH Geriatric Medicine. John sees TTSH GRM Department Secretary events because he is posted there and GRM PC events because GRM is his native programme. The TTSH GRM secretary event source is deduped if it is both assigned posting and native programme department.
- **Scenario B:** Native GRM Resident John is posted to TTSH Rehab. John sees TTSH Rehab Department Secretary events because he is posted there, TTSH GRM Department Secretary events because GRM is his native programme department, and GRM PC events because GRM is his native programme.
- **Scenario C:** Native Rehab Resident Mary is posted to TTSH GRM. Mary sees TTSH GRM Department Secretary events because she is posted there, TTSH Rehab Department Secretary events because Rehab is her native programme department, and Rehab PC events because Rehab is her native programme.

### POST `/resident/attendance`

Submit attendance for one or more events.

- **Auth:** resident only
- **Body:** `{ "event_ids": ["uuid1", "uuid2"] }`
- **Backend:**
  1. Validates event exists and is visible through the resident's allowed scheduled-event sources: assigned/current posting secretary event, native programme TTSH department secretary event, or native programme PC-created event
  2. Validates `event_date` falls within a `resident_postings` row with `status IN ('active', 'loa_working')` → `422` if outside tenure
  3. Validates `teaching_name` exists in `teaching_name_catalogue` for resident's `(posting_code, programme_code, r_year, reporting_period_id)` → `422` if no match
  4. Validates programme ownership: events with `created_for_programme_code` set must match the resident's `programme_code`
  5. Validates no duplicate (`UNIQUE(resident_id, teaching_event_id)`)
  6. Creates `attendance_records` rows — **does NOT store `session_type_id`**
  7. Checks each submitted event against `weekend_exceptions` — if a weekend session has no matching rule, adds a `compliance_warning` to the response
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

### Planned GET `/resident/adhoc-teaching-options`

Return assigned-posting context, attended TTSH department options, and catalogue-backed teaching options for the ad-hoc form.

- **Auth:** NHG Resident or Non-NHG Resident (`resident` or `external_resident` role)
- **Query params:**
  - `teaching_date` required.
  - `attended_posting_code` optional. This is the selected TTSH department/programme posting from the attended department dropdown. Older/alternate client field name `attended_department_posting_code` is equivalent if retained for compatibility.
- **NHG Resident backend:**
  1. Derives `assigned_posting_code` from `resident_postings` for `teaching_date` with `status IN ('active', 'loa_working')`.
  2. Uses resident native `programme_code` from `residents.programme_code`.
  3. Builds `attended_posting_options[]` from validated TTSH department/programme posting codes backed by `posting_codes` and configured mapping. Do not generate posting codes by string concatenation or regex.
  4. When `attended_posting_code` is provided, returns `teaching_options[]` from TTF Column K / `teaching_name_catalogue` for the selected attended department posting, scoped to resident native programme where applicable.
  5. Sets `compliance_posting_code = assigned_posting_code`.
  6. Sets `compliance_session_type_name = "Department/Programme Teaching [1h]"`.
  7. Resolves the fixed compliance session type against a tracked target for assigned posting, resident native programme, resident `r_year` for the selected date, and active/effectively active `reporting_period_id`.
  8. If assigned posting or the required fixed target cannot be resolved, return `countable = false` with a clear `reason`/`message`; do not guess.
- **Non-NHG Resident backend:**
  1. Derives date-specific host posting from `external_resident_postings` for `teaching_date` once forecast posting schedule is implemented.
  2. If no schedule row matches the date, returns `countable = false` and `reason = "posting_unavailable_for_date"`.
  3. Uses attended department selection only for option filtering/export context.
  4. Returns no NHG compliance attribution: `compliance_posting_code = null`, `compliance_session_type_name = null`, and `countable = false`.
- **Response example:**
```json
{
  "teaching_date": "2026-04-15",
  "assigned_posting_code": "TTSHRehab",
  "assigned_posting_label": "TTSH Rehabilitation Medicine",
  "attended_posting_options": [
    {
      "posting_code": "TTSHGerMed",
      "label": "TTSH Geriatric Medicine",
      "programme_code": "GERI",
      "programme_name": "Geriatric Medicine"
    }
  ],
  "selected_attended_posting_code": "TTSHGerMed",
  "teaching_options": [
    {
      "catalogue_id": "uuid",
      "teaching_name": "Journal Club"
    }
  ],
  "compliance_session_type_name": "Department/Programme Teaching [1h]",
  "compliance_posting_code": "TTSHRehab",
  "countable": true,
  "reason": null,
  "message": null
}
```
- **Frontend helper copy:** `Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.`

### POST `/resident/adhoc-teaching`

Submit an ad-hoc teaching not pre-created by a secretary.

- **Auth:** NHG Resident or Non-NHG Resident (`resident` or `external_resident` role)
- **Body:**
```json
{
  "teaching_date": "2026-04-15",
  "start_time": "10:00",
  "teaching_name": "Journal Club",
  "catalogue_id": "uuid",
  "attended_posting_code": "TTSHGerMed",
  "details_of_session": "Case discussion after ward teaching"
}
```
- **Backend:**
  1. Validates `teaching_date` is not a public holiday → `422` if PH.
  2. Derives assigned posting for the selected date:
     - NHG Resident: `resident_postings` date match with `status IN ('active', 'loa_working')`.
     - Non-NHG Resident: `external_resident_postings` date match once forecast posting schedule is implemented.
  3. Validates `attended_posting_code` / selected TTSH department posting against `posting_codes` and configured mapping. Do not generate codes by string concatenation or regex.
  4. Validates submitted `teaching_name` or `catalogue_id` was selected from the catalogue-backed options for the selected date and attended posting context. Arbitrary free-text teaching names must not drive compliance mapping.
  5. For NHG Residents, resolves fixed compliance attribution:
     - `compliance_posting_code = assigned_posting_code`
     - `compliance_session_type_name = "Department/Programme Teaching [1h]"`
     - required tracked target exists for assigned posting, resident native programme, `resident_postings.r_year`, and active/effectively active `reporting_period_id`
  6. If the required assigned-posting `Department/Programme Teaching [1h]` target cannot be resolved, return a clear unavailable/not-countable response rather than guessing.
  7. Creates `teaching_events` row with `is_adhoc = true`, `posting_code = assigned/compliance posting for NHG Resident ad-hoc`, `created_by_role = 'resident'` or `'external_resident'`, `cme_points_awarded = false`, `smc_event_code = null`, and planned `details_of_session` when provided.
  8. Creates `attendance_records` for NHG Residents or `external_attendance_records` for Non-NHG Residents in the same transaction.
  9. `end_time` = `start_time + 1 hour` for countable NHG ad-hoc compliance attribution. Display duration for the attended catalogue option must not override fixed NHG compliance attribution.
  10. Checks weekend exception — returns `compliance_warning` if session will not count for native compliance.
- **NHG compliance treatment:** All countable NHG Resident ad-hoc sessions map to `Department/Programme Teaching [1h]` and count under the assigned posting for the selected date. They do not count under the attended TTSH department unless that department is also the assigned posting.
- **Non-NHG treatment:** Non-NHG ad-hoc sessions create `external_attendance_records` only for attendance storage. They do not create native `attendance_records`, receive no NHG compliance attribution, and never enter NHG numerator, denominator, surplus, snapshots, clawback, or native reports.
- **Planned schema/API note:** `details_of_session` is not present in current models/migrations. It is display/audit-only and must have no operational or compliance use. `attended_posting_code` is planned audit/display metadata; if current schema does not support it, keep it as pending schema/API field and do not overload `teaching_events.posting_code`.

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

- Resident: returns `residents` row identity fields (`id`, `role`, `name`, `programme_code`, `mcr`) plus display-only `current_posting_code` and `current_posting_label` when a usable `resident_postings` row exists in the single effectively active period containing today. Within that period, display resolution prefers today's row, then the nearest future row, then the nearest recent past row. It does not return a trusted `posting_code` claim.
- Resident current posting for authorization-sensitive endpoints is still resolved server-side from `resident_postings` at request time.
- Non-NHG Resident: returns `external_residents` row identity fields (`id`, `role`, `name`, `mcr`, `home_cluster`) plus display-only `current_posting_code` and `current_posting_label` when a usable `external_resident_postings` row overlaps the single effectively active period containing today. Within that period, display resolution prefers today's row, then the nearest future row, then the nearest recent past row. It does not return `current_nhg_posting_code`, trusted `posting_code`, posting schedule, staff actor metadata, `admin_level`, `programme_code`, or `programme_scope`.
- Admin/Secretary: returns `users` row fields + scope, including `admin_level` for admin accounts and saved staff actor metadata:
  - `current_staff_actor_name`
  - `staff_actor_name_required` (`true` when the staff account has no saved non-blank actor name)
  - `staff_actor_name_updated_at`
  - `staff_actor_name_updated_by_user_id`

### POST `/auth/staff-actor-name`

Save the current human name for a shared staff role account.

- **Auth:** authenticated staff only (`admin` or `secretary`); NHG Residents and Non-NHG Residents receive `403`.
- **Body:**
```json
{
  "full_name": "Dr Priya Tan"
}
```
- **Behaviour:** trims and stores a non-empty name in `users.current_staff_actor_name`, updates `staff_actor_name_updated_at` and `staff_actor_name_updated_by_user_id`, and returns the updated `/auth/me` identity shape.
- **Authorization note:** this value is audit/display metadata only. It does not affect `role`, `admin_level`, `programme_scope`, `posting_code`, or any authorization decision.
- **Errors:** `401` unauthenticated, `403` non-staff, `422` blank/invalid name.

### Master Admin Staff Account Endpoints

These endpoints are Master Admin-only. Programme PCs and Secretaries receive `403`.

#### GET `/admin/staff-accounts`

Returns `{ "items": [...] }` for staff role accounts in `users`.

Each item includes `account_display_name`, `email`, `account_type` (`master_admin`, `programme_pc`, `secretary`), `programme_scope`, `posting_code`, `current_staff_actor_name`, and `is_active`.

#### POST `/admin/staff-accounts`

Create a generic staff role account.

```json
{
  "account_display_name": "Programme PC - DR",
  "email": "pc-dr@example.com",
  "account_type": "programme_pc",
  "password": "temporary working password",
  "is_active": true,
  "programme_scope": ["DR", "GRM"],
  "posting_code": null
}
```

- `master_admin`: stores `role = admin`, `admin_level = master`, no programme scope or posting code.
- `programme_pc`: stores `role = admin`, `admin_level = programme`, and requires non-empty `programme_scope`; empty scope grants no access and is rejected here.
- `secretary`: stores `role = secretary` and requires `posting_code`; programme scope is not used.
- In `AUTH_MODE=supabase`, the backend uses the server-only Supabase service role key to create the Supabase Auth user and stores returned `auth.users.id` in `users.supabase_user_id`.
- In stub/demo, only the local row/password hash is created.
- Passwords are never returned or logged. `current_staff_actor_name` starts empty.

#### PATCH `/admin/staff-accounts/{user_id}`

Edit account display name, account type/scope fields, posting code, and `is_active`. Email changes may be rejected. Hard delete is not supported. The backend rejects deactivating or demoting the last active Master Admin.

#### POST `/admin/staff-accounts/{user_id}/reset-password`

```json
{
  "password": "new working password"
}
```

Updates the Supabase Auth password in Supabase mode when `supabase_user_id` exists, updates the local password hash, and clears `current_staff_actor_name` plus actor-name timestamps for handover. The password is not returned or logged.

### PUT `/auth/settings`

Update password. Admin/secretary only.


---

## Non-NHG Resident Endpoints

Non-NHG Residents are Phase 5B pre-compliance scope. They use separate identity and attendance tables. They are never stored in `users`, never stored in native `residents`, and never represented through native `resident_postings`. Backend/internal route and table names may continue to use `external_resident`.

### POST `/external-residents/register`

Self-register a Non-NHG/cross-cluster resident.

- **Auth:** public/self-service with rate limiting
- **Body:**
```json
{
  "name": "Resident Name",
  "mcr": "E12345A",
  "home_cluster": "NUH",
  "posting_schedule": [
    {
      "start_date": "2026-07-01",
      "end_date": "2026-07-31",
      "programme_code": "GERI",
      "institution": "TTSH"
    }
  ]
}
```
- **Validation:**
  1. `home_cluster` must be `NUH` or `SingHealth`.
  2. `mcr` must not exist in native `residents`.
  3. `mcr` must not exist in `external_residents`.
  4. Each schedule row must have `start_date <= end_date`; schedule rows must not overlap.
  5. Each schedule row resolves exactly one posting code from trusted programme/institution posting configuration. The client must not send or choose `posting_code`.
- **Writes:** `external_residents` plus one `external_resident_postings` row per resolved schedule row. Do not create `users`, native `residents`, or native `resident_postings` rows.
- **Response convenience:** May return `current_nhg_posting_code` as today's derived/current posting for display/backward compatibility.
- **Duplicate/conflict:** `409` when MCR already exists.

### PUT `/external-residents/me/posting`

Update the Non-NHG Resident's current NHG posting pointer. Route name remains for compatibility with older clients; schedule-aware clients should use `/external-residents/me/posting-schedule`.

- **Auth:** Non-NHG Resident only (`external_resident` role)
- **Body:**
```json
{
  "current_nhg_posting_code": "KTPHDiagRd"
}
```
- **Validation:** `current_nhg_posting_code` must exist in `posting_codes`.
- **Behaviour:** updates the authenticated Non-NHG Resident's current/cache pointer and current `external_resident_postings` row. No native `resident_postings` rows are created.

### PUT `/external-residents/me/posting-schedule`

Replace the authenticated Non-NHG Resident's date-specific NHG posting schedule.

- **Auth:** Non-NHG Resident only (`external_resident` role)
- **Body:**
```json
{
  "posting_schedule": [
    {
      "start_date": "2026-07-01",
      "end_date": "2026-07-31",
      "programme_code": "GERI",
      "institution": "TTSH"
    }
  ]
}
```
- **Validation:** same schedule-row validation and trusted posting-code resolution as registration. If no single safe posting can be resolved, return `422` and keep the existing schedule.
- **Behaviour:** replaces `external_resident_postings`, updates the current/cache pointer from the resolved schedule, and never creates native `resident_postings`.

### GET `/resident/events` for Non-NHG Residents

The same route may support NHG and Non-NHG Residents through identity branching.

- For native `role = resident`, use native Phase 5A behaviour from `resident_postings`.
- For `role = external_resident`, derive date-specific posting from `external_resident_postings` for the event listing date/window. `external_residents.current_nhg_posting_code` may be used only as a current/cache/backward-compatibility pointer.
- If no `external_resident_postings` row matches a requested date, return unavailable/no posting for that date.
- If the posting's `posting_codes.supports_secretary_events = true`, return eligible secretary-created events for that posting.
- If `supports_secretary_events = false`, return no secretary-created event list but keep ad-hoc submission available in the frontend.
- Programme-owned PC events (`created_for_programme_code IS NOT NULL`) are not shown to Non-NHG Residents unless a future explicit requirement defines external visibility for that host programme.
- Filter `event_date <= today`.
- Exclude events already submitted by that Non-NHG Resident in `external_attendance_records`.
- Do not apply native NHG compliance catalogue/denominator logic to Non-NHG Residents.

### POST `/resident/attendance` for Non-NHG Residents

The same route may support NHG and Non-NHG Residents through identity branching.

- For `role = external_resident`, validate the event belongs to the Non-NHG Resident's date-matched NHG posting.
- Create `external_attendance_records`, not native `attendance_records`.
- Duplicate protected by `UNIQUE(external_resident_id, teaching_event_id)`.
- Weekend non-exception attendance is stored and returns `compliance_warning`.
- Do not store `session_type_id`.
- Do not include the row in NHG compliance.

### POST `/resident/adhoc-teaching` for Non-NHG Residents

The same route may support NHG and Non-NHG Residents through identity branching.

- For `role = external_resident`, derive host posting from `external_resident_postings` for `teaching_date`.
- If no schedule row matches `teaching_date`, return unavailable/no posting for selected date.
- Teaching options come from `GET /resident/adhoc-teaching-options` using the selected teaching date and attended department/programme.
- Attended department/programme selection is for option filtering/export context only.
- Resolve selected attended posting against `posting_codes` using validated/configured mapping. Do not concatenate strings or infer codes by regex.
- PH hard-block with `422`.
- Create `teaching_events` with `is_adhoc = true`, `created_by_role = 'external_resident'`, `posting_code = derived host posting`, `cme_points_awarded = false`, `smc_event_code = null`, and planned display/audit-only `details_of_session` when provided.
- Create `external_attendance_records` in the same transaction.
- Weekend non-exception attendance is stored and returns `compliance_warning`.
- Do not create native `attendance_records`.
- No NHG compliance attribution, numerator, denominator, surplus, snapshots, clawback, or native reports.

### GET `/resident/attendance-history`

Return the authenticated resident's past submitted attendance.

- **Auth:** NHG Resident or Non-NHG Resident (`resident` or `external_resident` role)
- **NHG Resident:** read from `attendance_records` scoped by `resident_id`.
- **Non-NHG Resident:** read from `external_attendance_records` scoped by `external_resident_id`.
- **Filters:** `date_from`, `date_to`, `status` optional.

### GET `/resident/dashboard` for Non-NHG Residents

Non-NHG Residents do not receive an NHG compliance dashboard.

- **Auth:** Non-NHG Resident only (`external_resident` role)
- **Response:**
```json
{
  "compliance_status": "not_applicable",
  "reason": "external_resident_excluded_from_nhg_compliance",
  "message": "Non-NHG Resident attendance is stored for future export to the home cluster PC. NHG compliance and clawback do not apply."
}
```

### Non-NHG attendance export

Non-NHG attendance list/read and Excel export are Phase 5B-F admin/PC tools. External attendance tables remain recording/export-only and never enter NHG compliance.

### GET `/admin/external-attendance`

List Non-NHG attendance for authorized admin/PC users.

- **Auth:** admin/PC only
- **Scope:** Programme-PC authorization requires a `teaching_name_catalogue` row matching the event posting, teaching name, programme scope, and the event's applicable reporting period. With no explicit period filter, the event date must map to exactly one reporting-period range; overlapping ranges fail closed. An explicit `reporting_period_id` scopes the report by date containment and permits authorized inactive historical reporting. Explicit master admin may access all programmes. Null/empty `programme_scope` means no access.
- **Filters:** `reporting_period_id`, `home_cluster`, `posting_code`, `attended_posting_code` where supported, `date_from`, `date_to`, `mcr`, `status`.
- **Compliance exclusion:** Results are for audit/forwarding only and must not be joined into native compliance reports.

### GET `/admin/external-attendance/{id}`

Read one external attendance record with resident, event, posting, and routing context.

- **Auth:** admin/PC only
- **Scope:** Same as list endpoint.

### GET `/admin/external-attendance/export.xlsx`

Export filtered external attendance to Excel for forwarding to NUH/SingHealth PCs.

- **Auth:** admin/PC only
- **Scope:** Same as list endpoint.
- **Filters:** Same as list endpoint.
- **Format:** `.xlsx`
- **Content:** Non-NHG Resident identity, `home_cluster`, current/event posting, teaching event details, submitted status/timestamps, and any planned `details_of_session` captured on ad-hoc event rows.
- **Not included:** Native `attendance_records`, native compliance percentages, surplus, snapshots, or clawback rows.

Workbook columns and programme/r_year routing metadata remain implementation-owned by the export service; the export must remain formula-safe and forwarding-only.

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
