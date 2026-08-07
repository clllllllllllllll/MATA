# Phase R - All-28 Programme Operational Readiness

## Scope and evidence boundary

Phase R is a local, synthetic verification phase for the final evolved-TTF
workflow. It covers the current final A-J TTF contract, programme metadata,
target reconciliation, Teaching Name/mapping configuration, authorization,
scheduled events, native attendance, Phase H target resolution, audit evidence,
and restricted-role isolation. It does not imply production onboarding,
deployment, real-workbook ingestion, real account provisioning, or compliance
calculation readiness.

This document records current source/audit facts and completed local Phase R
verification evidence. It is not a deployment claim.

## Integration checkpoint

| Item | Recorded source checkpoint |
| --- | --- |
| Phase R feature branch | `CL/evolved-ttf-r-programme-readiness` |
| Integration baseline | `CL/evolved-ttf-integration` at `6c5efff6985ac5cd7ab4b0cf5f322e7bc1ca9798` |
| Main | `3f396101f6184175450e8d5c83662c25813fb330` |
| Origin/main | `3f396101f6184175450e8d5c83662c25813fb330` |
| Current Alembic head | `20260806_000038` |
| Phase R migrations in this readiness layer | `20260806_000038` — Programme-PC pool-event RLS requires an exact Teaching Name/period/programme/posting mapping scope; it does not widen Secretary or Master authority. |

The checkpoint is a local source baseline, not a deployment claim. Phase R must
leave `main` and `origin/main` unchanged and must not contact remote services.

## Current contract audit facts

- The final TTF schema is A-J only. A populated K-or-later cell is rejected;
  formatted but empty trailing cells remain harmless. Formulas in A-J content
  are rejected. There is no dual A-K format, catalogue seeding, or
  workbook-text mapping inference.
- There are exactly 28 canonical programme rows. Twenty normalize target and
  resident-posting R-year values to `ALL`; eight retain actual normalized
  R-years. SPORTSMED and PALLMED retain `R4`, `R5`, and `R6`; neither uses
  `ALL` or SS remapping.
- AY date category remains persisted programme metadata, with fourteen
  `im_subspec` and fourteen `non_im_subspec` programmes.
- The four RDB aliases are persisted data: `Infectious Disease -> ID`,
  `Renal Medicine Extended -> RENAL`, `Surgery-in-General -> SIG`, and
  `Microbiology -> MICROB`.
- A TTF re-upload reconciles targets by
  `(reporting_period_id, programme_code, r_year, posting_code, session_type_id)`.
  Matching target IDs remain stable. A removed mapped target clears the retained
  mapping link to pending rather than rewriting events or attendance.
- Non-NHG availability is independently configured by
  `programme_institution_posting_map`. The current TTSH seed has 24 active
  rows and four inactive rows: FM, PATH, SPORTSMED, and PALLMED. A valid TTF
  does not activate this configuration.
- Teaching Name lifecycle and mappings are separately scoped by reporting
  period/programme and exact posting/R-year. Secretary authority requires an
  active explicit capability; Programme PC scope is persisted and non-empty;
  Master mapping oversight is read-only.
- Phase H is a read-only target-resolution seam with only
  `global_excluded`, `fixed_adhoc_target`, `mapped_target`, and
  `pending_mapping` outcomes. It is not a compliance engine.

## Executable readiness harness

The test-only manifest is
`backend/tests/phase_r_readiness_manifest.py`. It is the single explicit Phase
R expected inventory and exports a deterministic JSON-ready matrix. Production
code continues to read persisted `programmes` rows.

`backend/tests/phase_r_readiness_fixtures.py` creates one deterministic,
in-memory final A-J workbook per programme. Each fixture has no personal data,
uses a synthetic posting, includes the fixed one-hour ad-hoc target and a
separate pool-mappable target, and has initial/equivalent/reduced inputs for
stable target and mapping reconciliation.

`backend/tests/test_phase_r_all_programme_readiness.py` covers:

- the exact 28 inventory, 20/8 R-year split, AY categories, aliases, and TTSH
  Non-NHG boundary metadata;
- accepted A-J parsing for every programme through persisted-style supplied
  configuration, including SPORTSMED and PALLMED R4-R6;
- cross-programme upload rejection, populated K rejection, A-J formula
  rejection, sparse-sheet rejection, and harmless formatted trailing cells;
- all-28 in-memory target persistence/re-upload reconciliation, stable retained
  target IDs, stable mapped mapping IDs, and invalidation of a removed target
  back to a pending mapping; and
- deterministic status-matrix encoding. A local readiness outcome is bounded
  to synthetic data and local RLS evidence; it is never a staging or deployment
  claim.

The in-memory persistence fake is a scoped seam test only. It does not replace
the required local PostgreSQL restricted-role, RLS, audit, cache-after-commit,
event, resident, or attendance evidence.

## Programme matrix

Every row below has all-28 synthetic parser, target, mapping, event, resident,
attendance, resolver, audit, cache, and isolation coverage. The shared
restricted-role PostgreSQL runs additionally prove the exact authorization
boundaries. `verified (local synthetic)` is deliberately not a staging-data or
deployment statement.

| Programme | R-year mode | AY category | RDB alias | TTSH Non-NHG state | Current application readiness | Staging-data boundary |
| --- | --- | --- | --- | --- | --- | --- |
| AIM | ALL | im_subspec | - | active (`TTSHGenMed`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| ANAES | actual | non_im_subspec | - | active (`TTSHAnaes`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| CARDIO | ALL | im_subspec | - | active (`TTSHCardio`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| DERM | actual | im_subspec | - | active (`NSCDermat`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| DR | actual | non_im_subspec | - | active (`TTSHDiagRd`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| EM | ALL | non_im_subspec | - | active (`TTSHEmgMed`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| ENDO | ALL | im_subspec | - | active (`TTSHEndocr`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| ENT | ALL | non_im_subspec | - | active (`TTSHOtolar`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| EYE | ALL | non_im_subspec | - | active (`TTSHOphtha`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| FM | actual | non_im_subspec | - | inactive | verified (local synthetic) | Keep TTSH Non-NHG inactive; native synthetic path remains separate. |
| GASTRO | ALL | im_subspec | - | active (`TTSHGas`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| GERI | ALL | im_subspec | - | active (`TTSHGerMed`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| GS | ALL | non_im_subspec | - | active (`TTSHGenSrg`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| ID | ALL | im_subspec | Infectious Disease | active (`TTSHInfect`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| IM | ALL | im_subspec | - | active (`TTSHGenMed`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| MEDONCO | ALL | im_subspec | - | active (`TTSHMedOnc`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| ORTHO | ALL | non_im_subspec | - | active (`TTSHOrtSrg`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| PATH | ALL | non_im_subspec | - | inactive | verified (local synthetic) | Keep TTSH Non-NHG inactive; native synthetic path remains separate. |
| PSY | actual | non_im_subspec | - | active (`TTSHPsychi`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| REHAB | ALL | im_subspec | - | active (`TTSHRehabi`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| RENAL | ALL | im_subspec | Renal Medicine Extended | active (`TTSHRenal`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| RESPI | actual | im_subspec | - | active (`TTSHRespir`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| RHEUM | ALL | im_subspec | - | active (`TTSHRheuma`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| SPORTSMED | actual (R4-R6) | non_im_subspec | - | inactive | verified (local synthetic) | Keep TTSH Non-NHG inactive; native synthetic path remains separate. |
| SIG | ALL | non_im_subspec | Surgery-in-General | active (`TTSHGenSrg`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| URO | ALL | non_im_subspec | - | active (`TTSHUrolog`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| MICROB | ALL | non_im_subspec | Microbiology | active (`TTSHLabMed`) | verified (local synthetic) | Native/role fixtures remain synthetic; Non-NHG remains separate. |
| PALLMED | actual (R4-R6) | im_subspec | - | inactive | verified (local synthetic) | Keep TTSH Non-NHG inactive; native synthetic path remains separate. |

## Completed local evidence

The local disposable PostgreSQL gate completed through revision
`20260806_000038`. The clean upgrade, `current`/one-head check, migration
attestation, downgrade to `20260806_000037`, and clean re-upgrade all passed.
The attestation confirms that the replacement helpers revoke `PUBLIC`, use a
fixed `search_path`, and are no broader than the application PC event-scope
check.

- The forward-only migration partition passed 27 tests: the direct Phase R
  migration check, B1, Teaching Name Pool, in-place ad-hoc creator, and
  external-registration migration partitions all passed on the disposable
  target.
- Restricted-role PostgreSQL suites passed with 44 RLS-foundation, 27 RLS
  policy, 31 session-security, and 47 auth/external-resident tests. They cover
  the exact PC mapping identity, a same-programme cross-posting denial,
  explicit cross-programme denial, and Secretary, Resident, Master, and
  external-role boundaries.
- The local runner removed its disposable database and generated runtime test
  roles after each passing partition. No staging or operational data was used.

Future operational onboarding remains out of scope. No operational row was
invented to mark this matrix verified.

## Test commands and coordinator fields

Focused harness command:

```powershell
cd backend
venv\Scripts\python.exe -B -m pytest -q tests/test_phase_r_all_programme_readiness.py -p no:cacheprovider
```

- Broad synthetic backend evidence: **620 passed** across all-28 RDB/TTF,
  mapping lifecycle, event/resident workflow, authorization, and runner-safety
  coverage.
- Frontend evidence: **220 passed**; production type/lint/build and emitted
  artifact security scan passed. The intentional `/api/v1` production API base
  value was used without contacting any remote service.
- Local PostgreSQL evidence: clean migration and rollback/re-upgrade passed;
  one Alembic head is `20260806_000038`; restricted-role and migration
  partitions passed as recorded above.
- Security and diff evidence: source/artifact scans, security-script tests,
  Python compilation, and whitespace/diff checks passed.
- Independent Sol High re-review: **cleared** on 2026-08-07 with no blocking,
  material, or minor finding. It confirmed the fixed local runner target/owner/
  port checks and the exact PC event-scope authorization boundary.
- Feature and local integration commits are recorded in the Phase R handoff
  after the independent review clears the change.

## Explicit exclusions

Phase R does not:

- upload real source workbooks or read resident-level source data;
- create real PC, Secretary, or resident accounts;
- activate, deactivate, insert, or remove real Non-NHG mappings for readiness;
- implement compliance totals, percentages, shortages, reallocation, clawback,
  final close, or compliance UI;
- deploy, push, open a pull request, mutate Vercel/Supabase, or modify demo,
  UAT, staging, production, `main`, or `origin/main`.

## Handoffs

### Phase K

After a green Phase R matrix, Phase K receives comprehensive regression work
only: the broader backend, frontend contract/type/lint/build, security, and
current documentation consistency gates. It should not reopen Phase R
programme contract decisions without evidence of a defect.

### Phase L

Phase L receives local/deployed pre-compliance smoke planning only. It must
reconfirm the deployed environment independently and must not claim that local
synthetic Phase R evidence proves deployment readiness.

### Phase S staging onboarding inputs

Phase S should receive the final integration commit and Alembic head, the
canonical 28-programme matrix, explicit staging posting relationships, scoped
PC/Secretary capabilities, approved synthetic staging accounts, synthetic A-J
TTF uploads, Teaching Names, mappings, and the four TTSH Non-NHG states that
must remain inactive. It also needs the bounded staged smoke scenarios. Phase R
does not create those accounts, credentials, environment files, or deployment.
