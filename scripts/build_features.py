#!/usr/bin/env python
"""Module E - align layers on the master grid, build feature stack + table + data-quality report."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rfeatures
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.study_area import load_study_area, master_grid

LAYERS = [  # (feature name, file, nodata)
    ("elevation_m", "dem_elevation_utm44n_30m.tif", -9999.0),
    ("slope_deg", "slope_deg_utm44n_30m.tif", -9999.0),
    ("landcover_class", "landcover_class_utm44n_30m.tif", 255),
    ("builtup_fraction", "builtup_fraction_utm44n_30m.tif", -9999.0),
    ("rain_event_total_mm", "rainfall_event_total_mm_utm44n_30m.tif", -9999.0),
]
MISSING = {
    "flow_accumulation": "needs hydrologically conditioned DEM (e.g. pysheds/WhiteboxTools) - planned next",
    "twi": "derived from flow accumulation + slope - planned next",
    "distance_to_drainage": "needs OSM waterways/drains via Overpass - planned next",
    "drainage_density": "needs OSM waterways - planned next",
    "distance_to_roads": "needs OSM roads - planned next",
    "population": "needs WorldPop/Census ward population - not yet acquired",
    "relief_shelters": "needs shelter locations (OSM / GCC list) - not yet acquired",
    "flood_labels": "needs Sentinel-1 flood extents (Module F, requires Google Earth Engine authentication)",
}


def main():
    t0 = time.time()
    log = get_logger("E_features")
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    inside = G.inside_mask(grid, sa_utm.geometry)
    bands, names, qa = [], [], []
    for name, fn, nd in LAYERS:
        p = paths.DATA_PROC / fn
        if not p.exists():
            qa.append({"feature": name, "present": False, "reason": f"{fn} not found (upstream module missing/blocked)"})
            continue
        with rasterio.open(p) as ds:
            same = (ds.crs.to_string() == grid.crs and ds.transform.almost_equals(grid.transform)
                    and (ds.height, ds.width) == grid.shape)
            arr = ds.read(1).astype("float32")
            res = ds.res
        if not same:  # V2 fix: never stack a layer that is not on the master grid (stale file from an older boundary)
            qa.append({"feature": name, "present": False, "reason": f"{fn} is NOT aligned with the current master grid "
                       "(re-run the module that produces it after changing the boundary)"})
            continue
        arr = np.where(arr == nd, np.nan, arr)
        v = arr[inside]
        qa.append({"feature": name, "present": True, "aligned_with_master_grid": bool(same), "resolution_m": res[0],
                   "valid_pct_inside_study_area": round(100 * np.isfinite(v).mean(), 2),
                   "min": float(np.nanmin(v)) if np.isfinite(v).any() else None,
                   "max": float(np.nanmax(v)) if np.isfinite(v).any() else None,
                   "std": float(np.nanstd(v)) if np.isfinite(v).any() else None})
        bands.append(arr)
        names.append(name)
    if not names:
        status.record("E", status.BLOCKED, "No feature layers exist yet (DEM, land cover and rainfall all missing).",
                      requirements=["Resolve Modules B, C and D first."], seconds=time.time() - t0)
        return
    stack = np.stack(bands).astype("float32")
    stack_path = paths.DATA_PROC / "feature_stack_utm44n_30m.tif"
    with rasterio.open(stack_path, "w", driver="GTiff", height=grid.height, width=grid.width, count=len(names),
                       dtype="float32", crs=grid.crs, transform=grid.transform, nodata=np.nan, compress="deflate") as d:
        for i, n in enumerate(names, 1):
            d.write(stack[i - 1], i)
            d.set_band_description(i, n)
    (paths.DATA_PROC / "feature_names.json").write_text(json.dumps(names))

    ii, jj = np.where(inside & np.isfinite(stack).all(axis=0))
    rng = np.random.default_rng(42)
    take = rng.choice(len(ii), size=min(20000, len(ii)), replace=False) if len(ii) else np.array([], dtype=int)
    xs, ys = rasterio.transform.xy(grid.transform, ii[take], jj[take])
    tab = pd.DataFrame({"x_utm": np.round(xs, 1), "y_utm": np.round(ys, 1)})
    for k, n in enumerate(names):
        tab[n] = stack[k][ii[take], jj[take]]
    tab.to_csv(paths.OUT_TAB / "feature_table_sample.csv", index=False)

    ward_file = paths.DATA_PROC / "wards_utm44n.geojson"
    ward_out = None
    if ward_file.exists():
        import geopandas as gpd
        w = gpd.read_file(ward_file)
        shapes = [(g, int(u)) for g, u in zip(w.geometry, w["ward_uid"])]
        wid = rfeatures.rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=0, dtype="int32")
        rows = []
        for u, wi, nm in zip(w["ward_uid"], w["ward_id"], w["ward_name"]):
            m = wid == int(u)
            row = {"ward_uid": int(u), "ward_id": wi, "ward_name": nm, "cells": int(m.sum())}
            for k, n in enumerate(names):
                if n == "landcover_class":
                    row["builtup_class_pct"] = round(float(100 * np.nanmean(stack[k][m] == 50)), 2) if m.any() else None
                else:
                    row[n + "_mean"] = round(float(np.nanmean(stack[k][m])), 3) if m.any() and np.isfinite(stack[k][m]).any() else None
            rows.append(row)
        ward_out = paths.OUT_TAB / "ward_terrain_summary.csv"
        pd.DataFrame(rows).to_csv(ward_out, index=False)

    dq = {"grid": {"crs": grid.crs, "resolution_m": grid.res, "shape": list(grid.shape)},
          "features_present": names, "per_feature": qa, "missing_features": MISSING,
          "rows_in_complete_table": int(len(ii)), "rows_in_sample_csv": int(len(take))}
    (paths.OUT_REP / "data_quality_report.json").write_text(json.dumps(dq, indent=2, default=str), encoding="utf-8")
    md = ["# Data quality report", "", f"Grid: {grid.crs}, {grid.res} m, {grid.height} x {grid.width} cells", "",
          "| feature | present | aligned | valid % | min | max |", "|---|---|---|---|---|---|"]
    for q in qa:
        md.append(f"| {q['feature']} | {q['present']} | {q.get('aligned_with_master_grid', '-')} | "
                  f"{q.get('valid_pct_inside_study_area', '-')} | {q.get('min', '-')} | {q.get('max', '-')} |")
    md += ["", "## Missing features", ""] + [f"- **{k}**: {v}" for k, v in MISSING.items()]
    (paths.OUT_REP / "data_quality_report.md").write_text("\n".join(md), encoding="utf-8")

    absent = [q["feature"] for q in qa if not q["present"]]
    state = status.COMPLETED if not absent else status.PARTIAL
    status.record("E", state, f"Feature stack with {len(names)} layers ({', '.join(names)}). "
                  + (f"Absent: {', '.join(absent)}. " if absent else "") +
                  f"Still missing for the full design: {', '.join(k for k in MISSING if k != 'flood_labels')}.",
                  files=["data/processed/feature_stack_utm44n_30m.tif", "outputs/tables/feature_table_sample.csv",
                         "outputs/reports/data_quality_report.json", "outputs/reports/data_quality_report.md"]
                  + ([paths.rel(ward_out)] if ward_out else []),
                  datasets=[{"name": "Feature stack", "kind": status.DERIVED, "source": "Modules B, C, D",
                             "path": "data/processed/feature_stack_utm44n_30m.tif"}],
                  requirements=[f"{k}: {v}" for k, v in MISSING.items()], extra={"features": names},
                  seconds=time.time() - t0)


if __name__ == "__main__":
    main()
