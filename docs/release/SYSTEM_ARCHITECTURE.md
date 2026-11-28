# System architecture

## Architectural layers

1. **Configuration and provenance**
   - `config/` contains stage settings, event chronology, source registers and evidence registers.
   - Keep source identifiers, versions, licences, observation dates and processing assumptions traceable.

2. **Input acquisition and preparation**
   - Boundary, DEM/terrain, land-cover, rainfall, Sentinel-1 and reported-reference inputs are prepared through dedicated scripts.
   - Raw and large inputs are managed locally and are not automatically committed to Git.

3. **Core geospatial processing**
   - Ward/AOI processing, DEM/hydrology, land-cover and rainfall preparation feed derived indicators.
   - Sentinel-1 preprocessing and candidate workflows are kept distinct from reference integration.

4. **Analytical products**
   - SUS-1 builds a relative susceptibility stack.
   - S1WC-2 produces water-related candidate signals and persistence context.
   - DEP2 integrates reported reference and exposure/vulnerability evidence.
   - ML-EXP-1 and ML-EXP-1.1 provide exploratory ward analytics and statistical review.
   - S1TC-1 describes multi-date radar temporal context.

5. **Presentation and reporting**
   - `dashboard/` contains the Streamlit application, section modules, libraries and static assets.
   - `outputs/reports/`, selected `outputs/tables/`, `paper/` and `docs/` contain selected reporting artefacts.

6. **Quality assurance**
   - `tests/` covers software behavior.
   - Verification scripts, manifests and SHA-256 records support integration/reproducibility.
   - Independent source/reference review is a separate research activity, not replaced by software tests.

## Important separation of concepts

- Hazard-related candidate signal is not confirmed hazard observation.
- Susceptibility is not exposure or vulnerability.
- Exposure/vulnerability integration is not automatically a validated risk calculation.
- Reported reference records are not automatically ground truth.
- A dashboard layer is a visualisation of an input/output, not a validation result.

## Main code areas

| Area | Location |
|---|---|
| Core orchestration | `scripts/run_pipeline.py` |
| DEP2 | `scripts/dep2_run.py`, `src/dep2/` |
| Susceptibility | `scripts/build_susceptibility_stack.py`, susceptibility modules under `src/` |
| Sentinel-1 | `scripts/s1_*.py`, `scripts/build_s1_temporal_context.py` |
| Rainfall | `scripts/*rainfall*.py`, `scripts/qa_antecedent_rainfall.py` |
| Ward/ML analytics | `scripts/build_ward_analytics.py`, `scripts/build_ml_review.py`, `src/analytics/` |
| Dashboard | `dashboard/app.py`, `dashboard/lib/`, `dashboard/sections/`, `dashboard/static/` |
| Tests | `tests/` |

## Dependency and reproducibility rule

Run a downstream stage only after confirming its upstream inputs, configuration and evidence status. Use versioned output directories for new runs. Do not overwrite accepted baselines without owner approval, a verified backup and a documented before/after comparison.
