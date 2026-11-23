# V2 change log (branch v2-dev; V1 = commit 769d8b4 = chennai-flood-risk-starter.zip)
## Fixed (backward compatible; unit-tested on Linux)
- `src/geospatial/raster_io.py`: user-supplied DEM/land cover in a projected CRS (e.g. UTM) was silently treated as "no overlap" and the pipeline fell back to downloading. Bounds are now transformed into the raster CRS. (Bug reproduced in V1 before the fix.)
- `scripts/build_features.py`: a layer not aligned with the current master grid (e.g. left over from an older boundary) is now excluded and reported instead of being stacked.
- `src/geospatial/vector_io.py`: ZIP shapefile path uses forward slashes (Windows drive-letter paths with `zip://`).
- `scripts/process_dem.py`: elevation plausibility check (module becomes PARTIALLY COMPLETED with a warning if outside about -30..300 m).
## Added
- `src/flood_detection/s1_catalog.py`, `scripts/s1_availability.py` (module S1A): ASF catalogue search, same-orbit pairing, PROCESSABLE / MARGINAL / NOT PROCESSABLE verdicts.
- `src/flood_detection/gee_s1_flood.py`, `scripts/s1_flood_extent.py` (module S1B): flood proxy extent for one event; raster + GeoJSON + PNG + metadata.
- `src/flood_detection/export.py`, `agreement.py`, `scripts/compare_reference.py`: vectorising, descriptive stats, agreement vs reference.
- `config/s1_events.json`, `tests/test_v2.py` (7 tests), `docs/v2/*`.
- Pipeline runner includes S1A and S1B (they report BLOCKED instead of failing when offline/unauthenticated).
## Unchanged
All V1 scripts, outputs and behaviour. V1 `gee_sentinel1.py` and Module F are kept as they were.

## Packaging
- `chennai-flood-risk-v2.zip` built from branch `v2-dev` with `git archive` (tracked files only: no .venv, caches, data or outputs). README rewritten for V2.

## V2.1 (relative-orbit fix; branch v2-dev; V2.0 = tag v2.0-zip = chennai-flood-risk-v2.zip, unchanged)
- NEW `src/flood_detection/s1_orbits.py`: scene-name parser, relative orbit from catalogue keys (`pathNumber`, `relativeOrbit`, ...; 0/blank = missing), documented fallback derivation from the absolute orbit (ESA SentiWiki formulas for S1A and S1B). S1C/S1D are not derived (offsets are published as changing/provisional).
- `s1_catalog.normalise`: new columns `abs_orbit`, `abs_orbit_source`, `rel_orbit`, `rel_orbit_source`, `rel_orbit_catalogue`, `rel_orbit_derived`, `orbit_conflict`, `granule`; `scene` is now the clean product name (no `-GRD_HD`).
- `s1_catalog.pair_scenes`: scenes with unknown direction/relative orbit are excluded and counted (V2.0 grouped them together under `None`); pairing key = (direction, relative orbit); output lists platforms, rel-orbit sources and orbit conflicts.
- `scripts/s1_availability.py`: saves the raw ASF response to `data/raw/s1_catalog/` (never overwritten), writes `s1_asf_field_diagnostics.json`, copies earlier outputs once to `outputs/tables/archive_before_orbit_fix/`.
- NEW `scripts/s1_gee_check.py` (module S1G) + `match_scenes()`: scene-by-scene Earth Engine presence check and comparison of derived/catalogue relative orbit with Earth Engine's `relativeOrbitNumber_start`. Reports NOT QUERIED (with exact Windows commands) when Earth Engine is not authenticated.
- Tests: 29 total (13 earlier + 16 new), 1 skipped (Dec 2015 fixture file not provided). No flood detection was run; V1 not modified.

## V2.2 (S1B: scene-pinned November 2015 flood-extent PROXY; branch v2.2-dev; V2.1 untouched)
- `config/s1_events.json`: `2015_nov` now pins 4 pre + 1 post scene IDs (live-verified in Earth Engine by the user), orbit DESCENDING / relative orbit 92, plus `s1b_params` (starting values, not tuned).
- NEW `s1_gate.py`: processing is refused unless every pinned scene is FOUND in the live EE table with exact system:index, date, direction, relative orbit 92 and VV.
- NEW `s1_params.py` (parameters, `--set` overrides, run-id hash), `s1_proxy.py` (EE layer graph, tile plan, tile download, Drive export), `s1_report.py` (tile assembly with alignment checks, 10 m -> 30 m aggregation, statistics, HTML report, limitations).
- NEW `scripts/s1b_flood_extent.py`; pipeline step S1B now runs it (plan-only unless `--run`). Old `scripts/s1_flood_extent.py` (date-window method) is kept, unused by the pipeline.
- NEW `tests/test_s1b.py` (27 tests). Total 56 pass, 1 skipped.

## V2.3-dev: hydrological terrain analysis (module HYD)
- NEW `src/geospatial/hydrology.py` (validation, negative-cluster diagnostics, depth-limited priority-flood conditioning, D8 direction, topological accumulation, drainage extraction, guarded TWI) and `scripts/process_hydrology.py`; pipeline step `HYD` after `B`; status module `HYD`.
- NEW `tests/test_hydrology.py` (16 tests, SYNTHETIC rasters). Full suite: 90 passed, 1 skipped.
- Original DEM is read-only (hash checked before/after; run refuses if an output path equals the input).

## V2.3-dev M3: rainfall audit + source-agnostic workflow
- NEW `src/geospatial/rainfall.py`, `scripts/rainfall_workflow.py` (module C2), `config/rainfall_events.json`, `rainfall_sources.json`, `rainfall_source_template.json`, `tests/test_rainfall.py`, `docs/v2/RAINFALL_AUDIT_M3.md`.
- FIXED `scripts/process_rainfall.py`: no zero-filling, strict event total, AOI-weighted stats, coverage check, native raster, honest status.

## V2.3-dev — IMD 0.25° demo acquisition/conversion (UNTESTED on real data)
- Added `src/geospatial/imd.py`, `scripts/fetch_imd_rainfall.py`, `scripts/prepare_imd_rainfall.py`, `tests/test_imd.py` (SYNTHETIC fixtures built from IMD's documented grid), `requirements-imd.txt`.
- Context window now 2015-07-21..2015-12-20 (153 days); event window labelled PROVISIONAL.
- PROVISIONAL/UNCONFIRMED day definitions downgrade the rainfall workflow to PARTIALLY COMPLETED; added time-series and wettest-day figures.

## V2.3-dev — CHIRPS v3 DAILY_SAT controlled acquisition (live probe PASSED; bulk fetch NOT yet run)
- Probe (user's live run): 153/153 dates, 29 AOI cells, 100 % AOI-area coverage on all dates, 4 exports validated, verdict PROCEED-TO-REVIEW. Native EE grid 0.0500000007 deg, origin (-180, 60).
- Added `src/geospatial/chirps_acquire.py` (resumable engine), `scripts/fetch_chirps_rainfall.py`, `scripts/prepare_chirps_rainfall.py`, `src/geospatial/rainfall_compare.py`, `scripts/compare_chirps_imd.py`, `tests/test_chirps_acquire.py`; source `chirps_v3_daily` registered (day definition PROVISIONAL / NOT VERIFIED).

## V2.3-dev — CHIRPS pre-acquisition corrections
- LOW_COVERAGE status (valid file below --min-coverage: retained, not accepted, blocks COMPLETE); summary judged over the whole window.
- gate_on_probe compares the exact probe start/end (probe JSON `window`, else the probe per-date table) with the requested window; the probe now records its window.
- prepare_chirps_rainfall: explicit read-back checks (no assert), atomic `.part` write, stale/partial outputs removed, LOW_COVERAGE not converted unless --include-low-coverage.
