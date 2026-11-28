"""Reference-evidence preparation and event-specific, uncertainty-aware comparisons.

Rules enforced here (from the project control file):
* E3 reported locations are presences only; absence of a report is NOT absence of flooding;
  no negative labels, no precision/recall/accuracy/IoU.
* 2015 evidence is compared only with 2015 evidence; 2021 only with 2021.
* Sentinel-1 bright-VV components are E4 exploratory diagnostics, not floodwater.
* Every comparison is reported against a spatial null model so that a "match" is not read
  as agreement when it would also arise from the urban street layout alone.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import ANALYSIS_CRS, GEO_CRS, LOG, write_json

# master grid derived from the S1 component tables (verified exactly on 33,543 single-cell components)
GRID_X0, GRID_Y0, GRID_RES, GRID_W, GRID_H = 406020.0, 1463310.0, 30.0, 726, 1416


def grid_extent_polygon():
    from shapely.geometry import box
    return box(GRID_X0, GRID_Y0 - GRID_H * GRID_RES, GRID_X0 + GRID_W * GRID_RES, GRID_Y0)


def verify_grid_origin(components: pd.DataFrame) -> dict:
    r = components.bbox_rows.astype(str).str.split("-", expand=True).astype(int)
    c = components.bbox_cols.astype(str).str.split("-", expand=True).astype(int)
    one = components.cells == 1
    x0 = components.centroid_x - GRID_RES * (c[0] + c[1]) / 2 - GRID_RES / 2
    y0 = components.centroid_y + GRID_RES * (r[0] + r[1]) / 2 + GRID_RES / 2
    ok = bool(np.allclose(x0[one], GRID_X0) and np.allclose(y0[one], GRID_Y0))
    return {"single_cell_components_checked": int(one.sum()), "x0": GRID_X0, "y0": GRID_Y0, "res_m": GRID_RES,
            "width": GRID_W, "height": GRID_H, "origin_reproduced_exactly": ok,
            "max_row": int(r.max().max()), "max_col": int(c.max().max())}


def load_s1_components(path: Path):
    """S1PE bright-VV components (EXPLORATORY diagnostic; +5 dB primary threshold) as circles of equal area."""
    import geopandas as gpd
    d = pd.read_csv(path)
    d["radius_m"] = np.sqrt(d.area_km2 * 1e6 / np.pi)
    g = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d.centroid_x, d.centroid_y), crs=ANALYSIS_CRS)
    g["set"] = np.where(d["class"].str.startswith("bright on"), d["class"].str.slice(10, 20), d["class"])
    return g


def _nearest_edge_distance(points, comps):
    """Distance from each point to the nearest component EDGE (centroid distance minus equal-area radius, floored at 0)."""
    from scipy.spatial import cKDTree
    if len(comps) == 0 or len(points) == 0:
        return np.full(len(points), np.nan)
    xy = np.c_[comps.geometry.x, comps.geometry.y]
    tree = cKDTree(xy)
    k = min(8, len(comps))
    d, i = tree.query(np.c_[points.geometry.x, points.geometry.y], k=k)
    d, i = np.atleast_2d(d), np.atleast_2d(i)
    if k == 1:
        d, i = d.T, i.T
    edge = np.clip(d - comps.radius_m.values[i], 0, None)
    return edge.min(axis=1)


_NULL_CACHE: dict = {}


def null_pool(road_polys, region):
    """Candidate null locations: one representative point per TNGIS road polygon inside `region` (cached)."""
    key = (id(road_polys), region.wkb)
    if key not in _NULL_CACHE:
        pts = road_polys.representative_point()
        _NULL_CACHE[key] = pts[pts.within(region)].reset_index(drop=True)
    return _NULL_CACHE[key]


def null_points(road_polys, region, n, rng):
    """Random points on the street fabric (TNGIS road polygons) inside `region`: the null model for street-placed reports."""
    import geopandas as gpd
    pts = null_pool(road_polys, region)
    if len(pts) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=ANALYSIS_CRS)
    idx = rng.choice(len(pts), size=n, replace=True)
    return gpd.GeoDataFrame(geometry=pts.iloc[idx].values, crs=ANALYSIS_CRS)


def compare_reports_to_components(reports, comps_by_set: dict, roads, region, thresholds=(0, 100, 250), n_null=200, seed=20261128):
    """Presence-only association of reported locations with S1 component sets, with a street-fabric null model."""
    rng = np.random.default_rng(seed)
    rep = reports[reports.within(region)].copy()
    rows = []
    for name, comps in comps_by_set.items():
        d = _nearest_edge_distance(rep, comps)
        nulls = []
        for _ in range(n_null):
            q = null_points(roads, region, len(rep), rng)
            nulls.append(_nearest_edge_distance(q, comps))
        nulls = np.vstack(nulls) if nulls else np.empty((0, len(rep)))
        for t in thresholds:
            obs = float(np.mean(d <= t)) if len(d) else np.nan
            nd = (nulls <= t).mean(axis=1) if nulls.size else np.array([np.nan])
            rows.append({"component_set": name, "n_components": len(comps), "n_reports_in_grid": len(rep), "distance_threshold_m": t,
                         "share_reports_within": obs, "null_mean_share": float(np.mean(nd)), "null_p05": float(np.percentile(nd, 5)),
                         "null_p95": float(np.percentile(nd, 95)), "ratio_to_null": float(obs / np.mean(nd)) if np.mean(nd) > 0 else np.nan,
                         "share_null_draws_ge_observed": float(np.mean(nd >= obs)),
                         "median_edge_distance_m": float(np.median(d)) if len(d) else np.nan,
                         "null_median_edge_distance_m": float(np.median(nulls)) if nulls.size else np.nan})
    return pd.DataFrame(rows)


def compare_report_sets(a, b, roads, region, buffers=(50, 100, 250), n_null=200, seed=20261128, label_a="A", label_b="B"):
    """Share of A-locations within d m of any B-geometry, against the street-fabric null model (same event only)."""
    import geopandas as gpd
    rng = np.random.default_rng(seed)
    a = a[a.within(region)]
    tree_geoms = np.asarray([g if g.is_valid else g.buffer(0) for g in b.geometry if g is not None and not g.is_empty])
    rows = []
    da = dist_to_set(a.geometry, tree_geoms)
    for t in buffers:
        nd = []
        for _ in range(n_null):
            q = null_points(roads, region, len(a), rng)
            nd.append(float(np.mean(dist_to_set(q.geometry, tree_geoms) <= t)))
        nd = np.array(nd)
        obs = float(np.mean(da <= t))
        rows.append({"set_a": label_a, "set_b": label_b, "n_a_in_region": len(a), "buffer_m": t, "share_a_within_b": obs,
                     "null_mean_share": float(nd.mean()), "null_p05": float(np.percentile(nd, 5)), "null_p95": float(np.percentile(nd, 95)),
                     "ratio_to_null": float(obs / nd.mean()) if nd.mean() > 0 else np.nan, "share_null_draws_ge_observed": float(np.mean(nd >= obs))})
    return pd.DataFrame(rows)


def dist_to_set(points, geoms):
    """Exact distance from each point to the nearest geometry of a set (STRtree; no union, so invalid inputs cannot break it)."""
    import shapely
    tree = shapely.STRtree(geoms)
    idx, dist = tree.query_nearest(np.asarray(points.values if hasattr(points, "values") else points), return_distance=True, all_matches=False)
    out = np.full(len(points), np.nan)
    out[idx[0]] = dist
    return out


def reference_points(gdf_located, year: int):
    """One representative point per placed record of `year` (EPSG:4326) for the R0-R2 checker."""
    g = gdf_located[(gdf_located.year == year) & gdf_located.placed].copy()
    g["geometry"] = g.geometry.representative_point()
    keep = ["row_id", "year", "zone", "ward", "location", "depth_class_verified", "depth_verification", "placement_precision",
            "position_uncertainty_m", "evidence_class"]
    return g[keep + ["geometry"]].to_crs(GEO_CRS)


def checker_sidecar(ref_id, name, producer, source, obtained_on, licence, licence_ok, kind, d0, d1, independent, method_doc,
                    pos_acc, class_meaning, method_summary, sensor="none (administrative / crowd-sourced report)", extra=None):
    m = {"reference_id": ref_id, "name": name, "producer": producer, "source": source, "obtained_on": obtained_on, "licence": licence,
         "licence_permits_derived_stats": licence_ok, "kind": kind, "obs_date_start": d0, "obs_date_end": d1, "obs_time_of_day": None,
         "sensor_family": sensor, "independent_of_s1": independent, "production_method_documented": method_doc, "method_summary": method_summary,
         "positional_accuracy_m": pos_acc, "class_meaning": class_meaning, "declared_crs": GEO_CRS, "x_column": None, "y_column": None}
    if extra:
        m["_provenance_notes"] = extra
    return m


def run_checker_harness(harness_root: Path, ref_path: Path, meta_path: Path, outdir: Path, today: str) -> int:
    """Run the project's UNMODIFIED reference_integration_check.py inside a harness checkout (see README)."""
    import importlib
    import sys
    sys.path.insert(0, str(harness_root))
    for m in [k for k in sys.modules if k == "src" or k.startswith("src.") or k == "reference_integration_check"]:
        del sys.modules[m]
    spec = importlib.util.spec_from_file_location("reference_integration_check", harness_root / "scripts/reference_integration_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.main(["--reference", str(ref_path), "--meta", str(meta_path), "--outdir", str(outdir), "--today", today])
    sys.path.remove(str(harness_root))
    LOG.info("checker %s -> rc=%s", ref_path.name, rc)
    return rc
