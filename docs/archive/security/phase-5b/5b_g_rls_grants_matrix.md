# 5B-G-E Supabase RLS, Grants, And Data API Readiness Matrix

> **Current contract:** `docs/security.md`. This file is retained as dated
> planning and catalogue evidence and does not override the current security
> contract.

Status: historical 5B-G planning matrix reconciled with the locally implemented 5B-H-E catalogue; deployed verification pending.
Last updated: 2026-07-27

## Purpose And Scope

This matrix originally planned future Supabase Row Level Security, grants, exposed-schema, and Data API posture for MATA. The original risk/dimension matrix remains below as historical design input. Phase 5B-H-E subsequently implements the local role, context, policy, and grant cutover in migrations `20260726_000025` and `20260726_000026`; this document now reconciles the design with that implementation. It still does not establish deployed Supabase state.

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
- An incomplete RLS/policy/helper cutover can break uploads, admin reports, staff provisioning, exports, future snapshots/clawback, and data revalidation.

## Policy Dimension Legend

- `master`: explicit Master Admin (`users.role = admin`, `users.admin_level = master`).
- `pc_scope`: Programme PC scope from `users.programme_scope`.
- `secretary_posting`: secretary posting scope from `users.posting_code`.
- `resident_own`: NHG Resident own-row ownership by `residents.id`.
- `external_own`: Non-NHG Resident own-row ownership by `external_residents.id`.
- `period`: reporting-period scoping or effective active period.
- `immutable_audit`: append-only or restricted mutation semantics for audit/history.
- `backend_only`: no direct browser/Data API access expected.

## H-E Implemented Role And Object Boundary

- `mata_app_runtime` and `mata_auth_internal` are stable `NOLOGIN`, `NOINHERIT`, non-owner, `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`, and `NOREPLICATION` capability groups.
- Runtime, auth-helper, and migration/ownership login credentials are distinct. Startup attestation rejects ownership, privileged or cross-capability membership, delegable membership/grants, unexpected helpers or table/column actions, sequences, unsafe policies, schema creation, or browser/PUBLIC access.
- Protected queries receive database-revalidated, signed transaction-local identity. FastAPI authorization remains mandatory.
- All 34 application tables have RLS enabled; none has `FORCE ROW LEVEL SECURITY`. The 84 policies target only `mata_app_runtime`.
- Current direct browser/Data API application access is **none**, including for rows the historical matrix labeled as possible future read-only candidates.
- `mata_auth_internal` has no direct application-table or sequence privilege. `PUBLIC` and optional `anon`, `authenticated`, and `service_role` roles have no application-relation, H-E helper, or `CREATE` authority in `public`.
- Default privileges grant no future application tables, sequences, or functions to runtime, auth, browser, or PUBLIC roles. Future objects require explicit review.

Revision `20260728_000028` retains those table actions but narrows how Resident
ad-hoc rows are created. Ordinary `teaching_events` and attendance INSERT
policies accept scheduled paths only. `mata_app_runtime` alone may execute
`mata_rls.create_adhoc_attendance(...)`, which derives the verified subject and
native/external family, persists immutable typed creator ownership, and creates
the matching event/attendance pair without committing. `mata_auth_internal`,
PUBLIC, browser roles, and `service_role` have no execution right. Update
policies plus immutable triggers allow only the exact creator's matching-family
attendance removal and reject subject/event retargeting or in-place
resurrection.

| Application table | Implemented runtime actions |
|---|---|
| `academic_month_boundaries` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `app_sessions` | helper-only; no direct table privilege or table policy |
| `attendance_records` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `audit_logs` | `SELECT`; append through reviewed helper |
| `clawback_records` | helper-only; no direct table privilege or table policy |
| `event_series` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `external_attendance_records` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `external_resident_postings` | `SELECT`; own schedule mutations use reviewed helpers |
| `external_residents` | `SELECT`; registration/current-posting writes use reviewed helpers |
| `form_f1_records` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `global_session_types` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `loa_types` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `multi_posting_rules` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `period_snapshots` | helper-only; no direct table privilege or table policy |
| `posting_codes` | `SELECT` |
| `posting_groups` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `programme_institution_posting_map` | helper-only; no direct table privilege or table policy |
| `programmes` | `SELECT`, `UPDATE` |
| `public_holidays` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `rate_limit_buckets` | helper-only; no direct table privilege or table policy |
| `reporting_periods` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `resident_postings` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `residents` | `SELECT`, `INSERT`, `UPDATE` |
| `secretary_programme_pools` | `SELECT` |
| `session_types` | `SELECT` |
| `surplus_ledger` | helper-only; no direct table privilege or table policy |
| `teaching_events` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `teaching_name_catalogue` | `SELECT`, `INSERT`, `DELETE` |
| `teaching_targets` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `upload_logs` | `SELECT`, `INSERT` |
| `upload_warnings` | `SELECT`, `INSERT` |
| `users` | `INSERT`, `UPDATE`; column-limited `SELECT` on 16 non-password columns |
| `warning_issues` | `SELECT`, `INSERT`, `UPDATE` |
| `weekend_exceptions` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |

The action list describes grants and policy command coverage, not unconditional row access. `USING` and `WITH CHECK` predicates still enforce Master Admin, Programme PC scope, secretary posting/pool, native resident, Non-NHG Resident, period, catalogue, event, and attendance relationships.

## Historical 5B-G Design Matrix

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

## Cross-Table H-E Verification Contract

The local direct policy matrix and existing application suite exercise these invariants under restricted credentials:

- Supabase staff identity maps only through the current database-owned `users.supabase_user_id`; `user_metadata` and raw `X-User-*` headers cannot grant role, scope, posting, or admin level.
- Explicit Master Admin sees intended global/scoped rows but still cannot query helper-only tables directly.
- Programme PC sees and mutates only rows in normalized `programme_scope`; null, empty, and blank-only scopes fail closed.
- Secretary event, roster, attendance, series, and catalogue access remains bound to its exact posting and approved programme pool.
- NHG Resident sees and mutates only its native resident/posting/event/attendance surface and sees no external identity or attendance rows.
- Non-NHG Resident sees and mutates only its own external identity/schedule/event/attendance surface and sees no native resident or attendance rows.
- Native and external attendance remain separate; external rows never enter native compliance.
- Native and external ad-hoc ownership is persistent and exact: only the
  creator can select the ad-hoc event through a Resident context, only the
  matching attendance family can attach, and another Resident cannot reuse the
  event. Scheduled-event policy behavior is unchanged.
- Uploads, warnings, audit logging, reports, event guards, registration, session lifecycle, rate limits, and other existing workflows run through either scoped runtime policies or a reviewed helper boundary.
- Revision `20260727_000027` replaces restricted execution of the original
  full-row session resolve/issue/rotate functions with minimal lifecycle
  wrappers. Runtime/auth capabilities receive only identity/binding results,
  a refresh boolean, and CSRF/touch booleans; stored token/CSRF digests, expiry
  fields, and derived client lifetimes are not returned.
- The revision-owned lifecycle subset contains exactly eight helpers: three
  auth-only issuance wrappers, three shared resolve/touch/CSRF helpers, one
  runtime-only rotation helper, and
  `revoke_app_session_family_for_logout(bytea,bytea,text)`, which is auth-only.
  Runtime, PUBLIC, browser roles, and `service_role` have no execute authority
  on the logout helper. It accepts only keyed token/CSRF digests, derives the
  subject and family server-side, and exposes no hydration, signed-context,
  touch, rotation, or refresh capability.
- Bounded cleanup retains a `rotated` parent as logout proof until the
  immutable family absolute deadline, even if the parent's superseded idle
  deadline or the configured retention interval has already passed. A shorter
  retention value cannot remove that proof early or make a valid child
  eligible.
- No-context queries fail closed, helper-only table queries are permission denied, and public/browser roles remain denied.

## Open Readiness Items

- Independently verify the same revision, role/ownership catalogue, grants, policies, helper ACLs, default ACLs, and five-role workflows on the approved deployed target.
- Keep browser-facing Supabase Data API access disabled for MATA application data unless a separately approved future design adds a narrowly reviewed interface.
- Revisit the policy/action catalogue when a future table or workflow is implemented; default denial is not permission to omit explicit RLS review.
- Revisit this matrix after Phase 6 compliance SQL and future final close/freeze jobs exist.
