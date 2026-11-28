# Complete pipeline guide

This guide describes the workflow structure and safe entry points. It is not a blanket instruction to rerun every stage: source data may be large, restricted, locally cached or not present in a clean checkout.

## 1. Environment check

From the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\check_environment.py
```

Confirm Python, key geospatial libraries, configuration paths and local input availability before starting processing.

## 2. Configuration and source review

Review the relevant files in `config/` before each workflow. Current configuration inventory includes:

- `settings.json`
- `rainfall_events.json`, `rainfall_sources.json`, `rainfall_source_template.json`
- `reference_datasets.json`
- `s1_candidate_roles.json`, `s1_events.json`, `s1_inventory_events.json`
- `s1_preprocess.json`, `s1_water_candidates.json`, `s1_water_candidates_v2.json`
- `susceptibility.json`, `susceptibility_review.json`
- `dep2.json`, `dep2.local.json`, `dep2.cloud_run.json`, `dep2_sources.json`
- `event_chronology.json`, `evidence_register.json`

Do not commit credentials, access tokens, restricted source documents or local-only configuration values.

## 3. Core geospatial pipeline

` scripts/run_pipeline.py ` is the main orchestration entry point. Inspect its current CLI/help and configuration before execution:

```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py --help
```

The pipeline's logical sequence is:

1. Acquire/verify study boundary and ward inputs.
2. Prepare ward geometry and spatial reference.
3. Prepare DEM and terrain/hydrology derivatives.
4. Prepare land-cover and other environmental indicators.
5. Prepare rainfall sources and antecedent context.
6. Prepare Sentinel-1 observations and date-level coverage.
7. Generate water-related candidate products and persistence context.
8. Build SUS-1 susceptibility stack and sensitivity outputs.
9. Integrate reported references and DEP2 exposure/vulnerability evidence.
10. Build ward analytics and ML review outputs.
11. Generate reports, maps and dashboard-ready products.

Actual execution order and dependencies are controlled by code/configuration and may differ from this conceptual overview. Do not infer a stage's completion from its presence in the list.

## 4. Rainfall workflow

Relevant scripts include:

- `fetch_chirps_rainfall.py`
- `prepare_chirps_rainfall.py`
- `fetch_imd_rainfall.py`
- `prepare_imd_rainfall.py`
- `compare_chirps_imd.py`
- `qa_antecedent_rainfall.py`
- `rainfall_workflow.py`
- `process_rainfall.py`

CHIRPS is coarse relative to ward scale. The AOI has approximately 29 native CHIRPS cells and the ward feature matrix contains 22 distinct CHIRPS values. Do not describe the resulting values as independent ward-scale rainfall observations. The local IST observation-day convention remains a known interpretive issue for event-date comparisons.

## 5. Sentinel-1 workflow

Relevant scripts include `s1_inventory.py`, `s1_preprocess_2021.py`, `s1_preprocess_persistence.py`, `s1_water_candidates_review.py`, `s1_water_candidates_v2_review.py`, and `build_s1_temporal_context.py`.

S1WC-2 covers eight dates:
5 Sep, 17 Sep, 29 Sep, 11 Oct, 23 Oct, 4 Nov, 16 Nov and 28 Nov 2021.

Interpret class 1 / candidate flags as water-related radar candidates, not confirmed floodwater. Candidate area across the temporal context analysis was approximately 0.21–1.85 km² per date; median pairwise Jaccard was about 0.11; 53% of ever-flagged area appeared on one date only. These are descriptive metrics, not accuracy estimates.

## 6. SUS-1 susceptibility workflow

Main entry point:

```powershell
.\.venv\Scripts\python.exe scripts\build_susceptibility_stack.py --help
```

The accepted baseline uses a 30 m grid in EPSG:32644. Current review figures include 483,727 AOI cells, 471,472 scored cells and 12,255 provisionally excluded/not-assessed cells. The AOI is provisional. GLO-30 is a DSM; HAND is an Euclidean-nearest-drainage proxy. The no-TWI sensitivity comparison (Spearman 0.982; Jaccard 0.890) supports ranking robustness under that perturbation, not independent validity.

## 7. DEP2 reference/exposure/vulnerability workflow

Main entry point:

```powershell
.\.venv\Scripts\python.exe scripts\dep2_run.py --help
```

Use the local configuration for a local Windows execution and the cloud configuration only in the intended cloud environment. The locally recorded run using `config/dep2.local.json` exited successfully. DEP2 has 26 dedicated tests recorded as passing.

Reference evidence quality remains differentiated. For example:
- 2021 CDMP: R0 WARNING, R1 WARNING, presence-only.
- 2015 CDMP: R0 WARNING, R1 FAIL, qualitative-only.
- 2015 OSM-IN: R0 WARNING, R1 FAIL, qualitative-only.

These labels are evidence-quality outcomes, not necessarily software pipeline failures. The reference-code audit also records depth-class extraction/reconciliation issues: 72 rows lost, 36+42 relabelled, and 1,312 of 1,401 verified. Consult `outputs/dep2_reference_exposure_vulnerability_2026/E_documentation/REFERENCE_CODE_AUDIT.md` and its accompanying CSV before citing those values.

The DEP2 integration package contained 146 files; 62 sources were acquired/verified. Acquisition and copied-file manifests require reconciliation; do not assume every acquired source was integrated.

## 8. Ward analytics and ML review

Relevant entry points:

```powershell
.\.venv\Scripts\python.exe scripts\build_ward_analytics.py --help
.\.venv\Scripts\python.exe scripts\build_ml_review.py --help
```

ML-EXP-1 is exploratory. Clusters describe indicator-profile groups, not flood severity. The v1.1 review adds within-zone AUC, zone-stratified nulls and multiple-testing corrections. The reproducibility rerun produced identical statistical CSV and permutation/null-draw CSV hashes, and a pixel-identical comparison figure, with matching input hashes. This establishes computational reproducibility for those artefacts, not predictive validity.

## 9. Dashboard and reporting

Run the dashboard using the command in `DASHBOARD_GUIDE.md`. Check output availability and selected layers before interpreting the map. Dashboard screenshots in `docs/final/` and `docs/final02/` are integration evidence snapshots, not substitutes for a live review.

## 10. Safe rerun protocol

Before any rerun:
1. Confirm exact inputs and their hashes.
2. Confirm configuration and environment.
3. Inspect CLI help and output path behavior.
4. Choose a new versioned output directory.
5. Preserve accepted outputs and backups.
6. Record command, start/end time, exit code and warnings.
7. Compare outputs and hashes.
8. Do not upgrade evidence status solely because a workflow completed successfully.
