# 5B-H-D Session Transport Hardening Plan

> **Current contract:** `docs/security.md`. This file is retained as dated
> planning evidence and does not override the current security contract.

Status: H-D implemented and locally verified; deployment smoke pending; H-E was excluded from H-D scope and is reconciled in the post-H-D appendix
Last updated: 2026-07-26

## 1. Purpose

5B-H-D defines the session transport hardening implemented after the earlier protected-UAT security cut. It replaces the temporary browser-visible bearer-token transport with backend-owned opaque PostgreSQL sessions, strict cookies, CSRF, and same-origin API transport.

This document began as the design plan. The implemented state and exact local evidence are recorded here and in `docs/archive/security/phase-5b/5b_h_d_production_security_implementation.md`. Full RLS, Phase 6 compliance, final close, snapshots, and clawback are not part of H-D.

> **Current descendant override:** AUD-M-06 supersedes H-D's original
> best-effort/logout-ordering statements. Local identity and protected state
> now clear immediately; server revocation is confirmed only by
> `server_logout_confirmed = true`, and every unconfirmed outcome remains
> fenced. Unqualified logout completion statements retained elsewhere in this
> plan describe the historical H-D target, not the current contract. See
> `docs/archive/security/phase-5b/5b_h_m06_reliable_logout.md`.

## 2. Historical Pre-H-D Temporary State

The following bearer/Supabase-browser description is retained only as the pre-H-D design baseline:

- Staff users sign in with the browser Supabase client in `VITE_AUTH_MODE=supabase`.
- The frontend retrieves the current staff Supabase access token and sends it to the backend as `Authorization: Bearer`.
- NHG Resident and registered Non-NHG Resident MCR login returns a backend-signed MATA resident session token.
- MATA resident session tokens are browser-visible and stored through the frontend auth-session store.
- Logout clears local MATA app identity and calls local Supabase sign-out for staff, but full server-side session invalidation and refresh-token rotation are not complete.
- Production/Supabase backend mode rejects raw `X-User-*` identity headers, but bearer-token theft remains a browser compromise risk.

This state was the historical H-C protected-UAT posture and is not the current H-D transport.

## 2A. Implemented 5B-H-D State

Production/Supabase mode uses backend-owned opaque PostgreSQL sessions. The browser receives the `HttpOnly`, `Secure`, `SameSite=Strict`, host-only `__Host-mata_session` cookie and retains only identity plus the non-secret CSRF synchronizer value in memory. Unsafe methods require `X-CSRF-Token` and an approved `Origin`; production frontend API traffic uses same-origin relative `/api/v1` requests with credentials.

Staff password authentication is backend-mediated through Supabase, and no Supabase access/refresh token is returned to or persisted by the browser. Login, Non-NHG registration, and registration-options routes are intentionally public application entry points. They remain bounded by exact-origin checks where applicable, JSON-only mutations, generic errors, and persistent PostgreSQL rate limits. A Vercel outer gate is not an application-auth requirement.

Session and CSRF credentials are 256-bit values stored only as keyed digests. Rotation is serialized by subject, transaction-scoped family advisory lock, and locked/refreshed session row, with a unique parent-to-child constraint. Logout revokes a device session family. Subject generation fencing invalidates sessions after authorization change, password reset, or deactivation and prevents reset/rotation races from resurrecting access.

Revision `20260722_000023` creates `app_sessions` and subject-generation state. Revision `20260722_000024` revokes application-object and default privileges from `PUBLIC` and optional browser roles `anon`/`authenticated`. That privilege boundary is not full RLS; full RLS is Phase 5B-H-E.

Code completion and local verification do not prove that the deployed environment has these controls.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED

## 3. Historical Target Architecture Options

| Option | Shape | Benefits | Costs/risks | Recommendation |
|---|---|---|---|---|
| BFF session owner | Backend owns app sessions, stores/refreshes upstream tokens server-side, and exposes only `HttpOnly` cookies to the browser. | Best browser-token reduction; centralizes authz; aligns with backend-mediated app data. | More backend endpoints, session store, CSRF, refresh, logout, and test complexity. | Preferred end state. |
| Backend-managed app cookies wrapping Supabase/MATA sessions | Frontend may initially obtain Supabase/MATA credentials, then exchanges them once for backend app cookies; browser no longer transports app bearer tokens after exchange. | Incremental path from current implementation; can keep Supabase Auth as identity provider. | Must carefully clear browser-visible tokens after exchange and handle refresh without reintroducing token storage. | Recommended staged path. |
| Continue Supabase client-only staff sessions | Keep browser Supabase tokens and only tighten CSP/CORS/XSS controls. | Lowest implementation cost. | Does not remove browser-visible bearer-token risk; weak fit for real production/public use. | Not sufficient beyond protected UAT. |
| Hybrid transitional mode | Support both bearer and cookie transport behind explicit environment flags while migrating tests/users. | Safer rollout and rollback. | Two auth paths increase complexity and must have an expiry date. | Acceptable only as a short migration slice. |

## 4. Selected and Implemented Target

The selected design is backend-managed application-session cookies for all roles, with backend-mediated authorization remaining the source of truth.

Required properties:

- The production host-only cookie is `__Host-mata_session` with `HttpOnly`, `Secure`, `SameSite=Strict`, and `Path=/`.
- Unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) require a CSRF token that is independent from the session cookie.
- Backend validates session state on every protected request and derives role, staff scope, resident id, external resident id, posting scope, and admin level from trusted backend state.
- Supabase `user_metadata` is never used for MATA authorization.
- Resident posting/programme claims in client-visible state are display-only and never trusted for access control.
- Staff, NHG Resident, and Non-NHG Resident sessions have separate creation paths but converge into one backend identity shape.
- Logout invalidates the backend session server-side and clears cookies.
- Refresh/rotation uses opaque session ids backed by PostgreSQL `app_sessions`.
- Session keys and refresh material are stored server-side only.

## 5. CSRF Design

Cookie transport makes CSRF protection mandatory for unsafe API methods.

Implemented design:

- Backend issues an opaque CSRF token after login/session hydration.
- CSRF token is readable by the frontend only as a non-secret anti-CSRF value, not as an auth credential.
- Frontend sends the token in a custom header, for example `X-CSRF-Token`, on unsafe methods.
- Backend validates that the CSRF token matches the active backend session.
- `GET`, `HEAD`, and health/readiness endpoints remain side-effect-free.
- CORS remains an exact allowlist; never rely on CSRF alone for origin control.
- Failed CSRF validation returns a generic `403` without revealing session internals.
- Tests cover missing, mismatched, replayed-after-logout, and rotated token cases.

The selected pattern is a per-session synchronizer token. The raw value exists only in frontend module memory; PostgreSQL stores only its keyed digest. Rotation and logout invalidate the old CSRF state.

## 6. Implemented Backend Changes

The implementation slices were completed as follows:

1. Session store design.
   - PostgreSQL stores the keyed token and CSRF digests, subject id/type and generation snapshot, auth source, family/rotation state, expiry/revocation state, and optional keyed user-agent hash.
   - It stores no raw session, raw CSRF, IP address, role, or scope.
   - Migration `20260722_000023` adds the durable session and subject-generation state; `20260722_000024` adds browser-role grant hardening.

2. Cookie/session endpoints.
   - Login issues the opaque application cookie.
   - `/auth/me` resolves the cookie to the current identity and CSRF state without rotating it.
   - `/auth/session/refresh` performs serialized one-winner rotation.
   - `/auth/logout` revokes the current family and clears the cookie only when
     the presented proof produces the proof-positive confirmation result.

3. Staff Supabase exchange.
   - The backend performs the Supabase password call, verifies the returned access token, maps `sub` to `users.supabase_user_id`, and discards upstream credentials.
   - Authorization state is reloaded from `users`; Supabase `user_metadata` is never authoritative.

4. Resident MCR session exchange.
   - Keep MCR credential checks server-side.
   - Issue backend app cookie instead of returning a browser-stored MATA bearer token.
   - Keep native and external resident tables separate.

5. Middleware update.
   - Resolve normal production identity from the backend session cookie.
   - Historical H-D `bearer_compat` required explicit transport selection and
     a production rollback opt-in. H-E supersedes this: mandatory production
     RLS requires cookie transport, so the current binary cannot enable the
     compatibility path.
   - Preserve production rejection of raw `X-User-*` identity headers.

6. Security controls.
   - Add CSRF dependency/middleware for unsafe methods.
   - Add cookie flags and domain/path configuration tests.
   - Add rate-limit keys that use verified backend session identity.
   - Add safe error handling for expired, revoked, missing, and malformed sessions.

## 7. Implemented Frontend Changes

The frontend slices were completed as follows:

1. Auth transport.
   - App access tokens are not stored in `sessionStorage` or `localStorage`.
   - Routine `Authorization: Bearer` injection was removed.
   - Axios uses credentialed requests.

2. Staff login.
   - Staff credentials are submitted to the MATA backend for mediated Supabase password authentication.
   - Continue showing generic sign-in errors and rate-limit feedback.

3. Resident login.
   - Submit MCR to backend and receive only cookie-backed app session state.
   - Hydrate identity from backend session endpoint.

4. CSRF header.
   - Store the non-secret CSRF value only in frontend module memory.
   - Attach CSRF header to unsafe methods only.
   - Clear token on logout/session expiry.

5. Logout and hydration.
   - Clear local identity and protected state immediately, record explicit
     pending/unconfirmed state, and attempt backend logout with memory-only
     proof.
   - Block hydration and protected requests until proof-positive confirmation
     or a successful replacement login resolves the matching lifecycle.
   - Treat hydration failures as local state reset without leaking tokens.
   - Keep route guards synchronous and based on hydrated identity, not raw token claims.

6. Cleanup.
   - Browser Supabase and bearer-token storage clients were removed from the normal path.
   - Frontend contract tests reject app bearer persistence and injection in production cookie mode.

## 8. Verification Contract

Final local H-D evidence is recorded in `docs/archive/security/phase-5b/5b_h_d_production_security_implementation.md`: `1104 passed, 7 warnings` for the complete backend suite; `230 passed, 1 warning` for the focused security set; `13 passed` for PostgreSQL security integration; 20/20 process-isolated one-winner rotation repeats; and `78 passed` plus lint, typecheck, and production/Supabase build for the frontend. Deployment/manual checks remain pending.

Backend tests:

- Cookie flags: `HttpOnly`, `Secure`, `SameSite`, path, max-age/expiry.
- Staff Supabase exchange maps to backend `users` row and ignores `user_metadata`.
- NHG Resident and Non-NHG Resident sessions resolve to separate subject tables.
- Raw `X-User-*` headers remain rejected in production/Supabase mode.
- Missing, expired, revoked, rotated, malformed, and wrong-role sessions fail safely.
- Logout revokes server-side state and clears cookies.
- CSRF missing/mismatched/replayed tokens fail on unsafe methods.
- Rate-limit keys use verified session identity.

Frontend tests:

- Auth session store no longer persists app access tokens in cookie mode.
- Shared HTTP client uses cookie credentials and CSRF headers, not stored bearer tokens.
- Staff/resident login and hydration update app identity from backend session responses.
- Logout calls backend logout and clears local state.
- Source-level contract tests reject forbidden browser token transport in production cookie mode.

End-to-end/manual tests:

- Sign in/out for Master Admin, Programme PC, secretary, NHG Resident, and Non-NHG Resident.
- Open a second tab and verify hydration from cookie-backed session.
- Revoke/logout in one tab and verify unsafe actions fail in the other.
- Attempt unsafe method without CSRF header.
- Attempt API calls from unapproved origin.
- Confirm no app access token appears in `sessionStorage`, `localStorage`, browser-readable config, or normal API request headers.

## 9. Rollback

Rollback is emergency-only:

- The legacy bearer rollback flag is not a current production switch. H-E
  requires RLS and cookie transport.
- If cookie mode breaks after deployment, restrict access while diagnosing and
  use a coordinated application/database version rollback with forced
  reauthentication; do not relax the current RLS requirement in place.
- Revoke new backend sessions and clear cookies through logout/expiry response.
- Rotate session-signing or encryption material if exposure is suspected.
- Migration `20260722_000023` downgrade removes session state and generation columns and therefore requires an application rollback coordinated with forced reauthentication.
- Migration `20260722_000024` downgrade intentionally does not recreate unknown broad grants; restore only an independently reviewed prior grant set.
- Document rollback trigger, operator, and follow-up owner.

Rollback must not re-enable raw `X-User-*` production trust, weaken CSRF/cookie settings, or relax CORS.

## 10. Risks And Decisions

Resolved implementation choices:

- PostgreSQL durable session store.
- Same-origin proxy and host-only `__Host-mata_session` cookie.
- `SameSite=Strict`.
- Fully backend-mediated staff password authentication through Supabase.
- Opaque session-family rotation with bounded idle and absolute lifetimes.
- Per-session synchronizer CSRF token.
- Keyed user-agent hash recorded for audit signal but not used as an authorization bypass.
- Separately configured staff and resident timeouts.
- Subject generation fencing and subject-wide revocation.
- Emergency-only, double-opted-in production bearer compatibility.

Known risks:

- Cookie mode is harder to test across Vercel preview domains and custom API domains.
- A partial migration could create two divergent auth paths if the fallback window is not short.
- CSRF bugs can block valid users or leave unsafe methods exposed.
- Supabase staff password flows must avoid moving private credentials into logs or app telemetry.

## 11. Acceptance Criteria

The code and local-verification criteria below are satisfied. Deployed Vercel/Supabase configuration, migrations, grants, cookie behavior, and post-deployment smoke remain separate evidence.

- No app access token or refresh token is stored in `sessionStorage` or `localStorage`.
- Normal app API calls no longer send app bearer tokens from browser storage.
- All protected roles hydrate through backend session cookies.
- Cookies are `HttpOnly`, `Secure`, and have the approved `SameSite` setting.
- Unsafe methods require valid CSRF tokens.
- A proof-positive logout invalidates backend session state and clears the
  presented cookie; every other outcome remains explicitly unconfirmed.
- Staff authorization still derives from `users.supabase_user_id` and DB-owned role/scope fields.
- NHG Resident and Non-NHG Resident sessions remain table-separated and correctly scoped.
- Raw identity headers remain rejected in production/Supabase mode.
- Tests cover session creation, hydration, CSRF, expiry, rotation, logout, revocation, and cross-role denial.
- 5B-H-C smoke is updated to include cookie/session checks before production/public launch.

Full RLS is specifically Phase 5B-H-E and was not implemented by H-D privilege revocation.

## 12. Post-H-D H-E Session Integration

H-E subsequently integrates the H-D session envelope with the restricted PostgreSQL boundary:

- intentionally unauthenticated login/registration, initial session issuance, and shared session/rate-limit infrastructure use the distinct `mata_auth_internal` helper credential, which has no direct application-table or sequence privilege;
- protected handlers use the non-owner, `NOBYPASSRLS` `mata_app_runtime` capability;
- middleware-resolved session identity and authorization fingerprint are mandatory expected bindings, but PostgreSQL independently reloads the session and current subject before installing signed transaction-local context;
- ordinary protected requests take the shared session-family context lock; refresh and valid-session logout use the exclusive path so they do not attempt an in-transaction shared-to-exclusive lock upgrade;
- every new root SQLAlchemy transaction reinstalls and revalidates context after commit or rollback; transaction end clears context and expires ORM identity-map state;
- `app_sessions` is helper-only under H-E. The RLS path performs fresh locked SQL inside reviewed functions, while the non-RLS ORM fallback retains `populate_existing=True`;
- invalid/stale session context is a controlled unauthorized outcome, while SQLAlchemy, PostgreSQL, transaction, connection, and pool errors remain unexpected failures;
- transaction-local advisory locks and signed GUCs cannot survive commit/rollback as valid pooled-connection authority.

The H-E policy and lifecycle evidence belongs in `docs/archive/security/phase-5b/5b_h_e_full_rls_implementation.md`. It does not change the historical H-D test counts in this document and is not evidence of deployed Supabase behavior.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED
