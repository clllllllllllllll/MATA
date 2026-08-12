# API Endpoints

Base URL: `http://localhost:8000/api/v1`

`security.md` is authoritative for cross-cutting authentication,
authorization, session, CSRF, rate-limit, privacy, deployment, and RLS
requirements. This file remains authoritative for route and request/response
contracts.

Phase 6 dashboard/report and calculation references in this document are future
API specification unless independently marked as implemented pre-compliance
workflow. They do not claim that a full `compliance.py` engine is currently
implemented.

---

## Phase 5B-H-D Authentication and Browser Transport

MATA has three server-owned identity sources—`users`, `residents`, and `external_residents`—but one normal production browser transport: an opaque backend application session in `__Host-mata_session`. The cookie contains no identity or scope claims. The backend resolves its keyed digest in `app_sessions`, reloads the current subject, checks the stored generation snapshot, and derives role/scope from the subject table on every protected request.

Staff credentials are verified through a backend-mediated Supabase password call. Supabase access and refresh tokens are not returned to or persisted by the browser. Residents remain MCR-backed and do not become Supabase Auth users.

Login, registration options, and Non-NHG registration are intentionally public application endpoints. They do not require a Vercel outer gate. In production they remain protected by exact Origin validation where applicable, JSON-only public mutations, persistent PostgreSQL rate limits, generic errors, and strict authorization on every protected resource.

Normal production responses use the same-origin relative `/api/v1` path and credentialed cookie requests. The frontend holds only identity, session-bound CSRF, and a refresh hint in module memory. It stores no application access/refresh token and does not routinely send `Authorization: Bearer`.

`bearer_compat` is retained for non-production compatibility and historical
claim documentation. It is not reachable in the current production
configuration: production requires H-E RLS and RLS requires cookie transport.
An emergency production rollback therefore requires a coordinated application
and database version rollback plus forced reauthentication; the legacy flag
alone cannot enable bearer transport.

Resident identity assurance remains separately governed product debt. Do not
invent a second factor or claim workflow outside an approved product scope.

## Phase 5B-H-E Database Authorization Boundary

H-E adds a second, database-enforced authorization layer without replacing FastAPI authorization:

- protected application queries use a credentialed login that is a member only of the non-owner, `NOBYPASSRLS` `mata_app_runtime` capability group;
- intentionally unauthenticated login, registration-options, Non-NHG registration, session issuance, and shared session/rate-limit infrastructure use a distinct `mata_auth_internal` helper credential with no direct application-table privileges;
- migrations and ownership use a third credential that is never an application runtime credential;
- the runtime installs database-owned identity as transaction-local context before protected queries and revalidates it after every root transaction boundary;
- subject type/id, application role, explicit admin level, normalized programme scope, posting code, application-session id, and the authorization fingerprint are derived from the current database session/subject state;
- browser claims, raw `X-User-*` headers, request JSON, frontend state, and Supabase `user_metadata` cannot seed PostgreSQL authorization context;
- invalid or stale context produces the normal generic `401 Unauthorized` application response; unexpected SQLAlchemy, PostgreSQL, transaction, connection, or pool errors remain failures and are not reclassified as ordinary authorization denials.

All 34 application tables have RLS enabled locally by `20260726_000026`. The 84 policies target only `mata_app_runtime`; browser roles retain no application-table access. Six infrastructure/future-state tables have neither direct runtime table privileges nor table policies: implemented operations use reviewed functions, while unimplemented future workflows remain denied.

This is local implementation evidence only. A deployed Supabase project must independently prove its revision, roles, ownership, grants, policies, default ACLs, startup attestation, and five-role workflow behavior.

## Identity Sources

There are separate identity paths, but they share the opaque application-session envelope. The login UI exposes one shared Resident MCR field: it sends exactly one `{ "role": "resident", "mcr": "<NORMALIZED_MCR>" }` request, and the backend resolves the unique active row from `residents` or `external_residents`. Global cross-table MCR uniqueness makes that resolution deterministic.

### Path 1 — Admin and Secretary (`users` table)

Admin and secretary accounts are managed in the `users` table (email + password). Login via `POST /auth/login` with email and password. In cookie mode, the following identity shape is returned inside `user`; no JWT is returned:

```json
{
  "id": "<users.id>",
  "role": "admin" | "secretary",
  "programme_scope": ["DR", "GRM"],   // admin only
  "posting_code": "TTSHGerMed"        // secretary only
}
```

### Path 2 — Residents (`residents` table)

Residents are **not** in the `users` table. They authenticate with their **MCR number only** under the currently approved contract. In normal cookie mode, successful authentication creates an opaque backend session and returns identity plus session-bound CSRF state; it does not return a JWT or bearer token.

The following claim shape is retained only for explicitly enabled emergency `bearer_compat`:

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

In stub/demo mode, identity may be represented by the local session/header shim. In `AUTH_MODE=supabase`, NHG Residents still do not get Supabase Auth accounts; backend `/auth/login` resolves the shared MCR request to an active `residents` row and creates the opaque application session. The backend reloads the active resident row and current `session_generation` on protected requests.

`programme_code` is derived from the current `residents` row. It scopes all compliance lookups to the resident's native programme. Current posting is always derived at request time from `resident_postings`; it is not trusted from browser state or the opaque cookie.

### Path 3 — Non-NHG Residents (`external_residents` table)

Non-NHG/cross-cluster residents are **not** in the `users` table and are **not** native `residents`. They self-register first, then authenticate through the same shared Resident MCR field as NHG Residents. Allowed `home_cluster` values are strictly `NUH` and `SingHealth`. Normal cookie mode creates the same opaque application-session envelope used by other identities.

The following claim shape is retained only for explicitly enabled emergency `bearer_compat`:

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

In `AUTH_MODE=supabase`, Non-NHG Residents do not get Supabase Auth accounts. Backend `/auth/login` resolves the neutral shared request to an active `external_residents` row, returns `user.role = external_resident`, and creates an opaque application session. The backend reloads the current external-resident row and generation on protected requests.

Posting state and posting schedule are not trusted from browser state for authorization-sensitive reads. Fetch the Non-NHG Resident from `external_residents` and derive date-specific posting from `external_resident_postings` where relevant. `external_residents.current_nhg_posting_code` may remain a current/cache/backward-compatibility pointer, but schedule-aware resident flows use `external_resident_postings`. Non-NHG Residents do not receive NHG compliance or clawback surfaces.

**Global MCR uniqueness:** `POST /external-residents/register` must reject an MCR that already exists in either native `residents` or `external_residents`.

### How the compliance chain resolves from login

1. Resident logs in with MCR → opaque application session created; identity is reloaded from `residents`
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

### Browser session transport, Origin, and CSRF

- Production/Supabase frontend requests use relative same-origin `/api/v1` with credentials enabled.
- Staff email/password is submitted to `POST /api/v1/auth/login` on the
  frontend origin. The backend alone calls the approved Supabase password Auth
  endpoint, verifies the upstream subject, reloads MATA authority from trusted
  storage, discards upstream access/refresh tokens, and issues an opaque
  PostgreSQL-backed application session.
- Protected unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) require `X-CSRF-Token` matching the active session digest.
- Every production unsafe request also requires an exact `Origin` from `CORS_ORIGINS`; missing, wildcard, malformed, or unapproved origins fail with generic `403`.
- Public login and Non-NHG registration do not require an existing-session CSRF token because these endpoints are intentionally unauthenticated, but require exact production Origin and `application/json`; form-encoded variants return `415`. A production browser request with Fetch Metadata other than `Sec-Fetch-Site: same-origin` returns generic `403`, so direct browser-to-backend login is unsupported. An `Authorization` header on these cookie-mode routes returns generic `401`.
- `GET /auth/me` hydration is side-effect-free for session timestamps. Session
  resolution never touches. After session/CSRF validation and a successful 2xx
  protected unsafe response, the server may atomically extend idle expiry when
  the configured touch interval is due, never beyond absolute expiry. Failed
  requests, safe reads, polling, refresh, and logout do not qualify. If the
  final touch finds an expired, revoked, or stale session—or the lifecycle
  store fails—the pending protected 2xx response is replaced by a controlled
  `401` that leaves the shared session cookie unchanged. Generic or stale
  failure paths must not delete a newer valid cookie; cookie deletion remains
  limited to reviewed proof-positive logout.
- Normal cookie mode ignores raw client identity headers and does not use caller-provided authorization as the application credential. Local stub/demo and explicitly gated emergency bearer compatibility remain separate.
- Normal production browser requests do not send `Authorization`, do not rely
  on CORS, and hydrate `GET /auth/me` from the session cookie.

Effective expiry is the earlier of idle and family absolute expiry, with
equality treated as expired. Refresh replaces the credential and CSRF value
but extends neither the current idle deadline nor the original absolute
deadline. Expired sessions receive a controlled `401`, cannot establish CSRF
or RLS identity, and require full login.

The application cookie is intentionally a non-persistent browser-session
cookie: it carries neither `Max-Age` nor `Expires`. A relative lifetime derived
before commit and response delivery cannot rigorously track the PostgreSQL
absolute deadline. Server-side expiry remains authoritative even if a browser
retains or restores a stale session cookie.

### Request validation and sanitisation

- Validate all request bodies, query parameters, path parameters, and uploaded files with Pydantic schemas or explicit parser validation before any database write.
- Reject unknown enum values with `422` unless the relevant parser spec explicitly says the value is stored with a warning.
- Normalize user-controlled string inputs by trimming leading/trailing whitespace and rejecting control characters where not meaningful.
- Do not use client-provided filenames for storage paths or parser selection. Upload slot determines parser selection; filename is audit-only.
- Enforce server-side file validation on upload endpoints:
  - allowed extensions: `.xlsx` for RDB, TTF, FormF1; `.xlsx` or `.csv` for public holidays
  - validate MIME/content where practical
  - enforce the configured 4 MiB global and aggregate upload-request caps and the 3 MiB per-file cap
  - allow at most one file and only the documented route fields; each non-file field is capped at 4 KiB and decoded filenames at 255 UTF-8 bytes
  - reject password-protected or unreadable workbooks with `422`
- The pure ASGI body limiter runs before authentication and multipart parsing. It validates every observable `Content-Length` value and also counts actual streamed bytes, so missing or false-small lengths do not bypass the cap.
- A malformed or conflicting `Content-Length` returns controlled `400`. A known or streamed body over the selected cap returns controlled `413` with `Cache-Control: no-store`; exact-boundary bodies are allowed.
- Known oversized requests do not invoke the downstream parser. Unknown-length bodies may still be consumed or spooled up to the cap before the crossing chunk is rejected.
- Application limits do not prevent buffering or earlier rejection by an ingress/provider. The approved Vercel contract is 3 MiB per file inside a complete request capped at 4 MiB; larger files require a separately approved ingress. `docs/security.md` Sections 8, 13, and 17 define the current ingress and deployed-verification contract; `docs/archive/security/phase-5b/5b_h_m05_upload_preparser_limits.md` preserves the historical implementation evidence.
- All write endpoints must be idempotent only where explicitly documented. Otherwise duplicate/conflict cases return `409`.

### SQL injection protection

- Use SQLAlchemy ORM/query builder or parameterised raw SQL only.
- Never interpolate user input into SQL strings, including identifiers, sort fields, filters, search terms, or `ORDER BY` clauses.
- For dynamic sorting/filtering, map accepted public field names to hardcoded model columns.
- Private raw-SQL composition helpers must enforce explicit table, field, and
  column allowlists at their sinks; regression tests must keep structural query
  arguments as source literals and prove adversarial values remain bind
  parameters.
- PostgreSQL advisory-lock keys must be derived from validated internal IDs or deterministic hashes, not raw concatenated user strings.

### XSS and response safety

- API responses are JSON by default and must not intentionally return executable HTML.
- Do not trust stored free-text fields such as `teaching_name`, `posting_code`, `display_name`, or uploaded filename. They must be treated as plain text by the frontend.
- Backend-generated export files must escape spreadsheet formula injection. Any exported cell beginning with `=`, `+`, `-`, or `@` from user-controlled data must be prefixed safely before writing CSV/XLSX.
- Error responses must not leak stack traces, SQL errors, internal paths, environment variables, secrets, or raw parser internals.
- Security headers middleware should set at least:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - a restrictive `Content-Security-Policy` for any non-API responses

### Authentication and authorization

- All endpoints require authenticated identity except `/health`, non-production docs, `POST /auth/login`, `GET /external-residents/registration-options`, and `POST /external-residents/register`.
- Authorization is server-side only. Frontend role checks are UX only.
- Admin access is programme-scoped via `users.programme_scope`; `NULL` means no access, not all-access.
- Secretary access is posting-scoped from current `users.posting_code`; `X-User-Site` is local stub/demo compatibility only.
- Resident access is identity-scoped via `residents.id`; current posting is derived from `resident_postings` at request time.
- Do not expose resources across roles even when IDs are guessed correctly.

### Rate limiting

Production requires `RATE_LIMIT_STORE=postgres`. `rate_limit_buckets` uses atomic fixed-window PostgreSQL upserts and stores only a keyed HMAC-SHA256 identifier; raw IP, email, MCR, or subject identifiers are never persisted. In-memory limiting remains non-production compatibility only.

Required default limits, configurable via environment variables:

| Endpoint group | Suggested default | Key |
|---|---:|---|
| `POST /auth/login` | 5 attempts / minute by IP; 10/hour by normalized identifier | keyed digest only |
| `POST /external-residents/register` | 3 attempts / 10 minutes by IP; 5/hour by MCR | keyed digest only |
| `POST /admin/upload/*` | 10 uploads / hour | shared `admin_upload` subject bucket |
| mutation endpoints (`POST`, `PUT`, `PATCH`, `DELETE`) | 60 requests / minute | authenticated subject + mutation bucket |
| report/export endpoints | 20 requests / minute | shared `report` subject bucket |
| resident attendance submission | 30 requests / minute | resident id |
| general `GET` endpoints | 300 requests / minute | verified subject, or anonymous IP for public GETs |

When a limit is exceeded, return:

```json
{ "detail": "Too many requests" }
```

with HTTP `429` and `Retry-After`.

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

In `AUTH_MODE=supabase`, protected browser requests use the opaque MATA
application cookie. Staff Supabase JWTs are transient backend
credential-verification proof only, and resident MATA JWTs are not normal
browser application credentials. The backend reloads the active `users`,
`residents`, or `external_residents` row, checks `session_generation`, and
derives current role and scope on every protected request. Raw client headers,
cookie contents, browser state, and Supabase `user_metadata` are not
authorization sources. `bearer_compat` remains only as non-production and
historical rollback compatibility; the current production/RLS configuration
cannot enable it in place.

5B-E staff accounts are generic role accounts. `users.name` is the account display name. `current_staff_actor_name` is a self-declared current human name used for audit/display context only; it never grants role, programme scope, admin level, or posting scope.

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

## Shared Teaching Name pool, mapping API, and scheduled-event identity/runtime (Phases C, D, F, and G)

Revision `20260803_000031` activates the shared-pool lifecycle and
`20260803_000032` adds the narrow E1 TTF mapping-reconciliation helper. Phase D
adds the guarded Programme-PC mapping API below. Revision `20260804_000033`
adds explicit identity to new scheduled events: a pool event carries one
`teaching_name_id`, a global event carries one `global_session_type_id`, and
both retain an immutable `teaching_name` display snapshot. Revision
`20260804_000034` uses those persisted identities for Resident/Non-NHG runtime
discovery and attendance where present; both-null legacy rows retain
  deterministic persisted evidence only. Revision `20260805_000036` completes
  E2+B2: the physical parser is A–J only, and no current API or runtime path
  uses a catalogue or `details_of_training` field.
Revision `20260804_000035` adds immutable pool-source programme/period
snapshots. Pool creation writes both values, used-name deletion preserves them,
and list/manage/attendance authorization uses them without catalogue or display-
text inference. Event owner and source programme must agree exactly. An inactive
global type is excluded from new choices and new writes but does not hide or
invalidate an existing event.

### Lifecycle routes

| Route | Authority | Notes |
|---|---|---|
| `GET /secretary/teaching-name-programmes` | Secretary | Returns only active, explicitly capable programme pools for the Secretary's current posting. |
| `GET /secretary/teaching-names` | Secretary | Requires `reporting_period_id` and explicit `programme_code`. |
| `POST /secretary/teaching-names` | Secretary | Creates a name in an explicitly selected eligible pool. |
| `PATCH /secretary/teaching-names/{id}` | Secretary | Renames only a Secretary-created name from the actor's exact source posting, with `expected_revision`. PC-private names are read-only. |
| `POST /secretary/teaching-names/{id}/deactivate` | Secretary | Source-owner only; requires `expected_revision`. |
| `POST /secretary/teaching-names/{id}/reactivate` | Secretary | Source-owner only; requires `expected_revision`. |
| `DELETE /secretary/teaching-names/{id}` | Secretary | Source-owner only; deletes only an unused name with `expected_revision`. |
| `GET /admin/teaching-names` | Master Admin or Programme PC | Requires `reporting_period_id` and explicit `programme_code`. |
| `POST`, `PATCH`, `POST .../deactivate`, `POST .../reactivate` under `/admin/teaching-names` | Programme PC only | Create makes a programme-private name. Lifecycle mutations require source ownership; an admitted host Secretary name is read-only. A Master Admin receives `403` for ordinary lifecycle mutations. |
| `DELETE /admin/teaching-names/{id}` | Master Admin or Programme PC | A PC may delete an unused source owned by its programme, but not an admitted host source; Master Admin may perform the guarded used-name deletion below. |

Both list routes support `is_active`, `search`, `limit`, and `offset`. Name
responses expose the display value and lifecycle metadata, never the
server-owned normalized key.

### Authorization and lifecycle

- `teaching_name` operations are scoped to one
  `(reporting_period_id, programme_code)` pool. A Secretary needs the current
  exact posting and active `can_manage_teaching_names` capability; a Programme
  PC needs the programme in current scope. Native posting/event visibility and a
  first matching row never confer authority.
- Name normalization is server-owned: NFC, Unicode whitespace collapse,
  casefolded NFC uniqueness, preserved punctuation and wording. Blank, values
  retaining control characters after whitespace normalization, and
  over-200-character display or normalized values return `422`; an active or
  inactive duplicate returns `409` with its existing ID and reactivation hint.
- Creation and reactivation acquire the TTF reporting-period/programme advisory
  lock. The owner trigger creates one pending mapping for each distinct target
  `(posting_code, r_year)` scope and reactivation only fills missing rows. It
  preserves existing mapped rows and IDs. A scope with no targets is valid.
- Phase C itself adds no mapping endpoint. Phase D mapping mutations remain
  configuration only and do not activate pool-backed event or compliance work.
- A Secretary or PC may delete only an unused name. A Master Admin may delete a
  used name only with `force_delete = true`, a nonblank reason, confirmation
  exactly `"DELETE"`, and the current revision. The response exposes counts,
  never affected IDs; the event identity becomes null while snapshot and
  attendance records remain intact.

### Concurrency and mutation effects

- Rename, deactivate, reactivate, and delete require `expected_revision`; a
  stale value returns `409` with no partial write. Rename and deactivation
  preserve mappings, and each lifecycle change increments the name revision.
- Master deletion locks the name before it counts references: the RLS runtime
  uses its guarded definer helper, while the supported non-RLS runtime uses the
  same ordinary `SELECT ... FOR UPDATE` path as other deletes. A concurrent new
  event reference therefore waits, then either appears in the guarded count or
  fails after the name is deleted; it cannot be omitted from a successful
  count-only force-delete response.
- Each successful mutation writes one audit record atomically and invalidates
  only affected name/mapping/event option caches after commit. It returns a
  `future_compliance_impact` summary only; no compliance, surplus, warning, or
  attendance revalidation is performed.

### Scheduled-event source and timing contract

- A pool-backed scheduled-event request identifies one `teaching_name_id` and
  belongs to that name's single programme and reporting period. The selected
  name must have an existing mapping scope for the event's exact posting;
  either a pending or mapped scope is sufficient. A global event instead
  identifies one `global_session_type_id`; global types remain Admin-managed
  and outside the ordinary mapping queue. No event may carry both identities;
  transitional legacy rows may carry neither.
- The client supplies `start_time` only. For a pool-backed event, the server
  resolves duration from the exact Teaching Name, reporting period, programme,
  posting, and R-year mappings. Staff scheduling stores the longest effective
  R-year duration as the operational event envelope. A pending R-year mapping
  contributes a temporary one-hour duration; a mapped R-year contributes its
  selected TTF session type's duration. Global events use their configured
  duration. The server stores the envelope `duration_hours`, computes its
  `end_time`, and rejects a pool-event start later than 23:00 with `422`.
- Assigning, changing, clearing, or invalidating a mapping recalculates
  `duration_hours` and `end_time` on existing pool-backed events in the exact
  Teaching Name/posting/programme/reporting-period scope. Attendance rows and
  immutable event source/display snapshots are preserved. Native Resident
  submission and history views derive their own duration and end time from the
  Resident's exact event-date R-year mapping. Non-NHG Residents do not resolve
  NHG compliance or R-year mappings; they may view all scheduled events at
  their exact date-matched posting and use the staff event envelope.

#### Valid and prohibited R-year mapping cases

`teaching_name_mappings` includes R-year because compliance target selection is
resident-contextual. One shared event may therefore link through the same
Teaching Name to different duration-bearing TTF session types for different
R-years.

- **Intended valid case:** for one Teaching Name, reporting period, programme,
  and posting, R1 may map to `Journal Club [1h]` while R2 maps to
  `Journal Club [2h]`. Staff Add Teaching displays `Varies by R-year`, shows the
  one-hour and two-hour calculated end times, and stores two hours as the staff
  schedule envelope. An R1 Resident sees and uses one hour; an R2 Resident sees
  and uses two hours. Both attendance rows continue to reference the same
  scheduled event.
- **Prohibited case:** the same exact Teaching Name, reporting period,
  programme, posting, and R-year audience cannot be split between both a
  one-hour and two-hour target. The mapping identity has exactly one selected
  `teaching_target_id`; an attempt to apply competing changes to that same
  mapping identity is rejected atomically rather than duplicated or resolved by
  query order.

Native Resident timing always uses the R-year from the Resident's date-specific
posting/phase covering the event date, not merely a current profile value. The
same resident's historical events therefore retain the R-year applicable when
each event occurred. Resident overlap checks use those resident-specific event
intervals; staff and Non-NHG overlap/display use the longest-duration event
envelope.

Scheduled events may legitimately overlap. When staff select a posting, date,
and start time that overlaps an existing staff event envelope, Add Teaching
shows a non-blocking warning and still permits creation. A mapping change may
also create or expand an overlap after events or attendance exist; the mapping
remains authoritative, event timings update atomically, and neither event nor
attendance evidence is deleted or rewritten.

#### Protected mutation boundary

- Every Teaching Name mutation uses the current protected-mutation
  contract: opaque-session authentication, current server-side authorization,
  CSRF and exact-Origin validation, applicable rate limiting, transactional
  audit logging, and cache invalidation only after commit. Failed, stale,
  unauthorized, out-of-scope, or preview-fenced requests neither write an audit
  success record nor invalidate caches.
- The B1/Phase C RLS/grant/policy boundary is attested before these routes run.
  Phase D uses that boundary for Programme-PC mapping DML only; Secretaries and
  Master Admins have no mapping DML route.

### Programme PC Teaching Name mapping routes (Phase D)

| Route | Authority | Notes |
|---|---|---|
| `GET /admin/teaching-name-mappings` | Master Admin or Programme PC | Master Admin may read all queues; a PC sees only persisted programme scope. Supports `reporting_period_id`, `programme_code`, `posting_code`, `r_year`, `state` (`pending`/`mapped`), normalized display-name substring `search`, `limit`, and `offset`. |
| `GET /admin/teaching-name-mappings/{mapping_id}/impact` | Master Admin or in-scope Programme PC | Requires `expected_revision`; optional `teaching_target_id` is validated against the exact mapping scope. Returns aggregate event/attendance counts only. |
| `PATCH /admin/teaching-name-mappings/{mapping_id}` | In-scope Programme PC | Assigns, changes, or explicitly clears one existing mapping. |
| `POST /admin/teaching-name-mappings/bulk` | In-scope Programme PC | Atomically applies at most 100 independently revision-fenced changes; duplicate mapping IDs and partial success are rejected. |

A mapping queue row exposes the mapping/name IDs, mapping revision, display name,
period/programme/posting/R-year scope, derived `pending`/`mapped` state, current
target summary, and exact-scope target options. A target option is never inferred
from display text and must match the mapping's period, programme, posting, and
R-year exactly.

Single and bulk mutation items require `expected_revision` and a
`teaching_target_id` field. The field is an existing exact-scope target UUID to
assign/change, or explicit JSON `null` to clear while retaining the mapping UUID.
An omitted field is invalid. Successful changes update the target link,
increment the persisted mapping revision once, and recalculate exact-scope
pool-event duration and end time. A stale revision returns `409`.

For an assignment, change, or clear, the service counts only stable
Teaching Name ID plus posting identity and submitted attendance. Because events
do not carry R-year, the count is conservative across same-name/posting R-year
mappings rather than silently treating potentially affected evidence as zero. It
never returns event, attendance, resident, MCR, or external-resident identifiers.
When either aggregate is nonzero, a first request without
`confirm_impact: true` returns controlled `409` with count-only impact and no
write; retrying with the same current revision and explicit confirmation applies
the change. There is no confirmation token, generic confirmation framework, or
client-supplied scope fingerprint.

Each mutation uses the shared reporting-period/programme TTF advisory lock,
locks mapping rows and requested target rows deterministically, validates all
bulk items before writing, records mapping-specific audit and Data Revalidation
evidence atomically, commits once, and invalidates affected scoped mapping,
name-option, target-resolution, event, attendance-view, and report caches after
commit. Mapping changes preserve attendance rows and immutable display/source
snapshots while recalculating `duration_hours` and `end_time` on pool events in
the exact Teaching Name/posting/programme/period scope. Different R-years may
map to different durations; the stored staff event timing is the longest
effective R-year duration, while native Resident reads resolve their exact
event-date R-year duration. Impact confirmation also warns that a longer
duration may create or expand schedule overlaps; overlap is informational and
does not prevent the authoritative mapping change.

### Phase V Teaching Name visibility and creation contract

Phase V reuses the protected Teaching Name and mapping route families; it does
not introduce a client-controlled cross-programme grant endpoint.

For an effectively active reporting period, Programme-PC Teaching Name and
mapping reads return:

- names owned by the PC's native programme;
- Secretary-created names admitted from a host posting because the selected
  programme has at least one actual RDB-backed Resident posting there in that
  reporting period; and
- PC-created programme-private names owned by the selected programme.

The response exposes opaque IDs plus bounded provenance needed by the UI:
source/owner `programme_code`, `origin_posting_code` when Secretary-created,
immutable `created_by_role`, `visibility_scope`, `admission_reason`, and
`can_manage_name`. It must not expose Resident identity as evidence for the
admission. Same display text from two source departments remains two options.

`POST /admin/teaching-names` creates a programme-private name for a Programme
PC. The server derives the owner programme from the authenticated PC scope,
sets PC creator provenance and private visibility, and provisions only
in-programme mapping work. Request fields attempting to select another owner,
source posting, creator role, or broader visibility are rejected. Master Admin
ordinary creation remains forbidden.

An external host name is read-only as a source to the consuming Programme PC:
the PC may assign, change, or clear mappings belonging to its own programme,
but source-name rename, deactivate, reactivate, and delete routes return `403`
unless the existing owner-side lifecycle authorization independently permits
the operation. A mapping target must always belong to the authenticated PC's
programme TTF and exact reporting-period/posting/R-year scope; it is never
selected from the source department's TTF.

Secretary Teaching Name reads continue to require the exact Secretary posting
and explicit programme capability. A native Department Secretary additionally
sees PC-private names owned by that same programme, labelled as PC-created.
Secretaries at external host postings and unrelated programme PCs never see
those private names. A Secretary-created department-shared name remains
available to eligible external Programme PCs only through server-derived
programme admission; no Secretary request can nominate external programmes.

Cross-posting admission is based on actual usable `resident_postings` rows
anywhere in the selected reporting period, not merely on a generally permitted
rotation. An actual RDB-scheduled assignment may be earlier, current, or later
within that same period. Once admitted, the name and any pending or completed
mappings remain in that programme's active queue for the rest of the period
even if the last Resident leaves. Effectively inactive periods are excluded
from active routes; their rows remain available only to explicitly
historical/audit reads and are not copied into a new period.

**Valid:** a REHAB PC maps a GERI Secretary source at `TTSHGerMed` to a REHAB
TTF target because a REHAB Resident has an actual reporting-period posting at
that site.

**Rejected:** the same read/mutation when no REHAB Resident posting has admitted
that source; a mapping target from the GERI TTF; a request that broadens a
PC-private name to another programme; or a cross-programme lifecycle mutation
against the source name.

## Admin Endpoints

### POST `/admin/upload/rdb`

Upload RDB Posting Schedule Excel file.

- **Auth:** explicit Master Admin only (`role = admin` and persisted/verified `admin_level = master`). Programme PCs, including accounts with null, empty, blank, or whitespace-only `programme_scope`, receive `403`.
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

- **Auth:** explicit Master Admin for any programme, or Programme PC when the normalized requested `programme_code` is in the normalized persisted `programme_scope`. Null, empty, blank, whitespace-only, missing, or out-of-scope Programme PC scope receives `403`; none of these states imply Master Admin.
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID), `programme_code` (string)
- **Processing:** See `docs/parsing.md` § TTF Parser
- **Behaviour:** Stable target reconciliation within `(reporting_period_id, programme_code)` scope. Re-upload remains allowed regardless of existing attendance. Matching `(r_year, posting_code, session_type_id)` targets retain their UUID; stale mapped targets leave their mapping rows pending rather than deleting or redirecting them. The TTF is also the explicit programme-scoped replacement for posting-group configuration: blank or omitted Column E membership removes the prior group row for that posting.
- **Final A–J contract:** Columns A–J are the only accepted TTF fields. Each row must match the selected reporting period and programme; the parser supports all 28 seeded programmes generically, normalizes the 20 all-year programmes to `ALL`, and retains exact R-years for the other eight. A populated Column K or any later unsupported column returns controlled `422` without echoing submitted cell values.
- **Target validation:** `monthly_target` must be a non-negative whole number. `0` is accepted but does not determine Phase G event visibility or attendance eligibility. TTF never creates Teaching Names or mappings from workbook text.
- **Concurrency:** The programme-global `posting_groups` advisory lock is acquired before the existing reporting-period/programme scope lock. A concurrent upload for the same programme, including one for a different reporting period, returns controlled `409`; different programmes remain independent.
- **Audit log:** Writes `upload_logs` row with `upload_type = 'ttf'`
- **Response:**
```json
{
  "targets_created": 29,
  "targets_inserted": 4,
  "targets_updated": 17,
  "targets_removed": 2,
  "targets_unchanged": 6,
  "mappings_preserved": 11,
  "mappings_invalidated": 2,
  "mappings_with_target_semantics_changed": 3,
  "pending_mappings_created": 4,
  "affected_event_count": 3,
  "affected_attendance_count": 7,
  "session_types_upserted": 5,
  "posting_codes_added": ["AICAIC", "DPPallia"],
  "posting_groups_upserted": 5,
  "posting_groups_removed": 2,
  "rows_exploded": 3,
  "warnings": [],
  "errors": []
}
```
- **Counter compatibility:** `targets_created` retains the legacy processed-target-row count (as does the generic upload `created_count`). `targets_inserted`, `targets_updated`, `targets_removed`, and `targets_unchanged` are the reconciliation deltas for the current upload.
- **Error responses:**
  - `409` — concurrent upload for the same programme posting-group replacement or the same target scope (advisory lock)
  - `422` — file validation errors (returned before any writes)

### POST `/admin/upload/form-f1`

Upload FormF1 Excel file for active/inactive status per resident per calendar month.

- **Auth:** explicit Master Admin only (`role = admin` and persisted/verified `admin_level = master`). Programme PCs, including accounts with null, empty, blank, or whitespace-only `programme_scope`, receive `403`.
- **Content-Type:** multipart/form-data
- **Body:** `file` (xlsx), `reporting_period_id` (UUID)
- **Processing:** See `docs/parsing.md` § FormF1 Parser
- **Parsed/persisted fields only:** MCR, monthly status columns, and promotion date/senior promotion date. Other FormF1 profile/identity columns are non-authoritative and are not persisted from FormF1.
- **Column detection:** Dynamic header/column detection is preferred. Current-template fallback positions remain supported: column E = MCR, columns M–X = monthly statuses, column Y = promotion date.
- **Behaviour:** Full replace per `reporting_period_id` scope. Re-upload allowed at any time (e.g. to update for unforeseen LOAs). Promotion date is parsed and persisted but is not used by compliance yet.
- **Compliance gate:** Storage remains calendar-month keyed, but the resolved AY bucket `month_label` selects the FormF1 row used for both numerator and denominator across the entire bucket. The API/report layer must not switch to the event's raw calendar month or split/prorate a bucket.
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

### GET `/admin/parsed-data/teaching-targets`

List parsed teaching targets with filters.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `r_year`, `session_type`, `is_tracked`, `search`, `limit`, and `offset` (all optional except bounded pagination defaults)
- **Response:** paginated parsed teaching target objects

### PATCH `/admin/parsed-data/teaching-targets/{id}`

Correct a single parsed teaching target row (mid-period correction).

- **Auth:** admin only
- **Editable fields only:** `monthly_target`, `is_tracked`, `is_reallocatable`, and `tag`
- **Target validation:** `monthly_target` accepts non-negative whole numbers including `0`; negative and fractional values are rejected.
- **Identity columns (locked):** `session_type_id`, `posting_code`, `programme_code`, `r_year`, and reporting-period identity cannot be changed by this route. Full TTF re-upload is required for structural changes.
- **Side effect:** The correction updates only the target's mutable semantics, audit evidence, and bounded Data Revalidation outcome. It never seeds Teaching Names or creates mappings from text.
- **Body:**
```json
{
  "changes": {
    "monthly_target": 15,
    "is_tracked": true,
    "is_reallocatable": false,
    "tag": "A"
  },
  "correction_reason": "Corrected approved mid-period target",
  "last_seen_updated_at": "2026-08-03T10:00:00Z"
}
```

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
  "programme_code": "DR",
  "posting_code_1": "TTSHDiagRd",
  "posting_code_2": "NNINeuRad",
  "rule_type": "combine",
  "combined_label": "TTSHDiagRd & NNINeuRad",
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
- `main_posting`: Sources collapse to one configured existing `main_posting_code`, which is the compliance identity; no combined identity is created. FM rows with `posting_code_2 = null` define the recognised trigger list and `exclusion_code` is the configured zero-match fallback.
- `combine`: Sources resolve to one configured canonical combined code in `combined_label`. It must already exist in `posting_codes` and have TTF rows; one `resident_postings` identity is produced and no component compliance results are returned.
- `half_month`: Source codes remain independent rows with their own TTF targets and compliance identities. Each receives `active_months_weight = 0.5`; the API/config contract does not halve `monthly_target`. Posting groups may aggregate later only when separately configured.

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
- **Notes:** `group_code` is the canonical aggregation key. Add one row per posting code that belongs to the group. A posting code may only belong to one group per programme. This writer takes the same programme-level posting-group transaction lock as TTF replacement; it returns `409` while another posting-group writer or TTF replacement for that programme is in progress.

### PUT `/admin/posting-groups/{id}`

Update an existing posting group entry.

- **Auth:** admin only
- **Concurrency:** The update locks its original programme and, when moving the row, its replacement programme in deterministic code order before writing. It returns `409` if either programme is being replaced by TTF or changed by another posting-group writer.

### DELETE `/admin/posting-groups/{id}`

Delete a posting group entry.

- **Auth:** admin only
- **Concurrency:** This writer takes the same programme-level posting-group transaction lock as TTF replacement and returns `409` on contention.
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
- **ORTHO invariant:** The confirmed ORTHO mutation row must target only the exact original `NHG Orthopaedic Surgery Residency Teaching [3h]` session type. At compliance read time the original end time is reduced by two hours, the projected type becomes `National Didactics & Department Teaching [1h]`, and the Saturday 08:30–10:30 window is checked against that adjusted interval. Sunday is excluded and other ORTHO session types are not mutated. The API must not accept an update that broadens this confirmed seed into a wildcard ORTHO mutation.

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
  "r_year_required": true,
  "is_subspecialty": false,
  "rdb_alias": null
}
```

SPORTSMED and PALLMED must retain `r_year_required = true` and `is_subspecialty = false`; their R4–R6 values are not remapped to SS years.

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

The stored status remains `active` or `inactive`; due scheduled dates are resolved at read time and do not mutate the row. When both scheduled dates are due, the later scheduled date wins; if both are due on the same date, deactivation wins. Multiple periods may be administratively active. A current-date display workflow resolves exactly one effectively active period containing today, while a dated submission resolves exactly one containing its relevant date. Resident scheduled-event discovery is the intentional exception: it enumerates every effectively active period and evaluates each event against the one active period containing the event date. A future active period is not a current default, and overlapping active date windows return a safe configuration conflict for an affected event/submission date. With no effectively active period, resident event listing returns an empty list with `reason = "active_reporting_period_unavailable"` and ad-hoc disabled; attendance and ad-hoc submission endpoints reject with `422` when their selected date has no matching period.

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

- **Auth:** explicit Master Admin only (`role = admin` and persisted/verified `admin_level = master`). Programme PCs, including accounts with null, empty, blank, or whitespace-only `programme_scope`, receive `403`.
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

> **Shared contract:** All admin reports and the resident dashboard must apply the same ordered specification in `docs/business-logic.md` § BL-6. Batch optimization is allowed, but the API contract does not claim that Phase 6 code or tests are implemented.

> **Export format:** All four report endpoints support `?format=xlsx` in addition to JSON. Excel output mirrors the legacy Programme Reporting View format.

### GET `/admin/reports/monthly-view`

Monthly attendance summary per resident.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `posting_code`, `month` (YYYY-MM)
- **Response:** Per-resident rows with target per displayed AY bucket label, achieved, percentage, and traffic-light colour. Monthly percentages are display-only; the posting-level unrounded percentage is the canonical compliance predicate.

### GET `/admin/reports/posting-view`

Posting-level compliance summary.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `programme_code`, `format` (`json` | `xlsx`)
- **Response:** Per-resident, per-posting rows with: `target100`, `target70`, `achieved_and_counted`, `shortage`, `percentage`, `met_70pct`, `colour`, `compliance_unreliable`, `compliance_unreliable_reason`.
- **Semantics:** `percentage = achieved_and_counted / target100` is retained unrounded for the canonical `met_70pct = percentage >= 0.70` predicate and traffic light. `target70 = ceil(target100 × 0.70)` is display-oriented, including for fractional denominators; it must not override a passing percentage. Shortage is zero when percentage is at least 70%, otherwise `ceil((target100 × 0.70) - achieved_and_counted)`.
- **R-year transitions:** Physical posting/session-type/R-year contexts are targeted and capped separately, then their capped achievement and targets are summed into the final posting row. Raw attendance and active months are not duplicated across contexts.
- **Reallocation:** Reports transfer raw session counts one-for-one before final capping, within one physical posting, R-year context, and tag prefix. No duration-weighted, cross-posting, or cross-R-year transfer is exposed by the API.

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

**DEFERRED.** This route is a future placeholder only; no implementation-ready query, row identity, response fields, suppression contract, amount formula, or final-close behavior is confirmed. Norm rates/effective dating, funding R-year, financial classification, Extension/R7/SAF/SCDF precedence, grouped identity, billing attribution, missing-rate behavior, rounding, and final-close transaction/rerun rules remain unresolved. Ordinary compliance readiness is not blocked by this deferral.

### GET `/admin/exports/period-snapshot/{snapshot_id}`

Export a historical period snapshot as Excel. Available for finalized/frozen period snapshots only. Final close/freeze behavior is deferred and is separate from active/inactive operational status.

- **Auth:** admin only

### GET `/admin/form-f1-records`

List FormF1 active/inactive records.

- **Auth:** admin only
- **Query params:** `reporting_period_id`, `mcr`, `month_label`, `is_active` (all optional)

---

## Master Admin Secretary/PC Events

The user-facing Master Admin surface is **Secretary/PC Events**. Its existing route and API prefix remain `/admin/secretary-events` for backward compatibility.

### GET `/admin/secretary-events`

List scheduled teaching events created by Secretaries and Programme PCs, with one response row per `teaching_events.id`.

- **Auth:** explicit Master Admin only (`role = admin` and persisted/verified `admin_level = master`). Null or empty `programme_scope` never grants this authority.
- **Included sources:** Secretary events have `is_adhoc = false` and `created_for_programme_code IS NULL`; Programme PC events have `created_for_programme_code IS NOT NULL`. `created_for_programme_code` is authoritative even when legacy `created_by_role` metadata is absent or inconsistent.
- **Excluded:** NHG Resident and Non-NHG Resident ad-hoc events.
- **Query/filter behavior:** existing search, posting, date, attendance, fixed ordering, and pagination remain supported; `source_type` accepts `all`, `secretary`, or `programme_pc`.
- **Counts:** each item exposes all-linked `native_attendance_count`, `non_nhg_attendance_count`, and `total_attendance_count` without catalogue, target, programme, or attendance joins multiplying event rows. Existing `attendance_count`, `external_attendance_count`, `has_attendance`, attendance filtering, and summary metrics retain their submitted-only semantics.
- **Response fields:** existing event fields plus `source_type`, `created_by_role`, `created_for_programme_code`, `posting_code`, `series_id`, `is_adhoc`, the all-linked attendance counts, and `force_delete_allowed`.

### GET `/admin/secretary-events/{event_id}`

Return the corresponding Secretary or Programme PC scheduled event detail, including source ownership, series metadata, CME/SMC data, and the three attendance counts.

### POST `/admin/secretary-events/{event_id}/force-delete`

Permanently delete one eligible scheduled occurrence and all linked native and Non-NHG attendance submissions.

- **Auth:** explicit Master Admin only. Programme PCs, Secretaries, residents, and Non-NHG Residents receive `403`.
- **Body:**
```json
{
  "reason": "Required operational reason",
  "confirmation": "DELETE",
  "expected_native_attendance_count": 2,
  "expected_external_attendance_count": 1
}
```
- **Validation:** `reason` must be non-blank, `confirmation` must exactly equal `DELETE`, and both expected counts must be non-negative. The expected counts bind the destructive action to the impact shown in the confirmation UI; if the locked event has different linked counts, the action returns `409` without deleting anything. Ad-hoc events are ineligible and return `422`.
- **Transaction:** lock the event, capture the audit snapshot and counts, explicitly delete `attendance_records`, explicitly delete `external_attendance_records`, delete only the selected `teaching_events` row, and write `admin.teaching_event.force_delete` in one transaction. Series siblings and the `event_series` row are preserved.
- **Response:**
```json
{
  "event_id": "3eec9f56-49a8-49db-a719-7a2f3304ca29",
  "deleted": true,
  "source_type": "programme_pc",
  "native_attendance_deleted": 2,
  "external_attendance_deleted": 1,
  "total_attendance_deleted": 3
}
```
- **Status codes:** `200` success, `403` non-Master-Admin, `404` missing event, `422` invalid confirmation/reason/counts or ineligible ad-hoc event, `409` changed confirmation impact or proven transactional integrity conflict, and a generic safe `500` for unexpected failures. Cache invalidation runs after commit; an invalidation failure is logged for operational follow-up but does not misreport the already-committed deletion as failed.

Ordinary Secretary and Programme PC mutation endpoints are unchanged: both deletion paths still return `409` when submitted native or Non-NHG attendance exists. Neither role gains force-delete authority.

---

## `4B` Programme PC Teaching Event CRUD endpoints

Programme PCs manage scheduled teaching events for their own programmes before Phase 6 compliance. PC-created rows use `teaching_events.created_for_programme_code` for explicit programme ownership; secretary-created rows normally leave that field null and remain posting-owned/programme-neutral.

### GET `/admin/programme-teaching-events`

List scheduled teaching events visible to the Programme PC's programme scope.

- **Auth:** admin/PC only
- **Scope:** `programme_code IN programme_scope`. Null or empty `programme_scope` means no access. Master admin access is rejected on these PC CRUD endpoints.
- **Query params:** `programme_code`, `reporting_period_id`, `date_from`, `date_to`, `posting_code` optional.
- **Visibility contract:** Resolve the selected period, or the effectively active period containing today when none is selected. Return only events whose dates fall in that period. PC-created rows must be in scope. A pool-backed row is scoped by immutable source programme/period snapshots (and its exact Teaching Name ID while present); a global row uses the existing posting/programme pool rule without requiring its type to remain active; a true legacy both-null row uses deterministic owner/posting/creator evidence. Catalogue or display-text equality grants no listing or manageability. If an explicit period is supplied with `date_from` or `date_to`, each supplied date must fall inside it or the API returns `422`.

### GET `/admin/programme-teaching-name-options`

Return teaching-name options for PC event creation.

- **Auth:** admin/PC only
- **Query params:** `programme_code` required; `reporting_period_id` or `event_date` optional. An explicit period must be effectively active. When both are supplied, `event_date` must belong to the explicit period or the API returns `422`. With neither option, the backend resolves the single effectively active period containing today. Options are scoped to that resolved period.
- **Scope:** `programme_code IN programme_scope`.
- **Source:** Active `teaching_names` in the selected programme and period, plus active `global_session_types`. Pool options expose `teaching_name_id`; global options expose `global_session_type_id`. Each pool option's `posting_codes` contains only exact persisted mapping scopes that are also active programme postings and `posting_durations` reports the mapped or temporary duration for each posting. Each global option exposes all active programme postings. Same display text in two pools remains two choices with distinct IDs.

### POST `/admin/programme-teaching-events`

Create a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`.
- **Validation:** Returns `422` if `event_date` is in `public_holidays` or exactly one source ID is not supplied. A pool ID must be active, in the event period, in the exact request programme, and in the authenticated PC scope; it must also have an exact persisted Teaching Name mapping for that programme/period and the requested `posting_code`. Pending R-year scopes temporarily contribute one hour; mapped R-year scopes contribute their selected TTF session-type duration, and the longest effective duration becomes the staff event envelope. Different R-years may legitimately have different durations. A global ID must be active. The server computes end time, and a pool event rejects a start later than `23:00`. `teaching_name`, client duration, and client `end_time` are forbidden request fields.
- **Body:**
```json
{
  "programme_code": "DR",
  "posting_code": "KTPHDiagRd",
  "teaching_name_id": "00000000-0000-0000-0000-000000000001",
  "event_date": "2026-04-15",
  "start_time": "10:00",
  "cme_points_awarded": false,
  "smc_event_code": null
}
```
- **Backend writes:** `teaching_events.created_for_programme_code = programme_code`, `created_by_role = 'programme_pc'`, `is_adhoc = false`, the selected source ID, and the immutable display snapshot. A pool write also persists exact immutable `source_programme_code` and `source_reporting_period_id`, and the owner must equal the source programme. `created_by_role` is role/source metadata only; actor names are not stored on the event. Event and audit evidence commit atomically, then scoped caches are invalidated.
- **Resident visibility:** Residents can see the event only when their `programme_code` matches `created_for_programme_code` and the event also passes posting/date and persisted-source eligibility rules.
- **Schedule overlap:** An overlap with another scheduled event at the same
  posting is allowed. Add Teaching warns against the staff event envelopes so
  the creator can review the slot; the warning does not disable or reject the
  create request.

### PUT `/admin/programme-teaching-events/{id}`

Edit a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`, and event must be programme-owned for that programme or a secretary-created/null-owner scheduled row visible to that programme.
- **Validation:** Public holiday, exact-source-ID, scope, exact pool-mapping posting scope, source period, immutable owner/source equality, and server-timing rules apply. An existing global event may keep its same later-inactivated global ID; a new event may not select it. A legacy event with both source IDs null returns `409` rather than receiving an inferred identity.
- **Constraint:** Returns `409` if any native `attendance_records` or `external_attendance_records` exist for the event. `created_by_role` is preserved.
- **Concurrency:** The service locks and reloads the event before the
  all-status attendance guard and update, so a concurrent submission cannot
  validate against the pre-edit interval and attach after the edit.

### POST `/admin/programme-teaching-events/{id}/duplicate`

Duplicate a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`, and source event must be programme-owned for that programme or a secretary-created/null-owner scheduled row visible to that programme.
- **Validation:** Public holiday block and the same exact pool-mapping posting scope apply to the duplicate date. An optional source override may supply one source ID; otherwise the source event identity is copied. A both-null legacy source requires an explicit ID and otherwise returns `409`. The duplicated event sets `created_for_programme_code = programme_code` and `created_by_role = 'programme_pc'`.

### DELETE `/admin/programme-teaching-events/{id}`

Delete a programme-owned scheduled teaching event.

- **Auth:** admin/PC only
- **Scope:** request `programme_code IN programme_scope`, and event must be programme-owned for that programme or a secretary-created/null-owner scheduled row visible to that programme.
- **Constraint:** Returns `409` if any native `attendance_records` or `external_attendance_records` exist for the event.
- **Concurrency:** The service locks and reloads the event before checking
  every linked attendance status and deleting.

---

## Programme PC NHG Resident Attendance (read-only)

These endpoints provide a programme-level NHG Resident overview and one resident's personal attendance history. They are attendance-review reads only; they do not calculate compliance, targets, percentages, traffic-light states, shortages, surplus, reallocation, or clawback.

- **Auth:** Scoped Programme PC or explicit Master Admin. Programme PC access is derived from the authenticated `users.programme_scope`; null or empty scope returns `403` and never means all programmes. Explicit Master Admin retains all-programme read access, matching the shared admin attendance-read convention.
- **Scope:** For Programme PCs, every list count, search result, filter result, resident summary, and attendance row is constrained by `residents.programme_code IN programme_scope`. Authorization uses the resident UUID and programme membership, never MCR. An out-of-scope or unknown resident UUID returns the same controlled `404` response.
- **Native-only boundary:** Reads use `residents`, `resident_postings`, `attendance_records`, `teaching_events`, and display reference tables. They do not read or combine `external_residents`, `external_resident_postings`, or `external_attendance_records`. Non-NHG Attendance remains a separate endpoint and UI workflow.
- **Current posting:** The backend resolves the displayable current posting from native `resident_postings` within the single effectively active reporting period. It uses the established display ranking: an `active` or `loa_working` row covering today, then the nearest future eligible row, then the nearest recent past eligible row. It returns null when no posting is resolvable; the client displays `No current posting`.
- **Source classification:** One centralized mapping returns `Department Secretary`, `Programme PC`, or `Ad-hoc`. `teaching_events.is_adhoc = true` is `Ad-hoc`; otherwise a non-null `created_for_programme_code` is `Programme PC`; the remaining scheduled events are `Department Secretary`. `created_for_programme_code` is authoritative programme ownership and must not be overridden by inconsistent legacy `created_by_role` metadata.
- **Read-only:** Only the two `GET` routes below are provided. There is no edit, remove, delete, status-change, note, force-delete, or other attendance mutation action. Existing resident removal and Master Admin scheduled-event force-delete contracts are unchanged.

### GET `/admin/resident-attendance`

Return one compact row per authorized native NHG Resident.

- **Query params:** `programme_code`, `search`, and `posting_code` optional; `limit` defaults to `50` and is bounded to `1..200`; `offset` defaults to `0`. `programme_code`, when supplied by a Programme PC, must be in scope or the API returns `403`. `search` matches resident name or MCR only within the already-authorized set. `posting_code` filters the server-resolved current posting.
- **Ordering:** Deterministic resident ordering with a stable resident UUID tie-breaker.
- **Response:**

```json
{
  "items": [
    {
      "resident_id": "00000000-0000-0000-0000-000000000001",
      "name": "Test Resident",
      "mcr": "M00000D",
      "programme_code": "GERI",
      "r_year": "R2",
      "current_posting_code": "TTSHGerMed",
      "current_posting_label": "TTSH Geriatric Medicine",
      "attendance_count": 4
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

`attendance_count` is derived from native `attendance_records` only. External attendance never affects the value. The compact projection does not expose private profile fields such as email, phone, employee code, registration type, or unrelated employment metadata.

### GET `/admin/resident-attendance/{resident_id}`

Return the authorized resident summary plus a paginated native attendance history. `resident_id` is a resident UUID; MCR is display data and is never a path or query-string identifier for this lookup.

- **Query params:** `reporting_period_id`, `posting_code`, `date_from`, `date_to`, `source`, and `status` optional; `limit` defaults to `50` and is bounded to `1..200`; `offset` defaults to `0`.
- **Filter values:** `source` accepts `department_secretary`, `programme_pc`, or `adhoc`. `status` accepts the persisted native values `submitted`, `flagged`, or `removed`. `posting_code` filters the teaching event posting. `reporting_period_id` filters by the event date within that reporting period; date filters are inclusive.
- **Ordering:** `event_date DESC`, `start_time DESC`, followed by a stable attendance/event identifier tie-breaker.
- **Response:**

```json
{
  "resident": {
    "resident_id": "00000000-0000-0000-0000-000000000001",
    "name": "Test Resident",
    "mcr": "M00000D",
    "programme_code": "GERI",
    "r_year": "R2",
    "current_posting_code": "TTSHGerMed",
    "current_posting_label": "TTSH Geriatric Medicine"
  },
  "items": [
    {
      "attendance_id": "00000000-0000-0000-0000-000000000002",
      "teaching_event_id": "00000000-0000-0000-0000-000000000003",
      "teaching_name": "Journal Club",
      "details_of_session": null,
      "event_date": "2026-07-18",
      "start_time": "14:00:00",
      "end_time": "15:00:00",
      "posting_code": "TTSHGerMed",
      "posting_label": "TTSH Geriatric Medicine",
      "source": "Department Secretary",
      "status": "submitted",
      "submitted_at": "2026-07-18T15:10:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Removed attendance remains visible as read-only audit history. The response does not resolve or expose compliance-derived session types or target progress.

---

## Secretary Endpoints

### GET `/secretary/reporting-periods`

List reporting periods for the secretary Teaching Schedule period selector.

- **Auth:** secretary only
- **Purpose:** Read-only period metadata for explicit selection, including an effectively active reopened historical period. This does not grant access to Admin reporting-period CRUD.
- **Response:** Same reporting-period fields as the Admin list response (`id`, `label`, `start_date`, `end_date`, stored `status`, `activate_on`, `deactivate_on`, timestamps).

### GET `/secretary/teaching-events`

List teaching events for the secretary's posting site.

- **Auth:** secretary only
- **Scope:** Filtered to the current secretary subject's database-owned `users.posting_code`
- **Query params:** `date_from`, `date_to`, `session_type_id` (all optional)

### POST `/secretary/teaching-events`

Create a new teaching event.

- **Auth:** secretary only
- **Validation:** Returns `422` if `event_date` is in the `public_holidays` table.
- **Body:**
```json
{
  "teaching_name_id": "00000000-0000-0000-0000-000000000001",
  "event_date": "2026-04-15",
  "start_time": "10:00",
  "cme_points_awarded": false,
  "smc_event_code": null
}
```
- **Source identity:** Supply exactly one of `teaching_name_id` or
  `global_session_type_id`. The selected source must be active in the resolved
  reporting period and within the secretary's authorised pool; a global type is
  independently active and not a pool name. `teaching_name`, `end_time`, and
  `duration_hours` are not request fields.
- **Backend snapshot and timing:**
  - `posting_code` from the current secretary subject's database-owned `users.posting_code`
  - immutable `teaching_name` display snapshot from the selected source
  - `end_time` = `start_time + session_type.duration_hours` (server-computed — NOT a request field)
  - pool sources use the consistent exact posting-specific TTF mapping duration, temporarily defaulting to `1.00` while unmapped; global sources use their server-configured duration
  - no display-text, catalogue, or cross-posting duration inference occurs
- **Returns 422 if:** the identity is missing, both identities are present, or the selected source is inactive, outside scope, or incompatible with the event date. No text lookup, canonical-name fallback, duration tiebreaker, or client-supplied end time is accepted.
- **Transaction:** the event mutation and its existing Secretary audit entry
  commit once. Audit or commit failure rolls back the event; cache invalidation
  runs only after commit.

### PUT `/secretary/teaching-events/{id}`

Edit a secretary-owned scheduled teaching event.

- **Auth:** secretary only; the event must be in the secretary's posting scope.
- **Source identity and timing:** the request supplies exactly one current
  source ID and is validated as for create. The source display snapshot and
  server-computed timing replace the old values atomically.
- **Legacy transition:** a readable legacy scheduled row with both source IDs
  null is never matched by its stored text and is not rewritten. A valid
  source-bearing update is rejected with `409`; a missing/both source payload
  is rejected by normal request validation.

### POST `/secretary/teaching-events/duplicate`

Duplicate an existing event.

- **Auth:** secretary only
- **Body:**
```json
{
  "source_event_id": "uuid",
  "event_date": "2026-04-22",
  "start_time": "10:00",
  "teaching_name_id": "00000000-0000-0000-0000-000000000001"
}
```
- **Validation:** Returns `422` if `event_date` is a public holiday.
- **Source identity:** An optional single source ID replaces the source-event
  identity; otherwise the existing identity is copied and re-authorised. A
  source event with both IDs null is readable but cannot be duplicated without
  an explicit source ID (`409`). Stored text is never used to infer one.
- **Transaction:** the duplicate and its existing Secretary audit entry commit
  together.

### DELETE `/secretary/teaching-events/{id}`

Delete a teaching event.

- **Auth:** secretary only
- **Constraint:** Returns `409` if any attendance records exist against this event.
- **Transaction:** the event is locked before the all-status dependency check;
  deletion and the existing Secretary audit entry commit together.

### POST `/secretary/teaching-events/series`

Create a recurring event series.

- **Auth:** secretary only
- **Validation:** Any occurrence that falls on a public holiday is skipped and included in the response as a warning. Other occurrences are created normally.
- **Body:**
```json
{
  "teaching_name_id": "00000000-0000-0000-0000-000000000001",
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
- **Source identity:** Supply exactly one source ID. Each materialised row
  receives the authorised source ID, immutable display snapshot, and
  server-computed timing. Pool rows use the posting-specific mapped duration,
  temporarily default to one hour while unmapped, and cannot start after 23:00;
  the series does not infer names from text or catalogue mappings.
- **Backend:** Materialises individual `teaching_events` rows per occurrence.
- **Transaction:** series metadata, every materialised occurrence, and the
  existing Secretary audit entry are one all-or-nothing operation.

### DELETE `/secretary/teaching-events/series/{series_id}`

Delete a series. Options: `scope=single&event_id=X`, `scope=following&event_id=X`, `scope=all`.

- **Auth:** secretary only
- **Constraint:** Cannot delete occurrences that have attendance records.
- **Transaction:** affected occurrences are locked in deterministic order;
  deletion and the existing Secretary audit entry commit once.

### GET `/secretary/cme-dashboard`

CME summary view for the secretary's posting site.

- **Auth:** secretary only

### GET `/secretary/residents`

List residents currently posted to the secretary's site.

- **Auth:** secretary only

### GET `/secretary/teaching-name-options`

Get available Teaching Name and global-session-type source options for the secretary event-creation dropdown.

- **Auth:** secretary only
- **Query params:** `reporting_period_id` or `event_date` optional; `programme_code` is optional but, when supplied, restricts pool options to that exact programme. An explicit period must be effectively active. When both period and event date are supplied, `event_date` must belong to the explicit period or the API returns `422`. With neither option, the backend resolves the single effectively active period containing today. Pool options are scoped to that resolved period and the Secretary's active explicit capability; global options remain separate.

- **Phase F source contract:** This endpoint now returns each active
  `teaching_names` row in the secretary's authorised programme pool and period,
  plus each active global source. Pool options expose `teaching_name_id`; global
  options expose `global_session_type_id`. An option has exactly one non-null
  ID and immutable display text. Identical display text from different source
  rows remains distinct. A pool option has the exact posting's effective
  `duration_hours` and `duration_is_mapped`; a global option has its configured
  duration. This selection endpoint does not query a catalogue, `is_tracked`,
  or resident compliance.
- **Phase F/G provenance contract:** A pool event also stores immutable
  `source_programme_code` and `source_reporting_period_id`. The selected name
  must match them exactly and the Secretary must hold capability for that exact
  programme. Deleting the name later clears only its optional ID; snapshots,
  event history, and attendance remain. Inactive global types are omitted here
  but do not hide or invalidate existing global events.
- **Resident visibility/attendance in Phase G:** event creation stores the
  source ID and immutable `teaching_name` snapshot. Runtime selection and
  attendance use the explicit pool identity with an exact reporting-period and
  programme match, or the explicit global identity first. Both-null legacy rows
  retain deterministic persisted evidence; neither path uses catalogue or
  display-text inference.

- **Response:**

```json
{
  "options": [
    {
      "teaching_name_id": "00000000-0000-0000-0000-000000000001",
      "global_session_type_id": null,
      "keyword": "Journal Club",
      "duration_hours": 1.0,
      "duration_is_mapped": false,
      "programme_code": "GERI",
      "is_global": false
    },
    {
      "teaching_name_id": null,
      "global_session_type_id": "00000000-0000-0000-0000-000000000002",
      "keyword": "Department Meeting",
      "duration_hours": 1.5,
      "duration_is_mapped": true,
      "programme_code": null,
      "is_global": true
    }
  ]
}
```
Identity: This endpoint does not deduplicate distinct `teaching_names` rows by display text. A client must return the opaque ID selected by the user, never a display string.

Session type: a pool option is a source identity. Its posting-specific mapped
duration is scheduling data and does not multiply resident compliance counts.
Phase G runtime uses persisted identity, not catalogue/global text matching.

The following legacy `is_tracked` wording is not part of the Phase F option response or scheduling contract.

Note: is_global = true entries come from global_session_types and are always excluded from PTT compliance. is_tracked = false entries from the TTF are also shown but excluded from compliance. Secretary sees a unified list — the compliance distinction is transparent to them.

---

## Resident Endpoints

### GET `/resident/events`

List teaching events available for submission.

- **Auth:** resident only
- **Period resolution:** enumerate every effectively active reporting period using stored `status` plus due `activate_on` / `deactivate_on` transitions. Residents do not select a period. Each candidate event must fall inside exactly one of those periods; its persisted-source and posting checks use that same period ID. Events in inactive/expired periods are excluded, and overlapping active periods for an event date fail closed with `409`.
- **Visibility gating:**
  1. If the resident has no `resident_postings` rows in any effectively active period → no assigned-posting visibility; return empty list with `reason: "posting_schedule_unavailable"` if no other allowed source can produce events. A missing posting covering today does not suppress historical rows.
  2. Assigned posting secretary events: derive assigned posting from `resident_postings` covering each event date with `status IN ('active', 'loa_working')`. Secretary-created events at that `posting_code` are eligible.
  3. Native programme TTSH department secretary events: derive the native programme teaching posting from explicit config/mapping, for example `programmes.native_teaching_posting_code` or `programme_teaching_posting_map`. Do not infer this mapping by string manipulation.
  4. Native programme PC-created events: include events where `teaching_events.created_for_programme_code = resident.programme_code`.
  5. Deduplicate rows by `teaching_events.id` across all sources.
  6. Filter to `event_date <= today` (no future events).
  7. Exclude events already submitted by this resident.
  8. Exclude every other candidate whose resident-specific interval directly
     overlaps a submitted attendance interval. This is a direct interval test,
     not transitive suppression through an overlap chain. Before submission all
     eligible overlapping alternatives remain visible; after one is submitted,
     that event and its directly overlapping alternatives are absent from the
     available list. Removing the attendance makes them available again when
     all other eligibility rules still pass.
  9. Apply the event-date-specific effectively active reporting-period check; never resolve historical visibility from today.
  10. For a source-backed scheduled event, require the exact
      `teaching_name_id` and source reporting period. A Secretary-created
      department-shared source may retain a different owner programme when an
      exact persisted admission and mapping exist for the Resident's native
      programme, event posting, and event-date R-year. Resolve its duration
      through that native mapping. A PC-private source remains restricted to
      its owner programme. Apply an explicit `global_session_type_id` first.
      For a both-null legacy event, use only deterministic persisted
      event/ownership/posting/date evidence. Do not use catalogue, Column K, or
      display text to classify an event.
  11. Do not show PC-created events for non-native programmes.
  12. Do not show secretary-created events from arbitrary TTSH departments unless they are either the resident's assigned/current posting or the resident's native programme department.
- **Query params:** `date_from`, `date_to`, `teaching_name`, `posting_code`. Filters apply to the combined cross-period collection and cannot widen resident scope.
- **Response metadata:** each event includes the server-resolved `reporting_period_id` / `reporting_period_label`. The top-level `active_reporting_periods[]` lists the periods considered, allowing the frontend to distinguish no active submission period from an active-period empty result without presenting a selector.

**Native visibility examples:**
- **Scenario A:** Native GRM Resident John is posted to TTSH Geriatric Medicine. John sees TTSH GRM Department Secretary events because he is posted there and GRM PC events because GRM is his native programme. The TTSH GRM secretary event source is deduped if it is both assigned posting and native programme department.
- **Scenario B:** Native GRM Resident John is posted to TTSH Rehab. John sees TTSH Rehab Department Secretary events because he is posted there, TTSH GRM Department Secretary events because GRM is his native programme department, and GRM PC events because GRM is his native programme.
- **Scenario C:** Native Rehab Resident Mary is posted to TTSH GRM. Mary sees TTSH GRM Department Secretary events because she is posted there, TTSH Rehab Department Secretary events because Rehab is her native programme department, and Rehab PC events because Rehab is her native programme.

**Future native-programme compliance attribution:** For an approved native-programme event outside the resident's assigned posting, a future compliance read resolves the assigned posting from `resident_postings` on the event date and preserves the original event. Phase G does not calculate or reclassify compliance, consult mappings, or alter the raw event/attendance evidence.

### GET `/resident/submission-periods`

Return the effectively active reporting-period metadata used by the Submission Portal's loading and empty-state classification.

- **Auth:** NHG Resident or registered Non-NHG Resident from the authenticated session.
- **Response:** `{ "periods": [{ "id", "label", "start_date", "end_date" }] }`
- **Security/UX:** this endpoint does not accept a resident ID or a selected period and does not authorize access to events. `GET /resident/events` independently enforces the applicable identity-specific scope: native Residents use period, assigned/native posting, programme ownership, persisted-source, and duplicate checks; Non-NHG Residents use one exact date-matched schedule posting and duplicate checks without programme/R-year narrowing. The frontend must not render a resident reporting-period selector.

### POST `/resident/attendance`

Submit attendance for one or more events.

- **Auth:** NHG Resident or Non-NHG Resident (`resident` or `external_resident` role)
- **Body:** `{ "event_ids": ["uuid1", "uuid2"] }`
- **Native Resident backend:**
  1. Validates event exists and is visible through the resident's allowed scheduled-event sources: assigned/current posting secretary event, native programme TTSH department secretary event, or native programme PC-created event
  2. Validates `event_date` falls within a `resident_postings` row with `status IN ('active', 'loa_working')` → `422` if outside tenure
  3. Validates persisted event evidence: an explicit pool source must match the
     event-date reporting period. A host Secretary source may keep its source
     owner programme only when the Resident's native programme has the exact
     persisted admission and posting/R-year mapping; resident timing comes
     from that native mapping. A PC-private source must match the native
     programme. An explicit global source is global-first; a both-null legacy
     event is not text-inferred. For an approved native-programme event outside
     the assigned posting, it validates only the allowed source and does not
     assign or rewrite a compliance target.
  4. Validates programme ownership: events with `created_for_programme_code` set must match the resident's `programme_code`
  5. Validates no active duplicate; a submitted-only unique index on
     `(resident_id, teaching_event_id)` is the database race boundary.
  6. Before insert, rejects a later submission whose distinct event interval overlaps an already accepted event for the same resident. The earlier accepted attendance remains unchanged; this check is separate from same-event uniqueness.
  7. Creates accepted `attendance_records` rows — **does NOT store `session_type_id`**
  8. Checks each submitted event against `weekend_exceptions` — if a weekend session has no matching rule, adds a `compliance_warning` to the response
- **Non-NHG Resident backend:** requires one exact date-matched `external_resident_postings` row and accepts every normal scheduled event at that posting. It does not resolve Teaching Name R-year mappings and does not use source programme, PC programme ownership, or Secretary capability as a submission gate. It stores only `external_attendance_records` and uses the staff event envelope for display and overlap checks.
- **Transaction/concurrency:** The complete `event_ids` list is one atomic
  batch. Transaction-scoped event advisory keys are acquired in deterministic
  order and are shared with staff event edit/delete paths; a family-specific
  subject/date advisory key then serializes submit/remove and overlap
  decisions. The service validates the whole batch before DML and commits once;
  any item, insert, or commit failure rolls back every row in the request.
- **Response:**
```json
{
  "submitted": 3,
  "errors": [],
  "compliance_warning": "1 session(s) submitted on a weekend will not count toward your PTT compliance as they do not meet the weekend exception rules for your programme."
}
```
`compliance_warning` is `null` when all submitted sessions are either weekdays or match a weekend exception rule.

An overlapping distinct event is returned as a submission conflict for the later event. No delete or replacement is performed, and the earlier accepted attendance remains available in history and compliance reads.
The available-event list normally hides that directly overlapping alternative
after the first attendance is accepted, but the submission-time conflict
remains the server boundary for stale clients, direct API requests, and atomic
batches. Removing the first attendance restores both alternatives when they
remain otherwise eligible.

### DELETE `/resident/attendance/{attendance_id}`

Remove own submitted attendance without hard-deleting its history.

- **Auth:** resident only
- **Constraint:** Can only delete own records.
- **Persistence:** Takes the shared event advisory key, the same family-specific
  subject/date advisory key used by submission, and a row lock on the current
  attendance before conditionally changing `submitted` to `removed`. A repeated
  removal is idempotent. Resubmission creates a new row/identifier; a request
  carrying an older removed identifier cannot remove that newer row.

### GET `/resident/adhoc-teaching-options`

Return date-derived posting context and one fixed ad-hoc option.

- **Auth:** NHG Resident or Non-NHG Resident (`resident` or `external_resident` role)
- **Query params:**
  - `teaching_date` required.
  - `attended_posting_code` optional. If supplied, it must equal the sole
    server-derived posting; alternate values return `422`.
- **NHG Resident backend:**
  1. Derives `assigned_posting_code` from `resident_postings` for `teaching_date` with `status IN ('active', 'loa_working')`.
  2. Requires exactly one matching posting. It returns that posting as both the
    assigned and attended option; it never infers a different department/site.
  3. Returns exactly one option: `Department/Programme Teaching [1h]`, duration
    `1.00`, null `session_type_id`, and `is_global = false`.
  4. It does not query teaching targets, mappings, or any retired
    catalogue/`details_of_training`/Column K structure.
- **Non-NHG Resident backend:**
  1. Derives the date-specific host posting from `external_resident_postings` for `teaching_date`.
  2. If no schedule row matches the date, returns `available = false` and `reason = "posting_unavailable"`.
  3. Uses that schedule posting as the only attended option and returns the same
    fixed one-hour option. Non-NHG submissions remain outside NHG compliance.
- **Response example:**
```json
{
  "date": "2026-04-15",
  "teaching_date": "2026-04-15",
  "available": true,
  "reporting_period_id": "uuid",
  "posting_code": "TTSHGerMed",
  "posting_label": "TTSH Geriatric Medicine",
  "r_year": "R2",
  "attended_posting_options": [
    {
      "posting_code": "TTSHGerMed",
      "label": "TTSH Geriatric Medicine"
    }
  ],
  "selected_attended_posting_code": "TTSHGerMed",
  "selected_attended_posting_label": "TTSH Geriatric Medicine",
  "options": [
    {
      "teaching_name": "Department/Programme Teaching [1h]",
      "keyword": "Department/Programme Teaching [1h]",
      "session_type": "Department/Programme Teaching [1h]",
      "session_type_name": "Department/Programme Teaching [1h]",
      "session_type_id": null,
      "duration_hours": 1.0,
      "posting_code": "TTSHGerMed",
      "posting_label": "TTSH Geriatric Medicine",
      "reporting_period_id": "uuid",
      "r_year": "R2",
      "is_global": false
    }
  ],
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
  "attended_posting_code": "TTSHGerMed",
  "details_of_session": "Case discussion after ward teaching"
}
```
- `teaching_date` is canonical. The compatibility-only `date` field is also
  accepted temporarily. Supplying both with the same value is valid; conflicting
  values or omitting both returns controlled `422`.
- **Backend:**
  1. Validates `teaching_date` is not a public holiday → `422` if PH.
  2. Derives assigned posting for the selected date:
     - NHG Resident: `resident_postings` date match with `status IN ('active', 'loa_working')`.
     - Non-NHG Resident: `external_resident_postings` date match.
  3. Accepts no `teaching_name`; unknown request fields, including arbitrary
     names and targets, return `422`.
  4. Uses only the derived posting. A supplied `attended_posting_code` must
     equal it; a second posting is not selectable.
   5. Before either row is inserted, takes the native/external subject-date
      locks for every spanned date and rejects a full-datetime interval that
      overlaps an already submitted distinct event for that Resident. A one-hour
      `23:00–00:00` interval is valid, the end belongs to the next date, and exact
      boundary contact is allowed. A conflict uses controlled `409` and preserves
      the earlier attendance.
  6. Calls the narrow PostgreSQL ad-hoc creation function. It derives trusted
     subject identity and family from the signed transaction-local context,
     creates `teaching_events` with the fixed display snapshot
     `Department/Programme Teaching [1h]`, duration `1.00`, null
     `session_type_id`, and the matching immutable
     `created_by_resident_id` or `created_by_external_resident_id`, and inserts
     only the corresponding attendance family. The client supplies none of
     those ownership fields.
  7. The function and service share the caller transaction and commit once.
     Failure leaves neither an orphan event nor provisional attendance.
  8. `end_time` = `start_time + 1 hour`; no catalogue option or target mapping
     can override that fixed record.
  9. Checks weekend exception — returns `compliance_warning` if session will not count for native compliance.
- **NHG compliance treatment:** All countable NHG Resident ad-hoc sessions map to `Department/Programme Teaching [1h]` and count under the assigned posting for the selected date. They do not count under the attended TTSH department unless that department is also the assigned posting.
- **Non-NHG treatment:** Non-NHG ad-hoc sessions create `external_attendance_records` only for attendance storage. They do not create native `attendance_records`, receive no NHG compliance attribution, and never enter NHG numerator, denominator, surplus, snapshots, clawback, or native reports.
- **Schema/API note:** `details_of_session` is stored on the event as
  display/audit-only context and has no operational or compliance use.
  `attended_posting_code` is an optional confirmation of the single
  server-derived posting and has no dedicated persisted field.

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
      "target_100": 1.5,
      "target_70": 2,
      "achieved_and_counted": 1.5,
      "shortage": 0,
      "percentage": 1.0,
      "met_70pct": true,
      "colour": "green",
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

`percentage` is retained unrounded and is the canonical predicate for `met_70pct` and colour. `target_70 = ceil(target_100 × 0.70)` is a displayed whole-session threshold and must not make a capped 100% fractional-target result fail. When a resident changes R-year mid-period, the response's posting total sums targets and separately capped achievement from each physical-posting/session-type/R-year context; it never merges raw attendance before those caps or duplicates active months.

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
This is the shared NHG/registered Non-NHG Resident request. The backend normalizes MCR, queries both resident identity tables in one request, and resolves exactly one active match. It returns `user.role = resident` for a native match or `user.role = external_resident` for an external match. The frontend sends no explicit external role, performs no prefix inference, and makes no fallback request. **No password required in Phase 1.**

Explicit `{ "role": "external_resident", "mcr": "..." }` remains temporarily accepted for compatibility with older clients. That compatibility path considers only the external identity for authentication and never falls back to a native resident.

- **Native resident response:**
```json
{
  "user": {
    "id": "<uuid>",
    "role": "resident",
    "name": "John Tan",
    "programme_code": "GRM",
    "mcr": "M12345A"
  },
  "csrf_token": "<opaque session-bound CSRF value>",
  "session_refresh_required": false
}
```

- **Registered Non-NHG resident response:**
```json
{
  "user": {
    "id": "<external_residents.id>",
    "role": "external_resident",
    "name": "<resident name>",
    "home_cluster": "NUH",
    "mcr": "E12345A"
  },
  "csrf_token": "<opaque session-bound CSRF value>",
  "session_refresh_required": false
}
```

Success sets `__Host-mata_session=<opaque>` with `Secure; HttpOnly; SameSite=Strict; Path=/`, no `Domain`, and no persistent `Max-Age` or `Expires` in production. No `access_token`, refresh token, or `token_type` is returned in normal cookie mode.

For staff login, the browser request target is the frontend-origin
`/api/v1/auth/login`; the Vercel rewrite forwards it to this endpoint without a
redirect. Supabase password authentication and upstream JWT verification occur
only inside the backend. Neither upstream access nor refresh tokens are
persisted, returned, placed in the cookie, or used as the MATA request
credential.

- **Error responses:**
  - `401` - MCR not found or the resolved native/external resident is inactive; the response does not disclose which condition occurred
  - `401` - the MCR exists in both resident identity tables; cookie mode uses the same generic invalid-credentials outcome and the response/logs contain no identity details
  - `401` - Invalid email or password (admin/secretary)

### GET `/auth/me`

Return current identity from the validated opaque application session, together with `csrf_token` and `session_refresh_required`. This route does not return, rotate, or expose the session cookie and does not mutate session timestamps.

- Resident: returns `residents` row identity fields (`id`, `role`, `name`, `programme_code`, `mcr`) plus display-only `current_posting_code` and `current_posting_label` when a usable `resident_postings` row exists in the single effectively active period containing today. Within that period, display resolution prefers today's row, then the nearest future row, then the nearest recent past row. It does not return a trusted `posting_code` claim.
- Resident current posting for authorization-sensitive endpoints is still resolved server-side from `resident_postings` at request time.
- Non-NHG Resident: returns `external_residents` row identity fields (`id`, `role`, `name`, `mcr`, `home_cluster`) plus display-only `current_posting_code` and `current_posting_label` when a usable `external_resident_postings` row overlaps the single effectively active period containing today. Within that period, display resolution prefers today's row, then the nearest future row, then the nearest recent past row. It does not return `current_nhg_posting_code`, trusted `posting_code`, posting schedule, staff actor metadata, `admin_level`, `programme_code`, or `programme_scope`.
- Admin/Secretary: returns `users` row fields + scope, including `admin_level` for admin accounts and saved staff actor metadata:
  - `current_staff_actor_name`
  - `staff_actor_name_required` (`true` when the staff account has no saved non-blank actor name)
  - `staff_actor_name_updated_at`
  - `staff_actor_name_updated_by_user_id`

### POST `/auth/session/refresh`

Requires an active cookie session and valid CSRF. It atomically revokes the current session row and creates one replacement in the same family, preserving or tightening the parent's idle deadline, carrying forward the parent's last qualifying-activity timestamp, preserving absolute expiry, and rotating both cookie and CSRF state. Refresh is not qualifying activity, cannot slide either deadline, and cannot delay eligibility for the next real activity touch. Concurrent refresh permits exactly one child; the losing attempt receives a controlled non-clearing `409` and cannot create another replacement. The old cookie and old CSRF material are unusable.

### POST `/auth/logout`

Logout derives keyed token and CSRF digests from the presented cookie/header and sends only those digests to the auth-helper database boundary. After production origin and raw-authorization guards, the exact cookie-mode logout route bypasses ordinary active-session hydration and middleware CSRF handling; the termination helper alone evaluates the proof. Normally both digests identify the same active row, or the same row revoked only as `rotated`. A stale tab may instead present the current active child token with a rotated ancestor's CSRF value; that pair is accepted only when both rows have the same subject, subject generation, family, and authentication source, the child is before its idle and absolute deadlines, and the rotated proof is before the immutable family absolute deadline. The auth-only helper derives the subject and rotation family server-side; callers cannot supply a subject, session ID, or family ID. It then revokes every active row in only that family, returns no identity/context material, and grants no hydration, touch, rotation, or refresh authority. This permits a logout that began before refresh, or a stale tab updated to the child cookie, to terminate the refreshed child. Other device/session families remain active. Missing, malformed, cross-family, expired, or otherwise mismatched proof revokes nothing and leaves the shared browser cookie unchanged.

The runtime capability cannot execute the termination helper. Missing, malformed, mismatched, absolute-expired, idle-expired active, or non-`rotated` revoked proof revokes nothing. The server-side revocation effect remains idempotent; the route clears the browser cookie only when that request's reviewed proof revokes at least one row in the presented family.

The response remains HTTP `200` with `success: true` after the endpoint completes. `server_logout_confirmed` is `true` only when that request's reviewed proof revokes at least one row; this is the same proof-positive branch that clears the browser cookie. It is `false` for every zero-result case, including missing, malformed, mismatched, expired, or already-inert proof. The response discloses no revocation count, reason, session identifier, family identifier, or identity. A `false` value means only that this request did not obtain positive server-revocation confirmation; it is not an assertion that a server session exists.

The production browser clears local identity, CSRF, protected caches, upload
state, and authenticated UI immediately before awaiting this result. It treats
only the exact boolean `server_logout_confirmed: true` as confirmed server
revocation. A false value, malformed response, network ambiguity, or exhausted
bounded retry remains explicitly pending/unconfirmed and blocks hydration and
ordinary protected requests. Cross-tab/reload ordering uses only a
non-sensitive pending tombstone and resolution watermark; no token, cookie,
CSRF value, identity, MCR, role, or scope is persisted by that mechanism.

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

Changes to role, admin level, programme scope, posting, or active state increment `session_generation` and revoke all active application-session families for the subject. Display-only changes do not create authorization authority.

A self authorization change remains supported when it passes the last-active-Master-Admin guard. In one transaction, the service audits the planned final state while the request-start actor is still valid, applies the account mutation, and makes subject-wide session invalidation the final protected database statement before commit. Its audit deliberately records `revoked_session_count = null` and `revoked_session_count_is_exact = false`; a protected statement cannot safely read an exact count after invalidating its own signed context. Non-self changes continue to record the exact integer revocation count.

#### POST `/admin/staff-accounts/{user_id}/reset-password`

```json
{
  "password": "new working password"
}
```

Before the upstream password reset, the backend serializes the subject, commits `session_issuance_blocked = true`, and revokes active application sessions. Concurrent reset attempts serialize. On success it updates the credential, increments `session_generation` again, clears the issuance block and staff actor name, and commits. A failed upstream reset leaves issuance blocked and sessions revoked so an authorized retry cannot race with new login or rotation. The password is not returned or logged.

A Master Admin cannot reset the password of the same staff account through this endpoint. Self-reset returns controlled `422` before any subject lookup side effect, issuance block, session revocation, commit, audit write, or upstream Supabase call.

### PUT `/auth/settings`

Update password. Admin/secretary only.


---

## Non-NHG Resident Endpoints

Non-NHG Residents are Phase 5B pre-compliance scope. They use separate identity and attendance tables. They are never stored in `users`, never stored in native `residents`, and never represented through native `resident_postings`. Backend/internal route and table names may continue to use `external_resident`.

### GET `/external-residents/registration-options`

Return the public institutions and programme availability states from `programme_institution_posting_map`. The response never exposes `posting_code`, and registration independently resolves every submitted pair through the same trusted service.

```json
{
  "institutions": [
    { "code": "TTSH", "name": "TTSH" }
  ],
  "programmes": [
    {
      "programme_code": "GERI",
      "programme_name": "Geriatric Medicine",
      "institutions": [
        {
          "institution_code": "TTSH",
          "available": true,
          "status": "active"
        }
      ]
    }
  ]
}
```

Current TTSH response rules:

- exactly one institution, TTSH;
- exactly 24 programmes backed by active TTSH mapping rows, in deterministic programme seed order;
- `programme_code` and `programme_name` come from `programmes.code` and `programmes.name`, so clients can display labels such as `GERI - Geriatric Medicine`;
- every returned TTSH programme/institution entry has `available = true` and `status = active`;
- the inactive TTSH mappings for `FM`, `PATH`, `SPORTSMED`, and `PALLMED` are omitted, and there are no pending TTSH mappings;
- inactive here means unavailable only for Non-NHG programme/institution registration and posting-schedule selection, not global programme deactivation;
- no `posting_code` appears anywhere in the public response;
- no KTPH, WH, or other institution appears until mapping rows for it exist.

The response is data-driven. Adding a future institution's rows makes it appear without application changes, and changing a valid mapping to `active` makes that pair available without frontend changes.

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
  2. The normalized `mcr` must not exist in native `residents`.
  3. The normalized `mcr` must not exist in `external_residents`. Migration `20260726_000025` also enforces the cross-table invariant with serialized database triggers, so the service preflight is not the only concurrency boundary.
  4. Each schedule row must have `start_date <= end_date`; schedule rows must not overlap.
  5. Each schedule row resolves exactly one `active`, non-null canonical posting code from `programme_institution_posting_map`. The client must not send or choose `posting_code`.
  6. Pending, inactive, missing, malformed, or referentially invalid mapping rows return controlled `422` errors. Pending uses `Posting configuration for this programme is pending.` so the UI can distinguish configuration readiness from invalid user input.
- **Writes:** `external_residents` plus one `external_resident_postings` row per resolved schedule row. Each schedule row persists the validated `programme_code` and backend-resolved `posting_code`. Do not create `users`, native `residents`, or native `resident_postings` rows.
- **Response convenience:** May return `current_nhg_posting_code` as today's derived/current posting for display/backward compatibility.
- **Duplicate/conflict:** `409` when MCR already exists.
- **Transactionality:** all schedule rows are resolved and validated before any insert. One unavailable row prevents creation of both the resident and all schedule rows.

### PUT `/external-residents/me/posting`

Update the Non-NHG Resident's current NHG posting pointer through the trusted mapping resolver. Route name remains for compatibility with older clients; schedule-aware clients should use `/external-residents/me/posting-schedule`.

- **Auth:** Non-NHG Resident only (`external_resident` role)
- **Body:**
```json
{
  "programme_code": "DR",
  "institution": "KTPH"
}
```
- **Validation:** the normalized pair must have an active mapping with a valid canonical posting FK. Client-supplied posting codes are forbidden.
- **Behaviour:** updates the authenticated Non-NHG Resident's current/cache pointer and current `external_resident_postings` row, preserving both the validated `programme_code` and resolved `posting_code`. No native `resident_postings` rows are created.

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
- **Validation:** same schedule-row validation and trusted mapping resolution as registration. Pending/inactive/missing/malformed mappings return controlled `422`; the existing schedule remains unchanged.
- **Behaviour:** replaces `external_resident_postings`, persists each validated `programme_code` with its resolved `posting_code`, updates the current/cache pointer from the resolved schedule, and never creates native `resident_postings`.

The registration mapping is isolated from `programmes.native_teaching_posting_code`, `posting_codes.supports_secretary_events`, Secretary programme pools, native event visibility, and compliance attribution. Activating an external-registration mapping changes none of those capabilities.

### GET `/resident/events` for Non-NHG Residents

The same route may support NHG and Non-NHG Residents through identity branching.

- For native `role = resident`, use native Phase 5A behaviour from `resident_postings`.
- For `role = external_resident`, resolve the date-matching `external_resident_postings` row for each candidate event. Its `posting_code` is the scheduled-event authorization boundary; `external_residents.current_nhg_posting_code` may be used only as a current/cache/backward-compatibility pointer.
- If no `external_resident_postings` row matches a requested date, return unavailable/no posting for that date.
- Return every normal scheduled Secretary or Programme PC event whose
  `event.posting_code` exactly matches that date-matched schedule posting.
  Programme ownership, Teaching Name source programme, and
  `supports_secretary_events` do not narrow this Non-NHG listing because
  Non-NHG attendance is excluded from NHG compliance and no R-year mapping is
  resolved.
- Apply the exact posting match independently for every schedule row/date. Do
  not infer or broaden posting access from programme names, prefixes, teaching
  targets, the retired catalogue, fuzzy matching, or a first candidate.
- Return normal scheduled events only. Exclude resident-created ad-hoc events, events outside the schedule date range or in a schedule gap, and events blocked by existing reporting-period or status rules.
- Filter `event_date <= today`.
- Exclude events already submitted by that Non-NHG Resident in `external_attendance_records`.
- After one attendance is submitted, also exclude other candidates whose staff
  event envelope directly overlaps it. Removing that attendance restores all
  otherwise eligible alternatives.
- Do not apply native NHG compliance catalogue/denominator logic to Non-NHG Residents.

### POST `/resident/attendance` for Non-NHG Residents

The same route may support NHG and Non-NHG Residents through identity branching.

- For `role = external_resident`, authorize against the date-matched `external_resident_postings` row, not token claims or the current/cache pointer.
- A normal scheduled Secretary or Programme PC event requires the exact posting
  match. Programme ownership, Teaching Name R-year mapping, and Secretary
  capability are not submission gates for Non-NHG Residents. Another posting
  returns controlled `422`; the normal reporting-period, status, date,
  duplicate, and staff-envelope overlap checks still apply.
- Create `external_attendance_records`, not native `attendance_records`.
- Active duplicates are protected by the submitted-only unique index on
  `(external_resident_id, teaching_event_id)`; removed history is retained.
- External submissions use the same deterministic event-lock and
  subject/date advisory-lock protocol as native submissions, including
  distinct-event overlap rejection and controlled same-event conflicts.
- Weekend non-exception attendance is stored and returns `compliance_warning`.
- Do not store `session_type_id`.
- Do not include the row in NHG compliance.

### POST `/resident/adhoc-teaching` for Non-NHG Residents

The same route may support NHG and Non-NHG Residents through identity branching.

- For `role = external_resident`, derive host posting from `external_resident_postings` for `teaching_date`.
- If no schedule row matches `teaching_date`, return unavailable/no posting for selected date.
- `GET /resident/adhoc-teaching-options` returns the one date-derived posting
  and fixed `Department/Programme Teaching [1h]` option.
- A client may only omit or repeat that posting; it cannot choose a separate
  attended department/programme or Teaching Name.
- No catalogue, target, mapping, or Column K data is used for this ad-hoc flow.
- PH hard-block with `422`.
- The narrow PostgreSQL function derives the exact Non-NHG subject, persists
  immutable `created_by_external_resident_id`, and creates the event plus
  `external_attendance_records` in the same caller transaction. Optional
  `details_of_session` is persisted as display/audit-only event context.
- Another external Resident and every native Resident are denied visibility
  and attachment; ordinary direct ad-hoc table inserts are denied.
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
- **Scope:** Programme-PC authorization is based on persisted event/source evidence, never a display-text, catalogue, or target lookup. A pool-backed event requires its exact persisted source programme/reporting-period scope and exactly one matching Non-NHG schedule row for that programme and posting. A global or deterministic both-null legacy/ad-hoc event requires either the event's persisted PC programme or exactly one matching date-based Non-NHG schedule programme. Event-date reporting-period or schedule ambiguity fails closed. An explicit `reporting_period_id` permits authorized inactive historical reporting. Explicit master admin may access all programmes. Null/empty `programme_scope` means no access.
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
{ "detail": "Unauthorized" }                                                    // 401 invalid, expired, revoked, rotated, or generation-stale app session
{ "detail": "Forbidden — admin role required" }                                  // 403
{ "detail": "Forbidden" }                                                       // 403 missing/mismatched CSRF or unapproved production Origin
{ "detail": "Teaching event not found" }                                         // 404
{ "detail": "Cannot delete event with attendance" }                              // 409
{ "detail": "Duplicate attendance submission" }                                  // 409
{ "detail": "Attendance overlaps an earlier accepted event" }                    // 409
{ "detail": "A TTF upload or posting-group replacement for this programme is in progress" } // 409
{ "detail": "Another TTF upload for this scope is in progress" }                 // 409
{ "detail": "Unsupported media type" }                                           // 415 public login/registration is not application/json
{ "detail": "No active reporting period is available" }                          // 422
{ "detail": "TTF validation failed", "errors": [...] }                           // 422
{ "detail": "Event date is a public holiday — event creation not allowed" }      // 422
{ "detail": "Attendance submission invalid: event date is outside your tenure at this posting" }  // 422
{ "detail": "Teaching event is outside the Resident scope" }                         // 422
{ "detail": "Too many requests" }                                                // 429 persistent limit exceeded; Retry-After supplied
{ "detail": "Authentication service unavailable" }                              // 503 session store unavailable; shared cookie unchanged
```
