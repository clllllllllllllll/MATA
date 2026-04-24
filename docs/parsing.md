# Parsing Rules — RDB and TTF Upload

---

## RDB Parser

**Input:** `03_RDB_Posting_Schedule.xlsx`  
**Sheets:** `Phase 1 & 2`, `Phase 3`, `Phase 1 & 2 (FM)`, `SSR`  
**Trigger:** `POST /admin/upload/rdb`

### Sheet Structure

- **Row 1:** Month labels (`Jul-25`, `Aug-25`, ..., `Jun-26`)
- **Row 2:** Column headers with date ranges in columns I–T (e.g. `8 Jul 2025 - 3 Aug 2025`)
- **Rows 3+:** Resident data

### Column Mapping

| Column | Field | Notes |
|--------|-------|-------|
| A | employee_code | |
| B | name | |
| C | mcr | Primary identifier |
| D | classification | `Junior Resident` or `Senior Resident` |
| E | base_institution | May be `-` |
| F | r_year | `R1`..`R7` |
| G | specialization | Maps to programme_code via lookup |
| H | reg_type | `Full` or `Conditional` |
| I–T | posting per month | 12 month-phase columns |
| U | email | |
| V | phone | |

### Date Range Extraction

Column headers in row 2 (columns I–T) contain date ranges like `8 Jul 2025 - 3 Aug 2025`. Parse these to get `start_date` and `end_date` for each month-phase.

```python
import re
from datetime import datetime

def parse_date_range(header: str) -> tuple[date, date]:
    """Parse '8 Jul 2025 - 3 Aug 2025' into (date, date)"""
    match = re.match(r'(\d{1,2}\s+\w+\s+\d{4})\s*-\s*(\d{1,2}\s+\w+\s+\d{4})', header)
    if not match:
        raise ValueError(f"Cannot parse date range: {header}")
    start = datetime.strptime(match.group(1), '%d %b %Y').date()
    end = datetime.strptime(match.group(2), '%d %b %Y').date()
    return start, end
```

### Posting Cell Parsing

Each cell in columns I–T can be one of:

**1. Simple posting code:**
```
TTSHAnaes
```
→ `posting_code = "TTSHAnaes"`, `status = "active"`

**2. Empty cell:**
```
(blank)
```
→ Skip. Resident has no posting this month (may have exited programme).

**3. Pure LOA:**
```
LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025)
```
→ `posting_code = NULL`, `status = "loa"`, `loa_type = "Maternity Leave"`, parse dates

**4. Hybrid LOA (posting + LOA on same line):**
```
TTSHAnaes (Continue working during LOA from 01-Sep-2025 to 05-Oct-2025)
```
→ `posting_code = "TTSHAnaes"`, `status = "loa_working"`, parse LOA dates

**5. Multiline (posting + LOA on separate lines):**
```
TTSHGenMed\nLOA (Maternity Leave from 30-Aug-2025 to 31-Aug-2025)
```
→ `posting_code = "TTSHGenMed"`, `status = "loa_working"`, parse LOA dates from second line

**5b. Multiline hybrid (Continue working + pure LOA on separate lines):**
```
TTSHAnaes (Continue working during LOA from 02-Jun-2026 to 02-Jun-2026)
LOA (Maternity Leave from 03-Jun-2026 to 06-Jul-2026)
→ posting_code = "TTSHAnaes", status = "loa_working"
→ loa dates taken from the pure LOA line, not the Continue working line
```
**6. Pending SR promotion:**
```
TTSHEmgMed (Pending for SR Promotion from 06-Apr-2026 to 03-May-2026)
```
→ `posting_code = "TTSHEmgMed"`, `status = "active"`, store promotion annotation

**7. Employed posting:**
```
SAF-Employed, SCDF-Employed, KTPH-Employed, NCIS-Employed, 
SGH-Employed, NUH-Employed, TTSH-Employed, Assisi-Employed, NCCS-Employed
— and any future XXX-Employed variants

Detection: re.match(r'^[\w]+-Employed$', val)

→ posting_code = NULL
→ status = "employed"
→ employer_tag = val.split('-')[0]  # "SAF", "SCDF", "KTPH" etc.
   stored on residents.employer_tag, not on resident_postings

No resident_postings row is created for this month.
Resident-level employer_tag is set once on first encounter and 
persisted — subsequent months with the same pattern are consistent 
with the existing tag.
```
**8. Numeric values (FM polyclinic numbers):**
```
1, 2, 3, ... 270
```
→ These appear in the FM sheet. They are polyclinic site codes. Store as `posting_code` (convert to string).


**9. Refresher Training:**
```
PostingCode (Refresher Training (add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)
PostingCode (Refresher Training (don't add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)
→ posting_code = "PostingCode", status = "active"
→ store refresher_training_type, refresher_training_start, refresher_training_end
Detection: re.search(r'\(Refresher Training', val)
```
### LOA Date Parsing

LOA dates use format `DD-MMM-YYYY` (e.g. `01-Sep-2025`). Also handle variants with spaces around hyphens: `01 - Sep - 2025`.

```python
def parse_loa_annotation(cell_value: str) -> dict:
    """Parse LOA type and dates from cell annotation."""
    result = {'status': 'active', 'loa_type': None, 'loa_start': None, 'loa_end': None}

    loa_match = re.search(
        r'LOA\s*\(([^)]*?)\s+from\s+([\d\s\-\w]+?)\s+to\s+([\d\s\-\w]+?)\)',
        cell_value
    )
    if not loa_match:
        return result

    result['loa_type'] = loa_match.group(1).strip()
    
    # Normalise date: "01 - Sep - 2025" → "01-Sep-2025"
    start_str = re.sub(r'\s*-\s*', '-', loa_match.group(2).strip())
    end_str = re.sub(r'\s*-\s*', '-', loa_match.group(3).strip())
    
    result['loa_start'] = datetime.strptime(start_str, '%d-%b-%Y').date()
    result['loa_end'] = datetime.strptime(end_str, '%d-%b-%Y').date()

    # Determine status
    if 'Continue working' in cell_value:
        result['status'] = 'loa_working'
    elif cell_value.strip().startswith('LOA'):
        result['status'] = 'loa'
    else:
        result['status'] = 'loa_working'

    return result
```

### Posting Code Extraction

```python
def extract_posting_code(cell_value: str) -> str | None:
    if not cell_value or not cell_value.strip():
        return None
    
    val = cell_value.strip()
    
    # Pure LOA — no posting
    if val.startswith('LOA'):
        return None
    
    # Employed — no posting
    if re.match(r'^[\w]+-[Ee]mployed$', val):
        return None
    
    # Multiline: take first line
    if '\n' in val:
        val = val.split('\n')[0].strip()
    
    # Strip known annotation parentheticals only — not posting code suffixes
    for annotation in ['Continue working during LOA', 'Pending for SR Promotion', 
                       'Refresher Training']:
        if f'({annotation}' in val or f'({annotation.split()[0]}' in val:
            val = val.split('(')[0].strip()
            break
    
    return val if val else None
```

### Programme Code Resolution

The RDB "Specialization" column contains full names like "Geriatric Medicine". Map to programme codes using a seeded lookup:

```python
PROGRAMME_LOOKUP = {
    'Anaesthesiology': 'ANAES',
    'Advanced Internal Medicine': 'AIM',
    'Cardiology': 'CARDIO',
    'Dermatology': 'DERM',
    'Diagnostic Radiology': 'DR',
    'Emergency Medicine': 'EM',
    'Endocrinology': 'ENDO',
    'Family Medicine': 'FM',
    'Gastroenterology': 'GASTRO',
    'General Surgery': 'GS',
    'Geriatric Medicine': 'GERI',
    'Infectious Disease': 'ID',
    'Internal Medicine': 'IM',
    'Medical Oncology': 'MEDONC',
    'Microbiology': 'MICRO',
    'Ophthalmology': 'OPHTH',
    'Orthopaedic Surgery': 'ORTHO',
    'Otorhinolaryngology': 'ENT',
    'Palliative Medicine': 'PALL',
    'Pathology': 'PATH',
    'Psychiatry': 'PSYCH',
    'Rehabilitation Medicine': 'REHAB',
    'Renal Medicine Extended': 'RENAL',
    'Respiratory Medicine': 'RESP',
    'Rheumatology': 'RHEUM',
    'Sports Medicine': 'SPORTS',
    'Surgery-in-General': 'SIG',
    'Urology': 'URO',
}
```

### SSR Sheet

The SSR (Sub-Specialty Registrar) sheet has a different structure: MCR, Name, SI, Specialty, residency end date, SSR start date, interim posting. Parse separately — these are residents who have completed residency and are in an interim posting.

### Processing Order

1. Parse all sheets, collect resident data and posting schedules
2. Upsert `programmes` table from distinct specializations
3. Upsert `posting_codes` table from distinct posting codes found
4. Upsert `residents` table (keyed by MCR) — `residents.r_year` is updated to the value in column F, but this is for display only. Do not use it for compliance target lookup.
5. **Delete** existing `resident_postings` rows for the reporting period (scoped to residents present in this upload). This is a delete-first, not a blind insert — see Edge Cases § RDB re-upload below.
6. Insert `resident_postings` rows (one per resident per month-phase), copying `r_year` from RDB column F into **each row's** `r_year` column. A resident who is R3 in July and R4 in January must have `r_year = 'R3'` on July's row and `r_year = 'R4'` on January's row.

---

## TTF Parser

**Input:** `Teaching_Target_File_<PROGRAMME>__CL.xlsx`  
**Sheet:** `Sheet1`  
**Trigger:** `POST /admin/upload/ttf` with `reporting_period_id` and `programme_code`

### Column Mapping

| Column | Field | Notes |
|--------|-------|-------|
| A | reporting_period | e.g. `Jan - June` — validated against reporting_periods table |
| B | programme_code | e.g. `DR`, `GERI` |
| C | r_year | Single (`R2`) or multi (`R4, R5, R6`) — must be exploded |
| D | posting_code | Bare code (e.g. `KTPHDiagRd`) or legacy bracket format |
| E | dashboard_posting | Can be ignored — display only |
| F | session_type | Full name with duration, e.g. `Department/Programme Teaching [1h]` |
| G | monthly_target | Integer frequency target at 100% |
| H | is_tracked | `Yes` → true, anything else → false |
| I | is_reallocatable | `Y` → true, anything else → false |
| J | tag | Reallocation group label, e.g. `A`, `B`. Empty = no reallocation |
| K | details_of_training | Comma-separated keywords (e.g. `Journal Club, Grand Round, M&M`). Populated from PM-confirmed keyword list. Each `(keyword, duration)` combination must map to exactly one session type within a posting per programme — validated at upload time. |

### Multi-Year Row Explosion

Column C may contain comma-separated years: `R4, R5, R6`. Each becomes a separate `teaching_targets` row with identical values.

```python
def explode_r_years(r_year_str: str) -> list[str]:
    """'R4, R5, R6' → ['R4', 'R5', 'R6']"""
    return [y.strip() for y in r_year_str.split(',') if y.strip()]
```

### Posting Code Parsing

Column D may be in different formats:

**Clean (target format):**
```
KTPHDiagRd
```
→ Use directly

**Legacy bracket format (dormant sites):**
```
AIC [] [AICAIC]
```
→ Extract code from last bracket: `AICAIC`

**Dual-posting with `&`:**
```
PsyG [] [IMHGrPsyc & TTSHPsychi]
```
→ Explode into two rows: one for `IMHGrPsyc`, one for `TTSHPsychi` (identical targets)

```python
def parse_posting_code(raw: str) -> list[str]:
    """Parse posting code(s) from TTF column D."""
    raw = raw.strip()
    
    # Check for bracket notation
    bracket_match = re.search(r'\[([^\]]+)\]\s*$', raw)
    if bracket_match:
        inner = bracket_match.group(1).strip()
        # Check for & (dual posting)
        if '&' in inner:
            return [code.strip() for code in inner.split('&')]
        return [inner]
    
    # Bare code
    return [raw]
```

### Session Type Parsing

Extract duration from the session type name:

```python
def parse_session_type(name: str) -> tuple[str, float]:
    """Returns (name, duration_hours)"""
    match = re.search(r'\[(\d+(?:\.\d+)?)h\]', name)
    if match:
        return name.strip(), float(match.group(1))
    return name.strip(), 0.0  # unknown duration
```

### Validation Rules

Before inserting, validate:

1. `programme_code` matches a known programme
2. Each posting code exists in `posting_codes` table (or add it as a new dormant code)
3. `monthly_target` is a positive number
4. `session_type` name contains a duration bracket `[Xh]`
5. No duplicate `(reporting_period_id, programme_code, r_year, posting_code, session_type_id)` after explosion
6. If `is_reallocatable = true`, `tag` must not be empty
7. If `tag` is set, there must be at least one other row at the same posting with the same tag
8. **Keyword deduplication:** For each keyword in `details_of_training`, the `(keyword, duration_hours)` combination must map to exactly one session type within the same `(posting_code, programme_code)`. If the same keyword appears under two different session types with the same duration at the same posting, reject the upload with a descriptive error listing the conflicting rows.

### Upload Behaviour

The TTF upload is a full replace within `(reporting_period_id, programme_code)` scope. Mid-period corrections use the admin CRUD UI (`PUT /admin/teaching-targets/{id}`), not re-upload.

#### Concurrency — scope-level advisory lock

Two admins uploading TTFs for the same `(reporting_period_id, programme_code)` concurrently would produce a race on the delete+insert cycle. Prevent this with a PostgreSQL advisory lock keyed on the scope, acquired at the start of the transaction and released on commit/rollback:

```python
import hashlib

def ttf_scope_lock_key(reporting_period_id: str, programme_code: str) -> int:
    """
    Derive a stable 64-bit advisory lock key from the upload scope.
    hashlib gives us a stable hash without collisions across restarts.
    """
    raw = f"ttf:{reporting_period_id}:{programme_code}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF

async def upload_ttf(session, reporting_period_id, programme_code, rows):
    lock_key = ttf_scope_lock_key(reporting_period_id, programme_code)
    # pg_try_advisory_xact_lock returns false immediately if already locked
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": lock_key}
    )
    if not result.scalar():
        raise HTTPException(409, "Another TTF upload for this scope is in progress")

    # Lock held for duration of transaction
    await session.execute(
        text("DELETE FROM teaching_targets "
             "WHERE reporting_period_id = :period AND programme_code = :prog"),
        {"period": reporting_period_id, "prog": programme_code}
    )
    # ... insert new rows (see ON CONFLICT below) ...
```

Two concurrent uploads for **different** scopes (e.g. DR vs GRM) do not block each other.

#### `ON CONFLICT` upserts for catalogue tables

`session_types` and `posting_codes` are shared catalogues that may already contain rows from a previous TTF upload or a different programme's upload. Use `ON CONFLICT DO NOTHING` (or `DO UPDATE` for `posting_codes` display_name) rather than blind inserts:

```sql
-- session_types: keyed on the full name string (name is the natural key)
INSERT INTO session_types (id, name, duration_hours)
VALUES (:id, :name, :duration_hours)
ON CONFLICT (name) DO NOTHING;

-- posting_codes: add new codes; update display_name only if currently NULL
INSERT INTO posting_codes (code, display_name)
VALUES (:code, :display_name)
ON CONFLICT (code) DO UPDATE
  SET display_name = COALESCE(posting_codes.display_name, EXCLUDED.display_name);

-- teaching_targets: within-scope rows were just deleted, so plain INSERT is fine.
-- The UNIQUE constraint on (reporting_period_id, programme_code, r_year,
-- posting_code, session_type_id) is the safety net for any logic bugs.
INSERT INTO teaching_targets (...)
VALUES (...)
ON CONFLICT (reporting_period_id, programme_code, r_year, posting_code, session_type_id)
DO NOTHING;
```

#### Step order

1. Acquire scope-level advisory lock (fails fast with 409 if contended)
2. Validate all rows (see Validation Rules above) — abort before any writes if errors
3. `DELETE` all existing `teaching_targets` within scope
4. `INSERT ... ON CONFLICT DO NOTHING` into `teaching_targets`
5. `INSERT ... ON CONFLICT DO NOTHING` into `session_types`
6. `INSERT ... ON CONFLICT DO UPDATE` into `posting_codes`
7. Commit — lock released automatically

---

## TBD-2: Dormant Posting Codes

The following posting codes appear in the TTF but NOT in the current RDB. They are valid posting sites where no resident is currently posted.

**GRM dormant codes:**
`AICAIC`, `CGHGerMed`, `DPPallia`, `GERIResEdu`, `KTPHContCC`, `KTPHPallia`, `NTFGHGerMed`, `RenCiCommHosp`, `YishCommHosp`, `YCHPallia`

**DR dormant codes:**
`CGHDiagRd`, `NTFGHDiagRd`, `NUHDiagRd`, `SGHNuclea`, `SKHDiagRd`

**Status:** Handling confirmed — accept as-is, add to posting_codes with display_name = NULL. 
Canonical code correctness pending PM confirmation.

---

## Edge Cases

### In the event that the RDB posting is not done monthly
Column range I–T assumes 12 month-phases per reporting period. Parser should detect posting columns dynamically by scanning row 2 for date range headers rather than assuming a fixed column range.

### Empty cells in RDB posting columns
Skip — resident has no posting that month (may have exited, or posting TBD).

### Resident appears in multiple RDB sheets
Some residents may appear in both Phase 1 & 2 and Phase 3 sheets. Deduplicate by MCR — use the later sheet's data if there's a conflict.

### TTF frequency target of 0
Valid — means the session type exists at this posting but has no attendance requirement. Skip from compliance calculations.

### TTF "No" in Tracked column
The session type exists and events can be created, but attendance does NOT count toward the 70% compliance threshold.

### Posting code with parenthetical suffix in RDB
Examples: `TTSHCardio (CCU)`, `TTSHRespir(MICU)`, `KTPHOrtSrg(SportsMed)`
These are distinct posting codes — store them as-is including the parenthetical. They are NOT the same as `TTSHCardio` or `TTSHRespir`.

### FM polyclinic numeric codes
The FM sheet contains numeric posting codes (1, 2, 3, ..., 270) for polyclinic sites. Store as strings. These correspond to `NHGPlyNHGPly` in the main posting system — clarify mapping with PMs if needed.

### Overlapping date ranges for the same resident
After parsing all month-phase rows for a resident, check that no two rows overlap:

```python
def check_overlapping_phases(phases: list[dict], resident_mcr: str) -> list[str]:
    """
    phases: list of {start_date, end_date, month_label}
    Returns list of error strings (empty if no overlaps).
    """
    errors = []
    sorted_phases = sorted(phases, key=lambda p: p['start_date'])
    for i in range(len(sorted_phases) - 1):
        a, b = sorted_phases[i], sorted_phases[i + 1]
        if b['start_date'] <= a['end_date']:
            errors.append(
                f"Resident {resident_mcr}: phase {a['month_label']} "
                f"({a['start_date']}–{a['end_date']}) overlaps with "
                f"{b['month_label']} ({b['start_date']}–{b['end_date']})"
            )
    return errors
```

Overlapping phases are returned as validation errors in the upload response. The upload is **not** aborted — overlapping rows are inserted with a warning flag so the admin can investigate. The `GET /resident/events` query uses `ORDER BY start_date DESC LIMIT 1` as a tie-breaker when today falls on a boundary shared by two phases, so the portal remains functional even if overlaps exist.

### RDB re-upload (same reporting period)
When an admin re-uploads an RDB for a period that already has `resident_postings` data, the parser deletes all existing `resident_postings` rows for residents present in the new file before inserting the corrected rows. Residents not present in the new upload are untouched. This is a scoped delete-first, not a full-period wipe:

```python
async def delete_existing_postings(session, reporting_period_id: str, mcr_list: list[str]):
    """Delete resident_postings rows for the residents in this upload only."""
    await session.execute(text("""
        DELETE FROM resident_postings
        WHERE  reporting_period_id = :period_id
        AND    resident_id IN (
            SELECT id FROM residents WHERE mcr = ANY(:mcrs)
        )
    """), {"period_id": reporting_period_id, "mcrs": mcr_list})
```

Call this before the insert step in Processing Order step 6.