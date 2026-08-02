# Business Logic

This document covers the compliance engine, surplus chain, tag-based reallocation, and exception handling. All logic operates on **session counts, not hours**.

## Phase 6 and evolved TTF status

BL-1 through BL-12 are the future non-clawback compliance specification. They
do not establish that `compliance.py`, `surplus.py`, or a full Phase 6 engine is
implemented today. Clawback and final close remain separately deferred. Current
upload, event, and attendance behavior remains the legacy A-K catalogue path
through additive B1; Phase A changes documentation only.

The future evolved TTF uses `teaching_name` pools scoped by reporting period and
programme. A name's exact `(posting_code, r_year)` mapping is pending until it
selects an exact target in that programme's TTF. Pending names remain eligible
for Secretary/PC event creation, resident visibility, attendance, and audit,
but contribute neither numerator nor denominator until mapped. A mapping is
read on demand, so a successful map is effective on the next JIT calculation
without rewriting raw event or attendance records. There is no manually
excluded mapping state.

Global session types stay Admin-managed and are considered before ordinary
Teaching Name mapping. Resident ad-hoc teaching remains fixed to
`Department/Programme Teaching [1h]`; Non-NHG attendance is excluded from NHG
compliance. The final A-J TTF removes Column K. The current A-K parser,
`teaching_name_catalogue`, and `details_of_training` stay in place during B1;
only final E2/B2 may remove them. A populated legacy Column K in a future-format
upload must return `422`, with no dual-format fallback, backfill, or historical
migration.

---

## BL-1: Session Count Capping

For each `(resident, physical posting, session_type, r_year context)`, calculate raw eligible attendance and the correctly weighted target separately. Tag reallocation (BL-3) operates on those raw session counts. Each R-year context is capped at its own `target_100` only after reallocation, then the separately capped values and targets are summed into the final posting-level result.

```python
def cap_r_year_context(
    adjusted_raw_achieved: int,
    monthly_target: int,
    active_months: float  # may be fractional for half-month postings
) -> float:
    target_100 = monthly_target * active_months
    return min(adjusted_raw_achieved, target_100)
```

**How to count active_months:**
- Join `resident_postings` rows where `posting_code` matches, within the reporting period, and `status IN ('active', 'loa_working')`
- Sum `active_months_weight` per row (default 1.0, set to 0.5 for half-month posting rules)
- Use `resident_postings.r_year` (NOT `residents.r_year`) when joining to `teaching_targets` — a resident who crosses a year boundary mid-period must be matched against the correct target for each phase
- Resolve the AY bucket for each phase/event, then use the FormF1 record whose `month_label` equals that AY bucket label. The same bucket-level status gates numerator and denominator.
- Active month counting is **whole AY-bucket only** — do not split or prorate a bucket across calendar months and do not use the event's raw calendar month when it differs from the AY label.
- Attendance month bucketing for teaching events/compliance views uses `academic_month_boundaries` (AY Dates), not raw calendar-month extraction from event dates.

**FormF1 active/inactive gate (final):**
The `form_f1_records` table is the final authoritative active/inactive source. Records remain stored by calendar month, but compliance selects the record by the resolved AY bucket's `month_label`. If that bucket-level record has `is_active = false`, the entire bucket is excluded from both numerator and denominator.

Example: if the `Jul-26` AY bucket spans 8 July through 3 August, every contribution in that bucket uses July FormF1. An event on 3 August uses July status; an event on 4 August uses the `Aug-26` bucket and August status.

Unknown non-blank FormF1 monthly statuses retain their raw value and use the existing active fallback so the upload remains non-blocking. Each creates a persisted `unknown_formf1_status` warning with the unknown value and Excel cell reference. Blank, `NULL`, and whitespace-only monthly cells are recognised inactive values and do not create this warning.

**FormF1 and multi-posting cells:** FormF1 active/inactive is per month label per resident — not per posting code. If a resident has two postings in the same AY bucket, the bucket label's FormF1 status applies uniformly to both. A bucket cannot be Active for one posting and Inactive for another.

**active_months weight for half-month postings:**
For residents with a `half_month` rule applied (e.g. TTSHGas/NUHGas), each posting's `active_months_weight = 0.5`. Keep the uploaded TTF `monthly_target` unchanged and apply the `0.5` factor exactly once through the weight: `target_100 = monthly_target * 0.5`. Numerator sessions count fully. Do not also halve `monthly_target`, which would quarter the denominator.

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
    active_months uses whole AY-bucket counting gated by the FormF1 month
    selected by the AY bucket label.
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
- `achieved` = raw eligible session count before tag reallocation
- `adjusted_achieved` = read-time raw session count after tag transfers
- `achieved_and_counted` = `min(adjusted_achieved, target_100)` for each R-year context after all transfers; separately capped contexts are summed for posting compliance

**Mid-period R-year transitions:** Resolve each attendance against the `resident_postings` phase covering its event date and use that phase's `r_year`. Calculate separately for each `(physical posting, session_type, r_year)`, using only the active-month weight belonging to that context. Cap each context separately, then sum capped achievements and targets into the final posting result. Never merge raw attendance across R years before capping, apply a posting-wide month total to each R-year row, or duplicate active months.

**Zero targets:** A row with `monthly_target = 0` remains event-visible and attendance-capable, but is excluded before compliance aggregation. It contributes `0` to both numerator and denominator; its stored attendance is audit-only and cannot create a percentage, shortage, surplus, reallocation supply/demand, or clawback contribution.

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
    achieved_and_counted: float,  # sum of separately capped R-year contexts
    target_100: float             # sum of their correctly weighted targets
) -> dict:
    import math
    if target_100 <= 0:
        return {"applicable": False, "target_70": 0, "percentage": None,
                "shortage": 0, "met": None}
    target_70 = math.ceil(target_100 * TARGET_70_PCT)
    percentage = achieved_and_counted / target_100
    met = percentage >= TARGET_70_PCT
    shortage = 0 if met else math.ceil(
        (target_100 * TARGET_70_PCT) - achieved_and_counted
    )

    return {
        'target_100': target_100,
        'target_70': target_70,          # displayed whole-session target
        'achieved_and_counted': achieved_and_counted,
        'shortage': shortage,
        'percentage': percentage,
        'met_70pct': met,
        'colour': ('green' if percentage >= 0.70
                   else 'amber' if percentage >= 0.50
                   else 'red')
    }
```

**Critical:** The 70% threshold is at the POSTING level (aggregated across all session types), NOT at the monthly level or session-type level. The canonical predicate is the unrounded `percentage >= 0.70` for every target. `target_70 = ceil(target_100 * 0.70)` is retained as a displayed whole-session target. For fractional `target_100`, the percentage predicate takes precedence: a capped 100% result can never fail because the displayed ceiling is above the fractional cap.

When a resident is below 70%, the displayed whole-session shortage is `ceil((target_100 * 0.70) - achieved_and_counted)`. At or above 70%, shortage is zero. Display rounding must never determine `met_70pct` or colour. Clawback must eventually use the same unrounded percentage predicate, but clawback rules remain deferred.

### Traffic light colours

| Colour | Condition |
|--------|-----------|
| Green | percentage >= 70% (met) |
| Amber | 50% <= percentage < 70% |
| Red | percentage < 50% |

---

## BL-3: Tag-Based Session Reallocation

When a teaching target row has `is_reallocatable = true` and a `tag` value, raw achieved session counts may be projected from an earlier alphabetical tag to a later tag within the same tag prefix and physical posting before final capping.

### Rules

1. **Same tag prefix and R-year context = same group.** Tags use a prefix + number convention e.g. `A1`, `A2`, `A3`. Within one physical posting and one R-year context, rows sharing the same prefix (all chars except the last character) form one reallocation group. Never merge R-year contexts to create transfer supply or demand.
2. **Flow direction: alphabetically earlier tag → alphabetically later tag only.** Sort `A1`, `A2`, `A3` alphabetically. By convention, PCs assign earlier tags to longer-duration types, but the engine never sorts or calculates by duration.
3. **One-for-one in session counts.** 1 surplus session from `A1` = 1 session credit toward `A2` or `A3` shortfall. Duration is never a multiplier — 1 surplus [2h] session credits exactly 1 [1h] shortfall, not 2.
4. **Only tracked sessions participate.** Untracked session types (`is_tracked = false`) are excluded from reallocation.
5. **Physical-posting isolation.** Posting-group membership never permits transfers across member posting codes. Reallocate within each physical posting before group aggregation.
6. **Reallocation happens before final capping.** Use raw eligible achieved counts. For each session type, calculate `tag_target_70 = ceil(target_100 * 0.70)` for transfer supply/demand only.
7. **Bounded supply and demand.** Donor supply is `max(raw_achieved - tag_target_70, 0)`. Recipient demand is `max(tag_target_70 - adjusted_raw_achieved, 0)`. Decrement donor supply after every transfer so no surplus is spent twice.
8. **Final cap.** After all transfers, cap every session type at its own `target_100`. Those final capped values feed posting-level compliance. The posting-level `target_70` is calculated separately from the summed posting target.
9. **Read-time only.** Never write reallocated counts or a separate reallocated balance to `surplus_ledger`.

**Convention enforced by TTF upload validator:** The upload warns (not blocks) if a tag group's alphabetical order does not align with duration descending order — e.g. if `A1` maps to a `[1h]` session type and `A2` maps to a `[2h]` session type. This catches PC mislabelling early.

### Algorithm

```python
def reallocate_by_tag(rows: list[dict]) -> list[dict]:
    """
    rows: all teaching_target rows for ONE (resident, posting, R-year context) with
          is_reallocatable=True.
    Each row has: physical_posting_code, tag, raw_achieved, target_100.
    This function is called for one resident, one physical posting, and one R-year context.
    It returns read-time adjusted raw counts plus final capped counts.
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
        for row in group:
            row['tag_target_70'] = math.ceil(row['target_100'] * 0.70)
            row['adjusted_raw_achieved'] = row['raw_achieved']
            row['donor_supply'] = max(
                row['raw_achieved'] - row['tag_target_70'], 0
            )

        for recipient_index, recipient in enumerate(group):
            needed = max(
                recipient['tag_target_70'] - recipient['adjusted_raw_achieved'], 0
            )
            for donor in group[:recipient_index]:
                if needed <= 0:
                    break
                transfer = min(donor['donor_supply'], needed)
                donor['adjusted_raw_achieved'] -= transfer
                recipient['adjusted_raw_achieved'] += transfer
                donor['donor_supply'] -= transfer
                needed -= transfer

        for row in group:
            row['achieved_and_counted'] = min(
                row['adjusted_raw_achieved'], row['target_100']
            )
    return rows
```

### Example

At YishCommHosp (GRM), tag prefix `A`:
- `A1` = Case-based Teaching [2h]: `target_100 = 3`, `tag_target_70 = 3`, raw achieved = 5 → donor supply = 2
- `A2` = Department/Programme Teaching [1h]: `target_100 = 12`, `tag_target_70 = 9`, raw achieved = 7 → demand = 2

After reallocation (A1 → A2):
- `A1`: adjusted raw = 3 and final capped = 3 (gave away 2 sessions, one-for-one)
- `A2`: achieved adjusted to 9 (received 2 session credits, shortfall filled)

3-tier example with A1 (2h), A2 (1h), A3 (0.5h):
- Surplus flows A1→A2, A1→A3, A2→A3 as needed
- Each transfer is 1-for-1 regardless of duration difference

---

## BL-4: Surplus Chain

Surplus tracks independently per `(resident, posting_code, session_type)`.

### Accumulation

Persistent surplus is new MATA derived audit state; the legacy scripts had only temporary in-memory tag-transfer values and no persistent ledger. For each `(resident, physical posting, session_type, reporting_period)`, the invariant is:

`surplus = max(cumulative raw eligible attendance - cumulative target_100, 0)`

`surplus_ledger` stores this **pre-tag-reallocation** value. Raw attendance and targets are recomputed across all applicable phases in the reporting period. The ledger is never an independent attendance credit, is never added back to raw attendance, and is not consumed or mutated by BL-3.

`update_surplus` replaces the derived value idempotently; it never increments the prior stored value:

```python
def update_surplus(resident_id, posting_code, session_type_id, reporting_period_id):
    target = get_teaching_target(...)
    if not target.is_tracked or target.monthly_target == 0:
        return  # no surplus-ledger, reallocation, or clawback contribution
    cumulative_raw_eligible = count_raw_eligible_attendance_for_period(...)
    cumulative_target_100 = compute_cumulative_target_100_for_period(...)
    surplus = max(0, cumulative_raw_eligible - cumulative_target_100)
    upsert_surplus_ledger(
        resident_id=resident_id,
        posting_code=posting_code,
        session_type_id=session_type_id,
        reporting_period_id=reporting_period_id,
        surplus=surplus,  # replace existing value; do not add to it
        is_hibernating=not has_active_phase_at_posting(...)
    )
```

Repeated reads with unchanged attendance and targets produce the same row value. When a resident returns to the same posting in the same reporting period, unhibernate and recompute cumulative attendance and targets across the earlier and returning phases. If the expanded target consumes a prior excess, the ledger decreases or becomes zero.

Example: the first phase has target 2 and attendance 4, so surplus is 2. On return, cumulative target becomes 4 while cumulative attendance remains 4; counted attendance is 4 and recomputed surplus is 0. Never calculate `4 + stored surplus 2`.

### Hibernation and Resumption

Hibernation records whether an active phase remains; it does not convert the ledger into carry-in attendance:

1. **On RDB upload** — after `resident_postings` rows are written, the parser identifies all `(resident, posting_code)` pairs with no active phase in this period and sets `is_hibernating = true`.
2. **On return within the same reporting period** — set `is_hibernating = false` and recompute the derived value from period attendance and targets.

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

Surplus resets to zero at each reporting period boundary and does NOT carry across H1/H2. Closed-period rows may remain as historical evidence where supported, but no old-period value is read into a new period. Final-close transaction and rerun semantics remain deferred with clawback.

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

Only ORTHO sessions whose exact original resolved type is `NHG Orthopaedic Surgery Residency Teaching [3h]` use the mutation. Mutation and weekend acceptance are separate predicates; do not represent them as one broad rule that mutates every ORTHO session.

**How it works:**
1. Preserve the original event and attendance rows, including original times and type.
2. Require Saturday; Sunday remains excluded.
3. For the exact original 3h type, subtract two hours from the original end time.
4. Project the compliance type to `National Didactics & Department Teaching [1h]`.
5. Apply the Saturday 08:30–10:30 acceptance window against the adjusted start/end interval.
6. Resolve the target using the projected 1h type.
7. Do not mutate other ORTHO session types. They require their own separately configured acceptance rule to count.

**Why read-time (not event creation or submission time):** This preserves raw data for auditability. The adjusted time and projected type exist only in the compliance read model.

### URO weekend exception seeding

URO accepts Saturday sessions under two independent conditions (OR logic). Since `weekend_exceptions` matches one condition per row, URO requires two rows:

**URO Row 1** — session name match:
`programme_code = 'URO'`, `day_type = 'sat'`, `session_name_pattern = 'Urology National Teaching (Sat)'`, all other fields NULL

**URO Row 2** — session type match:
`programme_code = 'URO'`, `day_type = 'sat'`, `session_type_id = <National Teaching [2h]>`, all other fields NULL

**Note:** SIG has been removed from the confirmed weekend exceptions list per PC update. SIG no longer has a weekend exception row.

### Distinct-event overlap detection

```python
def intervals_overlap(earlier_event: dict, later_event: dict) -> bool:
    return (
        later_event['start_time'] < earlier_event['end_time']
        and earlier_event['start_time'] < later_event['end_time']
    )
```

**Submission-time outcome for distinct events:** For the same resident, compare a later submission against already accepted distinct events. If the later interval overlaps an earlier accepted interval, reject the later submission and preserve the earlier attendance unchanged. Do not delete, replace, or retroactively flag the earlier record. This rule applies before compliance calculation and is separate from the database uniqueness rule for submitting the same `teaching_event_id` twice. Do not infer any additional overlap behavior beyond this confirmed rule.

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
- FormF1 records remain calendar-month keyed, but the resolved AY `month_label` selects which FormF1 row gates both numerator and denominator for the entire bucket. Do not split/prorate a bucket or use the event's raw calendar month.

---

## BL-6: Compliance Calculation Trigger

The compliance engine runs **JIT (just-in-time)** — recalculated on read, not stored as a materialised value.

**Identity inputs to every compliance calculation:**
- `programme_code` — from the backend-hydrated resident record; never from a
  browser-supplied token claim
- `ay_date_category` — from `programmes.ay_date_category` for the resident programme
- `posting_code` — derived at request time from `resident_postings`
- `r_year` — from the `resident_postings` row for each phase (not `residents.r_year`)
- `reporting_period_id` — from the active/effectively active `reporting_periods` row
- `is_active` — from `form_f1_records` for the resident's MCR and the resolved AY bucket label

### Resident dashboard — Python (single-resident JIT)

1. Query active/`loa_working` `resident_postings` phases in the reporting period. Retain each physical posting, date range, `r_year`, AY `month_label`, and `active_months_weight`.
2. Resolve each event/phase to exactly one AY bucket through `academic_month_boundaries`. Use that bucket label to select FormF1; the same status gates numerator and denominator for the whole bucket.
3. Query only native submitted `attendance_records`. Do not use the audit copy `attendance_records.posting_code` and never join `external_attendance_records` into native compliance.
4. Reject later distinct-event overlaps at submission time under BL-5; the accepted row set reaching compliance therefore preserves the earlier event only.
5. Resolve the resident's assigned physical posting and phase R-year for the event date. Apply configured `main_posting`, `combine`, `half_month`, and FM projection semantics without conflating their identities.
6. For an approved native-programme event outside the assigned posting, preserve the raw event but project exactly one compliance session to `Department/Programme Teaching [1h]` under the assigned posting. Use the assigned posting's target; never use the creator posting or `programmes.native_teaching_posting_code` as a compliance result.
7. **First check `global_session_types`.** Matching rows remain auditable but are excluded from all compliance, surplus, and reallocation math before catalogue lookup.
8. For normal assigned-posting events, resolve the canonical `teaching_name` by `(reporting_period, resident programme, assigned/compliance posting, phase r_year, canonical name)`. The same name may exist at other postings and map differently. Do not use fuzzy matching. Missing mappings or a catalogue row without its required target remain stored/auditable but excluded and surfaced as configuration data quality; never invent a target. Case/spacing option cleanup is upload/event-option data quality, not unresolved compliance logic.
9. Apply weekend acceptance and the exact-type ORTHO adjusted-time projection from BL-5 without mutating raw rows.
10. Exclude untracked and zero-target rows. Count remaining eligible sessions one-for-one by `(resident, physical posting, session_type, r_year context)`; duration never multiplies count.
11. Calculate each context's correctly weighted `target_100`. A half-month leaves `monthly_target` unchanged and applies `active_months_weight = 0.5` once.
12. Recompute and replace the persistent pre-tag ledger from cumulative raw eligible attendance minus cumulative target (BL-4). Do not read the stored value as attendance input.
13. Apply tag reallocation to raw achieved counts within each physical posting, R-year context, and prefix, then cap each session type/R-year context at its own `target_100` (BL-3). Cap R-year contexts separately and sum them; never merge raw counts before transfer or capping.
14. After physical-posting reallocation/capping, aggregate configured `posting_groups`. Group membership never permits cross-posting tag transfers.
15. Compute posting-level percentage, display `target_70`, shortage, `met_70pct`, and colour under BL-2, then attach reliability and display annotations.

### Reporting-period active/inactive semantics

`reporting_periods.status` accepts `active` and `inactive` only. `open` and `closed` are legacy names and are rejected by the API after migration.

`activate_on` and `deactivate_on` are nullable scheduled transition dates. They are resolved at read time and do not mutate the stored `status` value. When both scheduled dates are due, the later scheduled date wins; if both scheduled dates are due on the same date, deactivation wins.

Multiple reporting periods may be administratively/effectively active at once. Administrative status is separate from date applicability: a current-date workflow resolves exactly one effectively active period containing today; an event or submission resolves exactly one effectively active period containing that event/submission date. A future active period must not become a current default, and a reopened past period remains explicitly selectable for its historical date range. If two effectively active periods contain the same relevant date, the workflow fails closed with a configuration conflict rather than choosing by row order.

Resident scheduled-event discovery enumerates all effectively active periods, then uses the date-aware resolver for every candidate event. The event must fall inside exactly one active period, and its posting/catalogue checks use that period ID; a period containing today is not required. New attendance and ad-hoc submissions continue to resolve exactly one effectively active period from the event/selected teaching date. If no effectively active period exists, the event list is empty with `reason = "active_reporting_period_unavailable"` and ad-hoc submission is disabled; attendance and ad-hoc submission attempts return `422` when their date has no matching period. Existing attendance records remain stored and auditable.

New reporting periods default `deactivate_on` to `end_date + 14 calendar days` unless an explicit value is supplied. A past period can be reopened only by a new effective inactive-to-active transition that supplies a future `deactivate_on`; this includes a newly scheduled future `activate_on`, for which `deactivate_on` must be strictly later than `activate_on`. Its historical start/end dates are not extended by reopening. Ordinary edits to an already effectively active reopened period preserve its existing future `deactivate_on` and do not require it to be resubmitted.

### PC-created teaching event visibility (planned 4B)

Secretary-created scheduled events remain posting-owned and programme-neutral: `teaching_events.created_for_programme_code IS NULL`. They are visible to eligible residents only after the normal posting/date/catalogue checks pass.

Programme PC-created scheduled events are programme-owned: planned `teaching_events.created_for_programme_code` is set to the PC's programme. Resident event discovery must show these events only to residents whose `resident.programme_code` equals `created_for_programme_code`, and only if the event also passes posting/date/catalogue visibility checks.

Null or empty admin `programme_scope` grants no programme access. Master admin all-programme access must be explicit; never infer master access from null programme scope.

PC-created events are scheduled teaching events, not ad-hoc submissions. Public holiday hard-block and ordinary delete-with-attendance guardrails apply.

### Master Admin scheduled-event force-delete override

Ordinary deletion contracts remain unchanged: Secretary and Programme PC deletion are blocked with `409` when submitted native or Non-NHG attendance exists. Programme PCs and Secretaries never receive force-delete authority.

The dedicated **Secretary/PC Events** override is restricted to an authenticated admin whose persisted/verified `admin_level` is explicitly `master`; null or empty `programme_scope` is not Master Admin authority. Eligible rows are scheduled Secretary events (`is_adhoc = false` and no programme owner) or Programme PC events (`created_for_programme_code IS NOT NULL`). `created_for_programme_code` is the authoritative source classifier; ad-hoc resident events are rejected.

Force deletion affects only the selected event occurrence. In one transaction the service locks the event, captures the event snapshot and linked counts, verifies that the counts still match the impact confirmed by the Master Admin, explicitly removes native and Non-NHG attendance, removes the event, and writes action `admin.teaching_event.force_delete`. A changed confirmation impact returns `409` before deletion. Any transactional failure rolls back the attendance deletions, event deletion, and audit row together. Series siblings and the `event_series` row remain unchanged.

After commit, affected event, attendance, resident-view, Master Admin list, and report caches are invalidated. A post-commit cache invalidation failure is logged without falsely returning failure for the committed deletion. Removed attendance no longer contributes to future live/JIT reads; this is an explicit destructive operational correction, not a new compliance rule.

### Native NHG Resident event visibility (Phase 5B)

NHG Resident scheduled-event discovery uses three allowed sources:

1. **Assigned/current posting secretary events**
   - Derive assigned posting from `resident_postings` covering each event date with `status IN ('active', 'loa_working')`.
   - Secretary-created events at that `posting_code` are eligible.

2. **Native programme TTSH department secretary events**
   - Derive from an explicit native-programme-to-TTSH-posting mapping.
   - Examples: `GRM -> TTSHGerMed`, `REHAB -> TTSH Rehab posting code`, `DR -> TTSH Diagnostic Radiology posting code`.
   - Do not infer this mapping by string manipulation. Preferred implementation is explicit config/mapping, for example `programmes.native_teaching_posting_code` or a `programme_teaching_posting_map` table.

3. **Native programme PC-created events**
   - `teaching_events.created_for_programme_code = resident.programme_code`.
   - PC-created events are NHG/programme-owned, not TTSH site-owned.

Deduplicate final event rows by `teaching_events.id`.

Do not show PC-created events for non-native programmes. Do not show secretary-created events from arbitrary TTSH departments unless they are either the resident's assigned/current posting or the resident's native programme department. Existing TTF/catalogue/date/reporting-period filters still apply. No RDB upload or no `resident_postings` still means no assigned-posting visibility for NHG Residents.

**Scenarios:**
- Native GRM Resident John posted to TTSH Geriatric Medicine sees TTSH GRM Department Secretary events because he is posted there and GRM PC events because GRM is his native programme. The TTSH GRM secretary source is not duplicated if it qualifies through both assigned posting and native programme department.
- Native GRM Resident John posted to TTSH Rehab sees TTSH Rehab Department Secretary events, TTSH GRM Department Secretary events, and GRM PC events.
- Native Rehab Resident Mary posted to TTSH GRM sees TTSH GRM Department Secretary events, TTSH Rehab Department Secretary events, and Rehab PC events.

Visibility source does not determine compliance attribution. An approved native-programme event outside the assigned posting is projected at read time as exactly one `Department/Programme Teaching [1h]` session under the resident's assigned posting and its TTF target. The event creator posting and `programmes.native_teaching_posting_code` are never separate compliance identities. Events held at the assigned posting continue through normal catalogue resolution unless another explicit rule applies.

Operational deactivation is not period close/freeze. It does not generate `period_snapshots`, `clawback_records`, or surplus hibernation, and it does not run compliance calculation. Admin JIT reports may still calculate a selected inactive period explicitly.

### Admin reporting views — shared compliance contract

Admin reports and the resident dashboard must execute the same ordered BL-6 rules and produce identical calculation fields. An optimized batch query may prefetch or aggregate data, but it is not a separate business-logic path and must not omit AY-label FormF1 gating, read-time projections, exact-type weekend rules, R-year-context caps, raw-count reallocation, persistent-surplus recomputation, or posting-group ordering. No illustrative SQL in this document is normative.

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

Multiple source postings resolve to one configured canonical combined posting code/name that already exists in `posting_codes` and has corresponding TTF rows. Persist one `resident_postings` row using that combined posting code (for example, `TTSHDiagRd` + `NNINeuRad` → `TTSHDiagRd & NNINeuRad`). Compliance target and catalogue lookup use the canonical combined code. Do not create separate component compliance results and do not treat the display label as a newly invented posting identity.

### half_month type

Two posting codes appear in the same RDB cell and match a `half_month` rule (currently only TTSHGas / NUHGas) → two separate `resident_postings` rows are created, each retaining its own posting code, TTF target, and compliance identity, with `active_months_weight = 0.5`.

- Apply the `0.5` factor exactly once through `active_months_weight`; keep the uploaded `monthly_target` unchanged
- Numerator sessions count fully at each posting — no numerator weighting
- A resident can accumulate 1.5 months at TTSHGas and 0.5 months at NUHGas across a period
- Posting-group aggregation may combine the separately calculated posting results later only when separately configured; it does not change half-month persistence

### main_posting type (FM)

Multiple posting codes appear in a single FM sheet cell. Explicit two-code `main_posting` rows, if present, are applied first. If no explicit rule matches, the parser uses the FM `main_posting` rows where `posting_code_2 IS NULL` as the recognised `RDB Posting #1` trigger list.

This rule collapses the sources to one configured existing `main_posting_code`, which becomes the compliance identity. It does not create a combined posting identity.

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
1. Resident first selects teaching date.
2. System derives assigned posting for that selected date:
   - NHG Resident: from `resident_postings` for the date (`status IN ('active', 'loa_working')`).
   - Non-NHG Resident: from `external_resident_postings` for the date after forecast posting schedule support is implemented.
3. Resident selects the attended TTSH department/programme from an additional dropdown backed by validated `posting_codes` / explicit config. This supports cases where residents attend teaching outside both their assigned posting and native programme. Do not create posting codes by string concatenation or regex.
4. In the current legacy A-K transition, the system returns teaching/session names from TTF Column K / `teaching_name_catalogue`, filtered by selected attended TTSH department posting, resident native programme where applicable, selected date, r_year/reporting-period context, and normal catalogue rules.
5. Resident selects a catalogue-backed teaching option and provides `start_time`. Optional `details_of_session` may be captured as display/audit-only text.
6. System validates the selected teaching option still exists in the same catalogue context at submit time. Arbitrary free-text teaching names must not drive compliance mapping.
7. System creates a `teaching_events` row with `is_adhoc = true`, `posting_code = assigned/compliance posting for NHG Resident ad-hoc`, `created_by_role = 'resident'` or `'external_resident'`, the matching immutable typed creator foreign key, `cme_points_awarded = false`, `smc_event_code = null`, and `details_of_session` if provided.
8. A narrow PostgreSQL function derives the trusted subject and storage family
   from the verified transaction-local context and creates that event plus an
   `attendance_records` row for an NHG Resident, or an
   `external_attendance_records` row for a Non-NHG Resident. The function does
   not commit; the service commits the complete operation once.
9. For countable NHG ad-hoc compliance attribution, `end_time`/duration is fixed to `Department/Programme Teaching [1h]` semantics; the attended teaching's original session type does not drive compliance attribution.

**UI helper copy:** `Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.`

**NHG Resident compliance treatment:** All countable NHG Resident ad-hoc sessions map to `Department/Programme Teaching [1h]`. Count is attributed to the resident's assigned posting for the selected date, not the attended TTSH department unless that is also the assigned posting.

The fixed session type must resolve against a tracked `Department/Programme Teaching [1h]` target for assigned posting, resident native programme, `resident_postings.r_year`, and active/effectively active `reporting_period_id`. If that required target cannot be resolved, return a clear unavailable/not-countable state rather than guessing.

This supersedes any interpretation that ad-hoc compliance session type is resolved from the attended teaching's original session type. Selected teaching name is controlled catalogue/display evidence only for ad-hoc compliance.

**Non-NHG treatment:** Non-NHG ad-hoc sessions are recording/export-only. They write `external_attendance_records`, never native `attendance_records`, and never enter NHG numerator, denominator, surplus, snapshots, clawback, or native resident compliance reports. Host programme/department selection is option-filtering/export context only.

**Validation:**
- Date must not be a public holiday (422 if PH)
- Teaching name must be selected from the catalogue-backed dropdown for the selected attended department posting + resident programme where applicable + r_year/reporting period (422 if not found)
- Required assigned-posting `Department/Programme Teaching [1h]` target must exist for countable NHG ad-hoc compliance; otherwise return unavailable/not-countable
- Duplicate detection (BL-5) applies

**Ownership, history, and concurrency:** PostgreSQL permits an ad-hoc event to
belong to exactly one native or external creator and rejects the other storage
family and every other Resident. Creator evidence and attendance
subject/event identifiers are immutable. Native and external submissions use
the same family-specific subject/date advisory-lock protocol. Removing
attendance transitions one submitted row to `removed`; resubmission inserts a
new submitted row and preserves the old identifier, so a stale removal request
cannot remove a newer resubmission.

The complete `event_ids` list in one `POST /resident/attendance` request is the
scheduled-attendance atomic unit. Every item is validated before DML, then the
batch commits once. Any validation, insert, or commit failure rolls back the
entire request. Attendance submit/remove and staff event mutation share a
transaction-scoped advisory key derived from the trusted event UUID. Staff
edit/delete then takes `FOR UPDATE`; batch and series event keys are sorted.
This avoids granting Residents an event UPDATE policy solely for locking and
serializes attendance against event changes. Any linked attendance status is a
dependency; ordinary mutation returns `409` rather than bypassing
removed/flagged history. The Master Admin force-delete operation remains the
only reviewed all-status hard-delete exception.

**Schema note:** `details_of_session` is stored on
`teaching_events` because both NHG and Non-NHG ad-hoc submissions create an
event row; it has no operational or compliance use. `attended_posting_code`
still has no dedicated persisted field and may need a future audit/display
column or table. Do not overload `teaching_events.posting_code`, which remains
the assigned/compliance posting for NHG ad-hoc.

---

## BL-12: Non-NHG / Cross-Cluster Resident Attendance

Non-NHG Residents are NUH or SingHealth residents who are temporarily posted to NHG departments and need to record teaching attendance for forwarding to their home cluster.

Phase 5B must be completed before Phase 6 compliance calculation begins.

**Identity and storage:**
- Non-NHG Residents live in `external_residents`, not `users` and not native `residents`.
- Non-NHG attendance lives in `external_attendance_records`, not native `attendance_records`.
- Non-NHG Residents are not RDB-backed and do not use native `resident_postings`.
- MCR is globally unique across native `residents` and `external_residents`; enforce cross-table checks in service code.

**Allowed home clusters:**
- `NUH`
- `SingHealth`

No other `home_cluster` values are valid.

**Forecast posting schedule:**
Non-NHG registration captures a repeatable upcoming NHG postings schedule instead of one "current NHG posting" field. Each row captures `start_date`, `end_date`, `programme_code` displayed as code plus full programme name, an institution returned by the backend registration-options response, and a backend-resolved `posting_code` from `programme_institution_posting_map`. Persist the validated `programme_code` and resolved `posting_code` together on each date-bounded `external_resident_postings` row; programme identity is schedule-row provenance, not a global field on `external_residents`.

Rows are persisted in `external_resident_postings`. Rows for the same Non-NHG Resident must not overlap. Gaps are allowed; event/ad-hoc options for a date in a gap return unavailable/no posting for selected date. Date ranges may cross calendar months.

`external_residents.current_nhg_posting_code` may remain as a current/cache/backward-compatibility pointer if implementation needs it, but once forecast posting schedule is implemented, authorization-sensitive event/ad-hoc derivation uses the date-matching `external_resident_postings` row.

Posting codes resolve only through the exact normalized `(programme_code, institution_code)` row in `programme_institution_posting_map`. The row must exist, have `status = active`, have a non-null posting code, and retain valid programme/posting foreign keys. Pending, inactive, missing, malformed, or invalid rows fail closed with controlled `422`; no fallback or alternative candidate search is allowed.

Never concatenate strings, infer an RDB code from a posting/institution name or prefix, fuzzy-match posting metadata, select a teaching-target/native/Secretary candidate, trust a client-provided posting code, or fall back to another programme/institution.

All schedule rows are resolved before registration or replacement writes begin. One unavailable row creates no external resident and no partial posting schedule; a failed replacement preserves the prior schedule.

New registration, schedule replacement, and current-posting compatibility writes always preserve the validated programme on the schedule row. The database column remains nullable only for legacy rows that cannot be resolved safely. Backfill only when authoritative mapping data identifies exactly one programme; ambiguous shared postings such as `TTSHGenMed` (AIM/IM) and `TTSHGenSrg` (GS/SIG) remain null. Never select the first matching mapping, and never grant Programme PC-event visibility to a null-programme legacy row.

**Current two-stage rollout:** Stage 1 established the generic mapping infrastructure and a 28-row pending/null TTSH safety baseline. The approved Stage 2 data-only migration produces exactly 24 active TTSH mappings, four inactive/null TTSH mappings (`FM`, `PATH`, `SPORTSMED`, and `PALLMED`), and zero pending TTSH mappings. Public Non-NHG registration options expose only the 24 active choices. The inactive status is scoped exclusively to Non-NHG programme/institution registration and schedule selection; it does not deactivate those programmes elsewhere in MATA. `GERI + TTSH` resolves through the same data-driven path to `TTSHGerMed`, with no runtime exception. KTPH, WH, and later institutions are discovered from future mapping rows without resolver or frontend branches.

**Isolation:** This external-registration mapping does not set or consult `programmes.native_teaching_posting_code`, `posting_codes.supports_secretary_events`, Secretary programme pools, resident event visibility configuration, or compliance posting attribution. Those domains retain their own rules.

**Scheduled-event visibility and submission:**
For each candidate event date, use the one `external_resident_postings` row whose date range covers that event. A gap produces no eligible event. The allowed scheduled-event sources are:

1. **Department Secretary event:** `event.posting_code = schedule.posting_code` and `event.created_for_programme_code IS NULL`. `posting_codes.supports_secretary_events` must be true, and the normal scheduled-event, reporting-period, status, date, duplicate/submission, and other existing filters continue to apply.
2. **Programme PC event:** the schedule `programme_code` must be present, `event.posting_code = schedule.posting_code`, and `event.created_for_programme_code = schedule.programme_code`. The normal scheduled-event, reporting-period, status, date, and duplicate/submission filters continue to apply. This source does not depend on the Secretary capability flag.

Both listing and `POST /resident/attendance` enforce the same exact source rule. Exclude another programme's PC event even when it shares the posting, a matching-programme event at another posting, events outside a schedule range or in a gap, any resident ad-hoc event, and events already submitted by that Non-NHG Resident. Successful attendance writes only `external_attendance_records`.

Do not hardcode TTSH or another institution in service logic. Never infer programme ownership from a posting-code prefix, institution name, teaching target, teaching-name catalogue row, `programmes.native_teaching_posting_code`, fuzzy match, or first mapping candidate. AIM and IM may share `TTSHGenMed`; GS and SIG may share `TTSHGenSrg`, so the persisted schedule programme is mandatory for PC-event authorization. Current TTSH pilot postings can enable Secretary listings through the capability flag; future hospitals such as KTPH can be onboarded through data.

**Compliance exclusion:**
Non-NHG Residents are excluded from all NHG compliance surfaces:
- no NHG compliance dashboard
- no numerator inclusion
- no denominator inclusion
- no surplus ledger
- no period snapshots
- no clawback
- no native resident compliance reports

`GET /resident/dashboard` for a Non-NHG Resident returns `not_applicable`, not compliance metrics.

**Phase 6 guardrail:** Compliance reads native `attendance_records` only. It must never join `external_attendance_records`, even for reporting convenience.

**Submission behaviour:**
- Non-NHG Residents can submit attendance for eligible Department Secretary events and exact-programme Programme PC events at their date-matched schedule posting.
- Non-NHG Residents can submit ad-hoc teaching using the revised catalogue-backed dropdown model.
- PH ad-hoc teaching is hard-blocked with `422`.
- Weekend non-exception submissions are stored and return `compliance_warning`.
- Session type is not stored on external attendance.

**Pre-compliance Phase 5B workflow scope:**
- Non-NHG registration/login
- Non-NHG upcoming NHG posting schedule update
- Non-NHG event listing
- Non-NHG attendance submission
- Non-NHG ad-hoc teaching submission using the revised dropdown model
- Non-NHG past attendance
- admin/PC external attendance list/read endpoint
- Excel export endpoint for external attendance
- frontend export preview/download flow where the roadmap UI scope includes it

**Non-NHG ad-hoc attended department selection:**
Non-NHG ad-hoc teaching uses the same date-first UI concept as NHG Residents. After the selected date resolves a date-matched `external_resident_postings` row, the attended TTSH department/programme dropdown filters catalogue-backed teaching options. Host programme/department selection is for option filtering/export context only. It must not make Non-NHG Residents part of native NHG compliance.

**Export status:**
External attendance must be queryable by authorized admin/PC users and exportable to Excel for forwarding to NUH/SingHealth PCs before Phase 6 compliance. Exported records are for recording/audit/forwarding only and must never write to native compliance, surplus, snapshots, or clawback outputs.

---

## BL-10: Clawback Calculation — DEFERRED

The ordinary non-clawback compliance specification is independent of this deferral. A future clawback implementation must use the same unrounded posting percentage predicate (`percentage < 0.70`) to identify failure, but that statement does not settle the financial calculation.

The legacy audit preserves evidence about the former scripts. That evidence is not an authoritative MATA formula and must not be copied as implementation logic. The following remain explicitly deferred: norm-rate values and persistence/effective dating; funding/clawback R-year selection; IM/subspecialty classification for financial rates; Extension/R7/SAF/SCDF suppression granularity and precedence; grouped-posting clawback identity; billing-department attribution; missing-rate behavior; financial rounding/precision; and final-close transaction, rerun, and idempotency behavior.

No clawback calculation, row-generation rule, final-close behavior, or implementation-ready API response contract is specified until those decisions are confirmed.

---

## BL-11: R-Year Configuration

20 of the 28 programmes do not differentiate teaching targets by residency year. For these programmes, `r_year_required = false` on the `programmes` table.

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

### SPORTSMED and PALLMED

Both programmes require R-year matching and are not configured as subspecialties:

- `r_year_required = true`
- `is_subspecialty = false`
- RDB R4, R5, and R6 remain R4, R5, and R6
- TTF target and catalogue rows use R4, R5, and R6
- Do not use `ALL` and do not remap these values to SS1, SS2, or SS3

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

### r_year_required = false (20 programmes)
AIM, CARDIO, EM, ENDO, ENT, EYE, GASTRO, GERI, GS, ID, IM, MEDONCO, ORTHO, PATH, REHAB, RENAL, RHEUM, SIG, URO, MICROB

### r_year_required = true (8 programmes)
ANAES, DERM, DR, FM, PSY, RESPI, SPORTSMED, PALLMED

---

## TBD-6: Refresher Training Compliance Treatment ✅ CLOSED

**Status: Closed.** Handled automatically by FormF1 active/inactive gate.

Refresher Training months that render a resident inactive appear as `Inactive` in FormF1 — no separate handling needed. The compliance denominator is governed by FormF1, not by RDB Refresher Training annotations.

The `add to Max Cand` / `don't add to Max Cand` flag is stored as a display annotation on `resident_postings.refresher_training_type`. No compliance impact. No code action needed beyond storing the value for display.

---

## TBD-7: Active/Inactive Source — FormF1 vs RDB ✅ CLOSED

**Status:** Resolved. FormF1 is the final authoritative active/inactive source for compliance.

**Final behaviour:**
- `form_f1_records.is_active` remains stored per calendar month, but the AY bucket's month label selects the FormF1 row used to gate both numerator and denominator for the whole bucket
- Active status values: `Active`, `Extension` → is_active = true
- `Inactive`, blank, `NULL`, and whitespace-only monthly cells → is_active = false → excluded from both numerator and denominator; valid MCR rows persist an inactive record for each blank in-scope month
- `form_f1_records.promotion_date` is captured from FormF1 for future R3→R4/senior promotion handling, but current compliance logic must not use it yet
- Employed residents: ordinary compliance follows FormF1 like other residents; any future financial treatment remains deferred
- LOA months that render a resident inactive appear as Inactive in FormF1 — no separate LOA compliance logic needed

**Why FormF1 over RDB for active/inactive:**
FormF1 remains the authoritative monthly source, while `academic_month_boundaries.month_label` is the bridge from an attendance or denominator date to the applicable FormF1 month. For example, an AY bucket labelled `Jul-26` may extend into 3 August; the whole bucket uses July FormF1 and is neither split nor prorated.

**RDB-derived denominator logic:**
Not implemented. Do not derive active/inactive status from RDB LOA/refresher/employed annotations. These remain parser/audit/display fields unless a separate future requirement explicitly changes this.

**Refresher Training and Employed treatment under FormF1:**
Both are handled automatically via FormF1 values. No special-case code needed.

---

## TBD-MIGRATION: Historical Data Migration Strategy (superseded — settled)

**Status:** **Settled — no historical data migration.** The 2026-08-02 evolved TTF transition contract supersedes this former TBD. The alternatives below are retained only as audit history.

**Settled rule:** Do not import, backfill, or migrate historical data. Retain legacy workbooks as legacy structural references only; do not build migration tooling.

**Historical options (superseded; not actionable):**

**Option A — Archive only (recommended default):**
Legacy Excel files remain accessible. New system holds data from cutover period onwards. Zero migration effort.

**Option B — Summary migration:**
One-time script reads legacy Programme Reporting View Excel files and inserts summary-level compliance records. Medium effort.

**Option C — Full migration:**
Parse original FormSG CSVs and legacy `.rds` snapshot files. Highest fidelity, highest effort.

**Developer instruction:** Do not build migration tooling. No option remains to be confirmed.

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

**BL-11 (R-year configuration):** Closed. `r_year = 'ALL'` applies to 20 programmes; eight require R-year matching. SPORTSMED and PALLMED use R4–R6 unchanged and have `is_subspecialty = false`. ✅

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
- Period snapshots are generated only by a future final close/freeze workflow, not by reporting-period deactivate/inactive status; snapshot/export reads may have longer TTLs.

### Required invalidation triggers

Invalidate affected compliance/report caches after:

- RDB upload or re-upload
- TTF upload, re-upload, or teaching target edit
- FormF1 upload or re-upload
- public holiday upload or public holiday CRUD change
- `posting_groups`, `multi_posting_rules`, `weekend_exceptions`, `global_session_types`, `programmes`, or `loa_types` CRUD change
- secretary teaching event create/update/delete
- Programme PC teaching event create/update/delete/duplicate/recurrence mutation
- Master Admin Secretary/PC event force deletion, including linked native and Non-NHG attendance removal
- resident attendance submit/delete
- resident ad-hoc teaching create
- reporting period create/update/delete/activate/deactivate or scheduled transition edits

### Data Revalidation

Data Revalidation is the standard service boundary for assessing the impact of Admin/PC Live Data and Config mutations. The backend service name is `data_revalidation_service`; user-facing text should use `Data Revalidation`, `Revalidate data`, and `Data revalidation impact summary`.

3H-B creates only the service contract/skeleton. It returns stable impact summaries with one of `no_op`, `warning_only`, `targeted_revalidation`, `future_compliance_impact`, or `manual_revalidation_required`.

3H-C wires Admin Live Data correction mutations to the service. Successful Resident, Resident Posting, Resident Posting source-cell replacement, Teaching Target, FormF1, and Academic Month Boundary corrections include a `data_revalidation` impact summary in the API response and correction audit metadata. Failed validation, stale/concurrency, unauthorized, or out-of-scope mutations do not call Data Revalidation.

3H-D wires successful Admin/PC Config CRUD mutations to the service. Reporting periods, public holidays, programmes, LOA types, multi-posting rules, posting groups, weekend exceptions, and global session types return `data_revalidation` in successful mutation responses and config audit metadata. Failed validation, unauthorized, out-of-scope, not-found, duplicate/conflict, and protected-delete mutations do not call Data Revalidation.

3H-D still does not mutate warnings, run RDB source-cell parsing, re-resolve existing multi-posting source cells, regenerate `resident_postings`, or calculate compliance. Multi-posting rule changes return `manual_revalidation_required` as a placeholder impact summary until 3H-E concrete handlers are implemented.

3H-E2 persists upload warnings as first-class `warning_issues` and `upload_warnings` records derived from immutable `upload_logs.summary`. Warning fingerprints group repeated occurrences across uploads. Admins may mark issues `resolved`, `dismissed`, or `superseded`; if the same fingerprint appears in a later upload, the issue becomes `reappeared` while preserving the prior resolution metadata.

3H-E2 warning actions are operational triage only. They do not mutate `upload_logs.summary`, parse RDB source cells, re-resolve multi-posting rules, regenerate `resident_postings`, update/resolve warning source data automatically, calculate compliance, generate snapshots, hibernate surplus, or generate clawback rows. Those concrete handlers remain later work.

Normal Refresh buttons are read-only refetch actions and must not trigger Data Revalidation. Reserve `reparse` for the low-level RDB source-cell parsing step only.

### What must never be cached as authoritative

- raw attendance rows
- raw uploaded files
- mutable upload parse warnings/errors
- authentication results
- authorization decisions without scope keying
- `surplus_ledger` after tag reallocation; the ledger stores pre-reallocation values only

### Query performance expectations

Compliance and reporting queries must use the indexes documented in `docs/schema.md`. Admin report SQL should be checked with `EXPLAIN ANALYZE` once sample data exists. If performance remains poor, prefer query/index tuning before introducing materialised compliance tables.
