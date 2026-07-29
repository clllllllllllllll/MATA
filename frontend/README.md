## MATA Frontend

React + Vite + TypeScript frontend for staff, NHG Resident, and Non-NHG Resident workflows.

### Run locally

Prerequisite: Node.js 22.22+.

1. `cd frontend`
2. `npm ci`
3. `npm run dev`
4. Open [http://localhost:5173](http://localhost:5173)

### Verification gates

- `npm test`
- `npm run build`
- `npm run lint`
- `npm run typecheck`

### Environment variables

Create `frontend/.env` (or `frontend/.env.local`) with:

```bash
VITE_APP_ENV=local
VITE_AUTH_MODE=stub
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_DEMO_ADMIN_USER_ID=5635c7b4-e0f1-4f59-88e1-f0b976b62d29
VITE_DEMO_ADMIN_PROGRAMME_SCOPE=DR,GERI
VITE_DEFAULT_PROGRAMME_CODE=DR
```

Notes:
- `VITE_API_BASE_URL` defaults to `http://localhost:8000/api/v1` if not set.
- Local Vite and Docker full-stack development remain `VITE_AUTH_MODE=stub`.
- Demo upload requests use Phase 1 stub headers:
  - `X-User-Role: admin`
  - `X-User-Id: <VITE_DEMO_ADMIN_USER_ID>`
  - `X-User-Programme: <VITE_DEMO_ADMIN_PROGRAMME_SCOPE>`
- TTF upload requires the selected `programme_code` to be inside `X-User-Programme`.
- Production uses `VITE_AUTH_MODE=supabase`, but the browser has no Supabase client configuration. Staff credentials are submitted to the MATA backend, which mediates Supabase Auth server-side.
- Production and Supabase-mode builds require the relative
  `VITE_API_BASE_URL=/api/v1` value exactly. Missing, absolute,
  scheme-relative, credentialed, or differently rooted values fail the build.
- All roles use the backend-owned `HttpOnly` application-session cookie. The frontend keeps only the current identity and synchronizer CSRF token in module memory, includes credentials on API requests, and sends `X-CSRF-Token` only on `POST`, `PUT`, `PATCH`, and `DELETE`.
- No authentication credential is retained in `localStorage` or `sessionStorage`.
- Startup removes only the exact superseded `mata.auth.session.v1` entry and
  never reads stored values or clears unrelated keys. The repository does not
  contain a trustworthy exact legacy Supabase project reference, so the app
  does not wildcard-delete `sb-*` keys. Users of an older deployment must
  clear site data once after the corrected release.
- Do not add backend secrets or database credentials to frontend env vars. No Supabase URL or publishable/anonymous key is required by the frontend.
- Backward-compatible fallbacks still supported:
  - `VITE_DEMO_ADMIN_ID`
  - `VITE_DEMO_ADMIN_PROGRAMMES`

### Backend connectivity

- Backend should run at `http://localhost:8000` (default API prefix `/api/v1`).
- If backend is offline or blocked by CORS, the upload cards display a connection error.
- Ensure backend CORS allowlist includes `http://localhost:5173`.
- For Docker full-stack startup, frontend is served by Nginx on `http://localhost:8080` and proxies API calls to backend using `/api/v1`.
- In Docker mode, set frontend build-time API base to `/api/v1` (already wired in `docker-compose.yml`).
- Local Vite dev can still use direct backend API base: `http://localhost:8000/api/v1`.

Production frontend values:

```dotenv
VITE_APP_ENV=production
VITE_AUTH_MODE=supabase
VITE_API_BASE_URL=/api/v1
```

After the production build, run:

```bash
python ../.github/scripts/security_source_scan.py --frontend-dist
```

### Docker full-stack startup

From repo root:

1. `docker compose up --build`
2. `docker compose exec backend alembic upgrade head`
3. Open `http://localhost:8080`

Checks:
- Direct backend health: `http://localhost:8000/health`
- Proxied health through Nginx: `http://localhost:8080/health`

### Data safety

- Do not commit local Excel uploads.
- Do not commit secrets.
- Use synthetic placeholder resident/programme data in frontend-only demo content.
