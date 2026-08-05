# Phase 6-A — R Script-to-Compliance Specification Audit

Audit date: 2026-07-17; Phase 6-A decision reconciliation: 2026-07-20
Scope: specification audit only; no application, migration, test, source workbook, or R-script changes

## 1. Final Verdict

**NON-CLAWBACK SPECIFICATION RESOLVED; CLAWBACK DEFERRED**

The Phase 6-A ordinary compliance business logic is resolved at specification level. This reconciliation updates the source-of-truth documents for FormF1/AY boundaries, distinct-event overlap rejection, exact-type ORTHO mutation, the three multi-posting outcomes, native-programme attribution, explicit source/mapping identity, SPORTSMED/PALLMED R-years, mid-period R-year contexts, fractional-target status, raw-count tag reallocation, and persistent-surplus lifecycle.

This verdict makes **no claim that Phase 6 application code or tests are implemented**. Implementation and verification remain future work. The legacy evidence and defect descriptions below are retained so known legacy defects—especially reusable donor supply, duplicated R-year months, formatted clawback triggering, and temporary in-memory transfer behavior—are not reproduced.

### Evolved TTF transition notice (2026-08-02)

The Column K/catalogue references in this audit describe preserved historical
evidence only. They do not define the final evolved TTF. The implemented E2+B2
cutover at revision `20260805_000036` is A-J only and uses Teaching Name pools
and exact mappings; a populated legacy Column K in a final-format upload
receives controlled `422`, with no dual format, backfill, or historical-data
migration. The former additive-B1 catalogue, `details_of_training`, and parser
structure are historical. This notice adds no Phase 6 implementation claim.

Unless a paragraph is explicitly labelled historical, the final event-source
contract is the persisted `teaching_name_id` or `global_session_type_id` (or
deterministic persisted evidence for a both-null legacy row). References below
to a catalogue, keyword, or Column K are legacy-analysis terminology, not a
live parser, event, attendance, or API contract. A future Phase 6 resolver must
use that source evidence and scoped mappings, never display-text matching.

Clawback remains explicitly **DEFERRED** and separate from ordinary compliance readiness. Norm rates/effective dating, funding R-year, financial programme classification, Extension/R7/SAF/SCDF suppression granularity/precedence, grouped-posting identity, billing attribution, missing-rate behavior, rounding/precision, and final-close transaction/rerun/idempotency are unresolved and must not be inferred from legacy scripts.

## 2. Scope and Sources Reviewed

### 2.1 Authority applied

The audit used the requested authority model:

- exact legacy behavior: the `.R` files;
- compliance/surplus/exceptions/clawback: `docs/business-logic.md`;
- persistence: `docs/schema.md`;
- API semantics: `docs/api.md`;
- upload parsing: `docs/parsing.md`;
- confirmed global conventions: `AGENTS.md`;
- navigation only: `docs/00_project_context.md`;
- secondary history only: `docs/99_decision_log_and_gap_audit.md`;
- secondary migration summary only: `MATA R Scripts/MATA_Core_Business_Logic_Audit.docx`.

No existing backend behavior was treated as authority. Frontend code and unrelated repository directories were not inspected.

### 2.2 R scripts inspected

| Relative path | Label | Purpose established from code | Inputs | Outputs | Compliance role |
|---|---|---|---|---|---|
| `MATA R Scripts/A/A_Masterfiles v3.R` | A | Builds programme, PH, FormF1, RDB phase, R-year, billing, multi-posting, CME, and TTF master objects | Dynamically selected general-settings, programme, PH, FormF1, RDB/billing, R-year, replacement, CME, and TTF workbooks | `A1_Masterfiles.rds` and period master RDS | Indirect, essential input transformation |
| `MATA R Scripts/B/B_Data collection and cleaning v4.R` | B | Parses FormSG, resolves identity/month/posting/R-year/session, applies exclusions, duplicates, PH/weekend rules, and native/non-native split | A RDS, FormSG CSVs, optional dashboard-error RDS/workbooks | B data RDS, error RDS, CME workbook | Determines attendance eligibility |
| `MATA R Scripts/C/C_Data preparation v3.R` | C | Synthesizes zero-achievement target rows; counts, caps, reallocates, aggregates, calculates thresholds/shortages | A and B RDS | C data RDS, all-data/log workbooks | Direct compliance engine |
| `MATA R Scripts/D/D1_Generate programme reporting view v2.R` | D1 | Reshapes C outputs into programme workbooks and applies submission-error formatting | A/B/C RDS, external Excel templates | Programme Reporting View and consolidated attendance | `NOT_COMPLIANCE_RELEVANT` report/export only |
| `MATA R Scripts/D/D2_Generate resident dashboard v2.R` | D2 | Writes resident dashboard/access workbooks; rounds displayed percentages upward to two decimals | A/B/C RDS, external dashboard templates | Resident dashboards/access list | `NOT_COMPLIANCE_RELEVANT` to engine; display behavior recorded in F-20 |
| `MATA R Scripts/E/E_Clawback v1.R` | E | Selects failing posting rows, selects norm rates, prorates by active months, applies a billing-derived SAF/SCDF filter | A/C RDS, two missing reporting-view templates, clawback template | Dated clawback workbook | Direct clawback calculation |
| `MATA R Scripts/F/F1_Preparation for NEW period v1.R` | F1 | Copies current inputs and creates the next CME directory in June/December | A RDS and legacy filesystem | Next-period files/directories | `NOT_COMPLIANCE_RELEVANT` operational rollover only |
| `MATA R Scripts/F/F2_Archiving v1.R` | F2 | Operator-gated copy/delete archive of legacy files and dashboards | A RDS and legacy filesystem | Archived filesystem state | `NOT_COMPLIANCE_RELEVANT`; no close/freeze math |

This is an eight-file implementation, not literally “six scripts.” A–F are six stage labels; D and F each contain two scripts.

### 2.3 Supporting files inspected

| Artifact | Inspection and relevance |
|---|---|
| `MATA R Scripts/MATA_Core_Business_Logic_Audit.docx` | Fully extracted in memory, including 8 tables; audited separately in section 8 |
| `MATA R Scripts/Script documentation.docx` | Secondary A/B object/data-flow notes |
| `MATA R Scripts/Script documentation ver3.docx` | Secondary master-file mapping notes |
| `MATA R Scripts/Script documentation ver2.xlsx` | `Script A` sheet, 24 rows, no formulas; secondary variable inventory |
| `MATA R Scripts/Duplicate or overlap.xlsx` | Six duplicate/overlap scenarios, no formulas; supports B’s adjacency behavior |
| `MATA R Scripts/A/A1_Masterfiles.rds` | Read-only object inventory; same bytes as period master; 41 objects |
| `MATA R Scripts/A/A1_(Jan-Jun26) Masterfiles.rds` | Read-only object inventory; 41 objects, including 935 TTF rows |
| `MATA R Scripts/A/A1_Masterfiles next.rds` | Read-only object inventory; different snapshot, 915 TTF rows |
| `MATA R Scripts/B/B1_(Jan-Jun24) Datafile.rds` | Historical B-stage contract inspected structurally |
| `MATA R Scripts/B/B1_(Jan-Jun26) Datafile.rds` | Read-only object inventory; 9 objects |
| `MATA R Scripts/B/B1_(Jan-Jun26) Error code from Resident Dashboard.rds` | Read-only object inventory; legacy feedback-loop artifact |
| `MATA R Scripts/C/C1_(Jan-Jun24) Datafile.rds` | Historical C-stage contract inspected structurally |
| `MATA R Scripts/C/C1_(Jan-Jun26) Datafile.rds` | Read-only object inventory; 7 objects and current output shapes |
| `MATA R Scripts/.Rhistory` | 72 lines; no compliance rule evidence |
| `MATA R Scripts/A/.Rhistory` | Empty; no rule evidence |

RDS inspection was structural and aggregate-only; no resident-level contents are reproduced in this report. The read-only inventory loaded each artifact without saving it and inspected object names, `length`/`nrow` dimensions and file identity only. It confirmed that the producing/consuming object contracts in A–E are real and that the current C snapshot contains posting, session-type, and reallocation outputs.

### 2.4 Markdown documents inspected

- `AGENTS.md`
- `docs/00_project_context.md`
- `docs/business-logic.md`
- `docs/schema.md`
- `docs/api.md`
- `docs/parsing.md`
- `docs/99_decision_log_and_gap_audit.md`

### 2.5 Unavailable dependencies limiting exact legacy verification

The scripts reference files not present beneath `MATA R Scripts/`, including:

- `REPORTING VIEW/R year mapping file_v2.xlsm`;
- `Scripts general settings.xlsx` and dynamically discovered programme/configuration workbooks;
- the operative PH, FormF1, RDB, billing, posting-replacement, CME, and per-programme TTF workbooks;
- `Template-Programme Reporting View-Single Others.xlsx`;
- `Template-Programme Reporting View-Single FM.xlsx`;
- programme/resident dashboard templates and the clawback output template.

Consequences:

- exact legacy norm-rate values and the semantic labels of positional rate cells cannot be proven;
- template-resident green/amber/red formulas and styles cannot be proven from R code;
- the R code proves positional rate selection and calculation order, not the business meaning or current value of the missing cells.

These are `LEGACY_AMBIGUITY` findings. They do not weaken the current Markdown traffic-light rule, but the missing financial inputs block clawback implementation.

## 3. Legacy Pipeline Map

### 3.1 Data lineage

```text
External master/config workbooks
        |
        v
A_Masterfiles v3.R
  -> A1_Masterfiles.rds
        |
        +------------------------------+
        v                              |
B_Data collection and cleaning v4.R   |
  -> B1_<period> Datafile.rds          |
        |                              |
        v                              |
C_Data preparation v3.R <-------------+
  -> C1_<period> Datafile.rds
        |
        +--> D1 programme reports (format/export)
        +--> D2 resident dashboards (format/export; upward display rounding)
        +--> E clawback (actual financial calculation; reads rates from templates)

F1 copies next-period inputs; F2 archives files. Neither calculates compliance or clawback.
```

### 3.2 Exact responsibility map

| Transformation | Actual source |
|---|---|
| Resident/programme/RDB phase, FormF1 status, posting-start R year, PH list, TTF target master | A: `83-137`, `149-226`, `241-319`, `400-645`, `790-860` |
| Legacy AY/posting-month bucket for an attendance date | B: `130-166` (inclusive boundaries) |
| Attendance posting | B: `(MCR, programme, posting month)` plus explicit event-date phase match at `225-299`; FormSG posting is not authoritative |
| Attendance R year | B: event-date comparison against the external mapping at `512-578` |
| Attendance filtering | B: future/feedback/error/PH/weekend/duplicate/non-resident blocks at `744-1059` |
| Session unit | B emits one row per teaching; C `table(...)` counts rows at `93-106` |
| Target/session resolution | C: programme + R-year substring + normalized posting + normalized session type at `113-180`; first match wins |
| Missing zero-attendance denominator rows | C: `184-280` |
| Active months | C: unique posting-month prefixes per dashboard posting at `286-295`; exact `Status == "Active"` at `63-64` |
| GASTRO split | C: deduct 0.5 posting active month at `299-319`; separately halve monthly-display target at `342-363` |
| Tracked filter | C: `321-326` |
| Monthly display cap | C: `365-374` |
| Period posting/session `target_100`, per-session `target_70`, initial cap | C: `380-395` |
| Tag reallocation | C: raw `Achieved`, lexical `order(Tag)`, all-but-last-char prefix, raw-minus-per-session-`target_70` supply at `399-497` |
| Final recap | C: `499-506` |
| Posting aggregation and percentage | C: `512-533` |
| Posting `target_70` and shortage | C: `535-549` |
| Report generation | D1/D2; D2 applies `ceiling(x * 100) / 100` for display at `186-201` |
| Clawback | E: trigger `36-41`, FormF1 R-year overwrite `43-59`, rate branch/formula `64-90`, first-month billing lookup and billing-derived SAF/SCDF filter `129-140` |
| Rollover/archive | F1/F2 only; no calculation or frozen snapshot |

### 3.3 Important chained-expression results

1. C calculates an initial `achieved_and_counted = min(raw, target_100)`, but tag logic mutates **raw `Achieved`**, not that capped column, and C caps again afterward. Reading only the first cap produces the wrong legacy behavior.
2. C’s `bringover[d]` is never decremented. The code therefore permits a donor balance to be reused for multiple recipients. This is a legacy bug, not a rule to port.
3. C computes posting percentage against summed `target_100`, then overwrites the exported column with `ceiling(sum(target_100) * .70)` and renames it `Target70`. The denominator remains the original target, not the renamed column.
4. E’s trigger calls `format(percentage, digits = 2)` before `< 0.7`; this is significant-digit formatting and can omit a raw failure near 70%. Current logic must never use this report artifact; the unformatted canonical predicate must be the one selected under F-10/BD-05.
5. E overwrites C’s phase-derived R year with FormF1 column 8 before rate lookup. Current FormF1 persistence deliberately has no R-year field, so a new funding-year rule is required rather than copying E blindly.

### 3.4 D/F operational and presentation details

These details were inspected so report/file behavior is not mistaken for calculation behavior:

- D1 hides all-empty monthly columns and R-year fields for programmes configured not to use R year (`D1:358-372`). It writes C’s already-calculated tables; this is `NOT_COMPLIANCE_RELEVANT` presentation logic.
- D2 hides the R-year dashboard row for no-R-year programmes (`D2:203-205`) and hides trailing attendance rows (`D2:273`). Its upward percentage rounding at `186-201` is presentation-only (F-20).
- F1 runs its copy/setup blocks only when the system month is June or December and only when the next-period file/directory does not already exist (`F1:26-58`). Its 1H existence check at `30` searches the current `chooseay` plus `2H`, while the destination at `31` always increments the AY before appending `2H`; this mismatch can create or skip the wrong “next” master copy. It is a `NOT_COMPLIANCE_RELEVANT` rollover defect, not a compliance rule.
- F2 sets `confirmanot <- "No"`, disabling its main master/data/report archive blocks unless an operator edits the script, while `turnononlyforresdashboard <- "Yes"` leaves resident-dashboard archiving active (`F2:20-21`). Master-file archive is additionally limited to `whichH == "2H"` (`23-36`). Copy success is not checked before deletion, and the initial resident-archive directory block references `proglist[i]` before that loop initializes `i` (`117-121`). These are legacy operational defects, not final-close/freeze semantics, and are `NOT_COMPLIANCE_RELEVANT` to Phase 6 math.

## 4. Rule Coverage Matrix

The following matrix supersedes the original pre-decision matrix. `Resolved` means the non-clawback source-of-truth specification is deterministic; it does not mean code or tests exist. `Deferred` is reserved for clawback/final-close rules.

| Rule area | Legacy evidence | Confirmed MATA behavior | Classification | Current status |
|---|---|---|---|---|
| Session unit | B/C count attendance rows | One session equals one; hours never multiply or transfer | `EXACT_MATCH` | Resolved |
| FormF1/AY gate | Legacy calendar/AY paths conflicted | AY bucket label selects one calendar-month FormF1 status for numerator and denominator | `INTENTIONAL_OVERRIDE_RESOLVED` | Resolved |
| Capping and R-year grain | C capped rows but duplicated posting-wide months across R-years | Target/cap each physical-posting/session-type/R-year context separately, then sum | `LEGACY_DEFECT_SUPERSEDED` | Resolved |
| Fractional status | Legacy ceil target and percentage artifacts could disagree | Unrounded posting percentage is canonical; `target_70` is display-oriented | `INTENTIONAL_OVERRIDE_RESOLVED` | Resolved |
| Tag reallocation | C transfers raw counts then recaps but reuses donor supply | Transfer raw one-for-one counts before caps within physical posting/R-year context/prefix; decrement supply; no cross-posting transfer | `LEGACY_DEFECT_SUPERSEDED` | Resolved |
| Persistent surplus | Legacy had temporary `bringover`, no ledger | Idempotent pre-tag raw-minus-target derived state; never add to attendance | `DOCUMENTED_NEW_BEHAVIOR` | Resolved |
| Multi-posting | Legacy used workbook/string paths | Distinct main/combine/half outcomes; half-month factor once | `ARCHITECTURAL_TRANSLATION` | Resolved |
| Combined posting | Legacy combined labels fed combined targets | Use configured canonical combined code with TTF rows; no component results | `ARCHITECTURAL_TRANSLATION` | Resolved |
| Native-programme event | No direct legacy equivalent | Project approved outside event to one assigned-posting 1h session | `DOCUMENTED_NEW_BEHAVIOR` | Resolved |
| Source/mapping resolution | Legacy fuzzy/first-match behavior | Exact persisted source identity and scoped mapping; duplicate display names may remain distinct; no fuzzy match | `INTENTIONAL_OVERRIDE_RESOLVED` | Resolved |
| SPORTSMED/PALLMED | Previous docs made remap unreachable | R-year required, not subspecialty; store/use R4–R6 | `DOC_CONTRADICTION_RESOLVED` | Resolved |
| Overlapping events | Legacy adjacency behavior was fragile | Reject later overlapping submission; preserve earlier attendance | `INTENTIONAL_OVERRIDE_RESOLVED` | Resolved |
| ORTHO mutation | Legacy exact mutation/order evidence | Exact 3h type only; adjust time, project type, then Saturday window | `ARCHITECTURAL_TRANSLATION` | Resolved |
| Posting groups | Legacy dashboard aggregate | Aggregate after physical-posting transfer/caps; no cross-posting transfer | `ARCHITECTURAL_TRANSLATION` | Resolved |
| Resident/admin parity | Legacy D1/D2 shared C outputs | Both surfaces use one BL-6 contract; optimization is non-normative | `ARCHITECTURAL_TRANSLATION` | Resolved specification |
| Non-NHG isolation | Legacy native/non-native split | External attendance never enters NHG compliance state | `ARCHITECTURAL_TRANSLATION` | Resolved |
| Clawback/close | E/F evidence is incomplete and contains defects | Only future use of unrounded failure predicate is known | `LEGACY_EVIDENCE_ONLY` | **Deferred** |

<details>
<summary>Original pre-decision coverage matrix (historical audit state; not current specification status)</summary>

In this preserved matrix, “Pending” and “BLOCKER” describe the 2026-07-17 state before the confirmed Phase 6-A decisions. They are superseded by the current matrix above except for clawback.

| Rule area | Legacy source | Current doc section | Classification | Severity | Implementation status |
|---|---|---|---|---|---|
| Session count unit | B `480-493`; C `93-106` | `business-logic.md` intro/BL-1; `AGENTS.md:109` | `EXACT_MATCH` | LOW | Specified |
| Active-month calculation | C `286-319` | BL-1, BL-8 | `DOC_AMBIGUITY` | BLOCKER | F-07: relational translation is intended; half-month factor wording is pending |
| FormF1 gate | A `609-629`; C `63-64` | BL-1; `parsing.md` FormF1 | `DOC_AMBIGUITY` | BLOCKER | F-03 value override is resolved; F-08 boundary gate is pending |
| AY month bucketing | B `130-166` | BL-5A/BL-6 | `DOC_AMBIGUITY` | BLOCKER | Inclusive resolver is translated; F-08 cross-calendar gate is pending |
| Capping | C `386-395`, `499-506` | BL-1 | `DOC_AMBIGUITY` | BLOCKER | Primitive formula matches; F-04 reallocation order and F-22 cross-R-year cap grain are pending |
| Target 100 | C `386-395` | BL-1 | `ARCHITECTURAL_TRANSLATION` | LOW | Arithmetic matches; current groups/phases are relational; F-07 wording remains |
| Target 70 | C `386-395`, `535-540` | BL-2/BL-3 | `DOC_AMBIGUITY` | BLOCKER | Posting formula is exact; the distinct per-session tag threshold and its role in transfer supply/demand require F-04/BD-01 clarification |
| Posting percentage | C `512-533` | BL-2 | `DOC_AMBIGUITY` | BLOCKER | The counted/target formula matches, but its numerator and result grain depend on F-04 and F-22 |
| Traffic-light thresholds | External templates not present | BL-2 | `DOC_CONTRADICTION` | BLOCKER | Current boundaries are new/deterministic for integer targets; F-10 fractional status conflicts |
| Zero targets | Legacy zero rows exist; C treats as numeric rows | BL-1 | `INTENTIONAL_OVERRIDE_RESOLVED` | MEDIUM | Specified: visible/auditable, compliance-inapplicable |
| Untracked targets | C `321-326` | BL-1/BL-3 | `ARCHITECTURAL_TRANSLATION` | LOW | Specified |
| Tag grouping | C `403-413`, `453-463` | BL-3 | `DOC_CONTRADICTION` | HIGH | Same-physical-posting scope is confirmed; F-06 grammar/validator and group order need patches |
| Tag ordering | C `413`, `463` | BL-3 | `EXACT_MATCH` | LOW | Lexical/alphabetical order specified, not duration |
| Tag transfer direction | C `417-443` | BL-3 | `EXACT_MATCH` | LOW | Earlier-to-later direction specified |
| Reallocation supply/demand | C `418-440` | BL-3 | `DOC_AMBIGUITY` | BLOCKER | F-04 pending |
| Surplus derivation | No persistent legacy surplus; local `bringover` only | BL-4 | `DOC_CONTRADICTION` | BLOCKER | F-05 pending |
| Surplus persistence/hibernation | No R equivalent | BL-4; `schema.md` surplus | `DOC_CONTRADICTION` | BLOCKER | New lifecycle partly specified; F-05 carry/use and F-18 uniqueness pending |
| R-year handling | A `565-607`; B `512-578`; C `380-395`, `512-518` | BL-1/BL-6/BL-11; `parsing.md` R year | `DOC_CONTRADICTION` | BLOCKER | Phase source is specified; F-09 flags and F-22 cap/aggregation grain are pending |
| `ALL` sentinel | Legacy long literal, A `565-568` | BL-11 | `DOC_CONTRADICTION` | BLOCKER | General translation is specified; F-09 subspecialty flags conflict |
| Posting groups | C dashboard posting `169-172`, `286-295`, `512-518` | BL-1/BL-6; `parsing.md` TTF E | `ARCHITECTURAL_TRANSLATION` | HIGH | Core grouping specified; clawback persistence pending |
| Multi-posting/half-month | A `405-535`; C `299-363` | BL-8 | `DOC_AMBIGUITY` | BLOCKER | Relational parser translation is intended; F-07/F-11 calculation paths pending |
| Combined-posting event attribution | A `449-489`; C `113-180` | BL-6/BL-8 | `DOC_GAP` | BLOCKER | Component events cannot reach combined phase/target without F-11 mapping |
| Dual/multi-posting reliability annotation | A multi-posting paths `405-535`; no exact legacy annotation | BL-7 | `DOC_AMBIGUITY` | MEDIUM | Independent fallback arithmetic is specified; exact-two versus two-or-more and month/period warning scope are pending F-23/G-41 |
| Global session exclusions | No exact R equivalent | BL-6; `schema.md` global types | `DOCUMENTED_NEW_BEHAVIOR` | LOW | Core order specified; API submission contradiction remains |
| Read-time catalogue/session/target resolution | C fuzzy target match `113-180` | BL-6; catalogue/target schema; API | `DOC_CONTRADICTION` | HIGH | Relational replacement is intended; F-17 cardinality, keyword normalization, global submission and catalogue-without-target outcomes remain |
| Native-programme event attribution | No distinct legacy visibility branch; C `113-180` | API resident visibility versus BL-6 | `DOC_AMBIGUITY` | HIGH | Visible/submittable outside assigned posting, but compliance identity is pending F-17 |
| Native ad-hoc fixed attribution | No distinct legacy ad-hoc calculation branch | BL-9; API ad-hoc endpoint | `DOCUMENTED_NEW_BEHAVIOR` | HIGH | Assigned posting + fixed Department/Programme Teaching [1h]; selected attended keyword is display/audit only |
| Weekend exclusions | B `899-947`, `1014-1017` | BL-5 | `INTENTIONAL_OVERRIDE_RESOLVED` | LOW | Current seed list specified except ORTHO row defect |
| Duplicate/conflict handling | B `881-883`, `952-1017` | BL-5; attendance schema/API | `DOC_AMBIGUITY` | HIGH | F-21 pair scope and action pending; DB uniqueness covers only same event |
| ORTHO mutation | B `912-918`, `940-941` | BL-5; schema weekend seed | `DOC_CONTRADICTION` | HIGH | F-13 seed/ordering pending |
| Public-holiday behavior | B `896-925`, `1014-1017` | BL-5 | `INTENTIONAL_OVERRIDE_RESOLVED` | LOW | Specified: creation hard block |
| FM handling | B `501-510`; D1 `202-213` | BL-FM | `INTENTIONAL_OVERRIDE_RESOLVED` | MEDIUM | Standard engine specified; 5h override must enter ordered pipeline |
| Resident/admin calculation parity | One C output feeds D1/D2, C `52-549` | BL-6 ordered path versus batch SQL; API reports | `DOC_CONTRADICTION` | BLOCKER | F-12: SQL is incomplete and non-normative; shared primitives/golden parity required |
| Employer exclusions | E `138-140` | BL-10 vs schema clawback | `DOC_CONTRADICTION` | BLOCKER | F-16 row semantics pending |
| Clawback trigger | E `36-41` | BL-10 | `INTENTIONAL_OVERRIDE_RESOLVED` | HIGH | Reject legacy formatting; use the unformatted canonical predicate selected by F-10/BD-05 |
| Norm-rate selection | E `25-34`, `64-90` | BL-10 | `DOC_GAP` | BLOCKER | F-14 values/storage/classification missing |
| Clawback result/billing identity | E `129-140` | BL-10; clawback/posting schema | `DOC_GAP` | BLOCKER | F-16/BD-13: static versus resident/month billing and standalone/group allocation are pending |
| R7 suppression | E `65-66` | BL-10/schema/API | `DOC_AMBIGUITY` | BLOCKER | Standalone row-present/zero is specified; overlap precedence/one-reason representation is pending F-15/F-16 |
| Extension suppression | No E equivalent; legacy C excludes Extension | BL-10 | `DOC_AMBIGUITY` | BLOCKER | New row behavior exists, but F-15 suppression granularity is pending |
| Clawback rounding | E `69-86` | BL-10 | `DOC_AMBIGUITY` | BLOCKER | F-16 formula timing matches; current Decimal mode pending |
| Non-NHG isolation | B `1019-1059` | BL-6/BL-12; `AGENTS.md` | `ARCHITECTURAL_TRANSLATION` | LOW | Specified |
| Final close/freeze | F2 is only file archival | BL-10; API reports | `DOC_GAP` | BLOCKER | New DB workflow is specified only at high level; BD-16 transaction/rerun contract is pending |

</details>

### 4.1 Detailed material finding register

The fields below preserve the original 2026-07-17 evidence and defect analysis. Their words “pending” or “blocker” are historical unless the current disposition table says `DEFERRED`.

| Finding | Current disposition | Confirmed resolution |
|---|---|---|
| F-03/F-08 | RESOLVED | AY bucket label selects the FormF1 month for both numerator and denominator across the whole bucket. |
| F-04/F-06 | RESOLVED | Reallocate raw one-for-one counts within physical posting/R-year context/prefix before caps; use configured prefix/tier labels in alphabetical order; decrement donor; duration never transfers. |
| F-05/F-18 | RESOLVED | Ledger is unique per resident/physical posting/type/period and idempotently replaces pre-tag raw-minus-target derived state; never carry it into attendance. |
| F-07 | RESOLVED | Half-month persists two rows at weight 0.5 and leaves monthly target unchanged. |
| F-09 | RESOLVED | SPORTSMED/PALLMED require R-year, are not subspecialties, and use R4–R6; overall split is 20/8. |
| F-10 | RESOLVED | Unrounded posting percentage is canonical; `target_70` is display-only. |
| F-11 | RESOLVED | `combine` uses one configured canonical combined posting code with TTF rows and no component results. |
| F-12 | RESOLVED SPECIFICATION | Resident and admin paths share the same BL-6 contract; no implementation claim. |
| F-13 | RESOLVED | Exact original ORTHO 3h type only; adjust end time, project type, then Saturday-window check. |
| F-14/F-15/F-16 | **DEFERRED** | Clawback financial, suppression, identity, billing, precision, and close behavior await confirmation. |
| F-17 | RESOLVED | Persisted explicit source plus scoped mapping; native outside events project under assigned posting; global/session/report semantics ordered in BL-6. |
| F-19/F-20 | RESOLVED AS AUDIT CONTEXT | Legacy report/Word claims remain evidence only and do not override source-of-truth rules. |
| F-21 | RESOLVED | Reject later overlapping distinct submission and preserve earlier attendance; same-event uniqueness is separate. |
| F-22 | RESOLVED | Target/cap each physical-posting/session-type/R-year context separately, then sum without duplicated months. |
| F-23 | NON-BLOCKING | Unmatched cells retain independent rows and parser warnings; reliability annotation details do not change ordinary arithmetic. |

The fields below are intentionally repetitive so an implementation or documentation owner can trace each conclusion without inferring missing legacy context.

#### F-01 — Core capping and posting aggregation

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-01 |
| Classification | `EXACT_MATCH` |
| Severity | LOW |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `380-395`, `499-549` |
| Legacy function/block/object | `freq_table_posting_sessiontype`, `total_freq_posting_table` |
| Relevant R expression or unique fragment | `Target100 <- Target(mth) * No. of active months(ALL)`; `ceiling(Target100*0.7)`; `Achieved and counted <- ifelse(Achieved>Target100,Target100,Achieved)`; posting `aggregate(...)` |
| Current documentation file | `docs/business-logic.md` |
| Current documentation section | BL-1 and BL-2 (`7-127`) |
| Observed behavior | Session rows are capped at `target_100`; posting numerator and denominator are sums across tracked types; posting `target_70` is the ceiling of 70% of the summed `target_100`; posting shortage is clamped at zero. |
| Current documented behavior | Same formulas and posting-level decision grain. |
| Analysis | The primitive arithmetic is an exact match for ordinary standalone rows and is safe to port once the order around reallocation and fractional status is resolved. Current posting-group and phase/R-year grains are architectural translations, not literal R grouping. Per-session `target_70` exists in R for tag demand, but final compliance is posting-level. |
| Implementation consequence | Do not sum per-session ceilings to produce posting `target_70`; do not use monthly colour as compliance status. |
| Recommended documentation action | Retain BL-1/BL-2; add a note that posting `target_70 = ceil(sum(target_100) * .70)`. |
| Decision required, if any | None for integer, non-tagged cases. |
| Required regression test | G-01, G-02, G-05 and G-24. |

#### F-02 — Legacy ingestion and error-feedback logic

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-02 |
| Classification | `LEGACY_DISCARD_CONFIRMED` |
| Severity | LOW |
| Legacy source file | `MATA R Scripts/B/B_Data collection and cleaning v4.R` |
| Legacy line range | `29-700`, `744-889`, `1019-1059` |
| Legacy function/block/object | FormSG parsing, response duplication, dashboard feedback, fuzzy resolution, native/non-native text split |
| Relevant R expression or unique fragment | `responseIDwithproblemALL`; `gsub()/tolower()/grepl()` matching; `_consec2`; `attendancecomb_ignore` |
| Current documentation file | `AGENTS.md`; `docs/00_project_context.md`; `docs/api.md`; `docs/schema.md` |
| Current documentation section | Direct submission/auth, attendance uniqueness/status, legacy cutover |
| Observed behavior | Free text and CSV shape drive identity, posting and session resolution; dashboard spreadsheets feed error codes back; one response can be duplicated into several teaching rows. |
| Current documented behavior | Authenticated identity, FK-backed events/catalogue, structured API validation, DB uniqueness, and no hybrid/feedback-loop ingestion. Distinct-event duplicate/overlap logic is separately retained and audited in F-21. |
| Analysis | These parsing/feedback loops are transport/workflow workarounds, not hidden compliance rules. The B bug that removes future rows only when more than one exists (`749-752`) is also not a rule. DB uniqueness does not settle F-21. |
| Implementation consequence | None of these loops should appear in Phase 6 services. |
| Recommended documentation action | Keep the discard statements; correct the Word audit’s invalid suggestion of status `excluded` to the schema’s allowed statuses. |
| Decision required, if any | None. |
| Required regression test | Duplicate native `(resident,event)` is rejected by the DB; non-NHG writes only to external attendance; use F-21 for distinct-event conflicts. |

#### F-03 — FormF1 status semantics and current AY architecture

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-03 |
| Classification | `INTENTIONAL_OVERRIDE_RESOLVED` |
| Severity | HIGH |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R`; `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | A `609-629`; C `63-64` |
| Legacy function/block/object | `activestatus`, `postingOnemcr` |
| Relevant R expression or unique fragment | Missing FormF1 defaults `Inactive`; C keeps `postingOnemcr$Status=="Active"` only. |
| Current documentation file | `docs/business-logic.md`; `docs/parsing.md`; `AGENTS.md` |
| Current documentation section | BL-1 FormF1 gate; FormF1 upload; confirmed guardrails |
| Observed behavior | Legacy excludes `Extension`, blanks, missing rows and all values other than exact `Active`; SIG has a URO fallback. |
| Current documented behavior | `Active` and `Extension` are active; blank/NULL/whitespace and `Inactive` are inactive; unknown nonblank values warn and use the active fallback; programme-specific SIG fallback is gone. AY boundaries bucket attendance. |
| Analysis | The current rule is an explicit replacement and must not be “corrected” to exact-Active legacy behavior. F-08 is a separate boundary-granularity gap. |
| Implementation consequence | Include Extension in numerator/denominator for ordinary compliance even though clawback suppression remains pending. |
| Recommended documentation action | Preserve current status mapping; cross-link it to the eventual calendar-vs-AY gating rule. |
| Decision required, if any | None for value mapping. |
| Required regression test | G-06, G-07, G-21 and the unknown-status parser test. |

#### F-04 — Reallocation order, supply, and effect

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-04 |
| Classification | `DOC_AMBIGUITY` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `386-395`, `399-506` |
| Legacy function/block/object | Both “Move according to tag” blocks; `bringover` |
| Relevant R expression or unique fragment | `bringover[c] <- temp3$Achieved[c]-temp3$Target70[c]`; donor/recipient mutate raw `Achieved`; `bringover[d]` is never reduced; final cap at `499-504`. |
| Current documentation file | `docs/business-logic.md`; `AGENTS.md` |
| Current documentation section | BL-3 `131-203`; global reallocation rules |
| Observed behavior | R uses raw-minus-per-session-`target_70` supply, transfers raw counts, then recaps. The same donor supply can be spent twice. R groups only by resident/prefix, so identical prefixes can cross postings. |
| Current documented behavior | BL-3 says same posting only, alphabetical earlier-to-later, one-for-one, capped `achieved_and_counted` supply, and donor balance decremented. Its examples imply a per-session `target_70 = ceil(session_target_100 * 0.70)` for tag demand, but the ordered contract does not state that distinct row-level threshold cleanly. BL-6 groups posting-group members before reallocation, which could be read to permit cross-member flow despite the confirmed no-cross-posting rule. |
| Analysis | The same-physical-posting scope and donor decrement are safe intentional fixes. Posting-group aggregation must occur only after each physical posting's transfers, so group membership cannot create cross-posting flow. But transferring already-capped values conserves the posting numerator; it cannot improve posting compliance or posting shortage. That conflicts with the stated purpose of filling shortfalls and materially differs from R. The per-session threshold must also remain distinct from the final posting-level `target_70`. |
| Implementation consequence | An implementer can produce either a distribution-only algorithm or a legacy-outcome algorithm and claim support from the docs. Three-tier outcomes diverge. |
| Recommended documentation action | State one canonical sequence and effect. Define per-session `tag_target_70`, donor supply, recipient demand, and their fractional-target behavior separately from posting-level `target_70`. Recommended: use raw attendance as auditable input, define a separately bounded transferable amount, consume it once, recap each recipient/donor, then aggregate; or explicitly declare reallocation display-only and remove claims that it affects posting compliance. Execute transfers within each physical posting before posting-group aggregation. Do not restore cross-posting flow or donor double-spend. |
| Decision required, if any | Does reallocation increase posting `achieved_and_counted`, or only redistribute a fixed capped posting total? What exact supply formula and per-session threshold apply? |
| Required regression test | G-11 through G-14 and G-25. |

#### F-05 — Surplus ledger meaning, carry-in, and resumption

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-05 |
| Classification | `DOC_CONTRADICTION` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `399-497` |
| Legacy function/block/object | Local `bringover`; no persisted surplus object in A/B/C/D/E/F |
| Relevant R expression or unique fragment | `bringover <- rep(0,nrow(temp3))` exists only within one calculation run. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md` |
| Current documentation section | BL-4 `207-260`; `surplus_ledger` `453-469` |
| Observed behavior | Legacy has no cross-month or cross-return persistent surplus; local tag supply is calculated and discarded in C. |
| Current documented behavior | Ledger stores pre-reallocation surplus, hibernates when a resident rotates away, resumes on return, resets at period boundary. BL-4 says the update uses capped achievement (`213-215`) but its code computes `max(0, raw achieved - target_100)` (`218-231`). |
| Analysis | If the input is capped at `target_100`, stored surplus is always zero. If raw is used, the text is wrong. The docs also do not state how an existing ledger balance enters a later read, how recalculation avoids additive double-counting, or whether the ledger is derived state versus an input. |
| Implementation consequence | Upserts can erase, duplicate, or never consume surplus; hibernation/resumption cannot be implemented deterministically. |
| Recommended documentation action | Define the ledger invariant, raw/capped formula, idempotent recomputation, carry-in use, consumption, return/resumption, and relationship to BL-3. |
| Decision required, if any | Is surplus `max(raw-target_100,0)`, `max(capped-target_70,0)`, or something else; and does it affect future compliance? |
| Required regression test | A return-to-posting sequence with repeated reads, mutation, hibernation, resumption, and period rollover. |

#### F-06 — Tag grammar and upload validation

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-06 |
| Classification | `DOC_CONTRADICTION` |
| Severity | HIGH |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `408-413`, `458-463` |
| Legacy function/block/object | Prefix extraction and `order(Tag)` |
| Relevant R expression or unique fragment | `substr(Tag,1,nchar(Tag)-1)`; `order(temp3$Tag)` |
| Current documentation file | `docs/business-logic.md`; `docs/parsing.md`; `AGENTS.md` |
| Current documentation section | BL-3; TTF Column J/validation `479-493`, `581-593`; architectural rule `112` versus `140` |
| Observed behavior | R accepts arbitrary strings, strips exactly one final character for grouping, and sorts lexically. Thus `A1.5` groups as `A1.`, `A10` as `A1`, and one-character tags share an empty prefix. |
| Current documented behavior | BL-3 expects distinct `A1/A2/A3` values sharing a prefix, while parsing requires another row with the **same exact tag** and gives `A`/`B` examples. `AGENTS.md:112` says duration-driven flow while `:140` and BL-3 say alphabetical. |
| Analysis | Canonical valid rows can be rejected, and multi-digit/decimal/space behavior is undefined. |
| Implementation consequence | Parser and engine can disagree about which rows form a group. |
| Recommended documentation action | Define a regex/normalized grammar and prefix/tier extraction; require at least two distinct tier tags with the same derived prefix; retain lexical flow and warning-only duration validation. |
| Decision required, if any | Allowed suffix grammar and whether `A10`, decimals, spaces, and suffix letters are valid. |
| Required regression test | Accept A1/A2; reject or explicitly normalize A, A10, A1.5, whitespace variants and duplicate tiers. |

#### F-07 — Half-month target application

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-07 |
| Classification | `DOC_AMBIGUITY` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `299-319`, `342-389` |
| Legacy function/block/object | GASTRO TTSHGas/NUHGas special case; `freq_table` versus `freq_table2` |
| Relevant R expression or unique fragment | Posting path subtracts `0.5` active month; separate monthly-display copy divides `Target(mth)` by 2. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md` |
| Current documentation section | BL-1 `36-37`; BL-8 `646-652`; multi-posting rules notes |
| Observed behavior | For posting compliance, R leaves monthly target unchanged and applies the 0.5 active-month adjustment once. Target halving occurs only in a separate monthly-display table. |
| Current documented behavior | Formula already multiplies monthly target by `active_months_weight`, but prose says both active months and `Target(mth)` are halved. Literal application quarters the posting target. |
| Analysis | The relational translation should replace R’s brittle row-count condition, but the factor must be applied once. |
| Implementation consequence | A valid half-month can receive 25% rather than 50% of the monthly denominator. |
| Recommended documentation action | State: persist TTF monthly target unchanged; set `active_months_weight=0.5`; compute `target_100=monthly_target*0.5` once. Any halved monthly display value is derived display-only data. |
| Decision required, if any | Confirm the single-weight interpretation (strongly supported by the posting-level R path). |
| Required regression test | G-03 and G-40, including multiple session types where the legacy hardcode failed. |

#### F-08 — Calendar FormF1 gate versus AY bucket

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-08 |
| Classification | `DOC_AMBIGUITY` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R`; `MATA R Scripts/B/B_Data collection and cleaning v4.R` |
| Legacy line range | A `609-629`; B `148-166` |
| Legacy function/block/object | Three-letter posting-month FormF1 match; inclusive changeover bucket |
| Relevant R expression or unique fragment | `substr(posting month,1,3) == substr(FormF1 column,1,3)`; event date between bucket start/end inclusively |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md`; `docs/parsing.md` |
| Current documentation section | BL-1 `25-34`; BL-5A; BL-6 `423-425`, batch SQL `490-513`; FormF1/AY schemas |
| Observed behavior | Legacy effectively assigns one status to the named posting month, even when its date range crosses a calendar boundary. |
| Current documented behavior | FormF1 is explicitly calendar-month authoritative; attendance is AY-boundary bucketed. Batch SQL gates a phase using the calendar month of `rp.start_date`. |
| Analysis | For an AY phase 8 Jul–3 Aug with July Active and August Inactive, the docs do not determine the denominator weight or whether a weekday Aug 3 attendance is included. The SQL’s start-month shortcut is not established as normative. |
| Implementation consequence | Resident and admin numerator/denominator can diverge at every AY/calendar boundary. |
| Recommended documentation action | Specify the exact calendar status applied to each phase fraction and each attendance date, including cross-calendar boundaries; then make resident and batch paths identical. |
| Decision required, if any | Gate by event calendar month, AY bucket label/start month, split phase weight across calendar months, or another confirmed rule. |
| Required regression test | G-06/G-07 plus a Jul-active/Aug-inactive weekday event on Aug 3 inside the July AY bucket. |

#### F-09 — `ALL` sentinel versus subspecialty remapping

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-09 |
| Classification | `DOC_CONTRADICTION` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R` |
| Legacy line range | `241-246`, `288-306`, `565-607` |
| Legacy function/block/object | Programme normalization, attempted SS remap, no-R-year replacement |
| Relevant R expression or unique fragment | SS remap compares long programme names after abbreviating them, then no-R-year programmes receive a long sentinel. The saved data does not prove the remap. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md`; `docs/parsing.md`; `AGENTS.md` |
| Current documentation section | BL-11; programme seed; `resolve_r_year()` `150-178` |
| Observed behavior | Legacy implementation contains an ordering/name mismatch and later replaces no-R-year values. |
| Current documented behavior | `SPORTSMED` and `PALLMED` have both `r_year_required=false` and `is_subspecialty=true`; parser code returns `ALL` before reaching SS remap. Text simultaneously promises R4→SS1, R5→SS2, R6→SS3 (one list omits R6). |
| Analysis | Both flags cannot affect the same stored value under the documented function. This is not a reason to preserve the legacy bug. |
| Implementation consequence | Targets/catalogue may be seeded as `ALL` while tests/UI expect SS years. |
| Recommended documentation action | Confirm which flag wins for these programmes and align seed, parser, TTF explosion, BL-11 and AGENTS. |
| Decision required, if any | Should these two programmes use `ALL`, or should they require/remap SS years? |
| Required regression test | G-08 plus R4/R5/R6 parser fixtures for both programmes. |

#### F-10 — Fractional target status and colour

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-10 |
| Classification | `DOC_CONTRADICTION` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R`; `MATA R Scripts/E/E_Clawback v1.R` |
| Legacy line range | C `386-395`, `526-545`; E `36-41` |
| Legacy function/block/object | Fractional `Target100`, posting percentage/Target70, clawback trigger |
| Relevant R expression or unique fragment | Cap can be decimal; `Target70=ceiling(Target100*.7)`; percentage uses capped/Target100; E triggers on percentage rather than `Target70` comparison. |
| Current documentation file | `docs/business-logic.md` |
| Current documentation section | BL-1 `11-18`; BL-2 `95-127` |
| Observed behavior | With `target_100=1.5` and raw achieved 2, capped achievement is 1.5, percentage is 1.0, but `target_70=2`; legacy percentage-based clawback does not trigger. |
| Current documented behavior | Pseudocode sets `met = achieved_and_counted >= target_70` and colour green only if `met`; the traffic table says green whenever percentage >=70%. These disagree for fractional targets. |
| Analysis | This is reachable because half-month weights are documented and odd integer monthly targets are valid. |
| Implementation consequence | One engine can return 100%, `met=false`, amber, shortage 0.5 and another can return green/met. Clawback candidacy also diverges. |
| Recommended documentation action | Define a single canonical compliance predicate for fractional denominators and align `met`, colour, shortage, and clawback. |
| Decision required, if any | Percentage criterion versus ceiling-count criterion (or a documented target quantization rule). |
| Required regression test | G-03. |

#### F-11 — Combined-posting event-to-target attribution

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-11 |
| Classification | `DOC_GAP` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R`; `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | A `449-489`; C `113-180`, `184-280` |
| Legacy function/block/object | `multiplepostingcombi_both`; dashboard/RDB target matching |
| Relevant R expression or unique fragment | Combine mapping replaces posting strings before C target construction. |
| Current documentation file | `docs/business-logic.md`; `docs/parsing.md` |
| Current documentation section | BL-6 `422-430`; BL-8 combine `637-644`; RDB multi-posting rules |
| Observed behavior | Legacy string replacement gives C one dashboard/combined identity before aggregation. |
| Current documented behavior | Resident phase and TTF target use a combined label, but secretaries create events under component posting codes. BL-6 requires event posting = phase posting and catalogue posting = event posting. |
| Analysis | A component event cannot match the combined phase or combined-label target. No read-time component map/attribution sequence is defined. |
| Implementation consequence | Valid combined-posting attendance is silently excluded. |
| Recommended documentation action | Define eligible component codes, catalogue lookup context, combined target identity, deduplication, and posting-group interaction using explicit configuration—never regex. |
| Decision required, if any | Whether component keywords/catalogues or the combined catalogue govern resolution, and how both sites contribute to one target. |
| Required regression test | Component A and B events both count once under the combined label; unrelated component is excluded. |

#### F-12 — Admin batch path versus normative JIT path

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-12 |
| Classification | `DOC_CONTRADICTION` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `52-549` |
| Legacy function/block/object | One common C result feeds both D1 and D2 |
| Relevant R expression or unique fragment | D1 and D2 both load the same `C1_*` output; there is no separate legacy admin formula. |
| Current documentation file | `docs/business-logic.md`; `docs/api.md` |
| Current documentation section | BL-6 ordered steps `422-435` versus SQL `487-590`; API reports `1063-1067` |
| Observed behavior | Legacy report consumers share one calculation output. |
| Current documented behavior | API says all admin views use the shown SQL, but that SQL omits global types, weekend/ORTHO logic, posting groups, zero targets and AY boundaries; omits catalogue `r_year`; groups by raw posting; and uses a different dual-posting test. |
| Analysis | The SQL is not an optimization-equivalent rendition of the normative pipeline. |
| Implementation consequence | Admin and resident results can differ for the same records. |
| Recommended documentation action | Mark SQL non-normative and replace it with an equivalence-complete plan/query; require shared domain functions and parity tests. |
| Decision required, if any | BD-18: the architecture/reporting owner must designate the ordered domain contract or an equivalence-complete replacement as normative and explicitly demote/remove the current SQL; this may not introduce new business semantics. |
| Required regression test | Run every golden fixture through resident and batch paths; assert field-for-field calculation equivalence. |

#### F-13 — ORTHO acceptance and mutation predicate

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-13 |
| Classification | `DOC_CONTRADICTION` |
| Severity | HIGH |
| Legacy source file | `MATA R Scripts/B/B_Data collection and cleaning v4.R` |
| Legacy line range | `912-918`, `940-941` |
| Legacy function/block/object | ORTHO mutation block and separate accepted-exception block |
| Relevant R expression or unique fragment | Mutation requires exact original 3h type and runs Sat/Sun; acceptance requires Saturday 08:30–10:30. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md` |
| Current documentation section | BL-5 `287-354`; confirmed weekend seed `613-647` |
| Observed behavior | Legacy first mutates an original weekend 3h row (subtracting two hours from end time), then applies Saturday 08:30–10:30 acceptance. |
| Current documented behavior | Current correctly requires read-time raw preservation and says only the 3h type mutates, but the ORTHO seed has `session_type_id=NULL`, so it can mutate every in-window type. The matching function also tests the **raw** end-time window before returning the mutation; a normal 08:30–11:30 3h event fails `end<=10:30` and never reaches mutation. |
| Analysis | Acceptance and mutation need separate predicates/rows, an original-type predicate, and an explicit mutation-versus-time-window order. Sunday should remain excluded under the current confirmed seed. |
| Implementation consequence | Ordinary ORTHO sessions can be relabelled, while the intended 3h session can be rejected before it is shortened. |
| Recommended documentation action | Define a type-constrained mutation evaluated in the approved order and a separate Saturday acceptance predicate; show raw and adjusted times. |
| Decision required, if any | Confirm broad versus type-specific acceptance and whether the adjusted or raw interval is tested against 08:30–10:30. |
| Required regression test | G-16 plus non-3h Saturday and 3h Sunday variants. |

#### F-14 — Norm rates and IM-sub-specialty classification

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-14 |
| Classification | `DOC_GAP` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R`; `MATA R Scripts/E/E_Clawback v1.R` |
| Legacy line range | A `251-257`; E `25-34`, `64-90` |
| Legacy function/block/object | `im_progname`, `normtab`, `normtab_fm`, clawback branch order |
| Relevant R expression or unique fragment | Rates are positional cells from two missing templates; dynamic `im_progname`; R7→0, FM match, SS/IM row 1, IM-subspec row 4, otherwise R-year match. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md`; `docs/99_decision_log_and_gap_audit.md` |
| Current documentation section | BL-10 `810-851`; clawback schema; open rates audit `1048-1057` |
| Observed behavior | Exact legacy values cannot be verified. A derives a period-specific dynamic IM set from Phase 3 RDB data, but a snapshot-derived set is not a durable business decision. |
| Current documented behavior | `im_programmes=[]` is explicitly a TODO; no rate table, values, effective dates, source/version, or seed exists. |
| Analysis | Financial output cannot be reproduced or audited from current source-of-truth docs. The Word audit further labels the first standard norm row as junior/R1 while using that same positional cell for SS/IM senior branches; without the template, only E’s positional branch is proven. |
| Implementation consequence | `clawback.py` would require invented money values/classification. |
| Recommended documentation action | Obtain owner-approved rates and classifications; define a versioned, period-effective persistence/seed model and branch table. |
| Decision required, if any | Exact rates, meanings of rate categories, durable IM set, effective period/version owner. |
| Required regression test | Branch table tests for FM R1–R3, SS, IM, IM-subspec, standard R years and missing rate. |

#### F-15 — Clawback funding year and Extension scope

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-15 |
| Classification | `DOC_AMBIGUITY` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R`; `MATA R Scripts/E/E_Clawback v1.R` |
| Legacy line range | C `63-64`, `512-518`; E `36-90` |
| Legacy function/block/object | Candidate rows; FormF1 R-year overwrite; rate calculation |
| Relevant R expression or unique fragment | E replaces every candidate R year with FormF1 column 8; E has no Extension suppression. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md` |
| Current documentation section | BL-1 phase R year; BL-10 `823-851`; FormF1 and clawback tables |
| Observed behavior | Legacy C may create separate R-year posting rows, then E overwrites both with one FormF1 funding year. Exact `Active` filtering means Extension months never reach E. |
| Current documented behavior | Compliance uses phase `resident_postings.r_year`; 22 programmes use `ALL`; FormF1 no longer stores R year; an “Extension resident” gets a zero row. One clawback row has one `r_year` and one suppression reason. |
| Analysis | Funding year is undefined for `ALL` when the selected rate branch is year-dependent, and the persisted audit year/result shape remains ambiguous even for branches whose rate ignores year. Mid-period transitions are also unresolved. Mixed Active/Extension does not say whether any, all, or only Extension-weighted months suppress a posting row, nor which reason wins when Extension overlaps R7 and/or an excluded employer. |
| Implementation consequence | Rate and amount can vary materially for the same compliance result. |
| Recommended documentation action | Define a separate funding/clawback year source and phase aggregation/proration; define Extension suppression granularity and its precedence/representation when another suppression applies. Do not reuse display/current resident year implicitly. |
| Decision required, if any | Funding year source for year-dependent branches and audit identity elsewhere; split versus one row; any/all/per-month Extension rule; overlapping-suppression precedence. |
| Required regression test | G-09, G-20, G-21, G-31 and G-36. |

#### F-16 — Clawback identity, exclusions, error handling, and precision

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-16 |
| Classification | `DOC_CONTRADICTION` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/E/E_Clawback v1.R` |
| Legacy line range | `36-41`, `69-90`, `129-140` |
| Legacy function/block/object | Candidate trigger, amount vector, first-month billing lookup, billing-derived SAF/SCDF filter |
| Relevant R expression or unique fragment | `format(...,digits=2)<0.7`; `round((rate/12)*months,2)`; `all1billingposting` plus the first posting month picks resident/month-specific billing; SAF/SCDF rows are removed; ERR18 is text, not zero. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md`; `docs/api.md` |
| Current documentation section | BL-10; `clawback_records`; GET clawback |
| Observed behavior | Legacy has no safe default for a missing rate, no group identity, no suppression reason, no final-close guard, and no employer output row. It calls base R `round(...,2)` once after the full formula; base R uses IEC-60559 ties-to-even where representable, subject to binary-double representation. |
| Current documented behavior | BL says SAF/SCDF produce no row; schema says show zero/suppressed rows; API names only Extension/R7, while `clawback_suppressed_reason` stores only one value. Posting groups can be the compliance identity but result schema requires one posting FK and copies a static `posting_codes.billing_dept`; no resident/month billing schedule replaces legacy `all1billingposting`. Missing R-year silently returns `0.0`; the current Decimal tie mode is not fixed. |
| Analysis | These are financial/audit semantics, not merely output formatting. Legacy significant-digit trigger should not be copied, but its unformatted replacement remains coupled to the F-10 fractional-target decision. Missing configuration must not masquerade as an exemption. A candidate can simultaneously be R7, Extension and SAF/SCDF, yet current row/no-row rules and one reason field have no precedence. Static billing is also a material unconfirmed departure from legacy resident/month billing even for a standalone posting. |
| Implementation consequence | Wrong debtor/billing department, silent zero amounts, inconsistent row counts/reasons, and irreproducible half-cent or close-rerun results. |
| Recommended documentation action | Choose standalone/group result identity, billing source and time grain, overlapping-suppression precedence/representation, employer row rule, fail-closed missing-rate behavior, canonical candidate predicate, Decimal scale/rounding, and final-close transaction/uniqueness/replacement/rerun behavior. Fix the schema index that references nonexistent `programme_code`. |
| Decision required, if any | All listed row/suppression/billing/error/rounding/close semantics. |
| Required regression test | G-01/G-02 trigger; G-22/G-23; G-28–G-30; G-36–G-39; G-43/G-44; missing rate; and approved close rerun/rollback behavior. |

#### F-17 — Source/mapping/API/report semantic conflicts

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-17 |
| Classification | `DOC_CONTRADICTION` |
| Severity | HIGH |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R`; no global-type legacy equivalent |
| Legacy line range | C `113-180` |
| Legacy function/block/object | First target match and exclusion on no match |
| Relevant R expression or unique fragment | `rowno_matched[1]`; unmatched attendance is marked error/excluded. |
| Current documentation file | `docs/schema.md`; `docs/parsing.md`; `docs/business-logic.md`; `docs/api.md`; `docs/99_decision_log_and_gap_audit.md` (secondary gap record only) |
| Current documentation section | persisted scheduled-event source identity, scoped Teaching Name mappings, final A-J TTF validation, BL-6 future resolver boundary, and event/attendance endpoints |
| Observed behavior | Legacy silently chooses the first fuzzy target and has no global catalogue. |
| Current documented behavior | The final schema removes the catalogue. Scheduled events persist exactly one Teaching Name or global source ID when source-backed; a both-null legacy row uses deterministic persisted evidence only. Global source rows are visible/attendance-trackable but excluded before a future compliance resolver. Phase G runtime discovery and attendance are not a compliance resolver. A future resolver must use explicit source identity plus scoped mappings and target context, never display text. |
| Analysis | Persisted source identity replaces “first match,” but the future resolver, mappings, and reporting API still need one authorized cardinality and grain. Legacy C has no separate native-programme visibility branch, so the future resolver must not infer an identity from visibility or a display snapshot. |
| Implementation consequence | Valid global attendance can be stored while remaining compliance-exempt; native-programme attendance can be accepted without granting implicit compliance attribution; UI cannot imply that a display name alone establishes a session type. |
| Recommended documentation action | Define the future scoped source-to-mapping/target contract, including native-programme and combined-posting attribution, and require every read-time path to use it. Preserve global exclusion and deterministic legacy evidence. Do not reintroduce keyword normalization, Column K, or display-text lookup. |
| Decision required, if any | Whether a native-programme event outside the assigned posting counts, under which posting/target identity, and the owner-approved combined-posting attribution contract. |
| Required regression test | G-17/G-18/G-35/G-45 and API global-submission test; posting summary equals breakdown aggregate. |

#### F-18 — Ledger persistence constraint

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-18 |
| Classification | `DOC_GAP` |
| Severity | HIGH |
| Legacy source file | No legacy persisted equivalent |
| Legacy line range | Not applicable |
| Legacy function/block/object | Not applicable |
| Relevant R expression or unique fragment | No A–F `save()` includes persistent surplus. |
| Current documentation file | `docs/schema.md`; `docs/business-logic.md` |
| Current documentation section | `surplus_ledger` `453-469`, indexes `1131-1139`; BL-4 upsert |
| Observed behavior | None in legacy. |
| Current documented behavior | Exactly one conceptual row per resident/posting/session/period is upserted, but schema documents only a non-unique index. |
| Analysis | An upsert has no conflict key and concurrent/read-triggered calculations can create duplicates. |
| Implementation consequence | Surplus reads and hibernation become nondeterministic. |
| Recommended documentation action | Add a unique constraint on `(reporting_period_id, resident_id, posting_code, session_type_id)` after F-05 semantics are resolved. |
| Decision required, if any | None about uniqueness once tuple identity is retained. |
| Required regression test | Concurrent/repeated upsert produces one row. |

#### F-19 — Word audit accuracy

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-19 |
| Classification | `AUDIT_SUMMARY_ERROR` |
| Severity | HIGH |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R`; `MATA R Scripts/B/B_Data collection and cleaning v4.R`; `MATA R Scripts/C/C_Data preparation v3.R`; `MATA R Scripts/D/D1_Generate programme reporting view v2.R`; `MATA R Scripts/D/D2_Generate resident dashboard v2.R`; `MATA R Scripts/E/E_Clawback v1.R`; `MATA R Scripts/F/F1_Preparation for NEW period v1.R`; `MATA R Scripts/F/F2_Archiving v1.R` |
| Legacy line range | A `565-607`; B `882`, `912-947`, `952-996`; C `299-319`, `380-506`; D1 `202-213`; D2 `186-205`; E `25-90`, `129-140`; F1 `26-58`; F2 `20-36`, `117-121` |
| Legacy function/block/object | C tag loop, E trigger/rate year, B exceptions, D templates |
| Relevant R expression or unique fragment | Word says higher digit→lower while its code sorts ascending; omits raw transfer/re-cap and legacy donor double-spend; omits E `format()` and FormF1 R-year overwrite. |
| Current documentation file | `MATA R Scripts/MATA_Core_Business_Logic_Audit.docx` (secondary); `docs/99_decision_log_and_gap_audit.md` |
| Current documentation section | Word Sections 1–3; decision-log script attribution around `900-905`, `951-957` |
| Observed behavior | Exact corrections are listed in section 8. |
| Current documented behavior | Word presents itself as a precise direct-translation reference; decision log calls clawback Script F and misattributes the FM report template. |
| Analysis | It is useful as an index only. Direct code and current domain docs must control implementation. |
| Implementation consequence | A literal port would implement wrong tag direction/supply, R-year source, exception list, and discarded/current features. |
| Recommended documentation action | Add a superseded/non-authoritative banner or publish corrections; fix decision-log attributions without treating stale history as authority. |
| Decision required, if any | None. |
| Required regression test | Not an engine test; traceability review must link every implementation rule to current authority/direct R evidence. |

#### F-20 — Legacy report/template-only behavior

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-20 |
| Classification | `LEGACY_AMBIGUITY` |
| Severity | MEDIUM |
| Legacy source file | `MATA R Scripts/D/D1_Generate programme reporting view v2.R`; `MATA R Scripts/D/D2_Generate resident dashboard v2.R`; `MATA R Scripts/E/E_Clawback v1.R` |
| Legacy line range | D1 `202-213`, `281-323`; D2 `186-201`; E `25-34` |
| Legacy function/block/object | External workbook templates; display writes; positional norm cells |
| Relevant R expression or unique fragment | D2 writes `ceiling(percentage*100)/100`; R scripts do not implement traffic colours; E reads last two columns of missing templates. |
| Current documentation file | `docs/business-logic.md`; `docs/api.md` |
| Current documentation section | BL-2 colours; report endpoints |
| Observed behavior | Display percentage is rounded upward; exact colour formulas/rates are external and unavailable. |
| Current documented behavior | Raw calculation percentage and exact colour boundaries are specified; display rounding is not. |
| Analysis | Current colours may be implemented from BL-2 without proving template formulas. Display formatting must never drive `met`/clawback. |
| Implementation consequence | A displayed 0.70 could hide raw 0.691 failure if rounding is copied without labeling. |
| Recommended documentation action | Define API numeric precision and optional display rounding separately; never use formatted values for decisions. |
| Decision required, if any | Whether to retain upward display rounding for legacy-compatible exports. |
| Required regression test | Raw 0.691 remains non-green/noncompliant regardless of displayed value. |

#### F-21 — Duplicate and overlapping distinct events

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-21 |
| Classification | `DOC_AMBIGUITY` |
| Severity | HIGH |
| Legacy source file | `MATA R Scripts/B/B_Data collection and cleaning v4.R` |
| Legacy line range | `881-883`, `952-1017` |
| Legacy function/block/object | Sorted adjacent duplicate/conflict scan; `dupcol`, `conflictcol`, `attendancecomb_final` |
| Relevant R expression or unique fragment | Sort by programme/MCR/date/start/timestamp; compare only `datatemp[j]` with `datatemp[j+1]`; exact same interval distinguishes same/different type; otherwise `secondrowstart < firstrowend`; mark the earlier row. |
| Current documentation file | `docs/business-logic.md`; `docs/schema.md`; `docs/api.md` |
| Current documentation section | BL-5 duplicate/conflict `368-381`; attendance uniqueness/status; attendance submission |
| Observed behavior | Legacy evaluates only same-resident/same-date adjacent pairs after sorting, marks the earlier row, and excludes that flagged row from the no-error compliance input. A later row can remain countable. It compares the legacy-resolved session type. |
| Current documented behavior | BL-5 supplies a symmetric interval comparator using `session_type_id`; DB uniqueness prevents only duplicate `(resident,event)`. No authoritative text defines which event pairs are checked, when resolution/mutation occurs, or whether a conflict is rejected, stored/flagged, or excluded from one/both sides. |
| Analysis | Duplicate same-event prevention does not replace conflicts between distinct scheduled/ad-hoc events. Porting only adjacency can miss chained/nonadjacent overlaps; applying all-pairs without action semantics can over-reject. |
| Implementation consequence | The numerator and user submission outcome can differ depending on iteration order and API path. |
| Recommended documentation action | Define resident/date scope, interval boundary (`end == next start`), all-pairs/interval algorithm, original versus compliance-mutated type, action/status for old/new rows, and API response. |
| Decision required, if any | Reject new conflict, store flagged and exclude one/both, or warn/store/count; and whether the same rule applies to scheduled and ad-hoc attendance. |
| Required regression test | Same-event DB duplicate; distinct events with identical interval/same type; identical interval/different type; partial overlap; A–B–C chain; touching endpoints; action/status and numerator for both records. |

#### F-22 — Cross-R-year capping and result grain

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-22 |
| Classification | `DOC_AMBIGUITY` |
| Severity | BLOCKER |
| Legacy source file | `MATA R Scripts/C/C_Data preparation v3.R` |
| Legacy line range | `286-295`, `380-395`, `512-518` |
| Legacy function/block/object | Posting-wide active-month aggregation, posting/session/R-year aggregation, target/cap assignment, final posting aggregation |
| Relevant R expression or unique fragment | `No. of active months(ALL)` is aggregated by dashboard posting without R year at `290-293`; later `aggregate()` calls retain `Year of Residency`, so each R-year row receives the posting-wide month count before its own cap and final R-year output. |
| Current documentation file | `docs/business-logic.md` |
| Current documentation section | BL-1 `9-24`, `68-70`; BL-6 `422-434` |
| Observed behavior | Legacy creates separate posting/session rows per R year and keeps separate R-year posting results, but applies the same posting-wide active-month count to every R-year row. A cross-year posting can therefore duplicate months and overstate each R-year target before capping. |
| Current documented behavior | BL-1 requires phase `resident_postings.r_year` for target lookup, but defines the cap for `(resident, posting, session_type)` without saying whether phases are kept separate. BL-6 then groups by `(group_code OR posting_code, session_type_id)` without R year before posting compliance. |
| Analysis | The legacy posting-wide active-month multiplier is a bug/limitation and must not be ported over the current phase-specific target rule. After correcting that multiplier, capping remains non-linear: `sum(min(raw_i,target_i))` can differ from `min(sum(raw_i),sum(target_i))`. For one R1 month target 2/raw 3 and one R2 month target 4/raw 0, corrected phase-first cap is 2 while merged cap is 3; literal C instead uses two months on both rows, targets [4,8], and caps [3,0]. Current documents do not state separate-result versus merged-result behavior. |
| Implementation consequence | A mid-period R-year change can change counted achievement, percentage, shortage, result row count, and clawback inputs solely from aggregation order. |
| Recommended documentation action | Explicitly reject C’s duplicated posting-wide active-month multiplier; define whether correctly phase-weighted R-year contexts produce separate compliance results or one posting result, the exact raw/target/cap order, and how the chosen result grain feeds posting groups, snapshots, dashboards and clawback. If merging is intentional, classify the result-shape change explicitly. |
| Decision required, if any | Cap and report separately per R year, or merge phase raw/targets before cap; if merged, how phase-specific session targets and later financial-year evidence are retained. |
| Required regression test | G-09, including resident and admin/batch parity and the approved clawback handoff shape. |

#### F-23 — Multi-posting reliability cardinality and scope

| Required field | Evidence/conclusion |
|---|---|
| Finding ID | F-23 |
| Classification | `DOC_AMBIGUITY` |
| Severity | MEDIUM |
| Legacy source file | `MATA R Scripts/A/A_Masterfiles v3.R`; no legacy `compliance_unreliable` annotation equivalent |
| Legacy line range | A `405-535` |
| Legacy function/block/object | Multi-posting string/rule transformations; no reliability-flag calculation |
| Relevant R expression or unique fragment | Legacy replaces/collapses configured posting strings but does not define a Boolean warning cardinality for unmatched two-versus-three-plus postings. |
| Current documentation file | `docs/business-logic.md` |
| Current documentation section | BL-7 `598-618` |
| Observed behavior | No exact legacy flag exists to settle current warning cardinality or month-versus-period scope. |
| Current documented behavior | BL-7 first refers to “more than one distinct” posting in a reporting period, then says the flag fires “only when two posting codes” are detected in the same month; its pseudocode relies on an undefined `is_dual_posted`. |
| Analysis | “Two” can mean exactly two or colloquially two-or-more, and the reporting-period opening sentence conflicts with the same-month predicate. Arithmetic fallback is independently documented, but the audit/reliability annotation for three-plus postings is not deterministic. |
| Implementation consequence | The same unmatched three-posting month can be labelled reliable or provisional depending on interpretation, changing API/report warnings even when arithmetic is identical. |
| Recommended documentation action | Define the date grain and explicit cardinality predicate (for example `count(distinct posting_code) >= 2` within one resident-month), the evidence payload, and behavior after a rule match. |
| Decision required, if any | Exact-two versus two-or-more, and reporting-period versus resident-month detection scope. |
| Required regression test | G-41 with both the annotation Boolean/reason/evidence and unchanged independent calculations. |

## 5. Confirmed Resolved Gaps and Intentional Departures

These differences must **not** be “corrected back” to legacy behavior.

| Current rule | Legacy behavior/evidence | Classification | Why the current rule wins |
|---|---|---|---|
| Authenticated, structured direct submission | B parses free-text MCR/name, CSV columns and timestamps (`29-700`) | `LEGACY_DISCARD_CONFIRMED` | Transport workaround eliminated by the application architecture. |
| Event/source/mapping resolution instead of fuzzy target matching | C normalizes strings and takes `rowno_matched[1]` (`113-180`) | `ARCHITECTURAL_TRANSLATION` | Persisted source IDs, scoped mappings, and validation provide the intended outcome without first-match ambiguity. |
| No resident-dashboard spreadsheet feedback loop | B reads error codes from generated dashboards (`759-857`) | `LEGACY_DISCARD_CONFIRMED` | API/DB state replaces circular workbook control. |
| No response-row duplication for consecutive/dept-meeting answers | B clones FormSG responses (`638-700`) | `LEGACY_DISCARD_CONFIRMED` | Each event/attendance is a discrete DB row. |
| FormF1 is final authority; `Extension` is active | C retains exact `Active` only (`63-64`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Explicit current confirmed decision; account status/RDB LOA must not replace it. |
| Blank/NULL/whitespace FormF1 month is inactive without unknown-status warning | Legacy missing values become inactive through brittle matching | `INTENTIONAL_OVERRIDE_RESOLVED` | Explicit parser/current-system rule. |
| AY boundaries are DB data and inclusive | B uses external changeover matrices (`148-166`) | `ARCHITECTURAL_TRANSLATION` | The resolved bucket label selects FormF1 for both numerator and denominator across the whole bucket. |
| `resident_postings.r_year` per phase; `ALL` sentinel | A/B use external date mapping and a long sentinel | `ARCHITECTURAL_TRANSLATION` | Use phase R-year; 20 programmes use `ALL`, while SPORTSMED/PALLMED preserve R4–R6. |
| Phase-specific active-month targets at an R-year change | C computes posting-wide active months without R year, then applies that count to each R-year row (`286-295`, `380-395`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Weight target and cap separately per physical-posting/session-type/R-year context, then sum; do not duplicate months. |
| Generic `multi_posting_rules` and `active_months_weight` | A hardcodes/replays workbook string replacements; C has brittle GASTRO branch | `ARCHITECTURAL_TRANSLATION` | DB configuration replaces spreadsheet code. Half-month applies 0.5 through the weight once and leaves TTF target unchanged. |
| Posting groups seeded from TTF Column E | C uses `Posting Site(Dashboard)` labels | `ARCHITECTURAL_TRANSLATION` | Preserves grouping outcome while keeping member targets explicit. Do not conflate with multi-posting rules. |
| Final A-J TTF and persisted event source evidence | Legacy TTF has only A–J and FormSG session type is matched directly | `DOCUMENTED_NEW_BEHAVIOR` | E2+B2 supersedes the former Column K transition: final TTF never creates source identities from workbook text, and future read-time resolution begins from persisted event evidence. |
| STP is not a system input | Legacy attendance/session matching depends on FormSG/TTF strings; no current STP ingestion is authorized | `LEGACY_DISCARD_CONFIRMED` | Final A-J TTF neither accepts Column K nor creates Teaching Names/mappings from workbook text; do not add an STP parser or hidden dependency. |
| Zero targets remain visible/auditable but are compliance-inapplicable | Legacy C can retain numeric zero rows and produce undefined `0/0` displays | `INTENTIONAL_OVERRIDE_RESOLVED` | Explicit current guardrail prevents false met/surplus/shortage/clawback. |
| Global session types excluded before source/mapping resolution | No exact R equivalent | `DOCUMENTED_NEW_BEHAVIOR` | Explicit confirmed rule; trackable attendance is not necessarily PTT compliance. |
| PH event/ad-hoc creation hard-blocked | B accepts/rejects PH rows after submission, including emergency subsets (`896-925`, `1014-1017`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Confirmed current product decision. Do not recreate PH exception ingestion. |
| Only confirmed URO, DERM and ORTHO weekend rules | B also accepts SIG, FM, ANAES and emergency postings (`923-947`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Later PC-confirmed list supersedes R. Schema’s stale emergency note must be patched. |
| ORTHO mutation is read-time and raw attendance is preserved | B mutates the working attendance data (`912-918`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Auditability/current decision; the exact original type, adjusted-time order, Saturday window, and Sunday exclusion are now confirmed. |
| Tag flow is same physical posting/R-year context, alphabetical, one-for-one, with consumable donor balance | R may cross postings with the same prefix and can double-spend donors (`403-443`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Confirmed raw-minus-row-70% supply and row-70% demand make the effect deterministic; decrementing supply fixes double-spend. |
| Tag participation requires `is_reallocatable=true` and a valid tag | C keys on non-NA `Tag`; its separate reallocation flag is not consumed | `INTENTIONAL_OVERRIDE_RESOLVED` | Current TTF schema/validator makes participation explicit; a stray tag alone must not move sessions. |
| FM uses the standard engine | D1 selects a separate FM workbook template (`202-213`) | `INTENTIONAL_OVERRIDE_RESOLVED` | Template selection is not a separate compliance engine/formula. The FM template is also an external clawback-rate source read by E, so its missing cells remain an F-14 evidence gap; retain only confirmed FM attribution/parser annotations in the compliance path. |
| Countable native ad-hoc uses fixed assigned-posting 1h attribution | Legacy FormSG does not implement the current dedicated authenticated branch | `DOCUMENTED_NEW_BEHAVIOR` | Detailed BL-9/API semantics supersede broad “same treatment” shorthand; selected attended keyword/duration must not drive compliance. |
| Native/external attendance uses separate tables; external never enters NHG math | B identifies/filter non-residents from FormSG (`1019-1059`) | `ARCHITECTURAL_TRANSLATION` | Explicit security/data-boundary decision. |
| Period snapshots/final close are not legacy F2 behavior | F2 only copies/deletes files and RDS snapshots | `LEGACY_DISCARD_CONFIRMED` | File archival is not a reliable compliance freeze. Any MATA final-close workflow remains deferred with clawback. |
| Unformatted future clawback failure predicate | E applies `format(...,digits=2)` before comparison (`36-41`) | `INTENTIONAL_OVERRIDE_RESOLVED` | A future clawback candidacy check must reuse the unrounded ordinary-compliance percentage; all financial behavior remains deferred. |

## 6. Documentation Gaps

### 6.1 Current unresolved/deferred register

No ordinary non-clawback calculation decision remains unresolved at specification level. The current open register is clawback-only:

| Deferred area | Why deferred |
|---|---|
| Norm-rate values, persistence, effective dating, and missing-rate behavior | No authoritative financial catalogue or safe failure contract exists. |
| Funding/clawback R-year and financial programme classification | Legacy positional/FormF1 evidence is not a current rule. |
| Extension/R7/SAF/SCDF granularity and precedence | Row visibility, amount, and overlapping reasons are unconfirmed. |
| Grouped identity and billing attribution | Compliance grouping does not determine financial row/billing identity. |
| Financial precision and rounding | Decimal scale/mode/timing are unconfirmed. |
| Final-close transaction, rerun, reopen, and idempotency | Legacy F2 archival is not a database close contract. |

Display/export rounding is a non-blocking presentation decision because API decision values remain unrounded. Historical migration remains separately tracked outside the ordinary Phase 6-A calculation contract.

<details>
<summary>Original 2026-07-17 gap register (historical; resolved rows are not current gaps)</summary>

The table below preserves the reasons the Phase 6-A decisions were requested. Only its clawback/final-close rows remain open.

| Gap | Finding | Why current documents do not resolve it | Required addition |
|---|---|---|---|
| Persisted surplus invariant and carry/resumption algorithm | F-05 | BL-4 names persistence/hibernation but never defines existing-balance input, idempotent recomputation, consumption, or raw/capped source. | A state-transition/invariant specification with examples and concurrency behavior. |
| Combined-posting component event attribution | F-11 | BL-8 describes component events and combined targets; BL-6 only has exact posting joins. | Explicit component map and ordered catalogue/target resolution. |
| Tag value grammar | F-06 | Only examples and “all but last char” exist. | Allowed regex/normalization and multi-digit/decimal/space policy. |
| Norm-rate data and durable source | F-14 | Missing templates contain legacy cells; no current rate table/seed/version exists. | Owner-approved values, category definitions, period-effective storage and audit provenance. |
| Confirmed IM-sub-specialty clawback set | F-14 | BL-10 contains an empty TODO; one RDS snapshot is evidence, not a durable decision. | Confirmed code list or a maintained classification field/table. |
| Cross-R-year compliance cap/result grain | F-22 | Phase R year drives target lookup, but BL-6 drops R year from its group key; no rule chooses phase-first versus merged capping/result rows. | Exact cap/aggregation order and result/handoff shape for mid-period R-year changes. |
| Clawback funding R year | F-15 | FormF1 R-year overwrite is discarded, phase values can be `ALL`/multiple, and result needs one value; year-dependent rate branches cannot use `ALL` as a rate key. | Funding-year source plus mid-period split/proration and persisted audit-year rule. |
| Mixed Active/Extension clawback semantics | F-15 | “Extension status resident” has no any/all/per-month definition. | Exact suppression grain and amount rule. |
| Overlapping clawback suppressions | F-15/F-16 | One candidate can be R7, Extension and SAF/SCDF, while current documents disagree on no-row versus zero-row and persist only one reason. | Precedence, row visibility, amount and single/multiple-reason representation. |
| Standalone/posting-group clawback identity and billing | F-16 | Compliance can be keyed by `group_code`; result requires one posting FK/static billing department; no current resident/month billing schedule replaces E’s legacy first-month lookup. | Billing source/time grain plus standalone and multi-member allocation/selection. |
| Missing rate/year failure state | F-16 | BL pseudocode silently returns zero without a valid suppression reason. | Fail-close or explicit error-state contract; never silent financial exemption. |
| Catalogue match with missing teaching-target row | F-17 | BL-6 specifies no-catalogue exclusion, but does not separately state the outcome when a catalogue row resolves and its target row is absent/inapplicable. | A fail-safe configuration-error or exclusion rule; never infer a target. |
| Catalogue keyword case/whitespace normalization | F-17 | BL-6 shows exact equality; domain docs do not define case-folding or whitespace normalization, and the secondary decision log explicitly leaves it unresolved. | One canonical value/matching rule applied at upload, uniqueness, event creation/submission and read time. |
| Financial decimal/rounding contract | F-16 | R calls `round`, Python pseudocode calls `round`, schema stores decimal; tie and intermediate precision are unstated. | Decimal precision, intermediate scale, final rounding mode, and timing. |
| Resident-visible native-programme event attribution while posted elsewhere | F-17 | Event visibility can include native programme events, but BL-6 exact phase/event posting join excludes them. | Explicit compliance posting/target rule or explicit display-only status. |
| Duplicate/overlap action for distinct events | F-21 | DB uniqueness handles only one `(resident,event)` pair; BL-5 defines an interval comparator but not pair scope, ordering, mutation stage, persistence status, rejection, or which side counts. | One deterministic scheduled/ad-hoc conflict policy, interval algorithm, stored status, API response, and numerator rule. |
| Display rounding policy | F-20 | D2 rounds upward, while current API does not define presentation precision. | Separate raw API values/decision values from optional export/UI formatting. |
| Final-close generation contract | F-14–F-16 / BD-16 | Current docs say future/deferred and do not define atomicity, a natural unique key/replacement rule, rollback, immutable provenance, or rerun/reopen behavior. | An owner-approved close/freeze contract before clawback generation is implemented; JIT compliance can be designed after core blockers resolve. |

</details>

## 7. Documentation Contradictions and Ambiguities

### 7.1 Current disposition

The non-clawback contradictions listed in the historical table below are resolved in the domain source-of-truth documents. In particular: raw-count transfer precedes caps; ledger state is raw-minus-target and never carry-in attendance; FormF1 follows the AY label; half-month weighting occurs once; SPORTSMED/PALLMED use R4–R6; R-year contexts cap separately; percentage is canonical; combined/native attribution is explicit; persisted source/mapping resolution is exact and scoped; later overlaps are rejected; ORTHO is exact-type/adjusted-time/Saturday-only; resident/admin calculation shares one contract; and the snapshot example is corrected.

Remaining ambiguity is clawback-only and remains deferred. The multi-posting reliability annotation and display rounding are non-blocking response/presentation details; they do not change specified arithmetic.

<details>
<summary>Original contradiction table (historical audit state)</summary>

Rows marked as blocking in this preserved table describe the pre-decision state. Domain documents now supersede them except for clawback/final-close rows.

| Conflict | Evidence | Domain authority / winner | Patch required |
|---|---|---|---|
| Post-cap reallocation conserves posting total, while prose says it fills compliance shortfall | BL-3 `141`, `173-186`; BL-2 `91-119`; legacy C `399-506` | `business-logic.md` must be made internally coherent; no current line wins | Blocking stakeholder decision (F-04) |
| BL-3 forbids cross-posting tag flow, while BL-6 groups posting-group members before reallocation | BL-3 same-posting scope; BL-6 ordered grouping/reallocation; confirmed `AGENTS.md` no-cross-posting guardrail | No-cross-posting guardrail wins: transfer per physical posting, then aggregate the posting group | Reorder/clarify BL-6; do not reopen the guardrail (F-04/G-32) |
| Cap-before-posting aggregation guardrail versus BL-6 group-before-cap order | Phase 6-A confirmed guardrail; BL-1 `9-18`, `39-66`; BL-6 `424`, `430-433` | Confirmed guardrail/BL-1 grain win: cap each physical posting/session context before posting-group aggregation | Reorder/clarify BL-6 and lock G-10; do not reopen the guardrail |
| “Capped” surplus versus raw formula | BL-4 `213-231` | BL-4 must define one invariant | Blocking decision (F-05) |
| Duration-driven versus alphabetical tag flow | `AGENTS.md:112` versus `:140`; BL-3 `137-143`; schema target note around `266` | BL-3 and later confirmed AGENTS rule win: alphabetical | Replace stale duration-only wording; do not reopen decision |
| Same-prefix group versus same-exact-tag validator | BL-3 `137`, `157-169`; `parsing.md:590-593` | Parsing must conform to BL-3 after grammar decision | HIGH patch (F-06) |
| Half target and half active month versus one multiplication formula | BL-1 `11-18`, `36-37`; BL-8 `648-652`; schema multi-posting note | Business formula plus direct R posting path support one weight | Blocking clarification (F-07) |
| Calendar FormF1 versus AY bucket/start-month SQL | BL-1 `25-34`; BL-5A; BL-6 `423-425`, `510-513` | BL must add missing cross-boundary rule; SQL cannot decide product semantics | Blocking decision (F-08) |
| No-R-year flag versus subspecialty remap | BL-11 `860-887`; schema `73-108`; parsing `155-178` | Programme configuration owner must resolve; parser order currently makes `ALL` win | Blocking decision (F-09) |
| Phase R-year target lookup versus BL-6 grouping without R year | BL-1 `9-24`, `68-70`; BL-6 `422-434`; legacy C `380-395`, `512-518` | No current line determines phase-first versus merged cap/result grain | Blocking decision (F-22/G-09) |
| `met`/colour based on ceiling count versus percentage | BL-2 `95-127` | BL-2 must define one predicate for fractional target | Blocking decision (F-10) |
| Combined target label versus component event exact join | BL-8 `637-644`; BL-6 `426-430` | BL-8 establishes product scenario; BL-6 needs translation algorithm | Blocking gap (F-11) |
| Normative JIT steps versus admin SQL | BL-6 `422-435` versus `487-590`; API `1063-1067` | Ordered BL-6 is domain authority, subject to blockers | Replace/mark SQL non-normative; parity required |
| ORTHO named-type mutation/null-type seed and raw-time-before-mutation order | BL-5 `307-325`, `344-354`; schema `636-646`; B `912-918`, `940-941` | BL-5 needs an owner-approved predicate/order; direct R proves legacy mutation-before-acceptance only | HIGH blocking patch (F-13) |
| Emergency posting accepts weekends/PH versus confirmed removal/hard block | schema posting-code note `128`; schema weekend notes `647`; BL-5 `273-275` | BL-5 and confirmed seed win | Remove stale schema note |
| One catalogue keyword versus duration tiebreaker | schema catalogue unique rule around `308`; parsing `493`, `592`; BL-6 `428` | Schema controls what can persist; product must choose cardinality | HIGH cross-file patch (F-17) |
| Global type visibility versus mandatory catalogue at submission | API event visibility `1394-1404` versus attendance validation near `1422`; BL-6 `427` | BL-6/global-session schema win | API patch (F-17) |
| Native-programme event visibility outside assigned posting versus exact phase/event join | API resident visibility rule versus BL-6 `422-430`; legacy C `113-180` | No current domain rule selects display-only, native target, or assigned-posting attribution | HIGH owner decision and cross-file patch (F-17/G-35) |
| Distinct-event interval comparator versus undefined reject/store/exclude semantics | BL-5 `368-381`; schema `(resident_id,event_id)` uniqueness; API attendance mutation | No current line defines the outcome or which event(s) count | HIGH owner decision and cross-file patch (F-21/G-34) |
| “More than one”/reporting-period scope versus “only when two”/same-month reliability flag | BL-7 `598-618` | No direct legacy authority; BL-7 must define an explicit cardinality and date grain | MEDIUM clarification (F-23/G-41) |
| Posting-level compliance versus session-type dashboard colour | BL-2 `91-127`; API dashboard `1546-1557`; monthly report `1069-1075` | BL-2 wins | Reshape examples: posting summary plus display-only breakdown |
| SAF/SCDF no row versus shown suppressed row | BL-10 `808`; schema `899`, `903-908`; API `1100-1106` | `business-logic.md` controls calculation, but persistence/API must align after owner confirms | Blocking clawback decision (F-16) |
| One suppression-reason field versus overlapping R7/Extension/employer conditions | BL-10 suppression branches; schema `clawback_suppressed_reason`; API reason enum | No current precedence or multi-reason representation exists; no-row employer handling can pre-empt every stored reason | Blocking decision (F-15/F-16/G-36) |
| Missing clawback rate returns zero versus financial error | BL-10 `847-851`; schema describes zero as exemption; legacy E `85-89` produces error text | BL-10 must add fail-safe semantics | Blocking decision (F-16) |
| Posting-group result versus `clawback_records.posting_code` | parsing `508-512`; schema `892-900` | Schema must support calculation identity selected by business logic | Blocking schema/business patch |
| Legacy resident/month billing versus current static `posting_codes.billing_dept` | E `129-133`; schema posting/clawback fields | Legacy is evidence, not automatic authority; finance owner must confirm the intended replacement/source and time grain | Blocking billing decision (F-16/G-37) |
| Surplus upsert versus no unique key | BL-4 `224-231`; schema `453-469`, `1131-1139` | Schema authority must add a constraint after tuple semantics confirmed | HIGH patch (F-18) |
| Snapshot example arithmetic | schema `855-873` says target70 21, achieved 18, percentage .857, met true | BL-2 formula wins | Correct example |
| FM 5h override absent from ordered pipeline | BL-FM `672-679` versus BL-6 `422-435`/SQL | BL-FM is authoritative for FM annotation | Insert exact step before grouping/catalogue target attribution |
| Ad-hoc “same treatment” shorthand versus fixed 1h attribution | `AGENTS.md:132`; API `1519-1529`; BL-9 | Detailed BL/API rule wins | Replace shorthand to avoid treating selected display duration as compliance type |
| Clawback source named Script F | decision log `900-905`; actual E header/calculation | Direct R E wins; decision log is secondary | Correct attribution; do not rewrite history as authority |
| FM report template attributed to E | decision log `951-957`; D1 `202-213`; E only reads rate cells `31-34` | Direct R wins | Correct attribution |

</details>

The decision log also contains stale entries describing defects that have already been corrected in domain docs (for example its old FM and FormF1-year notes). Those entries remain historical context and must not override the current domain files.

## 8. Word Audit Accuracy Review

`MATA_Core_Business_Logic_Audit.docx` is useful as a navigation aid, not as executable truth. Body-paragraph references below are `python-docx` body indices; table references are stable table numbers. DOCX rendering/page validation was not performed because this was a content audit and the report was the only authorized output; paragraph/table references are extraction indices, not page citations.

### 8.1 Correct or substantially correct claims

- Body P17–P30 correctly identifies C’s capping formula and that active months can be fractional.
- Body P41–P67 and Table 5 correctly identify posting aggregation, percentage, `ceiling(70%)`, shortage, and monthly display-only intent for ordinary integer cases.
- Body P76–P99 correctly shows all-but-last-character prefix extraction and ascending tag sort in its pseudocode.
- Body P103 onward correctly attributes clawback to Script E. The decision log—not the Word file—misattributes it to F.
- Table 6 correctly identifies that E reads standard/FM norm-rate cells from separate report templates and prorates annual rate by months.
- Body P195–P212 correctly records sorted, consecutive-only duplicate/overlap comparison; B `882`, `952-996` confirms it.
- Table 7 is a useful historical list of most weekend exceptions, provided it is clearly labelled legacy rather than current.
- Section 1 correctly discards most FormSG column parsing, free-text identity parsing, dashboard error feedback, and CME free-text matching.

### 8.2 Incorrect, unsupported, or oversimplified claims

| Word claim | Direct evidence/correction | Classification |
|---|---|---|
| P5 says “all six MATA R scripts” | There are eight `.R` files: A, B, C, D1, D2, E, F1, F2. A–F are stages. | `AUDIT_SUMMARY_ERROR` |
| Section 1 Table 2 says duration-suffix parsing is fully discarded | Current TTF still parses `[Xh]` from the session-type name (`parsing.md:514-524`). | `AUDIT_SUMMARY_ERROR` |
| Table 2/P162 says resident current R year replaces mapping | Current compliance explicitly uses `resident_postings.r_year` by phase, never `residents.r_year`. | `AUDIT_SUMMARY_ERROR` |
| Table 2 says multiple-posting resolution is redundant | `multi_posting_rules` remains essential at RDB parse time. | `AUDIT_SUMMARY_ERROR` |
| Table 3 suggests attendance `status='excluded'` | Schema allows `submitted`, `flagged`, `removed`; no `excluded`. | `AUDIT_SUMMARY_ERROR` |
| GASTRO pseudocode combines halved active months and halved monthly target in one posting formula | C uses active-month reduction for posting `target_100`; target division is only on the monthly-display copy. | `AUDIT_SUMMARY_ERROR` |
| P70–P74 say higher digit means longer and flow higher→lower | Its own pseudocode sorts ascending A1→A2. Current confirmed convention is earlier tag=longer and flow earlier→later. | `AUDIT_SUMMARY_ERROR` |
| P73 uses `A1.5` as a tier in the same group | `tag[:-1]`/R prefix extraction makes the prefix `A1.`, not `A`. | `AUDIT_SUMMARY_ERROR` |
| Tag pseudocode decrements supply and appears exact | R never decrements `bringover[d]`, so it can double-spend. Current decrement is an intentional safety fix, not an exact translation. | `AUDIT_SUMMARY_ERROR` |
| Tag description omits raw transfer and final recap | C transfers raw `Achieved`, then recomputes cap at `499-506`. | `AUDIT_SUMMARY_ERROR` |
| Exact green/amber/red is presented as R logic | No available R source applies these colours; D2 writes percentage to missing templates. Current BL-2 is authoritative. | `LEGACY_AMBIGUITY` |
| Clawback trigger is raw `<0.70` | E uses `format(percentage,digits=2)<0.7`. Current system should explicitly reject that formatting artifact. | `AUDIT_SUMMARY_ERROR` |
| Clawback pseudocode captures exact rate input | It omits E’s FormF1-column-8 R-year overwrite and SIG fallback (`43-59`), and a `.get(...,0)` default does not exist in R. | `AUDIT_SUMMARY_ERROR` |
| Table 6 calls the first standard norm row junior/R1 while pseudocode uses it as the SS/IM senior rate | E proves only positional `normtab[1,2]` use for SS/IM. The missing template is required to establish that cell’s business category. | `AUDIT_SUMMARY_ERROR` |
| R-year assignment is described as teaching-date logic for all uses | A assigns posting R year from posting start date (`565-607`); B separately assigns attendance R year from event date (`512-578`). | `AUDIT_SUMMARY_ERROR` |
| Table 7 is presented as “must count” current behavior | SIG, FM, ANAES and emergency rules were deliberately removed; PH creation is now blocked. It also omits the exact legacy PH subset distinction. | `INTENTIONAL_OVERRIDE_RESOLVED` |
| Table 8 says FormF1 active status is partially redundant to account status | FormF1 is the final current denominator authority. | `AUDIT_SUMMARY_ERROR` |
| Table 8 says event FK makes posting resolution fully redundant | Combined postings, native-programme visibility, ad-hoc fixed attribution and FM 5h override still need explicit posting logic. | `AUDIT_SUMMARY_ERROR` |

### 8.3 Important omissions

- C’s donor balance reuse bug and possible cross-posting tag-prefix grouping.
- The GASTRO hardcode’s dependence on exactly two frequency rows, which can fail with multiple session types.
- B’s single-future-row exclusion bug.
- E’s two-significant-digit candidate formatting, FormF1 R-year overwrite, first-month billing lookup, missing-rate failure modes, and zero-candidate `1:nrow`/row-name failure risk.
- D2’s upward display rounding.
- F1/F2 are rollover/archive only and do not implement period close or clawback.

### 8.4 Safe use of the Word audit

It remains safe for locating the broad C/E topics and identifying discarded FormSG workarounds. It is unsafe as direct implementation pseudocode unless each claim is revalidated against the `.R` files and current domain authority. No implementation citation should point only to the Word audit.

## 9. Phase 6 Implementation Contract

This is the current non-clawback specification contract. It does not assert that code or tests exist.

1. Resolve one applicable reporting period, resident scope, event-date physical posting phase, phase R-year, and inclusive AY bucket. Use the bucket label to select the FormF1 row for both numerator and denominator across the whole bucket.
2. Read native attendance only. The submission service has already rejected later distinct-event overlaps while preserving earlier accepted attendance; same-event uniqueness remains separate.
3. Resolve parse-time posting identity by the applicable distinct rule: existing main code, configured canonical combined code, or two half-month rows with unchanged targets and weight 0.5 once. Retain physical posting identity for tag transfer; posting groups aggregate only later.
4. For an approved native-programme event outside the assigned posting, preserve the event and project exactly one assigned-posting `Department/Programme Teaching [1h]` session using the assigned target. Normal assigned-posting events retain their persisted scheduled-event source evidence; a future resolver must use that evidence rather than display text or the retired catalogue.
5. Exclude active global session types before source/mapping resolution. Otherwise resolve the explicit Teaching Name source ID through its scoped period, resident programme, assigned/compliance posting, phase R-year, and mapping. Same display names may have distinct sources or mappings; never fuzzy-match.
6. Apply weekday/weekend rules. For ORTHO, only the exact original 3h type subtracts two hours from end time, projects to the 1h type, and then tests the adjusted interval against Saturday 08:30–10:30. Sunday is excluded; other ORTHO types do not mutate and require any separately applicable acceptance rule.
7. Exclude untracked and zero-target rows from ordinary math while retaining audit/visibility. Count eligible sessions one-for-one; duration never multiplies count.
8. Calculate correctly FormF1-gated `target_100` for each `(resident, physical posting, session type, R-year context)`. Never apply posting-wide months to every R-year row.
9. Recompute and idempotently replace persistent pre-tag ledger state as `max(cumulative raw eligible attendance - cumulative target_100, 0)` per resident/physical posting/type/period. Never read it back as attendance or a transfer balance.
10. Reallocate raw achieved counts within one physical posting, R-year context, and tag prefix. Sort tags alphabetically; earlier donates to later; supply is raw above the type's `ceil(target_100 × .70)` and demand is only to that threshold. Decrement supply after every one-for-one session transfer. Never transfer hours or cross postings/R-year contexts.
11. After all transfers, cap each session type/R-year context at its own `target_100`. Sum separately capped achievement and targets into the physical posting, then aggregate configured posting-group members.
12. For positive target, compute unrounded `percentage = achieved_and_counted / target_100`; set `met_70pct = percentage >= .70`; green at ≥70%, amber at ≥50% and <70%, red below 50%. Display `target_70 = ceil(target_100 × .70)`. Shortage is zero if met, otherwise `ceil((target_100 × .70) - achieved_and_counted)`.
13. Attach non-arithmetic reliability/display annotations without changing canonical values. Resident and admin/report surfaces execute this same contract and must return parity-identical decision values.
14. Keep clawback/final-close generation outside this contract and **DEFERRED**. A future candidacy check reuses the unrounded percentage, but no finance, suppression, billing, rounding, or close behavior is inferred.

### 9.1 Non-negotiable parity requirement

Resident JIT and admin batch paths must share the same rule primitives or pass the section 10 fixtures with identical raw counts, targets, exclusions, transfers, caps, metrics, and annotations. Performance is not permission to omit rules. The source-of-truth documents make no claim that this parity is already implemented.

<details>
<summary>Original pre-decision implementation contract (historical)</summary>

The following ordered contract contains `PENDING` markers from the 2026-07-17 audit. They are superseded for non-clawback behavior by the current contract above; clawback markers remain deferred.

1. **Resolve reporting period and resident scope.** Resolve exactly one date-applicable/effectively active reporting period for current-date/event-date workflows; fail closed on overlap. For an explicitly selected historical report, scope to that period and the caller’s authorized programme/resident. Source: `docs/business-logic.md` BL-6 `408-445`; `docs/api.md` reporting-period/report endpoints; `AGENTS.md` authorization rules.

2. **Enforce the native-attendance-only boundary and carry status evidence.** Load only native `attendance_records` in scope and carry their persisted status; never join `external_residents` or `external_attendance_records` into NHG compliance, surplus, snapshots or clawback. `submitted` is the baseline countable status and `removed` never enters the numerator. **PENDING F-21/BD-15:** either conflict resolution is a submission-time invariant and this step may safely select finalized `submitted` rows, or relevant `flagged`/paired rows must remain available through step 10; do not discard conflict evidence before the approved policy runs. Source: BL-6 step 6 `426`; BL-12; `docs/schema.md` attendance tables; `AGENTS.md` external-resident rules.

3. **Load active posting phases.** Query `resident_postings` overlapping the reporting period with status `active` or `loa_working`; retain phase start/end, posting code, `r_year`, month label and `active_months_weight`. Use phase `r_year`, never a resident-level display/current year. Source: BL-1 `21-27`; BL-6 `412-423`; BL-11; schema `resident_postings`.

4. **Apply the FormF1 denominator/numerator gate.** `Active`/`Extension` rows are active; `Inactive`/blank/NULL/whitespace are inactive. Exclude inactive resident-month target weight and associated attendance. Unknown nonblank status uses the documented active fallback and warning. **PENDING F-08:** define how a calendar FormF1 month gates an AY phase crossing a calendar boundary. Source: BL-1 `25-34`; `docs/parsing.md` FormF1; schema `form_f1_records`.

5. **Resolve the AY month bucket.** Resolve `programmes.ay_date_category`, then exactly one `academic_month_boundaries` row where `event_date BETWEEN start_date AND end_date` (inclusive). Do not branch on JR/SR text. Fail safely on missing/overlapping boundaries. **PENDING F-08:** align this event bucket with step 4’s calendar gate. Source: BL-5A and BL-6 step 4 `425`; `docs/parsing.md` AY Dates; schema academic boundaries.

6. **Determine compliance posting identity and fixed-attribution branches.** A countable native ad-hoc row first maps to the assigned posting and fixed `Department/Programme Teaching [1h]`; no client-selected teaching name or attended posting changes that attribution. For non-ad-hoc normal attendance, use the resolved posting and apply the documented FM 5h compliance-posting override. For a configured `posting_groups` member, retain the physical member posting and its phase/target contribution while recording `(programme_code, group_code)` as the later aggregate identity. Keep `multi_posting_rules` parse-time semantics distinct from posting groups. **PENDING F-11:** define component-event-to-combined-label attribution. Source: BL-1 posting groups `39-66`; BL-8; BL-FM `672-682`; BL-9; `docs/api.md` ad-hoc endpoint; `docs/parsing.md` TTF Column E/multi-posting.

7. **Exclude global session types first.** An explicit `global_session_type_id` is stored/auditable but excluded from numerator, denominator, source/mapping resolution, reallocation, surplus and clawback. Submission must not require a TTF-derived mapping for a valid global type. A both-null legacy row is never classified as global from display text. Source: BL-6 step 6/7 `426-427`; schema global session types; `AGENTS.md` global-type rule.

8. **Resolve source/mapping/session context at read time.** For non-global, non-fixed-ad-hoc records, start with the persisted Teaching Name source ID and its scoped mapping, then apply event posting context, resident programme, phase R year, reporting period, and the owner-approved target rule. A native fixed-ad-hoc row instead requires the assigned-posting fixed 1h target and must return unavailable/not-countable if it cannot be resolved. Attendance records never store session type. **PENDING F-11/F-17:** combined-posting context, native-programme event attribution outside the assigned posting, mapping/target cardinality, and missing-mapping/target behavior must be resolved. Do not use a catalogue, keyword, Column K, duration tiebreaker, or display-text lookup. Source: BL-6 step 7 `428`; BL-9; final schema source/mapping sections.

9. **Apply weekend acceptance or mutation.** Weekday records pass. Weekend records count only when a configured exception matches programme/posting, day, time and optional original name/type. Unaccepted weekend attendance remains stored and is excluded. For a valid ORTHO mutation, preserve raw attendance, substitute the configured session type/duration for compliance, and resolve the target for the mutated type. **PENDING F-13:** constrain the ORTHO mutation predicate, separate it from general acceptance, and decide whether raw or adjusted times are tested first. Source: BL-5 `277-366`; schema weekend exceptions.

10. **Resolve distinct-event conflicts and final status eligibility; filter tracked/zero targets.** After final session/weekend resolution and before counting, apply one deterministic resident/date conflict policy across distinct scheduled and ad-hoc events, then emit the final countable row set/status outcome. **PENDING F-21/BD-15:** define submission-time versus read-time resolution, all-pairs/interval scope, touching endpoints, raw-versus-mutated comparison, reject/store/flag status, and which side enters the numerator; do not port the legacy adjacent-order artifact by assumption. Then exclude `is_tracked=false` and `monthly_target=0` from all compliance math, percentage, shortage, tag supply/demand, ledger and clawback while preserving visibility/attendance audit. Source: BL-5 duplicate/conflict comparator `368-381`; B `881-883`, `952-1017`; BL-1 `68-72`; BL-3 `140`; BL-6 step 10 `431`; `AGENTS.md` zero/untracked rules.

11. **Count raw achieved sessions.** Count the final approved countable row set emitted by step 10 one-for-one by `(resident, physical compliance posting_code, r_year/phase target context, session_type)`; `submitted` is the baseline status, but do not preclude a different owner-approved flagged-row outcome under F-21. Retain a posting-group key only as a later aggregate identity. An approved combined-posting identity is **PENDING F-11** and must not be inferred. Duration never multiplies count. Retain raw counts for display/audit. Source: BL-1 `21-24`, `39-70`; `AGENTS.md` session-count/no-cross-posting rules; legacy confirmation C `93-106`, `380-384`.

12. **Calculate target 100 and the tag-row threshold.** For each physical posting/R-year target/session context, sum `monthly_target * active_months_weight` over eligible FormF1-gated phases; a posting-group member uses its own monthly target and stays separate until step 16. Persisted TTF monthly target is not changed by a half-month rule. For a tagged session row, calculate a distinct `tag_target_70 = ceil(session_target_100 * 0.70)` only for the approved transfer supply/demand algorithm; never sum these row ceilings to obtain final posting `target_70`. **PENDING F-07:** patch all prose to confirm the single-weight rule. **PENDING F-04/BD-01:** confirm the tag-row threshold, fractional behavior, and its exact supply/demand role. **PENDING F-22/BD-17:** define whether R-year contexts remain separate or merge before step 13. Source: BL-1 `11-24`, `39-66`; BL-3 examples/inputs; BL-8 `646-652`; parsing Column E.

13. **Cap achieved at the approved R-year grain.** Compute `achieved_and_counted = min(raw_achieved, target_100)` before any posting-group aggregation and do not use display-rounded values. **PENDING F-22/BD-17:** decide whether to cap each correctly phase-weighted physical-posting/session/R-year context and retain/sum those results, or merge raw/targets across R-year contexts and cap once. Never reproduce C’s posting-wide active-month duplication across R-year rows. **PENDING F-04:** this is the pre-tag value; the source/effect of later transferable supply still needs a decision. Source: BL-1 `7-24`, `68-70`; BL-3 `141`; legacy C `286-295`, `380-395`, `512-518`.

14. **Calculate/update pre-reallocation surplus.** Exclude zero/untracked targets and preserve the physical posting/department/session-type grain when writing one idempotent ledger row per configured tuple before read-time tag transfers. Do not derive a group-level donor balance. **PENDING F-05/F-18:** the raw/capped formula, prior-balance input, carry/consumption/resumption invariant and unique key must be resolved before any write is implemented. Source: BL-4; schema `surplus_ledger`.

15. **Apply tag reallocation read-time only.** Scope to one resident and one physical `posting_code`; sort normalized tag labels alphabetically; permit earlier-to-later one-for-one transfers; decrement donor balance; never persist post-transfer values to the ledger. Do not sort by duration and never cross physical postings—including members of the same posting group—or tag prefixes. Complete member-level transfers before step 16 aggregates a posting group. **PENDING F-04/F-06:** supply formula/effect, tag-row threshold semantics, and tag grammar. Source: BL-3; confirmed `AGENTS.md` no-cross-posting/alphabetical rules.

16. **Aggregate at posting/posting-group level.** After physical-posting tag transfers, sum final counted achievement and `target_100` across applicable tracked nonzero session types and then across configured posting-group members for the approved compliance identity. Monthly/session-type rows are breakdown/display levels. **PENDING F-22/BD-17:** preserve the approved separate/merged R-year result shape through this aggregation. Source: BL-2 `78-119`; BL-6 steps 9/13 `430-434`; parsing posting groups.

17. **Calculate final metrics.** For `target_100<=0`, return not-applicable with no percentage/met status. Otherwise compute posting `target_70=ceil(target_100*.70)`, percentage=`counted/target_100`, shortage=`max(0,target_70-counted)`, met and colour. Green/amber/red boundaries are 70%/50%. **PENDING F-10:** align the met/colour/clawback predicate for fractional `target_100`; do not let formatted display precision choose status. Source: BL-2.

18. **Attach reliability and display annotations.** Add unmatched multi-posting evidence without changing arithmetic, then apply the approved reliability cardinality/date grain. **PENDING F-23:** BL-7 must choose exact-two versus two-or-more and reporting-period versus resident-month detection; G-41 locks the three-posting outcome after that decision. Return a posting summary plus session/month breakdowns; labels/rounding must not change status. Source: BL-7 `598-620`; API posting/dashboard reports. API examples also require F-17/F-20 patches.

19. **Prepare clawback inputs; keep generation separate.** Expose the failing posting/group/R-year result, eligible active-month measure, phase/funding-year evidence, employer/billing context and period. Do not create `clawback_records` during JIT reads or operational deactivation. **PENDING F-14/F-15/F-16/F-22/BD-16/BD-17:** rates/classification, year-dependent funding year, Extension/overlapping suppressions, standalone/group billing source and identity, employer rows, missing-rate failure, Decimal rounding, cross-R-year result handoff, and the future close’s atomicity/rollback/uniqueness/replacement/rerun contract. Atomic/idempotent close is an audit recommendation, not yet current authority. Source: BL-10; BL-6 operational deactivation note; schema `clawback_records`/snapshots; API clawback/snapshot endpoints.

### Historical parity note

The illustrative batch SQL in BL-6 is not implementation-ready. Once the pending rules are resolved, the resident JIT and admin batch paths must share the same rule primitives or pass all section 10 fixtures with identical raw counts, target values, exclusions, transfers, metrics and annotations. Performance is not permission to omit rules.

</details>

## 10. Required Golden Tests

The following decision-lock fixtures supersede the `PENDING` branches in the historical table. They are recommendations for future tests, not claims that tests exist.

| Fixture | Confirmed expected ordinary-compliance result |
|---|---|
| G-03 fractional half-month target | Keep monthly target 3 and weight .5 once: `target_100=1.5`, displayed `target_70=2`, cap 1.5, percentage 1.0, shortage 0, met/green. |
| G-09 mid-period R-year change | R1 target2/raw3 caps2; R2 target4/raw0 caps0. Sum target6/counted2, displayed target70=5, percentage 1/3, shortage3, fail/red. Never use two posting-wide months on each row or merge raw before caps. |
| G-11 two-tier tags | Raw `[6,2]`, targets `[4,4]`, row 70% targets `[3,3]`: transfer one A1→A2, adjusted `[5,3]`, caps `[4,3]`, posting 7/8=.875, met/green. |
| G-12 three-tier tags | Raw `[6,2,2]`, targets 4 each: A1 supplies one to A2 and one to A3, adjusted/capped `[4,3,3]`, posting 10/12, met/green. |
| G-13 insufficient donor | Raw `[5,0]`, targets 4 each: A1 supply2, transfer2, final `[3,2]`, posting 5/8=.625, shortage1, fail/amber. |
| G-14 multiple donors | Raw `[5,5,0]`, targets 4 each: A1 donates2 and A2 donates1 to A3, final `[3,4,3]`, posting 10/12, met/green. Donor supply is decremented. |
| G-16 ORTHO exact mutation | Exact 3h raw 08:30–11:30 preserves raw rows, adjusts end to 09:30, projects to the 1h type, passes Saturday 08:30–10:30, and counts once. Other ORTHO types do not mutate; Sunday is excluded. |
| G-25 donor cannot be reused | Raw `[6,0,0]`, targets `[3,6,12]`: A1 supply3 goes to A2 only, final `[3,3,0]`; received credits do not become raw donor supply and A1 cannot be spent again. |
| G-26 AY/calendar boundary | AY bucket `Jul-26` includes 3 August. With July Active/August Inactive, the 3 August event and denominator use July, so raw1 and July-bucket target apply. The next AY bucket uses August. |
| G-34 distinct-event overlap | Earlier accepted event remains stored/countable once; later overlapping distinct submission is rejected. Same-event uniqueness remains a separate rejection. |
| G-35 native event outside assigned posting | Preserve the PN event but count exactly one assigned-P1 `Department/Programme Teaching [1h]` session against P1's target; no PN/native-posting result. |
| G-40 half-month multiple types | Weight .5 once with unchanged targets 3 and 1: caps `[1.5,.5]`, posting target2/counted2, met/green. |
| G-45 explicit source identities | Scheduled creation stores an exact source ID plus immutable display snapshot. P1 and P2 may have sources with the same display name but distinct scoped mappings; assigned/compliance posting selects the mapping. Display text is never fuzzy-matched at runtime. |
| G-46 persistent-surplus return | First phase target2/raw4 → ledger2. Return expands cumulative target to4 while raw remains4 → counted4 and idempotently replaced ledger0. Never calculate attendance as `4 + stored 2`. |
| G-47 combined posting | `TTSHDiagRd + NNINeuRad` resolves to existing canonical `TTSHDiagRd & NNINeuRad`; persist/use one row and its TTF target, with no component compliance results. |
| G-48 SPORTSMED/PALLMED years | SPORTSMED R4 and PALLMED R6 persist/match R4 and R6 mapping/target scopes. Neither resolves through `ALL` or SS1–SS3. |

All ordinary fixtures must produce identical canonical values through resident and admin/report paths. Clawback expectations are intentionally absent until its deferred rules are confirmed.

<details>
<summary>Original pre-decision golden-test table (historical)</summary>

The table below preserves the alternatives that motivated the decisions. Its non-clawback `PENDING` branches are superseded by the fixture outcomes above.

### 10.1 Fixture notation

Unless a case overrides it:

- period is H1 2026; resident is a native DR resident; posting `P1` is standalone; phase R year is `R2`;
- FormF1 is `Active`; date is Monday `2026-01-12`, inside exactly one AY boundary and not a PH;
- every attendance row is native, submitted, inside the phase, has an exact catalogue match, and refers to a distinct non-overlapping event interval (or distinct valid date) unless the fixture explicitly tests duplicate/conflict behavior;
- `S1`, `S2`, `S3` are distinct session types; a target notation such as `S1:10/T` means monthly target 10, tracked; `/U` means untracked; `A1` etc. are reallocatable tags;
- each listed phase has weight 1.0 unless `.5` is shown; each listed target is for the phase R year/period;
- “raw” means eligible compliance raw count; when stored-but-excluded differs, both values are shown;
- exact fractions/finite Decimals are authoritative calculation values; a repeating value may show a four-decimal display approximation as `≈.dddd`, which must never be used to choose status;
- a standard unsuppressed clawback formula test may inject annual rate `1200.00`, yielding `100.00` per active month. This tests the formula without pretending that 1200 is a real MATA rate;
- `PENDING` expected results are decision-lock fixtures. They must be converted to one asserted branch before implementation; accepting either branch at runtime is forbidden.

### 10.2 Calculation and exclusion cases

| ID / edge | Complete input (posting; R year; FormF1; targets; attendance/date context) | Expected raw | Expected cap and reallocation | Expected `target_100`; `target_70` | Expected percentage; shortage; status/colour | Expected clawback input/suppression |
|---|---|---:|---|---|---|---|
| G-01 Exactly 70% | `P1`; R2; Active; `S1:10/T`; seven S1 rows on weekday/non-PH dates | 7 | cap 7; no transfer | 10; 7 | .7000; 0; met/green | Not a candidate |
| G-02 Exactly 50% | `P1`; R2; Active; `S1:10/T`; five S1 rows | 5 | cap 5; none | 10; 7 | .5000; 2; fail/amber | Candidate: identity P1, funding R2, active months 1; injected rate 1200 gives 100.00 |
| G-03 Fractional target | Half-month `P1` weight .5; R2; Active; `S1:3/T`; two S1 rows | 2 | cap 1.5; none | 1.5; 2 | 1.0000; 0.5; **PENDING F-10**: count predicate→fail/amber, percentage predicate→met/green | **PENDING F-10**: candidate under count predicate, no candidate under percentage predicate |
| G-04 Zero target | `P1`; R2; Active; `S1:0/T`; two S1 rows | stored 2; compliance 0 | excluded before cap/reallocation | N/A (0 contribution); N/A | N/A; 0; not applicable/no colour | No candidate; no ledger/reallocation |
| G-05 Untracked target | `P1`; R2; Active; `S1:10/U`; seven S1 rows | stored 7; compliance 0 | excluded | N/A; N/A | N/A; 0; not applicable | No candidate; no ledger/reallocation |
| G-06 Inactive FormF1 | `P1`; R2; `Inactive`; `S1:10/T`; seven stored S1 rows in that calendar month | stored 7; compliance 0 | excluded by gate | 0; N/A | N/A; 0; not applicable | No candidate; active months 0 |
| G-07 Blank FormF1 | Same as G-06, monthly cell blank/whitespace | stored 7; compliance 0 | excluded by gate; no unknown-status warning | 0; N/A | N/A; 0; not applicable | No candidate |
| G-08 `ALL` R year | Programme AIM; `P1`; phase/target/catalogue `ALL`; Active; `S1:2/T`; two rows | 2 | cap 2; none | 2; 2 | 1.0000; 0; met/green | Not candidate; compliance must not seek resident current R year |
| G-09 Mid-period R-year change | `P1`; Jan R1/Active has `S1:2/T` and three rows; Feb R2/Active has `S1:4/T` and zero rows | phase raw [3,0]; total3 | literal legacy C (not to port): posting-wide months=2 on each R-year row, caps [3,0]. **PENDING F-22 current branches:** corrected phase caps [2,0]; merged-before-cap gives3 | legacy targets [4,8], target70 [3,6]; corrected separate targets [2,4], target70 [2,3]; corrected merged 6/5 | legacy: R1 3/4=.75 met/green, R2 0/8 shortage6 fail/red; corrected separate: R1 2/2 met/green, R2 0/4 shortage3 fail/red; phase-first merged 2/6=1/3 (≈.3333), shortage3, fail/red; merged-before-cap 3/6=.5, shortage2, fail/amber | Legacy multiplier branch is forbidden. Current result rows/candidacy **PENDING F-22**; funding year and split amount additionally **PENDING F-15** |
| G-10 Posting group, different targets | Group `G` has P1 `S1:1/T` for one month and P2 `S1:3/T` for one month; R2/Active; two P1 + one P2 rows | P1 raw2; P2 raw1; group raw3 | physical caps P1=1, P2=1; no transfer; group counted2 | 4; 3 | 2/4=.5; 1; fail/amber | Candidate; result identity is G, while persisted posting/billing is **PENDING F-16** |
| G-11 Two-tier tag | `P1`; R2/Active; `S1:4/T/A1`, `S2:4/T/A2`; raw S1=6, S2=2 | [6,2] | initial [4,2]. **PENDING F-04**: literal current transfer 1→[3,3]; raw-then-recap→[4,3] | 8; 6 | literal .7500/0/green; raw-recap .8750/0/green | Not candidate either way; asserted session breakdown pending |
| G-12 Three-tier tag | `P1`; R2/Active; three targets 4 tagged A1/A2/A3; raw [6,2,2] | [6,2,2] | initial [4,2,2]. **PENDING F-04**: literal [3,3,2]; corrected raw-recap [4,3,3] | 12; 9 | literal 8/12=2/3 (≈.6667), shortage1, fail/amber; raw-recap 10/12=5/6 (≈.8333), shortage0, met/green | Candidate only under literal post-cap conservation; proves blocker is material |
| G-13 Insufficient donor | `P1`; R2/Active; S1/S2 targets 4 tagged A1/A2; raw [5,0] | [5,0] | **PENDING F-04**: literal [3,1]; raw-recap [3,2] | 8; 6 | literal .5000/2/amber; raw-recap .6250/1/amber | Candidate; amount input uses selected result |
| G-14 Multiple donors | `P1`; R2/Active; three targets 4 tagged A1/A2/A3; raw [5,5,0] | [5,5,0] | **PENDING F-04**: literal [3,3,2]; raw-recap with consumable supply [3,4,3] | 12; 9 | literal 8/12=2/3 (≈.6667), shortage1, amber; raw-recap 10/12=5/6 (≈.8333), shortage0, green | Candidate only under literal branch |
| G-15 Weekend rejected but stored | `P1`; R2/Active; `S1:10/T`; one Sunday row, no exception | stored 1; compliance 0 | excluded before cap | 10; 7 | 0; 7; fail/red | Candidate with active month 1; submission response carries warning |
| G-16 ORTHO mutation | ORTHO posting; phase `ALL`/Active; original 3h type plus mutated `S1:2/T`; Saturday 2026-01-17 raw 08:30–11:30, not PH | **PENDING F-13**: mutation-first gives 1 under S1; raw-window-first gives compliance 0 | mutation-first: adjusted 08:30–09:30, cap1; raw event remains 08:30–11:30. Raw-window-first: excluded | mutation-first 2/2; raw-window-first 2/2 with zero achieved | mutation-first .5000/1/amber; raw-window-first 0/2/red | Candidate either way, but counted/session result differs. Non-3h in-window acceptance is also **PENDING BD-08**; 3h Sunday is excluded under the current Saturday-only seed |
| G-17 Global session exclusion | `P1`; R2/Active; applicable `S1:10/T`; one attendance whose name matches active global type, no catalogue required | stored 1; compliance 0 | global row excluded before catalogue | 10; 7 | 0; 7; fail/red | Candidate based on ordinary target; global row creates no supply/target and submission is accepted |
| G-18 Missing catalogue match | `P1`; R2/Active; `S1:10/T`; one submitted event with unmatched teaching name | stored 1; compliance 0 | silently excluded; no guessed session | 10; 7 | 0; 7; fail/red | Candidate; unmatched attendance is audit-visible only |
| G-19 FM standard engine | FM R1; event/session type at component site is `Department Teaching [5h]`, override to `NHGPlyNHGPly`; two Active months; target there `Department Teaching [5h]:5/T`; seven rows total | 7 | cap 7; standard path, no special FM formula | 10; 7 | .7000; 0; met/green | Not candidate; proves 5h posting attribution annotation, not a session-type change or separate engine |
| G-20 R7 clawback | `P1`; funding/phase R7; Active; `S1:10/T`; five rows | 5 | cap 5 | 10; 7 | .5000; 2; fail/amber | Row present; amount 0.00; reason `R7` |
| G-21 Extension clawback | Case A: one all-Extension month, `S1:10/T`, five rows. Case B: one Active + one Extension month, target 10/month, ten rows | A 5; B 10 | A cap5; B cap10 | A 10/7; B 20/14 | both .5000; shortages 2 and 4; fail/amber | A row present 0.00 reason Extension. Case B **PENDING F-15** any/all/per-month rule |
| G-22 SAF/SCDF | Two failing residents identical to G-02 with current authoritative `residents.employer_tag='SAF'` and `'SCDF'`; their legacy/current P1 billing text is deliberately ordinary | 5 each | cap5 | 10; 7 | .5000; 2; fail/amber | **PENDING F-16 current rule:** BL→no row; schema→row 0 with employer reason. Legacy E would retain these rows because it filters ordinary `billingcol`, demonstrating the source-field change—not an allowed current expected branch. Current classification must use the approved employer field |
| G-23 Non-NHG exclusion | External resident at P1; external attendance rows only; any external posting/target metadata | native compliance raw 0 | no native calculation | no native target/result | no native percentage/status | No native ledger, snapshot or clawback row |
| G-24 Posting ceiling after aggregation | `P1`; R2/Active; `S1:2/T`, `S2:2/T`; raw S1=2, S2=1 | [2,1] | [2,1], none | posting 4; **3**, not sum of per-type ceilings 4 | .7500; 0; met/green | Not candidate |
| G-25 Donor cannot be reused | `P1`; R2/Active; targets `S1=3/A1`, `S2=6/A2`, `S3=12/A3`; raw [6,0,0] | [6,0,0] | **PENDING F-04**: literal capped-first gives [3,0,0] (zero A1 supply); consumable raw-supply gives [3,3,0]; legacy stale balance gives forbidden [0,3,3] | 21; 15 | capped-first 3/21=1/7 (≈.1429), shortage12, red; raw-supply 6/21=2/7 (≈.2857), shortage9, red | Candidate in either approved branch; regression also forbids donor reuse |
| G-26 AY/calendar boundary | **H2 2026 override**; AY bucket labelled July spans 2026-07-08–2026-08-03; weekday event 2026-08-03; July FormF1 Active, August Inactive; `S1:10/T` | **PENDING F-08**: 1 or 0 | pending gate; no transfer | pending active weight; pending target70 | pending | pending; this exact fixture must lock the decision without a weekend confound |
| G-27 Catalogue without target | `P1`; R2/Active; catalogue maps the event keyword to S1, but no matching R2/P1/period teaching-target row exists; one submitted weekday row | stored 1; compliance **PENDING F-17** | no guessed cap/reallocation | no invented denominator | no invented percentage/status | Must produce the approved fail-safe configuration error/exclusion, never a zero-rate/zero-target success |
| G-28 Legacy formatted trigger boundary | `P1`; R2/Active; `S1:23/T`; sixteen S1 rows | 16 | cap16; none | 23; 17 | 16/23 (≈.6957); 1; fail/amber | Current unformatted predicates both make this a candidate; legacy E formats to about .70 at two significant digits and can omit it. Injected rate1200/one month→100.00 |
| G-29 Amount independent of shortfall | Two R2/Active residents at P1, each one month and `S1:10/T`; A has five rows, B has one | A5; B1 | caps A5/B1 | each 10; 7 | A .5000/2/amber; B .1000/6/red | Both candidates; same injected annual rate1200 and one active month produce the same 100.00 amount—shortage/percentage is not an amount multiplier |
| G-30 Fractional clawback multiplier | `P1`; R2/Active; total active-month weight 1.5; `S1:10/T`; ten S1 rows | 10 | cap10 | 15; 11 | 10/15=2/3 (≈.6667); 1; fail/amber | Candidate; injected annual rate1200 gives `(1200/12)*1.5 = 150.00`, rounded once at end |
| G-31 Failing `ALL` programme | ORTHO resident on weekday data; P1 phase/target/catalogue `ALL`; Active; `S1:10/T`; five rows | 5 | cap5 | 10; 7 | .5000; 2; fail/amber | ORTHO reaches the standard year-dependent rate branch, so funding year/rate and row split are **PENDING F-15/BD-11**; `ALL` is not a rate key by assumption |
| G-32 Posting-group tag isolation | Group G has P1 `S1:4/T/A1` raw6 and P2 `S2:4/T/A2` raw2; same resident/R2/Active | P1 6; P2 2 | cap P1=4/P2=2; **no cross-member transfer** because confirmed no-cross-posting rule; then group aggregate6 | 8; 6 | .7500; 0; met/green | Not candidate; member/session breakdown stays 4/2, not 3/3 or a raw-transfer variant |
| G-33 Native ad-hoc fixed attribution | DR resident assigned P1/R2/Active; selects an attended P2 keyword displayed as `Grand Round [2h]`; countable ad-hoc target at assigned P1 is fixed `Department/Programme Teaching [1h]:2/T`; one weekday row | 1 at P1/fixed 1h type | cap1; selected 2h keyword supplies no compliance mapping | 2; 2 | .5000; 1; fail/amber | Candidate input P1/R2; selected keyword/duration is audit/display only. Missing fixed target must return unavailable/not-countable, not guess |
| G-34 Distinct-event conflict | `P1`; R2/Active; `S1:10/T`; two different event IDs for the same resident/date with identical or overlapping intervals; include same/different resolved type variants | stored/raw/action **PENDING F-21** | pending reject/flag/exclude decision | denominator10; counted pending | percentage/shortage/status pending | Clawback input follows approved numerator; same-event duplicate remains DB-rejected separately |
| G-35 Native-programme event outside assigned posting | DR resident assigned P1/R2/Active; programme-native posting PN is separately visible; one submitted weekday PN event has a valid PN catalogue/target while the active phase is P1 | stored 1; compliance attribution **PENDING F-17** | pending display-only versus PN target versus explicit assigned-context rule; no implicit fallback | denominator/count pending the approved identity | percentage/shortage/status pending | Clawback input follows only the approved compliance identity; visibility alone must not invent attribution |
| G-36 Overlapping suppression reasons | Failing R7 resident; one Extension month; employer SAF; `S1:10/T`; five rows | 5 | cap5 | 10; 7 | .5000; 2; fail/amber | **PENDING F-15/F-16:** employer no-row versus stored zero row; if stored, R7/Extension/employer precedence or multi-reason representation must be asserted |
| G-37 Standalone billing changes by month | Standalone P1; R2/Active Jan+Feb; `S1:10/T` each month; ten rows total; legacy resident/month billing evidence says Jan DeptA, Feb DeptB, while current `posting_codes.billing_dept=DeptStatic` | 10 | cap10 | 20; 14 | .5000; 4; fail/amber | Candidate amount with injected rate is 200.00; billing source/department/allocation is **PENDING F-16/BD-13** and must not silently copy legacy first-month or current static behavior |
| G-38 Decimal half-cent | `P1`; R2/Active one month; `S1:10/T`; five rows; inject annual rate `1200.06` | 5 | cap5 | 10; 7 | .5000; 2; fail/amber | Candidate; exact Decimal pre-round amount `(1200.06/12)*1 = 100.005`; **PENDING BD-14:** half-even→100.00, half-up→100.01; round once after full formula |
| G-39 Empty close and rerun | Reporting period with no failing native results and otherwise valid frozen inputs/configuration | no candidate rows | N/A | N/A | N/A | First close must return an empty successful result, not E’s `1:nrow`/row-name failure; atomic write/rerun/replacement outcome is **PENDING BD-16** |
| G-40 Half-month with multiple session types | Half-month P1 weight .5; R2/Active; `S1:3/T`, `S2:1/T`; raw S1=2, S2=1 | [2,1] | caps [1.5,0.5]; no transfer | posting 2; 2 | 2/2=1; 0; met/green | Not candidate; a forbidden double-halving implementation would produce target100 1 instead of 2 |
| G-41 Three unmatched postings | Same resident-month contains P1, P2 and P3 with no matching multi-posting rule; R2/Active; each has `S1:1/T` and one matching weekday row | one raw row per posting | cap1 independently at each; no cross-posting transfer | each 1/1 | each 1/1=1, shortage0, met/green | No candidate; arithmetic is unchanged. Annotation is **PENDING F-23**: exact-two interpretation→false, two-or-more interpretation→true; approved reason/evidence must name all relevant codes |
| G-42 Public-holiday creation block | `P1`; R2/Active; `S1:10/T`; date exists in `public_holidays`; attempt both secretary event creation and resident ad-hoc submission | no event/attendance row stored; compliance raw0 | no PH row reaches cap/reallocation | existing target10; 7 | 0/10=0; shortage7; fail/red | API returns 422 for both creation paths; any candidate reflects absence of attendance, never a stored/excluded PH session |
| G-43 Failing posting group with two billing departments | Group G has P1/DeptA and P2/DeptB, each R2/Active one month with `S1:5/T`; two matching rows at each member | P1 raw2; P2 raw2 | physical caps2+2; no transfer; group counted4 | group10; 7 | 4/10=.4; shortage3; fail/red | Candidate; injected rate1200 and summed active months2 gives logical amount200.00; row identity and DeptA/DeptB allocation are **PENDING F-16/BD-13** |
| G-44 Non-empty close rerun | One failing standalone P1/R2/Active result identical to G-02; valid injected rate1200; invoke authorized final close twice with unchanged frozen inputs | 5 on both runs | cap5 on both | 10; 7 | .5000; 2; fail/amber | Logical candidate amount100.00 on both; physical snapshot/clawback row count/version/replacement and rollback behavior are **PENDING BD-16** and must never create an accidental duplicate within one close version |
| G-45 Catalogue keyword normalization | `P1`; R2/Active; `S1:4/T`; catalogue display keyword `Journal Club`; four distinct non-overlapping weekday events persist names `Journal Club`, `journal club`, ` Journal Club ` and `Journal  Club` | stored4; compliance raw **PENDING F-17/BD-09** (exact-only 1, case-fold+trim 3, plus internal-space collapse 4) | pending approved canonical match; cap equals approved raw | 4; 3 | exact-only 1/4=.25, shortage2, fail/red; case-fold+trim 3/4=.75, shortage0, met/green; collapsed4/4=1, met/green | Candidate only in exact-only branch; one normalization boundary must replace these branches before implementation |

</details>

### 10.3 Deferred clawback/close test register

The preserved clawback cases are not executable acceptance criteria yet. Once the deferred contract is confirmed, tests must cover every approved rate/effective-date branch, funding year, classification, suppression precedence, grouped identity/billing attribution, missing-rate behavior, Decimal rounding, empty/non-empty close, rollback, and rerun/idempotency. Do not use the illustrative injected rates or legacy branch order as current business authority.

Historical recommendations retained for future requirements analysis:

1. Every approved rate branch and its precedence: `R7 → FM → SS* → IM → im_programmes → exact standard R-year → missing`. In particular, an approved IM-sub-specialty resident carrying `SS*` must take the SS positional/rate category before the IM-sub-specialty category, matching E’s branch order unless deliberately changed.
2. A missing rate and missing funding year must fail final close or create the approved explicit error state; neither may silently produce an ordinary zero amount.
3. G-38’s exact Decimal `100.005` input must assert the chosen current rounding mode and that rounding occurs once after `(annual_rate / 12) * active_months`. Exact legacy parity would be base-R ties-to-even where representable with binary-double caveats; a deliberate Decimal rule may differ.
4. G-43’s failing posting group with two member billing departments and G-37’s standalone month-specific billing change must assert the approved result identity, billing source/time grain and allocation.
5. A period with no failed residents must return an empty, successful result; it must not reproduce E’s zero-candidate `1:nrow`/row-name failure before or inside its loops.
6. Operational deactivate alone must create no snapshots, clawback rows, or surplus close mutation. After BD-16 chooses a natural key/replacement policy, G-39 and G-44 must assert the approved empty/non-empty atomic write, rollback and rerun behavior; idempotency is recommended but currently pending.
7. Calculation percentage 0.691 may optionally display as 0.70 only if explicitly labelled/approved, but status/candidacy must use the unformatted predicate approved under BD-05; display formatting can never change it.
8. Candidacy and amount are separate: after a resident is a candidate, amount depends on annual rate and active months only—not shortage or percentage deficit. G-29/G-30 lock this behavior.
9. G-36 must assert overlapping R7/Extension/employer precedence, row visibility and one-versus-many suppression-reason representation.

### 10.4 Golden-test acceptance rule

No non-clawback implementation is acceptable unless it asserts the one confirmed outcome above and produces identical canonical values through single-resident and admin/report paths. Historical alternative branches are forbidden. Clawback/close tests must remain skipped/not authored as business assertions until the deferred owner decisions land; this document does not claim any current implementation or test coverage.

## 11. Decision Disposition Register

The former non-clawback blockers are resolved:

| IDs | Current disposition |
|---|---|
| BD-01 | RESOLVED: raw one-for-one tag transfers before caps; row 70% supply/demand; decrement donor; physical posting/R-year context/prefix only. |
| BD-02 | RESOLVED: idempotent pre-tag raw-minus-target derived ledger; never carry into attendance. |
| BD-03 | RESOLVED: half-month weight 0.5 once; monthly target unchanged. |
| BD-04 | RESOLVED: AY label selects FormF1 for the whole bucket. |
| BD-05 | RESOLVED: unrounded posting percentage is canonical; `target_70` display-only. |
| BD-06 | RESOLVED: configured canonical combined posting/TTF identity; no component results. |
| BD-07 | RESOLVED: SPORTSMED/PALLMED require R-year, are not subspecialties, and use R4–R6. |
| BD-08 | RESOLVED: exact ORTHO 3h type; adjust/project before Saturday-window test; Sunday excluded. |
| BD-09 | RESOLVED FOR COMPLIANCE: exact canonical scoped catalogue name, no fuzzy match; option/tag cleanup is upload data quality. |
| BD-15 | RESOLVED: reject later overlapping submission and preserve earlier attendance. |
| BD-17 | RESOLVED: target/cap R-year contexts separately, then sum without duplicated months. |
| BD-18 | RESOLVED SPECIFICATION: one shared BL-6 contract; no implementation claim. |
| BD-10–BD-14, BD-16 | **DEFERRED CLAWBACK/FINAL CLOSE.** No financial or close rule may be inferred. |

<details>
<summary>Original blocking-decision recommendations (historical)</summary>

The recommendations below preserve the alternatives considered before confirmation. They are not current product decisions and must not override the disposition table above.

### BD-01 — Reallocation source, row threshold, and effect

- **Decision needed:** Define per-session `tag_target_70`, donor supply, recipient demand, operation order, fractional-row behavior, and whether reallocation can increase the posting numerator.
- **Why scripts and docs do not resolve it:** C uses `ceil(session_target_100*.70)` and raw-minus-session-`target_70`, transfers raw counts, recaps, and accidentally reuses supply (`386-506`). BL-3 implies the row threshold but uses already-capped values and decrements supply (`141`, `173-186`), which conserves the posting total; BL-6 ordering could also be misread to transfer across posting-group members despite the confirmed no-cross-posting rule.
- **Affected calculation step:** 13–16.
- **Available interpretations:** (A) raw→bounded transfer→recap, preserving the useful legacy outcome but fixing scope/double-spend; (B) capped transfer only, explicitly distribution/display-only; (C) another owner-defined supply linked to the persistent ledger.
- **Recommended interpretation (not a decision):** A, with a separately named row-level threshold, physical-same-posting scope, consumable balance, one-for-one flow, recap, and posting-group aggregation only afterward, because it gives reallocation a material purpose while preserving confirmed safety fixes.
- **Owner needed:** Programme/business owner plus compliance product owner.

### BD-02 — Persistent surplus invariant

- **Decision needed:** Define the ledger formula and how balance is recomputed, consumed, hibernated and resumed.
- **Why scripts and docs do not resolve it:** R has no persistent equivalent. BL-4 contradicts itself about raw versus capped achievement and never defines carry-in use.
- **Affected calculation step:** 14–15 and period close.
- **Available interpretations:** Raw excess above `target_100`; counted excess above `target_70`; cumulative event-derived balance; or audit-only derived snapshot not used as an input.
- **Recommended interpretation (not a decision):** Treat it as idempotently derived pre-reallocation raw excess per period/tuple, with an explicit event/target recomputation source and no additive update; separately define whether/how that balance can supply later months.
- **Owner needed:** Compliance product owner and data architect.

### BD-03 — Half-month factor

- **Decision needed:** Confirm whether the .5 factor is applied once to active-month weight.
- **Why scripts and docs do not resolve it:** Formula and R posting path support one factor; prose says both active months and target are halved.
- **Affected calculation step:** 12.
- **Available interpretations:** One .5 factor (50% target) or two factors (25% target).
- **Recommended interpretation (not a decision):** One factor; persisted monthly target unchanged, monthly display derived separately.
- **Owner needed:** Compliance owner; documentation owner can patch after confirmation.

### BD-04 — FormF1 calendar gate at AY boundaries

- **Decision needed:** Define numerator/denominator gating when an AY bucket/phase crosses calendar months with different FormF1 states.
- **Why scripts and docs do not resolve it:** Legacy uses the posting-month label; current docs separately require calendar FormF1 and AY bucketing; SQL assumes phase start month without authority.
- **Affected calculation step:** 4–5 and active-month target.
- **Available interpretations:** Gate entire AY phase by its label/start month; gate each attendance by event calendar month while denominator remains phase-level; split phase weight across calendar months; or another confirmed mapping.
- **Recommended interpretation (not a decision):** Use explicit date intersections so each calendar-month FormF1 state gates the matching portion/event, with a documented weight rule; avoid start-month shortcuts.
- **Owner needed:** Programme/compliance owner familiar with FormF1 funding semantics.

### BD-05 — Fractional target pass/fail predicate

- **Decision needed:** Align `met`, colour, shortage and clawback for fractional `target_100`.
- **Why scripts and docs do not resolve it:** `ceil(70%)` count and percentage rules disagree when the cap is fractional.
- **Affected calculation step:** 17 and clawback trigger.
- **Available interpretations:** Pass by percentage; pass by achieving integer ceiling; quantize target/cap first; disallow odd-target half months.
- **Recommended interpretation (not a decision):** Use the percentage boundary for status/clawback and retain `target_70` as a displayed required-session count only if product owners accept the possible fractional-shortage presentation; otherwise define a consistent quantization rule.
- **Owner needed:** Programme/compliance owner.

### BD-06 — Combined-posting resolution

- **Decision needed:** Map component-site events to a combined posting phase/catalogue/target.
- **Why scripts and docs do not resolve it:** BL-8 requires component events and combined target; BL-6 exact joins exclude them.
- **Affected calculation step:** 6–8.
- **Available interpretations:** Component catalogue→combined target; combined catalogue keyed through explicit member map; duplicate catalogue rows per component; model combined posting as a posting group instead.
- **Recommended interpretation (not a decision):** Use an explicit configured component-membership map, retain component event ownership, and resolve one combined compliance identity/target without regex or duplicated counting.
- **Owner needed:** Compliance product owner and data architect.

### BD-07 — SPORTSMED/PALLMED R-year configuration

- **Decision needed:** Choose `ALL` or SS remapping for these programmes.
- **Why scripts and docs do not resolve it:** Both flags are set; parser returns `ALL` before remap; legacy remap is defective.
- **Affected calculation step:** RDB/TTF parsing and steps 3/8/12.
- **Available interpretations:** Keep `r_year_required=false` and remove/ignore subspecialty remap; set true and store SS1–SS3; use a separate display-only SS field.
- **Recommended interpretation (not a decision):** Confirm actual TTF differentiation with the programme owners, then make the flags mutually coherent. Do not infer from the broken R branch.
- **Owner needed:** SPORTSMED and PALLMED programme coordinators/data owner.

### BD-08 — ORTHO acceptance versus mutation

- **Decision needed:** Confirm broad versus type-specific acceptance and whether ORTHO time-window validation uses the raw or adjusted interval.
- **Why scripts and docs do not resolve it:** R mutates the 3h interval before its separate acceptance predicate; current matching code checks the raw time window before mutation; BL prose is type-specific; schema null-type seed mutates all in-window types.
- **Affected calculation step:** 9.
- **Available interpretations:** Broad acceptance + narrow mutation, with mutation before adjusted-window validation; only named type accepted/mutated; raw-window validation before mutation; all in-window types accepted/mutated.
- **Recommended interpretation (not a decision):** Broad Saturday acceptance plus narrow named-type mutation evaluated before testing the adjusted end time, matching the separable R predicates while preserving raw data.
- **Owner needed:** ORTHO programme owner.

### BD-09 — Tag grammar, catalogue normalization/cardinality, and missing targets

- **Decision needed:** Approve tag syntax, canonical keyword case/whitespace normalization, whether duplicate keywords at different durations are legal, and the fail-safe outcome for catalogue-without-target configuration.
- **Why scripts and docs do not resolve it:** Parser validation contradicts BL prefix groups; schema uniqueness contradicts tiebreaker logic; BL only specifies the no-catalogue case; exact keyword equality is shown without a canonicalization rule, and the secondary decision log records that ambiguity without authority to resolve it.
- **Affected calculation step:** TTF upload and 8/15.
- **Available interpretations:** Strict `^[A-Z]+[1-9][0-9]*$`-style tiers or a broader explicit grammar; exact-case keywords or a documented Unicode/case-folded key; trim-only versus controlled internal-space normalization; one keyword per full scope or keyword+duration uniqueness; target-missing exclusion with warning or fail-closed report/configuration error.
- **Recommended interpretation (not a decision):** Adopt a simple normalized prefix+positive-integer tier grammar and one canonical trimmed/case-folded keyword mapping per posting/programme/R-year/period, persisted alongside display text, unless a demonstrated use case requires duration ambiguity. Treat a resolved catalogue with no target as a visible configuration error and exclude it from math rather than inventing a target.
- **Owner needed:** TTF/data owner and compliance product owner.

### BD-10 — Norm-rate catalogue and IM classification

- **Decision needed:** Supply exact rates/categories, effective periods and the durable IM-sub-specialty set.
- **Why scripts and docs do not resolve it:** Rate templates are missing; BL has an empty TODO; dynamic RDB classification is not a stable rule.
- **Affected calculation step:** 19/final close.
- **Available interpretations:** Versioned DB table seeded by approved finance source; period snapshot JSON; hardcoded values (not recommended).
- **Recommended interpretation (not a decision):** Versioned, period-effective DB configuration with source document/version and immutable close-time snapshot.
- **Owner needed:** Finance/funding owner and programme governance owner.

### BD-11 — Clawback funding year and transition proration

- **Decision needed:** Define the funding/rate-year source for year-dependent branches and the persisted audit-year/result shape for `ALL` programmes and mid-period changes.
- **Why scripts and docs do not resolve it:** E uses FormF1 column 8; current FormF1 omits R year; result schema stores one year; compliance can span phases. Some rate branches ignore year, but that does not settle stored provenance or standard year-dependent branches such as G-31.
- **Affected calculation step:** 19.
- **Available interpretations:** Separate funding-year field; split one failing result into phase/rate rows; prorate one row by phase rates; choose year at close/start/end.
- **Recommended interpretation (not a decision):** Persist an explicit funding year per calendar/phase source and sum phase-prorated amounts with auditable components; do not infer a year from `ALL` or current resident year, and record why any branch legitimately ignores it.
- **Owner needed:** Finance/funding owner and data owner.

### BD-12 — Extension suppression

- **Decision needed:** Define all-Extension and mixed Active/Extension behavior, including precedence/representation when R7 or an excluded employer also applies.
- **Why scripts and docs do not resolve it:** Legacy excludes Extension entirely; current compliance includes it but BL-10 only says “Extension status residents” are suppressed. One stored reason cannot represent an unresolved R7/Extension/employer collision.
- **Affected calculation step:** 19.
- **Available interpretations:** Any Extension suppresses whole posting; all months must be Extension; suppress/prorate only Extension months; separate rows; one prioritized reason or multiple reason components when another suppression overlaps.
- **Recommended interpretation (not a decision):** Calculate compliance with all active statuses, then apply funding treatment per month/phase so mixed statuses remain auditable rather than suppressing unrelated Active months.
- **Owner needed:** Finance/funding owner.

### BD-13 — Standalone/posting-group clawback identity and billing

- **Decision needed:** Define the billing source/time grain for standalone postings and persist/bill a failed group containing multiple posting departments.
- **Why scripts and docs do not resolve it:** Calculation identity can be `group_code`; schema requires one posting FK and static posting-code billing department. Legacy E uses resident/month-specific `all1billingposting` and silently selects the first listed posting month, but no current schedule or explicit decision confirms that behavior or its static replacement.
- **Affected calculation step:** 19/final close.
- **Available interpretations:** Static posting-code department; resident/month schedule; one group row with group identity; one member row per weighted phase/department; choose main/first member.
- **Recommended interpretation (not a decision):** Use an owner-approved period-effective billing source; store one logical group result plus auditable allocation components per member/active-month contribution; never silently select the legacy first month or a static department without confirmation.
- **Owner needed:** Finance owner and schema/data architect.

### BD-14 — Employer rows, missing configuration, and rounding

- **Decision needed:** Resolve SAF/SCDF row visibility and precedence against other suppressions, missing-rate failure behavior, and financial precision.
- **Why scripts and docs do not resolve it:** BL/schema disagree on rows; one reason field cannot represent employer/R7/Extension collisions; pseudocode returns zero for missing year; R returns/error-coerces text; the current Decimal tie mode is unstated.
- **Affected calculation step:** 19/final close/API.
- **Available interpretations:** No employer row or explicit zero row; employer-first or another suppression precedence/multiple reasons; abort close or persist error; Decimal half-even/half-up/other.
- **Recommended interpretation (not a decision):** Follow BL’s no-row employer rule only after owner confirmation; fail close on missing configuration; use Decimal with explicitly approved two-decimal rounding after the full formula.
- **Owner needed:** Finance owner, API owner and data architect.

### BD-15 — Distinct-event duplicate and overlap handling

- **Decision needed:** Define which distinct event pairs are compared and whether a detected exact-interval duplicate or overlap is rejected, stored/flagged, excluded on one/both sides, or merely warned/countable.
- **Why scripts and docs do not resolve it:** B checks only adjacent sorted same-resident/date rows, marks the earlier row, and excludes that flagged row (`881-883`, `952-1017`). BL-5 provides a symmetric interval comparator but no persistence/numerator action; the DB constraint covers only duplicate `(resident,event)`.
- **Affected calculation step:** Attendance submission/mutation and steps 2/8/9/10/11.
- **Available interpretations:** Reject the new row; store both and exclude the new row; store both and exclude both; flag for review with an owner-defined provisional count; warning-only/count both.
- **Recommended interpretation (not a decision):** Use a deterministic all-overlaps check per resident/date across scheduled and ad-hoc events, allow touching boundaries, preserve both raw records when audit requirements require it, and expose an explicit conflict status whose counting rule is owner-approved. Do not port order-dependent “earlier row loses” behavior.
- **Owner needed:** Compliance product owner, resident-workflow owner and data architect.

### BD-16 — Final-close transaction and rerun contract

- **Decision needed:** Define authorization, atomicity, rollback, natural uniqueness, immutable input/config provenance, replacement versus append semantics, and rerun/reopen behavior for snapshots, clawback rows and close-time surplus state.
- **Why scripts and docs do not resolve it:** F2 is non-transactional file archival, not a database close. Current BL/API defer generation and schema has no complete natural key/replacement contract; “idempotent” is an audit recommendation, not current authority.
- **Affected calculation step:** 19/final close and period reopen.
- **Available interpretations:** Single atomic transaction with deterministic replace/upsert; immutable append-only close versions; delete/rebuild under explicit reopen authorization; separate transactions with compensating rollback.
- **Recommended interpretation (not a decision):** One authorized atomic transaction using frozen/versioned rate/config inputs and a documented natural key, with fail-all rollback and an explicit versioned replace/rerun policy. Operational deactivation remains separate.
- **Owner needed:** Compliance product owner, finance owner, API/security owner and data architect.

### BD-17 — Cross-R-year cap and compliance-result grain

- **Decision needed:** Choose separate per-R-year posting results, phase-first caps summed into one posting result, or merged raw/targets capped once when a resident changes R year mid-period.
- **Why scripts and docs do not resolve it:** Legacy C groups/caps/reports with `Year of Residency` but first duplicates posting-wide active months onto every R-year row; that multiplier is unsafe to port. BL-1 correctly uses phase R year for targets but names a `(resident, posting, session_type)` cap, while BL-6 drops R year from its grouping key. The corrected non-linear outcomes still differ in G-09.
- **Affected calculation step:** 11–17 and the step-19 clawback handoff.
- **Available interpretations:** Retain legacy separate R-year results; cap each R-year context then aggregate counted/target values; merge raw/targets across contexts then cap once.
- **Recommended interpretation (not a decision):** First reject the legacy duplicated-month multiplier. Retain explicit correctly weighted phase/R-year components and cap per R-year target context; if the product needs one posting summary, aggregate already-capped components while preserving component rows/provenance. Confirm this with owners because it differs from a merged-before-cap result.
- **Owner needed:** Compliance product owner, programme owner and reporting/finance owner.

### BD-18 — Normative resident/admin calculation path

- **Decision needed:** Declare whether the ordered domain pipeline or an equivalence-complete replacement query/service is normative, and retire the current illustrative batch SQL as an implementation contract.
- **Why scripts and docs do not resolve it:** Legacy D1/D2 consume the same C output, while current BL-6’s resident steps and batch SQL omit different rules and can return different values for the same attendance. API text currently points admin reports to the incomplete SQL.
- **Affected calculation step:** All steps in resident JIT, programme batch, snapshot preparation and clawback-input preparation.
- **Available interpretations:** One shared Python/domain service for all consumers; separately implemented JIT/SQL paths proven equivalent by the full fixture suite; SQL as sole normative engine after it is made rule-complete.
- **Recommended interpretation (not a decision):** Use one shared set of domain primitives and treat optimized batch queries as replaceable implementations that must pass every golden fixture field-for-field.
- **Owner needed:** Backend architecture owner, reporting/API owner and data architect.

</details>

## 12. Documentation Alignment Outcome

The Phase 6-A non-clawback patches represented by the historical recommendation table were applied to `AGENTS.md` and the domain documentation on 2026-07-20. This includes calculation order, FormF1/AY gating, R-year grain/configuration, multi-posting identity, overlap/native/catalogue rules, API parity wording, exact ORTHO behavior, ledger lifecycle, and examples. Clawback/final-close recommendations remain deferred, not applied as invented rules. The legacy Word/R artifacts were intentionally not modified.

<details>
<summary>Original recommended-patch table (historical)</summary>

“Blocking” in this preserved table describes the pre-decision state, not the current non-clawback specification.

| Target file / section | Exact issue | Recommended wording or rule change | Evidence | Blocking? |
|---|---|---|---|---|
| `docs/business-logic.md` BL-1 | Half-month prose permits double-halving | “TTF `monthly_target` remains unchanged. A half-month row contributes `monthly_target * 0.5` exactly once through `active_months_weight`; any half-target monthly view is display-only.” | C `299-319`, `342-389` | Yes |
| BL-1/BL-5A/BL-6 | Calendar FormF1 versus AY phase gate absent | Add owner-approved date-intersection/bucket rule and a cross-calendar example. Remove start-date shortcut unless it is confirmed. | F-08/G-26 | Yes |
| BL-1/BL-6 cross-R-year grain | Phase R year selects targets, but cap/result grouping drops R year | State separate-versus-merged result grain, raw/target/cap order and component provenance through posting groups/snapshots/clawback. | C `380-395`, `512-518`; F-22/G-09 | Yes |
| BL-2 | Fractional target gives conflicting met/colour | Define one predicate and show `target_100=1.5` example with target70, shortage, colour and clawback. | F-10 | Yes |
| BL-3 | Reallocation claims R equivalence but uses capped conserved total | Replace with owner-approved source/order/effect; explicitly retain same-posting scope, consumable balance and alphabetical one-for-one flow; note legacy raw transfer/double-spend. | C `386-506` | Yes |
| BL-3/BL-6 posting-group order | Group-before-transfer wording can imply cross-member tag flow | Define `tag_target_70` separately from posting `target_70`; perform transfer per physical posting, then aggregate group members; never transfer across member posting codes. | F-04/G-32; confirmed no-cross-posting rule | Yes |
| BL-1/BL-6 posting-group cap order | BL-6 groups members before cap despite the confirmed cap-before-posting-aggregation rule | Cap raw achievement per physical posting/session target context, perform same-posting transfer, then aggregate member results as in G-10. | Phase 6-A confirmed guardrail; BL-1; G-10 | High |
| BL-3 | Tag grammar absent | Define normalized prefix/tier grammar and deterministic sort, including multi-digit policy. | C `408-413`; F-06 | Yes |
| BL-4 | Raw/capped contradiction and missing carry algorithm | Define ledger invariant, idempotent recomputation, carry-in/use, hibernation/resumption and period reset sequence. | F-05 | Yes |
| BL-5 | ORTHO acceptance/mutation predicate/order | Separate broad acceptance from named-original-type mutation or constrain one compound rule; state whether adjusted or raw time is tested first and state Sunday outcome. | B `912-918`, `940-941` | Yes |
| BL-6 ordered pipeline | Missing FM override/combined translation and unresolved ordering | Replace with the final approved section 9 order; include FM 5h and combined component mapping. | F-11; BL-FM | Yes |
| BL-6 batch SQL | Query omits required rules | Remove it as normative pseudocode or replace with equivalence-complete query/design; state parity is mandatory. | F-12 | Yes |
| BL-7 reliability flag | “More than one”/reporting-period wording conflicts with “only when two”/same-month wording | Define an explicit distinct-posting cardinality and date grain, evidence payload and post-rule outcome; add G-41. | F-23; BL-7 `598-618` | Medium |
| BL-8 combine | Component events cannot reach combined target | Add explicit configured component membership/catalogue/target attribution and deduplication. | F-11 | Yes |
| BL-10 | Unformatted trigger | State the canonical predicate selected by BD-05/F-10 and explicitly prohibit display formatting/rounding before eligibility. | E `36-41` | Yes for clawback |
| BL-10 | Empty `im_programmes` and missing rate source | Replace TODO with approved versioned classification/rate source and effective-period rules. | A `251-257`; E `25-90` | Yes |
| BL-10 | Funding year, transitions, Extension, overlapping suppressions, standalone/group billing, missing configuration, rounding | Add decisions BD-11–BD-14 and worked G-31/G-36–G-38/G-43 examples; define billing source/time grain and suppression precedence. | E `43-90`, `129-140`; F-15/F-16 | Yes |
| BL-10/final close | Atomicity, rollback, natural uniqueness, provenance and rerun/reopen behavior are deferred | Add the owner-approved BD-16 transaction contract and keep operational deactivation separate. | F2 operational archive; F-16/G-39/G-44 | Yes before generation |
| BL-11 | Incompatible SPORTSMED/PALLMED flags | Make `ALL`/SS behavior coherent and align lists/remap including R6→SS3. | F-09 | Yes |
| `docs/schema.md` programmes seed | False `r_year_required` plus true subspecialty | Update seed/notes after BD-07. | schema `73-108`; parsing function | Yes |
| schema posting codes | Stale emergency weekend/PH note | Remove it; reference current weekend seed and universal PH creation block. | BL-5; schema `647` | High |
| schema teaching catalogue | Unique key contradicts duration tiebreaker; canonical keyword key is undefined | Align constraint with approved keyword cardinality and persist/enforce the owner-approved canonical case/whitespace key separately from display text. | F-17/G-45 | High |
| schema `surplus_ledger` | No unique constraint for upsert | Add unique tuple constraint after BD-02; retain supporting indexes. | BL-4; schema `453-469`, `1131-1139` | Yes |
| schema weekend seed | ORTHO row has no original-type constraint | Add approved acceptance/mutation representation. | F-13 | Yes |
| schema snapshot example | Arithmetic says target70 21, achieved18, .857, met true | Correct target fields/status using BL-2; add group/R-year component shape if approved. | schema `855-873` | Medium |
| schema `clawback_records` | One posting/year/static billing department cannot represent approved group/phase outcomes; one reason cannot represent suppression collisions; no natural uniqueness/replacement rule exists; index cites nonexistent `programme_code` | Redesign after BD-11–BD-17, define billing source/components and close-time uniqueness/provenance/replacement/rerun semantics, align suppression representation, and correct the index. | schema `885-910`, `1237-1244`; E `129-140` | Yes |
| `docs/parsing.md` R year | Remap unreachable and text omits R6 in one list | Align function/order and all lists with BD-07. | parsing `150-178`, `540-547` | Yes |
| parsing TTF Column J/validation | A/B examples and same-exact-tag rule contradict A1/A2 groups | Use approved tag grammar; require at least two distinct tiers under one prefix; normalize case/space. | parsing `479-493`, `590-593` | Yes |
| parsing combined postings | Parse output lacks read-time component semantics | Cross-link the BL-8 component map; ensure explicit configuration is persisted. | F-11 | Yes |
| `docs/api.md` attendance submission | Global types can be visible but unconditional catalogue requirement rejects them | Permit active global type submission, store it, and mark it compliance-exempt without catalogue lookup. | BL-6 step 7; F-17 | High |
| BL-6/schema/API target resolution | Catalogue match with no corresponding target has no explicit safe outcome | Define fail-safe behavior and a configuration warning/error; never invent a target or treat it as zero-target visibility. | Legacy C `128-158`; F-17 | High |
| BL-6/parsing/schema/API catalogue matching | Exact equality is shown without case/whitespace normalization | Apply one owner-approved canonicalization at TTF upload, uniqueness, event creation/submission and read-time lookup; keep display/audit text intact. | F-17/BD-09/G-45; decision log `1037-1054` | High |
| BL-6/API resident visibility | Native-programme events are visible outside the assigned posting but have no compliance attribution rule | Define display-only status or an explicit posting/phase/catalogue/target identity; never infer from visibility. | F-17/G-35; legacy C `113-180` | High |
| BL-5/schema/API distinct-event conflicts | Interval comparator has no pair scope, lifecycle action, status or numerator consequence | Define scheduled/ad-hoc pair scope, touching-boundary rule, pre/post-mutation comparison, reject/store/flag action, which side counts, and safe API response. | F-21/G-34; B `881-883`, `952-1017` | High |
| API resident dashboard/monthly view | Examples attach compliance colour to session/month rows | Return authoritative posting/group summary; label session/month percentages display-only. | BL-2; API `1069-1083`, `1532-1569` | High |
| API admin reports | Claims incomplete SQL powers all views | Reference the shared approved contract/parity rule, not incomplete SQL. | F-12 | Yes |
| API clawback/close | Suppression precedence, billing/result identity and close transaction/rerun errors are incomplete | Align after BD-11–BD-17; expose explicit configuration and rollback/conflict errors safely. | F-15/F-16/F-22 | Yes |
| `AGENTS.md` architectural rules | Earlier duration-driven tag sentence contradicts later alphabetical rule; ad-hoc shorthand is overly broad | Replace with alphabetical-only wording and exact fixed ad-hoc attribution cross-reference. | `AGENTS.md:112`, `:132`, `:140` | High |
| `docs/99_decision_log_and_gap_audit.md` | Calls clawback Script F and FM report template Script E; some historical “open” entries are already resolved | Correct factual attribution and label stale entries historical; do not let the log override domain docs. | E header/calculation; D1 `202-213` | Low |
| `MATA R Scripts/MATA_Core_Business_Logic_Audit.docx` | Presents inaccurate pseudocode as precise migration reference | Add a superseded/non-authoritative notice and the section 8 errata, or replace it with a link to current domain docs/audit. | F-19 | High, but Markdown source patches take priority |

</details>

## 13. Safe Implementation Checklist

### 13.1 Before coding

- [x] Non-clawback BD-01–BD-09, BD-15, BD-17 and BD-18 decisions are recorded in the authoritative domain documents.
- [x] Non-clawback `PENDING` golden-test branches have one asserted recommended outcome in section 10.
- [ ] **DEFERRED:** norm-rate, funding-year, classification, suppression, billing, rounding, and final-close decisions must exist before clawback code/tests start.
- [x] SPORTSMED/PALLMED flags and R4–R6 parser behavior are coherent.
- [x] Combined-posting canonical identity and target attribution are explicit configuration, never regex inference.
- [x] Tag-prefix and canonical catalogue-option behavior is fixed for compliance; case/spacing cleanup is upload/option data quality.
- [x] Native-programme events outside the assigned posting have explicit assigned-posting attribution.
- [x] Distinct-event overlap has deterministic later-reject/earlier-preserve behavior; same-event uniqueness remains separate.
- [x] Cross-R-year cap/result grain and posting-group ordering are specified for ordinary compliance.
- [x] Surplus tuple uniqueness and idempotent raw-minus-target state invariant are specified.

### 13.2 Calculation path

- [ ] Count sessions, never hours or duration-weighted units.
- [ ] Use only native accepted attendance; reject later overlaps at submission and never let external attendance enter any native calculation.
- [ ] Use `resident_postings.r_year` for ordinary phase/target context; never `residents.r_year` by convenience and never infer the deferred clawback funding year from it.
- [ ] Apply the AY-label FormF1 status to both numerator and denominator for the entire bucket.
- [ ] Resolve AY buckets inclusively and fail safely on missing/overlap configuration.
- [ ] Apply FM 5h attribution and combined/group identity in the approved order.
- [ ] Apply native ad-hoc assigned-posting/fixed-1h attribution before generic persisted-source/mapping resolution; no client-selected teaching name or attended posting changes that attribution.
- [ ] Exclude global types before source/mapping resolution.
- [ ] Resolve persisted scheduled-event source and mapping at read time; never persist session type on attendance records or consult the retired catalogue.
- [ ] Apply weekend exclusion/read-time mutation without changing raw attendance.
- [ ] Resolve distinct-event conflicts and final status eligibility before raw counting; never let query order decide which row counts.
- [ ] Exclude untracked and zero-target rows before cap, surplus and reallocation.
- [ ] Apply the half-month factor exactly once.
- [ ] Preserve raw achieved separately from counted/adjusted values.
- [ ] Reallocate raw session counts before caps; decrement donor supply; never cross physical posting, R-year context, or tag prefix.
- [ ] Idempotently replace pre-tag raw-minus-target ledger state, never add it to attendance, and keep tag-adjusted values read-time only.
- [ ] Cap each R-year context separately, then aggregate applicable types/physical members before posting/group status.
- [ ] Compute posting `target_70` from the summed `target_100`, not by summing per-type ceilings.
- [ ] Use unrounded posting percentage as canonical status; keep displayed `target_70` and UI formatting non-authoritative.
- [ ] Monthly and session-type percentages remain display/breakdown data only.

### 13.3 Persistence, API and close

- [ ] Resident JIT and admin batch paths share primitives and pass identical golden fixtures.
- [ ] Cache keys include role/scope and cache invalidation follows uploads/config/event/attendance mutations and close/reopen.
- [ ] Ledger updates are idempotent and concurrency-safe under the documented unique key.
- [ ] Missing source, mapping, or target evidence is stored/audited but excluded from compliance as specified; no guessing.
- [ ] **DEFERRED CLAWBACK:** missing-configuration, Decimal precision, billing identity, and suppression behavior require owner-approved rules first.
- [ ] Operational period deactivation does not generate snapshots, clawback or close-time surplus mutations.
- [ ] **DEFERRED:** final close/freeze has an owner-approved atomicity, rollback, uniqueness/replacement, rerun, authorization, and provenance contract.
- [ ] No FormSG parser, dashboard feedback loop, fuzzy posting matching, free-text MCR extraction, duration weighting, separate FM engine or legacy exception list is reintroduced.

### 13.4 Required verification

- [ ] Run all section 10 fixtures through the single-resident path.
- [ ] Run the same fixtures through the programme batch path and compare every calculation field.
- [ ] Add boundary tests for inclusive phase/AY dates, FormF1 calendar changes and mid-period R-year transitions.
- [ ] Add property tests for conservation/no-double-spend, tag direction/scope and idempotent repeated reads.
- [ ] Add database tests for attendance and surplus uniqueness.
- [ ] Add close tests for empty results, missing configuration, approved rerun behavior and rollback/atomicity once specified.
- [ ] Review outputs with the compliance/finance owner before declaring Phase 6 complete.

Ordinary non-clawback implementation may proceed from the aligned specification, but every implementation/test item above remains unchecked until independently completed. Clawback/final-close implementation remains blocked on its explicitly deferred owner decisions.
