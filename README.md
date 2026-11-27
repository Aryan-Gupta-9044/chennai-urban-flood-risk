# Chennai Urban Flood-Risk Mapping and Prediction Framework

**Project:** Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data
**Study area:** Chennai, Tamil Nadu, India
**Project reference:** B794
**Repository:** `chennai-urban-flood-risk`

## 1. Project overview

This project develops a reproducible geospatial framework for investigating urban flood-related conditions in Chennai using multi-source Earth observation, terrain, rainfall, hydrological and supporting spatial data.

The intended framework brings together:

- Sentinel-1 SAR observations and water-related candidate analysis.
- Terrain and hydrological indicators derived from elevation data.
- Rainfall observations and antecedent rainfall analysis.
- Flood-reference evidence and independent validation readiness.
- Exposure and vulnerability assessment.
- Integrated flood-risk assessment and, subject to sufficient evidence, prediction.

The project is being developed incrementally. Implemented analytical modules must not be interpreted as a completed, independently validated flood-risk or prediction system.

## 2. Current implementation status

### Implemented technical foundations

| Workstream | Current status |
|---|---|
| Sentinel-1 water-candidate analysis (S1WC) | Implemented; S1WC-2 technical integration accepted |
| Sentinel-1 persistence and antecedent analysis | Implemented and tested |
| Rainfall and CHIRPS workflows | Implemented with workflow isolation and date-source corrections |
| IMD rainfall integration | Implemented provisionally; interpretation and validation limitations remain |
| Hydrological terrain analysis | Implemented and tested |
| Susceptibility mapping (SUS-1) | Baseline implemented and accepted with qualifications |
| Susceptibility sensitivity review | Implemented; independent review findings documented |
| Flood-reference integration checks | R0-R2 integration and automated checks implemented |
| DEP-1 exposure and vulnerability | Requirements and architecture work in progress |
| Independent flood-reference validation | Unresolved; evidence acquisition and qualification ongoing |
| Integrated flood-risk assessment | Not yet validated |
| Flood prediction | Not yet implemented as a validated predictive model |

For the authoritative workstream status, decisions, evidence qualifications and next actions, consult `PROJECT_MASTER_CONTROL.md`.

## 3. Scientific interpretation and limitations

The project distinguishes between:

- **Susceptibility:** relative spatial predisposition based on selected terrain and environmental indicators.
- **Hazard:** the occurrence and characteristics of a potentially damaging flood event.
- **Exposure:** people, buildings, infrastructure and assets located in potentially affected areas.
- **Vulnerability:** the potential degree of harm to exposed people and assets.
- **Risk:** the consequences arising from the interaction of hazard, exposure and vulnerability.
- **Prediction:** estimation of future conditions using a separately specified and evaluated predictive approach.

A susceptibility index is not a flood map, observed inundation extent, flood probability or validated risk estimate.

Important current qualifications include:

- Independent, georeferenced flood-reference data sufficient for quantitative validation have not yet been established.
- Sentinel-1 water-related candidates are not automatically confirmed floodwater.
- Terrain-derived drainage is not a verified stormwater infrastructure inventory.
- The HAND implementation is a proxy and must not be interpreted as fully validated flow-path HAND.
- The elevation data and derived indicators have known limitations, including surface-model effects and possible artefacts.
- CHIRPS has a coarse native spatial resolution relative to the study area and is used with appropriate spatial limitations.
- Some indicators are correlated; equal weighting and index interpretation require explicit qualification.
- The study-area boundary is provisional and must not be presented as an official administrative boundary without verification.
- Excluded or NoData areas must not be interpreted as zero susceptibility or zero risk.

No flood-classification accuracy, predictive accuracy or independent validation performance should be claimed without suitable reference data and a documented evaluation.

## 4. Repository structure

The principal project directories include:

| Directory | Purpose |
|---|---|
| `src/` | Reusable analytical modules |
| `scripts/` | Workflow entry points and processing utilities |
| `config/` | Versioned workflow and parameter configurations |
| `tests/` | Automated unit, integration and safeguard tests |
| `docs/` | Methodology, technical reports and research documentation |
| `data/` | Data organisation; raw and processed datasets are generally excluded from Git |
| `outputs/` | Selected figures, tables and reports |
| `dashboard/` | Project dashboard components |

Generated datasets, local caches, credentials, temporary package assemblies and large source-data archives should not be committed indiscriminately.

## 5. Environment and testing

The project uses Python and a project-local virtual environment on the Windows development machine.

Activate or invoke the project environment from the repository root.

Run the automated test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The latest local verification, with the temporary `shive_upload_parts_20261126_093923` package assembly excluded from test discovery, produced:

- **488 passed**
- **1 skipped**
- **0 failed**

The test run also reported dependency deprecation warnings and geographic-CRS area warnings. These are documented technical-review items; a passing test suite does not independently establish scientific validity.

The temporary package assembly is not part of the intended repository. In a clean checkout where it is absent, the ordinary test command above should be used.

## 6. Reproducibility and data management

The project uses configuration files, source-data manifests, checksums, processing reports and automated tests to support reproducibility.

When reproducing a workflow:

1. Use the documented project environment and configuration.
2. Verify source-data provenance, dates, spatial reference systems and licensing.
3. Preserve original inputs.
4. Use distinct output locations for new runs.
5. Retain run metadata, checksums and processing reports.
6. Distinguish downloaded observations, derived products, proxies and reference evidence.
7. Record blocked, incomplete or uncertain processing honestly.

Raw data and large generated geospatial files are generally excluded from Git through `.gitignore`. Their acquisition and provenance should be documented separately.

## 7. Documentation and project control

Start with these documents:

- `PROJECT_MASTER_CONTROL.md` — current project baseline, ownership, verified findings, decisions, limitations and action register.
- `docs/susceptibility_framework.md` — SUS-1 methodology and interpretation.
- `docs/susceptibility_review_report.md` — independent technical review of susceptibility sensitivity and ranking.
- `docs/s1_water_candidates_review.md` — Sentinel-1 water-candidate review.
- `docs/s1_water_candidates_v2.md` — updated water-candidate methodology and documentation.
- `PATCH_NOTES.md` — recent rainfall workflow correction notes.

Other reports and supporting records are maintained under `docs/` and selected `outputs/` subdirectories.

## 8. Development roadmap

The remaining development is organised around:

1. Finalising and approving DEP-1 exposure and vulnerability requirements.
2. Implementing and testing exposure modules with verified data and provenance.
3. Qualifying independent flood-reference observations and spatial evidence.
4. Evaluating whether the available reference data support quantitative validation.
5. Developing a defensible integrated risk framework only when its component evidence and assumptions are sufficiently established.
6. Investigating predictive modelling only after suitable temporal data, target definitions, independent evaluation and leakage safeguards are available.
7. Improving the dashboard, reporting, reproducibility and publication documentation.

Implementation status and priorities are maintained in `PROJECT_MASTER_CONTROL.md`; this roadmap does not imply that the remaining stages are complete.

## 9. Research and publication integrity

The project prioritises reproducibility, transparent assumptions, traceable data provenance and scientifically defensible interpretation.

All reported results should identify:

- Data source and observation period.
- Spatial and temporal resolution.
- Processing and classification assumptions.
- Reference-data status.
- Known limitations and uncertainty.
- Whether a result is observed, derived, proxy-based, proposed or independently validated.

The framework is intended to become a demonstrable geospatial research product. Publication suitability will depend on the quality of the completed methodology, independent evidence, validation and reproducibility—not simply on the number of implemented modules.
