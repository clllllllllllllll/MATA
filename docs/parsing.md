# Parsing Rules — RDB, TTF, FormF1, and Public Holiday Uploads

---

## Upload Slots

All admin file uploads are routed through **dedicated upload slots** on the admin upload page. The endpoint determines which parser is invoked — filenames are never used for parser selection. The original client filename is stored in `upload_logs` for audit traceability only.

| Upload Slot | Endpoint | Accepted Format | Required Parameters |
|-------------|----------|-----------------|---------------------|
| RDB Posting Schedule | `POST /admin/upload/rdb` | `.xlsx` | `reporting_period_id` |
| Teaching Target File (TTF) | `POST /admin/upload/ttf` | `.xlsx` | `reporting_period_id`, `programme_code` |
| Form F1 | `POST /admin/upload/form-f1` | `.xlsx` | `reporting_period_id` |
| Public Holidays | `POST /admin/upload/public-holidays` | `.xlsx` or `.csv` | _(none beyond file)_ |

The TTF slot additionally requires the admin to select a **programme** (e.g. DR, GRM) from a dropdown before uploading, as a single TTF covers one programme at a time.

---

## RDB Parser

**Upload slot:** Admin uploads via the dedicated **RDB Posting Schedule** file input on the admin upload page. The filename is not used for parsing — the endpoint determines parser selection.
**Accepted format:** `.xlsx` only
**Sheets:** Dynamic — detect all sheets with valid RDB structure (see § Sheet Detection below). Known sheets as of current RDB: `Phase 1 & 2`, `Phase 3`, `Phase 1 & 2 (FM)`, `SSR`. Do NOT hardcode this list — new sheets may be added in future uploads.
**Trigger:** `POST /admin/upload/rdb`

### Sheet Detection

The parser must NOT enumerate sheets by name. Instead, iterate over all sheets in the workbook and apply the following detection logic:

**Standard resident sheets** (Phase 1 & 2, Phase 3, FM, and any future equivalents):
- Row 2 contains at least one cell matching the date-range pattern `\d{1,2}\s+\w+\s+\d{2,4}\s*-\s*\d{1,2}\s+\w+\s+\d{2,4}` (i.e., at least one posting column header exists)
- Column C of row 3+ contains MCR-like values (pattern: letter + digits + letter, e.g. `M12345A`)

If a sheet matches both criteria → parse as a standard resident sheet.

**SSR sheet** (different structure):
- Does NOT have date-range headers in row 2
- Column headers include `SSR` or `Sub-Specialty` in row 1 or 2, OR the sheet name contains `SSR`

If a sheet matches the SSR pattern → parse via the SSR-specific parser.

**Skip sheets** that match neither pattern (e.g. lookup/reference sheets, empty sheets, cover pages).

```python
def detect_rdb_sheets(workbook) -> dict[str, str]:
    """
    Returns dict mapping sheet_name → sheet_type ('standard' | 'ssr' | 'skip')
    """
    result = {}
    for name in workbook.sheetnames:
        ws = workbook[name]
        row2_values = [str(ws.cell(2, c).value or '') for c in range(1, 25)]
        has_date_range = any(
            re.search(r'\d{1,2}\s+\w+\s+\d{2,4}\s*-\s*\d{1,2}\s+\w+\s+\d{2,4}', v)
            for v in row2_values
        )
        if has_date_range:
            result[name] = 'standard'
            continue
        sheet_name_upper = name.upper()
        row1_values = [str(ws.cell(1, c).value or '').upper() for c in range(1, 10)]
        if 'SSR' in sheet_name_upper or any('SSR' in v or 'SUB-SPECIALTY' in v for v in row1_values):
            result[name] = 'ssr'
            continue
        result[name] = 'skip'
    return result
```

### Sheet Structure

- **Row 1:** Month labels (`Jul-25`, `Aug-25`, ..., `Jun-26`)
- **Row 2:** Column headers with date ranges (e.g. `08 Jul 25 - 03 Aug 25`) — detected dynamically
- **Rows 3+:** Resident data

### Resident Row Stop Marker

When parsing standard RDB sheets, stop resident-row parsing once any cell in a row contains `Please do not insert any row beyond this red line` case-insensitively.

Rows below this marker are legend/reference rows and must not produce:
- residents
- resident_postings
- posting_codes
- upload warnings

This stop marker takes priority over any parseable-looking values below the red line.

### Column Mapping

| Column | Field | Notes |
|--------|-------|-------|
| A | employee_code | |
| B | name | |
| C | mcr | Primary identifier |
| D | classification | `Junior Resident` or `Senior Resident` |
| E | base_institution | May be `-` |
| F | r_year | `R1`..`R7` — may be remapped for subspecialty programmes (see § R Year Handling) |
| G | specialization | Maps to programme_code via `programmes` table lookup (with alias normalisation) |
| H | reg_type | `Full` or `Conditional` |
| I–T | posting per month | 12 month-phase columns (detected dynamically — do NOT assume fixed column range) |

### Date Range Extraction

Column headers in row 2 contain date ranges like `08 Jul 25 - 03 Aug 25`. Parse these to get `start_date` and `end_date` for each month-phase.

```python
def parse_date_range(header: str) -> tuple[date, date]:
    """Parse '08 Jul 25 - 03 Aug 25' or '8 Jul 2025 - 3 Aug 2025' into (date, date)"""
    match = re.match(r'(\d{1,2}\s+\w+\s+\d{2,4})\s*-\s*(\d{1,2}\s+\w+\s+\d{2,4})', header)
    if not match:
        raise ValueError(f"Cannot parse date range: {header}")
    for fmt in ['%d %b %y', '%d %b %Y']:
        try:
            start = datetime.strptime(match.group(1).strip(), fmt).date()
            end = datetime.strptime(match.group(2).strip(), fmt).date()
            return start, end
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date range with known formats: {header}")
```

### Programme Code Resolution

Programme codes are resolved by querying the `programmes` table at parse time. The `rdb_alias` column on `programmes` handles cases where the RDB uses an alternative programme name.

```python
def resolve_programme_code(raw_specialization: str, programme_lookup: dict) -> str | None:
    """
    programme_lookup: dict mapping both programme.code and programme.rdb_alias → programme.code
    Built at parser startup from: SELECT code, name, rdb_alias FROM programmes
    """
    # Direct code match (e.g. 'DR', 'GERI')
    if raw_specialization in programme_lookup:
        return programme_lookup[raw_specialization]
    # Alias match (e.g. 'Infectious Disease' → 'ID')
    if raw_specialization in programme_lookup:
        return programme_lookup[raw_specialization]
    return None  # Unknown — warn in upload response
```

**Known RDB alias normalisations (seeded in `programmes.rdb_alias`):**

| RDB value | Normalises to |
|-----------|--------------|
| `Infectious Disease` | `ID` |
| `Renal Medicine Extended` | `RENAL` |
| `Surgery-in-General` | `SIG` |
| `Microbiology` | `MICROB` |

### R Year Handling

After resolving the programme code, apply r_year logic based on the programme's configuration flags:

```python
def resolve_r_year(raw_r_year: str, programme: Programme) -> str:
    """
    Returns the normalised r_year to store on resident_postings.
    """
    if not programme.r_year_required:
        # Programme does not differentiate by r_year — use sentinel
        return 'ALL'

    if programme.is_subspecialty:
        # Apply subspecialty remapping
        SS_MAP = {'R4': 'SS1', 'R5': 'SS2', 'R6': 'SS3'}
        return SS_MAP.get(raw_r_year, raw_r_year)

    return raw_r_year
```

**r_year_required = false (22 programmes — use 'ALL'):**
AIM, CARDIO, EM, ENDO, ENT, EYE, GASTRO, GERI, GS, ID, IM, MEDONCO, ORTHO, PATH, REHAB, RENAL, RHEUM, SPORTSMED, SIG, URO, MICROB, PALLMED

**r_year_required = true (6 programmes — use actual r_year):**
ANAES, DERM, DR, FM, PSY, RESPI

**is_subspecialty = true (2 programmes — apply remapping):**
SPORTSMED (R4→SS1, R5→SS2), PALLMED (R4→SS1, R5→SS2)

### Posting Cell Parsing

Each cell in the posting columns can be one of the following variants:

**1. Simple posting code:**
```
TTSHAnaes
```
→ `posting_code = "TTSHAnaes"`, `status = "active"`

**2. Empty cell:**
```
(blank)
```
→ Skip. Resident has no posting this month.

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
TTSHGenMed
LOA (Maternity Leave from 30-Aug-2025 to 31-Aug-2025)
```
→ `posting_code = "TTSHGenMed"`, `status = "loa_working"`, parse LOA dates from second line

**5b. Multiline hybrid (Continue working + pure LOA on separate lines):**
```
TTSHAnaes (Continue working during LOA from 02-Jun-2026 to 02-Jun-2026)
LOA (Maternity Leave from 03-Jun-2026 to 06-Jul-2026)
```
→ `posting_code = "TTSHAnaes"`, `status = "loa_working"`, loa dates taken from the pure LOA line

**6. Pending SR promotion:**
```
TTSHEmgMed (Pending for SR Promotion from 06-Apr-2026 to 03-May-2026)
```
→ `posting_code = "TTSHEmgMed"`, `status = "active"`, store promotion annotation. **This is a cell annotation — NOT a loa_type.**

**7. Employed posting:**
```
SAF-Employed, SCDF-Employed, KTPH-Employed, NCIS-Employed, SGH-Employed,
NUH-Employed, TTSH-Employed, Assisi-Employed, NCCS-Employed
— and any future XXX-Employed variants
Detection: re.match(r'^[\w]+-[Ee]mployed$', val)
```
→ `posting_code = NULL`, `status = "employed"`, `employer_tag = val.split('-')[0]` stored on residents table. No resident_postings row created.

**8. Numeric values (FM polyclinic numbers):**
```
1, 2, 3, ... 270
```
→ These appear in the FM sheet. Store as posting_code string. These correspond to `NHGPlyNHGPly` in the main posting system.

**9. Refresher Training:**
```
PostingCode (Refresher Training (add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)
PostingCode (Refresher Training (don't add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)
```
→ `posting_code = "PostingCode"`, `status = "active"`, store refresher_training_type, refresher_training_start, refresher_training_end. **This is a cell annotation — NOT a loa_type.**

**10. Multi-posting cell with explicit date ranges and AM/PM granularity:**

This cell variant contains multiple posting codes each with their own explicit date range fragments, including half-day AM/PM granularity:

```
NUHPaedia
(from 08-Jul-2025 to 09-Jul-2025 )
(from 10-Jul-2025 to 10-Jul-2025 AM)
(from 11-Jul-2025 to 11-Jul-2025 )
NHGPlyNHGPly
(from 10-Jul-2025 to 10-Jul-2025 PM)
(from 12-Jul-2025 to 12-Jul-2025 )
```

**Parsing algorithm for multi-posting cells:**

1. Split cell on newlines
2. Identify posting code lines: lines that are not `(from ...)` patterns and are not empty
3. For each posting code line, collect all subsequent `(from DD-MMM-YYYY to DD-MMM-YYYY [AM|PM])` lines until the next posting code line
4. Aggregate total date ranges per posting code
5. Look up explicit `multi_posting_rules` rows for this programme + posting code combination. Explicit `combine`, `half_month`, and two-code `main_posting` rules take priority.
6. Apply the matching explicit rule type:
   - `combine` → create one `resident_postings` row with `combined_label` as posting_code
   - `half_month` → create two rows each with `active_months_weight = 0.5`
   - explicit `main_posting` with both `posting_code_1` and `posting_code_2` → collapse to `main_posting_code`
7. If no explicit rule matched and `programme_code = 'FM'`, apply the FM main-posting trigger-list semantics:
   - Count how many distinct posting codes in the cell appear as `RDB Posting #1` / `posting_code_1` in FM `main_posting` rows where `posting_code_2 IS NULL`.
   - Exact one recognised posting → collapse the whole cell to that row's configured `main_posting_code`.
   - Zero recognised postings → collapse the whole cell to the configured `exclusion_code` from the FM `main_posting` seed rows, usually `NHGPlyNHGPly`.
   - Two or more recognised postings → do not infer. Persist each posting independently and emit `unmatched_multi_posting` unless an explicit rule exists.
8. If no matching rule found → create separate `resident_postings` rows for each posting code. Each posting is calculated independently for compliance. Active months use whole-month counting — a posting is credited a full calendar month for any month it appears in, regardless of how many days. No proration. Add a warning to upload response: `"unmatched_multi_posting": ["MCR=M12345A: TTSHCardio + TTSHAnaes — no combine/half_month/main_posting rule found. Compliance calculated independently per posting. Add a multi_posting_rule or posting_group if these should be combined."]`

**Note:** This multi-posting cell variant applies to ALL sheets — not FM only. Any RDB sheet (Phase 1 & 2, Phase 3, etc.) may contain cells with multiple posting codes and explicit date ranges.

**FM standalone NHGPly:** A singular `NHGPlyNHGPly` cell is a valid standalone posting. It is parsed as a normal simple posting, does not require `multi_posting_rules` lookup, and must not emit an `unmatched_multi_posting` warning.

**Unmatched warning workflow:** `unmatched_multi_posting` is an intentional PC review signal, not a parser failure. For non-FM unresolved combinations, and for ambiguous FM cells with two or more recognised main-posting triggers, the parser preserves independent rows and warns so PCs can either add a rule through Admin CRUD or correct the source RDB before reparsing.

Each `unmatched_multi_posting` warning payload must include workbook traceability fields for operational review:
- `type` = `unmatched_multi_posting`
- `mcr`
- `resident_name`
- `programme_code`
- `posting_codes`
- `month_label`
- `sheet_name`
- `row_number`
- `cell_ref` (preferred exact Excel cell coordinate, e.g. `J42`)
- `message`

### Final Product PC Review Workflow (documentation target)

After RDB upload, the Admin UI should present unmatched warnings in a review table with:
- Programme
- Resident
- MCR
- Month
- Sheet
- Row
- Cell
- Posting Combination
- Message / Suggested action

This table is for operational triage only. It helps PCs:
- identify the exact source RDB cell
- decide whether the source workbook needs correction
- add a rule via Multi-posting Rules CRUD (`Main Posting`, `To Combine Posting`, `Half Month Posting`) if the combination is valid
- re-upload/reparse RDB after correction

**Relationship to posting_groups:** `multi_posting_rules` governs how the RDB cell is **parsed** into `resident_postings` rows. `posting_groups` governs how compliance is **aggregated** across separate postings that were posted at independently. They are independent — a resident may have two clean separate `resident_postings` rows (no multi_posting_rule needed) but still have their compliance pooled via `posting_groups` if they served at both postings across the period.

**Note on trailing spaces:** LOA closing brackets in the new AY2025 RDB may contain trailing spaces before `)` (e.g. `LOA (Maternity Leave from 22-Aug-2025 to 31-Aug-2025 )`). The parser must strip trailing whitespace inside brackets before date parsing. Use `\s*\)` at the end of LOA regex patterns rather than `\)`.

**Note on date format variants:** Some cells use `DD - MMM - YYYY` with spaces around hyphens. Normalise before parsing: `re.sub(r'\s*-\s*', '-', date_str)`.

### LOA Type Validation

LOA types are validated against the `loa_types` reference table. If an unknown LOA type is found:
- Store the raw string in `loa_type` column
- Add a warning to the upload response: `"unknown_loa_types": ["Exam Leave"]`
- Do NOT reject the upload — unknown types are stored and flagged for admin review

**Confirmed LOA type seed list (14 types):**
- Annual Leaves
- Childcare Leave
- Compassionate Leave
- Family Care Leave
- Hospitalisation Leave
- Marriage Leave
- Maternity Leave
- Medical Leave
- National Service (NS)
- No-Pay-Leave
- Paternity Leave
- Training Leave
- Unrecorded Leave
- Unpaid Infant Care Leave

**Cell annotation types — NOT loa_type seed rows:**
The following strings appear in RDB cells but are handled as cell annotation/status types by the parser, NOT as `loa_types` entries:
- `Continue working during LOA` — sets `status = 'loa_working'`
- `Pending for SR Promotion` — sets `status = 'active'`, stores promotion annotation
- `Refresher Training (add to Max Cand)` — sets `refresher_training_type`, no compliance impact
- `Refresher Training (don't add to Max Cand)` — sets `refresher_training_type`, no compliance impact

### Cell Normalisation Before Parsing

Before classifying any posting cell, `rdb_parser.py` must normalise harmless Excel formatting drift:

- Preserve the raw original cell value for upload warnings and audit logs
- Convert `None` to an empty string
- Replace non-breaking spaces with normal spaces
- Normalise line endings (`\r\n`, `\r`) to `\n`
- Trim leading/trailing whitespace from the full cell and each line
- Remove empty lines after line-ending normalisation and trimming
- Collapse repeated internal whitespace only in parser-controlled tokens such as dates and annotation wrappers; do not alter posting codes, LOA type names, or free-text values used for audit/display
- Normalise date tokens with spaced hyphens:
  - `06 - Apr - 2026` → `06-Apr-2026`
  - `06- Apr-2026` → `06-Apr-2026`
- Allow trailing whitespace before closing brackets, e.g. `... 31-Aug-2025 )`

Normalisation must only fix syntax. It must not infer missing business intent.

Examples:
- `LOA (Maternity Leave from 22-Aug-2025 to 31-Aug-2025 )` is valid after trimming trailing whitespace.
- `TTSHAnaes (Continue working during LOA from 06 - Apr - 2026 to 03 - May - 2026 )` is valid after date normalisation.
- `Continue working during LOA ...` without an explicit posting code remains ambiguous and must emit a warning rather than inferring from adjacent cells.

### LOA Date Parsing

LOA dates use format `DD-MMM-YYYY` (e.g. `01-Sep-2025`). Also handle variants with spaces around hyphens.

```python
def parse_loa_annotation(cell_value: str) -> dict:
    result = {'status': 'active', 'loa_type': None, 'loa_start': None, 'loa_end': None}
    loa_match = re.search(
        r'LOA\s*\(([^)]*?)\s+from\s+([\d\s\-\w]+?)\s+to\s+([\d\s\-\w]+?)\s*\)',
        cell_value
    )
    if not loa_match:
        return result
    result['loa_type'] = loa_match.group(1).strip()
    start_str = re.sub(r'\s*-\s*', '-', loa_match.group(2).strip())
    end_str = re.sub(r'\s*-\s*', '-', loa_match.group(3).strip())
    result['loa_start'] = datetime.strptime(start_str, '%d-%b-%Y').date()
    result['loa_end'] = datetime.strptime(end_str, '%d-%b-%Y').date()
    if 'Continue working' in cell_value:
        result['status'] = 'loa_working'
    elif cell_value.strip().startswith('LOA'):
        result['status'] = 'loa'
    else:
        result['status'] = 'loa_working'
    return result
```

### Working Days Computation

At parse time, compute `working_days_in_month` for each `resident_postings` row:

```python
def compute_working_days(start_date: date, end_date: date, loa_start: date | None, loa_end: date | None) -> int:
    """
    Calendar days in phase minus LOA days.
    Does NOT exclude weekends or public holidays — hospital environment uses calendar days.
    """
    total_days = (end_date - start_date).days + 1
    if loa_start and loa_end:
        # Clip LOA range to the phase
        overlap_start = max(loa_start, start_date)
        overlap_end = min(loa_end, end_date)
        if overlap_start <= overlap_end:
            loa_days = (overlap_end - overlap_start).days + 1
            total_days -= loa_days
    return max(0, total_days)
```

This value is stored on `resident_postings.working_days_in_month` but is not currently used for compliance — it is stored for future use if the architectural decision shifts from FormF1 to RDB-derived active/inactive.

### SSR Sheet

The SSR (Sub-Specialty Registrar) sheet has a different structure: MCR, Name, SI, Specialty, residency end date, SSR start date, interim posting. Parse separately — these are residents who have completed residency and are in an interim posting.

### Processing Order

1. Parse all sheets, collect resident data and posting schedules
2. Load `programmes` table (with `r_year_required`, `is_subspecialty`, `rdb_alias` flags) into memory for lookup
3. Upsert `posting_codes` table from distinct posting codes found
4. Upsert `residents` table (keyed by MCR) — `residents.r_year` is updated to the value in column F for display only. Do not use it for compliance target lookup.
5. **Delete** existing `resident_postings` rows for the reporting period (scoped to residents present in this upload)
6. For each resident, for each posting cell:
   - Resolve programme code via `programmes` table (with alias normalisation)
   - Apply `resolve_r_year()` based on `r_year_required` and `is_subspecialty` flags
   - Apply multi-posting rule lookup from `multi_posting_rules` table
7. Insert `resident_postings` rows with resolved `r_year` per row
8. Compute and store `working_days_in_month` per row
9. Call `hibernate_stale_surplus()` after insert

---

## TTF Parser

**Upload slot:** Admin uploads via the dedicated **Teaching Target File (TTF)** file input on the admin upload page. The upload form also requires a **programme selector** (e.g. DR, GRM) — this is a required parameter alongside the file. The filename is not used for parsing.
**Accepted format:** `.xlsx` only
**Sheets:** Dynamic — detect the first sheet that contains valid TTF data (see § Sheet Detection below). Do NOT hardcode `Sheet1`.
**Trigger:** `POST /admin/upload/ttf` with `reporting_period_id` and `programme_code`

### TTF Sheet Detection

Iterate over all sheets in the workbook. The first sheet where:
- Row 1 contains expected column headers (columns A–K contain header-like text)
- At least one data row (row 2+) has a non-empty value in column B that matches a known `programme_code` format

...is treated as the data sheet. All other sheets are skipped.

```python
def detect_ttf_sheet(workbook) -> str | None:
    for name in workbook.sheetnames:
        ws = workbook[name]
        col_b_row2 = str(ws.cell(2, 2).value or '').strip()
        col_a_row2 = str(ws.cell(2, 1).value or '').strip()
        if col_b_row2 and col_a_row2 and not re.search(r'\d{4}', col_b_row2):
            return name
    return None
```

### Column Mapping

| Column | Field | Notes |
|--------|-------|-------|
| A | reporting_period | e.g. `Jan - June` — validated against reporting_periods table |
| B | programme_code | e.g. `DR`, `GERI` |
| C | r_year | Single (`R2`) or multi (`R4, R5, R6`) — must be exploded. Set to `'ALL'` for programmes with `r_year_required = false`. |
| D | posting_code | Bare code (e.g. `KTPHDiagRd`) or legacy bracket format |
| E | dashboard_posting | Compliance grouping key. When non-empty, this value seeds `posting_groups.group_code`; the resolved Column D posting code becomes `posting_groups.            posting_code`. All posting codes sharing the same Column E value and programme are aggregated under that group for active-month counting, `target_100`, `target_70`, posting-level percentage, shortage, and clawback. When empty, no posting group row is created and the posting remains standalone under its resolved Column D posting code. |
| F | session_type | Full name with duration, e.g. `Department/Programme Teaching [1h]` |
| G | monthly_target | Integer frequency target at 100% |
| H | is_tracked | `Yes` → true, anything else → false |
| I | is_reallocatable | `Y` → true, anything else → false |
| J | tag | Reallocation group label, e.g. `A`, `B`. Empty = no reallocation |
| K | details_of_training | Comma-separated keywords (e.g. `Journal Club, Grand Round, M&M`). Each `(keyword, duration)` combination must map to exactly one session type within a posting per programme. |

### TTF Column E — Posting Group / Dashboard Posting

Column E is not display-only. It is the source of `posting_groups`.

For each TTF row:
- Column D remains the posting code used by `teaching_targets` and `teaching_name_catalogue`.
- Column G remains the monthly target for that specific Column D row.
- If Column E is non-empty, create/upsert a `posting_groups` row:
  - `group_code = Column E`
  - `posting_code = resolved Column D`
  - `programme_code = TTF programme`
- If Column E is empty, do not create a `posting_groups` row.

Compliance impact:
- Events/attendance still match through the actual posting code from Column D.
- Each posting keeps its own TTF monthly target from Column G.
- During compliance calculation, postings sharing the same `group_code` are aggregated.
- Active months, `target_100`, `target_70`, posting-level percentage, shortage, and clawback are calculated on the grouped basis.

### Duration Extraction from Session Type Name

Duration is embedded in the session type name. No separate TTF duration column.

```python
def parse_session_type(name: str) -> tuple[str, float]:
    """Returns (name, duration_hours)"""
    match = re.search(r'\[(\d+(?:\.\d+)?)h\]', name)
    if match:
        return name.strip(), float(match.group(1))
    return name.strip(), 0.0
```

### Secretary Event Creation — end_time Computation

Secretary picks `start_time` only. `end_time` is server-computed:
```python
end_time = start_time + timedelta(hours=session_type.duration_hours)
```
`end_time` is never a request body field on the secretary event creation endpoint.

### Multi-Year Row Explosion

Column C may contain comma-separated years: `R4, R5, R6`. Each becomes a separate `teaching_targets` row.

```python
def explode_r_years(r_year_str: str, programme: Programme) -> list[str]:
    if not programme.r_year_required:
        return ['ALL']
    years = [y.strip() for y in r_year_str.split(',') if y.strip()]
    if programme.is_subspecialty:
        SS_MAP = {'R4': 'SS1', 'R5': 'SS2', 'R6': 'SS3'}
        return [SS_MAP.get(y, y) for y in years]
    return years
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
→ Extract code from last bracket: `AICAIC`. RDB posting code is the canonical standard — the last `[]` bracket in the TTF posting column equals the RDB posting code.

**Dual-posting with `&` (combined posting):**
```
PsyG [] [IMHGrPsyc & TTSHPsychi]
```
→ This is a combined posting label. Store as-is as the posting_code. The combined label (e.g. `IMHGrPsyc & TTSHPsychi`) must exist as a row in `posting_codes` — add it if not present. Do NOT explode into two separate TTF rows.

```python
def parse_posting_code(raw: str) -> str:
    raw = raw.strip()
    bracket_match = re.search(r'\[([^\]]+)\]\s*$', raw)
    if bracket_match:
        return bracket_match.group(1).strip()
    return raw
```

### Validation Rules

Before inserting, validate:

1. `programme_code` matches a known programme
2. Each posting code exists in `posting_codes` table (or add it as a new dormant code with display_name = NULL)
3. `monthly_target` is a positive number
4. `session_type` name contains a duration bracket `[Xh]`
5. No duplicate `(reporting_period_id, programme_code, r_year, posting_code, session_type_id)` after explosion
6. If `is_reallocatable = true`, `tag` must not be empty
7. If `tag` is set, there must be at least one other row at the same posting with the same tag
8. **Keyword deduplication:** For each keyword in `details_of_training`, the `(keyword, duration_hours)` combination must map to exactly one session type within the same `(posting_code, programme_code)`. If the same keyword appears under two different session types with the same duration at the same posting, reject the upload with a descriptive 422 error.
9. **Tag order vs duration warning (not block):** For each tag group at a posting, check that tag label alphabetical order aligns with duration descending (e.g. `A1` should map to longer duration than `A2`). If misaligned, add a warning to the upload response: `"tag_order_warnings": ["Posting TTSHGerMed: tag A1 maps to [1h] but A2 maps to [2h] — reallocation will flow A1→A2, which is shorter→longer. Verify tag assignment is intentional."]`. Upload still proceeds.

### Column E — Posting Groups

When column E ("For Dashboard (RDB Posting/Subspeciality)") is non-empty for a TTF row:
- The value is a `group_code` for compliance aggregation
- Upsert a `posting_groups` row: `group_code = column_E_value`, `posting_code = column_D_posting_code`, `programme_code = from TTF`
- This groups `TTSHRespi` and `TTSHRespi(MICU)` under the same compliance aggregate when both have `TTSHRespi` in column E

```python
def seed_posting_groups(ttf_row: dict, db_session):
    """Called for each TTF row where column E is non-empty."""
    dashboard_posting = ttf_row.get('dashboard_posting')  # column E
    rdb_posting = ttf_row['posting_code']                  # column D (resolved)
    if dashboard_posting and dashboard_posting.strip():
        db_session.execute(
            text("""
                INSERT INTO posting_groups (group_code, posting_code, programme_code)
                VALUES (:group_code, :posting_code, :programme_code)
                ON CONFLICT (posting_code, programme_code) DO UPDATE
                  SET group_code = EXCLUDED.group_code
            """),
            {
                'group_code': dashboard_posting.strip(),
                'posting_code': rdb_posting,
                'programme_code': ttf_row['programme_code']
            }
        )
```

### Upload Behaviour

The TTF upload is always a **full replace** within `(reporting_period_id, programme_code)` scope — regardless of whether attendance records exist. There is no attendance guard blocking re-uploads.

**Orphan detection (post-write):** After the delete-and-reinsert cycle, query for attendance records whose resolved session_type will no longer match any catalogue row. These are returned as warnings in the upload response — the upload still returns `200`.

**Concurrency:** A scope-level PostgreSQL advisory lock is acquired at the start of the transaction. A second upload for the same scope returns `409`.

#### Step order

1. Acquire scope-level advisory lock (409 if contended)
2. Validate all rows — abort before any writes if errors
3. `DELETE` all existing `teaching_targets` within scope
4. `DELETE` all existing `teaching_name_catalogue` rows within scope
5. `INSERT` into `teaching_targets`
6. Parse column K keywords and `INSERT` into `teaching_name_catalogue` — one row per keyword per TTF row. Non-tracked rows (`is_tracked = false`) are still seeded into `teaching_name_catalogue` for event visibility.
7. `ON CONFLICT DO NOTHING` into `session_types`
8. `ON CONFLICT DO UPDATE` into `posting_codes`
9. Upsert `posting_groups` from column E (where non-empty)
10. Commit
11. Run orphan detection — include results in response `warnings`

#### `ON CONFLICT` upserts

```sql
INSERT INTO session_types (id, name, duration_hours)
VALUES (:id, :name, :duration_hours)
ON CONFLICT (name) DO NOTHING;

INSERT INTO posting_codes (code, display_name)
VALUES (:code, :display_name)
ON CONFLICT (code) DO UPDATE
  SET display_name = COALESCE(posting_codes.display_name, EXCLUDED.display_name);

INSERT INTO posting_groups (group_code, posting_code, programme_code)
VALUES (:group_code, :posting_code, :programme_code)
ON CONFLICT (posting_code, programme_code) DO UPDATE
  SET group_code = EXCLUDED.group_code;
```

---

## FormF1 Parser

**Upload slot:** Admin uploads via the dedicated **Form F1** file input on the admin upload page. The filename is not used for parsing — the parser always targets the `Table 1` sheet by name.
**Accepted format:** `.xlsx` only
**Sheet:** `Table 1`
**Trigger:** `POST /admin/upload/form-f1` with `reporting_period_id`

### File Structure

- Rows 1–27: Header/legend content — skip entirely
- **Row 28:** Column headers
- **Row 29+:** Resident data

### Column Mapping

| Column | Field | Notes |
|--------|-------|-------|
| A | specialty | Raw specialty string |
| D | name | Resident name |
| E | mcr | Join key to residents.mcr |
| H | r_year | Year of residency |
| M–X | monthly status | 12 calendar months Jul–Jun |

Month columns M–X (0-indexed: 12–23) map to: Jul, Aug, Sep, Oct, Nov, Dec, Jan, Feb, Mar, Apr, May, Jun.

### Status Normalisation

| Raw value | is_active | Notes |
|-----------|-----------|-------|
| `Active` | true | Standard active |
| `Extension` | true | Always track — funding not allocated, clawback not exercised (`clawback_suppressed_reason = 'Extension'`) |
| `Inactive` | false | Excluded from both numerator and denominator |

**Exhaustive status list:** `Active`, `Inactive`, `Extension`. No other values are expected. Warn on any unrecognised value but do not fail the upload.

**When is_active = false:** The resident-month is excluded from both the compliance numerator and denominator. Sessions attended in that month are stored but not counted.

### Upload Behaviour

- Full replace per `reporting_period_id` scope
- Re-upload is allowed at any time (e.g. to handle unforeseen LOAs like maternity)
- Delete-and-reinsert within scope: `DELETE FROM form_f1_records WHERE reporting_period_id = :period_id`
- If MCR not found in `residents` table → add to warnings but do not fail upload
- Write `upload_logs` row with `upload_type = 'form_f1'`

### Parsing Logic

```python
def parse_formf1(file_path: str, reporting_period_id: str) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb['Table 1']

    MONTH_LABELS = ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
    # Columns M–X = indices 12–23 (0-based)
    MONTH_COL_OFFSET = 12

    records = []
    # Data starts at row 29 (1-indexed) = index 28 (0-indexed)
    for row_idx in range(28, ws.max_row):
        mcr = str(ws.cell(row_idx + 1, 5).value or '').strip()  # col E
        if not mcr or not re.match(r'[A-Z]\d+[A-Z]', mcr):
            continue
        for month_offset, month_label_prefix in enumerate(MONTH_LABELS):
            col = MONTH_COL_OFFSET + month_offset + 1  # 1-indexed
            raw_status = str(ws.cell(row_idx + 1, col).value or '').strip()
            if not raw_status:
                continue
            # Derive reporting year from period context — e.g. Jul-25 for AY2025
            year_suffix = '25' if month_offset < 6 else '26'  # adjust per period
            month_label = f"{month_label_prefix}-{year_suffix}"
            is_active = raw_status.lower() != 'inactive'
            records.append({
                'reporting_period_id': reporting_period_id,
                'mcr': mcr,
                'month_label': month_label,
                'status_raw': raw_status,
                'is_active': is_active,
            })
    return records
```

---

## Public Holiday File Parser

**Upload slot:** Admin uploads via the dedicated **Public Holidays** file input on the admin upload page. The filename is not used for parsing.
**Accepted formats:** `.xlsx` or `.csv`
**Format:** Three columns — `Date (dd-mmm-yy)` | `Day of Week` | `Public Holiday name`
**Trigger:** `POST /admin/upload/public-holidays`

### Parsing Logic

```python
def parse_public_holidays(file_path: str) -> list[dict]:
    """
    Parse PH file. Skip header row. Parse date from dd-mmm-yy format.
    Validate computed day-of-week matches uploaded day — warn if mismatch.
    """
    import pandas as pd
    from datetime import datetime
    import calendar

    df = pd.read_excel(file_path, header=0)
    records = []
    warnings = []

    for _, row in df.iterrows():
        raw_date = str(row.iloc[0]).strip()
        uploaded_day = str(row.iloc[1]).strip() if len(row) > 1 else ''
        ph_name = str(row.iloc[2]).strip() if len(row) > 2 else ''

        try:
            parsed_date = datetime.strptime(raw_date, '%d-%b-%y').date()
        except ValueError:
            try:
                parsed_date = datetime.strptime(raw_date, '%d-%b-%Y').date()
            except ValueError:
                warnings.append(f"Cannot parse date: {raw_date}")
                continue

        computed_day = calendar.day_name[parsed_date.weekday()]
        if uploaded_day and computed_day.lower() != uploaded_day.lower():
            warnings.append(
                f"Day mismatch for {raw_date}: file says {uploaded_day}, "
                f"computed {computed_day}. Using computed date — verify the row."
            )

        records.append({
            'holiday_date': parsed_date,
            'name': ph_name,
            'day_of_week': computed_day,
            'year': parsed_date.year,
        })
    return records, warnings
```

**Upload behaviour:** `INSERT ... ON CONFLICT (holiday_date) DO NOTHING` — safe to re-run. Write `upload_logs` row with `upload_type = 'public_holidays'`.

---

## Edge Cases

### RDB posting columns are not a fixed range
The parser detects posting columns dynamically by scanning row 2 for date-range headers. Do NOT assume columns I–T or any fixed column range.

### Empty cells in RDB posting columns
Skip — resident has no posting that month.

### Resident appears in multiple RDB sheets
Deduplicate by MCR — use the later sheet's data if there's a conflict.

### TTF frequency target of 0
Valid — session type exists at this posting but has no attendance requirement. Skip from compliance calculations.

### TTF "No" in Tracked column
The session type exists and events can be created, but attendance does NOT count toward compliance. The row is still seeded into `teaching_name_catalogue` so events are visible to residents. Both numerator and denominator exclude these sessions.

### Posting code with parenthetical suffix in RDB
Examples: `TTSHCardio (CCU)`, `TTSHRespir(MICU)`, `KTPHOrtSrg(SportsMed)`
These are distinct posting codes — store them as-is including the parenthetical. They are NOT the same as `TTSHCardio` or `TTSHRespir`.

### FM polyclinic numeric codes
The FM sheet contains numeric posting codes (1, 2, 3, ..., 270) for polyclinic sites. Store as strings.

### Overlapping date ranges for the same resident
After parsing all month-phase rows for a resident, check that no two rows overlap. Return as warnings in the upload response. The upload is NOT aborted — overlapping rows are inserted with a warning flag.

```python
def check_overlapping_phases(phases: list[dict], resident_mcr: str) -> list[str]:
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

### RDB re-upload (same reporting period)
Parser deletes existing `resident_postings` rows for residents present in the new file before inserting corrected rows. Residents not in the new upload are untouched.

### Dormant TTF posting codes
Posting codes that appear in the TTF but not in the current RDB are valid (dormant sites). Accept and add to `posting_codes` with `display_name = NULL`. Do not fail the upload. The canonical posting code is the RDB posting code — the last `[]` bracket in the TTF posting column.

### Multi-posting rule not found
If two or more posting codes appear in the same RDB cell and no matching rule is found in `multi_posting_rules`, create separate `resident_postings` rows for each posting code and include a warning in the upload response. For FM, first apply the exact-one / zero / two-or-more recognised main-posting trigger-list semantics above. Warnings are preserved for true unresolved combinations so PCs can add or adjust rules through Admin CRUD, or fix the RDB source and re-upload.

### Unknown programme in RDB
If `resolve_programme_code()` returns None for a specialization value (neither a known code nor a known alias), log a warning in the upload response and skip those rows. Do not fail the upload.
