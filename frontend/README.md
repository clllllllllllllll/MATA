## MATA Frontend (Phase 0)

React + Vite + TypeScript frontend for the Master Admin upload workflow demo path.

### Run locally

1. `cd frontend`
2. `npm install`
3. `npm run dev`
4. Open [http://localhost:5173](http://localhost:5173)

### Build / lint

- `npm run build`
- `npm run lint`

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
- Supabase frontend mode requires only public browser-safe variables:
  - `VITE_AUTH_MODE=supabase`
  - `VITE_SUPABASE_URL=https://<project-ref>.supabase.co`
  - `VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>` or `VITE_SUPABASE_ANON_KEY=<anon-key>`
- Never add server-only Supabase secrets to frontend env vars.
- In Supabase mode, staff sign in through Supabase Auth and MATA identity is loaded from backend `/auth/me`. NHG and registered Non-NHG Resident MCR-only login use backend-signed MATA resident session tokens.
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
