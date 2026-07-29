# Phase 5B-H M-06 Reliable Logout

> **Current contract:** `docs/security.md`. This file is retained as dated
> implementation evidence and does not override the current security contract.

Status: implemented and verified locally on `CL/5b-h-m06-reliable-logout`;
deployed verification is pending.

This work is based on the verified M-05 commit
`9c6de896fb956f268632af38022aac1c42e3efe2`. It is a local implementation and
evidence record only. No branch was pushed or merged, no Vercel configuration
or deployment was changed, no live Supabase resource was accessed, and no
remote migration was run.

## Security outcome

M-06 separates three states that must not be conflated:

1. **Local sign-out** happens immediately. The frontend clears its identity,
   CSRF value, role and scope state, protected caches, upload state, and
   authenticated UI without waiting for the network.
2. **Logout pending or unconfirmed** means local sign-out is complete but
   server revocation has not been proved. Hydration, restoration, and ordinary
   protected requests remain blocked.
3. **Server logout confirmed** means the backend returned the explicit
   proof-positive outcome for the matching logout operation. Only this state
   may be described to the user as confirmed server revocation.

A successful replacement login may safely supersede the matching pending
logout after the replacement session has committed. That transition is not
reported as confirmation that the previous server session was revoked.

## Backend confirmation contract

`POST /api/v1/auth/logout` retains the existing narrow termination path,
authentication-source checks, CSRF proof, session-family revocation, redaction,
and cookie coordination.

The response contains:

```json
{
  "success": true,
  "server_logout_confirmed": true
}
```

`server_logout_confirmed` is `true` only when the presented proof revokes one
or more rows in the matching session family. The response clears the shared
session cookie only on that same proof-positive branch.

A zero-result revocation returns `server_logout_confirmed: false`. This covers
missing, invalid, mismatched, already-consumed, or otherwise non-revoking proof.
It does not assert that a server session still exists. `success: true` means
only that the endpoint processed the request; it is not revocation evidence.
The response discloses no revocation count, reason, session or family
identifier, identity, role, MCR, or scope.

## Durable non-sensitive lifecycle state

The pending record is an exact, versioned four-field tombstone:

```text
{ version, requestId, initiatedAt, retryCount }
```

Its serialized UTF-8 representation is limited to 512 bytes. Parsing rejects
extra or missing fields, unsupported versions, invalid or overlong request
identifiers, unsafe or out-of-range timestamps, and retry counts outside the
four-attempt bound. It has no automatic expiry: elapsed time alone cannot
silently restore protected access.

Resolution ordering is recorded separately as an exact, versioned watermark:

```text
{ version, requestId, initiatedAt, resolvedAt, resolution }
```

The watermark is also strictly parsed and limited to 512 serialized UTF-8
bytes. `resolution` is exactly `confirmed` or `replacement-login`, and
`resolvedAt` cannot precede `initiatedAt`. The matching resolution watermark
is durably written and verified before the pending tombstone is removed.
Therefore a crash or interrupted clear cannot erase the evidence needed to
prevent an older pending replica or channel message from being resurrected.

The browser adapter uses the available `localStorage`, `sessionStorage`,
`history.state`, and prefixed `window.name` storage paths. The history and
window-name paths are bounded fallbacks for Web Storage failure; unrelated
window-name state is not overwritten during normal operation. Reads reconcile
strictly valid replicas, retain the newest in-memory or durable resolution, and
repair mirror state where safe.

Writable storage is established with a per-runtime, per-attempt unique probe
key and a fixed-size non-sensitive probe value. The probe must be written,
read back exactly, removed, and observed absent. A storage implementation that
silently drops writes or removals is not treated as safe.

Only the pending tombstone, the resolution watermark, and the non-sensitive
probe can enter these stores. They contain no opaque session token or cookie,
CSRF value, identity, email, MCR, role, programme, posting, site, authorization
scope, or protected application data. The opaque cookie remains inaccessible
to JavaScript, and the retry proof remains memory-only.

## Replica election and fail-closed behavior

Replica selection is deterministic rather than dependent on browser storage
enumeration order:

- pending tombstones are ordered by `initiatedAt`, then `requestId`, with the
  greatest retry count retained for the same operation;
- resolution watermarks are ordered by `resolvedAt`, then `requestId`;
- the same request identifier with contradictory initiation times is invalid;
- equal-order but non-identical resolution records are invalid;
- a resolution supersedes its exact request only with matching initiation
  evidence and also retires a distinct concurrent candidate initiated at or
  before `resolvedAt`;
- a genuinely newer pending operation remains pending.

Contradictory or ambiguous replicas do not elect an arbitrary winner. The
lifecycle stays blocked until durable state is absent or coherent. A clear
browser read heals the elected resolution across writable fallback replicas so
future operations clamp above the same monotonic watermark.

The frontend also fails closed for malformed or oversized records, unavailable
storage, read or write failure, failed write/removal verification, an
uncontrolled marker clear, an unconfirmed matching clear, an invalid channel
payload, and a proofless reload. A runtime fence preserves the matching
request identifier when durable cleanup cannot yet be proved. Exact-ID checks
prevent a recovery path for one logout from releasing a different or newer
logout.

The request interceptor is a standalone enforcement point: it reads the
logout lifecycle immediately before dispatch and rejects protected safe and
unsafe requests while the state is pending or blocked. This gate does not
depend on React hydration state. Only narrowly identified lifecycle requests,
such as the matching logout attempt or a replacement login, may opt through.
Hydration, focus and visibility revalidation, rotation, and authenticated state
publication repeat their own pending-state and generation checks.

## Retry and proof lifetime

The retry proof contains only the memory-resident CSRF value and the captured
session epoch, revision, and authentication generation. It is never written
to Web Storage, history, `window.name`, a cookie, a URL, or the channel.

The first automatic attempt is immediate. Retryable transport or server
failures use delays of 1, 2, and 4 seconds, producing nominal automatic attempt
offsets of 0, 1, 3, and 7 seconds. There are at most four total attempts.
Offline state pauses automatic dispatch. A user retry or `online` event may
advance one currently eligible attempt; simultaneous timer, online, and user
triggers coalesce and cannot exceed the same bound.

Each dispatch rechecks the exact pending request, retry count, session fence,
and authentication generation. An `AbortController` cancels obsolete in-flight
or scheduled work. Network and retryable server failures remain pending;
explicit false confirmation, non-retryable failure, exhaustion, or ambiguity
is shown as unconfirmed rather than converted into success.

A reload necessarily loses the proof. The durable pending state continues to
block hydration and protected requests, but it cannot reconstruct credentials
or issue a speculative logout request. The user may establish a replacement
session through a fresh full login.

## Web Lock, cross-tab, reload, and stale-response guarantees

Cookie-mode login, refresh, and logout continue to use the same origin-scoped
exclusive Web Lock through completion of the HTTP response. This orders
fixed-name `Set-Cookie` effects across tabs. There is no storage or
`BroadcastChannel` mutex fallback for missing Web Locks.

Within that ordering boundary:

- logout captures the current session proof and authentication generation
  before immediate local clear;
- every retry is tied to the exact logout request identifier;
- a stale logout callback or response cannot clear or relabel a newer login;
- a replacement login commits first, persists the matching
  `replacement-login` resolution, and only then clears the matching tombstone;
- if that ordered release cannot be verified, the replacement local session
  is discarded and protected access remains blocked;
- a failed login leaves the pending lifecycle untouched.

The typed `BroadcastChannel` protocol carries only strictly validated pending,
blocked, resolution-watermark, and synchronization messages. Storage events
and a synchronization request/replay handshake cover missed mount-time
messages. Durable watermarks prevent delayed pending or blocked messages from
relatching a resolved operation. An exact cleared-logout request identifier on
the authenticated-session announcement lets peer tabs accept only the matching
replacement login.

Durable storage changes carry the exact elected resolution context even when
`BroadcastChannel` is unavailable. A focus, visibility, or cross-tab
revalidation signal received while a full login owns the authentication
generation is deferred. A successful login discards that obsolete work; a
failed login replays one hydration only after the login attempt clears and only
if the pending fence permits it.

On cross-tab logout, each tab clears local protected state and blocks
hydration. On proof-positive confirmation, the matching watermark lets peers
converge on confirmed server revocation. On reload, deterministic replica
election restores the pending fence but never restores the memory-only proof.
A later, genuinely newer logout or login cannot be released by an older
storage event, channel message, request completion, or resolution.

## User experience and accessibility

The login page presents an explicit pending/unconfirmed panel stating that
local identity and protected data were cleared immediately while server
sign-out is not yet confirmed. It distinguishes confirming, offline,
retry-available, retry-exhausted, and proof-lost states, and it leaves both
full-login forms available for safe replacement authentication.

The pending panel uses an alert or polite status role appropriate to its
current activity, `aria-live`, `aria-busy` during retry, a focusable status
heading, and a disabled progress control while an attempt is in flight.
Scheduled and active retry states are announced politely. The manual retry
control has an explicit action label. Proof-positive completion uses a separate
polite status panel headed “Server sign-out confirmed.” A replacement login
clears the pending panel without displaying that confirmation claim.

## Verification record

The final M-06 local evidence below was produced after the implementation
settled. Earlier M-05 results and pre-correction logout results were not used as
substitutes for these reruns.

| Gate | Recorded result |
|---|---|
| Focused backend logout/session tests | Passed: 47 tests, 1 warning, 4.00 seconds |
| Backend bytecode compilation | Passed |
| Complete restricted-runtime backend suite against the explicit local disposable PostgreSQL database | Passed: 1,342 tests, 16 warnings, 376.42 seconds |
| Alembic one-head check | Passed: one head, `20260728_000028` |
| Focused logout-reliability and frontend security contracts | Passed: 119 tests |
| Complete frontend suite | Passed: 186 tests |
| Frontend lint | Passed |
| Frontend type-check | Passed |
| Production frontend build | Passed with the production Supabase/cookie environment: 228 modules transformed |
| Security scanner unit tests | Passed: 16 tests |
| Frontend and worktree security-source scan modes | Passed before commit |
| Committed M-05-base and atomic-base security-source scan modes | Run immediately after the immutable local commit and recorded in the handoff |
| Likely-secret and personal-data review of the scoped M-06 delta | Passed: zero email, phone, NRIC, or MCR shapes; four synthetic negative-test CSRF markers; no real personal data or likely secret |
| `git diff --check` | Passed |

The recorded restricted-runtime result used an explicitly local disposable
database; it is not evidence about live Supabase. Production deployment
verification, target-browser cross-tab/reload UAT, production cookie behavior,
and production authentication assurance remain outstanding. No live action is
authorized by this record.

PRODUCTION AUTH ASSURANCE BLOCKER — RESIDENT SECOND FACTOR NOT APPROVED
