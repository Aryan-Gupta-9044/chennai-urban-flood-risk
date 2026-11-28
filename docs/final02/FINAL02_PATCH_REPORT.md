# FINAL-02 patch report

**Date:** 28 Nov 2026 · **Role:** implementation side · **No evidence status changed** · nothing committed, pushed or published.

**Scope:** the dashboard and map defects from the owner's review, the map and legend audit, two new analyses (versioned outputs only), paper v2, tests and documentation.

**Not done:**

- **DEP-1:** out of scope, so no DEP-1 work.
- **SUS-1 and S1WC-2:** not rebuilt.
- **ML-EXP-1:** not rerun; it is reviewed, not rebuilt.

## 1. Results of this patch

| Area | Outcome |
|---|---|
| Map defects (J blank, ~5,000-mile scale, CARTO "API KEY REQUIRED", C and E basemap) | **Fixed in the shared helper; root causes in `MAP_DEFECT_DIAGNOSIS.md`.** The ward geometry and cluster join were already correct. The world-zoom and blank-map symptoms come from an unbounded map frame with scroll-wheel zoom, plus a failing CARTO default. |
| Legends | Three wrong or incomplete legends fixed: S1WC-2 classes 2–5 were drawn without legend entries; the D agreement codes; linear ramps on skewed ward data. Units were added. |
| Contrast and width | Notes and claims use self-contained dark-on-light colours, so they read in both themes (dark theme screenshot included). The content area is now up to 1,880 px or 97% of the viewport. |
| Integrity wording | "inputs unchanged: True" is replaced by **"4 guarded inputs unchanged"**, built from `input_hashes` in each run record, with the guarded files listed. |
| Deprecated `components.v1.html` | Replaced by `st.iframe` where Streamlit supports HTML strings, with a fallback for older versions. |
| Performance | Ward GeoJSON is about 64% smaller (5 m display-only simplification). The reference and raster layers are cached. |
| S1TC-1 (new, `outputs/s1_temporal_context_v1`) | Class-1 candidates are 0.21–1.85 km² per date. Median date-to-date Jaccard is 0.11, and 53% of the cells ever flagged appear on one date only. The top 10 wards hold 74–95% of the candidate area. Candidates are 3.4× enriched in the SUS-1 top decile, which is internal consistency, not validation: both products use slope. There is no rainfall association (\|ρ\| ≤ 0.31, n = 8). |
| ML-EXP-1.1 (new, `outputs/ml_review_v1_1`) | See below. |
| Paper v2 | Corrected and extended; v1 preserved (`paper/README.md` lists every change and its source) |

### ML-EXP-1.1 detail

The review adds:

- within-zone PB-AUC;
- a zone-stratified permutation null (200 permutations for logistic regression, 40 for random forests);
- Holm and BH correction over the 16 combinations.

It found:

- **Pooled values:** ML-EXP-1's pooled values are reproduced exactly.
- **2021:** no signal.
- **2015:** within-zone AUC is about 0.6, nominal p = 0.024–0.03 for two models, with **none surviving correction** (Holm ≥ 0.39, BH ≥ 0.24).
- **2021 area-only:** pooled p = 0.035, Holm-corrected 0.56.

## 2. Tests

| Suite | Result (sandbox, Python 3.13, Streamlit 1.67) |
|---|---|
| `tests/test_final02.py` (new) | 18 passed |
| Full suite | **565 passed, 4 skipped, 1 failed.** The failure is `test_import_src`, because `earthengine-api` is not installed in the sandbox; it failed before FINAL-01 too. |
| Live browser probe of every map (B–J) | Zoom 10.75–11, 10 km metric scale, 204–698 drawn paths, raster overlays present, tile-failure banner shown (tile servers are blocked in the sandbox) |
| Protected tree digests (13 folders and files) before and after | **Identical** (`PROTECTED_TREE_HASHES_BEFORE.json` / `_AFTER.json`) |

## 3. Status after FINAL-02

| Component | Status |
|---|---|
| SUS-1, S1WC-2 | Accepted baselines, unchanged |
| Reference statuses | Unchanged: REF-2021-CDMP WARNING/WARNING/PRESENCE_ONLY; REF-2015-CDMP and REF-2015-OSMIN-DEC2 WARNING/FAIL/QUALITATIVE_ONLY |
| Exposure / vulnerability | Provisional / partial (unchanged) |
| ML-EXP-1 (+1.1 review) | Exploratory; not validated. Supervised prediction is still not justified. |
| S1TC-1 | Exploratory description of E4 candidates |
| Dashboard | Map defects fixed in the sandbox. **Windows check pending:** OSM tile loading on the owner's network cannot be tested here. |
| Paper | DRAFT CANDIDATE v2, 5 pages. References still need Agent 1 checking; authors are placeholders. |

## 4. What cannot be claimed (unchanged)

- Any flood prediction, probability, hazard or risk map.
- Accuracy, precision, recall, F1, IoU or calibration.
- That a ward is flood-free.
- That S1 candidates or rainfall are floodwater.
- That 2015 validates 2021.
- That population density is vulnerability.
- That the clusters are severity classes.
- 30 m precision for coarse inputs.
- That the AOI is the official boundary.
- That anything ran on Windows. Everything ran in the sandbox on the delivered data.

## 5. Corrections to the prompt's baseline values

- **"52% of index variation from TWI."** The SUS-1 review attributes 52% to the three-indicator wetness family (slope, TWI, flow accumulation); TWI alone is 21.3%. The paper uses the correct statement.
- **The domain_class hash in the prompt** omits the characters `0e`. The file itself is unchanged.

## 6. For Agent 1

1. Is the zone-stratified null with Holm and BH the appropriate family for the 16 PB tests? Should the 4 control models be in the same family?
2. Should the weak 2015 within-zone signal be mentioned in the evidence log? Proposed: yes, as "not significant after correction".
3. Is the S1TC enrichment wording ("internal consistency, not validation") acceptable for the paper?
4. Check the paper v2 references, as before (Q5 of FINAL-01).

## 7. Prompt truncation

Both prompts received in this turn were cut off: at §9, line 793, and at §10, line 798. Any requirements after those points were not visible.
