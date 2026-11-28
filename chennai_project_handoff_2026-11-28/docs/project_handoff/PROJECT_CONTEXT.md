# Project Context

## 1. Project identity

**Title:** Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data  
**Geographic focus:** Chennai, Tamil Nadu, India  
**Project type:** Two-person B.Tech research and software project, with an aspiration to develop an IEEE conference-paper candidate.  
**Research/product principle:** Build a useful, reproducible geospatial decision-support framework while distinguishing susceptibility, candidate water signals, exposure, vulnerability, observed inundation and validated prediction.

## 2. Overall objective

Develop an integrated geospatial workflow that combines terrain-derived flood susceptibility, multi-date Sentinel-1 candidate water-related signals, exposure/vulnerability/reference datasets, ward-level exploratory analysis and an interactive dashboard. The framework should be transparent, reproducible and explicit about evidence quality and uncertainty.

The project must not imply that a susceptibility index or exploratory ML experiment is a calibrated operational flood forecast.

## 3. Main analytical components

### SUS-1 — terrain-based susceptibility

A multi-indicator susceptibility surface using terrain and related geospatial variables. Known grid baseline:

- CRS: EPSG:32644.
- Resolution: 30 m.
- Raster dimensions: 1416 × 726.
- AOI cells: 483,727.
- Approximately 471,472 scored cells.
- 12,255 provisional water-signature exclusions.
- 544,289 cells outside AOI.

Important data/method limits:

- AOI is provisional and must not be described as an official GCC boundary unless verified.
- Copernicus GLO-30 is a digital surface model, not a bare-earth DTM.
- HAND is a Euclidean-nearest-drainage proxy, not flow-path HAND.
- TWI is correlated with other wetness indicators.
- Wetness-family indicators account for about 52% of index variation; TWI alone about 21.3%.
- Wetness-family weight is 43%.
- Six-indicator no-TWI sensitivity: Spearman 0.982; top-decile Jaccard 0.890.
- Sensitivity is robustness analysis, not independent validation.

### S1WC-2 — Sentinel-1 temporal context

Eight dates:

- 2021-09-05
- 2021-09-17
- 2021-09-29
- 2021-10-11
- 2021-10-23
- 2021-11-04
- 2021-11-16
- 2021-11-28

Previously accepted checks: eight date rasters reproduced, 483,727 AOI cells, zero mismatches across 16 VV/VH comparisons, 25 tests passed.

Interpretation: class 1 is a candidate water-related signal, not confirmed floodwater. Water-signature exclusions are provisional. DEM=0 is not sea level. Relative TWI is unvalidated.

### DEP2 — reference, exposure and vulnerability

DEP2 combines reference, exposure and vulnerability-related source layers and supporting evidence. Previously reported: 146 files integrated; 62 sources acquired/verified in the existing acquisition work; local Windows pipeline completed with exit code 0; 26 DEP2 tests passed.

Reference classifications at the last documented review:

| Reference | R0 | R1 | Evidence status |
|---|---|---|---|
| 2021 CDMP | WARNING | WARNING | PRESENCE_ONLY |
| 2015 CDMP | WARNING | FAIL | QUALITATIVE_ONLY |
| 2015 OSM-IN | WARNING | FAIL | QUALITATIVE_ONLY |

These are evidence-quality statuses, not pipeline pass/fail or prediction metrics. Acquisition and copied-file manifests require reconciliation. CDMP 2026/2024 PDFs marked `redistribute:false` must not be redistributed.

### ML-EXP-1 / ML-EXP-1.1 — exploratory ward analysis

Known sample: 200 wards; multivariate n=198; wards 134 and 135 excluded from that analysis; k=2 selected for silhouette/interpretability; first three PCA components about 66.2%; mean ARI about 0.847; fifth-percentile ARI about 0.544; ward agreement about 0.856; silhouette about 0.298.

Clusters are indicator-profile groups, not flood-severity classes.

Earlier supervised results included 2015 physical-indicator pooled OOF AUC 0.4267 and median within-zone AUC about 0.6889; 2021 area-only pooled AUC 0.5566 with reported uncorrected permutation p=0.0396. ML-EXP-1.1 applied within-zone AUC, zone-stratified nulls and multiple-testing correction; weak nominal 2015 signal did not survive correction and 2021 did not show a robust supervised signal. Forty RF null permutations limit attainable p-value resolution to about 0.0244.

No robust supervised flood prediction has been established.

### FINAL-02 temporal context

Previously reported candidate area 0.21–1.85 km²/date; median Jaccard about 0.11; 53% one-date-only; ever-flagged area about 4.2 km²; ten wards account for 74–95% of each date's candidate area; enrichment 3.39×; absolute Spearman correlation with antecedent rainfall no greater than 0.31 across only eight observations.

No detectable monotonic relationship in eight observations is not evidence of no rainfall effect. Enrichment is correlated agreement, not independent validation.

## 4. Software and dashboard

Python geospatial stack includes GeoPandas, Rasterio, Shapely, NumPy and related libraries. Dashboard is Streamlit, launched from `dashboard/app.py`. Tests use pytest.

The dashboard was started from the merged baseline using the command in `WINDOWS_RUNBOOK.md`; user visually confirmed it was working. This is a smoke test, not a production deployment certification.

## 5. Collaboration

- **Pro agent:** implementation, engineering, experiment execution, reproducibility, integration, documentation and coordination.
- **Agent 1:** independent literature, source, evidence, methods, statistical and paper review.

Agent 1 must be able to disagree with implementation findings. Do not treat software tests as scientific validation.

## 6. Publication status

`paper/main.tex` and `paper/main.pdf` were present in the release. The README described the manuscript as a draft candidate (FINAL-02 / v2), not submitted and not yet independently reviewed by Agent 1 or supervisor. Author/affiliation placeholders and target-template checks remain. Preserve FINAL-01 historical files.

The project is not yet submission-ready merely because the PDF compiles.
