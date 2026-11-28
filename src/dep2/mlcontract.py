"""ML-ready data contract, leakage-prevention plan and dashboard layer inventory (next milestone)."""
from __future__ import annotations

import pandas as pd

from .common import write_csv, write_json

FEATURES = [
    # name, group, dtype, unit, source, missing_rule
    ("unit_id", "key", "string", "-", "ward_no (W###) or grid cell (r,c) on the SUS-1 30 m master grid", "never missing"),
    ("unit_type", "key", "string", "-", "'ward' | 'grid30' | 'block300'", "never missing"),
    ("geometry_ref", "key", "string", "-", "GPKG layer + fid, or grid row/col (EPSG:32644, x0=406020, y0=1463310, 30 m)", "never missing"),
    ("event_id", "key", "string", "-", "'2015_nd' | '2021_nd' (separate events, never pooled for validation)", "never missing"),
    ("obs_date", "key", "date", "ISO", "Sentinel-1 date (UTC) or report date", "null if source gives year only"),
    ("obs_time_utc", "key", "time", "UTC", "S1 ~00:31 UTC (06:01 IST); reports usually unknown", "null allowed"),
    ("sus1_index", "susceptibility", "float", "0-1", "outputs/susceptibility_v1 (accepted baseline A)", "NoData = not assessed (never 0)"),
    ("sus1_indicators_*", "terrain", "float", "native units", "SUS-1 feature stack (7 indicators; TWI correlated)", "NoData = not assessed"),
    ("rain_prior_{1,3,7,14,30}d_mm", "rainfall", "float", "mm", "CHIRPS (0.05 deg) / IMD (0.25 deg) antecedent windows", "coarse support: identical for many units"),
    ("s1_vv_db, s1_vh_db", "sentinel1", "float", "dB", "S1WC-2 per-date rasters", "invalid cells null"),
    ("s1_bright_vv_flag", "sentinel1", "int", "0/1", "S1PE +5 dB (exploratory)", "null if invalid"),
    ("s1_dark_candidate_class", "sentinel1", "int", "class code", "S1WC-2 candidate classes (exploratory; class 8 = DEM signature)", "null if invalid"),
    ("pop_density", "exposure", "float", "persons/km2", "CDMP ward table (year not stated) or WorldPop 2020 100 m", "null outside coverage"),
    ("road_surface_share", "exposure", "float", "0-1", "TNGIS road polygons", "0 only where mapped and absent"),
    ("critical_facilities_per_km2", "exposure", "float", "1/km2", "TNGIS + CDMP", "-"),
    ("vuln_housing, vuln_adaptive", "vulnerability", "float", "0-1", "DEP-2 components (exploratory); vuln_social MISSING (no defensible ward data)", "null if any indicator missing"),
    ("reference_observation", "label", "int", "1 / null", "presence of an independent report/observation at this unit and event", "NULL (unlabelled) where no report - NEVER 0"),
    ("label_source", "label", "string", "-", "evidence_id(s), e.g. EV-2021-01", "null if unlabelled"),
    ("label_confidence", "label", "string", "-", "'reported-admin' | 'reported-crowd' | 'mapped-extent' | 'derived-digitised'", "null if unlabelled"),
    ("evidence_class", "label", "string", "E1..E5", "evidence register", "null if unlabelled"),
    ("spatial_uncertainty_m", "label", "float", "m", "placement precision radius (50/100/300/750 m) or product accuracy", "null if unknown"),
    ("temporal_uncertainty_days", "label", "float", "days", "e.g. 365 for year-only CDMP records; 0 for dated observations", "null if unknown"),
    ("missing_flags", "qa", "string", "-", "semicolon list of features missing for this row", "-"),
]

LEAKAGE = [
    ("Spatially blocked split", "Assign whole 2 km blocks (or whole wards) to folds; never split neighbouring 30 m cells between train and test."),
    ("Buffer between folds", "Drop cells within one block width of a fold boundary from the test fold (spatial autocorrelation of terrain and S1)."),
    ("Event-level separation", "Train on one event, test on another (2015 vs 2021 vs later); 2015 labels never label 2021 rows and vice versa."),
    ("Temporal separation", "Within 2021, test dates must be later than training dates; antecedent rainfall windows must not include post-observation days."),
    ("Duplicate references", "De-duplicate reports by (location, ward, event) before splitting; a street listed twice must fall in one fold only."),
    ("No candidate-on-candidate testing", "Sentinel-1 candidate classes (E4) may be features or weak labels but must never be the test reference for an S1-derived model."),
    ("No negative labels from silence", "Unreported units are UNLABELLED; presence-only or PU-learning methods only, unless a mapped extent (E1) gives true negatives inside its own footprint and date."),
    ("Ward-level labels", "CDMP records are year-level and street-level; aggregate to ward x event before use; do not burn them into 30 m pixels."),
]

REQUIRED_DATA = [
    "At least one E1 mapped inundation extent for a single date close (<= 3 days) to a Sentinel-1 pass, with documented method and licence (e.g. NRSC 2015 KML if it qualifies; digitised NRSC Cartosat-2E 13 Nov 2021 maps labelled DERIVED).",
    "Dated (not year-only) georeferenced reports for 2021 (e.g. Care Earth Trust crowd map with 'date of peak flooding'; GCC control-room complaint logs with timestamps).",
    "True-negative evidence: areas confirmed dry on a known date (field survey or a mapped extent's 'observed, no water' class).",
    "A second event (e.g. Dec 2023 Michaung) with independent references for out-of-event testing.",
]

DASHBOARD = [
    # layer, path (relative to output dir), type, key, symbology
    ("reported_inundation_2021", "A_evidence_reference/cdmp_inundation_locations_2021.gpkg", "vector point/polygon", "row_id", "categorical by depth_class_verified (very_high #67000d, high #cb181d, medium #fb6a4a, low #fcbba1, unverified white)"),
    ("reported_inundation_2015", "A_evidence_reference/cdmp_inundation_locations_2015.gpkg", "vector", "row_id", "as 2021"),
    ("crowd_flooded_streets_2015_dec2", "A_evidence_reference/osmin_flooded_streets_2015_dec2.gpkg", "vector line", "osm_id", "blue lines #2171b5; label 'reported (crowd)'"),
    ("wards_reported_counts", "A_evidence_reference/ward_reported_inundation_counts.csv", "table", "ward_no", "join to wards; sequential reds by records per km2"),
    ("exposure_wards", "B_exposure/exposure_by_ward.gpkg", "vector polygon", "ward_no", "quantiles; raw quantities and *_score columns separate"),
    ("critical_facilities", "B_exposure/critical_facility_inventory.gpkg", "vector point", "facility_id", "icon by facility_group"),
    ("road_surface", "B_exposure/road_surface_tngis.gpkg", "vector polygon", "-", "grey fill"),
    ("vulnerability_wards", "C_vulnerability/vulnerability_by_ward.gpkg", "vector polygon", "ward_no", "OrRd quantiles; NoData hatched grey"),
    ("integrated_wards", "D_integration/integrated_ward_comparison.gpkg", "vector polygon", "ward_no", "count of top-tercile components (0-3); label 'exploratory, not risk'"),
    ("event_chronology", "A_evidence_reference/event_chronology.csv", "table", "date_ist", "timeline"),
    ("evidence_register", "A_evidence_reference/evidence_register.csv", "table", "evidence_id", "table with class badges E1-E5"),
]


def write_all(ctx):
    G = ctx.G
    write_csv(pd.DataFrame(FEATURES, columns=["feature", "group", "dtype", "unit", "source", "missing_rule"]), G / "ml_feature_schema.csv")
    write_csv(pd.DataFrame(LEAKAGE, columns=["control", "rule"]), G / "ml_leakage_controls.csv")
    write_csv(pd.DataFrame(DASHBOARD, columns=["layer", "path", "type", "key", "symbology"]), G / "dashboard_layer_inventory.csv")
    integ = pd.read_csv(ctx.D / "integrated_ward_comparison.csv")
    rows = []
    for ev, col in (("2015_nd", "cdmp_records_2015"), ("2021_nd", "cdmp_records_2021")):
        for _, r in integ.iterrows():
            has = r[col] > 0
            rows.append({"unit_id": f"W{int(r.ward_no):03d}", "unit_type": "ward", "event_id": ev, "obs_date": None,
                         "reference_observation": 1 if has else None, "label_source": "EV-2021-01" if ev == "2021_nd" and has else ("EV-2015-01" if has else None),
                         "label_confidence": "reported-admin" if has else None, "evidence_class": "E3" if has else None,
                         "spatial_uncertainty_m": None, "temporal_uncertainty_days": 365 if has else None,
                         "n_reports": int(r[col]), "pop_density": r.population_density_cdmp_per_km2, "exposure_index_provisional": r.exposure_index_provisional,
                         "vulnerability_index_provisional": r.vulnerability_index_provisional,
                         "missing_flags": ";".join(k for k in ("population_density_cdmp_per_km2", "vulnerability_index_provisional") if pd.isna(r[k]))})
    lab = pd.DataFrame(rows)
    write_csv(lab, G / "ml_ward_event_table_presence_only.csv")
    write_json(G / "ml_data_contract.json", {
        "status": "CONTRACT ONLY - no model trained",
        "label_policy": "presence-only; unlabelled rows have reference_observation = null (NOT 0)",
        "rows_with_independent_labels": {"2015_nd": int(lab[(lab.event_id == "2015_nd")].reference_observation.notna().sum()),
                                         "2021_nd": int(lab[(lab.event_id == "2021_nd")].reference_observation.notna().sum())},
        "label_strength": "E3 reported, year-level timing: supports presence-only / ward-level analysis; does NOT support supervised accuracy evaluation",
        "required_before_supervised_ml": REQUIRED_DATA,
        "leakage_controls": [dict(control=a, rule=b) for a, b in LEAKAGE]})
    (G / "ML_DASHBOARD_HANDOFF.md").write_text(
        "# ML and dashboard handoff (next milestone)\n\n"
        "**Status:** contract and stable files only. No model was trained and no dashboard was built.\n\n"
        "## What the next milestone can start from\n"
        "- `ml_feature_schema.csv`: the feature columns, units, sources and missing-data rules.\n"
        "- `ml_ward_event_table_presence_only.csv`: one row per ward and event (2015, 2021). Wards with no report are **unlabelled, not negative**.\n"
        "- `ml_leakage_controls.csv`: the rules for spatial, event and temporal separation.\n"
        "- `dashboard_layer_inventory.csv`: each layer's path, key and recommended symbology.\n\n"
        "## Why supervised ML is not yet evaluable\n"
        "The only independent labels are E3. They give year-level timing, street- or locality-level positions, and no true negatives. "
        "The following data would be needed first:\n\n"
        + "\n".join(f"- {x}" for x in REQUIRED_DATA) + "\n", encoding="utf-8")
