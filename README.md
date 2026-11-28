# Chennai Urban Flood-Risk Mapping and Prediction Framework

**Project:** Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data
**Study area:** Chennai, Tamil Nadu, India
**Project reference:** B794
**Release documentation baseline:** 28 November 2026
**Current research paper:** `paper/main.tex` and `paper/main.pdf` (working draft; not submission-ready)

## Project purpose

This repository develops a reproducible geospatial workflow for examining urban flood-related conditions in Chennai using multi-source data. It brings together Sentinel-1 radar-derived water-related candidates, rainfall context, terrain and susceptibility indicators, exposure/vulnerability datasets, reported flood references, exploratory ward analytics, and a dashboard.

The framework is **evidence-aware**: data products with different spatial/temporal support and confidence are kept distinct. A candidate signal, proxy, reported location, or exploratory model output is not automatically treated as observed flood extent, validated risk, or a flood prediction.

## Current implementation at a glance

| Workstream | Current state | Important qualification |
|---|---|---|
| S1WC-2 Sentinel-1 candidate workflow | Implemented and tested | Candidate water-related signal; not confirmed floodwater |
| SUS-1 susceptibility | Implemented and reviewed | Provisional OSM-derived AOI; relative susceptibility index, not flood probability |
| Rainfall / CHIRPS / IMD context | Implemented with QA workflows | CHIRPS is coarse; daily observation convention and source limitations must be disclosed |
| DEP2 reference, exposure and vulnerability integration | Implemented locally and tested | Reference quality varies; integration is not independent validation |
| ML-EXP-1 exploratory ward analysis | Implemented | Descriptive/exploratory; no robust supervised flood prediction justified |
| ML-EXP-1.1 statistical review | Implemented and reproducibility rerun completed | Corrected inference weakens nominal findings; presence-background results are not calibrated |
| S1TC-1 multi-date temporal context | Implemented | Descriptive temporal context across eight dates; no causal inference |
| Streamlit dashboard | Implemented; user-reported visual check completed | Dashboard presentation does not establish scientific validity |
| Integrated validated flood-risk / prediction model | Not established | Requires qualified independent references, accepted exposure inputs and defensible validation design |

For the detailed task history and decision records, see `PROJECT_MASTER_CONTROL.md`, `docs/final/`, and `docs/final02/`. The master-control file contains historical task/status entries; read this README and the dated FINAL-02 evidence alongside it rather than assuming every older action item is still current.

## Repository layout

```text
config/                 Workflow configuration and source/evidence registers
dashboard/              Streamlit app, sections, libraries, static assets
docs/                   Methods, reviews, integration evidence and release guides
outputs/                Selected reports, tables and figures (not raw-data archive)
paper/                  IEEE-style manuscript draft, bibliography and figures
scripts/                Pipeline, preprocessing, QA, analytics and review scripts
src/                    Python implementation modules
tests/                  Automated tests
```

Local backups, raw/large geospatial inputs, temporary SHIVE package assemblies, acquisition caches and selected rerun outputs are intentionally excluded from Git.

## Environment and setup

Use Python from the repository's project virtual environment on Windows:

```powershell
.\.venv\Scripts\python.exe scripts\check_environment.py
```

Install dependencies only after reviewing the repository's dependency files and your environment. Dashboard and DEP2 have additional requirement files:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dep2.txt
```

These commands are setup examples; use the project lock/requirements state and documented environment appropriate to your machine. Do not install cloud-only or optional packages unless that workflow requires them.

## Run the dashboard

From the repository root:

```powershell
& ".\.venv\Scripts\python.exe" -m streamlit run dashboard\app.py
```

Alternatively, use the supplied launcher if present:

```powershell
.\run_dashboard.ps1
```

The dashboard uses the local processed outputs and configuration available in the checkout. A clean checkout without the corresponding data products may show unavailable-data states; do not interpret missing layers as zero values.

See `docs/release/DASHBOARD_GUIDE.md` and `docs/release/DASHBOARD_SCREENSHOTS.md`.

## Run tests

The latest recorded complete local Windows test run, excluding the temporary duplicate package assembly from pytest discovery, was:

- **569 passed**
- **1 skipped**
- **0 failed**
- **3,508 warnings**
- Command:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q --ignore=shive_upload_parts_20261126_093923
```

The temporary assembly is local-only and ignored by Git. In a clean checkout where it is absent, the ordinary command is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Warnings included a GeoPandas/Shapely `unary_union` deprecation at `scripts/s1_preprocess_2021.py:294`. A passing test suite verifies software behavior covered by those tests; it does not independently validate the scientific interpretation or the flood reference data.

See `docs/release/TESTING_AND_REPRODUCIBILITY.md`.

## Main workflow entry points

The repository contains multiple stage-specific scripts. Start with the configuration and documentation before running a stage. Common entry points include:

- `scripts/run_pipeline.py` — core pipeline orchestration.
- `scripts/dep2_run.py` — DEP2 reference/exposure/vulnerability workflow.
- `scripts/build_susceptibility_stack.py` — SUS-1 stack construction.
- `scripts/s1_preprocess_2021.py` and `scripts/s1_preprocess_persistence.py` — Sentinel-1 preprocessing and persistence.
- `scripts/rainfall_workflow.py` — rainfall workflow.
- `scripts/build_s1_temporal_context.py` — multi-date radar temporal context.
- `scripts/build_ml_review.py` — ML-EXP-1.1 review.
- `scripts/verify_dashboard.py` — dashboard verification helper.

See `docs/release/COMPLETE_PIPELINE_GUIDE.md` for stage order, commands to inspect, and safeguards. Do not run a full pipeline blindly: confirm inputs, configuration, output directory and overwrite behavior first.

## Scientific interpretation and limitations

- The study-area boundary is provisional and OSM-derived, not an official GCC boundary.
- Sentinel-1 class/candidate signals are not confirmed floodwater observations.
- GLO-30 is a digital surface model (DSM), not a bare-earth DTM.
- HAND is an Euclidean-nearest-drainage proxy, not flow-path HAND.
- CHIRPS has coarse native spatial support; it must not be described as ward-scale rainfall observation.
- SUS-1 is a relative susceptibility index, not a flood probability or validated flood-risk map.
- NoData / excluded cells mean **not assessed**, not zero or low susceptibility.
- DEP2 reference evidence has varying quality and does not currently establish an independent ground-truth dataset.
- ML outputs are exploratory; no robust supervised flood prediction is justified by the current evidence.
- Integrated validated risk and predictive performance claims are not established.

See `docs/release/SCIENTIFIC_LIMITATIONS.md` and the evidence decision log.

## Research paper

The current manuscript is `paper/main.tex`, with PDF `paper/main.pdf`. It is a working IEEE-style research draft titled:

> What Reported Floods Can and Cannot Teach: An Evidence-Aware Multi-Source Framework for Urban Flood Assessment in Chennai, India

The author block still contains placeholders. Bibliographic verification, evidence wording, boundary provenance, supervisor approval, acknowledgements and venue requirements remain before submission. The previous draft `paper/main_v1_final01.*` is retained for history and must not be mistaken for the current version.

See `docs/release/PAPER_PREPARATION_CONTEXT.md`.

## Data, licensing and responsible redistribution

Do not commit raw source archives or restricted documents merely because they were used locally. In particular, CDMP 2026/2024 PDFs marked `redistribute:false` must not be redistributed. Preserve source URLs, licences, access dates, checksums and acquisition notes in provenance registers. Use the source manifests and `docs/final/` / `docs/final02/` evidence rather than copying restricted files into Git.

## Release integrity

Before committing or publishing:

1. Review `git status` and the exact staged file list.
2. Exclude local backups, temporary package assemblies, caches, raw datasets, secrets and restricted source files.
3. Run tests from a clean/appropriate environment.
4. Inspect diffs, generated reports and paper figures.
5. Keep documentation claims consistent with evidence statuses.
6. Do not commit, push or merge without project-owner approval.

## Team responsibilities

- **SHIVE:** implementation, code, tests, packaging and reproducible execution.
- **Agent 1:** independent research, source/reference verification, provenance/licensing review and methodological assessment.
- **Project owner:** decisions, acceptance, priorities and release approval.

## Status language

Use `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `READY FOR REVIEW`, `ACCEPTED`, `ACCEPTED WITH QUALIFICATIONS`, `REJECTED`, `SUPERSEDED`, and `UNVERIFIED` precisely. A reported completion is not accepted until its evidence is reviewed.
