# Responsive UI Plan

## 1. Purpose

This document records the Phase 3J-A responsive UI audit and the implementation contract for future responsive work. It is a planning document only. It does not change frontend code, backend code, API contracts, migrations, tests, or user-facing terminology.

Phase 3J is now framed as:

```text
3J - Fluid adaptive responsive UI system
Goal: make MATA adapt cleanly across arbitrary viewport widths, from narrow phones to wide desktop screens, without page-level horizontal overflow or fixed-device assumptions.
```

The audit inspected the current React/Vite frontend shell, route map, shared UI components, global CSS, implemented admin pages, implemented secretary and resident pages, and the existing UI design specification. The current frontend is a desktop-first demo UI with partial tablet/mobile rules. Phase 3J-B through 3J-F should convert the existing surfaces into fluid adaptive experiences without changing behavior or data access.

The core principle is: design for content to adapt across any viewport, with breakpoints used only as guardrails. QA widths are sample checkpoints, not the only supported sizes and not fixed device assumptions.

Approved user-facing resident terminology is:

- `NHG Resident`
- `Non-NHG Resident`

Future responsive work must not reintroduce old `Native Resident` or `External Resident` labels in user-visible UI.

## 2. Current Responsive Baseline

### Desktop, 1280px and wider

Desktop is the strongest current state. The app uses a two-column shell with a 248px left sidebar and a main workspace. Page content is constrained by `.page` / `.page-stack` at a max width near 1320px. Page heroes generally use a left title block and right meta/actions block. Admin, secretary, and resident tables render as full desktop tables with horizontal scroll wrappers where the table width exceeds the content area.

Observed desktop strengths:

- The app shell and role-based navigation are readable.
- PageHero, cards, metrics, upload cards, filter bars, and table wrappers are visually consistent.
- Large data pages intentionally use table min-widths for dense admin review.
- DetailDrawer is a shared overlay used across warnings, logs, parsed data, secretary events, resident submissions, config, and multi-posting rules.

Observed desktop risks:

- Some tables have fixed min widths from 980px to 1680px and will always need a responsive pattern below desktop.
- The global responsive breakpoints are mixed: 1280px, 1120px, 1080px, 900px, 880px, 860px, and 720px all appear in CSS.
- Several pages rely on route-specific CSS rather than shared responsive utilities.

### Tablet, 768px to 1279px

Tablet support is partial. Below 1280px the sidebar collapses to a 72px icon rail. Below 1080px many grids stack to one column, page padding shrinks, and heroes stack. This is a useful start, but it is not yet a tablet contract.

Current tablet behavior:

- Sidebar becomes a narrow icon rail at `max-width: 1280px`.
- App bar horizontal padding drops at `max-width: 1080px`.
- Shared grids such as `.grid-4`, `.grid-3`, `.grid-2`, `.upload-grid`, `.bottom-split`, `.grid-8-4`, `.form-grid`, and `.filter-bar` collapse to one column at `max-width: 1080px`.
- Admin config sub-navigation stacks from a 252px side nav to one column at `max-width: 1080px`.
- Admin secretary events filters reduce to two columns at `max-width: 1120px`.

Tablet gaps:

- The collapsed rail is not a tablet navigation design. It hides labels and footer/scope context without providing tooltips or an expanded drawer.
- The role switcher is anchored inside the collapsed sidebar and is likely cramped below 1280px.
- App bar search/right actions are hidden below 1280px if present in CSS, but the current AppShell only renders breadcrumbs.
- Table experiences are inconsistent: some tables scroll, one upload logs table explicitly disables horizontal overflow, and no shared table-to-card contract exists.
- Drawers remain right-side drawers rather than switching to fullscreen or bottom-sheet behavior.

### Mobile, 481px to 767px

Mobile is not yet production-ready. Several pieces stack, but the shell still uses a sidebar rail and many primary flows remain table-based.

Current mobile behavior:

- Page padding is smaller through the 1080px rule.
- Heroes stack.
- DetailDrawer width changes at `max-width: 720px` to `min(100vw, 96vw)` with reduced padding.
- Secretary/resident form rows stack.
- Resident panels stack.
- Admin secretary event metrics and filters stack at `max-width: 720px`.
- Parsed data tabs horizontally scroll.

Mobile gaps:

- The left sidebar rail remains visible and consumes 72px on phone-sized screens. It should become a hidden off-canvas nav opened by a top app bar button.
- Role switching is not phone-friendly.
- Resident submission remains a 980px min-width table inside a scroll container instead of cards or compact selectable rows.
- Secretary schedule remains a 1020px table.
- Admin Secretary Events and Admin Resident Submissions remain 1440px tables.
- Admin Logs remains a 1320px table.
- Parsed Data can reach 1680px depending on tab.
- Filters are stacked, but not collapsible; dense admin filter bars can dominate the first viewport.
- Drawer footer actions can become cramped because the shared footer does not wrap or become sticky/full-width by contract.

### Narrow Mobile, 480px and below

Narrow mobile needs explicit remediation before resident flows can be considered usable.

Likely narrow-mobile issues:

- The 72px sidebar rail leaves roughly 408px or less for content on a 480px viewport, and roughly 248px on a 320px viewport.
- Tables are technically scrollable in many places, but users must horizontally scroll very wide content to find key actions.
- Drawer width at 96vw leaves a sliver of backdrop rather than feeling like a true fullscreen task surface.
- Inline action rows may wrap unpredictably without a shared button stacking rule.
- Filter fields are usable individually, but dense filters are too tall without a collapsible summary.
- Touch target size is not governed globally; many buttons are visually compact.

## 3. Route Inventory And Priority Matrix

Status terms:

- `Good desktop / partial mobile`: usable on desktop, needs responsive contract before mobile.
- `Scrollable table mobile`: wrapped by horizontal scroll but not optimized for phones.
- `Stub/planned`: route exists as placeholder or exists only in the design spec.
- `High risk mobile`: likely blocks or frustrates phone users.

| Route | Role | Current Responsive Status | Priority | Recommended Mobile Pattern | Likely Files Affected | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| `/login` | all | Not implemented | High | Centered full-bleed auth card, single-column form, 44px controls | `frontend/src/App.tsx`, new login page, `frontend/src/index.css` | Medium |
| `/resident/submissions` | NHG Resident | Desktop/tablet partial; 980px event table; ad-hoc inline card; history list is closer to mobile | High | Mobile event cards with checkbox/select affordance, sticky submit bar, ad-hoc fullscreen modal, history cards | `ResidentSubmissionPage.tsx`, `PageHero.tsx`, `DetailDrawer.tsx` or new modal, `index.css` | High |
| `/resident` | NHG Resident | Redirect to `/resident/submissions` | High | Same as destination | `App.tsx` | Low |
| `/external` | Non-NHG Resident | Stub only | High | Full mobile-first entry/portal placeholder until full 5B routes exist | `StubPage.tsx` or future Non-NHG pages, `navigation.ts`, `index.css` | Medium |
| Non-NHG registration/login/portal/posting/past attendance | Non-NHG Resident | Planned in design spec, not implemented as separate routes | High | Mobile-first forms and card lists from day one; do not retrofit after implementation | future Non-NHG page files, `App.tsx`, `navigation.ts` | High |
| `/secretary/events` | Secretary | Good desktop; 1020px scroll table; drawer form; header partially stacks | Medium | Schedule cards on mobile, period chips horizontal scroll, add/edit drawer fullscreen, sticky form actions | `SecretaryTeachingSchedulePage.tsx`, `DetailDrawer.tsx`, `index.css` | High |
| `/secretary` | Secretary | Redirect to `/secretary/events` | Medium | Same as destination | `App.tsx` | Low |
| Secretary dashboard | Secretary | Planned, not implemented | Medium | Mobile metric cards, compact schedule list | future secretary dashboard page | Medium |
| `/pc/upload-ttf` | Programme PC | Stub only | Medium | Single upload card, compact recent-upload feed, reporting/programme controls stacked | `StubPage.tsx` now; future PC upload page, `UploadCard.tsx`, `index.css` | Medium |
| `/pc/warnings` | Programme PC | Reuses AdminWarningsPage; scrollable warning tables | Medium | Same warning cards/drawer contract as admin, scoped copy only | `AdminWarningsPage.tsx`, `DetailDrawer.tsx`, `index.css` | Medium |
| `/pc/config` | Programme PC | Reuses AdminConfigPage; side nav stacks below 1080px; config tables scroll | Medium | Horizontal section tabs or select on mobile, read-only locks preserved, forms fullscreen | `AdminConfigPage.tsx`, `DetailDrawer.tsx`, `index.css` | High |
| `/admin` | Master Admin | Good desktop; grids stack at tablet/mobile; recent uploads table not mobile-specific | Low | Keep cards stacked; recent uploads becomes compact list; warnings list stays card-like | `AdminHomePage.tsx`, `index.css` | Medium |
| `/admin/upload` | Master Admin | Upload grid stacks below 1080px; UploadCard mostly usable | Low | Single-column upload cards, compact file chip, full-width buttons | `AdminUploadPage.tsx`, `UploadCard.tsx`, `index.css` | Low |
| `/admin/upload/warnings` | Master Admin | Dense filters; grouped table min-width 1160px; drawer details | Low | Collapsible filters, warning issue cards on mobile, fullscreen detail drawer | `AdminWarningsPage.tsx`, `DetailDrawer.tsx`, `index.css` | Medium |
| `/admin/config` | Master Admin | Side nav + table pane; stacks below 1080px; many tables still wide | Low | Section tabs/select, table-to-card for smaller config sets, scroll only for high-density sets, fullscreen edit drawer | `AdminConfigPage.tsx`, `DetailDrawer.tsx`, `index.css` | High |
| `/admin/config/multi` | Master Admin | Dedicated config-like table; drawer form; empty state mostly responsive | Low | Rule cards by tab on mobile, fullscreen edit drawer, tab row scroll | `AdminMultiPostingPage.tsx`, `DetailDrawer.tsx`, `index.css` | Medium |
| `/admin/logs` | Master Admin | Dense filters; advanced filters in details; table min-width 1320px | Low | Keep advanced filters collapsed; log cards on mobile; JSON preview constrained | `AdminLogsPage.tsx`, `DetailDrawer.tsx`, `index.css` | Medium |
| `/admin/upload-logs` | Master Admin | Dense filters; table uses fixed layout and `overflow-x: hidden`; likely truncates on mobile | Low | Audit log cards on mobile; restore intentional scroll or card view; summary chips wrap | `AdminUploadLogsPage.tsx`, `DetailDrawer.tsx`, `index.css` | High |
| `/admin/parsed-data` | Master Admin | Tabs scroll; filters auto-fit; table min-width 980px to 1680px; large correction drawer | Low | Preserve horizontal scroll for desktop/tablet; mobile row summary cards with "View details"; correction editor fullscreen | `AdminParsedDataPage.tsx`, `DetailDrawer.tsx`, `index.css` | High |
| `/admin/secretary-events` | Master Admin | Filters become 2 columns then 1; metrics stack; table min-width 1440px | Low | Event summary cards, collapsible filters, fullscreen detail drawer | `AdminSecretaryEventsPage.tsx`, `DetailDrawer.tsx`, `index.css` | Medium |
| `/admin/submissions` | Master Admin | Filters similar to secretary events; table min-width 1440px | Low | Submission summary cards, preserve NHG terminology, collapsible filters, fullscreen detail drawer | `AdminResidentSubmissionsPage.tsx`, `DetailDrawer.tsx`, `index.css` | Medium |
| `*` | all | Redirect to `/admin` | Low | No special responsive work | `App.tsx` | Low |

## 4. Shared Responsive Design Contract

### Core Approach

Use this order for all future 3J-B/C/D/E work:

```text
fluid layout first
-> breakpoint corrections second
-> route-specific fallbacks only where needed
```

Do not build only for fixed widths such as 390px, 768px, or 1440px. Those widths are useful QA samples, but the UI must remain usable between them. Prefer flexible primitives first: content-sized grids, wrapping rows, max-width constraints, resilient typography, and contained scroll regions. Use breakpoints only when a layout needs a behavior switch, such as table-to-card, drawer-to-fullscreen, or sidebar-to-off-canvas navigation. Route-specific overrides are the last resort when a shared primitive cannot preserve the content or task flow clearly.

### Adaptive Layout Decision Hierarchy

Every page and repeated component should follow this decision process:

1. Does this layout naturally shrink?
2. If not, can it wrap?
3. If not, can it become a card/list?
4. If not, can it be contained in an intentional scroll area?
5. Does the whole page avoid horizontal overflow?

This hierarchy is a shared rule for all future 3J-B/C/D/E prompts. It applies before adding route-specific CSS. A page passes only when the full page avoids horizontal overflow, even if a table or tab strip intentionally scrolls inside its own declared container.

### Adaptive CSS Guidance

Preferred adaptive CSS patterns:

```css
width: min(100%, 72rem);
max-width: 100%;
grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
flex-wrap: wrap;
grid-template-columns: minmax(0, 1fr);
font-size: clamp(0.875rem, 0.85rem + 0.2vw, 1rem);
overflow-wrap: anywhere;
overflow-x: auto; /* only on declared scroll wrappers */
```

Use container-safe scroll wrappers for dense tables, tabs, code previews, and raw JSON. The scroll wrapper owns the overflow; the page must not.

Avoid:

- Fixed desktop widths leaking onto mobile.
- Hiding important actions only to fit width.
- Page-level horizontal overflow.
- Overfitting to named device sizes.
- Using `overflow-x: hidden` to mask broken layout unless a real mobile/card alternative exists.
- Duplicating shared responsive primitives in route-specific CSS without a route-specific reason.

### Breakpoints

Use one shared set of breakpoints for future responsive code:

- `mobile`: `<= 640px`
- `tablet`: `641px - 1024px`
- `desktop`: `>= 1025px`
- `wide`: `>= 1280px`

Breakpoints are behavior-switch guardrails, not fixed device targets. Layouts should remain usable between breakpoints, and the manual QA widths in this document are samples rather than design assumptions.

Implementation note: existing CSS uses 1280px, 1080px, 900px, 880px, 860px, 720px, and 1120px. Phase 3J-B should introduce shared variables/comments and migrate new responsive rules toward the contract. Existing page-specific breakpoints can remain temporarily when they are harmless, but new responsive fixes should use the contract and should not overfit to the sample QA widths.

### App Shell And Navigation

Navigation strategy:

```text
desktop: full sidebar
tablet: rail or collapsible nav if usable
phone: no rail; top menu + off-canvas nav
```

Desktop and wide:

- Keep the current 248px sidebar on wide screens.
- It is acceptable to keep a collapsed 72px rail on tablet if labels are available through accessible names/tooltips and the role switcher is usable.

Tablet:

- Use either the 72px rail with an expand action or an off-canvas nav. Prefer one pattern and apply it consistently.
- Role switcher must open in a content-width popover or modal, not a 72px constrained container.

Mobile:

- Replace the sidebar rail with a top app bar menu button.
- The nav opens as an off-canvas panel with role block, role switcher, navigation items, scope, and footer actions.
- Body scroll should be locked while the mobile nav is open.
- Current route and role must remain visible in the app bar or mobile nav header.
- The 72px rail should not remain on phone widths.
- The role switcher must remain usable at narrow widths.

### Page Hero

- Desktop: keep title/subtitle left and meta/actions right.
- Tablet/mobile: stack title, meta, and actions; actions wrap and become full width when there are two or fewer primary actions.
- On mobile, title should stay readable without horizontal overflow. Do not use viewport-width font scaling.
- Meta chips should wrap naturally and never force page-level overflow.

### Cards And Grids

- Desktop: preserve existing 2, 3, 4, and 8/4 layouts.
- Tablet: use two columns only where cards are small and comparable; otherwise one column.
- Mobile: all major page sections and upload cards become one column.
- Repeated metric cards should use two columns on tablet and one column on narrow mobile.
- Avoid nested cards when converting tables to cards; use one card per repeated record.

### Tables

Use three table patterns:

1. `ResponsiveScrollTable`: for data-heavy admin tables where preserving columns matters. The scroll container owns horizontal overflow. The page must not overflow.
2. `ResponsiveCardList`: for resident, secretary, warnings, logs, and review tables on mobile. Each row becomes a card with the primary label, key metadata, status, and row action.
3. `CompactKeyValueTable`: for small configuration tables where a card or definition-list layout is clearer than horizontal scrolling.

Rules:

- No page-level horizontal overflow at arbitrary narrow widths. QA sample widths include 320px, 375px, 390px, 414px, 480px, 640px, 768px, 1024px, 1280px, and 1440px.
- Intentional table overflow must be contained by `.table-scroll` or a successor utility.
- Mobile row cards must expose the same row click/detail affordance as the table row.
- Desktop table column density should not be reduced unless the route-specific plan says so.

Table strategy hierarchy:

```text
Resident / Secretary flows:
desktop table -> mobile cards

Admin review pages:
desktop table -> tablet contained horizontal scroll -> mobile cards where practical

Very dense Parsed Data / Config tables:
desktop table -> contained horizontal scroll acceptable
but no page-level horizontal overflow
```

Card conversion is preferred for user task flows because users need to act quickly, especially residents and secretaries on phones. Contained horizontal scroll is acceptable for dense admin audit/config data if card conversion would reduce clarity or hide important comparisons. The scroll must be inside a clear container, not the whole page.

### Filters

Desktop:

- Keep visible filter bars for admin/PC pages.

Tablet:

- Use two-column filter grids where practical.

Mobile:

- Filter bars collapse into a summary header with a `Filters` button.
- Active filters render as chips below the summary.
- Expanding filters shows a single-column form.
- `Clear filters` remains visible when any filter is active.
- Advanced filters in Admin Logs stay inside `<details>` and default closed.

### Drawers And Modals

Drawer and modal strategy:

```text
large viewport: right drawer
medium viewport: wider drawer or constrained drawer
small viewport: fullscreen task surface
```

Desktop/tablet:

- Keep right-side `DetailDrawer` for detail review and edit flows.

Mobile:

- `DetailDrawer` becomes fullscreen: `inset: 0`, `width: 100vw`, no side gap.
- Drawer header remains sticky at top.
- Drawer footer remains sticky at bottom, with full-width stacked buttons when space is tight.
- Long forms scroll only inside the drawer body.
- Destructive and save actions remain visible without requiring horizontal scrolling.
- Do not keep a desktop-width drawer on mobile.
- Forms and drawers must remain usable when the virtual keyboard reduces vertical space.

Dedicated modals:

- If a future modal is narrower than 640px on desktop, it should become fullscreen on mobile.
- Resident ad-hoc teaching should use a fullscreen mobile task surface, even if implemented as a drawer under the hood.

### Sticky Bottom Actions

Use sticky bottom actions for phone-first flows:

- Resident event submission: selected count + Submit button.
- Resident ad-hoc review/confirm step.
- Secretary add/edit teaching form.
- Config create/edit drawers.

Rules:

- Sticky bars must respect safe-area insets.
- Primary action remains reachable at 320px width.
- Buttons should stack vertically if two buttons cannot fit at 44px min height.

### Touch Targets

- Minimum interactive target: 44px by 44px on mobile.
- Compact chips and badges can be smaller only when not interactive.
- Checkbox rows must make the row label clickable where possible.
- Icon-only controls require `aria-label`.

### Typography And Spacing

- Keep existing desktop typography.
- On mobile, reduce page padding before reducing font size.
- Mobile page padding target: 16px; narrow mobile can use 12px inside dense task surfaces.
- Card padding can reduce from 20-24px to 14-16px.
- Do not use negative letter spacing or viewport-scaled font sizes.

### Horizontal Overflow

- `html`, `body`, and root app containers must not create page-level horizontal scroll.
- Scrollable table containers may scroll horizontally, but they need visible affordance through clipped edge/shadow or clear density.
- `overflow-x: hidden` on table wrappers is risky unless a card view replaces the table. Audit `upload-log-table-card .table-scroll` specifically.

## 5. Implementation Phases 3J-B Through 3J-F

### 3J-B - Fluid Responsive Foundation

One agent.

Goal: create the shared fluid responsive primitives before route-level fixes. This phase should make arbitrary viewport adaptation the default and prevent page-level horizontal overflow before route-specific mobile cards are added.

Scope:

- AppShell adaptive navigation: desktop sidebar, usable tablet rail/collapsible nav, phone top menu + off-canvas nav.
- PageHero fluid stacking and action wrapping.
- Shared responsive grid/card utilities in `index.css` using fluid primitives first.
- DetailDrawer adaptive behavior: right drawer on large viewports, constrained drawer on medium viewports, fullscreen task surface on small viewports.
- Shared sticky footer/action behavior for drawers.
- Shared filter bar collapsed mobile behavior.
- Baseline table overflow rules and helper classes.
- Global breakpoint comments or CSS custom property documentation.

Likely files:

- `frontend/src/components/AppShell.tsx`
- `frontend/src/components/PageHero.tsx`
- `frontend/src/components/DetailDrawer.tsx`
- `frontend/src/config/navigation.ts`
- `frontend/src/index.css`

Verification:

- Desktop shell still works at 1440px and 1280px.
- Mobile shell has no 72px rail at phone widths.
- Role switcher is usable across narrow widths, not only at 390px.
- Drawers are fullscreen on small viewports and actions are reachable.
- Existing routes still render.
- No page-level horizontal overflow at arbitrary widths between QA checkpoints.

### 3J-C - Resident / Non-NHG Adaptive Flows

One agent.

Goal: make likely phone flows adapt cleanly end to end across arbitrary viewport widths.

Scope:

- `/resident/submissions` event list uses desktop table -> mobile cards when the table no longer supports the task clearly.
- Resident submit action becomes sticky bottom action on mobile.
- Resident ad-hoc inline card is converted or restyled into a mobile task surface consistent with the future ad-hoc modal.
- Resident past attendance list remains card-based and gets touch/spacing polish.
- `/external` stub becomes mobile-safe and uses `Non-NHG Resident` terminology.
- Planned Non-NHG pages should inherit the same card/list/form contract when implemented.
- Any login/role entry route introduced later should be mobile-first.
- Primary actions remain reachable when content wraps or the virtual keyboard reduces vertical space.

Likely files:

- `frontend/src/pages/resident/ResidentSubmissionPage.tsx`
- `frontend/src/pages/StubPage.tsx`
- `frontend/src/App.tsx` if login or Non-NHG routes are added later
- `frontend/src/config/navigation.ts`
- `frontend/src/index.css`

Verification:

- A resident can select and submit events at narrow, mid, and wide sample widths without page-level horizontal scroll.
- Weekend compliance warnings remain visible.
- Submit action remains reachable after selecting events.
- Ad-hoc submission fields are usable with the keyboard open on phone.
- UI uses `NHG Resident` and `Non-NHG Resident` only.

### 3J-D - Secretary Adaptive Flows

One agent.

Goal: make schedule review and teaching creation adapt cleanly on tablet, phone, and in-between viewport widths.

Scope:

- `/secretary/events` follows desktop table -> mobile cards for the schedule task flow.
- Reporting period chips horizontally scroll or wrap cleanly.
- Header action cluster stacks with full-width primary action on mobile.
- Selection toolbar works with mobile cards.
- Add/edit/duplicate teaching drawer becomes fullscreen on mobile.
- Date/time/name/CME fields have mobile-safe stacking and sticky footer actions.
- Secretary-specific CSS should reuse shared fluid primitives wherever possible.

Likely files:

- `frontend/src/pages/secretary/SecretaryTeachingSchedulePage.tsx`
- `frontend/src/components/DetailDrawer.tsx`
- `frontend/src/index.css`

Verification:

- Add Teaching can be opened, filled, and closed at narrow phone widths.
- Table/card selection, duplicate, delete, and edit affordances remain clear.
- Public holiday validation remains visible and does not hide Save state.
- No route crash when reporting period chips overflow.
- No page-level horizontal overflow between breakpoint guardrails.

### 3J-E - Admin / PC Adaptive Data Pages

This may be split into route groups. Each group should be handled by one agent or one focused pass to avoid broad, brittle CSS edits.

Group 1: Logs and warnings

- `/admin/logs`
- `/admin/upload-logs`
- `/admin/upload/warnings`
- `/pc/warnings`

Mobile patterns:

- Collapsible filters.
- Log/warning cards on mobile.
- Fullscreen detail drawer.
- JSON/raw previews constrained to drawer width.
- Fix upload logs overflow behavior so content is not silently clipped.
- Use contained scroll only inside declared wrappers when card conversion is not practical.

Group 2: Parsed Data and Config

- `/admin/parsed-data`
- `/admin/config`
- `/admin/config/multi`
- `/pc/config`

Mobile patterns:

- Parsed data keeps scroll table on tablet, mobile summary cards for rows.
- Correction editor/detail drawer becomes fullscreen.
- Config nav becomes horizontal tabs or section select.
- Small config tables can become key/value cards; high-density tables can stay in contained scroll where cards would be misleading.
- Very dense Parsed Data / Config tables may use contained horizontal scroll on small screens, but the page itself must not overflow.

Group 3: Admin Secretary Events and Resident Submissions

- `/admin/secretary-events`
- `/admin/submissions`

Mobile patterns:

- Collapsible filters.
- Metric cards stack.
- Tables become event/submission cards.
- Detail drawer fullscreen.
- Keep admin pages read-only and do not call resident/secretary mutation endpoints.

Group 4: Upload, Home, PC Upload, PC Export

- `/admin`
- `/admin/upload`
- `/pc/upload-ttf`
- future `/pc/export`

Mobile patterns:

- Home tiles/summary lists stack.
- Upload cards remain single-column and full width.
- PC upload stub or future page follows UploadCard responsive rules.
- Future export page uses filter collapse and cards/table scroll by density.

Likely shared files:

- `frontend/src/pages/admin/AdminWarningsPage.tsx`
- `frontend/src/pages/admin/AdminLogsPage.tsx`
- `frontend/src/pages/admin/AdminUploadLogsPage.tsx`
- `frontend/src/pages/admin/AdminParsedDataPage.tsx`
- `frontend/src/pages/admin/AdminConfigPage.tsx`
- `frontend/src/pages/admin/AdminMultiPostingPage.tsx`
- `frontend/src/pages/admin/AdminSecretaryEventsPage.tsx`
- `frontend/src/pages/admin/AdminResidentSubmissionsPage.tsx`
- `frontend/src/pages/admin/AdminHomePage.tsx`
- `frontend/src/pages/admin/AdminUploadPage.tsx`
- `frontend/src/components/DetailDrawer.tsx`
- `frontend/src/components/UploadCard.tsx`
- `frontend/src/index.css`

Verification:

- Every admin route renders at arbitrary narrow widths without page-level horizontal overflow.
- Intentional table scroll remains inside containers.
- Admin and PC scoping behavior is not changed.
- No backend/API contract changes.
- Shared responsive primitives are reused before route-specific overrides are added.

### 3J-F - Cross-Viewport QA Sweep

One agent.

Goal: verify consistency after all route groups are complete across arbitrary viewport widths. The listed widths are sample checkpoints, not design targets.

Scope:

- Cross-route viewport sweep.
- Role switcher and mobile nav sanity.
- Touch target checks.
- Drawer/modal usability checks.
- No route crashes.
- No route removals.
- No terminology regression.
- Confirm resident phone submission flow.
- Confirm admin pages do not call resident/secretary endpoints incorrectly.
- Confirm layouts remain usable between breakpoint guardrails and do not depend on named device sizes.

Required commands:

- `npm run lint`
- `npm run typecheck`
- `npm run build`

Manual viewport sample checklist:

- 320px
- 375px
- 390px
- 414px
- 480px
- 640px
- 768px
- 1024px
- 1280px
- 1440px

Also test at least two arbitrary in-between widths, such as 536px and 911px, to catch overfitting to named checkpoints.

## 6. Per-Route Recommended Mobile Patterns

### High-Priority Mobile-First Flows

`/resident/submissions`

- Replace the mobile table with event cards showing teaching name, date/time, posting, type/global badge, submitted state, and a large checkbox/select action.
- Keep desktop table.
- Use a sticky bottom submit bar on mobile.
- Preserve weekend warning behavior above the sticky submit bar or inside it as a warning state.
- Keep past submissions as cards; improve spacing and touch targets.

Resident ad-hoc teaching

- Use a fullscreen mobile task surface.
- Date should remain first.
- Derived posting and PH validation must remain visible.
- Confirmation/submit action should be sticky at the bottom.

`/external` and future Non-NHG routes

- Current `/external` is a stub; make the stub mobile-safe and plain.
- Future Non-NHG registration/login/portal/posting/past attendance should start mobile-first.
- Use `Non-NHG Resident` in UI labels while preserving API/domain names internally where already established.

Login / role entry

- Not implemented.
- If introduced in Phase 3J or later, implement as a single-column, full-bleed focus frame with MCR-friendly inputs and 44px controls.

### Medium-Priority Tablet/Mobile Flows

`/secretary/events`

- Use cards on mobile with event name, date/time, type, CME, SMC, selected state, and action affordance.
- Keep table on tablet/desktop with contained horizontal scroll.
- Add/edit/duplicate drawer becomes fullscreen on mobile.
- Selection toolbar must work for both table rows and cards.

`/pc/upload-ttf`

- Current route is a stub. Future page should use a single UploadCard and recent upload feed.
- Programme controls must stack and remain above the dropzone.

`/pc/warnings` and `/pc/config`

- Reuse admin responsive primitives but preserve Programme PC scope and read-only/global lock behavior.

### Lower-Priority Admin Mobile-Usable Flows

`/admin`

- Home workspace tiles already stack through grid rules.
- Recent uploads mini-table should become a compact list on mobile.
- Warning list can remain card/list-based.

`/admin/upload`

- Upload cards already stack below 1080px.
- Tighten file chip, result actions, and dropzone heights for mobile.

`/admin/upload/warnings`

- Convert grouped warning rows to cards on mobile.
- Keep filter collapse and fullscreen detail drawer.

`/admin/config` and `/admin/config/multi`

- Convert left section nav to tabs/select on mobile.
- Use cards for low-column config sections.
- Keep contained table scroll only where row density matters.

`/admin/upload-logs` and `/admin/logs`

- Use log cards on mobile.
- Keep advanced filters collapsed.
- JSON previews must wrap or scroll inside the drawer, not the page.

`/admin/parsed-data`

- Preserve rich desktop table.
- Mobile should show row summary cards with "View details" and keep raw/source/correction detail inside fullscreen drawer.
- Parsed tabs should remain horizontally scrollable with a clear active state.

`/admin/secretary-events` and `/admin/submissions`

- Convert rows to cards on mobile.
- Keep metrics stacked.
- Keep filters collapsible.
- Preserve read-only admin intent.

## 7. Risk And Complexity Notes

High-risk areas:

- AppShell mobile navigation: it touches every route and role. Keep it isolated and verify route changes carefully.
- DetailDrawer mobile conversion: shared by many admin, secretary, and config flows. A good shared fix helps everywhere; a bad one breaks everywhere.
- Resident event submission: this is the most important phone workflow and must preserve selection/submission behavior.
- AdminParsedDataPage: very large file with correction workflows and tab-specific table widths. Avoid broad rewrites.
- AdminConfigPage: very large file with many embedded CRUD sections and drawers. Responsive work should add shared patterns without changing CRUD logic.
- AdminUploadLogsPage: current table wrapper disables horizontal overflow. This can silently clip data on small screens unless replaced by cards or corrected scroll behavior.

Medium-risk areas:

- Filter bars: many pages use `filter-bar` plus route-specific classes. A shared collapsed filter pattern needs careful opt-in to avoid breaking desktop layouts.
- Role switcher: currently demo-only but route-changing. Mobile treatment must not trap focus or render offscreen.
- Terminology: design docs still contain older labels. Implementation must keep `NHG Resident` and `Non-NHG Resident` in UI.

Open questions:

- Should tablet navigation keep the 72px rail or move to the same off-canvas navigation as mobile?
- Should admin data-heavy pages use mobile cards everywhere, or is contained horizontal table scroll acceptable for some admin-only review pages?
- Should the current inline resident ad-hoc card be converted into a true modal/drawer during 3J-C, or only restyled into a fullscreen section until the full Phase 5A ad-hoc contract is implemented?
- Should `/pc/upload-ttf` remain a stub during responsive work, or should Phase 3J include a responsive shell for the future PC upload page?
- Should a login route be introduced before responsive QA, or should 3J-F mark login as not applicable until auth UI exists?

## 8. Acceptance Criteria

Adaptive responsive implementation is acceptable only when all of the following are true:

- No backend changes.
- No API contract changes.
- No migration changes.
- No auth/scoping behavior changes.
- No route removals.
- No user-facing terminology regression to old `Native Resident` / `External Resident` labels.
- No admin page calls resident or secretary endpoints incorrectly.
- UI remains usable at any reasonable viewport width, not only predefined test widths.
- QA widths are samples, not design targets.
- No page-level horizontal overflow at arbitrary narrow widths, except intentional scroll containers.
- Intentional horizontal scrolling is allowed only inside declared scroll containers.
- Tables become contained scroll tables or mobile cards on mobile.
- Drawers and modals are usable at phone widths.
- Primary actions remain reachable when content wraps.
- Filter controls are usable on mobile and do not consume the whole first viewport by default on dense pages.
- Resident submission can be completed on a phone-sized viewport.
- Role switcher and mobile nav are usable by keyboard and pointer.
- Touch targets for interactive controls are at least 44px by 44px on mobile, or the full row/card is clickable.
- Forms and drawers remain usable when the virtual keyboard reduces vertical space.
- Route-specific CSS does not duplicate shared responsive primitives unnecessarily.
- `NHG Resident` and `Non-NHG Resident` labels are preserved.
- `npm run lint` passes.
- `npm run typecheck` passes.
- `npm run build` passes.

## 9. Manual QA Checklist

Run this checklist during 3J-F and whenever a phase touches shared shell/drawer/table behavior. These widths are sample checkpoints, not fixed targets. Also resize continuously between them or test arbitrary in-between widths to confirm fluid behavior.

Viewport samples:

- 320px phone
- 375px phone
- 390px phone
- 414px phone
- 480px narrow mobile
- 640px mobile breakpoint edge
- 768px tablet
- 1024px tablet breakpoint edge
- 1280px wide threshold
- 1440px desktop
- 536px arbitrary in-between sample
- 911px arbitrary in-between sample

Shell:

- Mobile nav opens and closes.
- Body does not scroll behind open nav.
- Role switcher opens within viewport.
- Current role and route are understandable.
- Breadcrumbs do not force horizontal overflow.

Resident:

- `/resident/submissions` loads.
- Event cards/table show pending and submitted states.
- Selecting one event updates selected count.
- Submit remains reachable.
- Weekend warning remains visible when applicable.
- Ad-hoc form/task surface can be completed.
- Past attendance remains readable.

Non-NHG:

- `/external` stub or future route loads at all viewports.
- UI uses `Non-NHG Resident`.
- Any future registration/posting/past attendance pages are single-column on mobile.

Secretary:

- `/secretary/events` loads.
- Period controls do not overflow the page.
- Add Teaching opens.
- Add/Edit form fields are usable on mobile.
- Drawer/form footer actions are reachable.
- Selection toolbar works on mobile cards or table.

Admin and PC:

- `/admin`, `/admin/upload`, `/admin/upload/warnings`, `/admin/config`, `/admin/config/multi`, `/admin/logs`, `/admin/upload-logs`, `/admin/parsed-data`, `/admin/secretary-events`, `/admin/submissions`, `/pc/warnings`, and `/pc/config` load.
- Filters collapse or stack as intended.
- Tables either become cards or scroll inside containers.
- Detail drawers are fullscreen on mobile.
- Raw JSON/source previews do not break layout.
- Admin pages remain read-only where intended.

Automated checks:

- Run `npm run lint` from `frontend/`.
- Run `npm run typecheck` from `frontend/`.
- Run `npm run build` from `frontend/`.

## 10. Open Questions

1. Confirm whether tablet should use a labeled collapsible rail or the same off-canvas nav as mobile.
2. Confirm whether all admin data-heavy mobile tables should become cards, or whether contained horizontal scroll is acceptable for lower-priority admin pages.
3. Confirm whether 3J-C should convert resident ad-hoc into a modal/fullscreen drawer now or only make the current inline card mobile-safe.
4. Confirm whether `/pc/upload-ttf` should remain a responsive stub until the real PC upload page exists.
5. Confirm when login and full Non-NHG routes will be implemented so 3J-F can mark them tested or not applicable.
