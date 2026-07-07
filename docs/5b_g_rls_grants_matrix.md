# 5B-G-E Supabase RLS, Grants, And Data API Readiness Matrix

Status: planning matrix only. RLS is not enabled here.
Last updated: 2026-07-06

## Purpose And Scope

This matrix plans future Supabase Row Level Security, grants, exposed-schema, and Data API posture for MATA. It is intentionally not an implementation. It does not modify migrations, does not enable RLS, and does not add policies.

Current Supabase posture to account for:

- Data API grants decide whether `anon`, `authenticated`, or `service_role` can reach a table, view, or function at all.
- RLS decides which rows those granted roles can see or mutate.
- Supabase's 2026 default-grants change makes explicit grants increasingly important for new `public` tables. MATA should treat Data API exposure as opt-in and reviewable.
- If MATA continues to use backend-mediated direct Postgres access for application data, most tables should stay reachable only through the backend, not through browser-facing Data API routes.

## Non-Negotiable Rules

- App-level authorization remains mandatory even after RLS. MATA scope rules are richer than simple row ownership.
- Supabase `user_metadata` must not authorize MATA access.
- Staff identity bridge is `users.supabase_user_id = auth.users.id`.
- MATA role, admin level, programme scope, posting scope, and active state come from `users`.
- NHG Resident and Non-NHG Resident MATA tokens are backend-verified artifacts, not Supabase Auth identities.
- Non-NHG tables are separate and must not feed NHG compliance, numerator, denominator, surplus, snapshots, clawback, or native reports.
- Service-role or privileged backend access must never be used to skip MATA authorization.
- Enabling RLS prematurely can break uploads, admin reports, staff provisioning, exports, future snapshots/clawback, and data revalidation.

## Policy Dimension Legend

- `master`: explicit Master Admin (`users.role = admin`, `users.admin_level = master`).
- `pc_scope`: Programme PC scope from `users.programme_scope`.
- `secretary_posting`: secretary posting scope from `users.posting_code`.
- `resident_own`: NHG Resident own-row ownership by `residents.id`.
- `external_own`: Non-NHG Resident own-row ownership by `external_residents.id`.
- `period`: reporting-period scoping or effective active period.
- `immutable_audit`: append-only or restricted mutation semantics for audit/history.
- `backend_only`: no direct browser/Data API access expected.

## Table Matrix

| Table | Data category | Direct browser access | Backend access mode | RLS posture | Policy dimensions | Grant/Data API posture | Required tests before enablement | Notes/risks |
|---|---|---|---|---|---|---|---|---|
| `users` | staff/admin-owned identity and scope | never expose directly | privileged backend for staff provisioning; normal backend for auth mapping | master-only/admin-only | master, pc_scope metadata, secretary_posting metadata, immutable_audit for handover traces | should not be browser-exposed; backend only | staff token maps only by `supabase_user_id`; user metadata ignored; inactive users rejected; null/blank scope grants no PC access | high-risk authorization table; service-role create/reset is backend-only |
| `residents` | native resident private identity | no direct browser access expected | backend scoped by resident/admin role | resident ownership candidate plus staff scoped policies | resident_own, pc_scope, master, period | safe only through backend | resident can read own identity; PC sees only programme scope; MCR uniqueness preserved | residents are not Supabase Auth users |
| `resident_postings` | native resident private schedule | no direct browser access expected | backend scoped by resident/admin role | resident ownership candidate plus staff scoped policies | resident_own, pc_scope, master, period | safe only through backend | resident own-postings only; PC programme scope; current posting not trusted from token | drives event visibility and compliance context |
| `attendance_records` | native attendance | no direct browser access expected | backend scoped by resident/admin role | resident ownership candidate | resident_own, pc_scope, master, period, immutable_audit for status changes | safe only through backend | resident own create/read/remove; duplicate guard; PC scoped reports; no session_type_id | Phase 6 compliance must read native attendance only |
| `external_residents` | Non-NHG resident private identity | no direct browser access expected | backend scoped by external resident/admin role | Non-NHG ownership candidate plus staff scoped policies | external_own, pc_scope, master | safe only through backend | external resident own identity; global MCR uniqueness; home cluster values only | never store in `users` or native `residents` |
| `external_resident_postings` | Non-NHG forecast posting schedule | no direct browser access expected | backend scoped by external resident/admin role | Non-NHG ownership candidate | external_own, pc_scope, master, period | safe only through backend | external resident own schedule; gaps/overlap validation; PC scoped export context | never use native `resident_postings` for Non-NHG |
| `external_attendance_records` | Non-NHG attendance/export-only | no direct browser access expected | backend scoped by external resident/admin role | Non-NHG ownership candidate plus admin export policies | external_own, pc_scope, master, period, immutable_audit | safe only through backend | external own history; PC scoped list/read/export; no native compliance joins | export-only; not NHG compliance data |
| `teaching_events` | teaching/event operational data | possible future read-only only after policy design | backend normal access; privileged bulk reads likely | staff scoped and resident visibility candidate | secretary_posting, pc_scope, resident_own via derived visibility, external_own via schedule, period | backend only for now; future read-only possible | secretary posting CRUD; PC programme-owned CRUD; resident visibility; external visibility; delete guarded by native and external attendance | visibility is derived; simple ownership policy is insufficient |
| `event_series` | recurring event metadata | no direct browser access expected | backend normal access | staff scoped policies candidate | secretary_posting, pc_scope if PC recurrence added | backend only | secretary can mutate own posting series; future PC series ownership clarified | child `teaching_events` may need programme ownership guard |
| `session_types` | reference/config | possible future read-only direct access | backend normal access | defer; read-only reference candidate | master for writes, pc_scope for scoped config if any | future read-only possible; writes backend only | read dropdowns; admin write restrictions | durations are display/tiebreaker, not compliance multipliers |
| `teaching_targets` | programme compliance config | no direct browser access expected | backend normal; bulk uploads | staff scoped policies candidate | pc_scope, master, period, immutable_audit through upload logs | backend only | PC scope on reads/writes; TTF full replace; no attendance guard; cache invalidation | sensitive because targets drive compliance |
| `teaching_name_catalogue` | visibility and session mapping config | no direct browser access expected | backend normal; bulk uploads | staff scoped plus resident visibility candidate | pc_scope, master, resident_own derived through posting/programme/r_year, period | backend only | resident event visibility; PC scope; TTF re-upload orphan behavior | single source of truth for keyword mapping |
| `posting_codes` | reference/config | possible future read-only direct access | backend normal | read-only reference candidate; admin write scoped | master, secretary_posting metadata, pc_scope for supported config | future read-only possible; writes backend only | canonical posting lookup; no regex derivation; secretary support flag | broad reference table but operationally sensitive |
| `programmes` | reference/config | possible future read-only direct access | backend normal | read-only reference candidate; admin write scoped | master, pc_scope for programme-specific edits | future read-only possible; writes backend only | programme flags; r_year_required; ay_date_category; native teaching mapping | no `compliance_variant`; do not expose write access |
| `reporting_periods` | operational config | no direct browser access expected | backend normal | staff scoped/admin-only candidate | master, pc_scope for read, period | backend only | activate/deactivate scope; no final close side effects | active status is operational, not freeze |
| `form_f1_records` | authoritative active/inactive private data | never expose directly | backend normal; upload/report reads | admin-only/staff scoped candidate | pc_scope, master, period, immutable_audit | should not be browser-exposed | PC scope by resident programme; resident no direct access; denominator gate verified | high sensitivity; drives denominator |
| `public_holidays` | reference/config | possible future read-only direct access | backend normal | read-only reference candidate | master for writes, secretary/read for event blocking | future read-only possible; writes backend only | PH hard block for secretary and ad-hoc creation | no direct denominator effect |
| `academic_month_boundaries` | reference/config for AY bucketing | no direct browser access expected | backend normal | read-only reference candidate | master for writes, period | backend only or future read-only | AY category lookup; overlap checks; upload replacement | required for month bucketing |
| `upload_logs` | upload/audit | never expose directly | backend scoped read/write | admin-only scoped policies candidate | pc_scope, master, immutable_audit, period | backend only | upload writes append audit; PC only scoped logs; no mutation of history | may contain parser summaries and operational metadata |
| `warning_issues` | upload/audit workflow | no direct browser access expected | backend scoped read/write actions | admin-only scoped policies candidate | pc_scope, master, immutable_audit | backend only | scoped list/read/action; status lifecycle; audit actor captured | durable issue records should not be public |
| `upload_warnings` | upload warning occurrences | never expose directly | backend scoped read | admin-only scoped policies candidate | pc_scope, master, immutable_audit | backend only | occurrence immutability; scoped issue visibility | append-only by upload occurrence |
| `audit_logs` | audit | never expose directly | privileged backend append; scoped backend read | master/admin-only; immutable | master, pc_scope for filtered reads, immutable_audit | never expose directly | no secret values; actor metadata safe; scoped admin logs | high-sensitivity history; service-role may be needed for append/read |
| `surplus_ledger` | future compliance/surplus state | never expose directly | backend compliance/reporting only | defer until compliance implemented | pc_scope, master, resident_own read maybe, period | backend only | read-time reallocation only; no external attendance; no cross-period carry | pre-reallocation values only |
| `period_snapshots` | future frozen compliance snapshot | no direct browser access expected | privileged backend generation/read | defer until final close/freeze | pc_scope, master, period, immutable_audit | backend only | snapshot generated once per programme/period; historical reads from snapshot | future final close only |
| `clawback_records` | future clawback output | never expose directly | privileged backend generation/read | defer until clawback implemented | master, pc_scope, period, immutable_audit | backend only | admin tab visibility; suppression reasons; no Non-NHG rows | sensitive financial/HR-adjacent data |
| `global_session_types` | reference/config; compliance-exempt catalogue | possible future read-only direct access | backend normal | read-only reference candidate; admin write scoped | master for writes | future read-only possible; writes backend only | dropdown inclusion; active-only; compliance exclusion priority | global sessions excluded before catalogue lookup |
| `multi_posting_rules` | config | no direct browser access expected | backend normal | staff scoped/admin-only candidate | master, pc_scope | backend only | CRUD scoped; parser applies at RDB upload; no FM special engine | wrong rules can alter compliance phases |
| `posting_groups` | config | no direct browser access expected | backend normal | staff scoped/admin-only candidate | master, pc_scope | backend only | group aggregation; TTF seed/upsert; CRUD scoped | affects target and active month aggregation |
| `weekend_exceptions` | config | possible future read-only direct access | backend normal | staff scoped/admin-only candidate | master, pc_scope | backend only or future read-only | weekend warning/exclusion; ORTHO read-time mutation; no FM seed | mutations must not alter raw attendance |
| `loa_types` | reference/config | possible future read-only direct access | backend normal | read-only reference candidate; admin write scoped | master for writes | future read-only possible; writes backend only | parser warning on unknown LOA; CRUD/admin only | not denominator authority |

## Cross-Table Test Requirements Before RLS Enablement

- Supabase staff JWT `sub` maps only through `users.supabase_user_id`.
- Supabase `user_metadata` and raw `X-User-*` headers cannot grant role, scope, posting, or admin level.
- Explicit Master Admin can access intended global/admin surfaces; null or empty programme scope never grants master.
- Programme PC can access only assigned `programme_scope`; blank-only scope is denied.
- Secretary can create/edit only assigned `posting_code` events.
- NHG Resident can see and mutate only own resident surfaces, with current posting derived from `resident_postings`.
- Non-NHG Resident can see and mutate only own external surfaces, with posting derived from `external_resident_postings`.
- Native compliance/reporting reads never join `external_attendance_records`.
- Uploads, warning actions, audit logging, and future data revalidation continue to work under any scoped policy model.
- Admin reports, exports, final close/freeze, snapshots, surplus hibernation, and clawback jobs have documented privileged backend paths before RLS is enabled.
- Data API grants are reviewed explicitly; tables not intended for browser access are not exposed through browser-facing schemas.

## Open Readiness Items

- Decide whether MATA should disable or avoid browser-facing Supabase Data API access entirely for app data.
- Decide whether to keep all MATA application tables in `public` with explicit grants/revokes or move future exposed objects to a dedicated API schema.
- Write a formal RLS policy test harness after final access surfaces are stable.
- Revisit this matrix after Phase 6 compliance SQL and future final close/freeze jobs exist.
