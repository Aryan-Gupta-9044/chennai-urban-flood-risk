# Proposed plan: flood-reference integration and evaluation readiness (PROPOSAL ONLY - nothing implemented)

Status: no flood classification, model training or accuracy evaluation is started. This plan is blocked at the **independent flood-reference gate** until the team decides how to handle it.

## 1. What the project has today (inspected, not assumed)
- Sentinel-1 2021: 8 date-level products (descending orbit 92, 30 m master grid), QA_PASS, plus the exploratory persistence diagnostic v1.2 (27 outputs; descriptive only, no flood label).
- CHIRPS 2021 daily rainfall and antecedent table (arithmetic QA: see the QA report; day-label convention still PROVISIONAL).
- `config/reference_datasets.json`: seven entries, all with access "NOT YET OBTAINED" and most fields UNCONFIRMED; the SAR-based candidates (ALOS-2, RISAT-1, RADARSAT-2) are dated **December 2015**, whereas the processed Sentinel-1 scenes are **September-November 2021**. The UNOSAT/IWMI products are noted as Sentinel-1 derived (not independent). `data/external/flood_labels/` is empty.
- Existing code: `ref_readiness.py` (conservative status logic), `agreement.py` (agreement metrics), `s1_gate.py`.
- Consequence to be decided by the team: a 2015 independent reference cannot validate 2021 scenes. Either (a) a georeferenced 2021 reference is found, or (b) the 2015 Sentinel-1 data are processed for 2015 (a different, thinner dataset) or (c) the fallbacks below are used with their limited claims.

## 2. Gate decisions required from the team (before any implementation)
1. Which event/year is the evaluation target (2015 or 2021)?
2. Is any georeferenced, independent (non-Sentinel-1) flood extent available for that event, with licence, CRS, date and extent confirmed from the actual file?
3. If not, which fallback tier(s) below are accepted, with their wording limits?

## 3. Stage plan (each stage small, tested, synthetic-data tests first)
| Stage | Content | Blocked by gate? |
|---|---|---|
| R0 | Reference intake validator: reads a candidate file, records CRS/format/extent/date/licence, SHA-256, never alters it; extends `ref_readiness.check_ingest` | No (needs no flood data to write; tested on synthetic files) |
| R1 | Reference-to-grid alignment report (footprint overlap with the AOI, date offset to each S1 scene, resolution mismatch, share of AOI covered). No resampling of the reference without a stated rule | Needs a real file to run |
| R2 | Evaluation-readiness checklist generator (independence from S1, date offset, spatial coverage, class balance, label type) producing READY / NOT READY with reasons | No |
| R3 | Candidate floodwater label layer (rule-based on S1, labelled CANDIDATE) | **Yes** - only after gate decision |
| R4 | Metrics on a suitable independent reference (agreement/IoU/precision/recall with confidence intervals and spatial blocking) | **Yes** - needs independent reference |
| R5 | Any model training (RF/XGBoost) | **Yes** - not before R4 inputs exist; spatial CV only |

## 4. Fallback tiers - each must stay separate and none is accuracy validation
| Tier | What it is | Allowed wording | NOT allowed |
|---|---|---|---|
| A. Candidate floodwater labels | Rule-based S1 candidates (e.g. threshold/change), carrying S1's own limitations | "candidate floodwater label, unvalidated" | "ground truth", "flood extent", training target presented as truth |
| B. Presence-only comparison vs reported locations | Whether candidate cells fall near reported flood points/areas (e.g. open-data flood-point lists). Points are reports, not a complete map | "fraction of reported locations coinciding with candidate cells (presence-only, reporting bias)" | recall/accuracy, omission or commission rates, any false-positive claim (absence of a report is not absence of flood) |
| C. Sensitivity analysis | Stability of candidates to thresholds, polarisation, persistence cut, orbit/date subset | "robustness of the candidate map to analyst choices" | evidence of correctness |
| D. Qualitative historical comparison | Visual/narrative comparison with published reports, rainfall and imagery | "consistent / inconsistent with documented accounts" | any metric labelled accuracy |
Combination rule: reports must state the tier, the reference's date offset, and that Sentinel-1-derived references (e.g. UNOSAT/IWMI) are consistency checks only.

## 5. Dependencies
- Team decision on the gate (section 2) - blocking for R3-R5.
- Actual reference file(s) with confirmed format/CRS/date/extent/licence (none present).
- Confirmation of the CHIRPS day-label convention and, for 2015 work, the missing 2015 daily rainfall (separate unresolved items).
- Official GCC boundary to replace the provisional OSM AOI (results must then be recomputed).
- Land cover/terrain context layers for the persistent-bright-target question left open by the persistence diagnostic.
- Software: existing stack only (numpy, pandas, rasterio, geopandas, scipy, matplotlib); no new dependency for R0-R2.

## 6. Test plan
Synthetic fixtures only until a real reference exists: ingest validator (missing CRS, wrong date, S1-derived flag), alignment report (offsets, zero overlap), readiness generator (every NOT READY reason), tier wording guard (a source-text test that forbids "accuracy"/"validation" in tier A-D outputs), read-only/no-overwrite hashing as in the persistence script. Existing 298+ tests must remain unweakened.
