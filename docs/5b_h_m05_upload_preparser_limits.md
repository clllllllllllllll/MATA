# Phase 5B-H AUD-M-05 — Pre-parser Request-Body Limits

> **Current contract:** `docs/security.md`. This file is retained as dated
> implementation evidence and does not override the current security contract.

## Scope and result

AUD-M-05 closes the application-layer gap in which a misleading or absent
`Content-Length` could allow Starlette to consume or spool multipart data before
the file reader rejected it. The earlier 10 MiB file setting is superseded by
the approved Vercel product contract below. The descendant branch adds a pure
ASGI request-body boundary before authentication and multipart parsing, retains
the file/workbook protections, and adds bounded multipart metadata parsing.

This is local implementation evidence only. No Vercel setting, deployment,
Supabase project, remote database, or live request was changed or accessed.

## Limit hierarchy

| Boundary | Default | Enforcement |
|---|---:|---|
| All HTTP request bodies | 4 MiB | Pure ASGI receive wrapper |
| `POST /api/v1/admin/upload/*` aggregate request | 4 MiB | Same ASGI wrapper, before auth/parser |
| Uploaded file | 3 MiB | Existing chunked file reader and workbook preflight |
| Multipart files | 1 | Starlette parser configuration |
| Non-file multipart fields | Route-specific: RDB 1, TTF 2, Form F1 1, public holidays 0 | Starlette parser configuration |
| One non-file multipart part | 4 KiB | Starlette `max_part_size`; this is not a file-part limit |
| Decoded filename | 255 UTF-8 bytes | Post-header, pre-handler validation |

The settings are `MAX_REQUEST_BODY_SIZE_MB=4`,
`MAX_UPLOAD_REQUEST_SIZE_MB=4`, and `MAX_UPLOAD_SIZE_MB=3`. Startup validation
requires positive values and
`MAX_UPLOAD_SIZE_MB < MAX_UPLOAD_REQUEST_SIZE_MB <= MAX_REQUEST_BODY_SIZE_MB`.
The 1 MiB file/request gap leaves room for multipart framing, so a valid 3 MiB
file fits within the complete 4 MiB request boundary. Production startup also
requires the exact 4/4/3 values, so superseded or independently overridden
environment values fail closed instead of diverging from the fixed
frontend/Nginx contract.

The pinned multipart stack also applies its own boundary and per-part header
bounds. These dependency bounds supplement rather than replace the application
limits.

## Request path and behavior

The effective application perimeter is:

```text
security headers -> strict/trusted host -> CORS -> request-body limit
-> authentication/CSRF -> upload content-type guard -> rate limit -> router
```

The limiter inspects every raw `Content-Length` occurrence. Empty, signed,
non-decimal, comma-malformed, or conflicting values receive a controlled `400`.
Numerically identical duplicates are accepted. A declared value over the
selected cap receives `413` without calling the downstream application or
multipart parser.

Every actual `http.request` chunk is counted even when `Content-Length` is
missing or falsely small. A total exactly equal to the cap is accepted; the
first crossing chunk is not forwarded. The middleware stores only counters and
flags, not a body copy. Genuine `http.disconnect` messages pass through, and
request cancellation is not caught or converted into an HTTP response.

Known oversized requests can therefore be rejected before application parsing
or spooling begins. Missing or false-small lengths cannot be known in advance:
Starlette may consume or spool up to the selected cap before the streaming
boundary aborts the request.

## Error and evidence safety

Application-generated `400` and `413` responses use the bounded API error
envelope, include `Cache-Control: no-store`, and expose no header value,
filename, body content, temporary path, parser detail, token, identity, or stack
trace. The limiter emits no request-content log.

Upload multipart count, field-size, and filename failures return a controlled
`422` and close any parsed `UploadFile` handles before returning. Authentication,
CSRF, rate limiting, extension/MIME checks, parser selection, and write
transactions remain unchanged for accepted requests.

## Existing archive and workbook limits

The existing defense-in-depth preflight remains:

- 3 MiB compressed upload/file cap;
- 100 MiB aggregate expanded archive cap;
- 2,048 archive members;
- 20 MiB per expanded member;
- 100:1 compression-ratio ceiling;
- nested-archive, encrypted-entry, unsafe ZIP name, relationship-target, and
  unsafe XML protections.

## Ingress and hosting boundary

The repository Nginx configuration now enforces 4 MiB globally and for the
normalized `/api/v1/admin/upload/` proxy path. Upload proxy buffering is
disabled so an unknown-length stream can reach the ASGI counter incrementally.
Nginx-generated `413` responses occur before FastAPI and are not guaranteed to
use the application JSON envelope or its cache headers.

The current Vercel Functions platform documents a non-configurable 4.5 MB
request/response payload ceiling. The repository's supported `vercel.json`
schema has no body-size override. The approved product contract therefore caps
each uploaded file at 3 MiB and the complete multipart or other request body at
4 MiB, including multipart framing. Application enforcement does not replace
Vercel's upstream boundary. Larger-file support requires a separately approved
upload ingress; no such ingress or unsupported `vercel.json` key is implemented
in this task.

References:

- [Vercel Functions limits](https://vercel.com/docs/functions/limitations)
- [Vercel guidance for the 4.5 MB body limit](https://vercel.com/kb/guide/how-to-bypass-vercel-body-size-limit-serverless-functions)
- [Vercel project configuration](https://vercel.com/docs/project-configuration/vercel-json)
- [Nginx `client_max_body_size`](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
- [Nginx proxy request buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering)

## Local verification evidence

The earlier 10/11/12 MiB test results are superseded and are not counted as
final evidence for this approved contract.

| Gate | Corrected 3/4/4 MiB result |
|---|---|
| Focused request-body and settings contracts | 50 passed |
| Upload/parser/multipart/workbook/auth/CSRF/rate-limit/redaction matrix | 513 passed; one known Starlette TestClient deprecation warning |
| Complete restricted-runtime backend suite | 1,342 passed; 16 known Starlette/Alembic deprecation warnings; runner roles removed |
| Complete frontend contracts | 112 passed |
| Frontend lint and type-check | Passed |
| Production frontend build | Passed with documented `production` / `supabase` / `/api/v1` values; existing chunk-size warning only |
| Security scanner unit tests | 16 passed |
| Frontend, worktree, and atomic-base diff source scans | Passed |
| Added-line personal-data-shape review | Zero email or phone matches; one deliberately synthetic redaction marker; no real personal data in the intended M-05 delta |
| Backend compile | Passed |
| Alembic/source whitespace | One head `20260728_000028`; `git diff --check` passed |
| Disposable PostgreSQL post-check | `mata_phase5b_m05_upload_limits_verify`, revision `20260728_000028`, zero residual `mata_test_*` roles |
| Nginx parser check | Not run: neither a local Nginx binary nor a running Docker engine was available. Repository contract tests passed. |

## Required deployed verification

Before production approval, record sanitized evidence that:

1. the actual ingress rejects above its approved cap before application parsing;
2. the deployed 4 MiB complete-request cap and advertised 3 MiB UI/API file cap
   agree, including multipart framing;
3. exact-boundary and boundary-plus-one requests behave as approved;
4. missing/false-small-length streams are terminated without retry storms;
5. upstream and application `413` responses are not cached and disclose no
   internal or personal data;
6. same-origin `/api/v1/admin/upload/*` requests reach the intended ingress rule;
7. normal authentication, CSRF, upload rate limits, and valid uploads still work;
8. slow-client/time-bound ingress protection is separately reviewed.

Local tests do not establish any of these deployed facts.
