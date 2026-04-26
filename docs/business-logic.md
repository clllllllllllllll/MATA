# Business Logic

This document covers the compliance engine, surplus chain, tag-based reallocation, and exception handling. All logic operates on **session counts, not hours**.

---

## BL-1: Session Count Capping

For each `(resident, posting, session_type)` triplet, the raw achieved count is capped at the target before being carried into the posting-level percentage.

```python
def compute_achieved_and_counted(
    raw_achieved: int,
    monthly_target: int,
    active_months: int  # number of month-phases at this posting
) -> int:
    target_100 = monthly_target * active_months
    return min(raw_achieved, target_100)
```

**How to count active_months:** Count `resident_postings` rows where `posting_code` matches within the reporting period and `status IN ('active', 'loa_working')`. Use `resident_postings.r_year` (not `residents.r_year`) when joining to `teaching_targets` — a resident who crosses a year boundary mid-period must be matched against the correct target for each phase.
Rows with status = 'loa' or status = 'employed' are excluded.
Note: LOA, Employed, and Refresher Training compliance treatment is pending PM confirmation — currently mirrors R system behaviour by only counting status = 'active'.

**"Achieved" vs "Achieved and counted":**
- `achieved` = raw count of attendance records (display only)
- `achieved_and_counted` = min(achieved, target_100) — this feeds compliance

---

## BL-2: Compliance Thresholds — 70% Traffic Light

### Three aggregation levels

**Level 1 — Monthly (per posting, per session type):**
```python
pct_monthly = min(achieved_this_month, monthly_target) / monthly_target
# Capped at 1.0. Display only — not used for compliance determination.
```

**Level 2 — Posting + Session Type:**
```python
pct_posting_session = achieved_and_counted / target_100
```

**Level 3 — Posting summary (compliance determination happens HERE):**
```python
TARGET_70_PCT = 0.70

def posting_compliance(
    achieved_and_counted: int,  # sum over ALL session types for this posting
    target_100: int             # sum of all (monthly_target * active_months)
) -> dict:
    import math
    target_70 = math.ceil(target_100 * TARGET_70_PCT)
    percentage = achieved_and_counted / target_100 if target_100 > 0 else 0
    shortage = max(0, target_70 - achieved_and_counted)
    met = achieved_and_counted >= target_70

    return {
        'target_100': target_100,
        'target_70': target_70,          # ceil() — matches R ceiling()
        'achieved_and_counted': achieved_and_counted,
        'shortage': shortage,
        'percentage': percentage,
        'met_70pct': met,
        'colour': 'green' if met else ('amber' if percentage >= 0.5 else 'red')
    }
```

**Critical:** The 70% threshold is at the POSTING level (aggregated across all session types), NOT at the monthly level or session-type level.

### Traffic light colours

| Colour | Condition |
|--------|-----------|
| Green | percentage >= 70% (met) |
| Amber | 50% <= percentage < 70% |
| Red | percentage < 50% |

---

## BL-3: Tag-Based Session Reallocation

When a teaching target row has `is_reallocatable = true` and a `tag` value, excess sessions from a longer-duration type can fill shortfall in a shorter-duration type within the same tag group.

### Rules

1. **Same tag = same group.** All rows at the same posting with the same tag value are in one reallocation group.
2. **Flow direction: longer → shorter only.** Sort group by `session_types.duration_hours` descending. Surplus from higher-duration types can transfer to lower-duration types, never upward.
3. **One-for-one in session counts.** 1 excess 2h session = 1 session credit toward a 1h shortfall. Duration is not a multiplier.
4. **Only tracked sessions participate.** Untracked session types are excluded from reallocation.
5. **Reallocation happens after capping.** First compute `achieved_and_counted` per session type, then reallocate.

### Algorithm

```python
def reallocate_by_tag(rows: list[dict]) -> list[dict]:
    """
    rows: all teaching_target rows for ONE (resident, posting) with 
          is_reallocatable=True, grouped by tag.
    Each row has: tag, session_type_id, duration_hours, achieved, target_70, 
                  achieved_and_counted
    """
    from itertools import groupby

    # Group by tag
    tag_groups = {}
    for row in rows:
        if not row['tag']:
            continue
        tag_groups.setdefault(row['tag'], []).append(row)

    for tag, group in tag_groups.items():
        if len(group) < 2:
            continue

        # Sort by duration descending — longest first
        group.sort(key=lambda r: r['duration_hours'], reverse=True)

        # Calculate surplus per row (achieved above target_70)
        surplus = []
        for row in group:
            s = max(0, row['achieved_and_counted'] - row['target_70'])
            surplus.append(s)

        # Transfer from longest to shortest
        for i in range(len(group)):
            if group[i]['achieved_and_counted'] >= group[i]['target_70']:
                continue  # this row doesn't need help
            needed = group[i]['target_70'] - group[i]['achieved_and_counted']
            # Look at rows with longer duration (earlier in sorted list)
            for j in range(i):
                if needed <= 0:
                    break
                transfer = min(surplus[j], needed)
                if transfer > 0:
                    group[j]['achieved_and_counted'] -= transfer
                    group[i]['achieved_and_counted'] += transfer
                    surplus[j] -= transfer
                    needed -= transfer

    return rows
```

### Example

At YishCommHosp (GRM), tag `A`:
- Case-based Teaching [2h]: target_70 = 2, achieved = 4, surplus = 2
- Department/Programme Teaching [1h]: target_70 = 9, achieved = 7, shortfall = 2

After reallocation:
- Case-based Teaching [2h]: achieved adjusted to 2 (gave away 2)
- Department/Programme Teaching [1h]: achieved adjusted to 9 (received 2, shortfall filled)

---

## BL-4: Surplus Chain

Surplus tracks independently per `(resident, posting_code, session_type)`.

### Accumulation

`surplus_ledger` stores **pre-reallocation** surplus — the raw surplus per `(resident, posting, session_type)` before any tag-based transfers. Reallocation (BL-3) is always a read-time computation applied after fetching ledger values; it is never written back to `surplus_ledger`. This keeps the ledger as a stable audit trail and means target changes mid-period do not require ledger corrections.

`update_surplus` is called **before** `reallocate_by_tag`, using the capped `achieved_and_counted` value (post-cap, pre-reallocation):

```python
def update_surplus(resident_id, posting_code, session_type_id, reporting_period_id):
    target = get_teaching_target(...)
    achieved = count_attendance_records(...)
    # active_months derived from resident_postings.r_year, not residents.r_year
    surplus = max(0, achieved - target.monthly_target * active_months)

    upsert_surplus_ledger(
        resident_id=resident_id,
        posting_code=posting_code,
        session_type_id=session_type_id,
        reporting_period_id=reporting_period_id,
        achieved_count=achieved,
        target_count=target.monthly_target * active_months,
        surplus=surplus,         # pre-reallocation
        is_hibernating=False
    )
    # reallocate_by_tag() is called after this, at the read layer only
```

### Hibernation and Resumption

Hibernation is triggered at **two points**, not lazily on compliance read:

1. **On RDB upload** — after `resident_postings` rows are written for the new period, the parser identifies all `(resident, posting_code)` pairs that no longer have an active phase in this period and sets `is_hibernating = true` for those ledger rows.
2. **On period close** (`PUT /admin/reporting-periods/{id}/close`) — all non-hibernating `surplus_ledger` rows for the period are set to `is_hibernating = true` as a housekeeping step (they will be superseded by a fresh period anyway, but this makes the boundary clean).

```python
# Called by the RDB upload service after writing resident_postings
def hibernate_stale_surplus(session, reporting_period_id: str):
    """
    Mark surplus as hibernating for any (resident, posting) combination
    that has no active or loa_working phase in this reporting period.
    """
    session.execute(text("""
        UPDATE surplus_ledger sl
        SET    is_hibernating = true
        WHERE  sl.reporting_period_id = :period_id
        AND    sl.is_hibernating = false
        AND    NOT EXISTS (
            SELECT 1 FROM resident_postings rp
            WHERE  rp.resident_id    = sl.resident_id
            AND    rp.posting_code   = sl.posting_code
            AND    rp.reporting_period_id = :period_id
            AND    rp.status IN ('active', 'loa_working')
        )
    """), {"period_id": reporting_period_id})
```

When resident returns to a posting they've been at before:
```python
# Resume — the existing surplus is already there, just un-hibernate
UPDATE surplus_ledger 
SET is_hibernating = false 
WHERE resident_id = :rid AND posting_code = :returning_posting
AND reporting_period_id = :period_id
```

### Cross-session-type isolation

Surplus for "Department/Programme Teaching [1h]" NEVER flows into "Case-based Teaching [2h]" through the surplus chain. Each session type's surplus is independent. Reallocation (BL-3) is the only mechanism for cross-type transfers, and it only works within tag groups.

### Period boundary behaviour

Surplus resets to zero at each reporting period boundary and does NOT carry across H1/H2. All surplus_ledger rows for the old period remain as historical records — new period starts fresh.

---

## BL-5: Exception Handling

### Public Holiday detection

```python
def is_public_holiday(teaching_date: date, ph_list: list[date]) -> bool:
    return teaching_date in ph_list
```

Attendance on public holidays is flagged but NOT automatically rejected. Exception rules determine whether it counts.

### Weekend detection

```python
def is_weekend(teaching_date: date) -> tuple[bool, str]:
    wd = teaching_date.weekday()  # Mon=0, Sun=6
    if wd == 5: return True, 'sat'
    if wd == 6: return True, 'sun'
    return False, ''
```

### Weekend exception logic

When a teaching falls on a weekend, check the `weekend_exceptions` table:

```python
def is_weekend_accepted(
    teaching_date: date,
    start_time: time,
    end_time: time,
    posting_code: str,
    programme_code: str,
    session_type_id: str,
    session_name: str
) -> bool:
    if not is_weekend(teaching_date)[0]:
        return True  # not a weekend, always accepted

    day_type = 'sat' if teaching_date.weekday() == 5 else 'sun'

    exceptions = query_weekend_exceptions(
        posting_code=posting_code,
        programme_code=programme_code
    )

    for exc in exceptions:
        if exc.day_type not in (day_type, 'both'):
            continue
        if exc.start_time_min and start_time < exc.start_time_min:
            continue
        if exc.end_time_max and end_time > exc.end_time_max:
            continue
        if exc.session_type_id and exc.session_type_id != session_type_id:
            continue
        if exc.session_name_pattern and exc.session_name_pattern not in session_name:
            continue
        return True  # matched an exception rule

    return False  # no exception, weekend teaching not accepted
```

### Duplicate and conflict detection

Pre-save check at the API layer when creating attendance records. Compare against existing records for the same resident on the same date.

```python
def check_duplicate_or_conflict(
    session_a: dict,  # {start_time, end_time, session_type_id}
    session_b: dict,
) -> str:
    """Returns: 'duplicate', 'conflict_same_type', 'conflict_diff_type', or 'ok'"""
    if (session_a['start_time'] == session_b['start_time'] and
        session_a['end_time'] == session_b['end_time']):
        if session_a['session_type_id'] == session_b['session_type_id']:
            return 'duplicate'
        return 'conflict_same_time_diff_type'

    # Overlap check
    if session_b['start_time'] < session_a['end_time'] and session_a['start_time'] < session_b['end_time']:
        if session_a['session_type_id'] == session_b['session_type_id']:
            return 'conflict_overlap_same_type'
        return 'conflict_overlap_diff_type'

    return 'ok'
```

**Note:** The UNIQUE constraint on `(resident_id, teaching_event_id)` catches exact duplicates at the DB layer. The conflict detection above catches overlapping-but-different events at the API layer.

---

## BL-6: Compliance Calculation Trigger

The compliance engine runs **JIT (just-in-time)** — recalculated on read, not stored as a materialised value.

**Identity inputs to every compliance calculation:**
- `programme_code` — from the resident's JWT claim (set at login from `residents.programme_code`, which comes from the RDB Specialization column). This selects which TTF the resident is measured against.
- `posting_code` — derived at request time from `resident_postings` (never from the JWT). This selects which rows within that TTF apply to the resident's current rotation.
- `r_year` — from the `resident_postings` row for each phase (not `residents.r_year`). This handles year-boundary crossings correctly.
- `reporting_period_id` — from `reporting_periods` WHERE `status = 'open'`.

A GRM resident and a DR resident at the same posting site will always resolve to different `teaching_targets` rows because their `programme_code` differs.

### Resident dashboard — Python (single-resident JIT)

When `GET /resident/dashboard` is called, the compliance engine runs in Python:

1. Query all active `resident_postings` for the resident within the reporting period (status `active` or `loa_working`). Use `resident_postings.r_year` (not `residents.r_year`) for target lookup.
2. For each active posting phase, query `attendance_records` joined via `teaching_events.posting_code` where `event_date BETWEEN phase.start_date AND phase.end_date` and `attendance_records.status = 'submitted'`. Do **not** filter by `attendance_records.posting_code` — it is audit-only and may be stale after RDB re-uploads.
3. Group by `(posting_code, session_type_id)`
4. Apply capping (BL-1)
5. Update `surplus_ledger` with pre-reallocation values (BL-4)
6. Apply tag-based reallocation (BL-3) — read-time only, not written back
7. Compute posting-level compliance (BL-2)
8. If the resident is dual-posted, annotate results with `compliance_unreliable = true` (BL-7)

For a single resident this involves a small, bounded number of queries and is fast enough to run synchronously on every request. Python logic is correct by construction — no SQL aggregation quirks.

### Admin reporting views — SQL (batch, programme-wide)

When any `GET /admin/reports/*` endpoint is called, compliance is computed **in SQL** across all residents in the programme at once. A single query joins `attendance_records`, `teaching_targets`, and `resident_postings` and returns all the aggregated values the report needs:

```sql
-- Posting-level compliance for all residents in a programme+period.
--
-- Key design rules reflected here:
--   1. teaching_targets joined on resident_postings.r_year (not residents.r_year)
--      so residents who cross a year boundary mid-period get the correct target.
--   2. Attendance is attributed via teaching_events.posting_code, NOT
--      attendance_records.posting_code (which is audit-only and can drift
--      after RDB re-uploads).
--   3. Attendance is only counted for events whose event_date falls within
--      a month-phase where the resident was active or loa_working at that
--      posting — preventing loa-status months from inflating the numerator.

WITH active_phases AS (
    -- One row per (resident, posting, month-phase) that counts toward compliance
    SELECT
        resident_id,
        posting_code,
        r_year,
        reporting_period_id,
        start_date,
        end_date
    FROM   resident_postings
    WHERE  reporting_period_id = :period_id
    AND    status IN ('active', 'loa_working')
),
active_months_agg AS (
    -- Count of active phases per (resident, posting) — the denominator base
    SELECT
        resident_id,
        posting_code,
        r_year,
        COUNT(*) AS active_months
    FROM   active_phases
    GROUP  BY resident_id, posting_code, r_year
),
counted_attendance AS (
    -- Attendance counts only for events that fall within an active phase.
    -- session_type_id is resolved via the resident's native programme TTF
    -- (teaching_targets), not from teaching_events — the same event may
    -- map to different session types for different programmes.
    SELECT
        ar.resident_id,
        te.posting_code,
        tt_resolve.session_type_id,
        COUNT(ar.id) AS achieved_raw
    FROM   attendance_records ar
    JOIN   teaching_events te ON te.id = ar.teaching_event_id
    JOIN   active_phases ap
           ON  ap.resident_id  = ar.resident_id
           AND ap.posting_code = te.posting_code
           AND te.event_date  BETWEEN ap.start_date AND ap.end_date
    JOIN   residents r_res ON r_res.id = ar.resident_id
    JOIN   teaching_targets tt_resolve
           ON  tt_resolve.posting_code        = te.posting_code
           AND tt_resolve.programme_code      = r_res.programme_code
           AND tt_resolve.reporting_period_id = :period_id
           AND tt_resolve.r_year              = ap.r_year
           AND tt_resolve.details_of_training ILIKE '%' || te.teaching_name || '%'
           -- Duration tiebreaker: if teaching_name matches multiple session types,
           -- use event duration to discriminate. session_types.duration_hours must
           -- match the event's duration_hours when multiple rows would otherwise match.
           AND (
               -- Only apply duration filter when ambiguity exists
               (SELECT COUNT(*) FROM teaching_targets tt2
                WHERE tt2.posting_code        = te.posting_code
                AND   tt2.programme_code      = r_res.programme_code
                AND   tt2.reporting_period_id = :period_id
                AND   tt2.r_year              = ap.r_year
                AND   tt2.details_of_training ILIKE '%' || te.teaching_name || '%'
               ) = 1
               OR EXISTS (
                   SELECT 1 FROM session_types st2
                   WHERE st2.id             = tt_resolve.session_type_id
                   AND   st2.duration_hours = te.duration_hours
               )
           )
    WHERE  ar.status = 'submitted'
    GROUP  BY ar.resident_id, te.posting_code, tt_resolve.session_type_id
)
SELECT
    r.id                                                          AS resident_id,
    r.name,
    ama.posting_code,
    tt.session_type_id,
    COALESCE(ca.achieved_raw, 0)                                  AS achieved_raw,
    LEAST(COALESCE(ca.achieved_raw, 0),
          tt.monthly_target * ama.active_months)                  AS achieved_and_counted,
    tt.monthly_target * ama.active_months                         AS target_100,
    CEIL((tt.monthly_target * ama.active_months) * 0.70)          AS target_70,
    -- Flag dual-posted residents so callers can mark compliance as unreliable
    -- until TBD dual-posting rule is confirmed (see BL-7)
    EXISTS (
        SELECT 1 FROM active_phases ap2
        WHERE  ap2.resident_id        = r.id
        AND    ap2.reporting_period_id = :period_id
        AND    ap2.posting_code       != ama.posting_code
        GROUP  BY ap2.resident_id
        HAVING COUNT(DISTINCT ap2.posting_code) > 1
    )                                                             AS is_dual_posted
FROM   residents r
JOIN   active_months_agg ama ON ama.resident_id = r.id
JOIN   teaching_targets tt
           ON  tt.posting_code        = ama.posting_code
           AND tt.programme_code      = r.programme_code
           AND tt.reporting_period_id = :period_id
           AND tt.r_year              = ama.r_year
LEFT JOIN counted_attendance ca
           ON  ca.resident_id    = r.id
           AND ca.posting_code   = ama.posting_code
           AND ca.session_type_id = tt.session_type_id
WHERE  r.programme_code = :programme_code
```

Tag-based reallocation (BL-3) is applied in Python **after** the SQL batch fetch — the SQL returns one row per `(resident, posting, session_type)` and the Python reallocation loop runs over that result set before the response is serialised.

**Why split:** A single resident's dashboard involves a handful of rows — Python JIT is simpler and always correct. Admin views over hundreds of residents would be slow if each resident triggered a separate Python JIT pass; pushing the aggregation into SQL keeps the query count constant regardless of cohort size.

**Why JIT at all:** Attendance can be deleted and resubmitted, teaching targets can be edited mid-period. Pre-computed/materialised compliance would require invalidation logic. JIT (per-request recalculation) is simpler and always correct.

---

## BL-7: Dual-Posting Compliance Reliability Flag

Residents with more than one distinct active `posting_code` in a reporting period (dual-posted) cannot have their compliance calculated correctly until the main-posting rule is confirmed (see AGENTS.md TBD item 5). Until that decision is made, the system must not silently produce wrong numbers.

**Two questions pending PM confirmation before this can be implemented correctly:**
1. **Main posting determination** — For residents on a dual posting (e.g. IMHGrPsyc & TTSHPsychi), what is the rule that determines which site is the "main posting"? This formula has not been sighted and is not currently documented.
2. **Compliance scope** — Once the main posting is determined, does the resident follow only the main posting's compliance targets, or do both sites' targets apply simultaneously? Can the TTF targets for each site differ?

**Rule:** Any compliance result row where `is_dual_posted = true` (as returned by the SQL batch query) must be decorated with a warning before being returned to the caller.

```python
def annotate_dual_posting_warnings(rows: list[dict]) -> list[dict]:
    for row in rows:
        if row.get('is_dual_posted'):
            row['compliance_unreliable'] = True
            row['compliance_unreliable_reason'] = (
                "Resident is dual-posted this period. Compliance figures are "
                "provisional until the main-posting rule is confirmed (TBD)."
            )
        else:
            row['compliance_unreliable'] = False
            row['compliance_unreliable_reason'] = None
    return rows
```

This applies to **all** admin report endpoints and the resident dashboard. The compliance numbers are still returned (so PCs can see the provisional picture), but the flag allows the UI to render a warning badge and prevents automated pass/fail decisions from being made on unreliable rows.

---

## TBD-1: Details of Training — Keyword-Based Filtering

**Status:** PM keyword list incoming — deduplication and "and others" ambiguity resolved by PMs.

**Confirmed behaviour:**

1. Each `teaching_targets` row has a `details_of_training` field containing comma-separated keywords (e.g. "Journal Club, Grand Round, M&M").
2. Each keyword maps to exactly ONE session type within a posting per programme (no ambiguity). Validated at TTF upload time.
3. **Secretary dropdown:** `GET /secretary/teaching-name-options` queries the union of all `details_of_training` keywords across ALL programmes at the secretary's `posting_code`. The event is programme-agnostic — the secretary picks a name, not a session type.
4. **Session type resolution happens at attendance submission time, per resident.** When a resident submits attendance for an event, the backend looks up `teaching_targets` WHERE `posting_code = event.posting_code` AND `programme_code = resident.programme_code` AND `details_of_training` contains `teaching_name`. The matched row's `session_type_id` is used for compliance. The same event resolves to different session types for residents of different native programmes.

   **Duration tiebreaker:** If `teaching_name` alone matches multiple session types at the same posting (edge case — e.g. "Multidisciplinary Meeting" appearing in both `Department/Programme Teaching [1h]` and `Case-based Teaching [0.75h]`), `duration_hours` from the event is used as a secondary discriminator to resolve to the correct session type. The deduplication rule therefore is: within a posting, each `(keyword, duration)` combination must map to exactly one session type.
5. **Resident visibility filter:** A resident sees events at both their **current posting** AND their **native programme posting** (if different). Within each posting, events are filtered to only those whose `teaching_name` keyword appears in the resident's native programme TTF for that posting. A GRM resident and an Anaes resident at the same posting may see different events.
6. **Compliance matching:** Attendance → `teaching_name` + `posting_code` + resident's `programme_code` + `r_year` → `teaching_targets` row → `session_type_id` and compliance target.

**Placeholder implementation:** Until TTF `details_of_training` is populated, the secretary dropdown shows all session types at the posting, and residents see all events at their current and native postings without keyword filtering.

## TBD-6: Refresher Training Compliance Treatment

**Status:** Awaiting PM confirmation.

Refresher Training annotations are captured and stored in `resident_postings` (`refresher_training_type`, `refresher_training_start`, `refresher_training_end`). No business logic currently acts on them. The R system had no explicit handling for Refresher Training — cells likely passed through as garbled posting codes or were partially stripped, meaning the annotation was silently lost. The new system captures the data correctly at parse time, but no calculation acts on it until confirmed.

**Questions pending PM confirmation:**
- **Active months denominator** — When a resident has a Refresher Training annotation for part of a posting month, should that period count toward their `active_months` denominator for compliance, or should it be excluded similarly to LOA?
- **Add to Max Cand** — Does `add to Max Cand` mean the resident counts toward the maximum candidate cap for that posting during the Refresher Training period? And does `don't add to Max Cand` exclude them from that cap entirely? This is a distinct question from the compliance denominator — it affects posting-level headcount caps, not just the individual resident's calculation.

## TBD-7: LOA and Employed Compliance Treatment

**Status:** Awaiting PM confirmation.

**Important context:** The R system's behaviour of excluding LOA and Employed months was a **silent byproduct of how cells were parsed**, not an explicit design decision. LOA and XXX-Employed cells were stripped entirely during RDB parsing, treated as blank — no posting row was created, no data was retained. This silently reduced the compliance denominator and excluded employed residents from compliance calculation entirely. The new system captures this data properly but currently mirrors the R output by filtering to `status = 'active'` only until a deliberate decision is made.

**Questions pending PM confirmation:**
- **LOA months** — When a resident is on LOA for one or more months in a reporting period, should those months be excluded from their compliance denominator (i.e. not penalised for months on leave), or should LOA months count as normal active months where compliance is still expected?
- **Employed residents** — Residents on SAF-Employed, SCDF-Employed, KTPH-Employed and other employed postings are currently excluded from compliance calculations entirely. Is this the intended behaviour going forward, or should employed residents appear in compliance reporting with their employed months explicitly flagged?

## Confirmed Decisions (previously TBD)

**Admin scope (TBD-3):** Admin/PC accounts are programme-scoped. 
Each account is linked to one or more programmes via users.programme_scope 
and only sees data for those programmes.

**Surplus period boundary (TBD-4):** Confirmed in BL-4 — surplus resets 
to zero at each reporting period boundary. ✅ Already correct in BL-4.

**Recurrence editing (TBD-5):** All three options are required — 
"this event only", "this and all following", "all events in the series".

**Reallocation scope:** Tag-group-only confirmed. Surplus cannot flow 
across tag groups or across postings. ✅ Already correct in BL-3.

---

## BL-FM: FM (Family Medicine) Compliance Variant

**Status:** Special arrangements confirmed with FM PCs. Full implementation details to be re-confirmed before development begins. Do NOT apply standard BL-1 through BL-7 logic to FM without reading this section first.

**What is confirmed:**
- FM uses `programmes.compliance_variant = 'fm'`
- FM has structural differences from the standard compliance calculation path
- The R script explicitly used a separate Excel template (`Template-Programme Reporting View-Single FM.xlsx`) for FM output, indicating the reporting structure differs

**What needs re-confirmation before implementation:**
- The exact compliance threshold FM uses (whether it differs from 70%)
- Whether FM session types follow the same capping rule (BL-1) or a different one
- Whether reallocation (BL-3) applies to FM or is disabled
- The exact sheet structure differences that required a separate template in the R script
- Whether FM R year handling follows the standard path

**Developer instruction:** When building the compliance engine, branch on `programmes.compliance_variant` early:
```python
if programme.compliance_variant == 'fm':
    return compute_fm_compliance(...)   # FM-specific path — DO NOT implement until spec confirmed
else:
    return compute_standard_compliance(...)
```

Do not implement the FM path with guessed logic. Leave it as a `NotImplementedError` stub until the spec is confirmed and this section is updated.

---

## TBD-PH: Public Holiday Impact on Compliance Denominator

**Status:** Awaiting PM confirmation.

PH detection (`is_public_holiday`) and weekend exception logic are fully implemented in BL-5. What is unconfirmed is the denominator impact:

**Option A — Display only:** Teachings on public holidays are flagged in the UI for visibility but do NOT affect the compliance denominator or the active_months count. This is the simpler path and mirrors typical practice.

**Option B — Excluded from denominator:** Teaching events that fall on a public holiday are excluded from both the numerator (not counted toward compliance) and the denominator (the monthly target is pro-rated to exclude PH days). This requires knowing the number of working days in each posting phase.

**Current placeholder:** Treating PH teachings as display-flag only (Option A). Do not change this until PM confirms Option B is required.

**Impact if Option B is confirmed:** The `active_months` denominator calculation in BL-1 would need to be replaced with an `active_working_days` calculation that subtracts public holidays and weekends (where not exception-approved) from each posting phase duration. This is a significant change to the compliance engine.

---

## TBD-MIGRATION: Historical Data Migration Strategy

**Status:** Awaiting stakeholder decision before first period close.

The legacy system produced Excel outputs (Programme Reporting View, Resident Dashboards, consolidated attendance files) across multiple reporting periods. Three options exist for handling this history:

**Option A — Archive only (recommended default):**
Legacy Excel files remain accessible on the shared drive. The new system holds data only from the cutover period onwards. PCs query history in the old files. Zero migration effort. Recommended unless there is a specific regulatory or operational requirement to query history through the new system.

**Option B — Summary migration:**
Write a one-time script that reads the legacy Programme Reporting View Excel files and inserts summary-level compliance records into a `legacy_compliance_records` table (separate from the live schema). Enough for historical reporting queries without recreating every individual attendance record. Medium effort — requires building an Excel parser for the legacy output format.

**Option C — Full migration:**
Parse the original FormSG CSVs and legacy `.rds` snapshot files and insert them as `attendance_records` and `resident_postings` into the new DB. Highest fidelity — full historical data queryable through the new system. Highest effort — requires porting the R script parsing logic to Python as a one-time migration job. Only warranted if there is a regulatory requirement to have all historical data in the same system.

**Developer instruction:** Do not build any migration tooling until the option is confirmed. The decision does not affect the core system schema or business logic — it is purely additive.