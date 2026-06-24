# 99_decision_log_and_gap_audit.md — MATA Dashboard Decision Log and Gap Audit

> **Purpose:** This is the exhaustive safety and audit document for the MATA project. It is not meant to be read linearly — it is a reference and audit trail for decisions, TBDs, rejected approaches, risks, and blind spots.
>
> **Authority:** This document is an audit trail. If it conflicts with `schema.md`, `api.md`, `business-logic.md`, `parsing.md`, or `AGENTS.md`, trust the domain-specific source-of-truth file and flag this document for update.
>
> **Status markers:** ❓ unresolved, ⚠️ high-risk, ✅ confirmed, 🔧 partially implemented, ❌ deprecated

---

## Section 1 — Complete Decision Log

Every important decision made during the project, with reasoning and consequences.

---

#### Decision: Admin accounts are programme-scoped
- **Status:** ✅ Confirmed
- **Decision:** Admin/PC accounts use `users.programme_scope TEXT[]` to restrict access to specific programmes. `NULL` = no access (not all-access).
- **Reasoning:** PCs manage specific programmes — they should not see data for programmes they don't own. Multiple programmes per account supported for PCs who manage several.
- **Alternatives considered:** (1) Single global admin role — rejected, violates least-privilege. (2) Separate admin table — rejected, unnecessary complexity.
- **Consequences for codebase:** Every admin endpoint must filter by `programme_scope`. Admin report queries include `WHERE r.programme_code = :programme_code` with programme_code validated against JWT claims.
- **Reference file and section:** `schema.md` § `users` table; `api.md` § Authentication Model
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: External / cross-cluster residents workflow (Phase 5B)
- **Status:** ✅ Confirmed implementation direction
- **Decision:** External residents are residents from `NUH` or `SingHealth` who are posted to NHG/TTSH departments. They use a separate `external_residents` table and separate `external_attendance_records` table. Native NHG residents remain RDB-backed in `residents` + `resident_postings`.
- **External registration capture fields:** `name`, `mcr`, `home_cluster` (`NUH` or `SingHealth`), `current_nhg_posting_code`.
- **MCR uniqueness:** MCR is globally unique for every doctor. Because native and external identities use separate tables, enforce cross-table uniqueness in service logic: reject registration if MCR exists in either `residents` or `external_residents`.
- **Workflow direction:** External residents self-register on first use. After registration, login is MCR-only. External residents may self-update their current NHG posting.
- **Posting model:** External current posting is stored separately on `external_residents.current_nhg_posting_code`; do not use native `resident_postings`.
- **Functional scope:** Phase 5B must be completed before Phase 6 compliance. It includes external registration/login, current NHG posting update, supported event listing, attendance submission, revised ad-hoc teaching submission, past attendance, admin/PC external attendance list/read, and Excel export for forwarding to NUH/SingHealth PCs.
- **Explicit exclusions:** External residents are excluded from NHG compliance and clawback surfaces:
  - no NHG resident compliance dashboard
  - no clawback output
  - no NHG compliance numerator inclusion
  - no NHG compliance denominator inclusion
  - no surplus ledger / period snapshot inclusion
- **Export requirement:** External attendance must be queryable by authorized admin/PC users and exportable to Excel for onward sharing to relevant NUH or SingHealth PCs.
- **Export status:** ✅ Confirmed before compliance. Exact endpoint response metadata and workbook columns are implementation details, but the export format is Excel.
- **Do not use:** `users`, `programme_scope`, native `residents`, or native `resident_postings` for external resident identity/posting state.
- **Reference file and section:** `schema.md` § `external_residents`, `external_attendance_records`; `api.md` § External Resident Endpoints; `business-logic.md` § BL-12
- **Do not change without PM/stakeholder approval:** Yes
---

#### Decision: Programme PC teaching event CRUD before compliance
- **Status:** ✅ Confirmed requirement, planned implementation
- **Decision:** Add pre-compliance roadmap item `4B - Programme PC Teaching Event CRUD`. Programme PCs must be able to create, list, edit, delete, duplicate, and manage recurrence for scheduled teaching events for their own programmes where practical, similar to department secretary event CRUD.
- **Ownership model:** PC-created teaching events are scheduled teaching events, not ad-hoc submissions. They must carry explicit programme ownership/scope, with planned nullable field `teaching_events.created_for_programme_code`: required for PC-created programme-owned events and null for normal secretary-created posting-owned/programme-neutral events unless an explicit future use case sets it.
- **Scope and auth:** Backend authorization is mandatory: `role = admin`, requested `programme_code IN programme_scope`, and null/empty `programme_scope` means no programme access. Master admin all-programme access must be explicit and is never inferred from null programme scope.
- **Visibility:** Secretary-created events remain posting-owned and programme-neutral. PC-created events must not be visible to other programmes unless explicitly intended. Resident event discovery must treat `created_for_programme_code IS NULL` as normal posting-owned visibility, and a set value as programme-owned visibility requiring resident `programme_code` match plus normal posting/date/catalogue checks.
- **Options source:** PC-created teaching options come from that programme's TTF Column K via `teaching_name_catalogue`.
- **Validation:** Public holiday hard-block applies. Delete is blocked if any native or external attendance exists. Audit actor is PC/admin, not secretary.
- **Implementation status:** Planned documentation contract only. Current models/migrations do not contain `created_for_programme_code`.
- **Reference file and section:** `schema.md` § `teaching_events`; `api.md` § Planned `4B` Programme PC Teaching Event CRUD endpoints; `business-logic.md` § PC-created teaching event visibility
- **Do not change without PM/stakeholder approval:** Yes
---

#### Decision: Secretary-created event visibility capability flag
- **Status:** ✅ Confirmed implementation direction
- **Decision:** Use `posting_codes.supports_secretary_events BOOLEAN DEFAULT false` as the scalable capability flag for secretary-created event visibility.
- **Current pilot:** TTSH pilot postings can be seeded/configured with `supports_secretary_events = true`, so residents posted there see secretary-created events plus ad-hoc submission.
- **Future onboarding:** Future hospitals such as KTPH can be enabled by setting the same flag on their posting codes. This avoids service-code hardcoding and makes onboarding a data/config change.
- **Behaviour:**
  - `supports_secretary_events = true` → residents/external residents at that posting may see secretary-created event lists and may also submit ad-hoc teaching.
  - `supports_secretary_events = false` → no secretary-created event list is expected; ad-hoc submission remains available.
- **Applicability:** Applies to both native NHG residents and external NUH/SingHealth residents.
- **Rejected approach:** Hardcoding `posting_codes.institution = 'TTSH'` in service logic.
- **Reference file and section:** `schema.md` § `posting_codes`; `business-logic.md` § BL-12; `api.md` § Resident/External Resident Endpoints
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
- **Consequences for codebase:** `surplus_ledger` rows are period-scoped via `reporting_period_id`. Future final close/freeze sets `is_hibernating = true` on all rows. New period starts with zero surplus.
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
- **Decision:** Surplus reallocation flows within tag groups only (same prefix). No cross-tag or cross-posting flow. Sort is alphabetical by tag label (A1→A2→A3), not by duration. One-for-one session count transfers.
- **Reasoning:** Matches the R script's `order()` on the Tag column. By convention, PCs assign A1 = longest duration, A2 = shorter. Alphabetical sort preserves this convention without requiring a separate sort field.
- **Alternatives considered:** (1) Duration-based sort — rejected, doesn't match R script behaviour. (2) Cross-tag flow — rejected by PM. (3) Weighted transfers based on duration ratio — rejected, adds complexity with no stakeholder request.
- **Consequences for codebase:** `reallocate_by_tag()` in `surplus.py` sorts by `row['tag']` alphabetically. TTF upload validator warns (not blocks) if tag order doesn't align with duration descending.
- **Reference file and section:** `business-logic.md` § BL-3; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Session counts, not hours — compliance unit
- **Status:** ✅ Confirmed
- **Decision:** Compliance is measured in number of sessions attended. Duration is never a multiplier. 1 session = 1 session regardless of 0.5h or 3h.
- **Reasoning:** Matches the legacy R script behaviour and the regulatory framework. Duration is embedded in session type names for display and reallocation flow direction only.
- **Alternatives considered:** Duration-weighted compliance — never proposed by stakeholders.
- **Consequences for codebase:** No multiplication by `duration_hours` anywhere in `compliance.py`. Duration stored on `session_types` and `teaching_events` for display and as a tiebreaker only.
- **Reference file and section:** `AGENTS.md` § Key Architectural Rules; `business-logic.md` § BL-1
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Reallocation is read-time only — never written to surplus_ledger
- **Status:** ✅ Confirmed
- **Decision:** `reallocate_by_tag()` is a read-time computation applied after fetching `surplus_ledger` values. Reallocated values are never written back to `surplus_ledger`.
- **Reasoning:** Writing reallocated values would corrupt the pre-reallocation audit trail and cause double-counting on the next compliance read. Surplus must always reflect the raw, pre-reallocation state.
- **Alternatives considered:** Materialising reallocated values — rejected due to audit trail corruption risk.
- **Consequences for codebase:** `surplus_ledger.surplus` stores pre-reallocation values only. `update_surplus()` is called BEFORE `reallocate_by_tag()`. The reallocation function modifies in-memory rows, never DB rows.
- **Reference file and section:** `business-logic.md` § BL-3, BL-4
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: TTF upload — full replace, warn not 422 on existing attendance
- **Status:** ✅ Confirmed
- **Decision:** TTF re-upload is always a full replace within `(reporting_period_id, programme_code)` scope, regardless of existing attendance. No 422 attendance guard. Orphaned attendance returned as warnings.
- **Reasoning:** PCs need to correct TTF errors mid-period. Blocking re-upload forces manual DB intervention. Orphaned attendance is silently excluded from compliance on next read — no data corruption, just compliance recalculation.
- **Alternatives considered:** 422 guard blocking re-upload when attendance exists — rejected, too restrictive for PC workflow.
- **Consequences for codebase:** `ttf_parser.py` deletes and re-inserts `teaching_targets` and `teaching_name_catalogue` within scope. Post-write orphan detection query checks for attendance records with no matching catalogue row. Results included in response `warnings` array.
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
- **Consequences for codebase:** `GET /resident/events` returns empty list with `reason: "posting_schedule_unavailable"` when no `resident_postings` rows exist for the current period.
- **Reference file and section:** `api.md` § GET `/resident/events` visibility gating
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: Use resident_postings.r_year for compliance — not residents.r_year
- **Status:** ✅ Confirmed
- **Decision:** Compliance target lookups use `resident_postings.r_year` (per phase), not `residents.r_year` (display only). A resident may cross a residency year boundary mid-period.
- **Reasoning:** A resident might be R2 for the first 3 months and R3 for the last 3 months of a reporting period. Each phase must be matched against the correct teaching targets.
- **Alternatives considered:** None — `residents.r_year` is a convenience display field only.
- **Consequences for codebase:** All compliance joins use `resident_postings.r_year`. The `residents.r_year` field is never used in `compliance.py` or `surplus.py`.
- **Reference file and section:** `business-logic.md` § BL-1, BL-6; `schema.md` § `residents` table
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: STP never uploaded — TTF is the compliance input
- **Status:** ✅ Confirmed
- **Decision:** STP is a planning document created by secretaries. It is never uploaded to the system. No STP parser exists. PC manually converts STP to TTF before Admin uploads TTF. Column K (Details of Training) is absent from STP and must be added manually.
- **Reasoning:** STP lacks the structured data needed for compliance (column K keywords, tags, reallocation flags). The PC adds this data during manual conversion. Automating the conversion is not possible without column K.
- **Alternatives considered:** STP upload with auto-conversion — rejected because column K data does not exist in STP.
- **Consequences for codebase:** No `stp_parser.py`. No STP upload endpoint. TTF is the only teaching target upload path.
- **Reference file and section:** `AGENTS.md` § "No STP in the system"
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: teaching_events.session_type_id is display only
- **Status:** ✅ Confirmed
- **Decision:** `session_type_id` on `teaching_events` is resolved at event creation for display in the Teaching Type column. It is NEVER used for compliance calculation. Compliance always re-resolves session type per resident at read time via `teaching_name_catalogue`.
- **Reasoning:** A teaching event may serve residents from multiple programmes. Each programme may map the same `teaching_name` to a different session type. Storing a single session type would be wrong for cross-programme residents.
- **Alternatives considered:** Storing session type per attendance record — rejected because TTF re-uploads would make stored values stale.
- **Consequences for codebase:** `compliance.py` never reads `teaching_events.session_type_id`. It always joins `teaching_name_catalogue` using `(keyword = teaching_event.teaching_name, posting_code, programme_code, r_year, reporting_period_id)`.
- **Reference file and section:** `AGENTS.md` § Key Architectural Rules; `business-logic.md` § BL-6; `schema.md` § `attendance_records`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: FormF1 as final active/inactive source (TBD-7 resolved)
- **Status:** ✅ Confirmed and final
- **Decision:** `form_f1_records.is_active` per calendar month is the compliance denominator gate. `Active` and `Extension` → true. `Inactive` → false (excluded from both numerator and denominator).
- **Reasoning:** FormF1 is calculated on a calendar month basis, which aligns with compliance targets. RDB posting phases use academic months (e.g. `08 Jul 25 - 03 Aug 25`). Using RDB phases creates date boundary inconsistencies.
- **Alternatives considered:** RDB-derived active/inactive using ≥15 working calendar days rule — rejected for current architecture.
- **Consequences for codebase:** `compliance.py` gates on `form_f1_records.is_active`. `formf1_parser.py` populates the table. FormF1 is per-resident per-month — not per posting code.
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

#### Decision: r_year = 'ALL' sentinel for 22 programmes
- **Status:** ✅ Confirmed
- **Decision:** 22 programmes with `r_year_required = false` use `r_year = 'ALL'` as a sentinel in `resident_postings`, `teaching_targets`, and `teaching_name_catalogue`. 6 programmes use actual r_year. 2 subspecialty programmes (SPORTSMED, PALLMED) remap R4→SS1, R5→SS2, R6→SS3.
- **Reasoning:** Most programmes do not differentiate teaching targets by residency year — all years share the same targets. The sentinel avoids duplicating target rows.
- **Alternatives considered:** NULL r_year — rejected because NULL complicates equality checks. Separate flag without sentinel — rejected, adds join complexity.
- **Consequences for codebase:** `r_year_matches()` function handles sentinel: `if target_r_year == 'ALL' or posting_r_year == 'ALL': return True`. All catalogue lookups must account for the sentinel.
- **Reference file and section:** `business-logic.md` § BL-11; `schema.md` § `programmes` seed data; `parsing.md` § R Year Handling
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: global_session_types exclusion priority over teaching_name_catalogue
- **Status:** ✅ Confirmed
- **Decision:** At compliance read time, before any `teaching_name_catalogue` lookup, check if `teaching_event.teaching_name` matches any active `global_session_types.name`. If matched → exclude from compliance entirely (both numerator and denominator). This check takes priority.
- **Reasoning:** Global session types (e.g. Department Meeting) should never count toward compliance regardless of whether a matching catalogue row exists.
- **Alternatives considered:** Checking after catalogue lookup — rejected, would allow accidental compliance counting if a global type name also appears in the catalogue.
- **Consequences for codebase:** `compliance.py` BL-6 step 5: global check before catalogue lookup. If matched, skip entirely — no catalogue join attempted.
- **Reference file and section:** `business-logic.md` § BL-6 step 5; `schema.md` § `global_session_types`; `AGENTS.md` confirmed decisions
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: ORTHO weekend mutation — read-time only
- **Status:** ✅ Confirmed
- **Decision:** ORTHO Saturday sessions of type `NHG Orthopaedic Surgery Residency Teaching [3h]` are mutated to `National Didactics & Department Teaching [1h]` at compliance read time via `weekend_exceptions.mutates_to_session_type_id` and `adjusted_duration_hours`. Raw attendance data is never modified in the DB.
- **Reasoning:** Consistent with R script (batch post-processing). Preserves raw data for audit. If ORTHO changes policy, update the `weekend_exceptions` row — no data migration needed.
- **Alternatives considered:** (A) Write mutation at submission time — rejected, corrupts raw data. (B) Read-time mutation (chosen). Both options documented in `AGENTS.md`.
- **Consequences for codebase:** `compliance.py` calls `is_weekend_accepted()` which returns `mutation_row`. When present, compliance engine uses mutated session type and duration instead of originals. `attendance_records` row unchanged.
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

#### Decision: Ad-hoc teaching submission uses catalogue-backed dropdown
- **Status:** ✅ Confirmed
- **Decision:** Native and external residents submit ad-hoc teachings through a date-first, catalogue-backed dropdown flow. Free-text teaching names must not drive compliance mapping.
- **Native resident flow:** Resident selects teaching date first. Backend derives posting from `resident_postings` for that date, then returns teaching options filtered by selected date, derived posting, resident programme, r_year, active/effectively active reporting period, and TTF Column K / `teaching_name_catalogue`.
- **External resident flow:** External resident selects teaching date first. Backend uses `external_residents.current_nhg_posting_code` unless date-specific external posting history through `external_resident_postings` is explicitly enabled later, then derives candidate host programme for the dropdown as documented in BL-12.
- **Submission fields:** `POST /resident/adhoc-teaching` creates `teaching_events` row (`is_adhoc = true`) and the relevant attendance row in the same transaction. It also stores planned `details_of_session` as display/audit-only free text with no operational or compliance use.
- **Ad-hoc event flags:** Ad-hoc teaching records must have `is_adhoc = true`, `cme_points_awarded = false`, and `smc_event_code = null`.
- **Frontend helper copy:** `Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.`
- **Reasoning:** Residents may attend teachings not pre-created by secretaries, but compliance mapping must remain controlled by TTF Column K and catalogue rows.
- **Alternatives considered:** Secretary-only event creation — rejected, too restrictive for resident workflow. Arbitrary free-text teaching names — rejected because they can break deterministic catalogue mapping.
- **Consequences for codebase:** Dedicated endpoint with PH validation, date-first posting derivation, catalogue-backed option lookup, optional display/audit detail capture, weekend exception check, and transaction wrapping event + attendance inserts.
- **Implementation status:** Planned rework for Phase 5A and 5B. Current models/migrations do not contain `details_of_session`.
- **Reference file and section:** `business-logic.md` § BL-9; `api.md` § POST `/resident/adhoc-teaching`
- **Do not change without PM/stakeholder approval:** Yes

---

#### Decision: External resident ad-hoc dropdown derives host programme from NHG posting
- **Status:** ✅ Confirmed requirement, planned implementation
- **Decision:** External residents should not manually select host programme by default. Backend should derive candidate `host_programme_code` from `external_residents.current_nhg_posting_code` for external ad-hoc dropdown options only.
- **Example:** `current_nhg_posting_code = KTPHDiagRd` derives host programme `DR` when the active/effectively active reporting period catalogue/targets map that posting to exactly one programme.
- **Preferred derivation source:** Active/effectively active reporting period `teaching_name_catalogue` / `teaching_targets`, or a future explicit posting-to-programme mapping if needed.
- **Edge cases:** Exactly one programme match defaults automatically. Multiple programme matches require explicit host programme selection. No programme match returns a clear unavailable-options response and must not guess.
- **R-year handling:** If the derived programme has `r_year_required = false`, use `r_year = 'ALL'`. If it has `r_year_required = true`, require external `host_r_year` selection before showing catalogue-backed options unless a later decision approves all-r-year option pooling.
- **Compliance guardrail:** Host programme derivation does not make external residents part of native NHG compliance, surplus, snapshots, clawback, or native reports.
- **Implementation status:** Planned endpoint/logic contract. Whether `host_programme_code` / `host_r_year` are persisted or calculated at read time is implementation-pending.
- **Reference file and section:** `schema.md` § `external_residents`; `api.md` § External Resident Endpoints; `business-logic.md` § BL-12
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

#### Decision: Clawback tab — 5th tab, generated by future final close/freeze
- **Status:** ✅ Confirmed
- **Decision:** Clawback is the 5th tab in admin/PC dashboard. Read-only. Generated by the future final close/freeze flow via `clawback_records` table (BL-10). All rows shown including suppressed (Extension, R7) with amount = 0.
- **Reasoning:** Senior management needs visibility into all compliance failures, even when no financial action follows.
- **Alternatives considered:** Separate clawback report page — rejected, integrated tab is more convenient.
- **Consequences for codebase:** Current reporting-period activate/deactivate routes do not generate `clawback_records`. A separate final close/freeze flow will generate them later. `GET /admin/reports/clawback` reads from that table. Suppressed rows included with `clawback_suppressed_reason` displayed.
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
- **Consequences for codebase:** Supabase Auth integration planned for Phase 2. RLS policies defined in `AGENTS.md`. Service role key server-only.
- **Reference file and section:** `AGENTS.md` § Tech Stack
- **Do not change without PM/stakeholder approval:** No (infra choice, not business rule)

---

#### Decision: Auth stub Phase 1; Supabase Auth Phase 2
- **Status:** ✅ Confirmed
- **Decision:** Phase 1 uses stub middleware reading role and identity from request headers. Phase 2 swaps to Supabase Auth with JWT. Only middleware changes — rest of the app unchanged.
- **Reasoning:** Allows rapid development without auth infrastructure. The header-based stub is simple to swap.
- **Alternatives considered:** Full auth from day 1 — rejected, slows initial development.
- **Consequences for codebase:** Middleware reads `X-User-Role`, `X-User-Id`, `X-User-Programme`, `X-User-Site`. All endpoints check these for authorization. Middleware swap is the only change for Phase 2.
- **Reference file and section:** `AGENTS.md` § Auth Stub; `api.md` § Authentication Model
- **Do not change without PM/stakeholder approval:** Yes (for Phase 2 timing)

---

#### Decision: Residents authenticate with MCR only — no password
- **Status:** ✅ Confirmed
- **Decision:** Residents authenticate with MCR number only. No password in Phase 1. This is an intentional design choice — no upgrade path planned.
- **Reasoning:** Residents are medical professionals with controlled MCR numbers. The system tracks attendance, not patient data. Low-friction login maximises adoption.
- **Alternatives considered:** Password-based auth — rejected for UX friction.
- **Consequences for codebase:** `POST /auth/login` with `role: 'resident'` accepts MCR only. Looks up `residents` table by MCR. Validates `status != 'inactive'`.
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

#### Decision: Non-tracked events seeded for visibility, excluded from compliance
- **Status:** ✅ Confirmed
- **Decision:** TTF rows with `Tracked? = "No"` are seeded into `teaching_name_catalogue` for event visibility. Attendance is stored normally but excluded from compliance numerator and denominator at read time.
- **Reasoning:** Residents should see these events and record attendance for audit purposes, even though they don't count toward compliance.
- **Alternatives considered:** Not seeding non-tracked rows — rejected, would make events invisible to residents.
- **Consequences for codebase:** `ttf_parser.py` seeds catalogue rows with `is_tracked = false`. `compliance.py` filters `WHERE is_tracked = true` when counting attendance.
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

#### Decision: Security — server-side enforcement, RLS at Phase 9
- **Status:** ✅ Confirmed
- **Decision:** All security checks enforced server-side. Frontend checks are UX only. RLS enabled on sensitive tables when Supabase Auth is integrated (Phase 9).
- **Reasoning:** Frontend code is client-controlled and cannot be trusted for security.
- **Alternatives considered:** None — standard security practice.
- **Consequences for codebase:** Every endpoint validates JWT and checks role + scope before DB operations. RLS policies defined in `AGENTS.md`. Admin operations spanning multiple residents use Supabase service role key.
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

#### TBD-MIGRATION: Historical Data Migration Strategy
- **Status:** ❓ Open — awaiting stakeholder decision
- **Description:** Three options for handling data from before the cutover period: (A) Archive only — legacy Excel files remain accessible, new system holds cutover-onwards only. (B) Summary migration — one-time script inserts summary-level compliance from legacy Excel. (C) Full migration — parse original FormSG CSVs and legacy `.rds` snapshots.
- **Why it matters:** Determines whether historical compliance reports are available in the new system.
- **Current placeholder logic:** None — no migration tooling exists.
- **File and section:** `business-logic.md` § TBD-MIGRATION
- **Who should answer:** PM / Programme Director / Senior Management
- **Can development proceed?** Yes — decision needed before the future final close/freeze workflow, not before development.
- **Mandatory instruction:** **Do NOT build migration tooling until option is confirmed. Add TODO: `# TBD-MIGRATION: awaiting stakeholder decision — archive/summary/full`**

---

### Resolved TBDs — Do NOT Reopen

---

#### TBD-1: Details of Training Keyword Matching (Mechanism)
- **Original question:** How should teaching events be matched to session types for compliance? The STP/Details of Training keywords were not available in the original system design.
- **Final decision:** `teaching_name_catalogue` table is the single source of truth. Seeded from TTF column K at upload time. One row per `(keyword, posting_code, programme_code, r_year, reporting_period_id)`. Session type resolved at compliance read time — never stored on `attendance_records`.
- **Consequences for codebase:** `ttf_parser.py` seeds `teaching_name_catalogue`. `compliance.py` joins via `keyword = teaching_event.teaching_name`. `PUT /admin/teaching-targets/{id}` re-seeds catalogue rows when `details_of_training` is updated.
- **File and section:** `business-logic.md` § BL-6; `schema.md` § `teaching_name_catalogue`; `parsing.md` § TTF Parser
- **Mandatory instruction:** Do NOT reopen. The mechanism is settled. Keyword data itself comes from TTF column K which the PC prepares.

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
- **Final decision:** Secretaries at both individual sites create events under their own posting codes. Compliance = total attended across both / total sessions from both combined.
- **Consequences for codebase:** Combined posting label must have its own TTF row. Compliance query unions events from both posting codes.
- **File and section:** `business-logic.md` § BL-8; `AGENTS.md` confirmed decisions
- **Mandatory instruction:** Do NOT reopen.

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
- **What replaced it:** Warn-on-reupload. Orphaned attendance returned as warnings in the upload response. Upload still returns 200.

---

#### ❌ STP upload / STP parser
- **What it was:** An endpoint and parser for uploading STP files directly to the system.
- **Why rejected:** STP lacks column K (Details of Training / keywords) which is mandatory for `teaching_name_catalogue` seeding. PC must manually add column K during STP→TTF conversion. Automating this conversion is not possible.
- **When it might become valid:** Only if the STP format is extended to include column K data — no current plans.
- **What replaced it:** TTF upload is the only teaching target upload path. PC manually converts STP → TTF.

---

#### ❌ LOA/Employed treatment via RDB-derived active/inactive logic
- **What it was:** Deriving active/inactive status from RDB posting phases using a ≥15 working calendar days rule.
- **Why rejected:** RDB posting phases use academic months (e.g. `08 Jul 25 - 03 Aug 25`) which don't align with calendar-month compliance targets. Creates date boundary inconsistencies.
- **When it might become valid:** Only if a separate future requirement explicitly changes the confirmed FormF1 decision.
- **What replaced it:** FormF1 active/inactive gate (`form_f1_records.is_active`), which uses calendar months aligned with compliance targets.

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
- **Where implemented:** `surplus.py` → `reallocate_by_tag()` function. Sort key is `row['tag']` (string sort).
- **Modifications:** TTF upload validator warns (not blocks) if alphabetical order doesn't align with duration descending.

---

#### KEEP: Clawback norm rate structure (R script F)
- **R script:** Script F — clawback calculation
- **What it does:** Applies per-r_year norm rates to compute clawback amounts. Separate rates for FM, IM, IM sub-specialties, and standard programmes.
- **Why retained:** The clawback calculation formula and rate structure are regulatory requirements.
- **Where implemented:** `clawback.py` → `compute_clawback()` function. See `business-logic.md` § BL-10.
- **Modifications:** Rates seeded from template rather than hardcoded. Suppression logic for Extension and R7 added.

---

#### KEEP: 70% compliance threshold and ceil() rounding
- **R script:** Script C — compliance calculation
- **What it does:** `target_70 = ceiling(target_100 * 0.70)` — uses ceiling function, matching R's `ceiling()`.
- **Why retained:** Regulatory requirement. `math.ceil()` in Python matches R's `ceiling()`.
- **Where implemented:** `compliance.py` → `posting_compliance()` function. See `business-logic.md` § BL-2.
- **Modifications:** None — identical logic.

---

#### KEEP: Session count capping (min of achieved vs target)
- **R script:** Script C — compliance calculation
- **What it does:** `achieved_and_counted = min(raw_achieved, target_100)` — caps achieved at 100% target.
- **Why retained:** Prevents over-counting when a resident exceeds the target for one session type from inflating overall compliance.
- **Where implemented:** `compliance.py` → `compute_achieved_and_counted()` function. See `business-logic.md` § BL-1.
- **Modifications:** None — identical logic.

> **⚠️ Most likely LLM mistake:** Porting R script logic not listed in this section — particularly the fuzzy string matching or CSV parsing logic. These are explicitly discarded in Section 4B. The silent consequence is fragile, redundant code that conflicts with the structured data model.

---

## Section 4B — Discarded R Script Logic (Full Audit)

### FormSG CSV Ingestion and Parsing (Script B)

| R Script Logic | What It Did | Why Discarded | Replaced By |
|---|---|---|---|
| FormSG CSV column detection via regex (`FORMSG01`–`FORMSG08` patterns) | Detected response columns by pattern because FormSG didn't guarantee stable positions | New system uses structured POST bodies | Pydantic request schemas |
| Date/timestamp format normalisation (dd-MMM-yy, dd/MM/yy, dd/MM/YYYY, etc.) | Parsed 6+ date formats from free-text submissions | Portal submits ISO-8601 | ISO-8601 `DATE` type in Pydantic |
| MCR extraction from free-text name string | Extracted MCR from "Name (MCR)" free-text format | Session-authenticated identity provides MCR directly | JWT `sub` → `residents.id` |
| Non-resident filtering via 'I am a' column | Filtered out non-resident FormSG submissions | Portal enforces auth role at login | `X-User-Role` middleware check |
| Consecutive teaching row duplication (`_consec2`, `_consec3` suffixes) | Duplicated rows for consecutive identical teachings in the same FormSG response | Each teaching event is a discrete DB record with its own `teaching_events.id` | `UNIQUE(resident_id, teaching_event_id)` constraint |
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

## Section 5 — Open Questions

### Business Rules

| # | Question | Why It Matters | Who Answers | Can Dev Proceed? |
|---|----------|---------------|-------------|-----------------|
| 1 | Active/inactive source (TBD-7 closed) | Gates compliance denominator for every resident | PM / Programme Director | Resolved — FormF1 is final authoritative source |
| 2 | TBD-MIGRATION: Archive only, summary, or full migration for historical data? | Determines whether historical reports available in new system | PM / Senior Management | Yes — decision needed before future final close/freeze |
| 3 | What is the exact list of clawback norm rates per r_year? | Required for BL-10 clawback calculation | PM / Finance | Yes — rates seeded from template, placeholder structure in place |
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
| 9 | What is the Supabase project URL and configuration? | Required for Phase 2 auth integration | DevOps / PM | Yes — not needed until Phase 2 |
| 10 | What is the Vercel deployment configuration for the frontend? | Required for production deployment | DevOps | Yes — not needed until deployment |

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

#### Ambiguity: FormF1 parser year suffix derivation
- **What:** The `parse_formf1()` sample code in `parsing.md` hardcodes `year_suffix = '25' if month_offset < 6 else '26'`. This is specific to AY2025 (Jul 2025 – Jun 2026) and will break for other reporting periods.
- **Which source to trust:** The logic is correct for AY2025 but must be made dynamic based on the reporting period's actual start date.
- **PM resolution needed?** No — developer should make dynamic. Flag as [Needs verification] for the exact derivation logic.

---

#### Ambiguity: teaching_name_catalogue keyword case sensitivity
- **What:** No explicit case-sensitivity rule stated in any document for `teaching_name_catalogue.keyword` matching. SQL default is case-sensitive.
- **Which source to trust:** Not specified. Developer should implement case-insensitive matching (e.g. `ILIKE` or `LOWER()`) to be safe, or confirm with PM.
- **PM resolution needed?** Recommended — case mismatch would silently exclude events from compliance.

> **⚠️ Most likely LLM mistake:** Assuming the FM Saturday exception still exists because `business-logic.md` § BL-FM describes it. The seed data in `schema.md` is authoritative — no FM row exists. The silent consequence is seeding a weekend exception that should not exist, causing FM Saturday sessions to incorrectly count toward compliance.

---

## Section 7 — Missing Context Audit

| # | What Is Missing | Why It Matters | Where Placeholder Is Used | Where to Update When Provided |
|---|----------------|---------------|--------------------------|-------------------------------|
| 1 | Active/inactive source lock (TBD-7 closed) | Gates compliance denominator | `compliance.py` — gate on `form_f1_records.is_active` | Keep FormF1 path authoritative |
| 2 | TBD-MIGRATION option selection | Determines historical data availability | No code exists — placeholder TODO only | New migration script(s) when option confirmed |
| 3 | Clawback norm rates per r_year | Required for BL-10 calculation amounts | `clawback.py` — rate lookup structure in place, actual rates need seeding | `clawback.py` → `norm_rates` and `norm_rates_fm` dicts |
| 4 | Exact `teaching_name_catalogue` keyword case-sensitivity rule | Determines whether "Journal Club" matches "journal club" | Not specified — developer must choose | `compliance.py` and `ttf_parser.py` — matching query |
| 5 | FormF1 year suffix dynamic derivation | Hardcoded '25'/'26' will break for non-AY2025 periods | `formf1_parser.py` sample code | `formf1_parser.py` — derive from `reporting_periods.start_date` |
| 6 | Actual implementation status of codebase | Source-of-truth files are design specs | This document marks all components as 📋 Planned | Verify against actual codebase and update Section 3 of `00_project_context.md` |

> **⚠️ Most likely LLM mistake:** Assuming the clawback norm rates are already seeded because `business-logic.md` shows the calculation formula. The formula structure exists; the actual rate values are placeholders. The silent consequence is zero or wrong clawback amounts.

---

## Section 8 — High-Risk Blind Spots

These are implementation errors that would fail silently — no exception thrown, wrong data produced.

---

#### ⚠️ Blind Spot 1: Using `residents.r_year` instead of `resident_postings.r_year`
- **Where:** `compliance.py` — any join to `teaching_targets`
- **Silent consequence:** Wrong `teaching_targets` row matched for residents who cross a year boundary mid-period. Wrong compliance target applied. Wrong percentage. Wrong traffic light. No error thrown.
- **How to detect:** Unit test: create a resident with R2 posting in months 1–3 and R3 posting in months 4–6. Verify that month-1 attendance matches R2 targets and month-4 attendance matches R3 targets.

---

#### ⚠️ Blind Spot 2: Writing reallocated surplus values to `surplus_ledger`
- **Where:** `surplus.py` — after `reallocate_by_tag()` returns
- **Silent consequence:** Next compliance read double-counts the reallocation. Audit trail corrupted. Surplus values grow unboundedly over multiple reads.
- **How to detect:** Integration test: run compliance calculation twice. Verify `surplus_ledger` values are identical both times (pre-reallocation). Verify reallocated values only exist in the response, not in DB.

---

#### ⚠️ Blind Spot 3: 70% threshold at session-type level instead of posting level
- **Where:** `compliance.py` — `posting_compliance()` function
- **Silent consequence:** Wrong traffic light colours for every resident. A resident could be green per session type but red at posting level, or vice versa.
- **How to detect:** Unit test: create a resident with 2 session types at one posting. Set achieved high for type A and low for type B. Verify threshold is applied to the sum, not per type.

---

#### ⚠️ Blind Spot 4: Using `teaching_events.session_type_id` for compliance
- **Where:** `compliance.py` — attendance counting logic
- **Silent consequence:** Cross-programme residents get wrong session type. Session type doesn't update when TTF is re-uploaded. Compliance percentages are stale.
- **How to detect:** Integration test: create an event at a posting shared by two programmes with different TTF mappings. Submit attendance from residents of both programmes. Verify each gets the correct session type from their own programme's catalogue.

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

#### ⚠️ Blind Spot 9: Skipping `global_session_types` check before catalogue lookup
- **Where:** `compliance.py` — BL-6 step 5
- **Silent consequence:** Events matching global session types (e.g. Department Meeting) feed compliance numbers when they should be excluded. Inflates both numerator and denominator.
- **How to detect:** Unit test: create a "Department Meeting [1h]" event. Submit attendance. Verify it is excluded from compliance numerator AND denominator.

---

#### ⚠️ Blind Spot 10: Using actual `r_year` instead of `'ALL'` for 22 programmes
- **Where:** `compliance.py` — `teaching_name_catalogue` lookup; `ttf_parser.py` — target insertion
- **Silent consequence:** Catalogue lookup returns zero results for 22 programmes. All compliance percentages show 0%. No error thrown.
- **How to detect:** Unit test: create a GERI (r_year_required = false) resident with R3. Upload TTF with `r_year = 'ALL'`. Verify catalogue lookup succeeds.

---

#### ⚠️ Blind Spot 11: Calculating compliance independently for grouped postings
- **Where:** `compliance.py` — active_months and target_100 calculation
- **Silent consequence:** Wrong compliance for postings in `posting_groups`. Active months not pooled across group. Target_100 computed per posting instead of across group.
- **How to detect:** Integration test: create a RESPI resident posted at `TTSHRespi` (3 months) and `TTSHRespi(MICU)` (2 months), both in group `TTSHRespi`. Verify `active_months = 5` (pooled), not calculated as two separate 3-month and 2-month postings.

---

#### ⚠️ Blind Spot 12: Ignoring `form_f1_records.is_active` gate
- **Where:** `compliance.py` — active_months counting
- **Silent consequence:** Inactive months included in denominator. Active_months inflated. Compliance percentages deflated for all residents with inactive months.
- **How to detect:** Unit test: set a resident as Inactive for 2 of 6 months in FormF1. Verify `active_months = 4`, not 6. Verify attendance in inactive months excluded from numerator.

---

#### ⚠️ Blind Spot 13: Writing ORTHO mutation to DB
- **Where:** `compliance.py` or attendance submission endpoint
- **Silent consequence:** Raw attendance data corrupted. Original session type and duration lost. If ORTHO changes policy, data migration needed instead of simple config change.
- **How to detect:** Integration test: submit ORTHO Saturday attendance. Verify `attendance_records` row retains original session type. Verify compliance read returns mutated type. Verify DB row unchanged.

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

| # | Rule / Decision | Why It Must Not Change | Who Approves | Where Implemented |
|---|----------------|----------------------|-------------|-------------------|
| 1 | 70% compliance threshold | Regulatory requirement | PM / Programme Director | `compliance.py` → `posting_compliance()` |
| 2 | Session counts as compliance unit (not hours) | Regulatory framework | PM / Programme Director | `compliance.py` — all counting logic |
| 3 | Surplus resets at period boundary | PM-confirmed policy | PM | `surplus.py` — future final close/freeze surplus hibernation logic |
| 4 | Tag-based reallocation sort: alphabetical by tag label | Matches R script; PC convention | PM | `surplus.py` → `reallocate_by_tag()` |
| 5 | Reallocation is read-time only | Audit trail integrity | PM | `surplus.py` — never write back |
| 6 | FormF1 as final active/inactive source | TBD-7 resolved | PM / Programme Director | `compliance.py` — `form_f1_records.is_active` gate |
| 7 | `r_year = 'ALL'` sentinel for 22 programmes | Programme configuration | PM | `rdb_parser.py`, `ttf_parser.py`, `compliance.py` |
| 8 | `teaching_events.session_type_id` is display only | Cross-programme correctness | PM | Schema design; `compliance.py` ignores it |
| 9 | TTF re-upload: warn, not 422 | PC workflow requirement | PM | `ttf_parser.py` — orphan detection |
| 10 | Public holiday hard block (422) | Operational policy | PM | Event creation endpoints |
| 11 | Posting codes from table only | Data integrity | PM | All code referencing posting codes |
| 12 | Resident visibility gated by RDB upload | Logical necessity | PM | `GET /resident/events` |
| 13 | `global_session_types` exclusion priority | Compliance correctness | PM | `compliance.py` BL-6 step 5 |
| 14 | ORTHO mutation read-time only | Audit trail integrity | PM | `compliance.py` weekend exception handling |
| 15 | `posting_groups` aggregation | Compliance correctness for grouped postings | PM | `compliance.py` group aggregation |
| 16 | FM uses standard engine — no variant | R script audit confirmed | PM | `compliance.py` — no FM branch |
| 17 | FM Saturday exception removed | PC confirmation | PM | `weekend_exceptions` seed data |
| 18 | Hard legacy cutover | Operational decision | PM / Senior Management | System architecture |
| 19 | Clawback tab: 5th tab, generated by future final close/freeze workflow | Reporting requirement | PM | `clawback.py`, admin dashboard |
| 20 | Ad-hoc teaching same compliance treatment, with catalogue-backed dropdown and no arbitrary free-text mapping | Policy decision | PM | `compliance.py` — no `is_adhoc` filter; BL-9 |
| 21 | MCR-only resident auth (no password) | Intentional design choice | PM | `POST /auth/login` resident path |
| 22 | Admin programme scope (TEXT[]) | Access control policy | PM | `users.programme_scope` |
| 23 | Non-tracked events seeded for visibility | Event visibility policy | PM | `ttf_parser.py` — catalogue seeding |
| 24 | Duration embedded in session type name [Xh] | TTF format convention | PM | `parsing.md` — no separate column |
| 25 | `posting_groups` independent from `multi_posting_rules` | Architectural separation | PM | Separate tables, separate usage contexts |
| 26 | Weekend submission: stored + warning | Resident transparency policy | PM | `POST /resident/attendance` response |
| 27 | Clawback suppressed rows shown (Extension, R7) | Senior management visibility | PM | `clawback_records` — all rows displayed |
| 28 | AY month bucketing via `academic_month_boundaries` + `programmes.ay_date_category` (ignore SR/SRs header wording) | Compliance month assignment correctness and parser stability across workbook header drift | PM / Programme Director | `parsing.md` AY Dates parser; `schema.md` programme/category + boundary tables; `business-logic.md` BL-5A |
| 29 | External/cross-cluster residents workflow is Phase 5B before compliance, excluded from NHG compliance/clawback, and Excel-exportable for forwarding | Prevents accidental inclusion in NHG denominator/numerator and establishes forwarding workflow before Phase 6 | PM / Programme Director | External resident auth/submission/export design |
| 30 | Master admin must be explicit; never inferred from `programme_scope = NULL` | Access-control correctness and least-privilege integrity | PM / Security owner | `users` auth model and admin endpoint guards |
| 31 | TTSH pilot visibility: non-TTSH postings use ad-hoc-only path when secretary list is unavailable | Preserves pilot operations without blocking attendance capture | PM / Programme Director | Future resident event visibility logic |
| 32 | Bulk TTF upload deferred; one-programme-at-a-time remains current workflow | Avoids premature high-risk parser/mapping complexity | PM | Existing `POST /admin/upload/ttf` scope flow |
| 33 | Latest uploaded TTF export/email deferred to end-of-roadmap and staged | Prevents premature storage/email coupling before core stabilization | PM / IT | Future admin productivity module |
| 34 | Programme PC teaching event CRUD is roadmap item `4B` before compliance; PC-created scheduled events are programme-owned | Lets PCs seed/manage programme teachings before compliance while preserving secretary programme-neutral event model | PM / Programme Director | Planned admin programme-teaching endpoints; planned `teaching_events.created_for_programme_code` |
| 35 | External ad-hoc dropdown derives host programme from current NHG posting where possible, e.g. `KTPHDiagRd -> DR` | Removes unnecessary manual host-programme selection while keeping ambiguous/no-match cases explicit | PM / Programme Director | External ad-hoc option endpoint; BL-12 |

> **⚠️ Most likely LLM mistake:** Changing the 70% threshold to 75% or 65% because it "seems more reasonable." The threshold is a regulatory requirement. The silent consequence is every compliance calculation being wrong for every resident.

---
