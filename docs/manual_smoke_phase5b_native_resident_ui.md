# Phase 5B Native Resident UI Smoke Checklist

Use this checklist for lightweight browser smoke verification after backend + frontend are running.

## Preconditions

1. Backend API reachable at `VITE_API_BASE_URL` (default `/api/v1`).
2. Frontend started and serving the demo shell.
3. Resident demo env values set (or defaults used):
   - `VITE_DEMO_RESIDENT_USER_ID`
   - `VITE_DEMO_RESIDENT_MCR`
   - `VITE_DEMO_RESIDENT_PROGRAMME`

## Browser Smoke Steps

1. Open `/`.
2. Navigate to `/resident/submissions` (or use role switcher to Native Resident).
3. Confirm sidebar/app shell shows Native Resident context.
4. Refresh the page on `/resident/submissions`; verify Native Resident shell remains active.
5. Confirm `GET /resident/events` renders available scheduled events when seeded.
6. Select one scheduled event and click `Submit Attendance`.
7. Confirm success callout appears and submitted event disappears from available list.
8. Refresh the page; confirm the submitted event remains excluded.
9. If weekend non-exception data is present, confirm weekend compliance warning banner appears after submit.
10. Submit ad-hoc teaching on a valid non-public-holiday date; confirm success callout.
11. Submit ad-hoc teaching on a seeded public holiday date; confirm visible validation error.
12. Navigate to `/secretary/events`; confirm secretary shell/page still renders.
13. Navigate to `/admin/upload`; confirm admin shell/page still renders.
