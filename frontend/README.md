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
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_DEMO_ADMIN_ID=00000000-0000-0000-0000-000000000001
VITE_DEMO_ADMIN_PROGRAMMES=GRM,DR,FM,REH
VITE_DEFAULT_PROGRAMME_CODE=GRM
VITE_DEFAULT_REPORTING_PERIOD_ID=
```

Notes:
- `VITE_API_BASE_URL` defaults to `http://localhost:8000/api/v1` if not set.
- Demo upload requests use Phase 1 stub headers:
  - `X-User-Role: admin`
  - `X-User-Id: <VITE_DEMO_ADMIN_ID>`
  - `X-User-Programme: <VITE_DEMO_ADMIN_PROGRAMMES>`
- TTF upload requires the selected `programme_code` to be inside `X-User-Programme`.

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
