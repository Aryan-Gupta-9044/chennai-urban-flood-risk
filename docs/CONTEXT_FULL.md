# SHIVE / B794 - full project context (state at V2.3-dev, 2026-11-21)
Purpose: paste this file at the start of any new session so work resumes without re-deriving history.

## 1. Project
B.Tech final-year project B794 (Aryan Gupta + one partner), SRM Kattankulathur. "Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data", study area Chennai. Target: May 2027; possible IEEE paper.
Claude's role ("SHIVE"): engineering/implementation only (Python, Earth Engine, Sentinel-1, geospatial processing, ML, dashboard, tests, docs). Does NOT invent research conclusions, validation results or dataset-reliability claims (Agent 1 handles literature/source verification).
Platform: Windows 11 + PowerShell, one-command workflow; Python 3.10-3.13; Earth Engine project `sylvan-mode-481804-f7` (config/settings.json -> gee.project).

## 2. Standing rules
One small testable stage at a time; never fabricate flood labels, accuracy, validation or simulated data presented as real; always distinguish TESTED / UNTESTED / SIMULATED; never overwrite V1, V2.0, V2.1 (or V2.2); ZIPs only when tested/requested; no RF/XGBoost/SHAP/dashboard work until flood inventory + data quality assessed; no silent dataset substitution; no credentials in logs; do not skip validation gates. Provenance kinds: REAL, SAMPLE, USER-SUPPLIED, PROVISIONAL, SIMULATED, DERIVED. Module states: COMPLETED / PARTIALLY COMPLETED / BLOCKED / NOT STARTED (outputs/reports/status.json).

## 3. Version history (all preserved)
| Version | What | Artifact / checksum |
|---|---|---|
| V1 | Starter: modules 0, A1, A2, B-F, G (RF), H dashboard; run.ps1. User ran it successfully on Windows. | chennai-flood-risk-starter.zip sha256 a0a00dd8...6f6096 |
| V2.0 | 4 V1 fixes (projected-raster bounds bug, stale-layer skip, zip path, DEM plausibility) + ASF Sentinel-1 availability + date-window S1B (superseded) | chennai-flood-risk-v2.zip 673c40ed...ebdba4 (tag v2.0-zip) |
| V2.1 | Relative-orbit fix (ESA formula), orbit-aware pairing, Earth Engine scene check (s1_gee_check.py), tests | chennai-flood-risk-v2.1.zip f9c022b7...e4a76 (commit d3a37d4) |
| V2.2 | S1B pinned-scene flood-proxy module: gate, params, EE layer graph, tiling, aggregation, report; 56 pass / 1 skip | chennai-flood-risk-v2.2.zip 9169c316...cf6c969 (tag v2.2-zip, branch v2.2-dev) |
| V2.3-dev | + window scan for better Sentinel-1 dates (this file's session) | branch v2.3-dev |

## 4. Verified facts (real, from the user's Windows runs)
- ASF search, Nov 2015: 5 full-coverage Sentinel-1A IW GRD DESCENDING scenes: 2015-08-20 (abs 7339), 09-01 (7514), 10-19 (8214), 10-31 (8389), 11-12 (8564). ASF `rel_orbit` was blank (cause never established; raw response now saved).
- Relative orbit = 92, NOT 164 (164 = abs mod 175 without S1A offset). ESA formula S1A ((abs-73) mod 175)+1, S1B ((abs-27) mod 175)+1; S1C/S1D not derived.
- Earth Engine COPERNICUS/S1_GRD: 5/5 exact system:index found; relative orbit 92; DESCENDING; S1A; derived orbit == EE for 5/5. Report: outputs/reports/s1_gee_availability_2015_nov.md; CSV outputs/tables/s1_gee_availability_2015_nov.csv.
- Pinned IDs (config/s1_events.json, event 2015_nov): pre = 20150820T003124.., 20150901.., 20151019.., 20151031.. ; post = S1A_IW_GRDH_1SDV_20151112T003120_20151112T003149_008564_00C241_37E8 (full IDs in the config).
## 5. CRITICAL scientific correction
The Dec 2015 Chennai flood peaked ~1-2 Dec 2015. **12 Nov 2015 is BEFORE the main peak.** The V2.2 Nov-12 proxy must NOT be described as the December peak flood extent; treat it as a separate, exploratory November-event proxy at best. (Rain-spell dates in Nov 2015 must be confirmed by Agent 1.)

## 6. Method in V2.2 (starting parameters, NOT tuned or validated)
GRD in EE is thermal/border-noise-removed, calibrated, orthorectified (no radiometric terrain flattening). 30 m circular focal median per scene; pre = median of 4 scenes (+ std dev diagnostic); flood candidate = (post - pre_median) < -3 dB AND post < -15 dB; masks: pre-median < -18 dB, JRC GSW occurrence >= 10 %, slope > 5 deg (NASADEM), HAND (MERIT) diagnostic only; connected clusters >= 8 px (10 m); processing at 10 m aligned to the 30 m master grid (EPSG:32644, 3x3 blocks), cell = proxy if >= 50 % of valid 10 m pixels. Outputs labelled SAR_PROXY_UNVALIDATED. Known weakness: urban double-bounce omission, layover/shadow, single VV, coarse HAND.
Gate: processing refused unless every pinned scene is FOUND with exact id/date/pass/rel orbit/VV in the live EE table. Run ids hash scenes+params+grid.

## 7. Testing status
Linux sandbox: 66 pass, 1 skip (Dec fixture absent) at V2.3-dev. TESTED: orbit logic, gate, params, tile plan, aggregation/stats/report on SYNTHETIC arrays, CLI plan/gate-block. **UNTESTED: every live Earth Engine call** (S1B layer graph, tile download, Drive export, window scan). No real flood-proxy output or processing report exists yet. No accuracy is known.

## 8. Errors found and fixed along the way
AUTH_HELP str.format KeyError (JSON braces); outputs dir missing when scripts run directly; V1 read_bounds ignored projected rasters; stale unaligned layer in feature stack; ward-union sliver gaps; RF runtime (sample cap); V2.0 pairing grouped unknown orbits; deprecated utcfromtimestamp; wrong user-computed orbit 164 (corrected to 92 and confirmed live); sandbox tests initially failed only for missing packages (ee, folium).

## 9. Open items / next phases (master prompt phases)
A inspect V2.2 [done: tests re-run, V1/V2.0/V2.1 checksums OK] -> B scan Nov 20-Dec 20 2015 for same-geometry S1 scenes (`scripts/s1_window_scan.py`, needs the user's run; 12-day grid from 12 Nov predicts 24 Nov, 6 Dec, 18 Dec, NOT availability) -> C decide event config (Dec event vs Nov separate event vs 2021/2023) -> D update methodology + tests -> E small real EE test -> F full export -> G inspect real raster/report -> H other datasets (Copernicus GLO-30, CHIRPS [earlier download failures to investigate], WorldCover, 200-ward boundaries with vintage notes, population, shelters verified vs inferred) -> I flood inventory + ML (spatial CV, RF/XGB, SHAP) -> J ward risk + dashboard -> K packaging.
Independent references for later agreement checks (not accuracy): ALOS-2 (3 Dec 2015 product), RISAT-1A, EOS-04, IITM logs. UNOSAT/MBRSC products are Sentinel-1-based (not independent).

## 10. Commands (PowerShell, project folder)
```
.\.venv\Scripts\python -m pytest -q tests
.\.venv\Scripts\python scripts\s1_window_scan.py --start 2015-11-20 --end 2015-12-21
.\.venv\Scripts\python scripts\s1b_flood_extent.py --event 2015_nov            # plan only
.\.venv\Scripts\python scripts\s1b_flood_extent.py --event 2015_nov --run      # only after the scan decision
```
