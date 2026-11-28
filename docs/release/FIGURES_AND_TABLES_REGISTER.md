# Figures and tables register

## Paper figures

| Figure file | Intended subject (verify caption against image/source) |
|---|---|
| `paper/figures/fig_cluster_map.png` | Ward indicator-profile cluster map |
| `paper/figures/fig_pca_clusters.png` | PCA / cluster structure |
| `paper/figures/fig_presence_background_auc.png` | Presence-background model comparison |
| `paper/figures/fig_s1tc_temporal_context.png` | Multi-date Sentinel-1 temporal context |
| `paper/figures/fig_three_dimensions.png` | Multi-dimensional framework illustration |
| `paper/figures/fig_within_zone_vs_pooled_auc.png` | Pooled versus within-zone AUC comparison |
| `paper/figures/map_A1_reported_inundation_2021.png` | Reported 2021 inundation/reference map |
| `paper/figures/map_A2_2015_two_reported_sources.png` | 2015 reported-source comparison map |

Do not infer map accuracy from cartographic appearance. Each figure caption should state source, date/epoch, CRS/resolution where relevant, processing and evidence class.

## Key analysis tables and outputs

| Subject | Evidence location |
|---|---|
| 2015 CDMP vs OSM-IN comparison | `outputs/dep2_local_run_01/A_evidence_reference/comparison_2015_cdmp_vs_osmin.csv` |
| 2021 CDMP vs bright-VV comparison | `outputs/dep2_local_run_01/A_evidence_reference/comparison_2021_cdmp_vs_s1_brightvv.csv` |
| Recurrence across years | `outputs/dep2_local_run_01/A_evidence_reference/recurrence_2015_2021.json` |
| DEP2 reference code audit | `outputs/dep2_reference_exposure_vulnerability_2026/E_documentation/REFERENCE_CODE_AUDIT.md` and `cdmp_depth_class_extracted_vs_verified.csv` |
| DEP2 methodology / inventory | `outputs/dep2_reference_exposure_vulnerability_2026/E_documentation/METHODOLOGY.md` |
| SUS-1 review | `docs/susceptibility_review_report.md`, `outputs/susceptibility_review_v1/` |
| ML-EXP-1 summary | `outputs/ml_exploratory_v1/ml_exp1_summary.json`, `tables/`, `ML_EXP1_REPORT.md` |
| S1TC summary | `outputs/s1_temporal_context_v1/s1tc_summary.json`, `tables/` |
| ML-EXP-1.1 review | `outputs/ml_review_v1_1/ml_review_summary.json`, `tables/pb_review_statistics.csv` |

Some output directories may be local-only or excluded from Git. A paper must not cite a file as publicly available unless it is included in the release or an accessible archival location is provided.

## Required caption checklist

- What is shown?
- Which source(s) and product version(s)?
- Observation date/period or epoch?
- Native and output resolution?
- CRS and study-area definition?
- Processing/classification method?
- Evidence class and limitations?
- Is the figure descriptive, derived, proxy-based or independently validated?
