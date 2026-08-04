# MATA Demo UI Design Spec

| Field | Value |
| --- | --- |
| **Status** | Frontend demo design source |
| **Design direction** | Version B — Modern SaaS Admin |
| **Scope** | Presentation demo UI after Phase 3 / 4 / 5A / 5B backend implementation |
| **Source** | Claude Design output plus exported screenshots |
| **Data policy** | This document uses synthetic placeholder data only. It must not contain real resident data, real MCR numbers, or values copied from uploaded source workbooks. |

## Authority

This document defines **frontend visual design, screen layout, interaction patterns, and demo flow only.**

Backend / API behavior must follow:

- `docs/api.md`
- `docs/schema.md`
- `docs/business-logic.md`
- `docs/parsing.md`
- `docs/99_decision_log_and_gap_audit.md`
- `AGENTS.md`

If this design spec conflicts with the source-of-truth docs above, the **source-of-truth docs win**.

## Implementation Use

- Codex should use this file and the screenshots in `docs/assets/demo-ui/` to implement the React / Vite / Tailwind demo UI.
- Do not infer backend behavior from this design file.
- Do not infer real data from screenshot placeholders. All names, MCRs, workbook references, and counts shown are synthetic demo values.
- The original two draft UI screenshots were used only as early design references. **Do not implement against them.**
- Codex should implement against the Version B Modern SaaS screenshots in `docs/assets/demo-ui/`, not the original draft screenshots.

## Screenshot Assets

- Screenshot assets are stored under `docs/assets/demo-ui/` and referenced by relative path only.
- No base64-embedded images.
- The original two draft screenshots are **not** included as implementation references.
- If the current prototype contains any data that resembles real residents or real workbook values, sanitize the prototype to use the synthetic placeholder set defined in this document before capturing screenshots.

See the **Screenshot Reference List** at the end of this document for the recommended file names.

---

## 1. Design System Foundations

### 1.1 Typography

| Use | Family | Notes |
| --- | --- | --- |
| Display / UI | Inter (weights 400 / 500 / 600 / 700) | Primary UI face. |
| Monospace | JetBrains Mono (weights 400 / 500 / 600) | MCR, posting codes, SMC event codes, sheet/row/cell traceability, programme codes. |

**Scale**

| Token | Size / Leading | Used for |
| --- | --- | --- |
| Page title | 28 / 36, weight 600 | Hero title |
| Page subtitle | 13 / 20, weight 500, purple | Programme / posting subtitle directly under title |
| Section heading | 18 / 24, weight 600 | Card / drawer / modal heading |
| Body | 14 / 20, weight 400 | Default |
| Secondary | 13 / 18, weight 400 | Helper text |
| Caption | 12 / 16, weight 600, +0.06em tracking, uppercase | Table column headers, eyebrow labels |
| Mono inline | 13 / 20, weight 400 | Inline code values |

### 1.2 Colors

**Sidebar (dark)**

| Token | Value | Use |
| --- | --- | --- |
| `sidebar/bg` | `#13132B` | Sidebar background |
| `sidebar/surface` | `#1F1F3D` | Active item, popover surface |
| `sidebar/text` | `#C8C9DE` | Primary sidebar text |
| `sidebar/muted` | `#7A7C9C` | Muted sidebar text |

**Canvas**

| Token | Value | Use |
| --- | --- | --- |
| `canvas/bg` | `#F4F5F8` | Page background |
| `canvas/bg-2` | `#EAECF2` | Hover, tag fill |
| `card/bg` | `#FFFFFF` | Card surface |
| `line` | `#ECEDF2` | Hairline border |
| `line-2` | `#DFE1EB` | Input border |
| `ink` | `#10121F` | Primary text |
| `ink-2` | `#2C2F45` | Secondary text |
| `ink-3` | `#5B5F73` | Tertiary text |
| `ink-4` | `#9499AD` | Muted text |
| `ink-5` | `#C8CBD9` | Disabled / placeholder |

**Brand purple**

| Token | Value | Use |
| --- | --- | --- |
| `purple/primary` | `#6D3BD9` | Primary action, accent bar, active pill |
| `purple/hover` | `#7C4DE6` | Hover state |
| `purple/deep` | `#3C1E80` | On-tint text |
| `purple/tint` | `#EDE4FE` | Tag fill, drawer accents |
| `purple/tint-2` | `#F6F0FF` | Selected row, hover tint |

**Green commit (Submit)**

| Token | Value | Use |
| --- | --- | --- |
| `green/primary` | `#0F4F32` | Resident Submit pill background |
| `green/hover` | `#0B3B26` | Submit hover |
| `green/tint` | `#D6EBDF` | Success badge background |
| `green/text` | `#1F7A4D` | Success text |

**Severity**

| Severity | Filled bg | Filled text |
| --- | --- | --- |
| Critical | `#FEE4E2` | `#B42318` |
| Warning | `#FEF0C7` | `#B7791F` |
| Info | `#DCEAFE` | `#1E5FCB` |
| Resolved | `#D6EBDF` | `#1F7A4D` |

### 1.3 Spacing

- Base unit: **8px**.
- Page gutter: **32px**.
- Card padding: **24px** (compact: 16–18px).
- Table cell padding: **12px × 16px**.
- Drawer / modal padding: **24px**.
- Field gap inside forms: **14–16px**.

### 1.4 Layout

- Target presentation viewport: **1440 × 900**.
- Sidebar width: **248px expanded**, **72px collapsed rail** (auto-collapse below 1280px).
- App bar height: **64px**.
- Content max-width: **1280px**, side-padded.
- Grid: **12 columns**, **24px gutter**.

### 1.5 Shape & Elevation

- Card radius: **16px**.
- Input radius: **10px**.
- Pill radius: **999px** (primary CTAs, chips, status pills).
- Card border: 1px `line`.
- Shadow 1 (resting): `0 1px 2px rgba(16,18,40,0.04)`.
- Shadow 2 (hover): `0 8px 24px rgba(16,18,40,0.06)`.
- Shadow 3 (modal / drawer): `0 20px 50px rgba(16,18,40,0.18)`.

### 1.6 Icons

- Line-style icon set, **1.75px stroke**, **18px default size** (sidebar 20px, inline caption 14px).
- Style is consistent across all screens; no decorative or filled icons mixed in.

### 1.7 DRAFT Stamp

- Placement: top-right of app bar.
- Style: monospace, 11px, letter-spaced (+0.18em), color `ink-4`.
- Vertical purple tick to its left, matching the page-title accent bar.
- Present on all demo screens. Removed when the build moves out of demo mode.

---

## 2. App Shell

### 2.1 Sidebar (dark, 248px)

Top to bottom:

1. **User block.** Avatar (36px circle, gradient fill, initials), full name, italic role label, chevron-down. Click opens the **role switcher popover**. Small bell glyph floats top-left of the avatar with a notification dot (decorative only).
2. **Primary nav.** Icon + label rows. Active item is a white rounded pill with purple text. Inactive items are sidebar-text color and lighten on hover. Optional count chip on the right of each item.
3. **Workspace block.** Lower section. Eyebrow label varies per role: *Scope*, *Assigned Programme*, *Posting Site*, *Current Posting*, *Non-NHG Resident*. Value line shows the resident's MCR / programme / posting with a small purple dot.
4. **Footer.** Settings, Log out — small underlined links.

### 2.2 Role Switcher (demo aid)

- Popover appears under the user block.
- Lists five options:
  - Master Admin
  - Programme PC
  - Secretary
  - NHG Resident
  - Non-NHG Resident
- Current role is highlighted with a purple-tinted background and a check icon.
- Each option shows the scope label (e.g. *TTSH Geriatric Medicine*).
- Footer note inside the popover (italic, muted): "Demo aid only — not in production."

### 2.3 App Bar (64px)

- Left: breadcrumb chain (e.g. *Master Admin › Upload Files*). Current crumb bold.
- Center: page-local search field, 360px pill, with placeholder "Search this page".
- Right: optional decorative bell icon + DRAFT stamp.

### 2.4 Page Hero

- Title (28/36) with a 3px vertical purple accent bar on its left.
- Purple subtitle directly under the title (programme, posting, or role scope).
- Meta row on the right: last-updated time, record count, scope chip.
- Primary action on the far right.

---

## 3. Screen Specifications

In all screens below, data references are synthetic placeholders.

### S1 — Master Admin Home

**Hero.** Title: *Welcome back, Demo Admin*. Subtitle: *Master Admin · All programmes · System overview*. Meta: last full sync timestamp, unresolved-warning count. Actions: secondary *Refresh*, primary *Upload files*.

**Row 1 — Source status (4 cards, 12-col split 3/3/3/3).**

Each card:

- Icon glyph (top-left), severity-coloured status badge (top-right).
- Source name: *RDB Posting Schedule*, *Teaching Target File*, *FormF1*, *Academic Calendar / Public Holidays*.
- "Last uploaded" line with timestamp and uploader.
- "Upload →" link.

Status states: **Current** (green), **Stale · >30d** (amber), **Missing** (red).

**Row 2 — Workspace tiles (6 tiles, 12-col split 2/2/2 over two rows).**

- Upload Files
- Configuration
- Upload Logs
- Parsed Data
- Secretary Events
- Resident Submissions

Each tile: icon, title, single-line description, count chip, "Open →" footer.

**Row 3 — Insight split (8/4).**

- Left (8-col): **Recent uploads** mini-table — Source · Uploader · When · Records · Warnings · Status. Footer "View all".
- Right (4-col): **Unresolved warnings** vertical list of top 5 items, each with a severity dot, warning type tag, subject preview, chevron. Footer "All warnings →".

**States.** Empty hero ("No uploads yet — start by uploading the RDB"); skeleton loaders for both bottom panels; banner if parser is offline.

---

### S2 — Upload Excel Files

**Hero.** Title: *Upload Files*. Subtitle: *Master Admin · Source workbooks*. Meta: source count + latest source.

**Body.** Four upload cards in a **2 × 2 grid**, equal height. Each card contains:

- File-type glyph, source name, "Last upload" line, source-current/stale/missing badge.
- (TTF card only) **Programme dropdown**, required.
- Drop zone with dashed border. "Drop .xlsx here or **Browse**".
- Upload button.

**Upload state machine (per card):**

| State | Visual |
| --- | --- |
| Idle | Dashed drop zone, "Browse" link. |
| File selected | Solid-border zone with file chip (name + size + remove). Upload button enabled. |
| Uploading | Determinate progress bar with percentage. Cancel link. |
| Parsing | Indeterminate shimmer bar with status text "Validating rows…". |
| Success | Green-tinted result block: "X created · Y updated · Z warnings". Buttons: *Upload another* + *Review warnings*. |
| Failure | Red-tinted result block with reason ("Sheet [name] missing required column [column_name]"). Buttons: *Retry* + *Download error report*. |

**Footer callout (info).** *Backend assumption — Parser runs server-side and returns `created`, `updated`, `warnings_count` per upload. Progress in this prototype is simulated.*

---

### S3 — Upload Results / Warning Review

**Hero.** Title: *Warnings*. Subtitle: count of unresolved across N uploads. Action: *Refresh*.

**Filter bar (sticky card).**

- Upload type dropdown (RDB / TTF / FormF1 / PH / All).
- Severity dropdown (Critical / Warning / Info / All).
- Programme dropdown.
- Reporting period dropdown.
- Search input.
- *Clear filters*.

**Body.** Table **grouped by upload type**. Each group has a collapsible header (icon, group name, count).

**Table columns:**

| Column | Notes |
| --- | --- |
| ☐ Select | Bulk select |
| Severity | Coloured dot |
| Type | Mono tag — `unmatched_multi_posting`, `unknown_loa_type`, `orphaned_attendance`, `mcr_not_found`, `duplicate_mcr_error` |
| Resident | E.g. *Resident A* |
| MCR | Mono, e.g. `M00001A` |
| Programme | Code |
| Month | E.g. *May 2026* |
| Source | Mono, e.g. `Sheet Phase 3:R42:J42` |
| Status | *Unresolved* / *Resolved* / *Dismissed* |
| ⋯ | Row action chevron |

**Bulk toolbar.** Appears on selection: *Mark resolved*, *Dismiss*, *Reassign*.

**Warning Detail Drawer** (slide-over, 480–520px):

- Header: severity badge + mono type tag + warning ID.
- **Subject** block (resident name, MCR, programme, month).
- **Source traceability** block (mono): Upload, Sheet, Row, Cell.
- **Message** text in a recessed card.
- **Suggested action** in a purple-tinted callout.
- Footer: *Open related config →* (visible only for `unmatched_multi_posting`), *Dismiss*, *Mark resolved*.

**Deep link.** *Open related config →* closes the drawer and navigates to Multi-Posting Rules with a pre-filled edit drawer and a resolution callout.

---

### S4 — All-in-One Admin Configuration

**Hero.** Title: *Configuration*. Subtitle scope chip — *All programmes* (Master Admin) or programme name (PC).

**Layout.** Left sub-nav (224px) + right content pane.

**Sub-nav sections:**

1. Reporting Periods
2. Public Holidays
3. Programmes
4. LOA Types
5. Multi-Posting Rules
6. Posting Groups
7. Weekend Exceptions
8. Global Session Types

Each item shows a small count badge. Items master-admin-only show a lock icon when viewed by a Programme PC.

**Right pane (per section).**

- Section header: title + description + *+ Add* button (hidden when locked).
- Toolbar (search / column visibility / density).
- Table with section-specific columns.
- Row click → edit slide-over.

**Edit slide-over (480–520px).**

- Header: *Edit [entity]* + entity ID chip.
- Section-specific fields.
- Inline validation under each field.
- Footer: *Delete* (red ghost, left) · *Cancel* · *Save* (purple primary, right).

**Programme PC scope.** Global-only sections (Public Holidays, LOA Types, Global Session Types) are visible **read-only** with a *Master Admin only* lock badge and disabled actions.

**Per-section states.** Empty ("No reporting periods configured yet"), Loading skeleton, Error banner with retry.

---

### S5 — Multi-Posting Rules CRUD

Deep view of the Multi-Posting Rules section. Featured because it's the warning-resolution landing.

**Hero.** Title: *Multi-Posting Rules*. Subtitle: *Configuration · 3 rule types*. Action: *+ Add rule*.

**Sub-tabs (underline).**

- Main Posting
- To Combine Posting
- Half Month Posting

Each tab shows a row count pill.

**Helper info banner under tabs.** *"Changes apply on next RDB re-upload."*

**Table columns** (all codes monospaced):

- `programme_code`
- `posting_code_1`
- `posting_code_2`
- `rule_type` (mono tag)
- `combined_label`
- `main_posting_code`
- `exclusion_code`
- ⋯

**Add / Edit drawer.**

- Programme dropdown (limited by role scope).
- `posting_code_1` / `posting_code_2` (mono inputs).
- `rule_type` dropdown (locked to active tab).
- `combined_label` text input.
- `main_posting_code` (visible only on Main Posting tab).
- `exclusion_code` text input.
- **Warning-resolution callout** at the top of the drawer when deep-linked from a warning. Example synthetic context: *"Resolving warning #demo-1 — `unmatched_multi_posting` for Resident A · MCR M00001A · May 2026."*
- Footer: *Cancel* · *Delete* (edit only) · *Save & resolve warning* (when in warning context) / *Save*.

---

### S6 — Programme PC TTF Upload

**Hero.** Title: *Upload Teaching Target File*. Subtitle: *Programme PC · [programme name]*.

**Top callout (purple).** *"Match the latest shared Teams folder copy. Upload only the most recent TTF file."*

**Body — two-column 8/4.**

- **Left (8-col).** Single upload card.
  - Programme dropdown locked to the PC's assigned programmes (single-programme PCs see a static chip).
  - Drop zone with the same upload state machine as S2.
- **Right (4-col).** *Recent TTF uploads* mini-feed showing this PC's TTF uploads only — file name (mono), when, warnings count.

**After upload success.** Inline success card includes *Review warnings →* which deep-links to S3 filtered to `upload_type=TTF, programme=[this]`.

**Visibility rule.** No RDB / FormF1 / PH cards on this screen.

**Footer callout (info).** *"Backend assumption — Programme PCs may upload TTF only for programmes in their `programme_scope` array. Server enforces this; the dropdown is constrained client-side as a courtesy."*

---

### S7 — Secretary Teaching Schedule

**Hero.** Title: *Teaching Schedule*. Subtitle posting — e.g. *TTSH Geriatric Medicine*. Meta: scope chip *"Scoped to TTSH Geriatric Medicine"*. Actions: *Export*, *+ Add Teaching*.

**Reporting period chips row.**

- Active period filled in purple, e.g. *AY25 2H (Jan–Jun 2026)*.
- Adjacent period outlined, e.g. *AY26 1H (Jul–Dec 2026)*.

**Contextual toolbar.**

- No selection: helper hint *"Select rows to edit, duplicate, or delete"*.
- With selection: row count, *Edit*, *Duplicate*, *Delete* (danger ghost), *Clear*.

**Table columns:**

| Column | Notes |
| --- | --- |
| ☐ | Bulk select |
| Teaching Type | Mono tag (e.g. *Department/Programme Teaching*) |
| Name of Teaching | Body, weight 500 |
| Date | Mono |
| Start Time | Mono |
| Duration | E.g. 1h |
| CME Pts | *Yes* (success outline badge) or *No* (neutral badge) |
| SMC Event | Mono |
| Created | Muted |

**Add / Edit Teaching modal (560px).**

Fields (top to bottom):

- Teaching name.
- Two-column row: Session type (dropdown from Global Session Types) + CME points awarded (Yes/No toggle).
- Date picker — inline calendar (custom). Public holidays are highlighted in red. Picking a PH date triggers an **error state**: red field border + inline error *"Cannot create a teaching on a public holiday — [PH name]"*. Save is disabled.
- Two-column row: Start time + Duration.
- SMC event code (mono input, visible only when CME = *Yes*).
- Footer: *Cancel* · *Add Teaching* / *Save*.

**Delete confirmation modal.** *"Delete N teachings? This cannot be undone. Deletion is unavailable for a teaching with linked attendance; no submission is detached."*

---

### Evolved Teaching Name management (future UX; not implemented in Phase A)

The current legacy parser/configuration controls remain the legacy A-K
transition UI through B1. Phase A introduces no page, route, or component.
Scheduled-event runtime source selection is persisted-ID based; the later
evolved UI uses these exact labels:

- The schedule/table domain column is **Name of Teaching**.
- The Secretary management page is **Update Names of Teaching** and its primary
  action is **Update Name of Teaching**. It supports create, rename,
  deactivate, and reactivate only for pools the Secretary is explicitly
  authorized to manage.
- Programme PC navigation is **Session Types**. Its management page is **Map
  Names of Teaching to Session Types**. PCs share name maintenance with the
  authorized Secretary, but only PCs may map a name to an exact TTF target.
- The mapping surface shows only **Pending** and **Mapped**. A pending name
  remains selectable and visible for eligible event/attendance workflows, with
  a clear compliance-pending explanation; it is not manually excluded. Phase D
  supplies count-only impact preview and uses the mapping revision plus explicit
  confirmation on nonzero impact; it has no client-held confirmation token or
  scope fingerprint. A changed revision requires refresh before confirmation.
- Pool-backed event creation selects a Name of Teaching and only `start_time`.
  The UI displays the server-computed one-hour end time, rejects starts later
  than 23:00 through the controlled validation state, and never changes stored
  timing when a mapping changes.
- **Master Teaching Name deletion modal.** *"Remove this Teaching Name? This is
  destructive. The Teaching Name identity is removed, while existing events,
  their immutable display text, and native and Non-NHG attendance evidence are
  preserved."* A used name additionally requires explicit force intent, a
  reason, and exact `DELETE` confirmation.

### S8 — NHG Resident Submission Portal

Closest to the original draft screenshot, modernised.

**Hero.** Title: *Submission Portal*. Subtitle: *Assigned posting: TTSH Geriatric Medicine*. Meta: MCR chip (mono, e.g. `MCR M00001A`) + native programme chip. Action: secondary *Submit Ad-hoc Teaching*.

**Filter row.**

- Filter icon + three pills: *All Teachings*, *Pending*, *Submitted*. Counts shown inline.
- Date range pill: two date glyphs with mono dates, e.g. *1 April 2026 — 6 April 2026*.

**Events card.**

- Column headers: *Teaching Name*, *Date*, *Time*, *Type*, *Status*, *Select*.
- Each row: name (weight 500), mono date, mono time, type tag, status badge.
- Status: *Pending* (amber outline), *Submitted* (success outline).
- Selected rows are tinted purple. Submitted rows are dimmed and unselectable.
- Event source can appear as a small muted label: *Assigned posting*, *Native department*, or *Programme teaching*. Duplicate rows are not shown if one event qualifies through multiple sources.

**Weekend warning banner.** When any selected event falls on a Saturday or Sunday without a configured weekend exception, an amber callout appears above the footer:

> *"Weekend selection — compliance warning. One or more selected teachings fall on a weekend with no configured exception. They may not count toward compliance."*

**Footer bar.**

- Left: *Submit Ad-hoc Teaching →* link (purple).
- Right: dark-green pill *Submit* button. Label changes to *Submit N* when N rows are selected. Disabled when 0 selected.

**On submit.**

- Submit button shows *Submitting…* spinner.
- Rows transition to *Submitted* with a purple-to-transparent row flash.
- Toast confirms count.
- Filter pill counts update.

**Empty.** *"No teachings here"* (filter-specific subtitle).

---

### S9 — NHG Resident Ad-hoc Teaching Modal

Modal (640px wide). Three-step flow.

**Stepper strip.** Numbered pills with connector bars. Steps: *Date · Session · Review*. Current step is bold purple; completed steps show a check.

**Step 1 — Date.**

- Inline calendar (PH-highlighted).
- Derived posting card below the calendar, info-coloured: *"On [date], you are posted to [posting]."*
- PH error: red highlight on the day + a red-tinted banner *"[PH name] falls on this date. Teachings cannot be recorded on public holidays."*. *Continue* disabled.

**Step 2 — Session.**

- Two-column row: Start time + fixed compliance type readout.
- The date-derived posting is a read-only server-provided value; there is no attended-department/programme selector.
- The teaching/session control is a read-only `Department/Programme Teaching [1h]` value. The client must not offer arbitrary Teaching Name, mapping, target, catalogue, or Column K selection.
- Optional details text area for display/audit notes only.
- Reminder card shows the derived posting for compliance and audit/display.
- Inline copy: *"Ad-hoc teachings count as Department/Programme Teaching [1h] under your assigned posting."*

**Step 3 — Review.**

- Recap card with mono date, start, derived posting, and fixed teaching/compliance type *Department/Programme Teaching [1h]*.
- Purple-tinted *Confirm submission* callout.
- *Back* and dark-green *Submit* button.

**Success state.** Replaces modal body:

- Large green check icon.
- Heading: *"Submitted — your ad-hoc teaching is recorded."*
- Subtext: *"Recorded as Department/Programme Teaching [1h] under your assigned posting."*
- Summary card.
- Actions: *Submit another* (ghost) · *Close* / *View past attendance →* (primary).

---

### S10 — NHG Resident Past Attendance

**Hero.** Title: *Past Attendance*. Subtitle: *Your submitted teachings*. Meta: record count.

**Filter bar.**

- Source dropdown — *All sources* / *Secretary Event* / *Ad-hoc*.
- Status dropdown — *All statuses* / *Submitted* / *Removed*.
- Date range pill.
- *Clear*.

**Table columns:**

| Column | Notes |
| --- | --- |
| Teaching name | Weight 500. **Removed** rows render with strikethrough and muted ink. |
| Date | Mono |
| Time | Mono |
| NHG posting | Sentence case |
| Source | *Secretary Event* (purple outline badge) or *Ad-hoc* (neutral badge, bolt glyph) |
| Status | *Submitted* (success outline) or *Removed* (neutral) |

**Status model — confirmed.** Past attendance uses **Submitted** and **Removed** only. There is no `Flagged` status and no `admin_note` field in this prototype.

**Empty.** *"No past attendance — no records match your filters."*

---

### S11 — Non-NHG Resident Entry / Login Choice

Full-bleed login page. No sidebar. No app bar.

**Card layout (480px).**

- Brand row at top: mark (square purple-on-navy "M"), product name *MATA*, subtitle *Medical Attendance Tracking*, DRAFT stamp on the right.
- Heading: *Sign in*.
- Helper text: *"NHG residents and secretaries sign in with MCR. Non-NHG residents (NUH / SingHealth) use the option below."*
- MCR field (mono input, placeholder *e.g. M00001A*).
- Primary *Continue* button.
- **"or" divider**.
- **Non-NHG CTA.** Large dashed-purple panel:
  - Title: *"I am a NUH / SingHealth resident posted to NHG"*.
  - Subtitle: *"First-time Non-NHG residents register here. Future logins use MCR only."*
  - Right-aligned arrow icon.
- Footer copy: *"By signing in you confirm you are an authorised user. Demo build — no production credentials accepted."*

---

### S12 — Non-NHG Resident Self-Registration

Full-bleed page (no shell). Card width **540px**.

**Header.** Brand row + DRAFT stamp + purple-outline badge *"Non-NHG Resident · First-time registration"*.

**Heading.** *Tell us about your posting*.

**Helper.** *"Non-NHG residents from NUH and SingHealth posted to NHG departments register once. After this, you sign in with MCR only."*

**Form fields:**

1. Full name (text).
2. MCR number (mono, helper *"Will be your login identifier going forward."*).
3. Home cluster — two large radio cards: **NUH** and **SingHealth**. Selected card has a purple border and tint + check icon.
4. Upcoming NHG Postings — repeatable row group:
   - Date range picker.
   - Programme dropdown showing code plus full programme name.
   - Institution dropdown limited to **TTSH**, **WH**, **KTPH**.
   - Resolved posting selection/display backed by `posting_codes`.
   - Icon buttons for add row and remove row.
   - Inline validation for overlapping ranges, missing posting resolution, or invalid programme/institution pairing.

**Info callout.** *"What happens next — Your account is created as a Non-NHG Resident. You'll log in with MCR only from now on. Your attendance is recorded for forwarding to your home cluster PC — not included in NHG compliance."*

**Footer.** *Cancel* · *Create Non-NHG account*.

**Success state** (replaces form):

- Green check disc.
- Heading: *"You're registered"*.
- Body: *"Welcome to MATA. From now on, sign in with just your MCR — no need to re-enter cluster or posting."*
- Recap card: Name, MCR (mono), Home cluster (badge), upcoming NHG postings table.
- Two callouts:
  - Info: *"Future login — MCR only. Next time, enter [MCR] on the sign-in screen and you'll go straight to your portal."*
  - Purple: *"Attendance routing. Your attendance is recorded for forwarding to [cluster] PC. NHG compliance and clawback do not apply to Non-NHG residents."*
- *Continue to Submission Portal* primary button.

---

### S13 — Non-NHG Resident Submission Portal

Same shell pattern as S8, with the external scope made explicit.

**Hero.** Title: *Submission Portal*. Subtitle: *Non-NHG Resident · [cluster] · Posting today: [derived NHG posting]*. Meta: MCR chip + purple-outline badge *"Non-NHG · [cluster]"*. Action: *Submit Ad-hoc Teaching*.

**Top callout (purple, always visible).** *"Non-NHG attendance routing. Your attendance is recorded for forwarding to your home cluster PC at [cluster]. It is not included in NHG compliance or clawback."*

**Supported posting branch.** Identical events table, filter row, weekend banner, and submit footer as S8 when the date-matched posting supports secretary-created events.

**Unsupported posting or schedule gap branch.** Events card is replaced with a card-pad **empty state**:

- Icon: bolt (purple).
- Heading: *"Secretary-scheduled teachings unavailable for this posting"*.
- Body: *"Use ad-hoc submission to record sessions you attended. Dates without a posting schedule row will show as unavailable."*
- Primary action: *Submit Ad-hoc Teaching*.

**Non-NHG ad-hoc copy.** The ad-hoc modal uses the same date → fixed record → review shape, with a read-only date-derived posting; the review and success copy must state: *"Recorded for forwarding to your home cluster. Not included in NHG compliance."*

---

### S14 — Non-NHG Resident Update Upcoming NHG Postings

**Hero.** Title: *Update Upcoming NHG Postings*. Subtitle: *Non-NHG Resident · [cluster] · MCR [MCR]*. Meta: purple-outline cluster badge.

**Top callout (info).** *"Self-service update. Non-NHG residents can update their upcoming NHG posting schedule themselves. Your home cluster ([cluster]) is fixed at registration and cannot be changed here."*

**Single schedule editor layout.**

- Top summary strip: Home cluster (badge), MCR (mono), derived current posting for today, resident type *Non-NHG*.
- Schedule table with editable rows: date range, programme, institution, resolved posting, row actions.
- Add row button appears below the table; remove row uses icon button with confirmation when the row has saved data.
- Inline validations: overlap, missing posting code, programme/institution mismatch, no posting code match, multiple posting code matches requiring explicit selection.
- When changed: purple-tinted *Confirm changes* callout *"Future event visibility will use this posting schedule. Previous attendance records are not rewritten."*. Otherwise: muted hint *"Edit a schedule row or add a new row to enable Save."*.
- Footer buttons: *Reset* · *Save schedule* (primary, disabled until changed and valid).

**Confirmation modal.**

- Heading: *"Update posting schedule?"*.
- Body shows the changed rows as a compact before/after table.
- Footer note: *"Future event visibility will use this posting schedule. Previous attendance records are not rewritten."*
- Footer: *Cancel* · *Update schedule*.

**Bottom callout (info).** *"Backend assumption — Non-NHG resident data is stored in external resident tables. Posting schedule rows resolve to `posting_codes` through backend validation."*

---

### S15 — Non-NHG Resident Past Attendance

Same shell as S10 with two differences.

**Top callout (purple).** *"Non-NHG attendance is recorded for forwarding to the resident's home cluster PC. It is not included in NHG compliance or clawback."*

**Additional column.** **Home cluster** between *NHG posting* and *Source*. Renders as a badge: *NUH* (info blue) or *SingHealth* (purple outline).

**Status model.** Same as S10 — *Submitted* and *Removed* only.

---

### S16 — Programme PC Non-NHG Attendance Export Preview

**Hero.** Title: *Non-NHG Attendance Export*. Subtitle: *Programme PC · For forwarding to NUH / SingHealth PCs*. Meta: record count, per-cluster counts. Actions: *Refresh*, primary *Export Non-NHG attendance*.

**Top callout (purple).** *"Export-ready preview. This screen previews what will be exported. The actual export endpoint and file format are pending integration contract with the NUH / SingHealth PC workflow. Email export is intentionally excluded."*

**Filter bar.**

- Home cluster dropdown (*All home clusters* / *NUH* / *SingHealth*).
- NHG posting dropdown.
- Source dropdown (*All sources* / *Secretary Event* / *Ad-hoc*).
- Date range pill (mono).
- *Clear*.

**Table columns:**

| Column | Notes |
| --- | --- |
| Resident | Synthetic placeholder name |
| MCR | Mono |
| Home cluster | Badge — *NUH* (info) or *SingHealth* (purple outline) |
| NHG posting | Sentence case |
| Teaching | Sentence case |
| Date | Mono |
| Source | Secretary Event / Ad-hoc badge |

**Empty.** *"No records match these filters — adjust filters to see external attendance for export."*

**Bottom callout (info — backend assumption).** *"Non-NHG attendance is excluded from NHG compliance numerator and denominator. The export shape (CSV vs JSON, field names, partitioning by cluster) is not finalised. Codex will receive an integration contract before wiring."*

---

### S17 — Programme PC NHG Resident Attendance Overview

**Route.** `/pc/resident-attendance`

**Hero.** Title: *NHG Resident Attendance*. Subtitle: *Review attendance submitted by NHG Residents in your assigned programmes*. The page is explicitly distinct from *Non-NHG Attendance*.

**Filter bar.**

- Programme dropdown only when the PC has more than one programme in scope.
- Resident name or MCR search.
- Current posting code field.
- *Clear filters*.

**Desktop table columns:**

| Column | Notes |
| --- | --- |
| Resident name | Primary resident identity |
| MCR | Mono; display only, never used as the route identifier |
| Programme | Raw programme code |
| R year | Display value or neutral fallback |
| Current posting | Backend label, then code fallback; `No current posting` when null |
| Total attendance submissions | Native `attendance_records` count only |
| Action | *View attendance* routes to the resident UUID page |

The overview uses bounded pagination. The frontend requests 25 rows and provides *Previous* / *Next* controls using the backend `total` and `offset` contract.

**Mobile.** At `640px` and below, replace the table with resident cards containing the same identity, current-posting, count, and route action. The page itself must not overflow horizontally.

**States.** Loading is distinct from empty. Errors show safe user-facing copy and a *Retry* action. Empty copy is exactly: *"No NHG residents found for the selected filters."*

**Authorization and privacy.** Client route protection is only UX. The backend enforces `residents.programme_code IN programme_scope` and returns no out-of-scope residents through rows, counts, search, filters, or detail navigation. Only compact attendance-review identity is displayed; no phone, email, employee code, registration type, or unrelated employment metadata appears.

---

### S18 — Programme PC NHG Resident Personal Attendance History

**Route.** `/pc/residents/{resident_id}/attendance`, where `{resident_id}` is the native resident UUID. MCR never appears in the route or query-string identity.

**Hero / resident summary.** Show resident name, MCR, programme, R year, and backend-resolved current posting. A *Back to NHG Resident Attendance* action returns to the overview and normal browser back/forward navigation remains intact.

**Filter bar.** Reporting period, event posting, inclusive date from/to, source, and status. Source choices are *Department Secretary*, *Programme PC*, and *Ad-hoc*. Status choices reflect persisted native values: *Submitted*, *Flagged*, and *Removed*.

**Desktop table columns:**

| Column | Notes |
| --- | --- |
| Teaching/session name | Canonical event display name; optional session details may appear as secondary text |
| Date | Mono |
| Start time | Mono; end time may be secondary display data |
| Posting | Event posting label/code |
| Source | Department Secretary / Programme PC / Ad-hoc |
| Status | Submitted / Flagged / Removed, display only |

Rows are ordered by event date descending, start time descending, then a stable identifier. Pagination requests 25 rows and uses *Previous* / *Next*. At `640px` and below, render dedicated attendance cards instead of allowing page-level horizontal overflow.

**States.** Loading is distinct from empty. Safe authorization/not-found errors do not reveal resident details and provide an appropriate return or retry action. Empty copy is exactly: *"No attendance submissions found for this resident."*

**Read-only boundary.** There is no drawer and no edit, delete, remove, force-delete, status-change, or notes control. Removed rows remain reviewable history. The page contains no compliance/dashboard tab or placeholder, targets, achieved-versus-target display, percentage, traffic light, shortage, surplus, reallocation, FormF1 denominator, or clawback UI.

---

## 4. Component Inventory

### 4.1 Layouts

- AppShell — dark sidebar + app bar + content area.
- SidebarCollapsedRail — icon-only sidebar at <1280px.
- PageHero — title + subtitle + meta + primary action.
- TwoColumnSplit — 8/4 or 1/1 column layout.
- ConfigShell — left sub-nav + right table + slide-over edit pattern.
- CenteredFocusFrame — full-bleed login / registration card.

### 4.2 Tables

- DataTable — sticky header, sortable, density toggle.
- GroupedDataTable — collapsible group headers (used in S3).
- SelectableTable — bulk select with contextual toolbar.
- ReadOnlyDataTable — for locked sections.
- TableEmpty / TableSkeleton / TableError.

### 4.3 Cards

- StatusSourceCard (S1 row 1).
- WorkspaceTile (S1 row 2).
- UploadCard (S2 / S6).
- ActivityFeedCard (S1 row 3 left).
- WarningListCard (S1 row 3 right).
- ConfigSectionCard wrapper.
- SuccessSummaryCard (post-upload, ad-hoc success).
- EmptyStateCard.

### 4.4 Forms

- TextField / MonoField / TextArea.
- DropdownSelect (single, multi, with search).
- ProgrammeDropdown (role-aware constraint).
- DatePicker / TimePicker / DurationPicker / DateRangePicker.
- ToggleYesNo / Checkbox / Radio.
- FileDropzone (with the six upload states).
- StepperHeader (S9).
- InlineValidation.
- FormFooterStickyBar (Cancel · Delete · Save).

### 4.5 Modals

- CreateEditModal (560px) — Add / Edit Teaching.
- AdhocModal (640px) — stepped Ad-hoc flow.
- ConfirmModal — delete / discard / update-posting.
- SuccessPanel — replaces modal body with success state.

### 4.6 Drawers (slide-over, 480–520px)

- DetailDrawer — read-only (warning detail, past attendance detail).
- EditDrawer — form with sticky footer (config edit, multi-posting edit).
- UploadResultDrawer — optional drawer variant of inline success.

### 4.7 Badges & Tags

- StatusBadge — *Submitted* / *Pending* / *Removed*.
- SeverityBadge — *Critical* / *Warning* / *Info* / *Resolved*.
- WarningTypeTag — mono, colour-coded per type.
- SourceBadge — *Secretary Event* / *Ad-hoc*.
- RoleBadge — *Master Admin* / *Programme PC* / *Secretary* / *NHG Resident* / *Non-NHG Resident*.
- ScopeChip — programme / posting / MCR.
- ClusterBadge — *NUH* / *SingHealth*.
- LockBadge — *Master Admin only*.
- DraftStamp — global header tag.

### 4.8 Filters

- FilterPillGroup (single-select).
- FilterDropdown (single / multi).
- DateRangePicker.
- SearchInput (page-local).
- ActiveFiltersChipRow.
- ClearFiltersButton.

### 4.9 Upload States

Idle → FileSelected → Uploading → Parsing → Success / Failure. Cancelable during Uploading. Result block renders inline or in a drawer.

### 4.10 Feedback States

- Toast (success / error / info).
- PageBanner (info / warning / error).
- InlineCallout (info / warning / purple / success).
- Tooltip.
- SkeletonRow / SkeletonCard.
- ErrorState (network / parser).
- EmptyState.

---

## 5. Clickable Prototype Plan

### 5.1 Routes

```
/login                              (S11 entry / S12 register — full-bleed)
/admin                              S1  Master Admin Home
/admin/upload                       S2
/admin/upload/warnings              S3
/admin/config                       S4  default: Reporting Periods
/admin/config/multi                 S5
/pc/home                            PC Home (overview)
/pc/upload                          S6
/pc/warnings                        Scoped warnings (PC view)
/pc/config                          S4 scoped
/pc/parsed                          Parsed data (scoped, read-only)
/pc/resident-attendance             S17
/pc/residents/{resident_id}/attendance S18
/pc/external-attendance             S16  Non-NHG Attendance (separate)
/secretary/schedule                 S7
/resident/portal                    S8
/resident/adhoc                     S9  (modal over /resident/portal)
/resident/past                      S10
/external/portal                    S13
/external/posting                   S14
/external/past                      S15
```

### 5.2 Role-Specific Sidebar Navigation

- **Master Admin.** Home · Upload Files · Warnings · Configuration · Upload Logs · Parsed Data · Secretary Events · Submissions · Settings.
- **Programme PC.** Home · Upload TTF · Teaching Events · Warnings · Configuration · NHG Resident Attendance · Non-NHG Attendance · Settings.
- **Secretary.** Teaching Schedule · Dashboard · Structured Plan · Settings.
- **NHG Resident.** Submission Portal · Past Attendance · Settings. *Submit Ad-hoc* lives as a button inside the portal, not as a nav item.
- **Non-NHG Resident.** Submission Portal · Past Attendance · Update Upcoming NHG Postings · Settings.

### 5.3 Key Interactions

1. **Role switcher** — clicking the user block opens the popover; selecting a role updates the sidebar and navigates to that role's default home.
2. **Upload simulation** — file drop → 2s determinate progress → 1.2s parsing shimmer → success state with synthetic counts.
3. **Warning row → drawer** — slide-in animation; inner blocks stagger-fade.
4. **Open related config** — closes the warning drawer, navigates to Multi-Posting Rules, opens the edit drawer pre-filled with synthetic context, shows the resolution callout.
5. **Save & resolve warning** — drawer footer button animates to a check; original warning is tagged *Resolved* on return.
6. **Add Teaching** — date picker live-validates against the public holidays list; picking a PH date triggers the error state and disables save.
7. **Resident select + submit** — checkboxes update the footer counter; weekend banner appears if any selected row is a weekend without an exception.
8. **Ad-hoc flow** — stepped 1 → 2 → 3 → success. Back is allowed until submit.
9. **Non-NHG entry → register → portal** — selecting *Non-NHG Resident* in the role switcher takes the user to the entry screen; registering completes to the Non-NHG portal with the new profile applied.
10. **Past attendance row click** — opens a read-only drawer using the same traceability layout as the warning drawer for visual consistency.
11. **PC View attendance** — navigates from the NHG Resident Attendance overview to the resident UUID history page. It never opens a drawer; browser back/forward navigation restores page history.

### 5.4 Modal / Drawer Rules

- One overlay at a time. Opening any new overlay closes the previous.
- Drawer width: **480–520px**, slides from right; backdrop dim 30%.
- Modal width: **560px** standard, **640px** wide (ad-hoc, confirmation with rich content). Backdrop dim 50%. Max-height 85vh, body scrolls.
- **Esc** closes drawers (with unsaved-changes confirm if dirty). Modals require an explicit Cancel for destructive flows.
- Animations: drawer slide 240ms, modal scale-in 220ms, both with easing `cubic-bezier(0.16, 1, 0.3, 1)`.

---

## 6. Demo Walkthrough Sequence

This sequence is for the live demo. All names, MCRs, and counts below are synthetic placeholders.

1. **Open as Master Admin** (`/admin`). Source-status row shows *RDB stale*, *TTF current*, *FormF1 current*, *PH missing*. Unresolved warnings panel shows three top items.
2. **Upload RDB** (`/admin/upload`). Drop a placeholder file → 2s progress → parsing shimmer → success: *"127 created · 14 updated · 5 warnings"*. Click **Review warnings**.
3. **Warning review** (`/admin/upload/warnings`). Filter to `unmatched_multi_posting`. Open a row. Show traceability: *Sheet Phase 3 · Row 42 · Cell J42*. Subject: *Resident A · MCR M00001A · May 2026*. Suggested action: *"Define a multi-posting rule for [demo posting] + [demo posting] in Configuration → Multi-Posting Rules → Main Posting."*
4. **Resolve via config** — click *Open related config →*. Lands on Multi-Posting Rules with the edit drawer open and the resolution callout visible. Fill `combined_label = "Demo Combined"`, click **Save & resolve warning**. Drawer closes. Success toast. Back on the warnings table the row is now *Resolved*.
5. **Switch role to Secretary**. Land on Teaching Schedule. Click **+ Add Teaching**. Pick a public holiday date — red error appears. Pick a valid date, fill remaining fields, save. The new row flashes briefly at the top of the table.
6. **Switch role to NHG Resident**. Submission Portal shows eligible secretary/programme events including the one just added. Select two events; selecting a weekend event triggers the amber compliance banner. Uncheck the weekend event. Click the green **Submit**. Rows transition to *Submitted* with a flash. Toast confirms.
7. **Switch role to Non-NHG Resident**. The full-bleed entry screen appears. Click *"I am a NUH / SingHealth resident posted to NHG"*. Fill the registration form with synthetic data, cluster *NUH*, and one upcoming NHG posting row. Success screen appears. Click *Continue to Submission Portal*.
8. **Non-NHG submission**. Portal shows eligible secretary events plus the purple "Non-NHG routing" banner. Submit an event. Open *Past Attendance* — same events appear with a *Home cluster* column and a routing banner. Show the *Submitted* / *Removed* status set with no `Flagged`.
9. **(Optional) Programme PC export.** Switch to Programme PC. Open *Non-NHG Export*. Filter by *NUH*. Show table of Non-NHG attendance ready for forwarding. Click *Export Non-NHG attendance* — toast indicates the actual endpoint is pending. Close on this state to highlight the integration boundary.

---

## 7. Backend / API Assumptions

The items below are **assumptions for visual demo purposes only**. They are not source-of-truth. Defer to `docs/api.md`, `docs/schema.md`, `docs/business-logic.md`, and `docs/parsing.md`.

| ID | Assumption |
| --- | --- |
| A-01 | Parser exposes `created`, `updated`, `warnings_count` per upload. Progress in this UI is simulated. |
| A-02 | Failed uploads produce a downloadable error report. The shape and endpoint are not finalised. |
| A-03 | Warnings have a stable ID and a `status` field (`unresolved` / `resolved` / `dismissed`). |
| A-04 | Public holidays are sourced from the PH/AY upload and are queryable by date for Add Teaching + Ad-hoc validation. |
| A-05 | A resident's current posting is derived from RDB by date. |
| A-06 | Past attendance status set is **Submitted** and **Removed** only — `Flagged` and `admin_note` are not used. |
| A-07 | Weekend exceptions are queryable by `(programme, date)`. |
| A-08 | Global Session Types and LOA Types are global. Programme PCs do not have write access. |
| A-09 | Multi-Posting Rules apply **on next RDB re-upload**; the UI states this in a banner. The re-upload is a manual Master Admin action. |
| A-10 | SMC event codes are free-text mono inputs in this UI; no external SMC registry validation. |
| A-11 | Notifications (bell icon) are decorative for the demo only. |
| A-12 | Non-NHG resident data uses `external_residents`, `external_resident_postings`, and `external_attendance_records`; user-facing labels should say Non-NHG Resident. |
| A-13 | Non-NHG attendance export endpoint and file format are **pending integration contract** with NUH / SingHealth PC workflow. Email export is intentionally excluded. |

---

## 8. Screenshot Reference List

Screenshots live under `docs/assets/demo-ui/` and are referenced from this document by relative path only. No base64 embeds. Capture each screen from the current Version B prototype at the **1440 × 900** presentation viewport. Sanitize prototype data to the synthetic placeholder set before capture.

### Full set

| # | Screen | Path |
| --- | --- | --- |
| 1 | Master Admin Home | `docs/assets/demo-ui/master-admin-home.png` |
| 2 | Upload Excel Files | `docs/assets/demo-ui/upload-files.png` |
| 3 | Upload Results / Warning Review | `docs/assets/demo-ui/warning-review.png` |
| 4 | All-in-One Admin Configuration | `docs/assets/demo-ui/admin-configuration.png` |
| 5 | Multi-Posting Rules CRUD | `docs/assets/demo-ui/multi-posting-rules.png` |
| 6 | Programme PC TTF Upload | `docs/assets/demo-ui/programme-pc-ttf-upload.png` |
| 7 | Secretary Teaching Schedule | `docs/assets/demo-ui/secretary-teaching-schedule.png` |
| 8 | NHG Resident Submission Portal | `docs/assets/demo-ui/native-resident-submission.png` |
| 9 | NHG Resident Ad-hoc Teaching Modal | `docs/assets/demo-ui/native-resident-adhoc.png` |
| 10 | NHG Resident Past Attendance | `docs/assets/demo-ui/native-resident-past-attendance.png` |
| 11 | Non-NHG Resident Entry / Login Choice | `docs/assets/demo-ui/external-resident-entry.png` |
| 12 | Non-NHG Resident Self-Registration | `docs/assets/demo-ui/external-resident-registration.png` |
| 13 | Non-NHG Resident Submission Portal | `docs/assets/demo-ui/external-resident-submission.png` |
| 14 | Non-NHG Resident Update Upcoming NHG Postings | `docs/assets/demo-ui/external-resident-update-posting.png` |
| 15 | Non-NHG Resident Past Attendance | `docs/assets/demo-ui/external-resident-past-attendance.png` |
| 16 | Programme PC Non-NHG Attendance Export Preview | `docs/assets/demo-ui/external-attendance-export.png` |

### Minimum high-value subset

If all 16 screens cannot be exported immediately, capture at least:

- `docs/assets/demo-ui/master-admin-home.png`
- `docs/assets/demo-ui/upload-files.png`
- `docs/assets/demo-ui/warning-review.png`
- `docs/assets/demo-ui/admin-configuration.png`
- `docs/assets/demo-ui/secretary-teaching-schedule.png`
- `docs/assets/demo-ui/native-resident-submission.png`
- `docs/assets/demo-ui/external-resident-registration.png`

### Capture notes

- The current Claude Design prototype does not auto-export screenshot files into `docs/assets/demo-ui/`. Either request screenshot capture explicitly after the prototype data has been sanitized to the synthetic placeholder set, or capture the screens manually from a browser at 1440×900.
- Use the synthetic placeholder set (Resident A / B / C, MCR `M00001A` / `M00002B` / `M12345X`, demo postings, etc.) before capture.
- Do not commit screenshots that show real resident names, real MCR values, or values copied from uploaded source workbooks.
