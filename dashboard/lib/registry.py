"""Single registry of every file the dashboard reads (read-only). A missing file is shown as missing, never invented."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
O = ROOT / "outputs"
DEP2 = O / "dep2_local_run_01"          # the accepted local Windows DEP2 run (project AOI)
MLX = O / "ml_exploratory_v1"
SUS = O / "susceptibility_v1"
SUSR = O / "susceptibility_review_v1"
S1WC2 = O / "s1_water_candidates_review_v2"
S1PE = O / "s1_2021_persistence_v1_2"
S1TC = O / "s1_temporal_context_v1"        # FINAL-02: multi-date context of S1WC-2 candidates
MLR = O / "ml_review_v1_1"                 # FINAL-02: ML-EXP-1.1 within-zone / stratified-null review
# The local DEP2 run wrote no E_documentation files; these documents come from the DEP2 cloud package (same code).
DEP2DOC = O / "dep2_reference_exposure_vulnerability_2026"
PROC = ROOT / "data" / "processed"

P = {
    "status": O / "reports/status.json",
    "aoi_wgs84": PROC / "study_area_wgs84.geojson",
    "aoi_meta": PROC / "study_area_meta.json",
    "wards_gpkg": DEP2 / "D_integration/integrated_ward_comparison.gpkg",
    "integrated_csv": DEP2 / "D_integration/integrated_ward_comparison.csv",
    "integrated_corr": DEP2 / "D_integration/integrated_correlation_spearman.csv",
    "high3": DEP2 / "D_integration/wards_high_on_reported_exposure_vulnerability_exploratory.csv",
    "sus1_overlay": DEP2 / "D_integration/sus1_top_decile_exposure_by_ward.csv",
    "sus1_overlay_unchanged": DEP2 / "D_integration/sus1_overlay_inputs_unchanged.json",
    "evidence_register": DEP2 / "A_evidence_reference/evidence_register.csv",
    "chronology": DEP2 / "A_evidence_reference/event_chronology.csv",
    "s1_reassess": DEP2 / "A_evidence_reference/s1_2021_date_reassessment.csv",
    "r012": DEP2 / "A_evidence_reference/R0_R1_R2_summary.csv",
    "r1_2015": DEP2 / "A_evidence_reference/R1_supplementary_temporal_2015_vs_s1_2015.csv",
    "cmp2021": DEP2 / "A_evidence_reference/comparison_2021_cdmp_vs_s1_brightvv.csv",
    "cmp2015": DEP2 / "A_evidence_reference/comparison_2015_cdmp_vs_osmin.csv",
    "recurrence": DEP2 / "A_evidence_reference/recurrence_2015_2021.json",
    "cdmp_summary": DEP2 / "A_evidence_reference/cdmp_records_summary_by_year.csv",
    "cdmp_depth_xt": DEP2 / "A_evidence_reference/cdmp_depth_class_extracted_vs_verified.csv",
    "cdmp_2015": DEP2 / "A_evidence_reference/cdmp_inundation_locations_2015.gpkg",
    "cdmp_2021": DEP2 / "A_evidence_reference/cdmp_inundation_locations_2021.gpkg",
    "osmin_dec2": DEP2 / "A_evidence_reference/osmin_flooded_streets_2015_dec2.gpkg",
    "ward_reports": DEP2 / "A_evidence_reference/ward_reported_inundation_counts.csv",
    "exposure": DEP2 / "B_exposure/exposure_indicators_by_ward.csv",
    "facilities": DEP2 / "B_exposure/critical_facility_inventory.gpkg",
    "pop_zone_chk": DEP2 / "B_exposure/population_cdmp_zone_reconciliation.csv",
    "wp_info": DEP2 / "B_exposure/population_worldpop2020_info.json",
    "top_exposed": DEP2 / "B_exposure/top20_exposed_wards_provisional_index.csv",
    "vuln": DEP2 / "C_vulnerability/vulnerability_indicators_components_by_ward.csv",
    "vuln_def": DEP2 / "C_vulnerability/vulnerability_indicator_definitions.csv",
    "vuln_missing": DEP2 / "C_vulnerability/vulnerability_missing_indicators.csv",
    "vuln_corr": DEP2 / "C_vulnerability/vulnerability_indicator_correlation_spearman.csv",
    "vuln_sens": DEP2 / "C_vulnerability/vulnerability_sensitivity.csv",
    "vuln_weights": DEP2 / "C_vulnerability/vulnerability_weights_normalisation.json",
    "vuln_rank": DEP2 / "C_vulnerability/vulnerability_ranking.csv",
    "limitations": DEP2DOC / "E_documentation/LIMITATIONS_AND_BLOCKERS.csv",
    "provenance": DEP2DOC / "E_documentation/DATA_PROVENANCE_AND_LICENSING.csv",
    "dep2_manifest": DEP2 / "run_manifest.json",
    "dep2_sums": DEP2 / "SHA256SUMS.txt",
    "acq_log": ROOT / "data/external/dep2_sources/ACQUISITION_LOG.json",
    "ml_contract": DEP2 / "G_ml_dashboard/ml_data_contract.json",
    "ml_leakage": DEP2 / "G_ml_dashboard/ml_leakage_controls.csv",
    "ml_schema": DEP2 / "G_ml_dashboard/ml_feature_schema.csv",
    "layer_inventory": DEP2 / "G_ml_dashboard/dashboard_layer_inventory.csv",
    # SUS-1
    "sus_pct": SUS / "rasters/susceptibility_percentile.tif",
    "sus_domain": SUS / "rasters/domain_class.tif",
    "sus_stack": SUS / "rasters/feature_stack_raw.tif",
    "sus_c": SUSR / "rasters/index_C_reduced_no_twi.tif",
    "sus_c_diff": SUSR / "rasters/percentile_difference_C_minus_A.tif",
    "sus_c_agree": SUSR / "rasters/top_decile_agreement_C_vs_A.tif",
    "sus_domain_summary": SUS / "tables/domain_summary.csv",
    "sus_corr": SUS / "tables/indicator_score_correlation_spearman.csv",
    "sus_schemes": SUSR / "tables/t1_scheme_distribution_and_overlap.csv",
    "sus_contrib": SUSR / "tables/t1_indicator_contribution_by_scheme.csv",
    "sus_stability": SUSR / "tables/t2_ranking_stability_summary.csv",
    "sus_vif": SUSR / "tables/t1_vif_and_effective_n.csv",
    "sus_audit": SUSR / "tables/t3_audit_checks.csv",
    # rainfall
    "chirps15": O / "tables/rainfall_chirps_v3_daily_2015_nov_dec_daily_series.csv",
    "chirps15_ante": O / "tables/rainfall_chirps_v3_daily_2015_nov_dec_antecedent_before_s1.csv",
    "chirps15_maxk": O / "tables/rainfall_chirps_v3_daily_2015_nov_dec_max_k_day.csv",
    "chirps21": O / "chirps_2021/tables/rainfall_chirps_2021_2021_sep_nov_daily_series.csv",
    "chirps21_ante": O / "chirps_2021/tables/rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1.csv",
    "chirps21_maxk": O / "chirps_2021/tables/rainfall_chirps_2021_2021_sep_nov_max_k_day.csv",
    "imd_cmp": O / "cmp_chirps_imd_run_20261128_01/tables/chirps_vs_imd_daily.csv",
    "imd_support": O / "cmp_chirps_imd_run_20261128_01/tables/chirps_vs_imd_support.csv",
    "imd_report": O / "cmp_chirps_imd_run_20261128_01/reports/chirps_vs_imd_comparison.md",
    # Sentinel-1
    "s1_qa": O / "tables/s1_2021_preprocessing_qa.csv",
    "s1_cov": O / "tables/s1_2021_date_level_coverage.csv",
    "s1_inv": O / "tables/s1_inventory_2021_nov_2021-09-01_2021-12-01.csv",
    "s1wc2_counts": S1WC2 / "tables/s1_water_candidates_v2_class_counts_per_date.csv",
    "s1wc2_before_after": S1WC2 / "tables/s1_water_candidates_v2_before_after_counts_per_date.csv",
    "s1wc2_comparability": S1WC2 / "tables/s1_water_candidates_v2_comparability_with_counts.csv",
    "s1wc2_count_raster": S1WC2 / "rasters/s1_water_candidates_v2_class1_candidate_date_count.tif",
    "s1pe_summary": S1PE / "tables/s1_2021_persistence_per_date_summary.csv",
    "s1pe_class_counts": S1PE / "tables/s1_2021_persistence_class_counts.csv",
    "s1pe_freq": S1PE / "rasters/s1_2021_persistence_vv_bright_frequency_gt5.tif",
    # ML-EXP-1
    "s1tc_summary": S1TC / "s1tc_summary.json",
    "s1tc_per_date": S1TC / "tables/s1tc_per_date_summary.csv",
    "s1tc_jaccard": S1TC / "tables/s1tc_class1_jaccard_between_dates.csv",
    "s1tc_persist": S1TC / "tables/s1tc_class1_persistence_histogram.csv",
    "s1tc_enrich": S1TC / "tables/s1tc_class1_sus1_decile_enrichment.csv",
    "s1tc_rain": S1TC / "tables/s1tc_rainfall_context_spearman.csv",
    "s1tc_fig": S1TC / "figures/fig_s1tc_temporal_context.png",
    "s1tc_sums": S1TC / "SHA256SUMS.txt",
    "mlr_summary": MLR / "ml_review_summary.json",
    "mlr_stats": MLR / "tables/pb_review_statistics.csv",
    "mlr_fig": MLR / "figures/fig_within_zone_vs_pooled_auc.png",
    "mlr_sums": MLR / "SHA256SUMS.txt",
    "mlx_summary": MLX / "ml_exp1_summary.json",
    "mlx_features": MLX / "tables/ward_feature_matrix.csv",
    "mlx_dict": MLX / "tables/feature_dictionary.csv",
    "mlx_pca_ev": MLX / "tables/pca_explained_variance.csv",
    "mlx_pca_load": MLX / "tables/pca_loadings.csv",
    "mlx_clusters": MLX / "tables/ward_clusters_and_pcs.csv",
    "mlx_scan": MLX / "tables/cluster_scan.csv",
    "mlx_profiles": MLX / "tables/cluster_profiles.csv",
    "mlx_similarity": MLX / "tables/ward_similarity_top5.csv",
    "mlx_moran": MLX / "tables/morans_i_contiguity.csv",
    "mlx_pb": MLX / "tables/presence_background_cv.csv",
    "mlx_transfer": MLX / "tables/presence_background_event_transfer.csv",
    "mlx_importance": MLX / "tables/association_importance.csv",
    "mlx_intensity": MLX / "tables/report_intensity_spearman.csv",
    "mlx_folds": MLX / "tables/spatial_folds.csv",
    "mlx_scores": MLX / "tables/ward_pb_relative_scores_oof.csv",
    "legacy_rf_raster": PROC / "flood_susceptibility_rf_v0.tif",
}

S1_DATES = ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"]


def exists(key) -> bool:
    return P[key].is_file()


def rel(key) -> str:
    try:
        return P[key].relative_to(ROOT).as_posix()
    except ValueError:
        return str(P[key])


def csv(key, **kw):
    return pd.read_csv(P[key], **kw) if exists(key) else None


def js(key, default=None):
    try:
        return json.loads(P[key].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def s1_class_raster(date):
    return S1WC2 / f"rasters/s1_water_candidates_v2_class_{date}.tif"


def s1_vv(date, pol="VV"):
    return PROC / f"s1_2021/S1A_IW_D092_{date.replace('-', '')}_{pol}_dB.tif"


def missing_report():
    return [{"key": k, "path": rel(k)} for k in P if not exists(k) and k != "legacy_rf_raster"]
