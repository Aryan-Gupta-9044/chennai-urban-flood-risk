# Project overview

**Baseline date:** 28 November 2026

## Aim

Develop an evidence-aware, reproducible geospatial framework for urban flood-related assessment in Chennai using multi-source spatial and temporal information. The framework is designed to make data provenance, scale, uncertainty and evidence quality visible rather than collapsing all inputs into a single apparently authoritative flood-risk score.

## Research questions the current work can support

1. How can multi-source geospatial inputs with different spatial and temporal support be prepared and compared consistently?
2. Where do terrain, land-cover and drainage-related indicators suggest relatively higher susceptibility under the current provisional study-area definition?
3. What water-related candidate signals are present in the available Sentinel-1 dates, and how persistent are they?
4. What can reported flood-reference data contribute, given their varying positional, temporal and classification quality?
5. What descriptive ward-level patterns are visible in exploratory analytics, and which are too weak or biased to support predictive claims?

## What the project currently delivers

- Reproducible preprocessing and configuration-driven workflows.
- Sentinel-1 water-related candidate and persistence products.
- Rainfall context and QA workflows.
- SUS-1 relative susceptibility indicators and sensitivity review.
- DEP2 reference/exposure/vulnerability integration and evidence documentation.
- Ward-level exploratory analytics and statistical review.
- Temporal context analysis across eight Sentinel-1 dates.
- Streamlit dashboard and paper-oriented figures.
- Tests, manifests, checksums and integration records.

## What it does not yet deliver

The current evidence does not establish a validated event-specific flood extent, calibrated flood probability, validated integrated flood-risk score, or operational flood prediction model. Such claims require independent reference observations with suitable temporal/spatial precision, defensible negative/background sampling, and an appropriate out-of-sample validation design.

## Workstream ownership

| Workstream | Primary responsibility |
|---|---|
| Implementation, code, tests, packaging | SHIVE |
| Independent literature/data/reference verification | Agent 1 |
| Acceptance, prioritisation, decisions and release | Project owner |
| Cross-checking, synthesis and documentation support | ChatGPT + project owner |

## Evidence hierarchy

Keep these classes separate in all reports:

- **Observed/source data:** measurements or source records, with metadata and licensing.
- **Derived product:** output produced by a documented processing workflow.
- **Proxy:** indirect indicator that approximates a process but is not direct observation.
- **Reported reference:** an event/location reported by a source; not automatically ground truth.
- **Exploratory result:** descriptive or model-based analysis not established as predictive/causal.
- **Independently validated result:** only where an independent, qualified reference and suitable validation design exist.

## Key evidence locations

- `PROJECT_MASTER_CONTROL.md`
- `docs/final/EVIDENCE_DECISION_LOG.md`
- `docs/final/FINAL_STATUS_REPORT.md`
- `docs/final02/FINAL02_PATCH_REPORT.md`
- `docs/final02/FINAL02_INTEGRATION_GUIDE.md`
- `docs/susceptibility_review_report.md`
- `docs/reference_integration_R0_R2_report.md`
- `paper/main.tex`
