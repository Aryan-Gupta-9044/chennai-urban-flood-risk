# FINAL-01 status report: what is complete, provisional, blocked, and not claimable

- **Date:** 28 Nov 2026
- **Scope:** final research-grade implementation, ML integration, unified dashboard, validation, and paper preparation
- **Role:** implementation side. No evidence status was upgraded; see `EVIDENCE_DECISION_LOG.md`.

## 1. Test evidence (sandbox, Linux, Python 3, merged PART1–3 plus this overlay)

| Suite | Result |
|---|---|
| `tests/test_ml_exp1.py` + `tests/test_dashboard_unified.py` (new) | **26 passed** |
| Full suite (`pytest -q`) | **547 passed, 1 failed, 4 skipped** (131 s) |
| The 1 failure | `test_import_src`: `earthengine-api` is not installed in the sandbox. This is an environment issue; the test is expected to pass on Windows `.venv`. |
| Baseline before FINAL-01 | 521 passed, 1 failed (same), 4 skipped |
| Dashboard | All 11 sections render headless (`streamlit.testing.AppTest`). Live Chrome screenshots were taken; maps render offline from the vendored Leaflet. |
| ML-EXP-1 reproducibility | Full run took 453 s; input hashes were identical before and after (`inputs_unchanged: true`) |

These are **not yet run on the Windows machine**. SHIVE should run sections 4–7 of `INTEGRATION_AND_RUN_GUIDE.md` and report the counts.

## 2. Status by component

| Component | Status | Notes |
|---|---|---|
| Handoff verification (4 ZIPs, 1,953 files) | COMPLETE | `MISSING_FILES_REPORT.md`, `HANDOFF_FILE_INVENTORY.csv`. Branch and HEAD cannot be verified because no `.git` was included. |
| Unified dashboard v1 (sections A–K) | COMPLETE (sandbox) | Extends and refactors `dashboard/app.py`. The original is kept in `dashboard/legacy/`. Windows run pending. |
| RF v0 retirement | COMPLETE (implementation) | Awaits Agent 1 confirmation (Q1) |
| ML-EXP-1 (ward structure, similarity, Moran's I, presence-background) | COMPLETE: EXPLORATORY, NOT VALIDATED | `outputs/ml_exploratory_v1/ML_EXP1_REPORT.md` |
| SUS-1 (baseline A) | ACCEPTED, unchanged | Candidate C kept as sensitivity only |
| S1WC-2 / S1PE | ACCEPTED as E4 candidates, unchanged | Not flood truth |
| Exposure (DEP2) | PROVISIONAL | Two population sources differ by about 3× (median WorldPop/CDMP ratio 0.29) |
| Vulnerability (DEP2) | PARTIAL, PROVISIONAL | Social-sensitivity indicators are missing. Leave-one-out ρ 0.56–0.85. |
| Study area | PROVISIONAL | OSM-derived, about 435 km². Not the official GCC boundary. |
| IEEE paper candidate | DRAFT CANDIDATE | `paper/main.pdf`, 4 pages. References need Agent 1 verification. Authors are placeholders. |
| Documentation | COMPLETE | `docs/final/*`, `paper/README.md` |
| Master control | Updated as a new versioned file | `docs/final/PROJECT_MASTER_CONTROL_v1.1_FINAL01.md`. The v1.0 file is not overwritten. |

## 3. Blocked

| Item | Blocker | What would unblock it |
|---|---|---|
| Validation of any flood map, and accuracy, precision, recall, F1 or IoU | No E1/E2 mapped extent near an S1 date; no negatives | A georeferenced GCC 2021 inundation map (EV-2021-02), UNOSAT 2015 (EV-2015-04), or dated reports |
| Supervised flood prediction | Same, plus the reporting-opportunity bias shown by ML-EXP-1 | The data contract in `G_ml_dashboard/ml_data_contract.json` |
| Hazard and risk maps | No hazard layer (depth or return period) | Hydrodynamic modelling or official hazard zoning |
| Official boundary | Not obtained | GCC or TNGIS boundary file |
| Several E4 and E3 sources | Host blocked from the agent workspace | The owner can download them (`evidence_register.csv`) |

## 4. Headline results (all exploratory)

- **2015.** The two independent reported sources agree spatially at **2.5×** the street-network null at 50 m (0 of 200 null draws reached the observed value).
- **2021.** Reports show **no association** with bright-VV radar components at 0–100 m (ratios 0.37–1.09).
- **Ward structure.** There are **two stable clusters** (silhouette 0.30, bootstrap ARI 0.85): 54 peripheral wards that are low-lying and high on SUS-1, and 144 dense core wards. All key variables are spatially autocorrelated (Moran's I from 0.10 to 0.77).
- **Presence-background test.** **No indicator set** ranks reported wards above unlabelled ones beyond a permutation null: 12 combinations, PB-AUC 0.39–0.54, p 0.24–0.95. Only the ward-area control is nominally significant (2021: 0.56, p = 0.04). The labels reflect reporting opportunity.

## 5. What cannot be claimed

- That any layer is a flood prediction, flood probability, or a validated hazard or risk map.
- Any accuracy, precision, recall, F1 or IoU.
- That any ward or cell is flood-free.
- That 2015 evidence validates 2021, or that S1 candidates or rainfall are flood truth.
- That population density is vulnerability, or that the partial composite is a social-vulnerability index.
- 30 m precision for coarse inputs: CHIRPS has about 29 native cells and WorldPop is 100 m with partial coverage.
- That the AOI is the official GCC boundary.
- That anything was executed on Windows. Everything here ran in the sandbox on the delivered data.

## 6. Limits of this execution

- The FINAL-01 prompt arrived truncated at §6.1. Later requirements, if any, were not seen.
- Basemap tiles (CartoDB, OSM) were not reachable from the sandbox, so screenshots show grey backgrounds. Overlays are unaffected.
- Agent 1 has not reviewed any FINAL-01 output.
