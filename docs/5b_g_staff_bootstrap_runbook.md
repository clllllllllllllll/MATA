# 5B-G-D Staff Bootstrap Runbook

> **Current contract:** `docs/security.md`. This phase-specific runbook remains
> operational evidence and does not override the current security contract.

Status: production runbook, not automation.
Last updated: 2026-07-06

## Purpose And Scope

This runbook defines how to create or repair the first production staff account for MATA when `AUTH_MODE=supabase`. It exists because normal staff account management is Master Admin-only, but a clean production environment has no Master Admin yet.

This document is operational guidance only. It does not create users, does not contain credentials, and does not add application code.

## Why Bootstrap Is Needed

MATA staff accounts live in the application `users` table. Supabase Auth users live in Supabase Auth's `auth.users` table. In Supabase mode, a protected staff request verifies the Supabase access token and maps token `sub` to `users.supabase_user_id`; MATA then derives `role`, `admin_level`, `programme_scope`, `posting_code`, active state, and staff actor metadata from the `users` row.

The first Master Admin cannot be created through `/admin/staff-accounts` because that endpoint requires an existing active Master Admin. Production therefore needs one controlled bootstrap step to create or map the first Supabase Auth staff user to one `users` row with `role = 'admin'` and `admin_level = 'master'`.

## Non-Goals

- Do not create Supabase Auth users for NHG Residents.
- Do not create Supabase Auth users for Non-NHG Residents.
- Do not place NHG Residents or Non-NHG Residents in `users`.
- Do not derive MATA authorization from Supabase `user_metadata`.
- Do not infer Master Admin access from `programme_scope = NULL`, an empty array, blank string, missing value, or any special programme code.
- Do not implement RLS, cookie/BFF transport, CSRF, session hardening, or compliance in this bootstrap step.

## Required Backend-Only Environment

The bootstrap operator must run from a trusted backend/server context with production environment variables already configured. Never run this from frontend code, a browser console, or a client-exposed build environment.

Required backend variables:

```env
ENV=production
AUTH_MODE=supabase
DATABASE_URL=<production async database url>
SYNC_DATABASE_URL=<production sync database url>
SUPABASE_URL=<production Supabase project url>
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_PUBLISHABLE_KEY=<publishable-or-anon-compatible-key-if-required-by-current-code>
SUPABASE_SERVICE_ROLE_KEY=<server-only service-role key>
MATA_RESIDENT_SESSION_SECRET=<backend-only random secret>
```

Optional backend variables supported by current code:

```env
SUPABASE_JWKS_URL=<explicit JWKS url if not derived from SUPABASE_URL>
SUPABASE_JWT_ISSUER=<explicit issuer if not derived from SUPABASE_URL/auth/v1>
SUPABASE_ANON_KEY=<legacy anon key fallback if publishable key is not configured>
SUPABASE_JWKS_CACHE_TTL_SECONDS=600
CORS_ORIGINS=<production frontend origin allowlist>
```

Forbidden frontend or `VITE_*` variables:

- `SUPABASE_SERVICE_ROLE_KEY`
- `MATA_RESIDENT_SESSION_SECRET`
- database URLs or database passwords
- JWT signing secrets or private keys
- backend-only API keys
- any backend-only secret

All `VITE_*` variables are browser-exposed. `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and the legacy `VITE_SUPABASE_ANON_KEY` fallback are public client configuration, not privileged secrets.

## Bootstrap Options

### Option A: Manual Supabase Auth Creation Plus SQL Mapping

1. Create the staff email/password user in the Supabase Dashboard or Supabase Admin API.
2. Copy only the returned Supabase Auth user id (`auth.users.id`), not any token or password, into the SQL mapping step.
3. Insert or update one `users` row with:
   - `supabase_user_id = <auth.users.id>`
   - `role = 'admin'`
   - `admin_level = 'master'`
   - `programme_scope = NULL` or `{}` only because `admin_level = 'master'` is explicit
   - `posting_code = NULL`
   - `is_active = true`
   - `current_staff_actor_name = NULL` for first-login actor-name capture, or a confirmed handover name if policy requires it

This is acceptable for first production bootstrap when performed by a trusted operator with change approval and audit notes.

### Option B: One-Time Backend Script

A future script is acceptable if it follows the existing local script safety posture and adds production-specific confirmations. It must:

- Require an explicit production confirmation string, such as the project ref plus the target staff email.
- Refuse missing `ENV=production`, `AUTH_MODE=supabase`, `SYNC_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `MATA_RESIDENT_SESSION_SECRET`.
- Refuse to print passwords, tokens, service-role keys, database URLs, or resident-token secrets.
- Create or map the Supabase Auth user first, then insert/update `users.supabase_user_id`.
- Use parameterized SQL or SQLAlchemy, never string interpolation.
- Set `role = 'admin'`, `admin_level = 'master'`, and `is_active = true`.
- Store `programme_scope` as `NULL` or empty only because `admin_level = 'master'` is the explicit authorization marker.
- Leave or clear `current_staff_actor_name` according to the staff actor-name contract.
- Print only safe identifiers such as email, local `users.id`, Supabase Auth user id, role, admin level, and active status.

No script is added in 5B-G-D. The next implementation step, if desired, should be a separate reviewed task.

### Option C: Restricted Backend Endpoint

A restricted admin-only backend endpoint is not a valid first-user bootstrap mechanism by itself because it still needs an already authorized administrator. It is acceptable only if separately protected outside normal app auth, such as behind a one-time deployment control with security approval. That is not part of 5B-G.

## Recommended Safest Approach

For the first production deployment, use Option A under a controlled change window or create Option B as a separate task after security review. Keep the bootstrap narrow: create one Master Admin role account, validate that login maps through `users.supabase_user_id`, then use normal Master Admin staff account management for all other staff users.

After the first login, the staff actor-name flow should capture the current human user of the shared role account. Because `current_staff_actor_name` is audit/display metadata only, it must not alter role, scope, posting, or admin level.

## SQL Mapping Template

Use placeholders only. Do not paste production URLs, tokens, or passwords into this document or logs.

```sql
-- Replace placeholders at execution time.
-- The password_hash marker is not used for Supabase authentication; Supabase owns the password.
INSERT INTO users (
    email,
    supabase_user_id,
    password_hash,
    role,
    name,
    posting_code,
    programme_scope,
    admin_level,
    is_active,
    current_staff_actor_name
)
VALUES (
    :email,
    :supabase_user_id,
    :password_hash_marker,
    'admin',
    'Master Admin',
    NULL,
    NULL,
    'master',
    true,
    NULL
)
ON CONFLICT (email)
DO UPDATE SET
    supabase_user_id = EXCLUDED.supabase_user_id,
    password_hash = EXCLUDED.password_hash,
    role = 'admin',
    name = EXCLUDED.name,
    posting_code = NULL,
    programme_scope = NULL,
    admin_level = 'master',
    is_active = true,
    current_staff_actor_name = NULL,
    staff_actor_name_updated_at = NULL,
    staff_actor_name_updated_by_user_id = NULL,
    updated_at = now()
RETURNING id, email, supabase_user_id, role, admin_level, programme_scope, is_active;
```

Use a non-secret marker such as `supabase-managed:<uuid>` for `password_hash`. Do not store the real password in `users.password_hash` in Supabase mode.

## Verification SQL

Verify the intended Master Admin row:

```sql
SELECT id, email, supabase_user_id, role, admin_level, programme_scope, posting_code, is_active
FROM users
WHERE lower(email) = lower(:master_admin_email);
```

Verify active Master Admin count:

```sql
SELECT count(*) AS active_master_admins
FROM users
WHERE role = 'admin'
  AND admin_level = 'master'
  AND is_active = true;
```

Verify production staff rows are mapped to Supabase Auth:

```sql
SELECT id, email, role, admin_level, posting_code, programme_scope
FROM users
WHERE role IN ('admin', 'secretary')
  AND is_active = true
  AND supabase_user_id IS NULL;
```

Verify no master access is implied by null scope:

```sql
SELECT id, email, role, admin_level, programme_scope, is_active
FROM users
WHERE role = 'admin'
  AND admin_level <> 'master'
  AND (programme_scope IS NULL OR cardinality(programme_scope) = 0);
```

Verify Programme PC rows have non-empty, non-blank programme scopes:

```sql
SELECT id, email, programme_scope
FROM users
WHERE role = 'admin'
  AND admin_level = 'programme'
  AND is_active = true
  AND (
    programme_scope IS NULL
    OR cardinality(programme_scope) = 0
    OR EXISTS (
      SELECT 1
      FROM unnest(programme_scope) AS scope_value
      WHERE btrim(scope_value) = ''
    )
  );
```

Verify Secretary rows have posting scope:

```sql
SELECT id, email, posting_code
FROM users
WHERE role = 'secretary'
  AND is_active = true
  AND (posting_code IS NULL OR btrim(posting_code) = '');
```

Verify duplicate Supabase Auth mappings are impossible or absent:

```sql
SELECT supabase_user_id, count(*) AS row_count
FROM users
WHERE supabase_user_id IS NOT NULL
GROUP BY supabase_user_id
HAVING count(*) > 1;
```

## Rollback Or Disable Procedure

If the wrong Master Admin was created or mapped:

1. Deactivate the affected `users` row with `is_active = false`.
2. Rotate or reset the Supabase Auth password for the affected Auth user.
3. If the Auth user id was mapped to the wrong staff row, unset `users.supabase_user_id` on the wrong row and map it to the correct row only after verification.
4. Do not casually delete `users` rows because they are referenced by upload logs, audit logs, staff actor metadata, and future operational history.
5. Preserve an operational note with the change ticket, affected safe identifiers, timestamp, and verifier.

If all Master Admin access is lost, use the same controlled bootstrap path to restore exactly one intended active Master Admin before proceeding with normal UI/API staff management.

## Edge Cases

- Supabase Auth user exists but `users` row is missing: insert the `users` row and map `supabase_user_id`.
- `users` row exists but `supabase_user_id` is missing: create or identify the Supabase Auth user, then update the row.
- Duplicate `supabase_user_id`: fix immediately; a unique constraint should prevent this, but verification SQL should still be part of the runbook.
- Inactive user: login must fail. Reactivate only after identity and scope are confirmed.
- Wrong `admin_level`: update only through a reviewed change; `admin_level = 'master'` is the sole master marker.
- Blank or whitespace programme scope: treated as empty and grants no Programme PC access.
- Generic shared role account handover: reset password and clear `current_staff_actor_name`; the next human user re-enters actor metadata after login.
- Supabase `user_metadata` contains role-like values: ignore for MATA authorization.

## Acceptance Checklist

- Exactly the intended first Master Admin staff row exists.
- The row has `role = 'admin'`, `admin_level = 'master'`, `is_active = true`, and a non-null `supabase_user_id`.
- Master access is not inferred from `programme_scope`.
- Programme PC rows have non-empty valid scopes.
- Secretary rows have non-empty valid `posting_code`.
- No residents or Non-NHG Residents were created in `users` or Supabase Auth.
- No backend-only secret was printed, committed, copied to frontend config, or copied to any `VITE_*` variable.
- Login succeeds with the Supabase staff Auth user and `/auth/me` returns the DB-owned MATA role/scope.
- Normal Master Admin staff account UI/API can create subsequent staff accounts.

## Open Decisions

- Whether to implement the one-time production bootstrap as a reviewed script or keep it as a manual runbook.
- Whether production will later replace self-declared `current_staff_actor_name` with corporate SSO identity.
- Whether service-role staff provisioning should be wrapped in additional operational approval beyond Master Admin role checks.
