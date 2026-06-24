# 3I-A - Unified Admin Logs Backend Contract

Status: planned contract for Phase 3I-B. This document describes the future backend read contract for a unified Admin Logs surface. It does not imply that `/admin/logs` is implemented today.

## 1. Naming Recommendation

Use **Admin Logs** as the final user-facing product name.

| Candidate | Recommendation | Rationale |
| --- | --- | --- |
| `Admin Logs` | Choose | Clear to Master Admin and Programme PC users; matches the `/admin/*` backend namespace and the left-nav mental model. |
| `Activity Logs` | Do not use as page/product name | Useful as a category word, but too broad and less connected to the admin audit purpose. |
| `Unified Logs` | Do not use | Implementation-oriented; not a good user-facing label. |

Final naming:

- Left-nav/page label: `Admin Logs`.
- API route namespace: `/admin/logs`.
- Frontend route, when implemented: prefer `/admin/logs`; keep `/admin/upload-logs` during transition.
- Internal category/type word: `activity` may be used inside copy or filters only when referring to a log category, not the product/page name.

Backward compatibility:

- Existing **Upload Logs** remains a source-specific compatibility page and endpoint family.
- `GET /admin/upload-logs` continues to mean upload history only.
- `GET /admin/logs?log_type=upload` is the future normalized equivalent for upload rows, but it must not replace existing endpoints until the frontend has migrated safely.

## 2. Current Log Sources

The current implementation has multiple persisted and frontend-only sources that the future Admin Logs read model can aggregate. The normalized read model should be a projection over these sources, not a new mutation path.

| Source | Current table/model/source | Current route(s) | Current frontend consumer(s) | Classification | Persisted? | Gaps/unknowns |
| --- | --- | --- | --- | --- | --- | --- |
| Upload logs | `upload_logs` / `UploadLog` in `backend/app/models/reporting.py` | `GET /admin/upload-logs`, `GET /admin/upload-logs/{id}`; writes from RDB, TTF, FormF1, and Public Holidays upload endpoints | `AdminUploadLogsPage`, `AdminHomePage`, `AdminParsedDataPage` raw RDB context | Immutable audit evidence plus compact upload status | Yes | Current compatibility list response is compact, but the service still reads `ul.summary` to calculate counts/search. 3I-B `/admin/logs` should avoid loading full JSONB summaries in list projections. |
| Upload action audit | `audit_logs` / `AuditLog` with actions `admin.upload.rdb`, `admin.upload.ttf`, `admin.upload.form_f1`, `admin.upload.public_holidays` | No dedicated read route today | Not directly consumed | Immutable audit evidence for who/what/when around upload actions | Yes | May be joined to upload rows for actor/admin-level metadata. Do not create duplicate upload rows when both `upload_logs` and matching audit rows exist. |
| Durable warning issues | `warning_issues` / `WarningIssue` | `GET /admin/upload-warnings`, `GET /admin/upload-warnings/{warning_issue_id}` | `AdminWarningsPage` | Mutable workflow status for a deterministic warning fingerprint | Yes | Null/unknown programme warnings should remain master-only unless a future scoped redaction rule is confirmed. |
| Upload warning occurrences | `upload_warnings` / `UploadWarning` | Returned through warning list/detail; fallback warning reader can derive from `upload_logs.summary` if durable tables are unavailable | `AdminWarningsPage` | Append-only warning occurrence/source evidence | Yes when durable table exists | Fallback derivation from `upload_logs.summary` is compatibility behavior only; Admin Logs should prefer persisted `upload_warnings`. |
| Warning action audit | `audit_logs` with actions `admin.upload_warning.resolve`, `admin.upload_warning.dismiss`, `admin.upload_warning.supersede` | Written by `POST /admin/upload-warnings/{warning_issue_id}/resolve`, `/dismiss`, `/supersede`; no direct read route | Action result shown in `AdminWarningsPage` | Immutable action audit plus linked mutable issue status | Yes | Future Admin Logs can expose these as `log_type = "warning_action"`. |
| Warning-linked source-cell correction | `audit_logs` action `admin.parsed_data.resident_posting.source_cell_replace`, metadata links `warning_issue_id`, `upload_warning_id`, fingerprint, source trace, before/after rows, and `data_revalidation` | `POST /admin/upload-warnings/{warning_issue_id}/source-cell-replace/preview`; `POST /admin/upload-warnings/{warning_issue_id}/source-cell-replace/apply` | `AdminWarningsPage` | Preview is derived/non-persisted; apply is immutable correction evidence | Apply only | Preview must not appear as an audit log row. Apply must not auto-resolve the warning issue or mutate `upload_logs.summary`. |
| Parsed-data correction audit | `audit_logs` actions under `admin.parsed_data.*` for resident, resident posting, teaching target, FormF1, academic month boundary, and source-cell replacement | `GET /admin/parsed-data/corrections`; mutation routes under `/admin/parsed-data/*` | `AdminParsedDataPage` | Immutable correction evidence with before/after rows and metadata | Yes | Currently scoped through metadata programme fields. 3I-B needs careful null/global handling. |
| Config CRUD mutation audit | `audit_logs` actions under `admin.config.*` for reporting periods, public holidays, programmes, LOA types, multi-posting rules, posting groups, weekend exceptions, and global session types | Mutation routes under `/admin/*`; no direct read route today | `AdminConfigPage` receives mutation responses but does not browse audit history | Immutable config mutation evidence with before/after payloads and metadata | Yes | No current frontend audit browser for config mutations. Global/null programme config logs should be master-only by default. |
| Data Revalidation summaries | `data_revalidation` response objects, stored inside `audit_logs.metadata_json.data_revalidation` for successful parsed-data corrections, source-cell apply, and config mutations | Returned by mutation routes; no standalone read route | `AdminWarningsPage`, `AdminParsedDataPage`, `AdminConfigPage` callouts | Derived summary attached to the mutation/correction audit entry | Persisted only as audit metadata | Do not create standalone persisted Data Revalidation rows in 3I-B. If exposed as `log_type = "data_revalidation"`, it is a read-model projection over the backing audit log. |
| Frontend upload history | `UploadMeta` in React state/localStorage key `mata.admin.uploads.v1`; compacted in `frontend/src/utils/storage.ts` | None | `AdminUploadPage` latest-by-type cards/navigation | Frontend-only UX cache/pseudo log | Browser-local only | Not canonical audit. Must not be used as a backend Admin Logs source. |
| Resident submissions admin view | Current route `/admin/submissions` is a placeholder page | No admin backend endpoint yet | Placeholder only | Future operational/admin view | No | Keep as future deep-link target only; do not add submission log aggregation in 3I-B. |

## 3. Immutable Audit Evidence vs Mutable Workflow Status

Unified Admin Logs must display both immutable evidence and mutable workflow status, but must not merge them into one mutable record.

Immutable audit evidence:

- `upload_logs.summary` raw JSONB and upload metadata.
- `upload_logs` row identity, upload type, uploaded user, uploaded timestamp, reporting period, programme, status.
- `upload_warnings` source traceability: sheet name, row number, cell reference, source payload, message, fingerprint, upload occurrence.
- `audit_logs.before_json`, `audit_logs.after_json`, and `audit_logs.metadata_json` for warning actions, source-cell apply, parsed-data corrections, upload action audit, and config mutations.
- Correction action before/after rows.
- Config mutation before/after payloads and embedded `data_revalidation` metadata when present.

Mutable workflow status:

- `warning_issues.status`.
- `warning_issues.resolution_note`.
- `warning_issues.resolved_by`.
- `warning_issues.resolved_at`.
- Warning lifecycle values: `unresolved`, `resolved`, `dismissed`, `superseded`, `reappeared`.

Rules:

- Mutable workflow status must never rewrite immutable audit evidence.
- `upload_logs.summary` remains persisted exactly as immutable upload audit and must not be mutated.
- Source-cell apply is a correction/audit action, not fake upload history.
- Warning resolve/dismiss/supersede is issue workflow, not upload summary mutation.
- Upload warning occurrences remain append-only evidence; warning issue status can change independently.
- Data Revalidation summaries describe mutation impact. They do not imply compliance calculation, period snapshots, clawback generation, surplus hibernation, or broad RDB reparsing.

## 4. Proposed Normalized Admin Log Read Model

This is a read model for list rows. It does not require a new database table in 3I-B.

Use prefixed string ids so the detail endpoint can disambiguate rows from different tables:

- `upload:<upload_log_id>`
- `warning:<warning_issue_id>`
- `warning_action:<audit_log_id>`
- `source_cell_correction:<audit_log_id>`
- `parsed_data_correction:<audit_log_id>`
- `config_mutation:<audit_log_id>`
- `data_revalidation:<audit_log_id>`

Backend responses should use snake_case to match current FastAPI/Pydantic conventions. Frontend types may convert to camelCase locally where existing API modules do so.

```ts
type AdminLogType =
  | "upload"
  | "warning"
  | "warning_action"
  | "source_cell_correction"
  | "parsed_data_correction"
  | "config_mutation"
  | "data_revalidation";

type AdminActorRole =
  | "master_admin"
  | "programme_pc"
  | "admin"
  | "secretary"
  | "resident"
  | "external_resident"
  | null;

type AdminLogListItem = {
  id: string;
  log_type: AdminLogType;
  occurred_at: string;
  actor_user_id: string | null;
  actor_name: string | null;
  actor_role: AdminActorRole;
  stored_actor_role?: string | null;
  actor_admin_level?: string | null;
  programme_code: string | null;
  reporting_period_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  upload_log_id: string | null;
  warning_issue_id: string | null;
  upload_warning_id: string | null;
  status: string | null;
  outcome: string | null;
  title: string;
  summary: string;
  source_ref: {
    sheet_name?: string | null;
    row_number?: number | null;
    cell_ref?: string | null;
  } | null;
  deep_link: AdminLogDeepLink | null;
};
```

Actor role normalization:

- If stored audit actor role is `admin` and `actor_admin_level = "master"`, expose `actor_role = "master_admin"`.
- If stored audit actor role is `admin` with a non-empty programme scope and no master flag, expose `actor_role = "programme_pc"`.
- If the source cannot safely determine the user-facing role, expose the stored role (`admin`, `secretary`) or `null`.
- Do not add or require `X-Actor-Name` for `/admin/logs`; read actor names from existing audit rows or joined user rows where already available. Current unknown actor values may remain `Unknown actor`.

Detail model:

```ts
type AdminLogDetail = {
  id: string;
  log_type: AdminLogType;
  list_item: AdminLogListItem;
  immutable_evidence: Record<string, unknown>;
  workflow_status: Record<string, unknown> | null;
  related_entities: AdminLogRelatedEntity[];
  available_actions: AdminLogAction[];
};

type AdminLogRelatedEntity = {
  entity_type: string;
  entity_id: string | null;
  label: string;
  relationship:
    | "primary"
    | "source"
    | "occurrence"
    | "workflow_issue"
    | "audit_log"
    | "upload_log"
    | "resident"
    | "config_entity"
    | "related";
  deep_link?: AdminLogDeepLink | null;
};

type AdminLogAction = {
  action:
    | "view_upload_evidence"
    | "view_raw_summary"
    | "view_warning"
    | "view_warning_occurrence"
    | "view_parsed_data"
    | "view_config"
    | "view_data_revalidation"
    | "download_raw_audit";
  label: string;
  method?: "GET";
  endpoint?: string;
  deep_link?: AdminLogDeepLink | null;
};
```

Performance rule:

- List rows must be compact.
- Detail rows must be bounded.
- `GET /admin/logs/{id}` must not include full raw `upload_logs.summary` by default.
- Raw upload summary access should require an explicit `include_raw_summary=true`, a raw export/download action, or a later dedicated raw audit endpoint.
- The default Admin Logs list must never trigger the 21MB raw-summary frontend fetch/render path.

## 5. Proposed Filters

`GET /admin/logs` should be paginated and support these query parameters.

Required 3I-B filters:

| Filter | Values / notes |
| --- | --- |
| `log_type` | `upload`, `warning`, `warning_action`, `source_cell_correction`, `parsed_data_correction`, `config_mutation`, `data_revalidation` |
| `actor_user_id` | UUID string. For uploads, maps to `upload_logs.uploaded_by` or matching `audit_logs.actor_user_id`; for audit-backed rows, maps to `audit_logs.actor_user_id`. |
| `actor_role` | `master_admin`, `programme_pc`, `admin`, `secretary`, `resident`, `external_resident`. 3I-B should normally return admin-derived roles only. |
| `upload_type` | `rdb`, `ttf`, `form_f1`, `public_holidays`. Applies to upload rows and warning rows with upload context. |
| `warning_type` | Known current values include `empty_posting_cell`, `unmatched_multi_posting`, `unknown_loa_type`, `unknown_loa_types`, `mcr_not_found`, `mcr_not_found_warnings`, `orphaned_attendance`, `public_holiday_day_mismatch`, `duplicate_mcr_error`, `duplicate_mcr_errors`, `tag_order_warning`, `tag_order_warnings`, `skipped_mcr`, `skipped_mcr_warnings`, `promotion_date_warning`, `promotion_date_warnings`, and generic `warning`. New parser warning types may be added without changing the Admin Logs route. |
| `entity_type` | Current audit-backed values include `upload_log`, `warning_issue`, `resident_posting_source_cell`, `resident`, `resident_posting`, `teaching_target`, `form_f1_record`, `academic_month_boundary`, `reporting_period`, `public_holiday`, `programme`, `loa_type`, `multi_posting_rule`, `posting_group`, `weekend_exception`, `global_session_type`. |
| `entity_id` | UUID/string id of the entity in its source table. |
| `programme_code` | Programme scope filter. Must be validated server-side against admin scope. |
| `reporting_period_id` | UUID string. |
| `status` | Upload status: `success`, `partial`, `failed`; warning status: `unresolved`, `resolved`, `dismissed`, `superseded`, `reappeared`; other rows may be `null`. |
| `outcome` | Data Revalidation outcomes: `no_op`, `warning_only`, `targeted_revalidation`, `future_compliance_impact`, `manual_revalidation_required`. For upload rows, `outcome` may mirror upload `status`; for warning actions, it may mirror the action result. |
| `date_from` | Inclusive ISO date/datetime lower bound for `occurred_at`. |
| `date_to` | Inclusive ISO date/datetime upper bound for `occurred_at`. |
| `search` | Compact text search over title, summary, action, type, actor name, programme, MCR, source ref, and safe metadata labels. Must not require loading full raw upload summaries. |
| `limit` | Default `50`, max `200`. |
| `offset` | Default `0`. |

Optional filters:

| Filter | Values / notes |
| --- | --- |
| `mcr` | Uppercase-normalized MCR. Applies to warning issues/occurrences and correction metadata where available. |
| `resident_id` | UUID string. Applies to warning and parsed-data correction rows where available. |
| `upload_log_id` | UUID string. Applies to upload, warning occurrence, source-cell correction, and parsed-data correction rows with source upload metadata. |
| `warning_issue_id` | UUID string. Applies to warning, warning action, and warning-linked source-cell correction rows. |
| `correction_type` | Suggested values: `row_update`, `source_cell_replace`, `warning_source_cell_replace`. |
| `config_entity_type` | `reporting_period`, `public_holiday`, `programme`, `loa_type`, `multi_posting_rule`, `posting_group`, `weekend_exception`, `global_session_type`. |

## 6. Detail and Deep-Link Model

Deep links should point into existing or planned UI surfaces without inventing unimplemented routes as if they already exist.

```ts
type AdminLogDeepLink = {
  route: string;
  params?: Record<string, string>;
  query?: Record<string, string>;
  drawer?: string;
  entity_id?: string;
};
```

Recommended deep-link mapping:

| Log type | Existing/planned destination | Deep-link notes |
| --- | --- | --- |
| `upload` | Existing `/admin/upload-logs`; future `/admin/logs` | Current Upload Logs drawer uses list-row data only. Raw summary remains hidden unless explicit raw audit action is added. |
| `warning` | Existing `/admin/upload/warnings` for master admin, `/pc/warnings` for programme PC | Query by `warning_issue_id` is planned, not implemented today. Until then use available filters such as `mode=history`, `upload_type`, `status`, or `search`. |
| `warning_action` | Same warning detail destination | Link to the warning issue and show action audit in Admin Logs detail. Existing warning workflow endpoints remain canonical for mutations. |
| `upload_warning` occurrence evidence | Warning issue destination with occurrence selected | Occurrence selection by `upload_warning_id` is planned. Existing detail response already includes `occurrences[]`. |
| `source_cell_correction` | Existing `/admin/parsed-data` resident-postings tab plus linked warning issue | Drawer/query selection is planned. Include links to `warning_issue_id`, `upload_warning_id`, source ref, and the correction audit row. |
| `parsed_data_correction` | Existing `/admin/parsed-data` plus correction history | The current correction history endpoint is `/admin/parsed-data/corrections`; detail can show before/after JSON from the audit row. |
| `config_mutation` | Existing `/admin/config` or `/pc/config` | Config section/entity drawer deep linking is planned. Use `config_entity_type` and `entity_id`. |
| `data_revalidation` | Related warning/config/parsed-data impact view | No standalone UI route exists. Detail should show the backing audit log and embedded Data Revalidation summary. |
| future resident submission admin row | Existing placeholder `/admin/submissions` | Backend support is pending. Do not include resident submission aggregation in 3I-B. |

Example list-row deep links:

```ts
{
  route: "/admin/upload/warnings",
  query: { warning_issue_id: "<warning_issue_id>" },
  drawer: "warning_detail",
  entity_id: "<warning_issue_id>"
}
```

```ts
{
  route: "/admin/parsed-data",
  query: { tab: "resident-postings", entity_id: "<resident_posting_id>" },
  drawer: "source_cell_correction",
  entity_id: "<audit_log_id>"
}
```

Pending routes and drawer query contracts must be marked as pending in frontend work. The 3I-B backend may still return `deep_link` metadata for future consumers, but frontend must handle missing route/query behavior gracefully.

## 7. Scope and Authorization Rules

All Admin Logs authorization is server-side. Frontend role checks are UX only.

Required rules:

- `/admin/logs` and `/admin/logs/{id}` are admin/PC-only.
- Phase 1 auth stub currently uses `X-User-Role: admin`, `X-User-Id`, `X-User-Programme`, and explicit `X-Admin-Level: master` or `master_admin` for master admin.
- Future Supabase/JWT auth must derive role, subject, programme scope, and master-admin state from verified server-side claims.
- Master admin can see all admin logs only when explicitly authorized as master admin.
- Master admin must never be inferred from `programme_scope = NULL`.
- Programme PC can see only logs scoped to programmes in `users.programme_scope`.
- `programme_scope = NULL` or empty scope means no programme-log access, not all access.
- Do not use `X-User-Site` for resident/admin log scoping.
- Do not reintroduce `X-Actor-Name` requirements for this read API.

Global/null-programme logs:

- Default rule: master-admin only.
- Programme PCs may see a global/null source only if the backend can safely derive and enforce a programme scope without exposing unrelated resident/private data.
- Unknown/null programme warnings are master-only unless a later decision confirms safe scoped redaction.

Upload logs:

- TTF upload logs are programme-scoped by `upload_logs.programme_code` and may be visible to PCs for programmes in scope.
- RDB, FormF1, and Public Holidays uploads may include cross-programme/global evidence. Treat them as master-only in 3I-B unless a dedicated redaction/splitting contract is approved.
- Mixed-programme upload details must either be master-only or return a redacted scoped detail. 3I-B should choose master-only for simplicity.

Warning logs:

- Prefer `warning_issues.programme_code` for issue visibility.
- Use `upload_warnings.programme_code` only when projecting occurrence evidence.
- Null/unknown programme warning issues are master-only.
- Warning action audit visibility follows the linked `warning_issue_id` scope.

Correction/config audit logs:

- Parsed-data correction visibility follows the corrected entity programme or metadata `programme_code`.
- Warning-linked source-cell correction visibility follows the linked warning issue and corrected resident posting programme.
- Config mutation visibility follows source endpoint semantics and source metadata:
  - Global config such as reporting periods, public holidays, LOA types, and global session types is master-only unless later scoped rules are confirmed.
  - Programme-scoped config such as posting groups, multi-posting rules, weekend exceptions, and programme rows may be PC-visible only when `programme_code` is in scope and the existing mutation endpoint permits that scope.

Resident/private data:

- Never expose resident data outside the admin's authorized programme scope.
- If a list row would reveal MCR/name/source cell details for an out-of-scope resident, omit the row rather than partially leaking context.

## 8. Pagination and Performance Rules

`GET /admin/logs`:

- Must be paginated.
- Default `limit`: `50`.
- Max `limit`: `200`.
- Default `offset`: `0`.
- Stable ordering: `occurred_at DESC, id DESC`.
- Use compact list projections only.
- Avoid loading full JSONB summaries in list views.
- Avoid joining huge raw payloads unless a bounded detail request explicitly needs them.
- Search must use compact indexed fields or bounded metadata fields. It must not cast full `upload_logs.summary` to text for broad list search.

`GET /admin/logs/{id}`:

- Must return bounded detail by default.
- Must not include giant raw `upload_logs.summary` by default.
- May include compact counts, selected source trace, warning occurrence snippets, and before/after payloads from audit logs.
- Raw audit payloads require explicit `include_raw_summary=true`, a download/export action, or a later dedicated raw audit endpoint.

Compatibility guardrails:

- Never reintroduce default frontend fetch/render of large `upload_logs.summary`.
- Normal upload-log row click must not call `GET /admin/upload-logs/{id}` unless the UI explicitly enters a raw audit/export/download/source-evidence flow.
- Keep `GET /admin/upload-logs` compatibility list compact.

Index recommendations for 3I-B:

- Existing useful indexes:
  - `idx_upload_logs_type_created`
  - `idx_upload_logs_period_programme`
  - `idx_upload_logs_uploaded_by`
  - `idx_warning_issues_status`
  - `idx_warning_issues_warning_type`
  - `idx_warning_issues_period_programme`
  - `idx_upload_warnings_upload_log`
  - `idx_upload_warnings_issue`
  - `idx_upload_warnings_warning_type`
  - `idx_upload_warnings_period_programme`
  - `idx_upload_warnings_mcr`
  - `idx_audit_logs_created_at`
  - `idx_audit_logs_actor_user_created`
  - `idx_audit_logs_entity_created`
  - `idx_audit_logs_action_created`
  - `idx_audit_logs_actor_role_created`
- Consider, after `EXPLAIN ANALYZE`, adding:
  - `upload_logs(uploaded_at DESC, id DESC)` if upload ordering cannot use current indexes.
  - Expression indexes on `audit_logs.metadata_json ->> 'programme_code'`, `audit_logs.metadata_json ->> 'reporting_period_id'`, and `audit_logs.metadata_json ->> 'warning_issue_id'` if metadata filters become slow.
  - A composite audit index for `(created_at DESC, id DESC)` if the existing descending created-at index is insufficient for combined-source pagination.

Do not add broad JSONB GIN indexes blindly. Add indexes only for documented query paths with measured need.

## 9. Compatibility Rules

Existing endpoints:

- Preserve `GET /admin/upload-logs` for current frontend compatibility.
- Preserve `GET /admin/upload-logs/{id}` if already public, but normal Upload Logs row-click UI must not require it.
- Preserve `GET /admin/upload-warnings` and `GET /admin/upload-warnings/{warning_issue_id}`.
- Preserve warning workflow mutation endpoints:
  - `POST /admin/upload-warnings/{warning_issue_id}/resolve`
  - `POST /admin/upload-warnings/{warning_issue_id}/dismiss`
  - `POST /admin/upload-warnings/{warning_issue_id}/supersede`
- Preserve warning-linked source-cell preview/apply endpoints.
- Preserve parsed-data/config mutation endpoints as canonical mutation surfaces.

New planned endpoints:

- `GET /admin/logs`
- `GET /admin/logs/{id}`

Rules for the new endpoints:

- `GET /admin/logs` aggregates existing sources into a normalized read model.
- It must be read-only.
- It must not mutate source tables.
- It must not create fake persisted log records.
- It must not rewrite historical `upload_logs.summary`.
- It must not auto-resolve warnings.
- It must not reparse RDB broadly or regenerate `resident_postings`.
- It must not calculate compliance, generate snapshots, hibernate surplus, generate clawback, send email, or perform exports.

Data Revalidation compatibility:

- Current Data Revalidation summaries remain embedded in mutation responses and audit metadata.
- A `data_revalidation` Admin Log row, if exposed in 3I-B, is a read-model projection over a backing audit log and must link back to that audit log. It is not a new persisted event table.

## 10. Exact 3I-B Backend Endpoint Plan

Recommended backend shape:

- Create `backend/app/schemas/admin_logs.py`.
- Create `backend/app/services/admin_logs_service.py`.
- Add schema exports in `backend/app/schemas/__init__.py`.
- Add route handlers in `backend/app/routers/admin.py` unless the router is split first. Current app wiring includes the single admin router, so adding there is the lowest-risk 3I-B path.
- Add tests in `backend/tests/test_admin_logs.py`.

Schemas to add:

- `AdminLogType` enum.
- `AdminLogActorRole` enum.
- `AdminLogSourceRef`.
- `AdminLogDeepLink`.
- `AdminLogRelatedEntity`.
- `AdminLogAction`.
- `AdminLogListItem`.
- `AdminLogListResponse`.
- `AdminLogDetailResponse`.
- Query parameter validation for filters listed in Section 5.

Service/query module responsibilities:

- Validate filter/scope inputs.
- Build source-specific compact queries for:
  - `upload_logs`
  - `warning_issues`
  - `upload_warnings` as related occurrence evidence, not a duplicate default row source unless `upload_warning_id` detail is requested
  - `audit_logs` warning actions
  - `audit_logs` parsed-data corrections
  - `audit_logs` source-cell corrections
  - `audit_logs` config mutations
  - `audit_logs.metadata_json.data_revalidation` projections, if requested
- Normalize rows into `AdminLogListItem`.
- Merge/sort rows by `occurred_at DESC, id DESC`.
- Apply pagination after source filtering without loading raw summaries.
- Fetch bounded detail by prefixed id.
- Redact/deny out-of-scope rows server-side.

Endpoints to add:

```http
GET /admin/logs
GET /admin/logs/{id}
```

`GET /admin/logs` response:

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

`GET /admin/logs/{id}` response:

```json
{
  "id": "warning:<warning_issue_id>",
  "log_type": "warning",
  "list_item": {},
  "immutable_evidence": {},
  "workflow_status": {},
  "related_entities": [],
  "available_actions": []
}
```

Implementation sequence:

1. Add schemas and unit-test model validation for list/detail rows.
2. Add service helpers for actor normalization, prefixed ids, source refs, and deep links.
3. Add upload log compact projection without selecting raw `summary`; use precomputed columns only where available, or bounded summary-derived counts only if no alternative exists and the response remains compact.
4. Add warning issue projection using `warning_issues` plus latest `upload_warnings` occurrence.
5. Add audit log projections for warning actions, parsed-data/source-cell corrections, config mutations, and optional Data Revalidation metadata.
6. Add authorization filters for master admin, programme PC, empty/null scope, global/null logs, mixed upload types, and linked warning/correction scopes.
7. Add route handlers.
8. Add tests.
9. Update docs if implementation diverges from this contract.

Test files to add:

- `backend/tests/test_admin_logs.py`

Authorization tests:

- Programme PC cannot see other programme logs.
- Programme PC with empty/null programme scope cannot see logs.
- Explicit master admin can see all logs.
- Master admin is not inferred from null programme scope.
- Null/global logs are master-only.
- TTF upload logs are PC-visible only for programmes in scope.
- RDB/FormF1/Public Holiday upload logs are master-only in 3I-B.
- Warning action/source-cell correction visibility follows linked warning issue scope.

Performance/guard tests:

- List endpoint returns compact rows.
- List endpoint does not include `summary`, `before_json`, `after_json`, or large raw payload fields.
- Upload rows appear with `log_type = "upload"`.
- Warning issues appear with `log_type = "warning"`.
- Warning action rows appear with `log_type = "warning_action"` when audit sources exist.
- Source-cell correction rows appear with `log_type = "source_cell_correction"` when audit sources exist.
- Parsed-data correction rows appear with `log_type = "parsed_data_correction"` when audit sources exist.
- Config mutation rows appear with `log_type = "config_mutation"` when audit sources exist.
- Data Revalidation projections appear only from backing audit metadata and do not create persisted rows.
- Detail endpoint returns bounded detail.
- Detail endpoint does not include full raw `upload_logs.summary` by default.
- `include_raw_summary=true` behavior is either explicitly implemented and tested or rejected with a clear 422/501 until a raw endpoint exists.

Compatibility tests:

- Existing `GET /admin/upload-logs` still works.
- Existing `GET /admin/upload-logs/{id}` still works.
- Existing warning endpoints still work.
- Existing parsed-data/config mutation endpoints still work.
- `/admin/logs` does not mutate source tables.
- No compliance, snapshot, clawback, surplus, Redis, external resident export, file storage, email, or migration tooling is added.

3I-B acceptance checks:

- Programme PC cannot see other programme logs.
- `programme_scope = NULL` cannot see logs.
- Explicit master admin can see all logs.
- List endpoint returns compact rows.
- Upload logs appear as `log_type = "upload"`.
- Warning issues appear as `log_type = "warning"`.
- Warning action/correction/config logs appear if current audit sources exist.
- Detail endpoint returns bounded detail.
- Detail endpoint does not include giant raw `upload_logs.summary` by default.
- Existing `/admin/upload-logs` frontend compatibility remains.
- No compliance/snapshot/clawback/surplus work is added.

## 11. Pending Decisions / Gaps

- Final master-admin schema/auth flag remains pending for Supabase/JWT. Current Phase 1 stub uses explicit `X-Admin-Level`, but production must not rely on client-provided headers.
- Exact global/null-programme log visibility for programme PCs remains pending. 3I-B should default to master-only.
- Raw audit summary access remains pending: choose between `include_raw_summary=true`, a raw export/download endpoint, or a dedicated raw audit endpoint.
- Whether Admin Logs should remain a live read model or later gain a materialized/admin-log table remains pending. 3I-B should use a read model over existing sources.
- Frontend transition remains pending: replace `Upload Logs` nav with `Admin Logs` immediately, keep both during migration, or keep `Upload Logs` as a nested/source-specific view.
- Whether `data_revalidation` should be a separate visible row type by default or only an embedded detail/filter projection remains pending. 3I-B can support the filter from audit metadata without adding a new persisted event source.
- Whether current upload log list counts should eventually be denormalized out of `upload_logs.summary` remains pending. The future Admin Logs list should not depend on loading raw summaries.

## 12. Final Output Format

For Phase 3I-A completion, the Codex response should report:

1. Files inspected.
2. Files changed.
3. Summary of contract decisions.
4. Pending decisions.
5. Exact 3I-B endpoint plan.
6. Verification commands run, or `not run - documentation-only`.
7. Verdict: `SAFE TO COMMIT` if docs-only contract is coherent and no backend/frontend code changed unexpectedly; otherwise `NEEDS FIXES`.

