# Phase 5B-H AUD-M-04 — Atomic Attendance and Ad-hoc Ownership

## Scope

This change closes AUD-M-04 and records the transaction boundary for every
implemented teaching-event and attendance mutation. In this application an
attendance row is also the submission record: there is no separate submission,
workflow, version, correction, or approval table.

The implemented attendance states are `submitted`, `flagged`, and `removed`.
Resident endpoints create `submitted` rows and transition them to `removed`.
They do not expose attendance edit, replacement, finalisation, administrative
correction, or hard-delete operations. A resubmission creates a new
`submitted` row and preserves the removed row and its identifier.

Uploads, warning actions, and Data Revalidation do not create, edit, remove, or
resubmit attendance. They are therefore not attendance bulk-mutation units.
`POST /resident/attendance` is the only attendance batch mutation and the
entire explicit `event_ids` request is its atomic unit.

## Immutable ad-hoc ownership

`teaching_events` stores two typed, nullable creator foreign keys:

- `created_by_resident_id -> residents.id`
- `created_by_external_resident_id -> external_residents.id`

Scheduled events have neither value. A resident-created ad-hoc event has
exactly one value, and it must agree with `created_by_role`:

- `resident` uses only `created_by_resident_id`;
- `external_resident` uses only
  `created_by_external_resident_id`.

The event kind, creator role, and creator foreign keys are immutable.
Attendance subject/event identifiers and their storage family are immutable,
and a removed row cannot be resurrected in place. Native and Non-NHG active
same-event uniqueness is enforced independently with submitted-only unique
indexes.

The API never accepts a creator identifier, creator role, or storage-family
selector. The narrow PostgreSQL ad-hoc creation function derives subject type
and identifier from the verified transaction-local request context, validates
the existing posting/catalogue authority, and inserts exactly one event plus
the matching native or external attendance row in the caller's transaction.
It does not commit.

## RLS and helper boundary

PostgreSQL enforces all of the following independently of FastAPI:

- a native Resident sees and updates only their own native ad-hoc association;
- a Non-NHG Resident sees and updates only their own external ad-hoc
  association;
- another Resident's ad-hoc event is not reusable;
- the native family cannot attach to an external-owned ad-hoc event;
- the external family cannot attach to a native-owned ad-hoc event;
- ordinary table INSERT policies accept scheduled attendance only;
- ordinary `teaching_events` INSERT policies reject resident ad-hoc creation;
- the dedicated ad-hoc function is executable by `mata_app_runtime` only;
- `mata_auth_internal`, PUBLIC, `anon`, `authenticated`, and `service_role`
  receive no execution right.

The helper is `SECURITY DEFINER`, owned by the reviewed dedicated
`mata_adhoc_attendance_definer` `NOLOGIN` role, has a fixed safe `search_path`,
accepts no subject identifier or table name, and returns only the created
event and attendance identifiers. That `NOINHERIT`, non-superuser,
`BYPASSRLS` definer has no memberships and only the exact schema, table,
context-accessor, and UUID-generation privileges required by this helper.
Downgrade revokes those object privileges and retains the empty cluster role.
Scheduled-event visibility and staff programme/posting scope remain unchanged.

Runtime-origin attendance inserts are database-normalised to `submitted`, the
event posting, and transaction timestamps. Runtime updates cannot retarget
identity, event, posting, or creation/submission evidence and permit only
`submitted -> removed`; the database owns the removal timestamp. These
trigger checks apply to both attendance families, including ordinary
scheduled-event writes.

## Transaction and concurrency matrix

| Operation | Entry point / affected rows | Transaction owner | Locks and constraints | Audit evidence | Rollback and family rule |
|---|---|---|---|---|---|
| Scheduled attendance creation / submission | `POST /resident/attendance`; one family attendance table | `resident_submission.submit_attendance`; one commit for the full `event_ids` batch | Deterministic transaction-scoped event advisory locks shared with staff mutation paths; subject/date advisory locks; active same-event unique index; overlap recheck | Database-owned creation/submission timestamps | Any rejected item or commit failure rolls back the whole batch. Native and external tables are selected from trusted subject type. |
| Ad-hoc event plus attendance creation | `POST /resident/adhoc-teaching`; `teaching_events` plus one family attendance table | `resident_submission.submit_adhoc_teaching`; the PostgreSQL helper does not commit | Subject/date advisory lock; strict helper identity derivation; creator/FK/family constraints | Immutable event ownership plus attendance row | A validation, event insert, attendance insert, or commit failure leaves neither row. |
| Attendance removal / withdrawal | `DELETE /resident/attendance/{id}`; one attendance row | Resident submission service | Event and subject/date advisory locks; locked current attendance row; conditional `submitted -> removed` update | Preserved row identifier and creation/submission timestamps; database-owned `updated_at` | Failure leaves the submitted row unchanged. An old removed identifier cannot remove a later resubmission. |
| Resubmission | `POST /resident/attendance`; new active attendance row | Resident submission service | Same locks as submission; submitted-only uniqueness | Prior removed row plus new submitted row | Failure preserves prior history and creates no active row. |
| Secretary scheduled event creation / duplicate | Secretary event routes; `teaching_events` plus `audit_logs` | Secretary route orchestration | Existing scope, catalogue, holiday, and duplicate validation | Existing Secretary event audit entry | Event and audit commit once; either both persist or neither persists. |
| Secretary series creation | Secretary series route; `event_series`, child `teaching_events`, `audit_logs` | Secretary route orchestration | One request transaction and existing recurrence validation | Existing Secretary series audit entry | Series metadata, every occurrence, and audit are all-or-nothing. |
| Secretary event edit | Secretary event route; `teaching_events`, `audit_logs` | Secretary route orchestration | Shared event advisory lock, then event `FOR UPDATE`; any linked attendance blocks with `409` | Existing Secretary event audit entry | Audit/commit failure preserves the complete pre-edit row. |
| Secretary event/series deletion | Secretary routes; scheduled event/series rows plus `audit_logs` | Secretary route orchestration | Sorted event advisory locks, then deterministic `FOR UPDATE` row locks; any linked attendance status blocks | Existing Secretary deletion audit entry | Rows and audit are deleted/written together or all remain unchanged. |
| Programme PC scheduled event creation / duplicate | Programme event service; `teaching_events` | Programme event service | Existing scope, catalogue, holiday, and duplicate validation | No separate audit row is defined by the current contract | The single business mutation commits once. |
| Programme PC event edit/delete | Programme event service; `teaching_events` | Programme event service | Shared event advisory lock, then event `FOR UPDATE`; any linked native/external attendance blocks with `409` | No separate audit row is defined by the current contract | Failure preserves the event. |
| Master force delete | Admin force-delete service; both attendance tables, one scheduled event, `audit_logs` | `admin_secretary_events.force_delete_event` | Shared event advisory lock, then event `FOR UPDATE`; all-status confirmation counts; FK checks | `admin.teaching_event.force_delete` | Attendance, event, and audit share the existing single transaction and explicit rollback. Ad-hoc events remain ineligible. |
| Attendance edit or replacement | Not implemented | N/A | N/A | N/A | No API or service mutation exists. |
| Resident ad-hoc event edit/delete | Not implemented | N/A | Immutable creator evidence still applies | N/A | No API or service mutation exists. |
| Administrative attendance correction | Read-only admin attendance/submission surfaces | N/A | N/A | N/A | No attendance mutation exists. |
| Data Revalidation and warning actions | Impact/reporting or warning tables only | Their existing operation owner | No attendance writes | Their existing audit contract | Not an attendance/submission transaction. |
| Uploads | Parser-owned domain replacement; no attendance writes | Existing upload contract | TTF may report orphan attendance but does not mutate it | Existing upload evidence | Not an attendance/submission bulk operation. |

Every path that submits/removes attendance or mutates an existing event first
takes the same transaction-scoped advisory key derived from the trusted event
UUID. Batch and series keys are acquired in sorted order. Staff mutation then
takes its `FOR UPDATE` row lock, while Resident paths remain least-privilege and
do not require an event UPDATE policy merely to serialize. Native and external
submission/removal also use the same subject/date advisory-lock namespace
within each family. This makes concurrent submit/remove and submit/event-edit
pairs resolve to one committed order and prevents two distinct overlapping
submissions for the same subject/date.

## Migration and populated-data rule

Revision `20260728_000028` follows `20260727_000027`.

Upgrade backfills an ad-hoc creator only when all historical attendance rows
prove exactly one same-family subject and `created_by_role` agrees:

- native role, one distinct native subject, and no external subject; or
- external role, one distinct external subject, and no native subject.

It counts distinct subjects across every status, not attendance rows. The
migration aborts rather than guessing when an ad-hoc event is orphaned,
multi-subject, mixed-family, or role-mismatched. It never chooses the earliest
or latest row, deletes evidence, changes an event to scheduled, or silently
quarantines ambiguous history.

Downgrade restores the revision-000027 policies and schema. It refuses a
downgrade when preserved native resubmission history cannot satisfy the former
full `(resident_id, teaching_event_id)` uniqueness rule.

## Assurance status

Local verification covers focused transaction ownership, resident service and
router behavior, direct native/external RLS matrices, real-PostgreSQL rollback
and concurrency, migration lifecycle, exact helper/grant catalogues, security
source scans, one-head topology, and diff hygiene. Deployment verification is
still required on an explicitly approved target; this work does not access or
mutate live Supabase or Vercel.

The unrelated production assurance blocker remains:

`PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED`
