# Integration and Validation Plan

## A. DEP2–SUS-1 integration

### Inspect first
- `src/dep2/`
- `src/analytics/`
- `src/flood_detection/`
- `scripts/dep2_run.py` (verify path)
- `config/dep2.json`
- DEP2 outputs and SUS-1 outputs
- `docs/final02/FINAL02_INTEGRATION_GUIDE.md`
- Historical `sus1_overlay_NOT_RUN.json`

### Scientific compatibility checklist
- CRS equality or documented reprojection.
- Grid origin, resolution, alignment and extent.
- AOI consistency.
- Nodata and water-exclusion masks.
- Temporal comparability.
- Spatial support of each variable.
- Aggregation and resampling effects.
- Correlated inputs and double counting.
- Missing coverage and evidence-quality flags.
- Sensitivity to alternative aggregation choices.

### Decision
Compare:
1. SUS-1 susceptibility-only.
2. DEP2 exposure/vulnerability-only.
3. Multi-layer exploratory screening.

Do not create a single numerical risk score unless the conceptual model, weights, evidence and uncertainty are defensible. Any exploratory overlay must be saved in a new versioned output directory.

## B. Independent validation

### Source inventory
For each candidate observation record:
- issuing authority/provider;
- original URL and retrieval date;
- event date/time;
- spatial coverage;
- CRS and resolution;
- observation method;
- license;
- processing;
- independence from model inputs;
- evidence status.

### Possible comparison types
- Independent spatial validation.
- Independent temporal validation.
- Event-based validation.
- Correlated comparison.
- Qualitative comparison.
- Presence-only evidence.

### Metrics only when justified
Potential metrics include IoU/Jaccard, precision, recall, omission/commission, ward-level agreement, distance-based comparison and area-weighted agreement. Do not compute classification metrics without suitable labels and sampling.

## C. ML review

- Reproduce source tables from code.
- Compare pooled and within-zone AUC.
- Verify zone-stratified permutation design.
- State the multiple-testing family.
- Check leakage and spatial dependence.
- Address sample size and excluded wards.
- Report permutation count and attainable p-value resolution.
- Preserve exploratory interpretation.
- No probability calibration or flood-prediction accuracy claim without appropriate independent observations and calibration design.

## D. Required outputs

- `docs/research/DEP2_SUS1_SCIENTIFIC_AUDIT.md`
- `docs/research/INTEGRATION_DECISION_LOG.md`
- `docs/research/VALIDATION_GAP_ANALYSIS.md`
- `docs/research/INDEPENDENT_COMPARISON_PROTOCOL.md`
- `docs/research/VALIDATION_DATA_INVENTORY.csv`
- `docs/research/VALIDATION_RESULTS.md`
- `docs/research/ML_STATISTICAL_AUDIT.md`
- `docs/research/ML_DECISION_REGISTER.csv`
