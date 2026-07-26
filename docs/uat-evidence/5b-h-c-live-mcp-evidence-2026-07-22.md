# Phase 5B-H-C live Vercel and Supabase evidence

> **Historical evidence boundary — 2026-07-22:** This document is a point-in-time Phase 5B-H-C record. Its commit identifiers, migration revision, test counts, live observations, and `BLOCKED` / `MANUAL VERIFICATION REQUIRED` results must remain unchanged. Phase 5B-H-D later replaced the browser-bearer transport described here; current implementation and local verification evidence is recorded in `docs/5b_h_d_production_security_implementation.md`. That later local evidence does not retroactively change any deployed result in this document.

Execution date: 2026-07-22

Environment: MATA UAT/staging

Method: read-only Vercel and Supabase MCP inspection, safe token-free HTTP probes, and repository correlation

# Verdict

**LIVE EVIDENCE PARTIAL — BLOCKED ITEMS REMAIN**

No live FAIL was found. The current production deployments are healthy and use the current `main` revision; the database revision, required schema, seed/config aggregates, staff-bootstrap aggregates, and protected-UAT grant boundary match the expected state. Stakeholder UAT sign-off remains unavailable because deployment-protection settings, deployed environment metadata, Data API settings, the direct public-key denial test, and approved synthetic role fixtures could not be verified safely through the connected read-only tools.

No deployment, setting, environment, Auth, grant, policy, schema, migration, or application-data mutation was performed. No secret value or personal row was retrieved.

# Git baseline

The Git gate passed before live inspection and before this evidence branch was created.

| Item | Evidence | Result |
|---|---|---|
| Starting branch | `main`, clean, tracking `origin/main` | PASS |
| Fetch | `git fetch --prune origin` completed | PASS |
| Ahead/behind | `0 0` | PASS |
| Current `main` | `8474314093235d7bf16ad08da938d1e20b3ee423` | PASS |
| `origin/main` | `8474314093235d7bf16ad08da938d1e20b3ee423` | PASS |
| Frontend deployed revision | `8474314093235d7bf16ad08da938d1e20b3ee423` | PASS — deployed |
| Backend deployed revision | `8474314093235d7bf16ad08da938d1e20b3ee423` | PASS — deployed |

Evidence collection was then placed on `CL/5b-h-c-live-mcp-evidence`. No historical audit document was edited.

# Vercel evidence

## Project and deployment identity

| Layer | Project | Production domain | Latest production deployment | Created | Status | Source | Region/runtime | Classification |
|---|---|---|---|---|---|---|---|---|
| Frontend | `mata-aine` | `https://mata-aine.vercel.app` | `dpl_3Vk8bFGG3xwa9mce4QV4Ph5mBF5J` | `2026-07-22T06:38:17Z` (`14:38:17` SGT) | `READY` | `main` at `8474314093235d7bf16ad08da938d1e20b3ee423` | `iad1`; Lambda deployment; project Node setting 24.x | PASS — current main deployed |
| Backend | `mata-backend` | `https://mata-backend.vercel.app` | `dpl_LW3U9x7N3RcChWtLmsNffNPsyDdr` | `2026-07-22T06:38:16.998Z` (`14:38:16.998` SGT) | `READY` | `main` at `8474314093235d7bf16ad08da938d1e20b3ee423` | `hnd1`; one Python Lambda reported; project Node setting 24.x | PASS — current main deployed |

Both deployed revisions equal current `main`. The required explicit-master upload fix and distinct-event overlap/advisory-lock fix are ancestors of and therefore included in both deployments.

## Deployment history and runtime errors

- PASS — no failed deployment was found for either project in the inspected seven-day window; the inspected deployments were `READY`.
- PASS — deployed: runtime-error cluster count since the latest frontend deployment was zero.
- PASS — deployed: runtime-error cluster count since the latest backend deployment was zero.
- Historical backend evidence retained: 33 `ProgrammingError` occurrences, last seen `2026-07-21T07:26:23Z`, and 6 `IntegrityError` occurrences, last seen `2026-07-20T05:55:12Z`, all before the current deployment. This is not evidence of a current-release error cluster.

## Deployment protection

- MANUAL VERIFICATION REQUIRED — the connected Vercel surfaces did not expose production or preview protection configuration, gate method, or stakeholder access-list state for either project.
- The frontend root returned a Vercel Security Checkpoint response to automation. That bot challenge is not treated as proof of an intentional stakeholder access gate.
- The backend health route was directly reachable, while a protected application route returned a controlled unauthenticated response. This confirms application authentication behavior for that route, not the project-level stakeholder gate.

## Environment-name and safe-mode review

- MANUAL VERIFICATION REQUIRED — Vercel MCP did not expose deployed environment-variable names or values. Consequently, deployed presence of the required frontend names `VITE_AUTH_MODE`, `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, and the supported public-key name could not be confirmed.
- MANUAL VERIFICATION REQUIRED — deployed frontend mode `supabase` could not be read safely.
- PASS — repository/build: tracked frontend source contains the expected public configuration names and contains no frontend occurrence of backend-only names or forbidden `VITE_` variants from the checklist.
- MANUAL VERIFICATION REQUIRED — deployed presence of backend names `ENV`, `AUTH_MODE`, `DATABASE_URL`, `SYNC_DATABASE_URL`, `SUPABASE_URL`, the JWKS or issuer name, the audience name, the supported public-key name, `SUPABASE_SERVICE_ROLE_KEY`, `MATA_RESIDENT_SESSION_SECRET`, and `CORS_ORIGINS` could not be inspected. Secret values were neither requested nor retrieved.
- MANUAL VERIFICATION REQUIRED — deployed safe modes `production`, `supabase`, and audience `authenticated` remain operator checks.
- MANUAL VERIFICATION REQUIRED — exact configured `CORS_ORIGINS` membership was unavailable. The runtime behavior for the approved and rejected origins passed, but cannot rule out an additional configured origin.

## Safe deployed HTTP checks

| Check | Safe result | Classification |
|---|---|---|
| `GET /health` | `200`; small JSON response containing only a `status` field | PASS — deployed |
| `GET /api/v1/auth/me` without credentials | controlled `401`; no SQL, stack, path, environment, token, or secret markers | PASS — deployed |
| Approved-origin preflight | `200`; exact allow-origin `https://mata-aine.vercel.app`; credentials allowed; no wildcard | PASS — deployed |
| Unapproved-origin preflight | `https://unapproved.example` returned `400` with no allow-origin header | PASS — deployed |
| Local-development-origin preflight | `http://localhost:5173` returned `400` with no allow-origin header | PASS — deployed |
| Preview-origin preflight | representative unapproved preview hostname returned `400` with no allow-origin header | PASS — deployed |
| Required security headers | HSTS, CSP, frame denial, content-type sniffing denial, and strict-origin referrer policy present | PASS — deployed |
| Current deployed 5xx body | no safe non-mutating 5xx fixture was available | MANUAL VERIFICATION REQUIRED |

# Supabase identity

| Item | Safe metadata | Result |
|---|---|---|
| Project reference | `aamnpyecwlorcxvfmbxh` | PASS |
| Approved UAT reference | `aamnpyecwlorcxvfmbxh` | PASS — exact match |
| Project name | not exposed by the project-scoped MCP endpoint | NOT APPLICABLE — absence is not an identity blocker |
| Organization/project label | project-scoped endpoint for the approved reference; account-management label not exposed | NOT APPLICABLE |
| Read-only flag | `true` in configured URL metadata | PASS |
| Feature groups | `database`, `debugging`, `docs` | PASS |
| Target confirmation | configured reference exactly matched the operator-approved UAT reference before database queries resumed | PASS — read-only Supabase metadata |

Only the allowed metadata tools were used. No migration or mutation tool was invoked.

# Migration and schema

## Migration revision

- PASS — read-only Supabase metadata: `public.alembic_version` contained exactly one revision, `20260721_000022`.
- PASS — repository: `python -B -m alembic heads` reported exactly `20260721_000022 (head)`.
- The Supabase-native migration list had no entries; Alembic metadata is authoritative for this application.
- PASS — `pgcrypto` 1.3 is installed.

## Required tables

PASS — all 25 required public tables exist:

`users`, `residents`, `resident_postings`, `attendance_records`, `external_residents`, `external_resident_postings`, `external_attendance_records`, `teaching_events`, `teaching_targets`, `teaching_name_catalogue`, `form_f1_records`, `programme_institution_posting_map`, `upload_logs`, `warning_issues`, `upload_warnings`, `audit_logs`, `programmes`, `posting_codes`, `reporting_periods`, `public_holidays`, `academic_month_boundaries`, `global_session_types`, `weekend_exceptions`, `multi_posting_rules`, and `posting_groups`.

No application rows were returned by the table-existence check.

## Required and forbidden columns

| Table.column | Live type | Nullable | Result |
|---|---|---:|---|
| `users.admin_level` | `varchar` | No | PASS |
| `users.supabase_user_id` | `uuid` | Yes | PASS |
| `programmes.native_teaching_posting_code` | `varchar` | Yes | PASS |
| `external_resident_postings.programme_code` | `varchar` | Yes | PASS |
| `teaching_events.created_for_programme_code` | `varchar` | Yes | PASS |
| `resident_postings.r_year` | `varchar` | No | PASS |
| `resident_postings.active_months_weight` | `numeric` | No | PASS |
| `resident_postings.day_part` | `varchar` | Yes | PASS |
| `programmes.compliance_variant` | absent | — | PASS |
| `attendance_records.session_type_id` | absent | — | PASS |

## Constraints and indexes

- PASS — `users.supabase_user_id` has `UNIQUE (supabase_user_id)`.
- PASS — `users.admin_level` is constrained to the explicit values `programme` and `master`.
- PASS — attendance duplicate protection is `UNIQUE (resident_id, teaching_event_id)`.
- PASS — external posting and attendance foreign keys reference only their external-resident owner tables plus the required posting, programme, and teaching-event parents.
- PASS — programme/institution mappings have `UNIQUE (programme_code, institution_code)` and an active-row check requiring a non-null `posting_code`.
- PASS — required external scope/date indexes and submitted-event partial unique indexes exist.
- PASS — one Alembic head only; no unexpected head was found.

# Seed/config evidence

All checks in this section used aggregate-only metadata queries; no resident or attendance row was returned.

| Check | Live aggregate | Expected | Result |
|---|---:|---:|---|
| Programmes | 28 | 28 | PASS |
| LOA types | 14 | 14 | PASS |
| Active global session types | 1 | required named type present | PASS |
| TTSH active mappings | 24 | 24 | PASS |
| TTSH inactive mappings | 4 | 4 | PASS |
| TTSH pending mappings | 0 | 0 | PASS |
| Active TTSH mappings with null posting | 0 | 0 | PASS |
| Reporting periods | 1 | present | PASS |
| Posting codes | 218 | present | PASS |

The active global session type is `Department Meeting [1h]`. The four inactive TTSH programme codes are exactly `FM`, `PATH`, `SPORTSMED`, and `PALLMED`.

Weekend-exception metadata passed: `DERM` has one Saturday row, `ORTHO` has one Saturday row, `URO` has two Saturday rows, and `FM` has zero rows.

# Auth/bootstrap metadata

These checks returned counts only; no staff identity, name, contact field, or person UUID was returned.

| Check | Live aggregate | Result |
|---|---:|---|
| Active explicit Master Admin rows | 2 | PASS |
| Active staff rows missing Supabase mapping | 0 | PASS |
| Active Programme PC rows with invalid scope | 0 | PASS |
| Active Secretary rows with invalid posting scope | 0 | PASS |
| Duplicate non-null Supabase mapping groups | 0 | PASS |

Master authority is explicitly represented by `role = admin` and `admin_level = master`; it was not inferred from an empty programme scope.

# RLS, grants, and Data API

## Sensitive-table posture

Exact catalog checks found no table privilege for `PUBLIC`, `anon`, or `authenticated` on any sensitive table. All listed tables had no policies. RLS was enabled only on `users`; forced RLS was disabled on every listed table.

| Sensitive table | RLS enabled | RLS forced | Policies | Public/browser-role privileges | Classification |
|---|---:|---:|---|---|---|
| `users` | Yes | No | None | None | PASS — no browser-public read path |
| `residents` | No | No | None | None | PASS — no browser-public read path |
| `resident_postings` | No | No | None | None | PASS — no browser-public read path |
| `attendance_records` | No | No | None | None | PASS — no browser-public read path |
| `external_residents` | No | No | None | None | PASS — no browser-public read path |
| `external_resident_postings` | No | No | None | None | PASS — no browser-public read path |
| `external_attendance_records` | No | No | None | None | PASS — no browser-public read path |
| `form_f1_records` | No | No | None | None | PASS — no browser-public read path |
| `teaching_targets` | No | No | None | None | PASS — no browser-public read path |
| `teaching_name_catalogue` | No | No | None | None | PASS — no browser-public read path |
| `upload_logs` | No | No | None | None | PASS — no browser-public read path |
| `warning_issues` | No | No | None | None | PASS — no browser-public read path |
| `upload_warnings` | No | No | None | None | PASS — no browser-public read path |
| `audit_logs` | No | No | None | None | PASS — no browser-public read path |

This PASS is specific to the present protected-UAT grant boundary. It does not claim that the deferred full RLS-policy model is complete. The browser roles can use the `public` schema, but neither role is a superuser or an RLS-bypass role.

## Data API and advisors

- MANUAL VERIFICATION REQUIRED — exposed-schema and API settings were not visible through the read-only database metadata session.
- MANUAL VERIFICATION REQUIRED — DIRECT PUBLIC-KEY DENIAL TEST NOT EXECUTED. No approved safe public-key tool was available.
- INFO, `SECURITY / policy review`, `RLS Enabled No Policy`: `academic_month_boundaries`, `alembic_version`, `event_series`, `global_session_types`, `loa_types`, `multi_posting_rules`, `posting_codes`, `posting_groups`, `programmes`, `public_holidays`, `rate_limit_buckets`, `reporting_periods`, `secretary_programme_pools`, `session_types`, `users`, and `weekend_exceptions`.
- CRITICAL, `SECURITY / RLS-policy review`, `Row Level Security is disabled`: `residents`, `teaching_name_catalogue`, `teaching_targets`, `clawback_records`, `period_snapshots`, `resident_postings`, `surplus_ledger`, `teaching_events`, `upload_logs`, `attendance_records`, `form_f1_records`, `external_residents`, `external_resident_postings`, `external_attendance_records`, `audit_logs`, `warning_issues`, `upload_warnings`, and `programme_institution_posting_map`.
- The generic disabled-RLS advisory wording suggests direct exposure, but exact ACL expansion across all 18 objects found zero privileges for `PUBLIC`, `anon`, and `authenticated`. The finding is retained for policy review and is not treated as proof that a sensitive row is presently readable.

## Frontend direct Supabase access

- PASS — repository/build: the browser Supabase client is used for Auth session operations only. Application-data requests use the FastAPI client.
- PASS — repository/build: no `supabase.from` or `supabase.rpc` application call and no Supabase REST or GraphQL application-data route was found in tracked frontend source.
- MANUAL VERIFICATION REQUIRED — the latest deployed frontend bundle/network behavior could not be inspected through the Vercel Security Checkpoint.

# Deployed authorization evidence

## Required merged fixes

| Fix | Source/deployment evidence | Classification |
|---|---|---|
| Explicit Master Admin authorization for RDB, FormF1, and public-holiday/AY-date uploads | source fix `e0efb0db6a163f4b6e82b726deba96ba9f82cef6` is an ancestor of deployed `8474314093235d7bf16ad08da938d1e20b3ee423` | PASS — deployed |
| Native distinct-event overlap rejection and PostgreSQL advisory locking | source fix `a0c4bd11bd67351c5b47274715328c09efc19791` is an ancestor of deployed `8474314093235d7bf16ad08da938d1e20b3ee423` | PASS — deployed |

Repository inspection confirmed the explicit master guard on all three global upload routes and the half-open overlap check, transaction-scoped advisory lock, scheduled/ad-hoc application, and PostgreSQL concurrency regression test. This is not proof of deployed functional mutation behavior; destructive or shared-state tests were intentionally not run.

## Valid-bearer conflicting-header check

BLOCKED — DEPLOYED VALID-BEARER FIXTURE UNAVAILABLE. No approved synthetic authenticated fixture existed in a secure agent/browser context, so raw-header override behavior was not exercised against the shared deployment.

## Deployed role matrix

| Role | Read-only deployed checks | Result |
|---|---|---|
| Master Admin | identity level and master-only read surfaces | BLOCKED — DEPLOYED ROLE FIXTURE UNAVAILABLE |
| Programme PC | normalized scope plus in-scope/out-of-scope reads | BLOCKED — DEPLOYED ROLE FIXTURE UNAVAILABLE |
| Secretary | own-posting and cross-posting denial reads | BLOCKED — DEPLOYED ROLE FIXTURE UNAVAILABLE |
| NHG Resident | own-resource and cross-resident denial reads | BLOCKED — DEPLOYED ROLE FIXTURE UNAVAILABLE |
| Non-NHG Resident | own external resources, no NHG compliance, cross-resident denial | BLOCKED — DEPLOYED ROLE FIXTURE UNAVAILABLE |

# Remaining manual checks

Only the following checks remain unresolved:

1. Confirm Vercel production and preview protection configuration, gate method, and intended stakeholder group for both projects.
2. Review deployed environment-name presence and only the approved safe modes; confirm frontend/backend separation and exact configured CORS hostname membership without recording any secret value.
3. Inspect a safe current-release 5xx response when a non-mutating fixture is available.
4. Confirm Supabase exposed schemas and Data API settings, then perform the approved direct public-key denial test without displaying the key.
5. Inspect the latest deployed frontend bundle/network path to confirm Auth-only browser Supabase use.
6. Provide approved synthetic UAT sessions to run the conflicting-header check and the five-role read-only authorization matrix.

# Overall 5B-H-C status

The prior broad live-evidence NO-GO can be narrowed: deployment revision, current-release health, operational CORS behavior, required headers, migration/schema, seed/config, staff-bootstrap aggregates, and the current protected-UAT grant boundary now have read-only PASS evidence. There is no live FAIL in this pass.

It cannot yet be converted to stakeholder UAT GO. The remaining deployment-control, environment, Data API, deployed-bundle, safe-5xx, and synthetic-role checks require manual access or approved fixtures. The correct status is therefore **LIVE EVIDENCE PARTIAL — BLOCKED ITEMS REMAIN**.
