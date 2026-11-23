# Version 2 development plan (concise)
Status date: 2026-11-19. V1 ZIP untouched (sha256 in `v1_zip.sha256`). V2 lives in a separate working copy, git branch `v2-dev`.
**Nothing below has been run on your Windows machine. Tested / untested / simulated is marked per item in IMPLEMENTATION_STATUS.md.**

## 0. Gate: your V1 Windows report
Send `outputs\reports\implementation_summary.html` (or `logs\pipeline.log`). Real DEM / WorldCover / CHIRPS / OSM downloads and `run.ps1` have never been run by me; their failures take priority over anything new.

## 1. Which event can actually be processed? (evidence so far, not yet confirmed)
| Event | Sentinel-1 evidence found | Independent reference found | Assessment |
|---|---|---|---|
| Nov 2021 | UNOSAT-style product by MBRSC from S1 of **16 Nov 2021** (Sentinel-Asia); S1A+S1B both still operating | ALOS-2 (L-band) flood detection 8 and 12 Nov 2021; FORMOSAT-5 16/22 Nov | **Candidate for first event** |
| Dec 2023 (Michaung) | Not found. Only S1A flew in 2023 (12-day repeat per orbit), so a pass near 4-7 Dec is not guaranteed | NRSC RISAT-1A map 7 Dec 2023 (pre 5 Nov; "official use", preliminary); EOS-04 7 Dec scene; IITM crowd-sourced water-depth logs 4-5 Dec (~1,200 users) | **Best validation resources; S1 coverage must be checked.** Needed as the unseen test event |
| Nov 2015 wave | UNOSAT used S1 of **12 Nov 2015** (+1 Sep 2015) | Same product (probable standing water, not field-validated) | Exploratory (single satellite, seasonal pre/post gap) |
| Dec 2015 peak (1-2 Dec) | Not found; public peak products used ALOS-2 (3 Dec) | ALOS-2 3 & 9 Dec; Charter activation 2 Dec | Exploratory until probed |

**Decision rule** (implemented in `scripts/s1_availability.py`): an event is PROCESSABLE only if ONE orbit (direction + relative orbit) has >=3 full-coverage pre-event scenes AND a post-event scene within 10 days after the peak. Run it first on your machine (public ASF catalogue, no login).
**Consequence to discuss with the guide:** the PPT's "train 2015+2021, test 2023" may be impossible with Sentinel-1 labels alone. Fallbacks: (a) train 2021 (+2015 Nov), test 2023 if a 2023 pass exists; (b) leave-one-event-out over whatever events pass; (c) cross-sensor labels from ALOS-2/RISAT-1A/EOS-04 products if they can be obtained as rasters/vectors.

## 2. Sentinel-1 flood detection (prepared, UNTESTED against live services)
`s1_availability.py` -> `s1_flood_extent.py --event <id>` -> `compare_reference.py`.
Same-orbit pairing; median of several pre scenes vs post; focal-median speckle reduction; rule (diff < -3 dB and post < -15 dB); masks for JRC permanent water, pre-event dark pixels, slope > 5 deg, tiny clusters; exports GeoTIFF (master grid), GeoJSON polygons, PNG, metadata JSON (scene IDs, thresholds, orbit). Label status is always `SAR PROXY - UNVALIDATED`. No accuracy is claimed; `compare_reference.py` reports *agreement with a named reference product*.
Known blind spot: flooded urban areas (double bounce) are under-detected, so Chennai's densest wards will show low recall.
**Threshold discipline:** set thresholds on the first event with a sensitivity analysis, freeze them, then apply unchanged to the test event.

## 3. Data-source improvements (nothing replaced automatically; see DATASET_SOURCE_REGISTER.md)
Ward boundaries: vintage of the DataMeet file is unverified (GCC redrew 119 of 200 wards and renumbered in the Dec 2018 delimitation). Compare ward numbers/zones with the official GCC list before any ward-level population/risk work. DEM: keep Copernicus GLO-30 for V2.0; evaluate a bare-earth-corrected DEM (e.g. FABDEM; check licence) as an *option*, with a documented before/after comparison. CHIRPS/WorldCover: keep; add fallbacks only if V1 downloads fail on your machine.

## 4. V1 review -> fixes (CHANGELOG_V2.md)
Fixed on `v2-dev` (with tests): projected-CRS DEM silently ignored; stale unaligned layer could crash/stack in feature builder; `zip://` path on Windows; DEM plausibility check. Planned/pending listed in KNOWN_ISSUES_V2.md.

## 5. ML module design (not built yet; waits for validated-enough labels)
- Samples: positives = SAR-proxy flood; negatives = non-flood, not permanent water, outside a ~100 m buffer of flood edges; sampled per spatial block. No simulated data can be trained on: the module refuses labels whose metadata says SIMULATED, and unit tests use synthetic arrays only for logic.
- Features (all on the 30 m master grid): elevation, slope, built-up fraction, land cover, + new: HAND/TWI/flow accumulation (needs hydrological conditioning), distance to OSM drains/roads. Event rainfall is an event attribute, not a pixel feature, until >=3 events exist.
- Models: Random Forest and XGBoost on identical folds; baselines (elevation-only, HAND-only) to show whether ML adds anything.
- Validation hierarchy: spatial-block CV -> leave-one-event-out -> independent 2023 event (no tuning, thresholds or scaling touched by it) -> cross-sensor agreement with ALOS-2/RISAT-1A/EOS-04 -> point check against IITM logs. Metrics: precision, recall, F1, ROC-AUC, PR-AUC, with block-bootstrap intervals; urban/non-urban reported separately.
- Circularity guard: slope is part of the SAR mask and a feature -> run an ablation without it.

## 6. Dashboard (incremental, Streamlit + Folium only)
D1 event selector + flood-extent layer + data-availability matrix (reads S1A output). D2 ward statistics (flooded % per ward via zonal stats, labelled proxy). D3 model-evaluation tab reading `rf_metrics.json` (no hard-coded numbers). D4 risk classes once exposure/vulnerability data exist. D5 SHAP when implemented.

## 7. Order of work and gates
1. V1 Windows report -> fix V1 problems. 2. Run `s1_availability.py` -> choose first event. 3. One event end-to-end with visual check in QGIS + reference comparison. 4. Freeze parameters; second event. 5. OSM/HAND/TWI features. 6. ML module. 7. Ward statistics + dashboard D1-D3.
