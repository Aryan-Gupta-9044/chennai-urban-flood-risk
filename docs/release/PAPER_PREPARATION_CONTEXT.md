# Paper preparation context

## Current manuscript

- Source: `paper/main.tex`
- Current PDF: `paper/main.pdf` (28 November 2026 build)
- Previous draft: `paper/main_v1_final01.tex` and `paper/main_v1_final01.pdf`
- Bibliography: `paper/references.bib`
- Figures: `paper/figures/`
- IEEE template: `paper/IEEEtran.cls`, `paper/IEEEtran.bst`

Current title:

**What Reported Floods Can and Cannot Teach: An Evidence-Aware Multi-Source Framework for Urban Flood Assessment in Chennai, India**

The author block still contains `[Author 1]` and `[Author 2]` placeholders. This is a research draft, not a submission-ready manuscript.

## Main contribution framing

The strongest defensible contribution is an evidence-aware multi-source geospatial workflow that explicitly distinguishes:
- candidate radar signals from confirmed inundation;
- relative susceptibility from flood probability;
- reported reference records from independent ground truth;
- exposure inventories from verified asset censuses;
- exploratory ward patterns from validated prediction.

Do not frame the contribution as a validated operational flood-prediction model.

## Evidence and results to report carefully

### SUS-1
- 30 m grid, EPSG:32644.
- 483,727 AOI cells; 471,472 scored; 12,255 provisional not-assessed/excluded.
- No-TWI sensitivity: Spearman 0.982 and top-decile Jaccard 0.890.
- Wetness family: approximately 43% weight and 52% of index variance; TWI alone approximately 21.3%.
- Robustness under a feature perturbation is not independent validation.

### S1WC-2 / S1TC-1
- Eight dates: 5 Sep, 17 Sep, 29 Sep, 11 Oct, 23 Oct, 4 Nov, 16 Nov, 28 Nov 2021.
- Candidate area: approximately 0.21–1.85 km² per date.
- Median Jaccard approximately 0.11.
- 53% of ever-flagged area was one-date-only.
- Top ten wards held approximately 74–95% of date-level candidate area.
- Enrichment approximately 3.4×.
- Absolute Spearman rho no greater than approximately 0.31 in the examined eight-date comparison.
- These are descriptive candidate-signal metrics, not flood-detection accuracy.

### Rainfall
- About 29 native CHIRPS cells intersect the AOI.
- Ward aggregation has 22 distinct values.
- Preserve both spatial-support facts. Do not imply 200 independent ward-scale rainfall measurements.

### Ward clustering / ML
- Multivariate sample n=198 after dropping wards 134 and 135.
- k=2; first three PCA components explain approximately 66.2%.
- Mean ARI approximately 0.847; fifth percentile approximately 0.544; ward agreement approximately 0.856; silhouette approximately 0.298.
- Describe groups as indicator-profile clusters, with moderate stability, not flood-severity classes.
- Original 2015 physical-indicator pooled OOF AUC approximately 0.4267; median within-zone AUC approximately 0.6889. Separately trained zone-model scores should not be pooled as if directly comparable.
- Original 2021 area-only pooled AUC approximately 0.5566, nominal p approximately 0.0396 across 100 permutations and 16 combinations, uncorrected. The v1.1 multiple-testing review weakens this result.
- No robust supervised flood prediction is justified.

### DEP2 references and exposure
- 2021 CDMP: R0 WARNING, R1 WARNING, presence-only.
- 2015 CDMP: R0 WARNING, R1 FAIL, qualitative-only.
- 2015 OSM-IN: R0 WARNING, R1 FAIL, qualitative-only.
- DEP2 depth-class audit: 72 rows lost, 36+42 relabelled, 1,312 of 1,401 verified. Explain extraction/reconciliation limitations and do not hide the discrepancy.
- Reported 96 wards in both years and seven exact recurring names only with a precise definition and source table.
- The inventory reports 2,350 crowd features, 43 outside region and 34,355 road polygons; clarify what each count represents and avoid equating feature counts with verified exposure.

## FINAL-02 / v2 manuscript changes

1. Added within-zone AUC and zone-stratified null analysis.
2. Added Holm/BH correction over 16 tests; report the test family and correction method transparently.
3. Replaced unqualified “stable” cluster wording with fifth-percentile ARI and “moderately stable”.
4. Clarified that 52% variance is attributable to the wetness family, not TWI alone.
5. Reported both CHIRPS native cell coverage and 22 distinct ward values.
6. Added spatial/temporal support for inputs.
7. Added multi-date radar temporal context.
8. Added calibration and null-model limitations.

## Before submission

1. Agent 1 verifies every entry in `paper/references.bib` against the original source: author order, title, venue, year and DOI/URL.
2. Confirm `gcc2026cdmp` and `iwmi2015chennai` grey-literature metadata and URLs.
3. Match evidence-class wording exactly to `docs/final/EVIDENCE_DECISION_LOG.md`.
4. Reconcile DEP2 depth-class audit and source manifests.
5. Confirm provisional AOI wording; replace only after an official boundary is obtained and affected workflows are rerun.
6. Add author names, affiliations and acknowledgements only after supervisor approval.
7. Check venue page limit, template version, anonymisation, copyright and supplementary-material rules.
8. Rebuild PDF from the reviewed source and check all references, figures, tables and cross-references.
9. Do not submit until the independent evidence/validation go-no-go decision is documented.

## Publication integrity

A passing software test, reproducible CSV or attractive map does not establish scientific validity. Clearly label results as observed, derived, proxy-based, reported, exploratory or independently validated.
