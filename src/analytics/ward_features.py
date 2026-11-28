"""Ward-level feature matrix built from accepted project products (all read-only).

Inputs and their roles:
* SUS-1 baseline A (accepted):  susceptibility_percentile.tif + domain_class.tif + feature_stack_raw.tif
* SUS-1 review candidate C (NOT adopted, sensitivity only): index_C_reduced_no_twi.tif
* S1WC-2 (exploratory): class-1 / class-8 candidate date-count rasters
* CHIRPS 2021 Sep-Nov event total (0.05 deg): CONTEXT ONLY, about 29 native cells over the AOI
* DEP2 local run (outputs/dep2_local_run_01): exposure, vulnerability, reported evidence
Excluded / missing / outside cells are "not assessed" and never enter a ward mean as zero.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SUS1 = "outputs/susceptibility_v1/rasters"
REVIEW = "outputs/susceptibility_review_v1/rasters"
S1WC2 = "outputs/s1_water_candidates_review_v2/rasters"
GRID = {"crs": "EPSG:32644", "transform": (30.0, 0.0, 406020.0, 0.0, -30.0, 1463310.0), "shape": (1416, 726)}
INDICATORS = ["elevation_m", "slope_deg", "twi", "flow_accumulation", "dist_to_drainage_m", "hand_proxy_m", "fill_depth_m"]

# Feature groups. "use_in_models" is False for anything derived from the reports (leakage), anything coarser than
# a ward (CHIRPS), partial-coverage sources (WorldPop) and reporting-effort proxies kept only as CONTROLS.
FEATURE_SPEC = [
    # name, group, use_in_models, description
    ("sus_a_mean_pct", "susceptibility", True, "SUS-1 baseline A: mean percentile of scored cells in the ward (0-100)"),
    ("sus_a_share_top_decile", "susceptibility", True, "share of scored cells with SUS-1 percentile >= 90"),
    ("sus_c_mean_pct", "susceptibility_sensitivity", False, "SUS-1 candidate C (no-TWI, NOT adopted): mean percentile; for comparison only"),
    ("med_elevation_m", "terrain", True, "median GLO-30 DSM elevation (DSM, not bare earth)"),
    ("med_slope_deg", "terrain", True, "median slope"),
    ("med_hand_proxy_m", "terrain", True, "median height above Euclidean-nearest drainage (NOT flow-path HAND)"),
    ("med_dist_to_drainage_m", "terrain", True, "median distance to DEM-derived drainage"),
    ("med_twi", "terrain", False, "median TWI (near-function of slope and flow accumulation; excluded to limit redundancy)"),
    ("p90_log10_flow_acc", "terrain", True, "90th percentile of log10 flow accumulation"),
    ("s1_class1_any_share", "sentinel1", True, "share of AOI cells that are S1WC-2 class-1 dark candidates on >= 1 date (exploratory, not floodwater)"),
    ("s1_class1_mean_dates", "sentinel1", False, "mean number of class-1 dates per AOI cell (redundant with any_share)"),
    ("s1_class8_any_share", "sentinel1", False, "share on the provisional DEM flattened-water signature (context)"),
    ("pop_density_cdmp", "exposure", True, "CDMP ward population / ward area (reference year not stated)"),
    ("road_surface_share", "exposure", True, "TNGIS road-surface share of ward area"),
    ("facilities_per_km2", "exposure", True, "critical facilities per km2 (TNGIS + CDMP)"),
    ("wp_pop_density_2020", "exposure", False, "WorldPop 2020 density (94 wards only; separate source, not merged)"),
    ("slum_area_share", "vulnerability", True, "slum polygon share of ward area (provenance unresolved)"),
    ("dist_public_health_km", "vulnerability", True, "distance to nearest public health facility"),
    ("relief_capacity_per_1000", "vulnerability", True, "relief-centre capacity per 1,000 residents (protective)"),
    ("chirps_2021_event_mm_coarse", "rainfall_context", False, "CHIRPS v3 Sep-Nov 2021 total at the ward centroid's 0.05 deg cell (context only)"),
    ("area_km2", "control", False, "ward area: CONTROL for reporting opportunity (more area, more chance of >= 1 listed street)"),
    ("assessed_share", "control", False, "share of the ward's grid cells that SUS-1 assessed"),
]


def _rasterize_wards(wards, shape, transform):
    from rasterio.features import rasterize
    return rasterize(((g, int(w)) for g, w in zip(wards.geometry, wards.ward_no)), out_shape=shape, transform=transform, fill=0, dtype="int32")


def _read(path, band=1):
    import rasterio
    with rasterio.open(path) as d:
        a = d.read(band).astype("float64")
        nd = d.nodata
        t = d.transform
        crs = str(d.crs)
        shp = d.shape
    if nd is not None:
        a[a == nd] = np.nan
    return a, t, crs, shp


def check_grid(path):
    import rasterio
    with rasterio.open(path) as d:
        ok = str(d.crs) == GRID["crs"] and tuple(d.transform)[:6] == GRID["transform"] and d.shape == GRID["shape"]
    if not ok:
        raise SystemExit(f"STOP: {path} is not on the accepted SUS-1 master grid")


def _midrank_percentile(v):
    from scipy.stats import rankdata
    out = np.full(v.shape, np.nan)
    m = np.isfinite(v)
    out[m] = (rankdata(v[m]) - 0.5) / m.sum() * 100.0
    return out


def _zonal(ids, a, wards, fn):
    s = pd.Series(a.ravel())
    z = pd.Series(ids.ravel())
    ok = np.isfinite(s.values) & (z.values > 0)
    g = s[ok].groupby(z[ok])
    return wards.ward_no.map(g.agg(fn))


def build(root: Path, wards, dep2_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Return the ward feature table (one row per ward, NaN = not available) and a provenance dict."""
    root = Path(root)
    prov = {"inputs": {}, "notes": []}
    pct_p, dom_p = root / SUS1 / "susceptibility_percentile.tif", root / SUS1 / "domain_class.tif"
    for p in (pct_p, dom_p, root / SUS1 / "feature_stack_raw.tif", root / REVIEW / "index_C_reduced_no_twi.tif",
              root / S1WC2 / "s1_water_candidates_v2_class1_candidate_date_count.tif"):
        check_grid(p)
    pct, tr, _, shp = _read(pct_p)
    dom, _, _, _ = _read(dom_p)
    ids = _rasterize_wards(wards, shp, tr)
    scored = dom == 1
    aoi = np.isfinite(dom) & (dom != 255)
    pct = np.where(scored, pct, np.nan)
    t = pd.DataFrame({"ward_no": wards.ward_no.astype(int).values, "zone_no": wards.zone_no.astype(int).values, "area_km2": wards.area_km2.values})
    n_grid = pd.Series(ids.ravel()[ids.ravel() > 0]).value_counts()
    n_sc = pd.Series(ids[scored]).value_counts()
    t["grid_cells"] = t.ward_no.map(n_grid).fillna(0).astype(int)
    t["assessed_share"] = (t.ward_no.map(n_sc).fillna(0) / t.grid_cells.replace(0, np.nan)).values
    t["sus_a_mean_pct"] = _zonal(ids, pct, wards, "mean").values
    t["sus_a_share_top_decile"] = _zonal(ids, np.where(np.isfinite(pct), (pct >= 90).astype(float), np.nan), wards, "mean").values
    c, _, _, _ = _read(root / REVIEW / "index_C_reduced_no_twi.tif")
    cp = _midrank_percentile(np.where(scored, c, np.nan))
    t["sus_c_mean_pct"] = _zonal(ids, cp, wards, "mean").values
    for b, name in enumerate(INDICATORS, start=1):
        a, _, _, _ = _read(root / SUS1 / "feature_stack_raw.tif", b)
        a = np.where(scored, a, np.nan)
        if name == "flow_accumulation":
            t["p90_log10_flow_acc"] = _zonal(ids, np.log10(np.clip(a, 1, None)), wards, lambda s: s.quantile(0.9)).values
        else:
            t[f"med_{name}"] = _zonal(ids, a, wards, "median").values
    cnt, _, _, _ = _read(root / S1WC2 / "s1_water_candidates_v2_class1_candidate_date_count.tif")
    cnt = np.where(aoi, cnt, np.nan)
    t["s1_class1_any_share"] = _zonal(ids, np.where(np.isfinite(cnt), (cnt >= 1).astype(float), np.nan), wards, "mean").values
    t["s1_class1_mean_dates"] = _zonal(ids, cnt, wards, "mean").values
    c8, _, _, _ = _read(root / S1WC2 / "s1_water_candidates_v2_class8_signature_candidate_date_count.tif")
    c8 = np.where(aoi, c8, np.nan)
    t["s1_class8_any_share"] = _zonal(ids, np.where(np.isfinite(c8), (c8 >= 1).astype(float), np.nan), wards, "mean").values
    # CHIRPS: one native 0.05 deg value at each ward centroid (context only - no sub-5 km information)
    ch_p = root / "data/processed/rainfall_chirps_2021/chirps_2021/2021_sep_nov_event_total_mm_native.tif"
    if ch_p.is_file():
        import rasterio
        with rasterio.open(ch_p) as d:
            cen = wards.geometry.representative_point().to_crs(d.crs)
            vals = np.array([v[0] for v in d.sample(list(zip(cen.x, cen.y)))], dtype=float)
            vals[vals == d.nodata] = np.nan
        t["chirps_2021_event_mm_coarse"] = vals
        prov["notes"].append(f"CHIRPS 2021: {pd.Series(vals).nunique()} distinct native-cell values over {len(vals)} wards (coarse context only)")
    # DEP2 local run tables
    e = pd.read_csv(dep2_dir / "B_exposure/exposure_indicators_by_ward.csv")
    v = pd.read_csv(dep2_dir / "C_vulnerability/vulnerability_indicators_components_by_ward.csv")
    r = pd.read_csv(dep2_dir / "A_evidence_reference/ward_reported_inundation_counts.csv")
    e = e.assign(pop_density_cdmp=e.population_density_cdmp_per_km2, facilities_per_km2=e.critical_facilities_per_km2,
                 wp_pop_density_2020=e.wp_population_2020 / e.area_km2)
    t = t.merge(e[["ward_no", "population_cdmp", "pop_density_cdmp", "road_surface_share", "facilities_per_km2", "wp_pop_density_2020",
                   "exposure_index_provisional"]], on="ward_no", how="left")
    t = t.merge(v[["ward_no", "slum_area_share", "dist_public_health_km", "relief_capacity_per_1000", "component_housing_built_environment",
                   "component_adaptive_capacity", "vulnerability_index_provisional"]], on="ward_no", how="left")
    rc = r[["ward_no", "cdmp_records_2015", "cdmp_records_2021", "cdmp_years_listed", "osmin_streets_2015_dec2"]]
    t = t.merge(rc, on="ward_no", how="left")
    for yr in (2015, 2021):
        t[f"reported_{yr}"] = np.where(t[f"cdmp_records_{yr}"] > 0, 1.0, np.nan)   # presence = 1; unreported = NaN (UNLABELLED, never 0)
    prov["inputs"] = {"sus1_percentile": pct_p.relative_to(root).as_posix(), "sus1_domain": dom_p.relative_to(root).as_posix(),
                      "dep2_dir": dep2_dir.relative_to(root).as_posix() if dep2_dir.is_relative_to(root) else dep2_dir.as_posix()}
    prov["n_wards"] = int(len(t))
    prov["wards_fully_outside_grid"] = int((t.grid_cells == 0).sum())
    return t, prov
