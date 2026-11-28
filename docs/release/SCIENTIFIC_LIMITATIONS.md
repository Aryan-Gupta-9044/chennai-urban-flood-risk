# Scientific limitations and claim boundaries

This document is intended to prevent implementation progress from being mistaken for scientific validation.

## Study area

The current AOI is provisional and OSM-derived, approximately 435 km². It must not be called an official Greater Chennai Corporation boundary. Boundary provenance, date, edge effects and any future official-boundary replacement must be disclosed.

## Sentinel-1 candidate water signals

S1WC-2 provides water-related radar candidate signals over eight 2021 dates. These are not confirmed floodwater observations. Temporal persistence, candidate-area changes and overlap statistics are descriptive. They do not provide omission/commission error without qualified independent reference data.

S1TC-1 reports candidate area of approximately 0.21–1.85 km² per date, median Jaccard around 0.11, 53% one-date-only area, top-ten ward concentration around 74–95%, enrichment around 3.4× and absolute Spearman correlation no greater than about 0.31 in the examined comparisons. The eight-date sample is small; lack of a detectable monotonic association is not proof of no rainfall relationship.

## Susceptibility

SUS-1 is a relative indicator index, not a flood probability, event-specific inundation map or validated integrated risk score.

- 483,727 AOI cells; 471,472 scored; 12,255 provisional exclusions/not-assessed.
- NoData/excluded cells are not zero or low susceptibility.
- GLO-30 is a DSM; building and vegetation effects may influence terrain derivatives.
- HAND is an Euclidean-nearest-drainage proxy, not a flow-path calculation.
- Water-signature exclusions are provisional, not confirmed permanent water.
- Fill-depth values are mostly zero and may include pit-scale artefacts.
- Correlated wetness indicators can double-count related terrain information.
- Wetness-family weight is about 43% and explains about 52% of index variance; TWI alone explains about 21.3%.
- Removing TWI yields Spearman 0.982 and top-decile Jaccard 0.890. This is sensitivity/robustness evidence, not independent validation.

## Rainfall

CHIRPS has coarse native spatial support: about 29 native cells intersect the AOI and ward aggregation contains 22 distinct values. It is contextual rainfall information, not 200 independent ward-scale observations. The local IST observation-day convention remains an open issue for precise event-day interpretation.

## DEP2 reference and exposure/vulnerability

DEP2 is an integration and documentation workflow, not independent validation. Evidence quality varies by source and event. Reference-code reconciliation identified row losses/relabels; consult the reference-code audit before quoting depth-class counts. The 2015 CDMP and OSM-IN records are qualitative-only under current review, while 2021 CDMP is presence-only under current review.

Exposure features sourced from OSM are subject to coverage, tagging, temporal and positional limitations. A feature count or polygon inventory is not a verified census of exposed assets.

## Exploratory ward analytics and ML

- Ward clusters are indicator-profile groups, not flood-severity classes.
- Original multivariate clustering used n=198 after dropping wards 134 and 135; k=2; first three PCA components explained about 66.2%.
- Mean ARI was about 0.847, fifth percentile about 0.544, ward agreement about 0.856 and silhouette about 0.298. Describe stability as moderate and report distribution, not mean alone.
- The original 2015 physical-indicator pooled OOF AUC was about 0.4267; median within-zone AUC about 0.6889. Scores from separate zone models are not directly comparable when pooled.
- The original 2021 area-only pooled AUC was about 0.5566 with nominal p about 0.0396 across 100 permutations and 16 combinations, uncorrected. The v1.1 correction framework weakens the claim; no robust supervised flood prediction is justified.
- RF null tests with 40 permutations have coarse p-value resolution (minimum approximately 0.0244), insufficient to pass a Holm threshold of 0.003125.
- Presence-background scores are not calibrated probabilities; absence of a report is not a verified non-flood label.
- Exploratory association is not causal evidence.

## Integrated risk and prediction

A defensible integrated risk product requires accepted susceptibility/hazard inputs, independently qualified exposure/vulnerability evidence, explicit weighting/normalisation choices, uncertainty propagation and independent validation. Prediction additionally requires suitable temporal labels, leakage controls and out-of-sample evaluation. These conditions are not currently established.

## Permitted wording

Prefer:
- “water-related candidate signal”
- “reported flood reference”
- “relative susceptibility index”
- “proxy indicator”
- “exploratory ward-level association”
- “descriptive temporal context”
- “evidence quality warning / qualitative-only / presence-only”

Avoid unsupported claims:
- “confirmed flood extent”
- “accurate flood map”
- “flood probability”
- “validated risk score”
- “predicts floods”
- “model accuracy” where only presence-background AUC is available
