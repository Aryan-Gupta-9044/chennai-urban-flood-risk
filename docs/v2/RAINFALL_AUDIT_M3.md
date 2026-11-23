# M3 - Rainfall module audit and preparation (V2.3-dev)
Evidence labels: (CODE) read from the code; (TEST) shown by a synthetic-data test; (NOT RUN) no real rainfall data has been obtained or processed. No 2015 rainfall values exist in this project yet; the 2023 sample was not used.

## 1. Audit of the existing code (`scripts/process_rainfall.py`, module C) - findings (CODE)
| # | Finding | Severity | Status after M3 |
|---|---|---|---|
| 1 | Event total was `sum(nan_to_num(day, nan=0))`: NaN/nodata cells were treated as 0 mm | HIGH | Fixed: strict total (NaN where any day is missing) |
| 2 | Days that failed to download were simply left out of the event sum (no flag): a silent undercount; module could still end COMPLETED | HIGH | Fixed: missing event days -> no total, status PARTIALLY COMPLETED with the reason |
| 3 | Event window could extend beyond the downloaded sample without any check | MED | Covered by (2) |
| 4 | Daily stats used a bounding-box +-0.025 deg cell selection, not the study-area polygon; empty selection would crash (`nanmax` of empty); failed days were omitted from the table | MED | Fixed: AOI-area-weighted stats, MISSING rows kept with blank values |
| 5 | Spatial coverage never checked: a raster covering only part of the AOI passed silently | MED | Fixed: coverage fraction per day; < 95 % -> INCOMPLETE_COVERAGE, excluded from totals |
| 6 | Only a 30 m nearest-neighbour copy was written, named like a 30 m product; native raster never saved | MED | Fixed: native raster written; the 30 m file keeps its legacy name (build_features reads it) but its band description/figure say RESAMPLED, no 30 m information |
| 7 | No unit handling (mm/day hard-coded); CRS not verified; grid consistency across days not verified | MED | Library: explicit unit conversion (unknown unit raises), CRS check, same-grid check |
| 8 | Day definition (UTC day vs observing day) not recorded | MED | Required field `day_definition` in the new workflow; UNCONFIRMED downgrades status |
| 9 | Config is the 2023 sample only (`sample_*`, `event_*`); no antecedent windows, k-day maxima, climatology | LOW | New `config/rainfall_events.json` (2015 PROPOSED windows) |
| 10 | No rainfall tests existed | MED | `tests/test_rainfall.py` (19 tests) |
| 11 | Download is CHIRPS-only, hard-coded URL; earlier download failures never diagnosed | INFO | Untouched; no source-specific download logic until the source is confirmed |
Downstream: `build_features.py` reads the legacy 30 m file as `rain_event_total_mm`; `train_random_forest.py` drops near-constant rainfall. With ~5 km cells the layer carries almost no spatial information for Chennai (existing KNOWN_ISSUES).

## 2. Changes made (all tested on SYNTHETIC rasters)
- NEW `src/geospatial/rainfall.py`: date ranges/missing dates, unit conversion, per-day cleaning (nodata/negative/over-range -> NaN, genuine 0 preserved), same-grid check, AOI area weights, weighted stats, day classification, strict/lower-bound totals, antecedent window totals (reference day excluded by default), complete-window k-day maxima, source comparability check, non-parametric anomaly (needs >= 10 same-source years).
- NEW `scripts/rainfall_workflow.py` (module C2): source-agnostic, reads daily rasters you place in `data/external/rainfall/<source_id>/` with a filled `source.json`. Outputs: daily series CSV (status per day), native event total + valid-day count, k-day max table, antecedent totals before each Sentinel-1 candidate date, daily-map montage (native cells, common scale, MISSING tiles), report. Optional `--resample-to-master` (labelled) and `--allow-partial` (labelled LOWER BOUND). Anomaly: not computed unless a same-source baseline exists (not yet supported by input layout).
- MODIFIED `scripts/process_rainfall.py`: items 1-6 above, nothing else; same outputs/names plus a native raster.
- NEW configs: `rainfall_events.json` (2015 windows PROPOSED, not verified), `rainfall_sources.json` (candidates, everything unconfirmed), `rainfall_source_template.json`.
- `src/utils/status.py`: module C2. Not touched: DEM, hydrology, Sentinel-1 code/outputs.

## 3. Can the workflow take IMD, CHIRPS or ERA5? (design review)
- CHIRPS / IMD gridded: yes, if delivered as one georeferenced daily raster per day in mm (or convertible units) on a stable grid. They stay separate products; nothing mixes them.
- ERA5/ERA5-Land: only after source-specific work: precipitation is a model accumulation (metres, forecast-window based) and needs de-accumulation and a day-boundary decision. NOT implemented, deliberately.
- Misleading-comparison risks the code blocks or flags: mixed sources/resolutions/day definitions (`comparable`), anomaly without a same-source multi-year baseline, resampled rainfall presented as 30 m, partial windows presented as totals, missing days as zero.
- Day boundaries differ between products (UTC calendar day vs an observing-day convention), which matters because Sentinel-1 overpasses are ~00:31 UTC (~06:01 IST): whether "rain on the acquisition date" is before or after the pass depends on the definition. Antecedent tables therefore use only days BEFORE the date and state the convention.

## 4. Required input datasets and formats
1. Daily rainfall, one source, 2015-08-01 to 2015-12-20 (context window; event window proposed 2015-11-08..12-05), one file per day.
2. Format: georeferenced raster (GeoTIFF; NetCDF/binary must be converted first), single band, CRS stated (default expected EPSG:4326), fixed grid for all days, documented nodata, unit in {mm, mm/day, kg m-2, m, cm} or a rate with accumulation hours.
3. `source.json` (template provided): source id, version, product type, unit, day definition, file pattern, expected CRS, native resolution, provenance, licence note.
4. For anomaly: the same source's daily or window totals for >= 10 other years, same calendar window, same grid (not yet requested, not supported until supplied).
5. Optional independent check: station/gauge daily series (table: station, lat, lon, date, mm, day definition); not implemented as a module.

## 5. Ready vs blocked
READY (tested on synthetic data): all handling rules, workflow, tests, configs, antecedent-before-Sentinel-1 tables.
BLOCKED pending source confirmation (Agent 1 / you): which product; its day definition, units, grid, licence; any download logic; ERA5 de-accumulation; climatology for anomaly; confirmation of the 2015 event windows.
NOT RUN: everything on real data. No rainfall evidence yet exists for the Sentinel-1 baseline-dryness question.

## 6. Tests
`python -m pytest -q tests`: see CHANGELOG entry for the latest counts.
