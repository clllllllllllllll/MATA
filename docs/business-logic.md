# Business Logic

This document covers the compliance engine, surplus chain, tag-based reallocation, and exception handling. All logic operates on **session counts, not hours**.

---

## BL-1: Session Count Capping

For each `(resident, posting, session_type)` triplet, the raw achieved count is capped at the target before being carried into the posting-level percentage.

```python
def compute_achieved_and_counted(
    raw_achieved: int,
    monthly_target: int,
    active_months: float  # may be fractional for half-month postings
) -> int:
    target_100 = monthly_target * active_months
    return min(raw_achieved, target_100)
```

**How to count active_months:**
- Join `resident_postings` rows where `posting_code` matches, within the reporting period, and `status IN ('active', 'loa_working')`
- Sum `active_months_weight` per row (default 1.0, set to 0.5 for half-month posting rules)
- Use `resident_postings.r_year` (NOT `residents.r_year`) when joining to `teaching_targets` — a resident who crosses a year boundary mid-period must be matched against the correct target for each phase
- Gate by `form_f1_records.is_active`: for each calendar month, check `form_f1_records` for this resident's MCR. If `is_active = false` for that month, exclude those resident_postings rows from the active_months count and exclude associated attendance from the numerator
- Active month counting is **whole-month only** — a posting is credited a full calendar month for any month it appears in, regardless of how many days within that month were spent there. No proration.
- Attendance month bucketing for teaching events/compliance views uses `academic_month_boundaries` (AY Dates), not raw calendar-month extraction from event dates.

**FormF1 active/inactive gate (final):**
The `form_f1_records` table is the final authoritative active/inactive source. A resident-month where `is_active = false` is excluded from both the compliance numerator and denominator.

**FormF1 and multi-posting cells:** FormF1 active/inactive is per calendar month per resident — not per posting code. If a resident has two postings in the same calendar month (e.g. multi-posting cell), FormF1 applies uniformly to both. A month cannot be Active for one posting and Inactive for another.

**active_months weight for half-month postings:**
For residents with a `half_month` rule applied (e.g. TTSHGas/NUHGas), each posting's `active_months_weight = 0.5`. Both `active_months` and `Target(mth)` are halved accordingly. Numerator sessions count fully.

**Posting group aggregation:**
When a resident's `posting_code` belongs to a `posting_groups` entry, active_months and target_100 are aggregated across ALL posting codes sharing the same `group_code` and `programme_code`:

```python
def compute_group_target_100(
    resident_id: str,
    group_code: str,
    programme_code: str,
    session_type_id: str,
    reporting_period_id: str
) -> float:
    """
    For grouped postings (e.g. TTSHRespi + TTSHRespi(MICU)):
    target_100 = sum of (monthly_target × active_months) across ALL group members.
    Each posting's own monthly_target from its TTF row applies per phase.
    active_months uses whole-month counting gated by FormF1.
    """
    group_members = get_posting_group_members(group_code, programme_code)
    total_target_100 = 0.0
    for posting_code in group_members:
        phases = get_active_phases(resident_id, posting_code, reporting_period_id)
        for phase in phases:
            target = get_teaching_target(posting_code, programme_code, phase.r_year, session_type_id)
            total_target_100 += target.monthly_target * phase.active_months_weight
    return total_target_100
```

**TTF Column E source:** `posting_groups` is primarily seeded from TTF Column E. A non-empty Column E value becomes the compliance `group_code`; the resolved Column D posting code becomes the group member. Column E does not replace the row’s monthly target. Each Column D row still contributes its own `monthly_target`; grouping only changes the posting-level aggregation identity.

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

1. **Same tag prefix = same group.** Tags use a prefix + number convention e.g. `A1`, `A2`, `A3`. All rows sharing the same prefix (all chars except the last character) at the same posting form one reallocation group.
2. **Flow direction: alphabetically earlier tag → alphabetically later tag only.** The R script sorts by tag label alphabetically ascending — `A1` before `A2`, `A2` before `A3`. By convention, PCs assign earlier tags to longer-duration session types and later tags to shorter-duration session types: `A1` = longest (e.g. 2h), `A2` = shorter (e.g. 1h), `A3` = shortest (e.g. 0.5h). The compliance engine enforces alphabetical order — it does NOT sort by duration.
3. **One-for-one in session counts.** 1 surplus session from `A1` = 1 session credit toward `A2` or `A3` shortfall. Duration is never a multiplier — 1 surplus [2h] session credits exactly 1 [1h] shortfall, not 2.
4. **Only tracked sessions participate.** Untracked session types (`is_tracked = false`) are excluded from reallocation.
5. **Reallocation happens after capping.** First compute `achieved_and_counted` per session type, then reallocate.

**Convention enforced by TTF upload validator:** The upload warns (not blocks) if a tag group's alphabetical order does not align with duration descending order — e.g. if `A1` maps to a `[1h]` session type and `A2` maps to a `[2h]` session type. This catches PC mislabelling early.

### Algorithm

```python
def reallocate_by_tag(rows: list[dict]) -> list[dict]:
    """
    rows: all teaching_target rows for ONE (resident, posting) with
          is_reallocatable=True.
    Each row has: tag, session_type_id, duration_hours, achieved, target_70,
                  achieved_and_counted
    Sort is by tag label ALPHABETICALLY (matches R script order() on Tag column).
    Convention: A1 = longest duration, A2 = shorter, A3 = shortest.
    """
    # Group by tag prefix (all chars except last)
    tag_groups = {}
    for row in rows:
        if not row['tag']:
            continue
        prefix = row['tag'][:-1]  # e.g. 'A1' → prefix 'A', 'A2' → prefix 'A'
        tag_groups.setdefault(prefix, []).append(row)

    for prefix, group in tag_groups.items():
        if len(group) < 2:
            continue
        # Sort alphabetically by tag label — A1 before A2 before A3
        group.sort(key=lambda r: r['tag'])
        bringover = [0] * len(group)

        for c in range(len(group)):
            if group[c]['achieved_and_counted'] >= group[c]['target_70']:
                # Has surplus — compute how much can be brought over
                bringover[c] = group[c]['achieved_and_counted'] - group[c]['target_70']
            elif c > 0 and sum(bringover) > 0:
                # Has shortfall — fill from earlier tags (alphabetically before)
                needed = group[c]['target_70'] - group[c]['achieved_and_counted']
                for d in range(c):
                    if needed <= 0:
                        break
                    transfer = min(bringover[d], needed)
                    if transfer > 0:
                        group[d]['achieved_and_counted'] -= transfer
                        group[c]['achieved_and_counted'] += transfer
                        bringover[d] -= transfer
                        needed -= transfer
    return rows
```

### Example

At YishCommHosp (GRM), tag prefix `A`:
- `A1` = Case-based Teaching [2h]: target_70 = 2, achieved = 4 → surplus = 2
- `A2` = Department/Programme Teaching [1h]: target_70 = 9, achieved = 7 → shortfall = 2

After reallocation (A1 → A2):
- `A1`: achieved adjusted to 2 (gave away 2 sessions, one-for-one)
- `A2`: achieved adjusted to 9 (received 2 session credits, shortfall filled)

3-tier example with A1 (2h), A2 (1h), A3 (0.5h):
- Surplus flows A1→A2, A1→A3, A2→A3 as needed
- Each transfer is 1-for-1 regardless of duration difference

---

## BL-4: Surplus Chain

Surplus tracks independently per `(resident, posting_code, session_type)`.

### Accumulation

`surplus_ledger` stores **pre-reallocation** surplus — the raw surplus per `(resident, posting, session_type)` before any tag-based transfers. Reallocation (BL-3) is always a read-time computation applied after fetching ledger values; it is never written back to `surplus_ledger`.

`update_surplus` is called **before** `reallocate_by_tag`, using the capped `achieved_and_counted` value (post-cap, pre-reallocation):

```python
def update_surplus(resident_id, posting_code, session_type_id, reporting_period_id):
    target = get_teaching_target(...)
    achieved = count_attendance_records(...)
    surplus = max(0, achieved - target.monthly_target * active_months)
    upsert_surplus_ledger(
        resident_id=resident_id,
        posting_code=posting_code,
        session_type_id=session_type_id,
        reporting_period_id=reporting_period_id,
        surplus=surplus,         # pre-reallocation
        is_hibernating=False
    )
```

### Hibernation and Resumption

Hibernation is triggered at **two points**, not lazily on compliance read:

1. **On RDB upload** — after `resident_postings` rows are written, the parser identifies all `(resident, posting_code)` pairs with no active phase in this period and sets `is_hibernating = true`.
2. **On period close** — all non-hibernating `surplus_ledger` rows for the period are set to `is_hibernating = true`.

```python
def hibernate_stale_surplus(session, reporting_period_id: str):
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

### Period boundary behaviour

Surplus resets to zero at each reporting period boundary and does NOT carry across H1/H2.

---

## BL-5: Exception Handling

### Public Holiday detection

```python
def is_public_holiday(teaching_date: date, ph_list: list[date]) -> bool:
    return teaching_date in ph_list
```

**Secretary event creation on PH dates is hard-blocked.** `POST /secretary/teaching-events` validates the event date against the `public_holidays` table and returns 422 if the date matches. The same block applies to `POST /resident/adhoc-teaching`.

**PH impact on compliance denominator:** Since no events can be created on PH dates, there are no PH attendance records to count or exclude. PH detection is for display/flagging only and has no denominator impact.

### Weekend detection

```python
def is_weekend(teaching_date: date) -> tuple[bool, str]:
    wd = teaching_date.weekday()  # Mon=0, Sun=6
    if wd == 5: return True, 'sat'
    if wd == 6: return True, 'sun'
    return False, ''
```

### Weekend exception logic

```python
def is_weekend_accepted(
    teaching_date: date,
    start_time: time,
    end_time: time,
    posting_code: str,
    programme_code: str,
    session_type_id: str,
    session_name: str
) -> tuple[bool, dict | None]:
    """
    Returns (accepted: bool, mutation_row: dict | None)
    mutation_row is set when a mutates_to_session_type_id is configured for the matching exception.
    """
    if not is_weekend(teaching_date)[0]:
        return True, None
    day_type = 'sat' if teaching_date.weekday() == 5 else 'sun'
    exceptions = query_weekend_exceptions(posting_code=posting_code, programme_code=programme_code)
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
        # Matched — check for mutation
        mutation = None
        if exc.mutates_to_session_type_id:
            mutation = {
                'session_type_id': exc.mutates_to_session_type_id,
                'duration_hours': exc.adjusted_duration_hours
            }
        return True, mutation
    return False, None
```

### Weekend submission warning (Option B)

When a resident submits attendance and `is_weekend_accepted()` returns `False` for one or more events, the submission still proceeds (sessions are stored) but the response includes a `compliance_warning` field:

```python
# In POST /resident/attendance response
{
    "submitted": 2,
    "errors": [],
    "compliance_warning": "1 session(s) submitted on a weekend will not count toward your PTT compliance as they do not meet the weekend exception rules for your programme."
}
```

The warning is per-submission, not per-session. The resident is informed upfront so they are not surprised when their compliance percentage does not reflect these submissions.

### ORTHO weekend session mutation (read-time, Option B)

ORTHO Saturday sessions of type `NHG Orthopaedic Surgery Residency Teaching [3h]` are mutated to `National Didactics & Department Teaching [1h]` at compliance read time via the `weekend_exceptions` table.

**How it works:**
1. Attendance is stored as submitted — raw data is never modified.
2. At compliance read time, `is_weekend_accepted()` returns the `mutation_row` for the matched ORTHO exception.
3. The compliance engine uses `mutation_row['session_type_id']` and `mutation_row['duration_hours']` instead of the original values for this attendance record.
4. The TTF matcher resolves compliance targets using the mutated session type.

**Why read-time (not event creation or submission time):** Consistent with how the original R script worked (batch post-processing before compliance calculation). Preserves raw data for auditability. If ORTHO changes their policy, update the `weekend_exceptions` row — no data migration needed.

### URO weekend exception seeding

URO accepts Saturday sessions under two independent conditions (OR logic). Since `weekend_exceptions` matches one condition per row, URO requires two rows:

**URO Row 1** — session name match:
`programme_code = 'URO'`, `day_type = 'sat'`, `session_name_pattern = 'Urology National Teaching (Sat)'`, all other fields NULL

**URO Row 2** — session type match:
`programme_code = 'URO'`, `day_type = 'sat'`, `session_type_id = <National Teaching [2h]>`, all other fields NULL

**Note:** SIG has been removed from the confirmed weekend exceptions list per PC update. SIG no longer has a weekend exception row.

### Duplicate and conflict detection

```python
def check_duplicate_or_conflict(session_a: dict, session_b: dict) -> str:
    if (session_a['start_time'] == session_b['start_time'] and
        session_a['end_time'] == session_b['end_time']):
        if session_a['session_type_id'] == session_b['session_type_id']:
            return 'duplicate'
        return 'conflict_same_time_diff_type'
    if session_b['start_time'] < session_a['end_time'] and session_a['start_time'] < session_b['end_time']:
        if session_a['session_type_id'] == session_b['session_type_id']:
            return 'conflict_overlap_same_type'
        return 'conflict_overlap_diff_type'
    return 'ok'
```

---

## BL-5A: Academic-Year Month Bucketing (AY Dates)

Attendance/event month assignment for compliance should use `academic_month_boundaries`, not raw calendar-month extraction from `event_date`.

Resolver chain:
1. `resident.programme_code`
2. `programmes.ay_date_category` (`im_subspec` or `non_im_subspec`)
3. `academic_month_boundaries` row where:
   - `ay_date_category` matches programme category
   - `event_date BETWEEN start_date AND end_date`
4. Assigned bucket = `academic_month_boundaries.month_label`

Rules:
- JR/SR does not branch this resolver.
- R1-R3 and R4+ use the same AY-date category for a programme.
- SR/SRs header wording in Excel is detection-only parser text and has no persistence meaning.
- `resident_postings.r_year` behaviour is unchanged and still used for TTF target lookup.
- `reporting_periods` windows remain Jan-Jun / Jul-Dec and are not replaced by AY categories.
- FormF1 is the final active/inactive denominator gate (calendar-month based).

---

## BL-6: Compliance Calculation Trigger

The compliance engine runs **JIT (just-in-time)** — recalculated on read, not stored as a materialised value.

**Identity inputs to every compliance calculation:**
- `programme_code` — from the resident's JWT claim
- `ay_date_category` — from `programmes.ay_date_category` for the resident programme
- `posting_code` — derived at request time from `resident_postings`
- `r_year` — from the `resident_postings` row for each phase (not `residents.r_year`)
- `reporting_period_id` — from `reporting_periods` WHERE `status = 'open'`
- `is_active` — from `form_f1_records` for the resident's MCR and each calendar month

### Resident dashboard — Python (single-resident JIT)

1. Query all active `resident_postings` for the resident within the reporting period (status `active` or `loa_working`)
2. For each phase, check `form_f1_records.is_active` for the corresponding calendar month. If false, exclude from denominator and numerator (FormF1 gate, separate from AY month bucketing)
3. For each active posting phase, check `posting_groups` for `(posting_code, programme_code)`. If a group is found, fetch all posting codes sharing the same `group_code`. Sum active_months and attendance across ALL group members (whole-month counting, no proration)
4. For each attendance event, resolve AY month bucket using `programmes.ay_date_category` and `academic_month_boundaries` where `event_date BETWEEN start_date AND end_date`
5. For each active posting phase, query `attendance_records` joined via `teaching_events.posting_code` where `event_date BETWEEN phase.start_date AND phase.end_date` and `attendance_records.status = 'submitted'`. Do NOT filter by `attendance_records.posting_code` — it is audit-only
6. For each attendance record, **first check `global_session_types`**: if `teaching_event.teaching_name` matches any active `global_session_types.name` → exclude from compliance entirely (skip catalogue lookup, excluded from both numerator and denominator). This check takes priority over the TTF catalogue.
7. For remaining records, resolve `session_type_id` at read time by joining `teaching_name_catalogue` WHERE `keyword = teaching_event.teaching_name AND posting_code = teaching_event.posting_code AND programme_code = resident.programme_code AND r_year = phase.r_year AND reporting_period_id = current_period`. Use `duration_hours` tiebreaker if multiple catalogue rows match. If no catalogue match — silently exclude from compliance.
8. Apply ORTHO weekend mutation if applicable (BL-5)
9. Group by `(group_code OR posting_code, session_type_id)` — use group_code when a posting group exists, posting_code otherwise
10. Apply capping (BL-1), accounting for `active_months_weight` and posting group aggregation
11. Update `surplus_ledger` with pre-reallocation values (BL-4)
12. Apply tag-based reallocation (BL-3) — read-time only, not written back
13. Compute posting-level compliance (BL-2)
14. Annotate dual-posting flag (BL-7)

### Admin reporting views — SQL (batch, programme-wide)

```sql
WITH form_f1_active AS (
    -- Active months from FormF1 — the denominator gate
    SELECT mcr, month_label
    FROM   form_f1_records
    WHERE  reporting_period_id = :period_id
    AND    is_active = true
),
active_phases AS (
    SELECT
        rp.resident_id,
        rp.posting_code,
        rp.r_year,
        rp.reporting_period_id,
        rp.start_date,
        rp.end_date,
        rp.active_months_weight
    FROM   resident_postings rp
    JOIN   residents res ON res.id = rp.resident_id
    JOIN   form_f1_active f1
           ON  f1.mcr = res.mcr
           -- FormF1 gate uses calendar month labels; AY month bucketing is resolved separately from `academic_month_boundaries` by event_date
           AND f1.month_label = TO_CHAR(rp.start_date, 'Mon-YY')
    WHERE  rp.reporting_period_id = :period_id
    AND    rp.status IN ('active', 'loa_working')
),
active_months_agg AS (
    SELECT
        resident_id,
        posting_code,
        r_year,
        SUM(active_months_weight) AS active_months
    FROM   active_phases
    GROUP  BY resident_id, posting_code, r_year
),
counted_attendance AS (
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
    JOIN   teaching_name_catalogue tnc
           ON  tnc.posting_code        = te.posting_code
           AND tnc.programme_code      = r_res.programme_code
           AND tnc.reporting_period_id = :period_id
           AND tnc.keyword             = te.teaching_name
           AND (
               (SELECT COUNT(*) FROM teaching_name_catalogue tnc2
                WHERE tnc2.posting_code = te.posting_code
                AND tnc2.programme_code = r_res.programme_code
                AND tnc2.reporting_period_id = :period_id
                AND tnc2.keyword = te.teaching_name) = 1
               OR tnc.duration_hours = te.duration_hours
           )
    JOIN   teaching_targets tt_resolve
           ON  tt_resolve.posting_code        = tnc.posting_code
           AND tt_resolve.programme_code      = tnc.programme_code
           AND tt_resolve.reporting_period_id = tnc.reporting_period_id
           AND tt_resolve.r_year              = ap.r_year
           AND tt_resolve.session_type_id     = tnc.session_type_id
    WHERE  ar.status = 'submitted'
    AND    tt_resolve.is_tracked = true
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
    EXISTS (
        SELECT 1 FROM active_phases ap2
        WHERE  ap2.resident_id = r.id
        AND    ap2.reporting_period_id = :period_id
        AND    ap2.posting_code != ama.posting_code
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

Tag-based reallocation (BL-3) is applied in Python after the SQL batch fetch.

**Why split:** A single resident dashboard involves a handful of rows — Python JIT is simpler and always correct. Admin views over hundreds of residents would be slow if each triggered a separate Python pass; pushing aggregation into SQL keeps query count constant.

---

## BL-7: Dual-Posting Compliance Reliability Flag

Residents with more than one distinct active `posting_code` in a reporting period may have compliance calculated using multi-posting rules. The `compliance_unreliable` flag fires only when two posting codes are detected in the same month and **no matching rule is found** in `multi_posting_rules`.

```python
def annotate_dual_posting_warnings(rows: list[dict]) -> list[dict]:
    for row in rows:
        if row.get('is_dual_posted') and row.get('no_rule_found'):
            row['compliance_unreliable'] = True
            row['compliance_unreliable_reason'] = (
                "Resident has multiple postings this month with no matching "
                "multi-posting rule. Compliance figures are provisional — "
                "add a rule in Admin > Multi-Posting Rules."
            )
        else:
            row['compliance_unreliable'] = False
            row['compliance_unreliable_reason'] = None
    return rows
```

If a `multi_posting_rules` row matches and the rule type is applied correctly (combine / half_month / main_posting), compliance is fully reliable and the flag does NOT fire.

---

## BL-8: Multi-Posting Compliance Rules

Three rule types govern how multiple posting codes in the same RDB month-cell are handled for compliance.

### Rule source and CRUD workflow

`Multiple postings per month.xlsx` is a seed/update source for database configuration. It is not a recurring operational upload and is not part of the normal RDB/TTF/FormF1 upload flow.

Long-term, PCs manage `multi_posting_rules` through Admin CRUD in three logical tabs:
- Main Posting
- To Combine Posting
- Half Month Posting

Seed refreshes must be idempotent. Re-running a seed or data migration must not create duplicate rules, and it must preserve manually added CRUD rules unless a workbook-derived row has the same unique key and intentionally replaces that row's configured output.

### combine type

Two posting codes appear in the same RDB cell and match a `combine` rule → a single `resident_postings` row is created with `combined_label` as posting_code (e.g. `IMHGrPsyc & TTSHPsychi`).

- Secretaries at both individual sites create teaching events under their own posting codes (IMHGrPsyc and TTSHPsychi separately)
- Compliance = total attended across both sites / total sessions created by both secretaries combined
- The combined posting label must have its own TTF row — compliance targets are from that combined row
- Posting order in the label (e.g. `IMHGrPsyc & TTSHPsychi` vs `TTSHPsychi & IMHGrPsyc`) indicates which site the resident starts at first — no compliance impact

### half_month type

Two posting codes appear in the same RDB cell and match a `half_month` rule (currently only TTSHGas / NUHGas) → two separate `resident_postings` rows are created, each with `active_months_weight = 0.5`.

- Both `active_months` and `Target(mth)` are halved per posting
- Numerator sessions count fully at each posting — no numerator weighting
- A resident can accumulate 1.5 months at TTSHGas and 0.5 months at NUHGas across a period

### main_posting type (FM)

Multiple posting codes appear in a single FM sheet cell. Explicit two-code `main_posting` rows, if present, are applied first. If no explicit rule matches, the parser uses the FM `main_posting` rows where `posting_code_2 IS NULL` as the recognised `RDB Posting #1` trigger list.

- Exact one recognised `RDB Posting #1` code in the cell → collapse to that row's `main_posting_code`.
- Zero recognised `RDB Posting #1` codes in the cell → collapse to the configured `exclusion_code`, usually `NHGPlyNHGPly`.
- Two or more recognised `RDB Posting #1` codes in the cell → do not infer. Persist postings independently and emit `unmatched_multi_posting` unless an explicit rule exists.
- A singular `NHGPlyNHGPly` cell is a normal standalone posting. It does not require a multi-posting rule and does not warn.
- This handles the FM polyclinic rotation where residents alternate between specialty departments and NHGPly without hardcoding `NHGPlyNHGPly` as a universal exclusion.

Non-FM unmatched combinations continue to persist independently and emit `unmatched_multi_posting`. The warning is the PC review workflow: add a rule through CRUD if the combination is valid, or fix the source RDB and re-upload if it is not.

---

## BL-FM: FM (Family Medicine) — Standard Engine with Specific Annotations

**FM uses the standard compliance engine (BL-1 through BL-7).** There is no separate FM compliance variant. FM-specific rules are annotations within the standard path:

**Rule 1 — Department Teaching [5h] posting override:**
When an FM resident submits attendance for a session of type `Department Teaching [5h]`, the posting for compliance attribution is always overridden to `NHGPlyNHGPly`, regardless of what posting site the event was created under.

```python
# Applied at attendance submission time and compliance read time
if programme_code == 'FM' and session_type_name == 'Department Teaching [5h]':
    compliance_posting_code = 'NHGPlyNHGPly'
```

**Rule 2 — FM main-posting parser semantics:**
FM multi-posting cells use the `main_posting` trigger-list semantics in BL-8. This is parse-time posting resolution only; it does not create a separate FM compliance engine.

**FM Saturday exception removed:**
FM is not in the confirmed `weekend_exceptions` seed list. Saturday FM sessions follow the general weekend warning/exclusion flow unless a future PC-confirmed exception is added through Admin CRUD.

**Reporting:** FM output uses the same compliance calculation as all other programmes. The R script's separate Excel template for FM was a layout difference only — not a calculation difference. No separate report template is needed in the new system.

---

## BL-9: Ad-hoc Teaching Submissions

Residents can submit ad-hoc teachings not pre-created by secretaries via `POST /resident/adhoc-teaching`.

**Flow:**
1. Resident provides: `date`, `start_time`, `teaching_name`
2. System derives `posting_code` from `resident_postings` for the given date (status IN ('active', 'loa_working'))
3. System resolves `session_type_id` from `teaching_name_catalogue` (same logic as secretary event creation)
4. System creates a `teaching_events` row with `is_adhoc = true`
5. System creates an `attendance_records` row in the same transaction
6. `end_time` = `start_time + session_type.duration_hours`

**Compliance treatment:** Ad-hoc sessions are treated identically to secretary-created sessions for compliance purposes. `is_tracked` and session type resolution follow the same rules.

**Validation:**
- Date must not be a public holiday (422 if PH)
- Teaching name must exist in `teaching_name_catalogue` for the resident's posting + programme + r_year (422 if not found)
- Duplicate detection (BL-5) applies


---

## BL-12: External / Cross-Cluster Resident Attendance

External residents are NUH or SingHealth residents who are temporarily posted to NHG/TTSH departments and need to record teaching attendance for forwarding to their home cluster.

**Identity and storage:**
- External residents live in `external_residents`, not `users` and not native `residents`.
- External attendance lives in `external_attendance_records`, not native `attendance_records`.
- External residents are not RDB-backed and do not use `resident_postings`.
- MCR is globally unique across native `residents` and `external_residents`; enforce cross-table checks in service code.

**Allowed home clusters:**
- `NUH`
- `SingHealth`

No other `home_cluster` values are valid.

**Posting state:**
External residents store their current NHG posting as `external_residents.current_nhg_posting_code`. They may update it themselves. This is separate from native RDB posting schedules and has no compliance denominator meaning.

**Secretary-created event visibility:**
Use `posting_codes.supports_secretary_events` as the scalable capability flag:
- `true` → external/native residents at that posting may see secretary-created event lists.
- `false` → ad-hoc submission remains available, but no secretary-created list is expected.

Do not hardcode TTSH in service logic. Current TTSH pilot postings can be enabled by setting this flag in seed/config data; future hospitals such as KTPH can be onboarded the same way.

**Compliance exclusion:**
External residents are excluded from all NHG compliance surfaces:
- no NHG compliance dashboard
- no numerator inclusion
- no denominator inclusion
- no surplus ledger
- no period snapshots
- no clawback

`GET /resident/dashboard` for an external resident returns `not_applicable`, not compliance metrics.

**Submission behaviour:**
- External residents can submit attendance for eligible secretary-created events at their current NHG posting.
- External residents can submit ad-hoc teaching.
- PH ad-hoc teaching is hard-blocked with `422`.
- Weekend non-exception submissions are stored and return `compliance_warning`.
- Session type is not stored on external attendance.

**Export status:**
External attendance must be exportable/queryable later by NHG PCs for forwarding to NUH/SingHealth PCs, but CSV/XLSX/dashboard export shape is deferred until requirements are confirmed.

---

## BL-10: Clawback Calculation

Generated at period close for residents who failed to meet the 70% PTT threshold.

**Trigger condition:** Any `(resident, posting)` where `percentage(posting) < 0.70` AND the posting has at least one active month.

**Exclusions (no clawback row generated):** SAF-Employed and SCDF-Employed residents.

**IM sub-specialty programme classification (for clawback rate lookup):**
Programmes are classified as IM sub-specialties based on their appearance 
in the Phase 3 sheet of the RDB. These programmes use `non_im_senior_rate` 
for clawback calculation.

The confirmed list must be verified against Programme_ABBREV.xlsx — 
the R script derives this dynamically at runtime from Phase 3 RDB 
sheet contents, not from a hardcoded list.

# TODO: Seed confirmed im_programmes list here once verified against 
# Programme_ABBREV.xlsx Phase 3 sheet contents
im_programmes = []  # placeholder — verify before seeding clawback.py

**Suppressed rows (row generated, amount = 0):** Extension status residents, R7 residents. Set `clawback_suppressed_reason` accordingly. Row is still shown in clawback tab.

**Formula:**
```python
def compute_clawback(
    programme: str,
    r_year: str,           # 'R1'…'R6', 'SS1'…'SS3', 'R7'
    active_months: float,
    norm_rates: dict,      # {'R1': x, 'R2': y, ...} seeded from template
    norm_rates_fm: dict,   # {'R1': a, 'R2': b, 'R3': c}
    im_programmes: list,   # programme codes classed as IM sub-specialty
    non_im_senior_rate: float,
    sr_rate: float,
) -> float:
    if r_year == 'R7':
        return 0.0   # R7 suppressed
    if programme == 'FM':
        rate = norm_rates_fm.get(r_year, 0)
    elif r_year.startswith('SS'):
        rate = sr_rate
    elif programme == 'IM':
        rate = sr_rate
    elif programme in im_programmes:
        rate = non_im_senior_rate
    elif r_year in norm_rates:
        rate = norm_rates[r_year]
    else:
        return 0.0  # ERR18 — r_year not found
    return round((rate / 12) * active_months, 2)
```

**Clawback tab:** Displayed as a 5th tab in the admin/PC dashboard alongside Monthly View, Posting View, Attendance Breakdown, Submitted Attendances. Read-only. Generated/refreshed at period close. Visible to admin/PC role only.

---

## BL-11: R Year Not Required Programmes

22 of the 28 programmes do not differentiate teaching targets by residency year. For these programmes, `r_year_required = false` on the `programmes` table.

### Sentinel value

Both `resident_postings.r_year` and `teaching_targets.r_year` are set to `'ALL'` for these programmes at parse/upload time.

### TTF matcher rule

```python
def r_year_matches(target_r_year: str, posting_r_year: str) -> bool:
    """
    target_r_year: from teaching_targets.r_year
    posting_r_year: from resident_postings.r_year
    """
    if target_r_year == 'ALL' or posting_r_year == 'ALL':
        return True
    return target_r_year == posting_r_year
```

### Subspecialty R year remapping

For programmes with `is_subspecialty = true` (SPORTSMED, PALLMED), the RDB parser remaps r_year values at parse time:

```python
if programme.is_subspecialty:
    r_year_map = {'R4': 'SS1', 'R5': 'SS2', 'R6': 'SS3'}
    r_year = r_year_map.get(r_year, r_year)
```

### RDB alias normalisation

For programmes with a non-NULL `rdb_alias`, the RDB parser normalises the programme name on upload:

```python
# Applied when reading RDB Specialization column
ALIAS_MAP = {
    'Infectious Disease': 'ID',
    'Renal Medicine Extended': 'RENAL',
    'Surgery-in-General': 'SIG',
    'Microbiology': 'MICROB',
}
programme_code = ALIAS_MAP.get(raw_specialization, raw_specialization)
```

### r_year_required = false (22 programmes)
AIM, CARDIO, EM, ENDO, ENT, EYE, GASTRO, GERI, GS, ID, IM, MEDONCO, ORTHO, PATH, REHAB, RENAL, RHEUM, SPORTSMED, SIG, URO, MICROB, PALLMED

### r_year_required = true (6 programmes)
ANAES, DERM, DR, FM, PSY, RESPI

---

## TBD-6: Refresher Training Compliance Treatment ✅ CLOSED

**Status: Closed.** Handled automatically by FormF1 active/inactive gate.

Refresher Training months that render a resident inactive appear as `Inactive` in FormF1 — no separate handling needed. The compliance denominator is governed by FormF1, not by RDB Refresher Training annotations.

The `add to Max Cand` / `don't add to Max Cand` flag is stored as a display annotation on `resident_postings.refresher_training_type`. No compliance impact. No code action needed beyond storing the value for display.

---

## TBD-7: Active/Inactive Source — FormF1 vs RDB ✅ CLOSED

**Status:** Resolved. FormF1 is the final authoritative active/inactive source for compliance.

**Final behaviour:**
- `form_f1_records.is_active` per calendar month is the denominator gate
- Active status values: `Active`, `Extension` → is_active = true
- Inactive → is_active = false → excluded from both numerator and denominator
- `form_f1_records.promotion_date` is captured from FormF1 for future R3→R4/senior promotion handling, but current compliance logic must not use it yet
- Employed residents: Active in FormF1 (they have real postings in RDB, no funding/clawback)
- LOA months that render a resident inactive appear as Inactive in FormF1 — no separate LOA compliance logic needed

**Why FormF1 over RDB for active/inactive:**
FormF1 is calculated on calendar month basis, aligning with compliance targets. RDB posting phases use academic months (e.g. `08 Jul 25 - 03 Aug 25`). Using RDB academic phases to derive active/inactive creates date boundary inconsistencies with calendar-month compliance targets.

**RDB-derived denominator logic:**
Not implemented. Do not derive active/inactive status from RDB LOA/refresher/employed annotations. These remain parser/audit/display fields unless a separate future requirement explicitly changes this.

**Refresher Training and Employed treatment under FormF1:**
Both are handled automatically via FormF1 values. No special-case code needed.

---

## TBD-MIGRATION: Historical Data Migration Strategy

**Status:** Awaiting stakeholder decision before first period close.

**Option A — Archive only (recommended default):**
Legacy Excel files remain accessible. New system holds data from cutover period onwards. Zero migration effort.

**Option B — Summary migration:**
One-time script reads legacy Programme Reporting View Excel files and inserts summary-level compliance records. Medium effort.

**Option C — Full migration:**
Parse original FormSG CSVs and legacy `.rds` snapshot files. Highest fidelity, highest effort.

**Developer instruction:** Do not build any migration tooling until the option is confirmed.

---

## Confirmed Decisions (previously TBD)

**Admin scope (TBD-3):** Admin/PC accounts are programme-scoped via `users.programme_scope TEXT[]`.

**Surplus period boundary (TBD-4):** Surplus resets to zero at each reporting period boundary. ✅

**Recurrence editing (TBD-5):** All three options required — "this event only", "this and all following", "all events in the series".

**Reallocation scope:** Tag-group-only confirmed. No cross-tag or cross-posting flow. ✅

**TBD-PH (Public Holiday):** Hard block on event creation on PH dates (secretary and resident). Denominator question moot since no PH events can be created. ✅

**TBD-2 (Dormant posting codes):** RDB posting code is canonical standard. Last `[]` bracket in TTF = RDB posting code. Dormant codes accepted with display_name = NULL. ✅

**Dual posting (TBD-5 original):** Combined postings follow their own TTF row. Resolved via multi_posting_rules table and R script analysis. ✅

**FM compliance variant:** FM uses standard engine. No NotImplementedError stub. Two FM-specific rule annotations apply. ✅

**TBD-6 (Refresher Training):** Closed. Handled automatically by FormF1 gate. No compliance action needed. ✅

**BL-11 (R year not required programmes):** Closed. `r_year = 'ALL'` sentinel, 22 programmes confirmed, TTF matcher rule documented. ✅

---

## BL-12: Performance, Caching, and Read-Time Calculation Safety

MATA compliance is calculated JIT (just-in-time) on read. Performance optimisations must not turn JIT compliance into stale stored business truth.

### Caching rules

- Compliance results may be cached only as derived read models, never as source-of-truth records.
- Cache keys must include all inputs that affect the result:
  - `resident_id` or admin identity/scope
  - `programme_code`
  - `posting_code` or `group_code` where relevant
  - `reporting_period_id`
  - report endpoint and query params
  - role/scope information
- Suggested TTL for live compliance/report results: 30–120 seconds.
- Period snapshots generated at close are frozen records; snapshot/export reads may have longer TTLs.

### Required invalidation triggers

Invalidate affected compliance/report caches after:

- RDB upload or re-upload
- TTF upload, re-upload, or teaching target edit
- FormF1 upload or re-upload
- public holiday upload or public holiday CRUD change
- `posting_groups`, `multi_posting_rules`, `weekend_exceptions`, `global_session_types`, `programmes`, or `loa_types` CRUD change
- secretary teaching event create/update/delete
- resident attendance submit/delete
- resident ad-hoc teaching create
- reporting period close/reopen

### What must never be cached as authoritative

- raw attendance rows
- raw uploaded files
- mutable upload parse warnings/errors
- authentication results
- authorization decisions without scope keying
- `surplus_ledger` after tag reallocation; the ledger stores pre-reallocation values only

### Query performance expectations

Compliance and reporting queries must use the indexes documented in `docs/schema.md`. Admin report SQL should be checked with `EXPLAIN ANALYZE` once sample data exists. If performance remains poor, prefer query/index tuning before introducing materialised compliance tables.

