# IEEE conference-paper candidate

**Status: DRAFT CANDIDATE, v2 (FINAL-02).** The FINAL-01 version is kept unchanged as `main_v1_final01.tex` / `main_v1_final01.pdf`. It is not submitted and has not been reviewed by Agent 1 or the supervisor. The author and affiliation fields are placeholders on purpose.

## Build

```
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

You can also run `latexmk -pdf main`. v2 compiles to 5 pages in IEEE conference format.

- `IEEEtran.cls` is V1.8b and `IEEEtran.bst` is v1.12. Both are LPPL-licensed and copied from the CTAN mirror on GitHub.
- Before submission, replace both with the versions in the target conference's template.

## Where each number comes from

| Claim in the paper | Source file |
|---|---|
| 2015 CDMP vs crowd streets: ratios 2.51 / 1.64 / 1.29, reverse 2.27 | `outputs/dep2_local_run_01/A_evidence_reference/comparison_2015_cdmp_vs_osmin.csv` |
| 2021 CDMP vs bright-VV ratios and nulls | `.../comparison_2021_cdmp_vs_s1_brightvv.csv` |
| 96 wards in both years; 7 exact recurring names | `.../recurrence_2015_2021.json` |
| Depth-class errors: 72 rows lost, 36+42 relabelled; 1,312 of 1,401 verified | `outputs/dep2_reference_exposure_vulnerability_2026/E_documentation/REFERENCE_CODE_AUDIT.md`, `cdmp_depth_class_extracted_vs_verified.csv` |
| 2,350 crowd features, 43 outside the region; 34,355 road polygons | `.../E_documentation/METHODOLOGY.md` |
| 12,255 not-assessed cells; 471,472 scored cells | `docs/susceptibility_review_report.md` |
| No-TWI variant: Spearman 0.982, Jaccard 0.890 | SUS-1 review tables (`outputs/susceptibility_review_v1`) |
| Clusters, PCA, Moran's I, PB-AUC, transfer, intensity | `outputs/ml_exploratory_v1/ml_exp1_summary.json`, `tables/`, `ML_EXP1_REPORT.md` |
| Multi-date radar context: 0.21–1.85 km², Jaccard 0.11, 53% one-date, top-10 wards 74–95%, enrichment 3.4×, ρ ≤ 0.31 | `outputs/s1_temporal_context_v1/s1tc_summary.json`, `tables/` |
| Within-zone AUC, zone-stratified null, Holm/BH over 16 tests | `outputs/ml_review_v1_1/ml_review_summary.json`, `tables/pb_review_statistics.csv` |
| Wetness family 43% weight → 52% variance; TWI 21.3% | `docs/susceptibility_review_report.md` |
| CHIRPS: 22 distinct ward values | `outputs/ml_exploratory_v1/tables/ward_feature_matrix.csv` |
| Figures | `outputs/ml_exploratory_v1/figures/`, `outputs/dep2_local_run_01/F_maps/` (copied unchanged) |

## Before submission

1. **Agent 1 must check every reference in `references.bib`** against the original source: authors, venue, year and DOI.
   - `gcc2026cdmp` and `iwmi2015chennai` are grey literature. Confirm their titles and URLs.
2. Confirm that the evidence-class wording matches the evidence decision log (`docs/final/EVIDENCE_DECISION_LOG.md`).
3. The study area is provisional. If the official GCC boundary is obtained, rerun the pipeline and update the numbers.
4. Add author names, affiliations and an acknowledgement after the supervisor approves.
5. Check the target venue's page limit and anonymisation rules.

## Changes in v2 (FINAL-02) and why

| Change | Reason |
|---|---|
| Pooled out-of-fold AUC is no longer the only presence-background result. Added within-zone AUC, a zone-stratified null and Holm/BH correction over all 16 tests. | Pooled scores come from separately trained zone models and are not directly comparable. The v1 text gave the 2021 area-only p = 0.04 without saying it was uncorrected. |
| The cluster wording now reports the 5th-percentile ARI (0.54), says "moderately stable", and describes the clusters as indicator-profile groups. | v1 called the clusters "stable" from the mean ARI alone. |
| Added that the wetness family holds 43% of the weight and drives 52% of the variance (TWI 21%), and that the no-TWI agreement shows robustness, not validity. | Wording from the SUS-1 review. Note that the prompt's "52% from TWI" is incorrect; 52% is the three-indicator wetness family. |
| CHIRPS now states both facts: about 29 native cells cover the study area, and the wards take 22 distinct values. | Both are true, and v1 gave only the first. |
| Table I now shows the spatial and temporal support of each input. | Shows that the sources differ in resolution, timing and precision. |
| New subsection and Fig. 2: multi-date radar context. | New analysis S1TC-1. |
| Added a calibration and null-model limitation. | Presence-background scores cannot be calibrated without negatives. |
