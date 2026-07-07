# 5B-H-D Session Transport Hardening Plan

Status: Planning complete; implementation not started
Last updated: 2026-07-06

## 1. Purpose

5B-H-D defines the deeper session transport hardening required after the immediate protected UAT security cut. Its purpose is to replace temporary browser-visible bearer-token transport before real production, broader public use, or any deployment where Vercel access protection is not the primary outer gate.

This is a plan only. It does not implement cookies, CSRF, migrations, RLS, Supabase grants, Phase 6 compliance, final close, snapshots, or clawback.

## 2. Current Temporary State

The current 5B-H UAT baseline accepts a controlled, protected deployment with known temporary transport risks:

- Staff users sign in with the browser Supabase client in `VITE_AUTH_MODE=supabase`.
- The frontend retrieves the current staff Supabase access token and sends it to the backend as `Authorization: Bearer`.
- NHG Resident and registered Non-NHG Resident MCR login returns a backend-signed MATA resident session token.
- MATA resident session tokens are browser-visible and stored through the frontend auth-session store.
- Logout clears local MATA app identity and calls local Supabase sign-out for staff, but full server-side session invalidation and refresh-token rotation are not complete.
- Production/Supabase backend mode rejects raw `X-User-*` identity headers, but bearer-token theft remains a browser compromise risk.

This state is acceptable only for protected stakeholder UAT when 5B-H-C smoke confirms deployment protection, exact CORS, no backend-secret exposure, and no direct sensitive Supabase app-table access.

## 3. Target Architecture Options

| Option | Shape | Benefits | Costs/risks | Recommendation |
|---|---|---|---|---|
| BFF session owner | Backend owns app sessions, stores/refreshes upstream tokens server-side, and exposes only `HttpOnly` cookies to the browser. | Best browser-token reduction; centralizes authz; aligns with backend-mediated app data. | More backend endpoints, session store, CSRF, refresh, logout, and test complexity. | Preferred end state. |
| Backend-managed app cookies wrapping Supabase/MATA sessions | Frontend may initially obtain Supabase/MATA credentials, then exchanges them once for backend app cookies; browser no longer transports app bearer tokens after exchange. | Incremental path from current implementation; can keep Supabase Auth as identity provider. | Must carefully clear browser-visible tokens after exchange and handle refresh without reintroducing token storage. | Recommended staged path. |
| Continue Supabase client-only staff sessions | Keep browser Supabase tokens and only tighten CSP/CORS/XSS controls. | Lowest implementation cost. | Does not remove browser-visible bearer-token risk; weak fit for real production/public use. | Not sufficient beyond protected UAT. |
| Hybrid transitional mode | Support both bearer and cookie transport behind explicit environment flags while migrating tests/users. | Safer rollout and rollback. | Two auth paths increase complexity and must have an expiry date. | Acceptable only as a short migration slice. |

## 4. Recommended Target

Adopt backend-managed app session cookies for all roles, with backend-mediated authorization remaining the source of truth.

Required properties:

- Cookies are `HttpOnly`, `Secure`, and scoped to the approved API domain.
- `SameSite` is `Strict` where the deployment topology allows it; otherwise use `Lax` with explicit CSRF controls for unsafe methods.
- Unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) require a CSRF token that is independent from the session cookie.
- Backend validates session state on every protected request and derives role, staff scope, resident id, external resident id, posting scope, and admin level from trusted backend state.
- Supabase `user_metadata` is never used for MATA authorization.
- Resident posting/programme claims in client-visible state are display-only and never trusted for access control.
- Staff, NHG Resident, and Non-NHG Resident sessions have separate creation paths but converge into one backend identity shape.
- Logout invalidates the backend session server-side and clears cookies.
- Refresh/rotation uses short-lived access cookies or opaque session ids plus a server-side session record.
- Session keys and refresh material are stored server-side only.

## 5. CSRF Design

When cookies become the auth transport, CSRF protection becomes mandatory for unsafe API methods.

Recommended design:

- Backend issues an opaque CSRF token after login/session hydration.
- CSRF token is readable by the frontend only as a non-secret anti-CSRF value, not as an auth credential.
- Frontend sends the token in a custom header, for example `X-CSRF-Token`, on unsafe methods.
- Backend validates that the CSRF token matches the active backend session.
- `GET`, `HEAD`, and health/readiness endpoints remain side-effect-free.
- CORS remains an exact allowlist; never rely on CSRF alone for origin control.
- Failed CSRF validation returns a generic `403` without revealing session internals.
- Tests cover missing, mismatched, replayed-after-logout, and rotated token cases.

Open decision:

- Choose synchronizer-token storage in the server session record or a signed double-submit token. The synchronizer pattern is safer if a durable session store is already introduced.

## 6. Backend Changes Needed

Planned backend slices:

1. Session store design.
   - Decide Postgres, Redis/platform cache, or hybrid storage.
   - Track session id, subject id, role, auth source, expiry, rotation state, revoked time, created IP/user-agent hash if approved, and CSRF token metadata.
   - Add a migration only in the future implementation task if persistent storage is selected.

2. Cookie/session endpoints.
   - Add login/exchange endpoints that issue app cookies.
   - Add session hydration endpoint that resolves cookies to the existing identity response.
   - Add refresh endpoint if short-lived cookie rotation is used.
   - Add logout endpoint that revokes server-side session state and clears cookies.

3. Staff Supabase exchange.
   - Verify a Supabase staff JWT once at exchange time.
   - Map `sub` to `users.supabase_user_id`.
   - Persist only backend session state required for MATA auth.
   - Never copy Supabase `user_metadata` into authorization state.

4. Resident MCR session exchange.
   - Keep MCR credential checks server-side.
   - Issue backend app cookie instead of returning a browser-stored MATA bearer token.
   - Keep native and external resident tables separate.

5. Middleware update.
   - Resolve identity from the backend session cookie before bearer fallback.
   - Keep bearer fallback only behind a temporary, explicit UAT migration flag.
   - Preserve production rejection of raw `X-User-*` identity headers.

6. Security controls.
   - Add CSRF dependency/middleware for unsafe methods.
   - Add cookie flags and domain/path configuration tests.
   - Add rate-limit keys that use verified backend session identity.
   - Add safe error handling for expired, revoked, missing, and malformed sessions.

## 7. Frontend Changes Needed

Planned frontend slices:

1. Auth transport.
   - Stop storing app access tokens in `sessionStorage`.
   - Remove routine `Authorization: Bearer` injection for app API calls after cookie mode is active.
   - Send `credentials: include` or the Axios equivalent for API calls.

2. Staff login.
   - Either exchange a freshly obtained Supabase access token with the backend and then clear browser-visible Supabase session state, or move staff password/OAuth handling behind a backend-mediated flow if approved.
   - Continue showing generic sign-in errors and rate-limit feedback.

3. Resident login.
   - Submit MCR to backend and receive only cookie-backed app session state.
   - Hydrate identity from backend session endpoint.

4. CSRF header.
   - Store the non-secret CSRF token in memory or a non-credential cookie as selected.
   - Attach CSRF header to unsafe methods only.
   - Clear token on logout/session expiry.

5. Logout and hydration.
   - Call backend logout before clearing local identity.
   - Treat hydration failures as local state reset without leaking tokens.
   - Keep route guards synchronous and based on hydrated identity, not raw token claims.

6. Cleanup.
   - Remove obsolete bearer-token storage helpers after the migration window closes.
   - Update frontend contract tests to reject app bearer persistence in production cookie mode.

## 8. Testing Plan

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

Rollback plan for the future implementation task:

- Keep the current bearer transport behind a temporary protected-UAT-only feature flag until cookie mode passes smoke.
- If cookie mode breaks UAT, disable cookie mode and restrict access back to the protected bearer-token baseline.
- Revoke new backend sessions and clear cookies through logout/expiry response.
- Rotate session-signing or encryption material if exposure is suspected.
- Preserve database rollback steps for any future session-store migration.
- Document rollback trigger, operator, and follow-up owner.

Rollback must not re-enable raw `X-User-*` production trust or relax CORS.

## 10. Risks And Decisions

Open decisions before implementation:

- Session store: Postgres, Redis/platform cache, or hybrid.
- Cookie domain strategy for Vercel frontend/backend topology and preview URLs.
- `SameSite=Strict` versus `SameSite=Lax` for the deployed domains.
- Staff login exchange design: short-lived Supabase browser token exchange versus fully backend-mediated auth flow.
- Refresh strategy: opaque session id rotation, split access/refresh cookies, or server-side sliding expiry.
- CSRF token pattern: synchronizer token versus signed double-submit token.
- Whether to bind sessions to user-agent/IP signals and how to handle hospital network changes.
- Session duration and idle timeout for staff versus residents.
- Migration window length for bearer fallback, if any.
- Operational controls for revoking all sessions after a suspected incident.

Known risks:

- Cookie mode is harder to test across Vercel preview domains and custom API domains.
- A partial migration could create two divergent auth paths if the fallback window is not short.
- CSRF bugs can block valid users or leave unsafe methods exposed.
- Supabase staff password flows must avoid moving private credentials into logs or app telemetry.

## 11. Acceptance Criteria

The future implementation is complete only when all are true:

- No app access token or refresh token is stored in `sessionStorage` or `localStorage`.
- Normal app API calls no longer send app bearer tokens from browser storage.
- All protected roles hydrate through backend session cookies.
- Cookies are `HttpOnly`, `Secure`, and have the approved `SameSite` setting.
- Unsafe methods require valid CSRF tokens.
- Logout invalidates backend session state and clears cookies.
- Staff authorization still derives from `users.supabase_user_id` and DB-owned role/scope fields.
- NHG Resident and Non-NHG Resident sessions remain table-separated and correctly scoped.
- Raw identity headers remain rejected in production/Supabase mode.
- Tests cover session creation, hydration, CSRF, expiry, rotation, logout, revocation, and cross-role denial.
- 5B-H-C smoke is updated to include cookie/session checks before production/public launch.
