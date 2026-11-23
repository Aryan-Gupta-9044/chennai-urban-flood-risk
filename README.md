# Chennai Flood Risk - Version 2.2 (S1B: Nov 2015 SAR flood-extent PROXY, unvalidated)

Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction (Chennai, project B794).
V2 = all V1 modules, unchanged in behaviour, + 4 small fixes + Sentinel-1 modules + V2 documentation (`docs\v2\`).
Version 1 is NOT modified by this package: extract V2 into its own NEW folder.

## V2.2: November 2015 flood-extent proxy (S1B)
Earth Engine parts of this step are UNTESTED until you run them. The result is a SAR proxy, not verified flood extent; no accuracy is claimed.
Run from the project folder (PowerShell). Prerequisites already done on your machine: V1 data, `s1_gee_check.py --event 2015_nov` table.
```
.\.venv\Scripts\python -m pytest -q tests
.\.venv\Scripts\python scripts\s1b_flood_extent.py --event 2015_nov            # plan only (gate + tile plan), no EE work
.\.venv\Scripts\python scripts\s1b_flood_extent.py --event 2015_nov --run      # live re-check, tiled download, processing, report
```
Alternative with Earth Engine export tasks: `... --event 2015_nov --mode drive`, then watch **code.earthengine.google.com -> Tasks tab**
(or `.\.venv\Scripts\earthengine task list`), download the GeoTIFF from Drive folder `chennai_flood_s1b`, and run `... --event 2015_nov --from-tif <file>`.
Outputs (`<id>` = run id printed by the script): `data\processed\s1b\2015_nov\<id>\` (flood_proxy_30m.tif, flood_proxy_10m.tif, composites and diagnostic layers, flood_proxy_30m.geojson, metadata.json),
`outputs\maps\s1b_2015_nov_<id>_*.png`, `outputs\reports\s1b_2015_nov_<id>_report.html`, `outputs\tables\s1b_2015_nov_<id>_stats.json`.
Parameter test: `--set diff_threshold_db=-2.5` (new run id; earlier runs are kept).

## V2.3: hydrological terrain analysis (module HYD)
Terrain-derived flow direction, accumulation and drainage from the existing 30 m DEM. UNVERIFIED: not stormwater infrastructure, not validated. Tested on SYNTHETIC rasters only until you run it on the real DEM.
```
.\.venv\Scripts\python -m pytest -q tests
.\.venv\Scripts\python scripts\process_hydrology.py
```
Options: `--threshold-km2 0.1` or `--threshold-cells N` (drainage threshold), `--max-fill-depth-m 1.0` (depressions deeper than this are kept as sinks), `--dem`, `--slope`, `--out-dir`, `--outputs-dir`, `--no-twi`.
Outputs: `data\processed\dem_conditioned_utm44n_30m.tif`, `flow_direction_d8_utm44n_30m.tif`, `flow_accumulation_utm44n_30m.tif`, `drainage_network_utm44n_30m.tif` (+ `.gpkg`), `twi_utm44n_30m.tif` (only if justified);
`outputs\figures\flow_accumulation_map.png`, `drainage_network_map.png`, `dem_conditioning_difference.png`, `twi_map.png`; `outputs\tables\hydrology_statistics.csv` (+ negative clusters, depression and threshold sensitivity); `outputs\reports\hydrology_methodology.md`.
The original DEM is never modified.

## What is tested and what is not (read this first)
- Tested (Linux build sandbox): 13 unit/import tests; offline pipeline behaviour (failed downloads reported as BLOCKED); V1 modules on a simulated fixture; V1 itself has since been run successfully by you on Windows 11.
- ASF search: ran successfully on your Windows machine (V2.0). The V2.1 orbit changes were tested only with unit tests and a stubbed (simulated) ASF response in the build sandbox, not against live ASF.
- **NOT tested live: everything that uses Google Earth Engine** (including `s1_gee_check.py`). Report any error text.
- `run.ps1` additions for V2: none (same script as V1).

## Immediate goal: Sentinel-1 availability check (Windows 11, PowerShell)
1. Extract `chennai-flood-risk-v2.zip` to a NEW folder, e.g. `C:\Users\aryan\Downloads\chennai-flood-risk-v2`.
2. Open PowerShell in the folder that contains `run.ps1` (File Explorer -> address bar -> type `powershell` -> Enter).
3. Run ONE command (creates its own `.venv`, installs packages once, fetches the study-area boundary, then queries the ASF catalogue):

        powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Only "A1,S1A"

4. Read the result:
   - `outputs\tables\s1_availability_summary.csv`  (verdict per event: PROCESSABLE / MARGINAL / NOT PROCESSABLE)
   - `outputs\tables\s1_scenes_<event>.csv`  (every scene found: date, satellite, orbit, coverage %)
   - `outputs\tables\s1_pairing.json`  (the chosen orbit and scenes)
   - `outputs\reports\implementation_summary.html` and `logs\pipeline.log`
5. Send me the summary CSV (and `logs\S1A_availability.log` if the module says BLOCKED).

Optional, to avoid re-downloading the boundary/ward data: copy `data\raw` from your V1 folder into this folder's `data\raw` before step 3.
To re-run only the availability check later (after the boundary exists):

        .\.venv\Scripts\python scripts\s1_availability.py

Run the tests:

        .\.venv\Scripts\python -m unittest discover tests -v

## V2.1: relative-orbit fix and Earth Engine scene check (no flood detection)
What changed: ASF returned no relative orbit, so V2.0 grouped scenes under "orbit = None". V2.1 reads the relative orbit from the catalogue
when present and otherwise DERIVES it from the absolute orbit with ESA's formula (S1A: (abs-73) mod 175 + 1; S1B: (abs-27) mod 175 + 1);
scenes with unknown orbit are never paired; pairing needs the same direction AND relative orbit. The raw ASF response is now saved in
`data\raw\s1_catalog\` and `outputs\tables\s1_asf_field_diagnostics.json` shows which orbit fields ASF filled. Your earlier V2.0 result files
are copied once to `outputs\tables\archive_before_orbit_fix\` (copy your old `outputs\tables` into the new folder first if you extracted V2.1 elsewhere).
Note: for your five Nov 2015 scenes the ESA formula gives relative orbit **92**, not 164 (164 is simply absolute orbit mod 175 without the
mission offset). Earth Engine's own `relativeOrbitNumber_start` is the tie-breaker; the check below reports it.

1. Re-run the availability check (needs internet; boundary must exist, otherwise use the `-Only "A1,S1A"` command above):

        .\.venv\Scripts\python scripts\s1_availability.py

2. One-time Earth Engine sign-in (PowerShell, in the project folder):

        .\.venv\Scripts\earthengine authenticate

   Then put your Earth-Engine-registered Google Cloud project id in `config\settings.json`:  `"gee": {"project": "YOUR-PROJECT-ID"}`
3. Scene-by-scene check in Earth Engine (queries COPERNICUS/S1_GRD; no flood detection):

        .\.venv\Scripts\python scripts\s1_gee_check.py --event 2015_nov

   Results: `outputs\reports\s1_gee_availability_2015_nov.md` and `outputs\tables\s1_gee_availability_2015_nov.csv`.
   If Earth Engine is not signed in, the report says NOT QUERIED and prints the exact commands.

## Later (NOT needed for the availability check)
Flood extent for one event, only after an event is PROCESSABLE and Earth Engine is set up:

        .\.venv\Scripts\earthengine authenticate
        (put your Cloud project id in config\settings.json -> "gee": {"project": "..."})
        .\.venv\Scripts\python scripts\s1_flood_extent.py --event 2021_nov

Outputs are SAR proxy labels, **unvalidated**; no accuracy is claimed. Compare with an independent reference using
`scripts\compare_reference.py`. Details: `docs\v2\V2_PLAN.md`.

## V1 behaviour (unchanged)
`.\run.ps1` with no `-Only` runs every module (boundary, wards, DEM, rainfall, land cover, features, flood inventory, S1A, S1B,
Random Forest, dashboard check, report). Module states: COMPLETED / PARTIALLY COMPLETED / BLOCKED / NOT STARTED.
S1B and Random Forest report BLOCKED until labels exist - by design. Dashboard: `.\.venv\Scripts\streamlit run dashboard\app.py`.
Manual drop-in folders: `data\external\{boundary,wards,dem,landcover,sentinel1,flood_labels}`.

## Documentation (`docs\v2\`)
V2_PLAN.md | CHANGELOG_V2.md | DATASET_SOURCE_REGISTER.md | IMPLEMENTATION_STATUS.md | RESEARCH_DECISIONS.md | KNOWN_ISSUES_V2.md

## IMD 2015 rainfall demo (V2.3-dev, PROVISIONAL, not validated) — Windows PowerShell
```
python scripts/fetch_imd_rainfall.py --year 2015 --format grd        # or download NetCDF in a browser, then: --register <file>
python scripts/prepare_imd_rainfall.py --year 2015
python scripts/rainfall_workflow.py --source-id imd_gridded_daily --event 2015_nov_dec   # add --min-coverage 0.6 if coastal cells are undefined
```
Send back `outputs/reports/imd_inspection_2015.md` and the workflow report.
