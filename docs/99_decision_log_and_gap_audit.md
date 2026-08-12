# 99_decision_log_and_gap_audit.md — MATA Dashboard Decision Log and Gap Audit

> **Purpose:** This is the exhaustive safety and audit document for the MATA project. It is not meant to be read linearly — it is a reference and audit trail for decisions, TBDs, rejected approaches, risks, and blind spots.
>
> **Authority:** This document is the current decision and gap audit trail. If it conflicts with `schema.md`, `api.md`, `business-logic.md`, `parsing.md`, `auth-account-contract.md`, `security.md`, or `AGENTS.md`, trust the domain-specific source-of-truth file and flag this document for update. `security.md` is the current cross-cutting security contract; archived Phase 5B records are supporting historical evidence only.
>
> **Status markers:** ❓ unresolved, ⚠️ high-risk, ✅ confirmed, 🔧 partially implemented, ❌ deprecated

---

## Section 1 — Complete Decision Log

Every important decision made during the project, with reasoning and consequences.

### Decision: Evolved TTF transition contract (2026-08-02)

- **Status:** Phase G Resident/Non-NHG runtime decoupling and its D/F/G audit
  corrections are implemented at local revision `20260804_000035`; revision
  `20260805_000036` completes the final E2+B2 cutover.
- **Current boundary:** The parser accepts A–J only: reporting period,
  programme, R-year, posting, dashboard posting/posting group, session type,
  monthly target, tracked, reallocatable, and tag. It physically removes
  `teaching_name_catalogue` and `teaching_targets.details_of_training` without
  reconstructing historical catalogue rows or Column K text. A populated legacy
  Column K receives controlled `422`; there is no dual format, backfill, or
  workbook-text-driven Teaching Name/mapping creation. Historical warning and
  audit evidence remains immutable.
- **Runtime preservation:** Phase F source IDs and immutable display snapshots,
  plus revision `20260804_000035` immutable pool-source programme/period
  snapshots, remain the event/attendance authority. Guarded Teaching Name
  deletion cannot erase provenance. Phase G uses persisted source evidence where
  present, keeps both-null legacy rows as deterministic persisted evidence, and
  never infers authorization from display text. Global type inactivity gates new
  choices only; full-datetime overlap treats a wrapped end time as the next date.
- **Terms and ownership:** The canonical term is `teaching_name`. The schedule
  column is **Name of Teaching**; the Secretary page/button are **Update Names
  of Teaching** / **Update Name of Teaching**; Programme PC navigation/page are
  **Session Types** / **Map Names of Teaching to Session Types**. Pools are
  scoped by `(reporting_period_id, programme_code)`, begin empty for each new
  period, do not copy forward, and preserve prior periods as history. Explicitly
  authorized Secretaries and Programme PCs may create, rename, deactivate, and
  reactivate names; only PCs may map names to targets. **Historical deletion
  rule (superseded by the current Phase C rule below):** Master Admin may
  hard-delete only an unused name.
- **Current Phase C deletion rule:** Secretary and Programme PC may hard-delete
  unused names only. Master Admin may also delete a used name through the
  guarded destructive workflow with the current revision, explicit force intent,
  a nonblank reason, and exact `DELETE` confirmation. The Teaching Name identity
  is removed, while events, immutable event display text, and attendance remain
  preserved.
- **Normalization and mappings:** Normalize Unicode canonically, trim outer
  whitespace, collapse internal whitespace, and enforce case-insensitive
  uniqueness while preserving punctuation/wording. No fuzzy, abbreviation,
  synonym, or semantic matching. An exact mapping is scoped by period,
  programme, posting, R-year, and Teaching Name to one exact target. Null target
  is pending; non-null is mapped; no excluded state exists. Pending names remain
  selectable, visible, attendance-capable, and auditable, but are excluded from
  compliance until a mapping resolves on the next JIT read without raw-data
  rewrite.
- **Provisioning and fencing:** Name creation provisions pending rows for
  existing posting/R-year scopes; reactivation reconciles scopes added while
  inactive; TTF scope creation provisions missing rows; a session type added to
  an existing scope does not duplicate a mapping; removed scopes remain pending
  or are reconciled under final target-cutover rules. Existing name/mapping
  mutations are revision-fenced. Phase D mapping apply validates the current
  mapping revision and exact selected-target scope, returns count-only impact,
  and requires an explicit retry confirmation only when current impact is
  nonzero. It uses no confirmation token or client-supplied scope fingerprint.
- **Event, authority, and security:** Pool events carry `teaching_name_id` and
  no global ID; global events carry `global_session_type_id` and no Teaching
  Name ID; legacy rows may have neither but never both. Pool events belong to
  exactly one programme through their name; PC programme must match and text
  fan-out is forbidden. Pool events accept start only, compute end server-side,
  store the longest effective posting/R-year duration as the staff envelope,
  use a temporary one-hour contribution for each pending R-year, and reject
  starts after 23:00. Different R-years may map the same Teaching Name to
  different duration-bearing targets; each exact R-year identity still selects
  only one target. Native Resident views use the event-date R-year duration,
  while Non-NHG views use exact posting visibility and the staff envelope.
  Mapping changes recalculate existing exact-scope event timing while
  preserving attendance and immutable source/display snapshots. Secretary write
  authority is an explicit Secretary-to-programme capability (TTSH GERI pilot),
  not native-teaching-posting visibility. Mutations use current CSRF,
  authorization, rate-limit, audit, and post-commit cache-invalidation
  contracts. Globals remain Admin-managed/outside the queue; ad-hoc remains
  fixed to `Department/Programme Teaching [1h]`; Non-NHG remains outside NHG
  compliance.
- **Current Phase R RLS alignment:** Revision `20260806_000038` requires a
  Programme-PC pool-event write to match an existing Teaching Name mapping at
  the exact source period, source programme, and requested posting. A pending
  mapping is sufficient; missing or cross-posting scope is denied. This is a
  defence-in-depth match for the application authorization and does not alter
  Secretary, Master, Resident, or cross-programme authority.
- **Historical module labels:** Later historical entries that refer to
  `compliance.py` or `surplus.py` in a consequence, blind-spot, or planned
  module column describe the future specification only. They are not evidence
  that either full engine exists in current application code.
- **Phase 6 boundary:** Non-clawback Phase 6 logic is specified, not
  implemented; no full `compliance.py` engine is currently implemented.

This decision is implemented by E2+B2. Later entries documenting Column K or
catalogue behavior are pre-cutover audit evidence only; do not reinterpret them
as current parser, API, runtime, or authorization behavior.

---

### Phase 6-A confirmed non-clawback decisions (2026-07-20)

These entries supersede any earlier contradictory current-state entry in this audit log. They resolve the ordinary compliance specification only; they do not claim that Phase 6 application code or tests are implemented.

1. **FormF1 follows the AY bucket label.** Calendar-month storage remains, but the AY bucket `month_label` selects one FormF1 status for both numerator and denominator across the whole bucket. Do not split/prorate or use the event's raw calendar month.
2. **Overlapping distinct events.** For the same resident, reject a later submission that overlaps an earlier accepted distinct event. Preserve the earlier attendance. Same-event database uniqueness remains separate.
3. **ORTHO mutation.** Only exact original type `NHG Orthopaedic Surgery Residency Teaching [3h]` is eligible. Preserve raw rows, subtract two hours from original end time, project to `National Didactics & Department Teaching [1h]`, then apply the Saturday 08:30–10:30 window to adjusted time. Sunday remains excluded; other ORTHO types are not mutated.
4. **Multi-posting types stay distinct.** `main_posting` collapses sources to one configured existing `main_posting_code`; `combine` persists one configured canonical combined posting code that already exists and has TTF rows; `half_month` preserves both posting identities and unchanged TTF targets with `active_months_weight = 0.5` applied once. Posting groups may aggregate later when separately configured.
5. **Native-programme event attribution.** Phase G preserves an approved native-programme event and its attendance without current projection or target resolution. If Phase 6 later permits attribution outside the assigned posting, it must use persisted source identity and a scoped mapping under the assigned posting; do not create creator-posting, native-teaching-posting, or separate native compliance results.
6. **Persisted source/mapping resolution is deterministic and not a Phase 6 blocker.** Scheduled events carry explicit source IDs or deterministic both-null legacy evidence. Any future resolution is scoped by source identity, reporting period, resident programme, assigned/compliance posting, and phase R-year. Display snapshot case/spacing is audit/UI data only; no text matching or fuzzy matching is permitted.
7. **SPORTSMED/PALLMED use R4–R6.** Both have `r_year_required = true` and `is_subspecialty = false`; neither uses `ALL` nor R4→SS1/R5→SS2/R6→SS3 remapping. This supersedes the former 22/6 and subspecialty-remap decision: the split is now 20 `ALL` programmes and 8 R-year-required programmes.
8. **Mid-period R-year contexts are independent until posting summation.** Resolve event phase R-year, calculate correctly weighted target, and cap each `(physical posting, session type, R-year context)` separately; then sum capped results/targets. Never merge raw attendance first or duplicate posting-wide active months.
9. **Percentage is canonical.** `met_70pct = percentage >= 0.70` using the unrounded posting percentage. Green/amber/red boundaries are 70%/50%. `target_70 = ceil(target_100 × 0.70)` is a displayed whole-session target. For a failing result, displayed shortage may be `ceil((target_100 × 0.70) - achieved_and_counted)`; otherwise zero.
10. **Tag reallocation uses raw session counts before final capping.** Transfers are one-for-one within one physical posting, R-year context, and tag prefix; tags sort alphabetically, earlier donates to later, donor supply is raw above the type's 70% target, recipient demand is only to that target, and supply is decremented. Duration is never transferred/multiplied; group membership never permits cross-posting transfer. Cap each type/R-year context after all transfers. Reallocation is read-time only and never stored in the ledger.
11. **Persistent surplus is derived audit state.** Per resident/physical posting/session type/period, replace idempotently with `max(cumulative raw eligible attendance - cumulative target_100, 0)` before tag reallocation. Never increment it, add it back to attendance, or consume it as an independent credit. Recompute on return, hibernate/unhibernate by phase lifecycle, and reset at the period boundary while preserving closed history where supported.

**Clawback status:** DEFERRED. Norm rates/effective dating, funding R-year, financial classification, suppression granularity/precedence, grouped identity, billing attribution, missing-rate behavior, rounding/precision, and final-close transaction/rerun/idempotency remain unresolved. The future failure trigger must use the same unrounded percentage, but no further financial contract is implied.

---

#### Decision: TTF zero monthly target semantics
- **Status:** Confirmed
- **Decision:** `teaching_targets.monthly_target = 0` is valid. The final A–J target row remains persisted; TTF creates no Teaching Name or mapping from the row. Phase G Resident/Non-NHG event discovery and attendance use persisted event-source evidence instead.
- **Compliance consequence:** Zero-target rows contribute to neither numerator nor denominator and create no percentage, shortage, surplus, reallocation, or clawback contribution.
- **Do not change without PM/stakeholder approval:** Yes

#### Decision: FormF1 blank monthly status semantics
- **Status:** Confirmed
- **Decision:** `Active` and `Extension` map to active. `Inactive`, blank, `NULL`, and whitespace-only monthly status cells map to inactive. A valid MCR row persists an inactive record for every blank in-scope reporting-period month.
- **Boundary:** A blank MCR with no monthly values remains the parser's end/skip-row condition. Unknown non-blank statuses remain warning-only, retain `status_raw`, use the existing active fallback, and persist an `unknown_formf1_status` warning containing the value and Excel cell reference. Blank statuses do not create this warning.
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Vercel stakeholder UAT requires a deployment security cut before Phase 6 compliance
- **Status:** Confirmed historical H-A/B/C protected-UAT sequencing
- **Decision:** Stakeholder UAT needs a protected Vercel/Supabase deployment before Phase 6 compliance starts. Vercel deployment must not be treated as safe just because the frontend uses Supabase Auth.
- **Deployment access control:** The UAT deployment should be protected from public access where possible, for example Vercel Deployment Protection, Vercel Authentication, or password protection depending on project plan availability.
- **Backend runtime requirement:** Backend must run with `ENV=production` and `AUTH_MODE=supabase` for stakeholder deployment. Raw `X-User-*` identity headers must remain rejected in production/Supabase mode.
- **CORS requirement:** CORS must be restricted to the exact Vercel frontend origin or approved frontend origins. Wildcard CORS is not acceptable for UAT or production-like deployment.
- **Frontend env requirement:** Vercel frontend environment variables must be browser-safe `VITE_*` values only. Backend-only secrets must never be placed in Vercel frontend env, including:
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `MATA_RESIDENT_SESSION_SECRET`
  - `DATABASE_URL`
  - `SYNC_DATABASE_URL`
  - JWT/private secrets
  - database passwords
- **Supabase direct access requirement:** The Supabase frontend client should be used only for Auth unless a later RLS/grants phase explicitly approves direct table access. Supabase app table/Data API exposure must be reviewed before UAT.
- **Phase boundary:** Full RLS enablement and policy SQL remain deferred to a dedicated RLS phase. Cookie/BFF/CSRF/session hardening remains part of 5B-H, with the deployment-safe cut first.
- **Compliance sequencing:** Phase 6 compliance should not begin until the protected deployment/security baseline is acceptable.
- **Non-NHG invariant:** Non-NHG data remains separate and must not enter NHG compliance later.
- **Reference file and section:** `docs/archive/security/phase-5b/5b_h_vercel_uat_security_plan.md`; `docs/auth-account-contract.md` 5B-H roadmap alignment; `docs/archive/security/phase-5b/5b_g_rls_grants_matrix.md`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: 5B-H-D backend-owned session transport and intentionally public authentication boundary
- **Status:** Implemented in code and locally verified; deployment evidence pending
- **Decision:** Normal production browser transport uses backend-owned opaque PostgreSQL sessions. Staff credentials are submitted to the backend, which mediates Supabase authentication and does not return upstream access or refresh tokens. NHG and Non-NHG Resident MCR login use the same opaque application-session envelope while preserving separate identity tables.
- **Public boundary:** Staff login, Resident login, registration options, and Non-NHG registration are intentionally public application entry points. They do not require a Vercel outer gate. Exact production Origin validation where applicable, JSON-only public mutations, generic errors, persistent PostgreSQL rate limits, and application authorization remain mandatory.
- **Browser boundary:** Production uses relative `/api/v1`, credentialed cookie requests, memory-only identity/CSRF state, and no routine bearer persistence or injection.
- **Session boundary:** `__Host-mata_session` is host-only, `Secure`, `HttpOnly`, `SameSite=Strict`, and `Path=/`. Raw session and CSRF values are 256-bit and only keyed digests persist. One-winner family rotation, family logout, expiry, generation fencing, and password-reset issuance blocking fail closed.
- **Database boundary:** `20260722_000023` adds application sessions and subject generations. `20260722_000024` revokes application-object privileges from `PUBLIC` and optional browser roles. This is not full RLS; Phase 5B-H-E owns the restricted runtime role, trusted transaction context, policies, and full-table verification.
- **Dependency disposition:** The final sanitized `pip-audit`, npm runtime audit, and npm full-tree audit reported zero findings. Exact advisory history and version changes are recorded in `docs/archive/security/phase-5b/5b_h_d_production_security_implementation.md`.
- **Verification:** Complete backend `1104 passed, 7 warnings`; focused H-D security `230 passed, 1 warning`; PostgreSQL security integration `13 passed`; 20/20 process-isolated concurrent-rotation repeats; frontend `78 passed` plus lint, typecheck, and production/Supabase build.
- **Evidence boundary:** Code completion and local verification do not prove deployed security.

Resident identity assurance remains separately governed product debt. Reopen
only under an approved product scope.

---

#### Decision: 5B-H-E full PostgreSQL RLS and restricted database roles
- **Status:** Implemented in code and verified against the named local disposable PostgreSQL database; deployment evidence pending
- **Decision:** Normal application SQL runs through a distinct credentialed login that inherits only the non-owner, `NOBYPASSRLS` `mata_app_runtime` capability. Intentionally unauthenticated auth/registration/session infrastructure uses a second login that inherits only `mata_auth_internal`. Alembic and ownership use a third credential that is never an application credential.
- **Trusted context:** PostgreSQL reloads the current application session and subject and installs signed transaction-local subject type/id, app role, explicit admin level, normalized programme scope, posting code, application-session id, and authorization fingerprint. Browser claims, request JSON, raw identity headers, frontend state, and Supabase `user_metadata` cannot seed it. Every new root transaction revalidates context, including after mid-request commit or rollback.
- **Policy and grant boundary:** Revision `20260726_000026` enables RLS on all 34 application tables and creates 84 policies targeted only to `mata_app_runtime`. Six tables remain helper-only with no direct runtime table privilege. `mata_auth_internal` has no direct application-table or sequence privilege. PUBLIC and optional `anon`, `authenticated`, and `service_role` roles have no application-object, H-E helper, or schema-creation authority.
- **Application boundary:** FastAPI authorization remains mandatory. RLS is defense in depth and must not broaden or replace current route/service role, programme, posting, resident, external-resident, period, or workflow checks.
- **Identity separation:** Native and Non-NHG Resident rows, schedules, attendance, and compliance eligibility remain separate. Migration `20260726_000025` adds serialized database-level normalized MCR uniqueness across the two identity tables.
- **Evidence boundary:** Local tests and catalogue inspection do not prove deployed Supabase revision, roles, ownership, policies, grants, environment, or runtime behavior.
- **Reference files:** `docs/archive/security/phase-5b/5b_h_e_full_rls_implementation.md`; `docs/archive/security/phase-5b/5b_g_rls_grants_matrix.md`; `docs/schema.md`
- **Do not change without PM/security-owner approval:** Yes

---

#### Decision: Admin accounts are programme-scoped
- **Status:** ✅ Confirmed
- **Decision:** Admin/PC accounts use `users.programme_scope TEXT[]` to restrict access to specific programmes. `NULL` = no access (not all-access).
- **Reasoning:** PCs manage specific programmes — they should not see data for programmes they don't own. Multiple programmes per account supported for PCs who manage several.
- **Alternatives considered:** (1) Single global admin role — rejected, violates least-privilege. (2) Separate admin table — rejected, unnecessary complexity.
- **Consequences for codebase:** Every admin endpoint must filter by `programme_scope`. Admin report queries include `WHERE r.programme_code = :programme_code`, with programme scope validated from the current database-owned staff subject loaded through the opaque app session.
- **Reference file and section:** `schema.md` § `users` table; `api.md` § Authentication Model
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Non-NHG / cross-cluster residents workflow (Phase 5B)
- **Status:** ✅ Confirmed implementation direction
- **Decision:** Non-NHG Residents are residents from `NUH` or `SingHealth` who are posted to NHG departments. They use a separate `external_residents` table and separate `external_attendance_records` table. Native NHG Residents remain RDB-backed in `residents` + `resident_postings`.
- **User-facing label:** Use **Non-NHG Resident** in UI and user-facing documentation. Existing backend/internal terms such as `external_residents`, `external_resident_postings`, `external_attendance_records`, and `external_resident` role names remain valid implementation names.
- **Registration capture fields:** `name`, `mcr`, `home_cluster` (`NUH` or `SingHealth`), and a date-bounded upcoming NHG posting schedule. The older single `current_nhg_posting_code` pointer may remain as a current/cache/backward-compatibility field, but it is no longer the long-term sole source for date-sensitive event/ad-hoc derivation.
- **MCR uniqueness:** MCR is globally unique for every doctor. Because native and external identities use separate tables, enforce cross-table uniqueness in service logic: reject registration if MCR exists in either `residents` or `external_residents`.
- **Workflow direction:** Non-NHG Residents self-register on first use. After registration, they use the same shared Resident MCR field as NHG Residents. The frontend sends one neutral `role = resident` request and never selects, infers, or retries an identity subtype; the backend resolves the unique native/external match and returns the authenticated role. Non-NHG Residents may self-update their upcoming NHG posting schedule.
- **Posting model:** Non-NHG date-bounded forecast postings are stored in `external_resident_postings`; do not use native `resident_postings`. Each row retains the validated `programme_code` and resolved `posting_code`, and authorization-sensitive event/ad-hoc derivation uses the row matching the selected event date.
- **Scheduled-event sources:** A date-matched schedule row authorizes every normal scheduled Department Secretary or Programme PC event at its exact posting. Non-NHG Residents do not resolve NHG compliance, R-year mappings, PC programme ownership, or the Secretary capability for this list. Listing and attendance submission enforce the same exact-posting rule and use the staff event envelope.
- **Functional scope:** Phase 5B must be completed before Phase 6 compliance. It includes Non-NHG registration/login, upcoming NHG posting schedule update, supported event listing, attendance submission, revised ad-hoc teaching submission, past attendance, admin/PC external attendance list/read, and Excel export for forwarding to NUH/SingHealth PCs.
- **Explicit exclusions:** Non-NHG Residents are excluded from NHG compliance and clawback surfaces:
  - no NHG resident compliance dashboard
  - no clawback output
  - no NHG compliance numerator inclusion
  - no NHG compliance denominator inclusion
  - no surplus ledger / period snapshot inclusion
- **Export requirement:** Non-NHG attendance must be queryable by authorized admin/PC users and exportable to Excel for onward sharing to relevant NUH or SingHealth PCs.
- **Export status:** ✅ Confirmed before compliance. Exact endpoint response metadata and workbook columns are implementation details, but the export format is Excel.
- **Do not use:** `users`, `programme_scope`, native `residents`, or native `resident_postings` for Non-NHG Resident identity/posting state.
- **Reference file and section:** `schema.md` § `external_residents`, `external_resident_postings`, `external_attendance_records`; `api.md` § Non-NHG Resident Endpoints; `business-logic.md` § BL-12
- **Do not change without PM/stakeholder approval:** Yes
---

#### Decision: Two-stage programme/institution posting mapping rollout (Phase 5B)
- **Status:** ✅ Confirmed; Stage 2 mapping state approved
- **Decision:** Non-NHG registration and schedule updates resolve `(programme_code, institution_code)` only through `programme_institution_posting_map`. The resolver trims/uppercases inputs, rejects blanks/control characters, requires one active row with a non-null valid posting FK, and fails closed for pending, inactive, missing, or malformed configuration.
- **Stage 1:** Generic backend/frontend infrastructure seeded one pending/null TTSH row for each of the 28 baseline programmes as a safe initial state.
- **Stage 2:** Apply the approved configuration through one transactional data-only Alembic migration after validating the complete baseline, every programme and posting FK target, blanks, duplicates, set disjointness, and final counts. The final TTSH state is 24 exact active mappings, four inactive/null mappings (`FM`, `PATH`, `SPORTSMED`, and `PALLMED`), and zero pending mappings. Any validation failure rolls back the entire migration; no inferred codes or manual production SQL is allowed.
- **Public options:** TTSH exposes only the 24 active programme choices, each sourced from `programmes.code` and `programmes.name` and marked available/active. The four inactive mappings are omitted, and posting codes are never exposed by the registration-options response.
- **Inactive scope:** Mapping status here affects only Non-NHG programme/institution registration and schedule selection. It does not deactivate `FM`, `PATH`, `SPORTSMED`, or `PALLMED` globally or change native NHG Resident behavior, Secretary capabilities, visibility, TTF/targets, or compliance.
- **Scalability:** Future KTPH, WH, or other institutions are added through mapping rows only. No institution enum, resolver branch, or frontend production array is allowed.
- **Forbidden derivation:** Do not construct codes, fuzzy-match metadata, use posting prefixes, pick a first candidate, or fall back to `programmes.native_teaching_posting_code`, Secretary programme pools, teaching targets, or `posting_codes.institution`.
- **Isolation:** External-registration mappings do not grant Secretary event creation/visibility, alter native resident visibility, populate `native_teaching_posting_code`, toggle `supports_secretary_events`, or change compliance attribution.
- **Reference file and section:** `schema.md` § `programme_institution_posting_map`; `api.md` § Non-NHG Resident Endpoints; `business-logic.md` § BL-12; `auth-account-contract.md` § Non-NHG Resident Register + MCR Login
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Programme PC teaching event CRUD before compliance
- **Status:** Implemented in Phase 4B
- **Implementation phase:** Implemented in Phase 4B.
- **Decision:** Add pre-compliance roadmap item `4B - Programme PC Teaching Event CRUD`. Programme PCs must be able to create, list, edit, delete, duplicate, and manage scheduled teaching events for their own programmes where practical, similar to department secretary event CRUD.
- **Ownership model:** PC-created teaching events are scheduled teaching events, not ad-hoc submissions. They carry explicit programme ownership/scope via nullable field `teaching_events.created_for_programme_code`: required for PC-created programme-owned events and null for normal secretary-created posting-owned/programme-neutral events unless an explicit future use case sets it.
- **Scope and auth:** Backend authorization is mandatory: `role = admin`, requested `programme_code IN programme_scope`, and null/empty `programme_scope` means no programme access. Master admin is rejected from Programme PC teaching event CRUD.
- **Visibility:** Secretary-created events remain posting-owned and programme-neutral. PC-created events must not be visible to other programmes unless explicitly intended. Resident event discovery treats `created_for_programme_code IS NULL` as normal posting-owned visibility, and a set value as programme-owned visibility requiring resident `programme_code` match plus normal posting/date and persisted-source checks.
- **Options source:** The pre-Phase-F legacy catalogue option path is historical. Current scheduled-event creation selects one explicit in-scope Teaching Name or Global Session Type ID; Resident/Non-NHG runtime discovery does not consult the catalogue.
- **Validation:** Public holiday hard-block applies. Edit/delete is blocked if any native or external attendance exists. `created_by_role` is source-role metadata only and uses `programme_pc` for PC-created rows.
- **Implementation status:** Implemented with `teaching_events.created_for_programme_code`, Programme PC CRUD endpoints, secretary shared schedule visibility, and resident programme-owned visibility filtering.
- **Implemented reference:** `schema.md` table `teaching_events`; `api.md` section `4B` Programme PC Teaching Event CRUD endpoints; `business-logic.md` PC-created teaching event visibility.
- **Reference file and section:** `schema.md` § `teaching_events`; `api.md` § `4B` Programme PC Teaching Event CRUD endpoints; `business-logic.md` § PC-created teaching event visibility
- **Do not change without PM/stakeholder approval:** Yes
---

#### Decision: Programme PC NHG Resident Attendance is native-only, read-only, and pre-compliance
- **Status:** ✅ Confirmed and implemented
- **Decision:** Programme PCs have an `NHG Resident Attendance` overview and a dedicated personal attendance-history page for each resident. `View attendance` navigates to the resident UUID route; it does not open a drawer and never uses MCR as an authorization or route identifier.
- **Authorization:** Backend authorization is authoritative. A Programme PC may see only residents whose `residents.programme_code` belongs to the authenticated `users.programme_scope`. Null or empty scope returns `403`; an unknown or out-of-scope resident UUID returns the same controlled `404`. Explicit Master Admin keeps read access in line with shared admin attendance-read routes; Master authority is never inferred from null scope.
- **Data boundary:** The feature reads native `residents`, `resident_postings`, `attendance_records`, `teaching_events`, and display reference tables only. It does not query or combine `external_residents`, `external_resident_postings`, or `external_attendance_records`. Non-NHG Attendance remains a distinct page and workflow.
- **History contract:** Attendance source is centrally classified as `Department Secretary`, `Programme PC`, or `Ad-hoc`, with `is_adhoc` first and `created_for_programme_code` authoritative for scheduled PC ownership. Persisted `submitted`, `flagged`, and `removed` rows may be displayed, but none can be edited, deleted, removed, or have status changed from this feature.
- **Current posting:** Display uses the existing server-side native current-posting resolution contract and returns a controlled null state rendered as `No current posting`; client state, attendance recency, teaching-event posting, and programme mappings are not alternative resolvers.
- **Explicit exclusion:** This phase does not implement compliance dashboards or placeholders for them, monthly targets, session-type target progress, percentages, traffic lights, shortages, surplus, reallocation, FormF1 denominator work, snapshots, or clawback. Those requirements remain deferred pending separate confirmation.
- **Schema impact:** No migration is required; the feature is a read-only projection over existing native tables and ownership/status fields.
- **Routes:** Backend `GET /admin/resident-attendance` and `GET /admin/resident-attendance/{resident_id}`; frontend `/pc/resident-attendance` and `/pc/residents/{resident_id}/attendance`.
- **Reference file and section:** `api.md` § Programme PC NHG Resident Attendance (read-only); `ui-design-spec.md` S17–S18; `responsive-ui-plan.md` route inventory.
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Master Admin audited force deletion for Secretary/PC scheduled events
- **Status:** ✅ Confirmed and implemented
- **Decision:** Rename the user-facing Master Admin review surface to **Secretary/PC Events** while retaining `/admin/secretary-events`. The list includes Secretary and Programme PC scheduled events, classifying Programme PC ownership from `created_for_programme_code`; NHG and Non-NHG Resident ad-hoc events are excluded.
- **Authorization:** Force deletion is available only when the authenticated actor has `role = admin` and persisted/verified `admin_level = master`. Null or empty `programme_scope` never implies Master Admin. Programme PCs, Secretaries, residents, and Non-NHG Residents are forbidden.
- **Destructive semantics:** After an explicit reason and exact `DELETE` confirmation, lock one eligible event occurrence; capture its bounded audit snapshot and linked counts; verify those counts still match the displayed confirmation impact; explicitly delete native `attendance_records`, Non-NHG `external_attendance_records`, and the event; write `admin.teaching_event.force_delete`; then commit once. A changed impact returns `409` before deletion, and any transactional failure rolls back all four changes. No cascade or schema migration is introduced, and series siblings remain intact.
- **Guardrail:** Ordinary Secretary and Programme PC delete-with-attendance `409` behaviour remains unchanged. The override is a dedicated Master Admin action and is not exposed through either role's mutation endpoint.
- **Consequences for codebase:** The Master Admin list/detail expose source ownership and split attendance counts; the confirmation UI states the irreversible impact; successful deletion attempts to invalidate event, attendance, resident-view, admin-list, and report caches, and logs any post-commit invalidation failure without misreporting the committed deletion; future live/JIT reads reflect the removal.
- **Reference file and section:** `api.md` § Master Admin Secretary/PC Events; `schema.md` § `teaching_events`; `business-logic.md` § Master Admin scheduled-event force-delete override
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Secretary-created event visibility capability flag
- **Status:** ✅ Confirmed implementation direction
- **Decision:** Use `posting_codes.supports_secretary_events BOOLEAN DEFAULT false` as the scalable capability flag for secretary-created event visibility.
- **Current pilot:** TTSH pilot postings can be seeded/configured with `supports_secretary_events = true`, so residents posted there see secretary-created events plus ad-hoc submission.
- **Future onboarding:** Future hospitals such as KTPH can be enabled by setting the same flag on their posting codes. This avoids service-code hardcoding and makes onboarding a data/config change.
- **Behaviour:**
  - `supports_secretary_events = true` → native NHG Residents at that posting may see secretary-created event lists and may also submit ad-hoc teaching.
  - `supports_secretary_events = false` → no secretary-created event list is expected for native NHG Residents; ad-hoc submission remains available. Non-NHG scheduled-event visibility is separately governed by exact date-matched posting and is not narrowed by this flag.
- **Applicability:** Applies to both native NHG residents and external NUH/SingHealth residents.
- **Rejected approach:** Hardcoding `posting_codes.institution = 'TTSH'` in service logic.
- **Reference file and section:** `schema.md` § `posting_codes`; `business-logic.md` § BL-12; `api.md` § Resident/Non-NHG Resident Endpoints
- **Do not change without PM/stakeholder approval:** Yes
---

#### Decision: Master admin is an explicit authorization concept (not inferred from NULL scope)
- **Status:** ✅ Confirmed authorization direction
- **Decision:** Master admin is explicit and separate from programme-scoped PC authorization.
- **Master admin scope:** Can upload RDB, Public Holidays / AY Dates, FormF1, and TTF for any programme; can read global/admin-wide config and upload logs where appropriate.
- **Programme PC scope:** Can upload TTF only for programmes in `programme_scope`; can view/manage only programme-scoped data for assigned programmes.
- **Invariant preserved:** `programme_scope = NULL` means no access, not all access.
- **Explicit non-inference rule:** Master admin must not be inferred from `programme_scope IS NULL`.
- **Pending implementation/design detail:** Exact schema/auth mechanism is open, e.g.:
  - `users.admin_level = 'master' | 'programme'`
  - `users.is_master_admin = true/false`
  - explicit equivalent with same semantics
- **Pending endpoint authorization matrix detail:** Exact split of master-admin-only vs programme-PC-accessible upload/config endpoints remains to be finalized.
- **Reference file and section:** `AGENTS.md` security and scope rules (`programme_scope` semantics)
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Bulk TTF upload is deferred
- **Status:** ✅ Confirmed deferred
- **Decision:** Bulk TTF upload (all departments/programmes in one operation) is deferred.
- **Current safe workflow:**
  - master admin uploads TTF one programme at a time through existing TTF endpoint
  - programme PC uploads only for programmes in their scoped programmes
- **Parser selection invariant:** Endpoint/upload slot determines parser selection. No filename-based programme detection. Filename remains audit-only unless future explicit bulk design changes it.
- **Phase guardrail:** No bulk-upload implementation in current phase/document update.
- **Pending implementation/design details:**
  - input format choice (zip of files vs multi-file upload vs one workbook with many programme sheets)
  - programme mapping approach (manual per file vs manifest-based vs other explicit mapping)
  - transaction behavior (partial success allowed vs full atomic batch)
- **Reference file and section:** `api.md` upload slot behavior; `AGENTS.md` parser and upload rules
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Latest uploaded TTF export/email is deferred to end-of-roadmap
- **Status:** ✅ Confirmed deferred
- **Decision:** "Latest uploaded TTF" means latest original uploaded TTF workbook regardless of uploader type (programme PC or master admin). Feature is master-admin-triggered and deferred until end-of-roadmap after core workflows stabilize.
- **Preferred staged delivery plan (future):**
  1. export/download latest uploaded TTF
  2. email latest uploaded TTF after email destination/provider/config is finalized
- **Explicitly not now:** no email sending implementation, no file storage implementation, no UI button, and no backend endpoint in this phase unless later explicitly requested.
- **Pending implementation/design details:**
  - ETA corporate destination mailbox/contact is undecided
  - email provider undecided (Microsoft Graph/Outlook, SMTP, SendGrid, or other)
  - file storage decision required because current upload flow may persist parsed data + metadata but not original workbook
  - retention policy for original uploaded TTF files
  - export semantics: exact original workbook vs regenerated workbook from parsed rows
- **Reference file and section:** upload audit and roadmap sequencing context
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Surplus resets at reporting period boundary
- **Status:** ✅ Confirmed
- **Decision:** `surplus_ledger` values reset to zero at each `reporting_periods` boundary. Surplus does NOT carry across H1/H2.
- **Reasoning:** Each 6-month reporting period is an independent compliance window. Carrying surplus across periods would mask chronic under-attendance.
- **Alternatives considered:** Rolling surplus across periods — rejected by PM.
- **Derived-state lifecycle:** The ledger is not carry-in attendance. Within a period, recompute/replace `max(cumulative raw eligible attendance - cumulative target_100, 0)` from all relevant phases; never increment or add it to attendance. Hibernate when no active phase remains and unhibernate/recompute on return. New period starts at zero, while closed-period evidence may remain stored.
- **Reference file and section:** `business-logic.md` § BL-4; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Recurrence editing — all three granularities
- **Status:** ✅ Confirmed
- **Decision:** Secretary can edit/delete recurring events with three scopes: "this event only", "this and all following", "all events in the series".
- **Reasoning:** Matches standard calendar application UX. Secretaries need flexibility to cancel single occurrences, cancel remainder of a series, or cancel the entire series.
- **Alternatives considered:** (1) Single-event-only editing — rejected, too restrictive. (2) All-or-nothing — rejected, too destructive.
- **Consequences for codebase:** `DELETE /secretary/teaching-events/series/{series_id}` accepts `scope` query param (`single`, `following`, `all`) + `event_id`. Cannot delete occurrences with attendance records (409).
- **Reference file and section:** `api.md` § Secretary Endpoints; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Tag-based reallocation scope — tag-group-only, alphabetical sort
- **Status:** ✅ Confirmed
- **Decision:** Reallocation operates on raw achieved session counts before final capping, within one physical posting, R-year context, and tag prefix. Sort alphabetically (A1→A2→A3); earlier tags donate only to later tags. Donor supply is raw achieved above that type's 70% target, recipient demand is only to reach its 70% target, and supply is decremented after each one-for-one transfer. Duration is never a multiplier and posting groups do not permit cross-posting transfer.
- **Reasoning:** Matches the R script's `order()` on the Tag column. By convention, PCs assign A1 = longest duration, A2 = shorter. Alphabetical sort preserves this convention without requiring a separate sort field.
- **Alternatives considered:** (1) Duration-based sort — rejected, doesn't match R script behaviour. (2) Cross-tag flow — rejected by PM. (3) Weighted transfers based on duration ratio — rejected, adds complexity with no stakeholder request.
- **Specification consequence:** After all transfers, cap every session type/R-year context at its own `target_100`; final capped values feed posting compliance. The TTF validator may warn when tag order does not align with duration descending, but duration does not drive transfer. No claim of implementation is made here.
- **Reference file and section:** `business-logic.md` § BL-3; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Session counts, not hours — compliance unit
- **Status:** ✅ Confirmed
- **Decision:** Compliance is measured in number of sessions attended. Duration is never a multiplier. 1 session = 1 session regardless of 0.5h or 3h.
- **Reasoning:** Matches the legacy R script behavior and the regulatory framework. Duration is embedded in session type names for display/timing metadata and validation only; alphabetical tag labels—not hours—define reallocation direction.
- **Alternatives considered:** Duration-weighted compliance — never proposed by stakeholders.
- **Consequences for codebase:** No multiplication by `duration_hours` anywhere in the planned compliance path. Duration stored on `session_types`, catalogue options, and `teaching_events` is display/timing metadata and must not break ties in compliance resolution.
- **Reference file and section:** `AGENTS.md` § Key Architectural Rules; `business-logic.md` § BL-1
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Reallocation is read-time only — never written to surplus_ledger
- **Status:** ✅ Confirmed
- **Decision:** `reallocate_by_tag()` is a read-time computation over raw eligible attendance counts before final caps. Reallocated values are never written to or read from `surplus_ledger` as transfer balances.
- **Reasoning:** Writing reallocated values would corrupt the pre-reallocation audit trail and cause double-counting on the next compliance read. Surplus must always reflect the raw, pre-reallocation state.
- **Alternatives considered:** Materialising reallocated values — rejected due to audit trail corruption risk.
- **Specification consequence:** `surplus_ledger.surplus` stores independently recomputed pre-tag derived audit state. It is not added to raw attendance and is not directly consumed by the in-memory transfer calculation.
- **Reference file and section:** `business-logic.md` § BL-3, BL-4
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: TTF upload — logical scope replacement, warn not 422 on existing attendance
- **Status:** ✅ Confirmed
- **Decision:** TTF re-upload always logically replaces the `(reporting_period_id, programme_code)` target scope, regardless of existing attendance. Physical persistence reconciles by stable target identity: matching targets retain UUIDs, mutable fields update, and only stale targets are removed. Mappings for removed targets remain as pending rows. No 422 attendance guard.
- **Reasoning:** PCs need to correct TTF errors mid-period. Blocking re-upload forces manual DB intervention. Current event/attendance runtime preserves its persisted source evidence and does not use the retired catalogue path.
- **Alternatives considered:** 422 guard blocking re-upload when attendance exists — rejected, too restrictive for PC workflow.
- **Consequences for codebase:** `ttf_parser.py` reconciles `teaching_targets` within scope and replaces programme-wide `posting_groups`. It does not regenerate a catalogue or emit catalogue-specific orphan warnings.
- **Reference file and section:** `api.md` § POST `/admin/upload/ttf`; `parsing.md` § TTF Parser Upload Behaviour
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: RDB re-upload — full-period snapshot replace
- **Status:** ✅ Confirmed
- **Decision:** On RDB re-upload, existing `resident_postings` rows for the selected `reporting_period_id` are deleted and re-inserted as a full replacement snapshot for that period.
- **Reasoning:** RDB uploads are complete period snapshots, not partial uploads. Full replace prevents stale residents/postings from lingering after correction uploads.
- **Alternatives considered:** Upsert-only approach — rejected, harder to handle deleted postings.
- **Consequences for codebase:** `rdb_parser.py` runs `DELETE FROM resident_postings WHERE reporting_period_id = :period_id` only after successful parse/validation, then inserts the new parsed rows in the same transaction.
- **Reference file and section:** `parsing.md` § RDB Parser Processing Order; `schema.md` § `resident_postings`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FormF1 re-upload — full replace, allowed any time
- **Status:** ✅ Confirmed
- **Decision:** FormF1 re-upload is a full replace per `reporting_period_id` scope. Allowed at any time (e.g. to update for unforeseen LOAs like maternity).
- **Reasoning:** Unforeseen LOAs can change active/inactive status after the initial upload. PCs need the ability to re-upload corrected FormF1 at any point in the period.
- **Alternatives considered:** Incremental updates — rejected, full replace is simpler and less error-prone.
- **Consequences for codebase:** `formf1_parser.py` runs `DELETE FROM form_f1_records WHERE reporting_period_id = :period_id` before insert.
- **Reference file and section:** `parsing.md` § FormF1 Parser; `schema.md` § `form_f1_records`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Posting codes from table only — never derived by regex
- **Status:** ✅ Confirmed
- **Decision:** `posting_codes` table is the source of truth for all posting codes. Codes are never derived by string pattern, regex, or institution+department concatenation.
- **Reasoning:** Real posting codes like `AICAIC`, `MOHHGTG1`, `NHGPlyNHGPly`, `RenCiCommHosp` break any uniform pattern. The `posting_codes` table note in `schema.md` explicitly states this.
- **Alternatives considered:** Regex derivation — rejected due to unpredictable code formats.
- **Consequences for codebase:** All code that needs a posting code queries `posting_codes`. No string construction or pattern matching.
- **Reference file and section:** `schema.md` § `posting_codes` table Important note
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Resident event visibility gated by RDB upload
- **Status:** ✅ Confirmed
- **Decision:** Residents only see teaching events after their posting schedule has been uploaded via RDB. No RDB upload = no visible events. Enforced by `resident_postings` lookup at request time.
- **Reasoning:** Without a posting schedule, the system cannot determine which events are relevant to the resident. Showing all events would be incorrect and confusing.
- **Alternatives considered:** None — this is a logical necessity.
- **Consequences for codebase:** `GET /resident/events` enumerates every effectively active period and returns an empty list with `reason: "posting_schedule_unavailable"` only when no eligible `resident_postings` context exists across those periods. A missing posting covering today does not suppress historical event-date eligibility.
- **Reference file and section:** `api.md` § GET `/resident/events` visibility gating
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Use resident_postings.r_year for compliance — not residents.r_year
- **Status:** ✅ Confirmed
- **Decision:** Compliance target lookups use `resident_postings.r_year` (per phase), not `residents.r_year` (display only). A resident may cross a residency year boundary mid-period.
- **Reasoning:** A resident might be R2 for the first 3 months and R3 for the last 3 months of a reporting period. Each phase must be matched against the correct teaching targets.
- **Alternatives considered:** None — `residents.r_year` is a convenience display field only.
- **Specification consequence:** Resolve each attendance to the phase covering its event date. Calculate target and cap separately for every physical-posting/session-type/R-year context, then sum. Do not merge raw attendance before capping or duplicate the posting-wide active-month total across R-year rows.
- **Reference file and section:** `business-logic.md` § BL-1, BL-6; `schema.md` § `residents` table
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: STP never uploaded — TTF is the compliance input
- **Status:** ✅ Confirmed
- **Decision:** STP is a planning document created by secretaries. It is never uploaded to the system; the PC manually converts it to a final A-J TTF before a Master Admin or in-scope Programme PC uploads it.
- **Reasoning:** No STP parser has been approved. The former A-K/Column K conversion detail is historical only and does not apply to the final format.
- **Alternatives considered:** STP upload with auto-conversion — rejected; no STP parser is authorized.
- **Consequences for codebase:** No `stp_parser.py`. No STP upload endpoint. TTF is the only teaching target upload path.
- **Reference file and section:** `AGENTS.md` § "No STP in the system"
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: teaching_events.session_type_id is display only
- **Status:** ✅ Confirmed
- **Decision:** `session_type_id` on `teaching_events` is legacy display/prototype data. It is NEVER used for Phase G Resident/Non-NHG source classification, event visibility, attendance eligibility, or ad-hoc classification. The Phase 6 compliance resolver remains deferred and must use persisted source identity plus a scoped mapping, not the event display text.
- **Reasoning:** A teaching event may serve residents from multiple programmes. Each programme may map the same `teaching_name` to a different session type. Storing a single session type would be wrong for cross-programme residents.
- **Alternatives considered:** Storing session type per attendance record — rejected because TTF re-uploads would make stored values stale.
- **Consequences for codebase:** No current compliance engine exists. A future implementation must not use `teaching_events.session_type_id` or `keyword = teaching_event.teaching_name` as its source classifier.
- **Reference file and section:** `AGENTS.md` § Key Architectural Rules; `business-logic.md` § BL-6; `schema.md` § `attendance_records`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FormF1 as final active/inactive source (TBD-7 resolved)
- **Status:** ✅ Confirmed and final
- **Decision:** FormF1 remains stored per calendar month, but the AY bucket `month_label` selects the one `form_f1_records.is_active` value that gates both numerator and denominator for the entire bucket. `Active`/`Extension` are true; inactive values exclude the whole bucket. Do not use an event's raw calendar month or split/prorate a bucket.
- **Reasoning:** This preserves FormF1 authority while aligning it deterministically to AY attendance/target bucketing. For example, a `Jul-26` bucket ending 3 August still uses July FormF1 on 3 August.
- **Alternatives considered:** RDB-derived active/inactive using ≥15 working calendar days rule — rejected for current architecture.
- **Specification consequence:** `formf1_parser.py` remains calendar-month persistence; compliance joins through `academic_month_boundaries.month_label`. The same status gates numerator and denominator.
- **Reference file and section:** `business-logic.md` § BL-1, BL-6, TBD-7 (closed)
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FormF1 parser persistence scope = MCR + monthly status + promotion_date only
- **Status:** ✅ Confirmed
- **Decision:** FormF1 parser uses only MCR, monthly Active/Inactive/Extension status columns, and promotion date/senior promotion date for persistence. MCR is the only resident identifier from FormF1.
- **Reasoning:** Resident identity, programme, r_year, and posting are authoritative from RDB-backed tables. Persisting non-authoritative FormF1 profile columns risks drift and silent overwrites.
- **Consequences for codebase:** FormF1 upload does not overwrite resident profile/programme/r_year/posting data. `form_f1_records.promotion_date` is stored for future use but is not consumed by compliance yet. Duplicate normalized MCR within a single FormF1 upload is a blocking `422` validation error because parser cannot safely choose between conflicting rows. Dynamic header detection is preferred so template row shifts do not require parser rewrites.
- **Reference file and section:** `parsing.md` § FormF1 Parser; `schema.md` § `form_f1_records`; `api.md` § POST `/admin/upload/form-f1`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: r_year configuration — supersedes former 22/6 and SS-remap entry
- **Status:** ✅ Confirmed; previous entry superseded
- **Decision:** 20 programmes with `r_year_required = false` use `r_year = 'ALL'`. Eight use actual R-year. SPORTSMED and PALLMED have `r_year_required = true`, `is_subspecialty = false`, and preserve R4, R5, and R6 in RDB, targets, and catalogue rows. No SS remapping applies.
- **Reasoning:** Most programmes do not differentiate teaching targets by residency year — all years share the same targets. The sentinel avoids duplicating target rows.
- **Alternatives considered:** NULL r_year — rejected because NULL complicates equality checks. Separate flag without sentinel — rejected, adds join complexity.
- **Specification consequence:** The sentinel matcher remains for the 20 programmes. SPORTSMED/PALLMED must never use `ALL` or SS1–SS3 in current parser/compliance behavior.
- **Reference file and section:** `business-logic.md` § BL-11; `schema.md` § `programmes` seed data; `parsing.md` § R Year Handling
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: explicit global-source exclusion priority
- **Status:** ✅ Confirmed
- **Decision:** Phase G treats `teaching_events.global_session_type_id` as the explicit global source identity and never classifies an event by matching its display text. The Phase 6 compliance exclusion implementation is deferred; when implemented, it must use persisted identity before any scoped mapping.
- **Reasoning:** Global session types (e.g. Department Meeting) should never count toward compliance regardless of a display snapshot or transitional parser configuration.
- **Alternatives considered:** Display-name matching — rejected because it can classify an unrelated event and reintroduce the legacy runtime dependency.
- **Consequences for codebase:** No current `compliance.py` exists. A future implementation must skip explicit global sources without text inference.
- **Reference file and section:** `business-logic.md` § BL-6 step 5; `schema.md` § `global_session_types`; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: ORTHO weekend mutation — read-time only
- **Status:** ✅ Confirmed
- **Decision:** Only the exact original ORTHO type `NHG Orthopaedic Surgery Residency Teaching [3h]` is eligible. Preserve raw rows, subtract two hours from its original end time, project to `National Didactics & Department Teaching [1h]`, and then test Saturday 08:30–10:30 against adjusted time. Sunday remains excluded and other ORTHO types are not mutated.
- **Reasoning:** Consistent with R script (batch post-processing). Preserves raw data for audit. If ORTHO changes policy, update the `weekend_exceptions` row — no data migration needed.
- **Alternatives considered:** (A) Write mutation at submission time — rejected, corrupts raw data. (B) Read-time mutation (chosen). Both options documented in `AGENTS.md`.
- **Specification consequence:** Mutation predicate and weekend-acceptance predicate are ordered and must not be collapsed into a programme-wide wildcard. This audit makes no code-implementation claim.
- **Reference file and section:** `business-logic.md` § BL-5 ORTHO weekend section; `schema.md` § `weekend_exceptions`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: posting_groups for compliance aggregation
- **Status:** ✅ Confirmed
- **Decision:** `posting_groups` table groups related posting codes for compliance aggregation. When a resident serves at multiple postings sharing the same `group_code`, `active_months` and `target_100` are summed across all group members. Each posting's own TTF `monthly_target` applies per phase.
- **Reasoning:** Some postings are sub-units of a larger department (e.g. `TTSHRespi` and `TTSHRespi(MICU)`). Compliance should be pooled, not calculated independently.
- **Alternatives considered:** Manual compliance override — rejected, error-prone. Merging posting codes — rejected, they are distinct sites with distinct event schedules.
- **Consequences for codebase:** `compliance.py` checks `posting_groups` for each `(posting_code, programme_code)`. If a group is found, fetches all members and sums `active_months` and `target_100`. `posting_groups` independent from `multi_posting_rules`.
- **Reference file and section:** `business-logic.md` § BL-1 Posting group aggregation; `schema.md` § `posting_groups`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FM uses standard compliance engine — no compliance_variant
- **Status:** ✅ Confirmed
- **Decision:** FM uses the same compliance engine as all other programmes. No `compliance_variant` column on `programmes`. No separate code path. Two FM-specific annotations only: (1) Department Teaching [5h] posting overridden to `NHGPlyNHGPly`; (2) FM Saturday exception **removed from confirmed list** — no seed row in `weekend_exceptions`.
- **Reasoning:** R script analysis (MATA Core Business Logic Audit) confirmed FM's separate Excel template was a layout difference only, not a calculation difference. The compliance logic is identical.
- **Alternatives considered:** `compliance_variant = 'fm'` column + `NotImplementedError` stub — implemented, then removed after R script audit confirmed no variant needed.
- **Consequences for codebase:** No FM-specific code path in `compliance.py`. Rule 1 (Department Teaching [5h]) is a simple if-check. Rule 2 (Saturday exception) is no longer applicable — FM is not in the confirmed `weekend_exceptions` seed data.
- **Reference file and section:** `business-logic.md` § BL-FM; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FM Saturday exception removed from confirmed list
- **Status:** ✅ Confirmed (Final)
- **Decision:** FM is NOT in the confirmed `weekend_exceptions` seed data. The FM Saturday 08:00–13:00 exception has been removed per PC update. No FM row should be seeded.
- **Reasoning:** PC confirmed removal. The original R script exception was outdated.
- **Alternatives considered:** Keeping the exception — rejected per PC update.
- **Consequences for codebase:** No FM row in `weekend_exceptions` seed data. FM Saturday sessions will trigger `compliance_warning` on submission. They are stored but do not count toward compliance.
- **Reference file and section:** `AGENTS.md` § Key Architectural Rules (removal note); `schema.md` § `weekend_exceptions` confirmed seeded rows (no FM row)
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Public holiday event creation hard-blocked (422)
- **Status:** ✅ Confirmed
- **Decision:** `POST /secretary/teaching-events` and `POST /resident/adhoc-teaching` validate event date against `public_holidays` table. Returns 422 if date matches. Recurring series occurrences on PH dates are skipped with warning.
- **Reasoning:** No teaching events should be created on public holidays. Hard block is simpler and more reliable than post-hoc exclusion.
- **Alternatives considered:** Soft warning + compliance exclusion — rejected, creates confusing events that can never count.
- **Consequences for codebase:** Both endpoints check `public_holidays` table before insert. Series materialisation skips PH dates. PH impact on compliance denominator is moot — no events created.
- **Reference file and section:** `business-logic.md` § BL-5; `api.md` § error responses
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: AY Dates in Academic Calendar / Public Holiday workbook are required for compliance month bucketing
- **Status:** ✅ Confirmed
- **Decision:** `POST /admin/upload/public-holidays` now parses both `Public Holidays` and `AY Dates` sheets. `AY Dates` is required to populate attendance month-bucketing boundaries in `academic_month_boundaries`. `Fr RMT` is ignored.
- **Decision details:**
  - Internal categories are fixed to `im_subspec` and `non_im_subspec`.
  - Category is resolved by **programme code**, not by display name.
  - Category does **not** depend on JR/SR wording, resident classification, or `r_year`.
  - SR/SRs wording in workbook headers is legacy/inconsistent detection text only and must not affect persistence.
  - IM Sub-Spec and Non-IM Sub-Spec categories apply to both JR and SR.
- **Confirmed programme-code mapping (all 28 seeded programmes):**
  - `im_subspec`: AIM, CARDIO, DERM, ENDO, GASTRO, GERI, ID, IM, MEDONCO, PALLMED, REHAB, RENAL, RESPI, RHEUM
  - `non_im_subspec`: ANAES, DR, EM, ENT, EYE, FM, GS, MICROB, ORTHO, PATH, PSY, SIG, SPORTSMED, URO
- **Consequences for codebase:** Compliance month bucketing resolves `resident.programme_code -> programmes.ay_date_category -> academic_month_boundaries(event_date BETWEEN start_date AND end_date)`. Header text is detection-only and not stored.
- **Reference file and section:** `schema.md` § `programmes`, `academic_month_boundaries`; `parsing.md` § Academic Calendar / Public Holiday File Parser; `business-logic.md` § BL-5A
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Multi-posting rules seeded in DB — no file upload
- **Status:** ✅ Confirmed
- **Decision:** The three rule types (`main_posting`, `combine`, `half_month`) are managed via admin CRUD UI. `Multiple postings per month.xlsx` is a seed/update source for the `multi_posting_rules` table, not a recurring upload slot.
- **Reasoning:** Multi-posting rules are stable configuration data, not per-period upload data. CRUD UI is simpler and allows immediate correction. The workbook provides initial/source-of-truth seed rows when configuration needs to be refreshed.
- **Alternatives considered:** Parsing rules from RDB file — rejected, rules are cross-programme and don't belong in a per-programme upload.
- **Consequences for codebase:** Admin CRUD endpoints for `multi_posting_rules`. `rdb_parser.py` looks up the table at parse time. No rule file parser.
- **Persistence semantics:** `main_posting` collapses to one configured existing main code; `combine` persists one configured canonical combined code with its own TTF rows and no component results; `half_month` persists both source codes with `active_months_weight = 0.5` and leaves TTF `monthly_target` unchanged. These outcomes must not be collapsed into one `main_posting_code` behavior.
- **Reference file and section:** `schema.md` § `multi_posting_rules`; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FM main-posting semantics and PC CRUD workflow
- **Status:** ✅ Confirmed
- **Decision:** PCs manage multi-posting rules through three logical Admin CRUD tabs: Main Posting, To Combine Posting, and Half Month Posting. For FM `main_posting` rules, `RDB Posting #1` is the recognised trigger list. Exact-one recognised posting in an FM multi-posting cell collapses to that row's `Main posting`; zero recognised postings collapse to the configured `Exclusion (Only for FM)`, usually `NHGPlyNHGPly`; two or more recognised postings must not infer and should persist independently with `unmatched_multi_posting` unless an explicit rule exists.
- **Reasoning:** PC clarified that FM exclusion is configured data, not a universal hardcoded fallback. Ambiguous cells with multiple recognised main postings need PC review rather than parser guessing.
- **Alternatives considered:** Hardcoding `NHGPlyNHGPly` globally, inferring the full rule set from AY25 warnings, or suppressing unmatched warnings. All rejected because they hide PC review points or encode unconfirmed business intent.
- **Consequences for codebase:** RDB parser applies explicit rules first, then FM trigger-list semantics. Seed/data migrations must be workbook-derived and idempotent. Non-FM unknown combinations still warn and persist independently.
- **Reference file and section:** `parsing.md` § RDB Parser multi-posting cells; `business-logic.md` § BL-8; `schema.md` § `multi_posting_rules`; `api.md` § Admin multi-posting rule endpoints
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Ad-hoc teaching submission uses a fixed server-owned record
- **Status:** ✅ Implemented locally in Phase G
- **Decision:** NHG Residents and Non-NHG Residents submit ad-hoc teachings through a date-first fixed-record flow. The backend derives one posting from the selected date and exposes only `Department/Programme Teaching [1h]` at duration `1.00`; clients cannot select a Teaching Name, mapping, target, arbitrary text name, or alternate attended department/programme.
- **NHG Resident flow:** `resident_postings` must yield exactly one active/LOA-working posting for the date. The optional supplied posting is only a confirmation of that value; a different value is rejected.
- **Non-NHG Resident flow:** `external_resident_postings` must yield exactly one date-matched schedule posting. The optional supplied posting is only a confirmation of that value; a different value is rejected. Non-NHG attendance remains recording/export-only.
- **Submission fields:** `POST /resident/adhoc-teaching` uses canonical
  `teaching_date`; compatibility-only `date` is accepted when it is the sole
  alias or equals `teaching_date`, while conflict or omission returns `422`. It
  creates a fixed `teaching_events` row (`is_adhoc = true`) and the matching typed attendance-family row in one transaction. `details_of_session` remains display/audit-only free text with no operational or compliance use.
- **Ad-hoc event flags:** Ad-hoc teaching records have `is_adhoc = true`, `cme_points_awarded = false`, `smc_event_code = null`, null `session_type_id`, fixed display snapshot, and exact one-hour end time.
- **Frontend helper copy:** `Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.`
- **Compliance attribution:** Any future countable NHG ad-hoc treatment remains under the derived assigned posting; Phase G does not consult or rewrite a mapped target.
- **Reasoning:** Residents may attend teachings not pre-created by secretaries, but classification must be server-owned and independent of the transitional catalogue.
- **Alternatives considered:** Secretary-only event creation — rejected, too restrictive for resident workflow. Client-selected text, Teaching Names, mappings, or targets — rejected because they would reintroduce a client-controlled or legacy-catalogue classification path.
- **Consequences for codebase:** Dedicated endpoint with PH validation, date-first posting derivation, fixed option/read-only posting, optional display/audit detail capture, weekend exception check, and one atomic event + attendance write.
- **Implementation status:** Implemented locally by revision `20260804_000034`.
- **Reference file and section:** `business-logic.md` § BL-9; `api.md` § POST `/resident/adhoc-teaching`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Superseded Non-NHG ad-hoc host-programme derivation from NHG posting
- **Status:** ❌ Superseded by Phase 5B forecast posting schedule requirement
- **Decision:** The older single-current-posting host-programme derivation is superseded. Non-NHG Resident event/ad-hoc derivation must use `external_resident_postings` by selected date once the forecast schedule is implemented, and attended department/programme selection must resolve to a real `posting_codes.code` through validated lookup/config.
- **No string-derived codes:** Do not concatenate institution and department strings, and do not infer RDB posting codes by regex. If selected institution/programme/department values map to multiple `posting_codes`, require explicit user selection. If no code matches, return an unavailable/invalid selection state.
- **Compliance guardrail:** Attended department selection does not make Non-NHG Residents part of native NHG compliance, surplus, snapshots, clawback, or native reports.
- **Implementation status:** Superseded requirement; keep this entry only as historical audit context.
- **Reference file and section:** `schema.md` § `external_residents`; `api.md` § Non-NHG Resident Endpoints; `business-logic.md` § BL-12
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision A: Non-NHG Resident forecast posting schedule (Phase 5B)
- **Status:** ✅ Confirmed Phase 5B requirement
- **Decision:** Replace the single registration field "current NHG posting" with a repeatable "Upcoming NHG postings" section.
- **Schedule row fields:** Each row captures `start_date`, `end_date`, `programme_code` displayed as code plus full programme name, and an institution supplied by the backend registration-options response. The backend resolves the canonical posting code from `programme_institution_posting_map`; the client does not submit it. Current configuration exposes TTSH with 24 active Non-NHG registration choices; future institutions remain configuration-driven.
- **Date ranges:** Ranges may cross calendar months, for example `8 Jan` to `7 Feb`.
- **UI direction:** Use a multi-row "Add posting row" interaction.
- **Storage:** Persist the validated `programme_code` and backend-resolved `posting_code` together on each date-bounded `external_resident_postings` row. Programme belongs to the schedule row because a Non-NHG Resident may rotate through different programmes; do not add one global programme to `external_residents`. `external_residents.current_nhg_posting_code` may remain as a current/cache/backward-compatibility pointer if implementation needs it.
- **Write paths:** Initial registration, schedule replacement, and the current-posting compatibility route must all preserve the validated programme with its resolved posting.
- **Legacy provenance:** Keep the schedule `programme_code` nullable for unresolved legacy rows. Backfill only when authoritative mapping data yields exactly one programme, for example `TTSHGerMed -> GERI`; leave shared postings such as `TTSHGenMed` (AIM/IM) and `TTSHGenSrg` (GS/SIG) null. Never pick the first match. A null legacy programme grants no Programme PC-event visibility.
- **Authorization-sensitive derivation:** Event/ad-hoc derivation must use the date-matching `external_resident_postings` row rather than token claims or the current/cache pointer. Every normal scheduled Secretary or Programme PC event at the exact schedule posting is eligible; PC programme ownership and Secretary capability do not narrow Non-NHG visibility. Listing and attendance submission use the same exact-posting rule.
- **No inference:** Do not infer schedule or event programme ownership from posting prefixes, institution names, teaching targets, teaching-name catalogue rows, `programmes.native_teaching_posting_code`, fuzzy matching, or the first mapping row.
- **Range validation:** Rows for the same Non-NHG Resident must not overlap. Gaps are allowed, but event/ad-hoc options for a date in a gap return unavailable/no posting for selected date.
- **Identity and compliance:** Global MCR uniqueness still applies. Non-NHG attendance remains export-only and excluded from NHG compliance, clawback, numerator, denominator, surplus, snapshots, and native reports.
- **Posting-code resolution:** Do not concatenate strings or search metadata to create/choose RDB posting codes. Require one exact active `programme_institution_posting_map` row; pending, inactive, missing, or malformed configuration returns a controlled unavailable state.
- **Reference file and section:** `schema.md` § `external_resident_postings`; `api.md` § Non-NHG Resident Endpoints; `business-logic.md` § BL-12
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision B: Native NHG Resident event visibility sources (Phase 5B)
- **Status:** ✅ Confirmed Phase 5B requirement
- **Decision:** NHG Resident event discovery has three allowed scheduled-event sources: assigned/current posting secretary events, native programme TTSH department secretary events, and native programme PC-created events.
- **Assigned posting secretary events:** Derived from `resident_postings` covering each scheduled event date. Secretary-created events at that `posting_code` are visible subject to normal date, persisted-source, and reporting-period checks. Scheduled discovery automatically combines all effectively active periods; residents do not select a reporting period.
- **Native programme TTSH department secretary events:** Derived from an explicit native-programme-to-TTSH-posting mapping, for example `GRM -> TTSHGerMed`, `REHAB -> TTSH Rehab posting code`, and `DR -> TTSH Diagnostic Radiology posting code`. Do not infer this mapping by string manipulation. Preferred implementation is explicit config/mapping such as `programmes.native_teaching_posting_code` or a `programme_teaching_posting_map` table.
- **Native programme PC-created events:** `teaching_events.created_for_programme_code = resident.programme_code`. PC-created events are NHG/programme-owned, not TTSH site-owned.
- **Deduplication:** Deduplicate event rows by `teaching_events.id` when an event qualifies through more than one source.
- **Source-evidence rule:** An explicit Teaching Name source must match the event-date reporting period and native programme exactly; a duplicate display name in another programme must not fan out. An explicit global source is global-first. A both-null legacy event uses deterministic persisted evidence only and is never classified from text, catalogue, targets, or Column K.
- **Negative rules:** Do not show PC-created events for non-native programmes. Do not show secretary-created events from arbitrary TTSH departments unless they are either the resident's assigned/current posting or the resident's native programme department. No RDB upload or no `resident_postings` still means no assigned-posting visibility for NHG Residents.
- **Scenario A:** Native GRM Resident John is posted to TTSH Geriatric Medicine. John sees TTSH GRM Department Secretary events because he is posted there and GRM PC events because GRM is his native programme. The TTSH GRM secretary source is not duplicated when it is both assigned posting and native programme department.
- **Scenario B:** Native GRM Resident John is posted to TTSH Rehab. John sees TTSH Rehab Department Secretary events because he is posted there, TTSH GRM Department Secretary events because GRM is his native programme department, and GRM PC events because GRM is his native programme.
- **Scenario C:** Native Rehab Resident Mary is posted to TTSH GRM. Mary sees TTSH GRM Department Secretary events because she is posted there, TTSH Rehab Department Secretary events because Rehab is her native programme department, and Rehab PC events because Rehab is her native programme.
- **Compliance attribution:** Visibility source is not compliance identity. Phase G preserves raw event and attendance evidence and does not consult mappings or targets; a future compliance calculation remains separately governed.
- **Reference file and section:** `api.md` § GET `/resident/events`; `business-logic.md` resident event visibility; `schema.md` § `programmes` / native teaching posting mapping
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision C: Fixed ad-hoc teaching flow and attribution (Phase G)
- **Status:** ✅ Implemented locally
- **Decision:** Ad-hoc teaching is date-first and fixed to `Department/Programme Teaching [1h]` at one hour under the assigned/date-derived posting. There is no attended TTSH department/programme or teaching/session dropdown.
- **Flow:** The backend derives the sole posting from `resident_postings` for NHG Residents or `external_resident_postings` for Non-NHG Residents. It returns a singleton fixed option and accepts only that optional posting confirmation. `details_of_session` remains display/audit-only if provided.
- **No client classification:** The request contains no teaching name and cannot select a Teaching Name, target mapping, session type, catalogue keyword, `details_of_training`, or Column K data.
- **NHG compliance attribution:** Any future countable NHG ad-hoc treatment is under the assigned posting for the selected date. Phase G does not resolve a tracked target, map a session type, or return target-based unavailability.
- **Non-NHG treatment:** Attendance writes `external_attendance_records`; no NHG compliance attribution, surplus, or clawback applies. The server derives the schedule posting without client alternative selection.
- **Supersedes:** This supersedes the historical catalogue-backed attended-department dropdown interpretation.
- **Reference file and section:** `api.md` § GET `/resident/adhoc-teaching-options` and POST `/resident/adhoc-teaching`; `business-logic.md` § BL-9
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Weekend submission — stored + compliance_warning
- **Status:** ✅ Confirmed
- **Decision:** When a resident submits attendance for a weekend session with no matching `weekend_exceptions` rule, the session is stored but the response includes a `compliance_warning` field informing the resident it won't count toward PTT compliance.
- **Reasoning:** Option B chosen. Rejecting would prevent audit trail. Warning gives the resident transparency.
- **Alternatives considered:** (A) Hard reject — rejected, no audit trail. (B) Store + warn (chosen). (C) Store silently — rejected, resident would be surprised.
- **Consequences for codebase:** `POST /resident/attendance` response includes `compliance_warning` when applicable. Weekend check runs per-event in the submission batch.
- **Reference file and section:** `business-logic.md` § BL-5 Weekend submission warning
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Clawback tab/contract — deferred (supersedes implementation-ready wording)
- **Status:** DEFERRED
- **Decision:** A future clawback tab/route may remain a roadmap placeholder, but no row-generation, suppression, response, financial, or final-close contract is implementation-ready. Earlier statements that fixed Extension/R7 rows or generation behavior are superseded.
- **Boundary:** Ordinary compliance uses the unrounded percentage and is specification-ready independently. Clawback rates/effective dating, funding R-year, classifications, suppression granularity/precedence, grouped identity, billing, missing rates, rounding, and final-close transaction/rerun/idempotency all await confirmation.
- **Consequences for codebase:** Do not implement or infer clawback from this audit record or legacy scripts. Operational period activate/deactivate continues to generate no clawback state.
- **Reference file and section:** `business-logic.md` § BL-10; `api.md` § GET `/admin/reports/clawback`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Secretary provisioning — TTSH-only at launch
- **Status:** ✅ Confirmed
- **Decision:** At launch, one secretary account per TTSH posting code. Architecture supports other institutions without schema change — just provision new accounts scoped to their posting codes.
- **Reasoning:** TTSH is the primary institution at launch. Architecture is flexible for future expansion.
- **Alternatives considered:** None — straightforward provisioning decision.
- **Consequences for codebase:** `users` table with `posting_code` FK. No institutional hierarchy table needed.
- **Reference file and section:** `AGENTS.md` confirmed decisions; `schema.md` § `users`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Hard legacy cutover at period boundary
- **Status:** ✅ Confirmed
- **Decision:** FormSG and Google Forms submission channels are closed at a confirmed cutover date aligning with a period boundary. In-flight submissions processed one final time through legacy R scripts. After cutover, all attendance flows through this system only. No hybrid operation.
- **Reasoning:** Hybrid operation would require maintaining two compliance engines simultaneously, doubling complexity and creating reconciliation problems.
- **Alternatives considered:** Gradual migration with dual operation — rejected due to complexity.
- **Consequences for codebase:** No FormSG import endpoints. No Google Forms integration. No dual-mode compliance.
- **Reference file and section:** `AGENTS.md` § Key Architectural Rules
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FastAPI + SQLAlchemy async for backend
- **Status:** ✅ Confirmed [Assumed — standard choice]
- **Decision:** FastAPI with SQLAlchemy 2.0 async ORM and Alembic migrations.
- **Reasoning:** [Not explicitly documented — standard choice for async Python web APIs with ORM support.]
- **Alternatives considered:** [Not documented.]
- **Consequences for codebase:** All database operations use async session. Models defined with SQLAlchemy 2.0 declarative style.
- **Reference file and section:** `AGENTS.md` § Tech Stack
- **Do not change without PM/stakeholder approval:** No (tech choice, not business rule)

---

#### Decision: React/Vite/TypeScript for frontend
- **Status:** ✅ Confirmed [Assumed — standard choice]
- **Decision:** React SPA with Vite build tool and TypeScript.
- **Reasoning:** [Not explicitly documented — standard choice for modern SPAs.]
- **Alternatives considered:** [Not documented.]
- **Consequences for codebase:** TypeScript types in `src/types/`. Tailwind CSS core utility classes only.
- **Reference file and section:** `AGENTS.md` § Tech Stack
- **Do not change without PM/stakeholder approval:** No (tech choice, not business rule)

---

#### Decision: PostgreSQL → Supabase hosting
- **Status:** ✅ Confirmed [Assumed — organisation preference]
- **Decision:** PostgreSQL for local dev; Supabase-hosted PostgreSQL for production.
- **Reasoning:** [Not explicitly documented — likely organisation infrastructure preference.]
- **Alternatives considered:** [Not documented.]
- **Consequences for codebase:** Supabase staff password authentication is backend-mediated and wrapped in opaque MATA application sessions. H-E locally implements the restricted runtime/auth-helper role architecture and full application-table RLS. Service-role credentials remain server-only and are not the normal application runtime.
- **Reference file and section:** `AGENTS.md` § Tech Stack
- **Do not change without PM/stakeholder approval:** No (infra choice, not business rule)

---

#### Decision: Auth stub Phase 1; Supabase Auth Phase 2
- **Status:** Confirmed historical sequencing; production transport superseded by H-D
- **Decision:** Local/demo may use stub middleware. In production, Supabase remains the staff credential verifier, while MATA owns the browser application session, cookie/CSRF transport, subject reload, and generation checks. H-D proved that production requires more than a middleware-only swap.
- **Reasoning:** Allows rapid development without auth infrastructure. The header-based stub is simple to swap.
- **Alternatives considered:** Full auth from day 1 — rejected, slows initial development.
- **Consequences for codebase:** Synthetic `X-User-*` headers remain local/demo-only. Production rejects them as identity sources and uses `app_sessions` plus current database-owned role/scope.
- **Reference file and section:** `AGENTS.md` § Auth Stub; `api.md` § Authentication Model
- **Do not change without PM/stakeholder approval:** Yes (for Phase 2 timing)

---

#### Decision: Residents authenticate with MCR only — no password
- **Status:** ✅ Confirmed
- **Decision:** NHG Residents and already-registered Non-NHG Residents authenticate through one shared MCR field. No password in Phase 1. First-time Non-NHG registration remains a separate action.
- **Reasoning:** Residents are medical professionals with controlled MCR numbers. The system tracks attendance, not patient data. Low-friction login maximises adoption.
- **Alternatives considered:** Password-based auth — rejected for UX friction.
- **Consequences for codebase:** `POST /auth/login` with `role: 'resident'` is the neutral shared resident request. It checks `residents` and `external_residents` in one backend resolution, relies on global MCR uniqueness, validates the resolved row is active, returns the resolved `resident | external_resident` role, and rejects cross-table duplicates without issuing a token. The frontend makes exactly one request and never probes the tables sequentially.
- **Assurance boundary:** MCR-only remains the implemented and approved resident credential path. This decision is not evidence that resident production authentication assurance is sufficient, and H-D does not invent an unapproved factor.

- **Product-debt status:** Resident identity assurance remains separately
  governed. Do not invent a second factor or claim workflow outside an approved
  product scope.
- **Reference file and section:** `api.md` § POST `/auth/login`; `AGENTS.md` § Security Rules
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Duration embedded in session type name [Xh]
- **Status:** ✅ Confirmed
- **Decision:** Duration stays embedded in the session type name as `[Xh]` (e.g. `Department/Programme Teaching [1h]`). No separate TTF duration column. Secretary picks `start_time` only; `end_time` server-computed.
- **Reasoning:** Matches the TTF file format. Adding a separate column would require changing the PC's workflow.
- **Alternatives considered:** Separate duration column in TTF — rejected, would change PC workflow.
- **Consequences for codebase:** `parse_session_type()` extracts duration via regex `\[(\d+(?:\.\d+)?)h\]`. `end_time = start_time + timedelta(hours=duration_hours)`. `end_time` is never a request field.
- **Reference file and section:** `parsing.md` § TTF Parser Duration Extraction; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Non-tracked target rows retained; compliance treatment deferred
- **Status:** ✅ Confirmed
- **Decision:** TTF rows with `Tracked? = "No"` remain target semantics only. Phase G event visibility and attendance do not consult target configuration; the future compliance treatment remains a compliance-only concern.
- **Reasoning:** The final parser retains the target row while runtime authorization remains intentionally independent of target configuration.
- **Alternatives considered:** Creating Teaching Names or mappings from the row — rejected because workbook text is not an authority source.
- **Consequences for codebase:** `ttf_parser.py` persists `is_tracked = false` without seeding a catalogue, Teaching Name, or mapping. No current runtime visibility or compliance engine reads it for Phase G authorization.
- **Reference file and section:** `AGENTS.md` confirmed decisions; `parsing.md` § TTF Parser
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: posting_groups independent from multi_posting_rules
- **Status:** ✅ Confirmed
- **Decision:** `posting_groups` governs how compliance is aggregated across separate postings. `multi_posting_rules` governs how RDB cells are parsed into `resident_postings` rows. They are independent mechanisms.
- **Reasoning:** A resident may have two clean separate `resident_postings` rows (no multi-posting rule needed) but still have compliance pooled via `posting_groups`.
- **Alternatives considered:** Merging the two mechanisms — rejected, they serve different purposes at different stages.
- **Consequences for codebase:** `rdb_parser.py` uses `multi_posting_rules`. `compliance.py` uses `posting_groups`. Neither references the other.
- **Reference file and section:** `parsing.md` § Multi-Posting Cell Variant relationship note; `schema.md` § `posting_groups`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Upload audit logging via upload_logs
- **Status:** ✅ Confirmed
- **Decision:** Every RDB, TTF, FormF1, and PH upload writes a row to `upload_logs` with full JSONB summary.
- **Reasoning:** Audit trail for all data changes. Enables troubleshooting of parse errors.
- **Alternatives considered:** None — standard audit practice.
- **Consequences for codebase:** All four upload endpoints write `upload_logs` row before returning response.
- **Reference file and section:** `schema.md` § `upload_logs`; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Data Revalidation service boundary
- **Status:** Confirmed for Phase 3H-B; Live Data mutation wiring added in Phase 3H-C; Config mutation wiring added in Phase 3H-D
- **Decision:** Use `Data Revalidation` as the shared system/user-facing concept for mutation impact assessment. The backend service boundary is `data_revalidation_service`.
- **Reasoning:** Admin/PC Live Data and Config mutations need a common impact summary without overloading read-only Refresh actions or introducing heavy recalculation into every endpoint.
- **Consequences for codebase:** Phase 3H-B defines the service contract and default outcomes: `no_op`, `warning_only`, `targeted_revalidation`, `future_compliance_impact`, and `manual_revalidation_required`. Phase 3H-C wires successful Admin Live Data correction mutations to the service and returns a `data_revalidation` impact summary in mutation responses and correction audit metadata. Phase 3H-D wires successful Admin/PC Config CRUD mutations, including reporting-period activate/deactivate and scheduled transition edits, to the service and returns the same impact summary in mutation responses and config audit metadata. Concrete warning updates, source-cell parsing, multi-posting re-resolution, resident posting regeneration, period snapshot generation, surplus hibernation, clawback generation, and compliance recalculation remain 3H-E/later work.
- **Naming guardrail:** Reserve `reparse` for low-level RDB source-cell parsing only. Use `Revalidate data` and `Data revalidation impact summary` for user-facing actions and summaries.
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: First-class upload warning issues
- **Status:** Confirmed for Phase 3H-E2
- **Decision:** Upload warnings derived from `upload_logs.summary` are persisted into durable `warning_issues` and `upload_warnings` records. `warning_issues` group repeated warnings by deterministic fingerprint; `upload_warnings` records each upload occurrence.
- **Reasoning:** PCs need a stable review queue that survives refreshes and repeat uploads without rewriting historical upload summaries.
- **Consequences for codebase:** Successful RDB, TTF, FormF1, and Academic Calendar / Public Holidays uploads derive warning issues after the upload log is written. Admin endpoints list issues, show occurrence details, and allow manual `resolve`, `dismiss`, or `supersede` actions with audit logging. Resolved/dismissed/superseded issues become `reappeared` if the same fingerprint appears again. RDB blank resident/month cells now emit low-priority `empty_posting_cell` warnings.
- **Boundary:** 3H-E2 does not mutate `upload_logs.summary`, reparse RDB source cells, re-resolve multi-posting rules, regenerate `resident_postings`, update warning source data automatically, calculate compliance, generate snapshots, hibernate surplus, or generate clawback rows.
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Reporting-period active/inactive operational status
- **Status:** ✅ Confirmed for 3H-D-FU
- **Decision:** Reporting periods use stored status values `active` and `inactive`. `activate_on` and `deactivate_on` are optional scheduled transition dates resolved at read time, without mutating the row. `open` and `closed` are legacy values and are migrated/rejected.
- **Reasoning:** PCs need to control when a period is visible for live resident workflows without accidentally freezing compliance history or triggering finance flows.
- **Alternatives considered:** Reusing final close/freeze concepts for operational visibility — rejected because final close/freeze implies snapshots, surplus hibernation, and clawback generation.
- **Consequences for codebase:** Current `PUT /admin/reporting-periods/{id}/activate` and `/deactivate` routes only update operational status and return Data Revalidation impact summaries. They do not generate `period_snapshots`, hibernate surplus, generate `clawback_records`, or run compliance calculation. Final close/freeze remains future work.
- **Reference file and section:** `schema.md` § `reporting_periods`; `api.md` § Reporting-period effective status
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Security — server-side enforcement and Phase 5B-H-E full RLS
- **Status:** Confirmed; H-D transport/grant hardening and H-E RLS are locally implemented, deployed verification pending
- **Decision:** All security checks are enforced server-side. Frontend checks are UX only. Protected requests use opaque application sessions, current subject-row reloads, and H-E database-revalidated transaction-local identity.
- **Reasoning:** Frontend code is client-controlled and cannot be trusted for security.
- **Alternatives considered:** None — standard security practice.
- **Consequences for codebase:** Every endpoint validates the app session and checks current role/scope before DB operations. Migration `20260722_000024` revokes browser-role grants but is not RLS. Revisions `20260726_000025` and `20260726_000026` implement the non-owner `NOBYPASSRLS` runtime, separate auth-helper capability, transaction-local trusted context, exact policies/grants, and startup attestation. Ordinary application queries do not use `service_role`, ownership, or `BYPASSRLS`.
- **Reference file and section:** `AGENTS.md` § Security Rules
- **Do not change without PM/stakeholder approval:** Yes

> **⚠️ Most likely LLM mistake:** Omitting a decision from this log and then making a code change that contradicts it. The silent consequence is inconsistent system behaviour that only surfaces during testing or production use.

---

### Decision: RDB Cell Normalisation Before Parsing

Status: ✅ Resolved

- All RDB posting cells must be normalised before classification
- Covers whitespace, line endings, spaced date hyphens, trailing bracket spaces
- Normalisation is syntax-only; must not infer business intent
- Applies globally, not only to LOA parsing

## Section 2 — TBD Register (Full)

---

### TBD Status Entries

---

#### TBD-7: FormF1 vs RDB as Active/Inactive Source
- **Status:** ✅ Resolved — FormF1 is final
- **Resolution:** `form_f1_records.is_active` is the final authoritative active/inactive source for compliance denominator gating.
- **Operational rule:** `Active` and `Extension` are active; `Inactive` is inactive; inactive resident-months are excluded from both numerator and denominator.
- **File and section:** `business-logic.md` § TBD-7; `schema.md` `form_f1_records`
- **Implementation guardrail:** Do not implement RDB-derived denominator logic. Do not derive active/inactive from RDB LOA/refresher/employed annotations.

---

#### TBD-MIGRATION: Historical Data Migration Strategy (superseded — settled)
- **Status:** ✅ Settled — **no historical data migration.** The 2026-08-02 evolved TTF transition contract supersedes the previous option-selection question.
- **Settled decision:** Do not import, backfill, or migrate historical data. Retain legacy workbooks only as legacy structural references; do not build migration tooling.
- **Historical record:** The previous alternatives were (A) archive only — legacy Excel files remain accessible, new system holds cutover-onwards only; (B) summary migration — one-time script inserts summary-level compliance from legacy Excel; and (C) full migration — parse original FormSG CSVs and legacy `.rds` snapshots.
- **Why it mattered (historical):** It would have determined whether historical compliance reports were available in the new system.
- **Current behavior:** No migration tooling exists or is to be built.
- **File and section:** `business-logic.md` § TBD-MIGRATION
- **Historical owner:** PM / Programme Director / Senior Management
- **Can development proceed?** Yes — the decision is settled; no migration or backfill is permitted.
- **Mandatory instruction:** **Do NOT build migration tooling or add an option-selection TODO.**

---

### Resolved TBDs — Do NOT Reopen

---

#### TBD-1: Details of Training Keyword Matching (historical mechanism retired by E2+B2)
- **Original question:** How should teaching events be matched to session types for compliance? The STP/Details of Training keywords were not available in the original system design.
- **Historical decision:** The former A-K parser seeded `teaching_name_catalogue` from Column K. It was not a Phase G runtime source classifier, and session type was not stored on `attendance_records`.
- **Current consequence:** Revision `20260805_000036` removes that table/column and the parsed-data regeneration path. The deferred Phase 6 resolver must use persisted source identity and a scoped mapping, never display-text equality.
- **File and section:** `business-logic.md` § BL-6; `schema.md` final TTF persistence; `parsing.md` § TTF Parser
- **Mandatory instruction:** Do not restore the retired legacy mechanism. The final A-J contract governs current uploads.

---

#### TBD-2: LOA Types and Dormant Posting Codes
- **Original question:** What LOA types should the system accept? How should posting codes not in the current RDB be handled?
- **Final decision:** 14 confirmed LOA types. Parser warns (does not reject) on unknown. Dormant posting codes accepted with `display_name = NULL`. RDB posting code is canonical standard for TTF (last `[]` bracket).
- **Consequences for codebase:** `loa_types` seed data. `rdb_parser.py` warning on unknown. `ttf_parser.py` `ON CONFLICT DO UPDATE` for `posting_codes`.
- **File and section:** `parsing.md` § LOA Type Validation; `schema.md` § `loa_types`, `posting_codes`
- **Mandatory instruction:** Do NOT reopen.

---

#### TBD-3: Admin Scope
- **Original question:** Should admin accounts be global or programme-scoped?
- **Final decision:** Programme-scoped via `users.programme_scope TEXT[]`.
- **Consequences for codebase:** All admin endpoints filter by `programme_scope`.
- **File and section:** `schema.md` § `users`; `api.md` § Authentication Model
- **Mandatory instruction:** Do NOT reopen.

---

#### TBD-4/PH: Public Holiday Event Creation
- **Original question:** Should events on public holidays be allowed with compliance exclusion, or hard-blocked?
- **Final decision:** Hard-blocked (422) for secretary event creation and resident ad-hoc teaching. PH denominator question is moot.
- **Consequences for codebase:** Both endpoints validate against `public_holidays` table before insert. Series materialisation skips PH dates.
- **File and section:** `business-logic.md` § BL-5; `api.md` § error responses
- **Mandatory instruction:** Do NOT reopen.

---

#### TBD-5: Recurrence Editing Granularity
- **Original question:** Should recurrence editing support single-event, following, or all-in-series?
- **Final decision:** All three options required.
- **Consequences for codebase:** `DELETE /secretary/teaching-events/series/{series_id}` with `scope` param.
- **File and section:** `api.md` § Secretary Endpoints
- **Mandatory instruction:** Do NOT reopen.

---

#### TBD-5b: Combined Posting Event Ownership
- **Original question:** For combine-type postings (e.g. `IMHGrPsyc & TTSHPsychi`), who creates events?
- **Status:** ⚠️ Compliance-attribution wording superseded by Phase 6-A; event creator ownership remains historical operational context only.
- **Current compliance decision:** A `combine` rule persists and calculates under one configured canonical combined posting code that already exists in `posting_codes` and has its own TTF rows. No component compliance result is produced, and the denominator comes from the canonical combined posting's targets—not from counting events created at component sites. Event rows may retain their original creator posting, but that field does not replace the configured combined compliance identity.
- **File and section:** `business-logic.md` § BL-8; `AGENTS.md` confirmed decisions
- **Mandatory instruction:** Do not restore component-result or event-count-denominator behavior without a new confirmed decision.

---

#### TBD-6: Refresher Training Compliance Treatment
- **Original question:** Should Refresher Training months have separate compliance logic?
- **Final decision:** Closed. Handled automatically by FormF1 active/inactive gate. Refresher Training months that render a resident inactive appear as `Inactive` in FormF1. `add to Max Cand` / `don't add to Max Cand` stored as display annotation only on `resident_postings.refresher_training_type`.
- **Consequences for codebase:** No separate compliance logic. Store annotation for display only.
- **File and section:** `business-logic.md` § TBD-6
- **Mandatory instruction:** Do NOT reopen.

---

#### TBD-FM: FM Compliance Variant
- **Original question:** Does FM require a separate compliance engine variant?
- **Final decision:** No. FM uses the standard engine. `compliance_variant` column removed. Two FM-specific annotations only: (1) Department Teaching [5h] posting override to `NHGPlyNHGPly`; (2) FM Saturday exception **removed from confirmed list**.
- **Consequences for codebase:** No separate code path. No `compliance_variant` column. Simple if-check for Rule 1.
- **File and section:** `business-logic.md` § BL-FM; `AGENTS.md` confirmed decisions
- **Mandatory instruction:** Do NOT reopen.

> **⚠️ Most likely LLM mistake:** Reopening a resolved TBD (especially TBD-FM or TBD-6) and building separate compliance logic for FM or Refresher Training. Both are resolved — FM uses standard engine, Refresher Training handled by FormF1 gate. The silent consequence is divergent compliance paths that produce different results from the standard engine.

---

## Section 3 — Rejected and Deprecated Approaches

---

#### ❌ `programmes.compliance_variant = 'fm'` column
- **What it was:** A column on the `programmes` table to flag FM as requiring a different compliance calculation path. Initially included a `NotImplementedError` stub.
- **Why rejected:** R script analysis (MATA Core Business Logic Audit) confirmed FM's separate Excel template was a layout difference only — the compliance calculation is identical. Two FM-specific annotations exist within the standard path; no separate variant is needed.
- **When it might become valid:** Never. FM compliance is confirmed as standard.
- **What replaced it:** FM-specific rule annotations in `compliance.py` (Department Teaching [5h] posting override; FM Saturday exception now removed).

---

#### ❌ 422 guard on TTF re-upload when attendance exists
- **What it was:** Blocking TTF re-upload with a 422 error if any attendance records reference the existing teaching targets.
- **Why rejected:** PCs need to correct TTF errors mid-period. Blocking re-upload forces manual DB intervention, which is operationally unacceptable.
- **When it might become valid:** Never in the current workflow.
- **What replaced it:** Re-upload remains allowed. Current event/attendance runtime retains its persisted source evidence and no longer produces retired catalogue-specific orphan warnings.

---

#### ❌ STP upload / STP parser
- **What it was:** An endpoint and parser for uploading STP files directly to the system.
- **Why rejected:** The former A-K rationale required a now-retired Column K/catalogue path. The final A-J TTF does not require or accept Column K, and no STP parser is authorized.
- **When it might become valid:** The historical A-K rationale is superseded at final A-J/E2/B2 cutover; no STP parser is authorized by this decision.
- **What replaced it:** TTF upload is the only teaching target upload path. PC manually converts STP → TTF.

---

#### ❌ LOA/Employed treatment via RDB-derived active/inactive logic
- **What it was:** Deriving active/inactive status from RDB posting phases using a ≥15 working calendar days rule.
- **Why rejected:** RDB posting phases use academic months (e.g. `08 Jul 25 - 03 Aug 25`) which don't align with calendar-month compliance targets. Creates date boundary inconsistencies.
- **When it might become valid:** Only if a separate future requirement explicitly changes the confirmed FormF1 decision.
- **What replaced it:** FormF1 remains calendar-month stored, while the resolved AY bucket label selects the status that gates both numerator and denominator for the whole bucket.

---

#### ❌ `responseIDwithproblemALL` error-code feedback loop
- **What it was:** R script mechanism that tagged individual FormSG submissions with error codes (e.g. `FORMSG01_duplicateposting`, `FORMSG08_sessionnotfound`) and fed them back for manual review.
- **Why rejected:** The new system uses structured POST bodies with Pydantic validation, eliminating the free-text parsing errors that required this mechanism. Validation happens at submission time, not in a batch post-processing step.
- **When it might become valid:** Never.
- **What replaced it:** `status` field on `attendance_records` (`submitted`, `flagged`, `removed`) + real-time 422 validation errors.

---

#### ❌ FormSG CSV column detection via regex
- **What it was:** R scripts detected FormSG response columns via regex patterns (e.g. `FORMSG01` through `FORMSG08`) because FormSG did not guarantee stable column positions.
- **Why rejected:** New system uses structured POST bodies — no CSV parsing needed.
- **When it might become valid:** Never (hard legacy cutover confirmed).
- **What replaced it:** Pydantic request schemas with fixed field definitions.

---

#### ❌ Fuzzy posting-site string matching via `tolower(gsub())`
- **What it was:** R scripts normalised free-text posting site names to match against a master list using lowercase conversion and character stripping.
- **Why rejected:** New system uses `posting_codes` FK relationship — posting codes are exact matches, not fuzzy text.
- **When it might become valid:** Never.
- **What replaced it:** `posting_codes` table with UNIQUE constraint on `code`.

> **⚠️ Most likely LLM mistake:** Re-implementing the `compliance_variant = 'fm'` column or a separate FM compliance code path. This was explicitly rejected after R script analysis. The silent consequence is a divergent FM compliance calculation that may produce different results from the standard engine, creating confusion and audit issues.
---

## Section 4A — R Script Logic to KEEP / PORT

**No additional R script logic confirmed for porting beyond the items below. Do not port any R script logic unless this section is updated.**

---

#### KEEP: Tag-based reallocation sort order (R script `order()` on Tag column)
- **R script:** Script C — compliance calculation, `order()` function applied to Tag column
- **What it does:** Sorts tag groups alphabetically by tag label (A1→A2→A3), which by convention maps to longest→shortest duration.
- **Why retained:** The alphabetical sort order is the confirmed behaviour. PCs assign tags to align alphabetical order with duration descending.
- **MATA specification:** Planned `surplus.py` behavior sorts by tag string. It transfers raw session counts before caps; the TTF validator warns (not blocks) if alphabetical order does not align with duration descending. No code-implementation claim is made.

---

#### DEFERRED EVIDENCE: Legacy clawback rate structure
- **Legacy evidence:** The audited clawback script applied positional/per-R-year rate data and programme classifications.
- **MATA status:** Evidence only, not retained authority and not an implementation claim. Rates, persistence/effective dating, funding R-year, classifications, suppressions, grouping/billing, missing-rate behavior, rounding, and final-close behavior remain deferred.

---

#### KEEP WITH CONFIRMED PRECEDENCE: 70% percentage threshold and displayed ceil target
- **R script:** Script C — compliance calculation
- **Observed legacy behavior:** The script displayed `target_70 = ceiling(target_100 * 0.70)`.
- **Confirmed MATA rule:** Use unrounded `percentage >= 0.70` as the canonical predicate. Retain `target_70` only as a displayed whole-session threshold. This precedence is essential for fractional targets.
- **Implementation status:** Specification only; no application-code or test claim is made.

---

#### KEEP WITH PHASE 6-A ORDERING: Session count capping
- **R script:** Script C — compliance calculation
- **What it does:** `achieved_and_counted = min(raw_achieved, target_100)` — caps achieved at 100% target.
- **Why retained:** Prevents over-counting when a resident exceeds the target for one session type from inflating overall compliance.
- **Confirmed ordering:** Tag transfers use raw achieved session counts first. Each physical-posting/session-type/R-year context is capped at its own target only after transfers, then summed. No implementation claim is made.

> **⚠️ Most likely LLM mistake:** Porting R script logic not listed in this section — particularly the fuzzy string matching or CSV parsing logic. These are explicitly discarded in Section 4B. The silent consequence is fragile, redundant code that conflicts with the structured data model.

---

## Section 4B — Discarded R Script Logic (Full Audit)

### FormSG CSV Ingestion and Parsing (Script B)

| R Script Logic | What It Did | Why Discarded | Replaced By |
|---|---|---|---|
| FormSG CSV column detection via regex (`FORMSG01`–`FORMSG08` patterns) | Detected response columns by pattern because FormSG didn't guarantee stable positions | New system uses structured POST bodies | Pydantic request schemas |
| Date/timestamp format normalisation (dd-MMM-yy, dd/MM/yy, dd/MM/YYYY, etc.) | Parsed 6+ date formats from free-text submissions | Portal submits ISO-8601 | ISO-8601 `DATE` type in Pydantic |
| MCR extraction from free-text name string | Extracted MCR from "Name (MCR)" free-text format | Session-authenticated identity provides MCR directly | Validated app session → current `residents.id` |
| Non-resident filtering via 'I am a' column | Filtered out non-resident FormSG submissions | Portal enforces current database-owned role at login/request time | App-session subject and server-side role reload |
| Consecutive teaching row duplication (`_consec2`, `_consec3` suffixes) | Duplicated rows for consecutive identical teachings in the same FormSG response | Each teaching event is a discrete DB record with its own `teaching_events.id` | Submitted-only unique `(resident_id, teaching_event_id)` index; removed cycles remain immutable history |
| `responseIDwithproblemALL` error-code feedback loop | Tagged submissions with error codes for manual review | Real-time 422 validation at submission time | `status` field on `attendance_records` |

### String Matching and Posting Resolution (Scripts A, B, C)

| R Script Logic | What It Did | Why Discarded | Replaced By |
|---|---|---|---|
| Fuzzy posting-site string matching via `tolower(gsub())` | Normalised free-text posting names to match master list | `posting_codes` FK relationship — exact matches | `posting_codes` table UNIQUE constraint |
| R year derivation from date-range mapping file | External file mapped date ranges to r_year labels | `resident_postings.r_year` DB field populated at RDB parse time | `rdb_parser.py` → `resolve_r_year()` |
| Multiple-posting resolution via string matching (`multipleposting_main`) | Resolved multi-posting free-text into primary posting via string ops | `multi_posting_rules` table with explicit rule types | Admin CRUD + `rdb_parser.py` lookup |
| MASTER07 posting site replacement file | External CSV mapping old posting codes to new ones | Admin UI edits `posting_codes` directly | `posting_codes` table managed via admin |

### Compliance Calculation Overrides (Scripts C, E)

| R Script Logic | What It Did | Why Discarded | Replaced By |
|---|---|---|---|
| `programmes.compliance_variant = 'fm'` + `NotImplementedError` | Separate FM compliance code path | R script audit confirmed FM calculation is identical to standard | Standard engine + two FM annotations |
| Changeover date hard-coded period logic (1H/2H, IM/non-IM) | Hard-coded period boundaries with IM-specific cutover dates | `reporting_periods` table with flexible `start_date`, `end_date` | Admin-managed reporting periods |
| FM separate Excel template (Script E) | Separate report generation for FM | Layout difference only — calculation identical | Standard report endpoints with same calculation |

### Legacy Data Handling (Script A)

| R Script Logic | What It Did | Why Discarded | Retained For |
|---|---|---|---|
| R year derivation from date-range mapping file (batch recalculation) | Recalculated r_year from date ranges for historical amendments | `resident_postings.r_year` is set at RDB parse time | May be needed for historical amendments — retain as batch recalculation job only if needed |

> **⚠️ Most likely LLM mistake:** Porting the `multipleposting_main` string matching logic from R Script C. The new system uses `multi_posting_rules` table with explicit `combine`, `half_month`, `main_posting` rule types — no string matching. The silent consequence is posting resolution that silently disagrees with the `multi_posting_rules` table.

---

## Section 5 — Open Questions and Settled Historical Records

### Business Rules

| # | Question | Why It Matters | Who Answers | Can Dev Proceed? |
|---|----------|---------------|-------------|-----------------|
| 1 | Active/inactive source (TBD-7 closed) | Gates compliance denominator for every resident | PM / Programme Director | Resolved — FormF1 is final authoritative source |
| 2 | TBD-MIGRATION (historical; settled): earlier archive-only, summary, or full-migration options | Formerly determined whether historical reports would be available in the new system | N/A — settled 2026-08-02 | Yes — no historical migration, backfill, or tooling |
| 3 | Clawback financial/final-close contract: rates/effective dating, funding R-year, classification, suppressions, grouped identity, billing, missing rates, rounding, and rerun/idempotency | Required before any clawback implementation | PM / Finance / Programme Director | No for clawback; ordinary compliance can proceed |
| 4 | Are there any additional programmes beyond the 28 seeded in `programmes`? | Missing programmes would cause parse failures on RDB upload | PM | Yes — new programmes can be added via admin CRUD |

### Excel Format

| # | Question | Why It Matters | Who Answers | Can Dev Proceed? |
|---|----------|---------------|-------------|-----------------|
| 5 | Does the FormF1 year suffix need to handle academic years other than AY2025 (Jul-25 through Jun-26)? | Parser sample hardcodes '25'/'26' — must be dynamic | PM / Dev | Yes — make dynamic based on `reporting_periods.start_date` |
| 6 | Are there FormF1 status values beyond `Active`, `Inactive`, `Extension`? | Unknown values would be silently treated as active | PM | Yes — parser warns on unknown values |

### Frontend

| # | Question | Why It Matters | Who Answers | Can Dev Proceed? |
|---|----------|---------------|-------------|-----------------|
| 7 | What is the exact UX flow for the admin configuration panel (CRUD for `loa_types`, `weekend_exceptions`, etc.)? | Affects frontend page structure | PM / UX Designer | Yes — standard CRUD patterns |
| 8 | Should the resident dashboard show historical compliance from past periods (via `period_snapshots`)? | Determines dashboard scope | PM | Yes — can be added later |

### Deployment

| # | Question | Why It Matters | Who Answers | Can Dev Proceed? |
|---|----------|---------------|-------------|-----------------|
| 9 | What approved Supabase deployment target and configuration will be used? | Required for deployed backend-mediated staff auth and H-D post-deployment verification | DevOps / PM | Local implementation can proceed; deployment evidence remains separate |
| 10 | What is the Vercel deployment configuration for the frontend? | Required for production deployment | DevOps | Yes — not needed until deployment |
| 10A | What approved resident second factor, if any, will satisfy production assurance? | MCR-only remains the implemented path but assurance approval is unresolved | PM / Security owner / Programme leadership | H-D may complete; do not invent a factor |
| 10B | Has deployed cookie, Origin, migration, grant, and session behavior passed the H-D smoke contract? | Local verification does not prove deployed controls | DevOps / Security owner | Deployment approval remains separate |
| 10C | Has the approved database passed the H-E revision, three-credential, ownership, role, policy, helper, grant, default-ACL, PUBLIC/browser, startup-attestation, and five-role workflow checks? | Local disposable-PostgreSQL evidence does not establish the deployed RLS boundary | DevOps / Security owner | Deployment approval remains separate |

### Testing

| # | Question | Why It Matters | Who Answers | Can Dev Proceed? |
|---|----------|---------------|-------------|-----------------|
| 11 | What test data (sample RDB, TTF, FormF1 files) is available? | Required for parser testing | PM | Yes — development can use mock data |
| 12 | What are the acceptance criteria for compliance calculation accuracy? | Defines test pass/fail threshold | PM | Yes — use R script output as reference |

> **⚠️ Most likely LLM mistake:** Treating open questions as blocking and refusing to generate code. Most questions have a "Can Dev Proceed? Yes" answer — development proceeds with the documented placeholder/default.

---

## Section 6 — Contradictions and Ambiguities

---

#### Contradiction: FM Saturday exception — conflicting signals across files
- **What:** `business-logic.md` § BL-FM states "FM Saturday teachings are accepted if start_time >= 08:00 and end_time <= 13:00. This is handled via the `weekend_exceptions` table." But `AGENTS.md` Key Architectural Rules states "FM Saturday exception has been removed from the confirmed weekend_exceptions list per PC update." And `schema.md` `weekend_exceptions` confirmed seeded rows do NOT include an FM row.
- **Which source to trust:** `schema.md` seed data is authoritative for what's actually seeded. **No FM row in `weekend_exceptions`.** AGENTS.md confirmed decisions table is authoritative: 'SIG, FM, ANAES, and all emergency posting exceptions removed per PC confirmation.' business-logic.md § BL-FM is stale on this specific point only — it has not been updated to reflect the removal.
- **PM resolution needed?** No — resolved. FM Saturday exception is removed. Final.

---

#### Contradiction: Attendance status lifecycle
- **What:** The project prompt mentions "Attendance status lifecycle: pending → approved / rejected" but `schema.md` defines `attendance_records.status` as `DEFAULT 'submitted'` with values `submitted`, `flagged`, `removed`. No `pending`, `approved`, or `rejected` states exist in the schema.
- **Which source to trust:** `schema.md` is authoritative for database schema. The status values are `submitted`, `flagged`, `removed`.
- **PM resolution needed?** Possibly — if an approval workflow is intended for a future phase, the schema would need updating. For now, use schema values.

---

#### Resolved: FormF1 month-label year derivation
- **Rule:** Derive every FormF1 `month_label` dynamically from the selected reporting period dates. Do not hardcode AY2025 suffixes.
- **PM resolution needed?** No. This is parser correctness and is specified in `parsing.md`.

---

#### Resolved: persisted event source and scoped mapping boundary
- **Confirmed rule:** Scheduled-event creation selects explicit source IDs. Phase G discovery and attendance use those IDs (or deterministic both-null legacy evidence), and never classify from a name. The Phase 6 resolver remains deferred; it must scope any mapping by source identity, period, resident programme, assigned/compliance posting, and phase R-year.
- **Data-quality boundary:** Display snapshot case/spacing is upload/UI cleanup, not a runtime source or compliance ambiguity. Do not use display-text matching, fuzzy matching, or `ILIKE` as a substitute for persisted source identity.
- **PM resolution needed?** No for the Phase G runtime boundary; Phase 6 implementation remains deferred.

> **⚠️ Most likely LLM mistake:** Restoring the legacy FM Saturday exception. Current `business-logic.md`, `schema.md`, and `AGENTS.md` all confirm that no FM weekend-exception row is seeded.

---

## Section 7 — Missing Context and Settled-History Audit

| # | What Is Missing | Why It Matters | Where Placeholder Is Used | Where to Update When Provided |
|---|----------------|---------------|--------------------------|-------------------------------|
| 2 | TBD-MIGRATION option selection (historical; settled) | Former question of historical data availability | No migration code or placeholder TODO; migration is prohibited | No action — settled: no historical data migration |
| 3 | Complete clawback financial/final-close contract | Required only for deferred clawback | No implementation-ready placeholder; legacy evidence is non-authoritative | Source-of-truth documents after stakeholder confirmation |
| 7 | Approved resident identity-assurance change, if any | Separately governed product debt; not a stop condition for the final security review | No factor is invented or implemented by H-D | Auth contract and deployment approval records after stakeholder decision |
| 8 | Deployed H-D/H-E verification | Required to distinguish local code evidence from live cookie/session and RLS behavior | H-D and H-E implementation reports contain local evidence only | Deployment smoke/evidence document |

> **⚠️ Most likely LLM mistake:** Treating legacy clawback evidence as an implementation-ready formula. The entire financial/final-close contract is deferred; ordinary compliance remains independently specified.

---

## Section 8 — High-Risk Blind Spots

These are implementation errors that would fail silently — no exception thrown, wrong data produced.

---

#### Security blind spots added by 5B-H-D

- Mistaking `20260722_000024` browser-role privilege revocation alone for the H-E role/context/policy implementation.
- Treating passing local tests and audits as proof of deployed Vercel/Supabase security.
- Enabling `bearer_compat` as routine production transport instead of a time-bounded emergency rollback.

#### Security blind spots added by 5B-H-E

- Using the migration/ownership credential, `service_role`, a superuser, or any `BYPASSRLS` role for ordinary application queries.
- Installing transaction context from browser claims or request fields instead of the current database-owned application session and subject.
- Losing transaction-local context after an in-request commit/rollback or retaining stale identity-map authority across a pooled connection.
- Broadening an exact helper grant or adding direct privileges to helper-only tables to fix a workflow.
- Treating the local 34-table/84-policy catalogue as proof that the approved Supabase target has revision `20260726_000026` or the same roles, owners, grants, policies, and default ACLs.

#### ⚠️ Blind Spot 1: Using `residents.r_year` instead of `resident_postings.r_year`
- **Where:** `compliance.py` — any join to `teaching_targets`
- **Silent consequence:** Wrong `teaching_targets` row matched for residents who cross a year boundary mid-period. Wrong compliance target applied. Wrong percentage. Wrong traffic light. No error thrown.
- **How to detect:** Unit test: create R2 and R3 phases at the same physical posting. Verify event-date phase resolution, correctly weighted targets, separate context caps, and posting-level summation without duplicated active months.

---

#### ⚠️ Blind Spot 2: Writing reallocated surplus values to `surplus_ledger`
- **Where:** `surplus.py` — after `reallocate_by_tag()` returns
- **Silent consequence:** Treating the ledger as a transfer balance or adding it back to attendance double-counts sessions. Incrementing instead of replacing makes repeated reads non-idempotent.
- **How to detect:** Recompute twice and verify the value remains `max(cumulative raw eligible attendance - cumulative target_100, 0)`. Extend the target by a return phase and verify the stored surplus decreases without being added to attendance.

---

#### ⚠️ Blind Spot 3: 70% threshold at session-type level instead of posting level
- **Where:** Planned `compliance.py` posting aggregation
- **Silent consequence:** Applying the session-type threshold or displayed `target_70` instead of the unrounded posting percentage gives wrong colours, especially for fractional targets.
- **How to detect:** Verify a fractional target capped at 100% passes even when displayed `ceil(target_100 × 0.70)` exceeds the fractional cap; also verify aggregation across two session types.

---

#### ⚠️ Blind Spot 4: Using `teaching_events.session_type_id` for compliance
- **Where:** `compliance.py` — attendance counting logic
- **Silent consequence:** Cross-programme residents get wrong session type. Session type does not update when source/mapping configuration changes. Compliance percentages are stale.
- **How to detect:** Integration test: create source-backed events at a posting shared by two programmes with distinct persisted source IDs and scoped mappings. Submit attendance from residents of both programmes. Verify each resolves through its authorized source/mapping, never `session_type_id` or display text.

---

#### ⚠️ Blind Spot 5: Deriving posting codes by string pattern
- **Where:** Any code that constructs a posting code from institution + department strings
- **Silent consequence:** Silently wrong codes for non-pattern codes (`AICAIC`, `MOHHGTG1`, `NHGPlyNHGPly`, `RenCiCommHosp`). Events created under wrong posting. Compliance attributed to wrong posting.
- **How to detect:** Code review: search for string concatenation or regex patterns that construct posting codes. All posting codes must come from `posting_codes` table queries.

---

#### ⚠️ Blind Spot 6: Using raw `achieved` instead of `achieved_and_counted`
- **Where:** `compliance.py` — posting-level compliance aggregation
- **Silent consequence:** Compliance percentages above 100% for session types where achieved > target. Overall posting compliance inflated. Green traffic light when it should be amber/red.
- **How to detect:** Unit test: set `monthly_target = 5`, `active_months = 2`, `raw_achieved = 15`. Verify `achieved_and_counted = 10` (capped at target_100), not 15.

---

#### ⚠️ Blind Spot 7: Implementing RDB-derived denominator logic against confirmed FormF1 decision
- **Where:** `compliance.py` — active/inactive gate
- **Silent consequence:** Incorrect denominator gating and compliance drift from confirmed requirements.
- **How to detect:** Code review: search for denominator logic derived from RDB LOA/refresher/employed fields instead of `form_f1_records.is_active`.

---

#### ⚠️ Blind Spot 8: Treating a Codex design spec as implemented code
- **Where:** Any module that imports from a planned (unimplemented) module
- **Silent consequence:** `ImportError` at runtime, or worse, building code that assumes an API surface that doesn't exist yet.
- **How to detect:** Before coding any module, check whether the modules it depends on actually exist in the codebase. Don't rely on the source-of-truth files alone.

---

#### ⚠️ Blind Spot 9: Skipping explicit global-source identity before scoped mapping
- **Where:** `compliance.py` — BL-6 step 5
- **Silent consequence:** Explicit global-source events (e.g. Department Meeting) feed compliance numbers when they should be excluded. Inflates both numerator and denominator.
- **How to detect:** Unit test: create an event with `global_session_type_id`. Submit attendance. Verify it is excluded from compliance numerator AND denominator without inspecting display text.

---

#### ⚠️ Blind Spot 10: Applying the wrong R-year configuration
- **Where:** deferred `compliance.py` scoped mapping/target resolution; `ttf_parser.py` target insertion
- **Silent consequence:** Scoped mapping/target resolution returns zero or wrong results for the 20 `ALL` programmes, or SPORTSMED/PALLMED are incorrectly stored as `ALL`/SS years.
- **How to detect:** Verify GERI resolves through `ALL`, while SPORTSMED/PALLMED preserve and match R4, R5, and R6 with `is_subspecialty = false`.

---

#### ⚠️ Blind Spot 11: Calculating compliance independently for grouped postings
- **Where:** `compliance.py` — active_months and target_100 calculation
- **Silent consequence:** Wrong compliance for postings in `posting_groups`. Active months not pooled across group. Target_100 computed per posting instead of across group.
- **How to detect:** Integration test: create a RESPI resident posted at `TTSHRespi` (3 months) and `TTSHRespi(MICU)` (2 months), both in group `TTSHRespi`. Verify `active_months = 5` (pooled), not calculated as two separate 3-month and 2-month postings.

---

#### ⚠️ Blind Spot 12: Ignoring `form_f1_records.is_active` gate
- **Where:** `compliance.py` — active_months counting
- **Silent consequence:** Using raw event calendar month can apply two FormF1 states inside one AY bucket, inconsistently gating numerator and denominator.
- **How to detect:** Use an AY `Jul-26` bucket ending 3 August. Verify 3 August uses July FormF1 for both numerator and denominator, while the next AY bucket uses August.

---

#### ⚠️ Blind Spot 13: Writing ORTHO mutation to DB
- **Where:** `compliance.py` or attendance submission endpoint
- **Silent consequence:** Raw attendance data corrupted. Original session type and duration lost. If ORTHO changes policy, data migration needed instead of simple config change.
- **How to detect:** Submit the exact 3h type and another ORTHO type. Verify only the exact type subtracts two end-time hours, projects to the 1h type, and is checked against Saturday 08:30–10:30; verify Sunday remains excluded and raw rows stay unchanged.

---

#### ⚠️ Blind Spot 14: Using `compliance_variant = 'fm'` code path
- **Where:** `compliance.py` — any conditional branch checking for FM variant
- **Silent consequence:** Divergent FM compliance calculation. May produce different results from standard engine. Code maintenance burden doubles.
- **How to detect:** Code review: search for `compliance_variant`, `fm_variant`, or any FM-specific compliance conditional. Should not exist.

---

#### ⚠️ Blind Spot 15: Hardcoding RDB posting column range (I–T)
- **Where:** `rdb_parser.py` — column iteration
- **Silent consequence:** Missing posting months if the RDB file adds or shifts columns. Parser silently skips months, creating gaps in `resident_postings`.
- **How to detect:** Unit test: create an RDB file with posting columns starting at column J instead of I. Verify parser detects all months via date-range header scanning.

---

## Section 9 — Things Not to Change Without PM/Stakeholder Approval

| # | Rule / Decision | Why It Must Not Change | Who Approves | Specification location / planned module |
|---|----------------|----------------------|-------------|-------------------|
| 1 | Unrounded posting percentage is the canonical 70% predicate; `target_70` is display-oriented | Regulatory requirement and fractional-target correctness | PM / Programme Director | `business-logic.md` BL-2; planned `compliance.py` |
| 2 | Session counts as compliance unit (not hours) | Regulatory framework | PM / Programme Director | `compliance.py` — all counting logic |
| 3 | Surplus resets at period boundary | PM-confirmed policy | PM | `surplus.py` — future final close/freeze surplus hibernation logic |
| 4 | Tag-based reallocation sort: alphabetical by tag label | Matches R script; PC convention | PM | `surplus.py` → `reallocate_by_tag()` |
| 5 | Reallocation is read-time only | Audit trail integrity | PM | `surplus.py` — never write back |
| 6 | FormF1 as final active/inactive source | TBD-7 resolved | PM / Programme Director | `compliance.py` — `form_f1_records.is_active` gate |
| 7 | `ALL` for 20 programmes; SPORTSMED/PALLMED R4–R6 with no SS remap | Programme configuration | PM | `schema.md`, `parsing.md`, BL-11 |
| 8 | `teaching_events.session_type_id` is display only | Cross-programme correctness | PM | Schema design; `compliance.py` ignores it |
| 9 | TTF re-upload: warn, not 422 | PC workflow requirement | PM | `ttf_parser.py` — orphan detection |
| 10 | Public holiday hard block (422) | Operational policy | PM | Event creation endpoints |
| 11 | Posting codes from table only | Data integrity | PM | All code referencing posting codes |
| 12 | Resident visibility gated by RDB upload | Logical necessity | PM | `GET /resident/events` |
| 13 | `global_session_types` exclusion priority | Compliance correctness | PM | `compliance.py` BL-6 step 5 |
| 14 | Exact-type ORTHO adjusted-time Saturday mutation is read-time only | Audit trail and predicate correctness | PM | BL-5; `weekend_exceptions` specification |
| 15 | `posting_groups` aggregation | Compliance correctness for grouped postings | PM | `compliance.py` group aggregation |
| 16 | FM uses standard engine — no variant | R script audit confirmed | PM | `compliance.py` — no FM branch |
| 17 | FM Saturday exception removed | PC confirmation | PM | `weekend_exceptions` seed data |
| 18 | Hard legacy cutover | Operational decision | PM / Senior Management | System architecture |
| 19 | Clawback financial/final-close contract remains deferred | Prevents invention of financial rules | PM / Finance | BL-10 deferred register |
| 20 | Ad-hoc teaching is a fixed server-owned `Department/Programme Teaching [1h]` record under the date-derived posting; no catalogue/target lookup or arbitrary free-text mapping | Policy decision | PM | BL-9; `POST /resident/adhoc-teaching` |
| 21 | MCR-only resident auth (no password) | Intentional design choice | PM | `POST /auth/login` resident path |
| 22 | Admin programme scope (TEXT[]) | Access control policy | PM | `users.programme_scope` |
| 23 | Non-tracked rows retained as transitional parser/configuration data; Phase G uses persisted source evidence | Parser/configuration policy | PM | `ttf_parser.py` — catalogue seeding |
| 24 | Duration embedded in session type name [Xh] | TTF format convention | PM | `parsing.md` — no separate column |
| 25 | `posting_groups` independent from `multi_posting_rules` | Architectural separation | PM | Separate tables, separate usage contexts |
| 26 | Weekend submission: stored + warning | Resident transparency policy | PM | `POST /resident/attendance` response |
| 27 | Former fixed clawback suppression/display wording | Superseded; precedence and row behavior are deferred | PM / Finance | Deferred clawback register |
| 28 | AY month bucketing via `academic_month_boundaries` + `programmes.ay_date_category` (ignore SR/SRs header wording) | Compliance month assignment correctness and parser stability across workbook header drift | PM / Programme Director | `parsing.md` AY Dates parser; `schema.md` programme/category + boundary tables; `business-logic.md` BL-5A |
| 29 | Non-NHG resident workflow is Phase 5B before compliance, excluded from NHG compliance/clawback, and Excel-exportable for forwarding | Prevents accidental inclusion in NHG denominator/numerator and establishes forwarding workflow before Phase 6 | PM / Programme Director | Non-NHG resident auth/submission/export design |
| 30 | Master admin must be explicit; never inferred from `programme_scope = NULL` | Access-control correctness and least-privilege integrity | PM / Security owner | `users` auth model and admin endpoint guards |
| 31 | Native NHG Resident scheduled-event visibility is limited to assigned posting secretary events, native programme TTSH department secretary events, and native programme PC-created events | Prevents arbitrary TTSH department visibility while preserving native teaching access | PM / Programme Director | Future resident event visibility logic |
| 32 | Bulk TTF upload deferred; one-programme-at-a-time remains current workflow | Avoids premature high-risk parser/mapping complexity | PM | Existing `POST /admin/upload/ttf` scope flow |
| 33 | Latest uploaded TTF export/email deferred to end-of-roadmap and staged | Prevents premature storage/email coupling before core stabilization | PM / IT | Future admin productivity module |
| 34 | Programme PC teaching event CRUD is roadmap item `4B` before compliance; PC-created scheduled events are programme-owned | Lets PCs seed/manage programme teachings before compliance while preserving secretary programme-neutral event model | PM / Programme Director | Implemented admin programme-teaching endpoints; implemented `teaching_events.created_for_programme_code` |
| 35 | Non-NHG forecast posting schedule uses date-bounded `external_resident_postings`; `current_nhg_posting_code` is not the long-term sole derivation source | Supports cross-month postings and date-specific authorization | PM / Programme Director | Non-NHG resident registration/update; BL-12 |
| 36 | Posting codes must resolve through `posting_codes` and validated/configured mapping, never string concatenation or regex | Data integrity for non-uniform RDB posting codes | PM / Programme Director | Posting selection, registration, ad-hoc options |
| 37 | Native programme to TTSH teaching-posting visibility requires explicit mapping, not string inference | Avoids accidental cross-department event exposure | PM / Programme Director | `programmes.native_teaching_posting_code` or `programme_teaching_posting_map` |
| 38 | Non-NHG programme/institution mapping used a pending Stage 1 baseline followed by a validated Stage 2 state of 24 active and 4 inactive/null TTSH mappings, with no runtime exceptions or cross-domain fallback | Prevents guessed posting identity and accidental Secretary/native/compliance coupling while allowing mapping-scoped unavailability | PM / Programme Director | `programme_institution_posting_map` and trusted resolver |
| 39 | Master Admin force deletion is an explicit, audited, transactional exception for Secretary/PC scheduled events only | Prevents silent partial deletion or privilege expansion while allowing destructive operational correction | PM / Security owner | Dedicated `/admin/secretary-events/{id}/force-delete` action and audit service |
| 40 | Backend-owned opaque cookie/CSRF transport is the normal production path | Prevents reintroduction of browser-visible application credentials | PM / Security owner | H-D implementation and auth contract |
| 41 | Subject → family advisory lock → fresh locked-row rotation order and unique one-child invariant | Prevents concurrent session resurrection or double rotation | Security owner | `app_sessions` service and PostgreSQL race tests |
| 42 | No resident second factor may be invented without approval | Authentication policy and clinical-user workflow require stakeholder authority | PM / Security owner / Programme leadership | Separately governed product-debt record and auth contract |
| 43 | A Programme PC maps its own TTF against its native Department Secretary's names and host-Secretary names admitted by actual same-period native Resident postings; admission persists for that reporting period | Ensures Residents posted externally receive their native programme's correct TTF classification without granting every PC every department list | PM / Programme leadership | Implemented Phase V; `business-logic.md`, `schema.md`, `api.md`, `security.md` |
| 44 | PC-created Teaching Names are private to the PC's native programme, visible only to that programme's PCs and native Department Secretary, and labelled with immutable PC provenance | Prevents cross-programme name leakage while allowing PCs to add and map missing programme-specific names | PM / Programme leadership / Security owner | Implemented Phase V; Teaching Name lifecycle and mapping contracts |

> **⚠️ Most likely LLM mistake:** Changing the 70% threshold to 75% or 65% because it "seems more reasonable." The threshold is a regulatory requirement. The silent consequence is every compliance calculation being wrong for every resident.

---
