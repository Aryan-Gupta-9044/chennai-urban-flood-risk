# Chennai Urban Flood-Risk Project — Living Master Control File

**Document ID:** CHENNAI-FLOOD-MASTER-STATE
**Version:** 1.0
**State snapshot date:** 27 November 2026
**Project root (Windows):** `C:\Users\aryan\Downloads\chennai-flood-risk-v2.3-dev\chennai-flood-risk`
**Python environment:** `.\.venv\Scripts\python.exe`
**Status:** Working master record — update after every meaningful, verified project change.

> **Purpose:** This file is the project's single working reference for its pipeline, context, decisions, progress, completed work, task ownership, risks, and next actions. It is a controlled summary, not a substitute for source code, raw evidence, manifests, test logs, or approved technical reports. When this file conflicts with primary evidence, inspect the primary evidence and correct this file with an explicit change-log entry.

---

## 1. Project identity and objective

**Project title:** *Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data*
**Study area:** Chennai, Tamil Nadu, India
**Project type:** Two-person B.Tech project, with supporting AI-agent workstreams.
**Product-quality target:** 10 December 2026 (self-imposed quality milestone, not a university submission deadline).
**Broader academic horizon:** May 2027.
**Publication aspiration:** Develop a technically defensible IEEE conference-paper candidate; publication is not guaranteed.

### Core objective

Build a reproducible, evidence-led geospatial framework that progressively integrates:
1. Flood-related surface/wetness observations and event evidence.
2. Terrain- and environment-based flood susceptibility.
3. Exposure datasets and, only when justified, vulnerability information.
4. Spatially explicit risk assessment.
5. Prediction only if adequate independent, temporally appropriate reference data and validation are available.
6. Clear maps, reports, reproducible outputs, and a demonstrable user-facing product.

### Scientific guardrails

- **Susceptibility is not hazard, risk, observed inundation, or prediction.**
- A susceptibility index identifies relative terrain/environmental predisposition; it does not establish that a location flooded.
- Hazard requires a defensible event/process representation. Risk requires hazard plus exposed elements and vulnerability/consequence evidence.
- Prediction requires a defined target, time horizon, suitable predictors, leakage controls, and independent temporal/spatial validation.
- Never claim accuracy, validation, flood labels, or predictive skill without qualified independent reference data and an appropriate evaluation design.
- Preserve uncertainty and source evidence statuses exactly. Do not upgrade “reported”, “plausible”, “uncertain”, or “unverified” evidence without new supporting material.
- NoData / not assessed must never be silently converted to zero or low risk.
- Retain provenance, licences, input/output hashes, configuration, software versions, and reproducible commands.

---

## 2. Team and workstream ownership

| Owner | Responsibility | Boundaries |
|---|---|---|
| **Project owner (user)** | Final decisions, scope approval, running local commands, reviewing evidence, accepting deliverables | No implementation or scientific claim is accepted solely because an agent reports completion. |
| **SHIVE** | Implementation, coding, tests, debugging, reproducible builds, packaging, implementation audits | Must preserve accepted baselines and protected outputs; no commits/pushes or destructive cleanup without explicit permission. |
| **Agent 1** | Independent research, literature review, dataset/reference verification, provenance/licensing, methodology assessment, validation readiness | Independent evidence/research role; do not assign implementation work unless explicitly authorised. |
| **Sande** | Requirements engineering and DEP-1 documentation consolidation, traceability, schemas, acceptance specifications, implementation checklist | No network access, actual data processing, coding, or repository modification. |
| **ChatGPT** | Architecture, technical review, task decomposition, command guidance, risk assessment, reconciliation of evidence, master-file maintenance | Cannot directly monitor or edit the user's local Windows working folder. Updates require the user to share new outputs/files or apply a generated replacement file. |

**There is no Agent 3.** Do not create or assign an Agent 3 workstream.

---

## 3. End-to-end project pipeline

The following is the intended staged pipeline. A downstream stage is not considered complete merely because its folder or placeholder exists.

| Stage | Purpose | Main inputs | Main outputs / acceptance evidence | Current state |
|---|---|---|---|---|
| **0. Project control and AOI** | Establish reproducible project structure, AOI, CRS, grid, data inventory and provenance | AOI boundary, project configuration, source inventory | AOI version, CRS/grid specification, source register, hashes, reproducible environment | Foundation exists; AOI remains provisional |
| **1. S1WC-1 baseline** | Establish initial Sentinel-1 water/wetness workflow | Sentinel-1 scenes and supporting inputs | Baseline rasters/tables, logs, tests, manifest | Completed/accepted with qualifications |
| **2. S1WC-2 technical integration** | Improve/reproduce multi-date Sentinel-1 workflow and regression checks | Accepted S1WC-1 plus S1WC-2 inputs/config | Eight date rasters, regression evidence, tests and reproducibility checks | Local technical integration accepted |
| **3. SUS-1 susceptibility baseline** | Build relative terrain/environment susceptibility index | DEM-derived indicators, drainage, land/environment inputs, CHIRPS context | Susceptibility stack, index, classes/domain, tables, manifest, framework documentation | Built and accepted with mandatory caveats |
| **4. SUS-1 independent review** | Audit assumptions, sensitivity, ranking stability, spatial effects and reproducibility | SUS-1 outputs, code/config, review scenarios | Review rasters/tables/report, tests, audit log | Review run; documentation reconciliation substantially integrated; final local audit pending |
| **5. DEP-1 requirements and exposure design** | Define exposure datasets, spatial aggregation, schemas, provenance, QA and implementation plan | Requirements package, source verification, accepted S1WC/SUS foundations | Owner-approved requirements, traceability, I/O schemas, manifest and QA specs | Documentation consolidation pending final package and owner approval |
| **6. DEP-1 implementation** | Implement approved exposure modules and reproducible outputs | Approved DEP-1 specification and qualified datasets | Exposure layers/tables, tests, manifests, maps and reports | Not started |
| **7. Independent event/reference evidence** | Acquire and qualify independent event observations for validation | Georeferenced event products, metadata, acquisition records, reference polygons/pixels | Evidence register, qualified reference dataset or explicit no-go decision | In progress; no qualified independent validation set yet |
| **8. Integrated risk assessment** | Combine suitable hazard/susceptibility, exposure and vulnerability components | Accepted upstream products and approved method | Transparent risk outputs, uncertainty, sensitivity, validation | Not yet established; do not imply completion |
| **9. Prediction (conditional)** | Train/test a defined predictive model only if data support it | Adequate event/time-series labels and predictors | Leakage-controlled model, temporal/spatial validation, calibrated metrics and limitations | Not started; feasibility unresolved |
| **10. Product, maps and communication** | Package a demonstrable, reproducible user-facing product | Accepted modules and reports | Maps, dashboard/report, reproducibility instructions, paper-ready figures | Early/planning stage |
| **11. Final QA and dissemination** | Independent audit, final documentation, presentation and paper preparation | All accepted outputs and evidence | Final release package, technical report, presentation, possible paper submission | Pending |

### Dependency rule

Do not start DEP-1 implementation until the Sande requirements package is received, reconciled with SHIVE's Stage-1 readiness audit and Agent 1 evidence, and explicitly approved by the project owner. Do not claim an integrated risk or prediction product before its required components and validation are genuinely complete.

---

## 4. Verified technical baseline

### 4.1 Project environment and conventions

- Repository root: `C:\Users\aryan\Downloads\chennai-flood-risk-v2.3-dev\chennai-flood-risk`
- Use the project virtual environment: `.\.venv\Scripts\python.exe`
- User runs commands in Windows PowerShell.
- Run commands from the repository root unless a task explicitly says otherwise.
- Copy only the command text from instructions, not explanatory prose, prompt labels, or terminal output.
- Do not commit or push unless the project owner explicitly authorises it.
- Do not run `git clean`, `git reset`, delete untracked outputs, overwrite accepted outputs, or replace files without a guarded backup/reconciliation procedure.

### 4.2 S1WC-2 accepted facts

- Five files were integrated for S1WC-2.
- Focused tests: 25 passed, 2 warnings.
- Local build exited successfully.
- Eight S1WC-2 date rasters reproduced.
- Inputs unchanged; regression check true.
- Sixteen VV/VH TIFF comparisons had zero mismatches.
- TWI clamp: 0.1°, 12,614 cells.
- Stable-cell VV shift range: −1.121 to +1.825 dB.
- Stable-cell VH shift range: −0.822 to +1.245 dB.

**Limitations to retain:** provisional flattened-water DEM signature is not a confirmed permanent-water mask; DEM=0 is not sea level; plateau detection is AOI-only; TWI is relative/unvalidated; class-1 candidates are not confirmed floodwater; no independent reference/accuracy claim; AOI remains provisional OSM-derived.

### 4.3 SUS-1 accepted baseline facts

Relevant files:
- `src/flood_detection/susceptibility.py`
- `config/susceptibility.json`
- `scripts/build_susceptibility_stack.py`
- `tests/test_susceptibility.py`
- `docs/susceptibility_framework.md`

Real-data build:
- Output directory: `outputs/susceptibility_v1`
- CRS: EPSG:32644
- Resolution: 30 m
- Raster dimensions: 1416 × 726
- AOI cells: 483,727
- Provisional OSM AOI area: approximately 435 km²; not an official GCC boundary.
- Scored domain: 471,472 cells.
- Provisional water-signature exclusion: 12,255 cells.
- Missing indicator count: 0.
- Outside AOI: 544,289 cells.
- DEM==0 cells: 5,097.
- Plateau-only cells: 7,158.
- TWI slope clamp: 3,620 scored cells.
- HAND proxy negative clipping: 44,026 cells (9.1% of AOI).
- Drainage cells: 5,394.
- Fill-depth median 0, p75 0, p95 0.0979, p99 0.5445, max 0.9997, mean 0.01856.
- HAND proxy median 2.93 m, mean 3.77 m.
- Input manifest: 17 inputs with SHA256 verified; 26 output hashes.

**CHIRPS spatial/temporal qualification:**
- Native CHIRPS grid: 0.05°, nominal scale approximately 5,566 m.
- 29 native CHIRPS cells intersect the AOI; they are not all wholly inside it.
- CHIRPS carries no usable sub-5 km spatial information for this AOI.
- Probe: 29/29 cells valid on four probe dates; 115/115 daily dates temporally complete in the probe report.
- Daily definition is provisional; local IST observation-day windows are unverified.
- CHIRPS v3 SAT uses IMERG Late V07 to split pentad totals and blends station data; it is not independent of gauges.
- Do not describe CHIRPS as fine-resolution local flood observation.

**Other limitations:**
- No independent flood reference/calibration/accuracy.
- Indicators are correlated.
- GLO-30 is a DSM, not bare-earth DTM.
- HAND is an Euclidean-nearest-drainage proxy, not flow-path HAND.
- Fill depth is mostly zero and may reflect pit-scale artefacts.
- AOI edge effects and provisional DEM-based flattened-water exclusion remain.
- No exposure/vulnerability in SUS-1.

### 4.4 SUS-1 review findings and required interpretation

- Review audit: 17 checks passed.
- Focused tests: 30 passed in the latest documentation integration run (see Section 5).
- Historical full suite on an earlier review state: 463 passed, 1 skipped, 0 failed.
- TWI is nearly a function of slope and flow accumulation (R² approximately 0.93); seven indicators carry about four independent information dimensions.
- Three wetness indicators have nominal 43% weight but drive about 52% of index variation.
- Six-indicator `C_reduced_no_twi` candidate: Spearman rank agreement 0.982; top-decile Jaccard 0.890.
- This is a **defensible sensitivity candidate, not an adopted replacement**. Baseline A remains accepted. No independent reference establishes that C is more accurate than A.
- Original mean-index hotspot ranking retains only 57% of top 10 across 511 scenarios.
- Area-weighted excess susceptibility retains 99%, but largely reflects area (rank correlation with area approximately 0.93).
- Primary planning ranking: mean index in fixed 300 m planning blocks; retains 85% of top 10; no threshold/minimum-size rule.
- 98.3% of drainage-network cells are in the top decile; the index partly restates DEM-derived channels.
- 12,255 excluded cells reproduced exactly; all 471,472 scored inputs valid.
- Excluded means not assessed; NoData is not zero.
- `hotspot_label.tif` zero is ambiguous without `domain_class.tif`.

**Mandatory reporting conditions:** equal weights are an assumption; do not headline the mean-index hotspot ranking; use 300 m blocks for primary planning ranking; disclose channel circularity; describe excluded cells as not assessed; call outputs exploratory.

---

## 5. Latest local work: SHIVE-SUS1-DOC-FINAL-02

**Task:** Reconcile SUS-1 framework/review documentation with SHIVE's corrected findings.
**Package:** `update2byshive.zip`
**ZIP SHA256:** `1A936CD067AD30577C33C3F6E1F2FE58226034EAAAE6C495F7DEA40A4052883F`
**Inspection folder:** `C:\Users\aryan\Downloads\SHIVE_update2_inspection`

### Changes reviewed

SHIVE's review-report diff contained four intended corrections:
1. `C_reduced_no_twi` is a defensible sensitivity candidate, not adopted; baseline unchanged.
2. Variation-share statement corrected from 14.5–21.9% to 8.0–21.9%; max/min ratio 2.8 rather than 3.5 for A; wording acknowledges moderate top-decile change (Jaccard 0.89).
3. Recommendation wording replaced with a finding; no independent reference proves C more accurate than A.
4. Section 5/index description updated to baseline A unchanged and C unadopted sensitivity candidate.

### Local integration evidence

**`docs/susceptibility_framework.md`**
- Retained local version; not replaced by SHIVE's framework file.
- Local file already had the corrected CHIRPS wording: about 29 native cells intersect the AOI.
- Local SHA256 recorded:
  `7A7B28AB6F8900D2260D3015D4578677767AE056CAE8691950BDC867B6014015`

**`docs/susceptibility_review_report.md`**
- Replaced with SHIVE's corrected report using a guarded local integration.
- Previous file preserved as: `docs/susceptibility_review_report.md.pre_shive_reconcile.bak`
- Previous report SHA256:
  `7291928A1BE736D48481882C0C8A739DC3E1803338C57F9A99BB61FEA7754C8F`
- Integrated report SHA256:
  `F3D6667C863EB10BC0DC67185A0770F4A2BC2AE2568CF68E128B8707EA179073`

### Test evidence after integration

Command:
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_susceptibility.py tests\test_susceptibility_review.py -v
```
Result: **30 passed, 25 warnings, 0 failed in 14.96 seconds.**
Warnings were Rasterio `PendingDeprecationWarning` about affine multiplication (`*`) and recommending `@`; not test failures.

### Current status of this task

**Substantially integrated locally; final repository audit still pending.** The two documents are locally updated as recorded. This does not mean source code, configuration, or baseline outputs changed. No commit/push was made.

### Required final audit (not yet recorded as complete)

Run from repository root, one command at a time:
```powershell
git diff --check
```
```powershell
git status --short
```
```powershell
Select-String -Path .\docs\susceptibility_review_report.md -Pattern 'recommended candidate|preferred index|14\.5|most even|without losing information|defensible sensitivity candidate|not adopted|no independent reference'
```
```powershell
Select-String -Path .\docs\susceptibility_framework.md -Pattern 'About 14 native|14\.5|most even|About 29 native'
```
Review outputs before deciding whether any further correction is needed. Inspect `git status` carefully for pre-existing work and the preserved backup; do not delete untracked files. Do not commit/push.

---

## 6. DEP-1 requirements workstream

### Current position

DEP-1 implementation is **not started**. Requirements consolidation and approval must come first.

### Sande's expected final package

- DEP-1 Trial Report.
- Complete Requirements Specification.
- A1/A2 correction addenda.
- DEP1-PKG-01 v0.2.
- Traceability matrix.
- Dataset provenance/licensing register.
- Input/output schemas.
- Manifest specification.
- QA acceptance specification.
- SHIVE implementation checklist.
- Architecture and staged plan.
- Open decisions / owner approval register.

Sande's role is documentation and requirements consolidation only; no code, data processing, network downloads, or repository edits.

### Reconciliation requirements

The final package must:
- Reconcile accepted S1WC-2 and SUS-1 baselines and limitations.
- Preserve Agent 1 evidence statuses and uncertainty.
- Explicitly handle OSM temporal mismatch (2021 vs 2026 source availability/coverage).
- Define WorldCover fractions as 0–1 where appropriate.
- State GHSL product variant, native 100 m Mollweide grid and metadata caveats.
- Define exposure allocation and aggregation assumptions.
- Preserve NoData as not assessed, never zero.
- Retain 300 m planning blocks as primary SUS-1 planning aggregation, with limitations.
- Address licensing and provenance for every dataset.
- Clearly separate confirmed, proposed, unresolved, and owner-decision items.
- Include checksums, file index, schemas, tests and acceptance criteria.

### Prior readiness findings

SHIVE's DEP-1 Stage-1 readiness audit:
- ZIP SHA256: `d42afc2c015792954fc7b5573e149ab3ebe5838f7caa28a9f5d71fd5799e4df5`
- Internal evidence hashes: zero mismatches.
- Stage-1 only; not implementation.
- Snapshot tests: 476 passed, 1 failed, 1 skipped; failure because `dashboard/app.py` was missing from that snapshot. Confirm against the actual checkout before treating it as a real repository defect.
- Historical full suite: 463 passed, 1 skipped.
- DEP-1 decisions remain provisional pending requirements approval.
- SHIVE estimated 14.5–19.5 working days for full DEP-1; core-three route 9–12 days. Treat as planning estimates, not commitments.
- Main blockers: final owner-approved DEP-1 documents absent from Stage-1 snapshot; no final owner-approved specification.
- SHIVE recommends separate exposure modules and no unsupported combined flood-risk index.

**Gate:** Receive Sande's package → inspect completeness and evidence → reconcile with SHIVE and Agent 1 → resolve/record open decisions → owner approval → only then issue bounded implementation tasks to SHIVE.

---

## 7. Independent flood-reference and validation workstream

### Current status

No qualified independent, georeferenced flood-reference dataset has yet been established for accuracy assessment. This is a major project limitation and a blocker for strong validation or predictive claims.

### Agent 1 evidence context — November 2021 event

- Event ID: `15-FL-2021-TN`.
- ALOS-2 PALSAR acquisition: 8 November 2021, 23:00.
- Cartosat-2E Chennai/Ambattur/Ponneri products acquired 13 November and issued 14 November.
- PDFs show inundation information, but machine-readable georeferenced validation products have not been established.
- Eight-date evidence classifications must remain as recorded:
  - 5 Sep: plausible wet.
  - 17 Sep and 29 Sep: uncertain.
  - 11 Oct: wet, unconfirmed.
  - 23 Oct: transition.
  - 4 Nov: wet pre-event.
  - 16 Nov: post-event/recovery.
  - 28 Nov: recurrent wet/event-affected.
- NDEM 2021 polygons: qualitative only; yearly aggregate unsuitable as event-specific validation; source/licensing unresolved.
- Sentinel Asia / NRSC sources are potential leads, not qualified reference data until original products, georeferencing, metadata and licensing are checked.
- 16 Nov FORMOSAT-5 may be useful if original imagery and metadata are acquired.
- ALOS archive product not acquired.
- Agent 1 ZIP previously lacked E39–E51 and referenced files; missing evidence must be recovered or marked unavailable.
- CHIRPS daily time convention remains unresolved.
- Keep master AOI unchanged; a separate NRSC overlap sub-AOI may be used for reference research only.
- Do not use SUS-1 as independent validation of S1WC-2.

### Agent 1 task direction

The current research direction is `AGENT1-NRSC-REFERENCE-ACQUISITION-AND-VALIDATION-READINESS-02`: investigate genuine georeferenced NRSC/ISRO/ALOS-2/Cartosat products for the November 2021 Chennai event, selected pixel evidence and validation readiness; preserve evidence statuses; do not invent labels or claim accuracy.

### Validation go/no-go criteria

Before using any candidate reference:
1. Original source/product is identified and obtainable.
2. Acquisition date/time and event relevance are documented.
3. Spatial reference/georeferencing and resolution are known.
4. Class/label meaning and interpretation method are documented.
5. Coverage intersects the intended AOI and analysis dates.
6. Licensing and permitted use are clear.
7. Independent provenance from model inputs is assessed.
8. Uncertainty and positional/classification error are recorded.
9. A suitable spatial/temporal validation design is defined.

If these conditions cannot be met, report validation as unavailable or qualitative only; do not manufacture a substitute ground truth.

---

## 8. Current progress dashboard

This dashboard is a qualitative planning snapshot based on known evidence, not a measured percentage of all project effort.

| Workstream | Status | Evidence / next gate |
|---|---|---|
| Project structure and AOI | Foundation established; AOI provisional | Confirm AOI provenance and approved boundary decision |
| S1WC-1 | Accepted with qualifications | Preserve baseline and caveats |
| S1WC-2 | Local technical integration accepted | Preserve regression evidence and limitations |
| SUS-1 baseline | Accepted with qualifications | Preserve exploratory interpretation and caveats |
| SUS-1 review | Review run; docs integrated; final audit pending | Complete `git diff --check`, status and wording audit |
| Research/data verification | In progress | Resolve source provenance, licensing, missing evidence and temporal semantics |
| DEP-1 requirements | Pending final consolidation and owner approval | Receive and review Sande package |
| DEP-1 implementation | Not started | Wait for approved specification |
| Exposure/vulnerability | Early / not yet established | Implement only approved and qualified datasets |
| Independent event validation | Not qualified yet | Agent 1 source acquisition and validation-readiness decision |
| Integrated risk | Not established | Requires approved hazard/susceptibility + exposure + vulnerability method |
| Prediction | Not started | Requires adequate independent labels and validation feasibility |
| Dashboard/report/publication | Early planning | Build only on accepted outputs and honest claims |

Do not convert these qualitative statuses into a percentage without defining a weighted work breakdown and measuring it.

---

## 9. Prioritised action register

### P0 — immediate

| ID | Action | Owner | Dependency | Completion evidence |
|---|---|---|---|---|
| P0-01 | Complete final audit of locally integrated SUS-1 documents | Project owner, with ChatGPT guidance | Current local repository | `git diff --check`, reviewed `git status --short`, old-wording search, verified hashes |
| P0-02 | Receive Sande's final DEP-1 package | Sande | Consolidation | Complete indexed package with checksums and all expected documents |
| P0-03 | Review Sande package against SHIVE readiness audit and Agent 1 evidence | ChatGPT + project owner | P0-02 | Gap/reconciliation report and open-decision register |
| P0-04 | Obtain explicit owner approval of DEP-1 requirements | Project owner | P0-03 | Recorded approval and frozen specification version |

### P1 — after requirements approval

| ID | Action | Owner | Dependency | Completion evidence |
|---|---|---|---|---|
| P1-01 | Issue bounded DEP-1 implementation task(s) | Project owner + ChatGPT | P0-04 | Task brief with scope, inputs, outputs, tests, no-go conditions |
| P1-02 | Implement approved core exposure modules | SHIVE | P1-01 | Code, tests, real-data run, manifests and audit |
| P1-03 | Verify dataset variants, provenance and licensing | Agent 1 | DEP-1 source list | Evidence-backed provenance/licensing register |
| P1-04 | Independently review DEP-1 outputs and limitations | ChatGPT + project owner | P1-02 | Reconciliation and acceptance review |

### P1 — independent validation (parallel research)

| ID | Action | Owner | Dependency | Completion evidence |
|---|---|---|---|---|
| P1-05 | Continue NRSC/ISRO/ALOS-2/Cartosat reference acquisition research | Agent 1 | Source access | Original files or documented acquisition failure, metadata and evidence register |
| P1-06 | Resolve missing Agent 1 evidence references E39–E51 | Agent 1 | Original package/source recovery | Recovered evidence or explicit unavailable status |
| P1-07 | Decide whether any event reference qualifies for validation | Agent 1 + project owner | P1-05/P1-06 | Written qualification/no-go decision |

### P2 — integration and communication

| ID | Action | Owner | Dependency | Completion evidence |
|---|---|---|---|---|
| P2-01 | Define integrated risk method only after upstream modules are accepted | Project owner + ChatGPT + Agent 1 | Accepted susceptibility/hazard and exposure evidence | Method specification and uncertainty register |
| P2-02 | Assess prediction feasibility; proceed only with adequate labels | Agent 1 + project owner | P1-07 and suitable time series | Written go/no-go and validation design |
| P2-03 | Build dashboard/maps/report from accepted outputs | SHIVE | Stable module interfaces | Reproducible app/build, tests and user-facing documentation |
| P2-04 | Prepare final technical report and publication candidate | Project team | Accepted evidence and results | Reproducible figures, methods, limitations and review |

---

## 10. Decision and risk register

| ID | Issue / decision | Current position | Required handling |
|---|---|---|---|
| D-01 | AOI boundary | Provisional OSM-derived area, approximately 435 km² | Do not call it an official GCC boundary; document source/date and edge effects |
| D-02 | SUS-1 baseline vs no-TWI candidate | Baseline A remains accepted; C is sensitivity candidate only | Do not silently replace baseline; owner decision required for future change |
| D-03 | CHIRPS scale | 29 native cells intersect AOI; nominal ~5.566 km | Contextual temporal input only; no sub-5 km spatial claim |
| D-04 | CHIRPS daily convention | Local IST observation-day window unresolved | Document uncertainty; verify before event-date interpretation |
| D-05 | Independent flood reference | Not yet qualified | No accuracy/validation claim until reference passes qualification |
| D-06 | NDEM polygons | Qualitative/yearly aggregate, licensing unresolved | Do not use as event-specific ground truth |
| D-07 | DEM-derived water exclusion | Provisional flattened-water signature | Do not call confirmed permanent water |
| D-08 | GLO-30 | DSM, not bare-earth DTM | Disclose surface/building/vegetation effects |
| D-09 | HAND | Euclidean-nearest-drainage proxy | Do not describe as flow-path HAND |
| D-10 | Fill depth | Mostly zero; possible pit-scale artefact | Retain caveat and sensitivity interpretation |
| D-11 | Correlated susceptibility indicators | TWI strongly overlaps slope/flow accumulation | Disclose double-counting and sensitivity findings |
| D-12 | Hotspot ranking | Mean-index ranking not preferred headline; 300 m blocks primary | Use fixed 300 m planning blocks and disclose assumption |
| D-13 | Excluded/NoData cells | Excluded means not assessed | Never interpret as zero/low susceptibility |
| D-14 | OSM temporal mismatch | 2021 vs 2026 issue unresolved in DEP-1 planning | Document temporal mismatch and owner decision |
| D-15 | WorldCover/GHSL | Variant/aggregation decisions require final specification | Preserve fractions and native grid/CRS metadata |
| D-16 | Integrated risk/prediction | Not validated or established | No unsupported combined risk or prediction claims |

---

## 11. Acceptance and change-control rules

A task is **not complete** merely because a person or agent says it is complete. For implementation tasks, require as applicable:
- Exact changed-file inventory.
- Diff or change summary.
- Test command and complete result.
- Real-data execution evidence where relevant.
- Input/output manifest and hashes.
- Reproducibility check.
- Before/after comparison showing accepted outputs were preserved.
- Known limitations and unresolved issues.
- Explicit acceptance by the project owner.

### Protected-work rules

1. Never overwrite accepted baselines or outputs without explicit approval and a verified backup.
2. Never delete backups, untracked outputs, or evidence files as routine cleanup.
3. Never run destructive Git commands (`git clean`, `git reset`, destructive checkout/restore) without explicit approval and a reviewed recovery plan.
4. Never commit or push without explicit approval.
5. Separate documentation-only changes from code/config/data changes.
6. Keep raw evidence immutable; create derived products in versioned output locations.
7. Preserve exact evidence statuses and source wording where required.
8. Record the command, environment, date, inputs and outputs for each real-data build.
9. When a result conflicts with this master file, inspect primary evidence; do not assume the master file is correct.
10. If uncertain, mark **UNVERIFIED** or **OPEN** rather than guessing.

### Status vocabulary

- **NOT STARTED** — no work evidence.
- **IN PROGRESS** — work underway; not accepted.
- **BLOCKED** — cannot proceed until a dependency/decision is resolved.
- **READY FOR REVIEW** — deliverable exists; acceptance review pending.
- **ACCEPTED** — evidence reviewed and owner accepted.
- **ACCEPTED WITH QUALIFICATIONS** — usable only with recorded caveats.
- **REJECTED** — fails acceptance; correction required.
- **SUPERSEDED** — replaced by a newer accepted version; retain history.
- **UNVERIFIED** — reported but not independently checked.

---

## 12. How this master file must be updated

Whenever the project owner shares a new agent package, command output, test result, dataset finding, decision, code change, or accepted deliverable:

1. Identify the affected workstream, task ID, file(s), and decision(s).
2. Separate **reported** facts from **locally verified** facts and **independently reviewed** facts.
3. Check hashes, test logs, diffs and source evidence when available.
4. Update the relevant pipeline stage, progress dashboard, task register, risk/decision register and evidence references.
5. Add a dated entry to the change log below.
6. Preserve superseded decisions and prior accepted versions in the history; do not silently erase them.
7. If evidence is incomplete, record the gap and keep the status open.
8. Generate a new version of this file for the project owner to place in the repository root.
9. Do not claim that the local repository file has been updated until the project owner confirms replacing it or a tool has actually written to that path.

**Recommended filename in the repository root:** `PROJECT_MASTER_CONTROL.md`

**Recommended update naming in conversation:** `PROJECT_MASTER_CONTROL_v1.1_YYYY-MM-DD.md`, `v1.2`, and so on. The canonical in-repository file remains `PROJECT_MASTER_CONTROL.md`; preserve a dated backup before replacing it.

---

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 27 Nov 2026 | Initial master record created from the latest consolidated project context. Recorded accepted S1WC-2 and SUS-1 baseline facts, SUS-1 review findings, local documentation integration, pending final audit, DEP-1 requirements gate, Agent 1 validation status, team roles and prioritised tasks. |

---

## 14. Quick project handoff — current next step

**Immediate next action:** Complete the final local audit of `docs/susceptibility_framework.md` and `docs/susceptibility_review_report.md` from the repository root. Do not commit or push.

**Then:** Receive Sande's DEP-1 requirements package, review it against SHIVE's Stage-1 readiness findings and Agent 1's evidence statuses, resolve open decisions, and obtain explicit project-owner approval before DEP-1 implementation begins.

**Current truth in one sentence:** The project has a reproducible S1WC foundation and an exploratory SUS-1 baseline with a completed review run; documentation reconciliation is integrated but awaiting final local audit, while DEP-1 implementation, qualified independent flood validation, integrated risk assessment and prediction remain pending.
