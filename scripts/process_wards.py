#!/usr/bin/env python
"""Module A2 - ward boundary acquisition, validation, statistics and maps."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.data_acquisition.wards import acquire_wards
from src.geospatial.vector_io import read_vector
from src.geospatial.study_area import load_study_area
from src.visualization import maps
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ID_CANDS = ["ward_no", "wardno", "ward_num", "ward_id", "wardid", "ward", "no", "id", "objectid"]
NAME_CANDS = ["ward_name", "wardname", "name", "ward_nam", "area_name", "locality"]


def pick(cols, cands):
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c in low:
            return low[c]
    return None


def main():
    t0 = time.time()
    log = get_logger("A2_wards")
    cfg = load_settings()
    path, prov = acquire_wards(cfg, log)
    if path is None:
        msg = "Ward boundaries not obtained: " + prov["error"]
        log.error(msg)
        status.record("A2", status.BLOCKED, msg,
                      requirements=["Put a ward boundary file (GeoJSON/Shapefile/GPKG/ZIP) in data/external/wards/ "
                                    "and re-run. Check source licence and vintage (GCC is commonly cited as 200 wards; "
                                    "older files may have 155).",
                                    "Or re-run with internet access so the DataMeet download can be attempted."],
                      seconds=time.time() - t0)
        return
    gdf = read_vector(path)
    notes = []
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
        notes.append("input had no CRS; assumed EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    n_invalid = int((~gdf.geometry.is_valid).sum())
    if n_invalid:
        gdf["geometry"] = gdf.geometry.buffer(0)
        notes.append(f"{n_invalid} invalid geometries repaired with buffer(0)")
    gdf = gdf.to_crs(4326)
    utm = gdf.to_crs(cfg["analysis_epsg"])
    idc, namec = pick(gdf.columns, ID_CANDS), pick(gdf.columns, NAME_CANDS)
    gdf["ward_uid"] = np.arange(1, len(gdf) + 1)
    gdf["ward_id"] = gdf[idc].astype(str) if idc else gdf["ward_uid"].astype(str)
    gdf["ward_name"] = gdf[namec].astype(str) if namec else ""
    gdf["area_km2"] = (utm.geometry.area / 1e6).round(4).values
    utm = utm.assign(ward_uid=gdf["ward_uid"].values, ward_id=gdf["ward_id"].values,
                     ward_name=gdf["ward_name"].values, area_km2=gdf["area_km2"].values)
    gdf.to_file(paths.DATA_PROC / "wards_wgs84.geojson", driver="GeoJSON")
    utm.to_file(paths.DATA_PROC / "wards_utm44n.geojson", driver="GeoJSON")

    table = pd.DataFrame(gdf.drop(columns="geometry"))
    table.to_csv(paths.OUT_TAB / "ward_statistics.csv", index=False)
    a = gdf["area_km2"]
    unnumbered = []
    if idc:
        num = pd.to_numeric(gdf[idc], errors="coerce")
        bad = gdf[(num.fillna(0) == 0)]
        unnumbered = [{"row": int(i), "area_km2": float(r["area_km2"]), "attrs": {k: str(v) for k, v in r.drop("geometry").items()
                       if k not in ("ward_uid", "ward_id", "ward_name", "area_km2")}} for i, r in bad.iterrows()]
        if unnumbered:
            notes.append(f"{len(unnumbered)} polygon(s) without a ward number (id 0/empty) kept in the data but flagged; "
                         f"{len(gdf) - len(unnumbered)} numbered wards")
    summary = {"ward_count": int(len(gdf)), "numbered_ward_count": int(len(gdf) - len(unnumbered)),
               "unnumbered_polygons": unnumbered, "total_area_km2": round(float(a.sum()), 2),
               "area_km2_min": round(float(a.min()), 3), "area_km2_median": round(float(a.median()), 3),
               "area_km2_mean": round(float(a.mean()), 3), "area_km2_max": round(float(a.max()), 3),
               "id_column": idc, "name_column": namec, "duplicate_ids": int(gdf["ward_id"].duplicated().sum()),
               "source": prov.get("source"), "provenance": prov.get("kind"), "notes": notes,
               "attribute_columns": [c for c in table.columns]}
    try:
        sa_wgs, sa_utm, _ = load_study_area()
        sa = sa_utm.geometry.union_all() if hasattr(sa_utm.geometry, "union_all") else sa_utm.geometry.unary_union
        wu = utm.geometry.union_all() if hasattr(utm.geometry, "union_all") else utm.geometry.unary_union
        inter = sa.intersection(wu).area
        summary["share_of_study_area_covered_by_wards_pct"] = round(100 * inter / sa.area, 1)
        summary["share_of_ward_area_inside_study_area_pct"] = round(100 * inter / wu.area, 1)
    except Exception as e:
        notes.append(f"study-area comparison skipped: {e}")
    (paths.DATA_PROC / "wards_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("wards: %s", summary)

    fig, ax = plt.subplots(figsize=(7, 7.5))
    utm.plot(ax=ax, column="area_km2", cmap="YlOrRd", edgecolor="grey", linewidth=0.3, legend=True,
             legend_kwds={"label": "Ward area (km2)", "shrink": 0.7})
    try:
        sa_utm.boundary.plot(ax=ax, color="black", linewidth=1.2)
    except Exception:
        pass
    ax.set_title(f"Ward boundaries (n={len(gdf)}; {prov.get('kind')})")
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    f1 = paths.OUT_FIG / "wards_map.png"
    fig.savefig(f1, dpi=200)
    plt.close(fig)
    f2 = paths.OUT_MAPS / "wards.html"
    maps.boundary_map(sa_wgs, f2, f"Wards ({len(gdf)})", wards_wgs84=gdf, ward_fields=["ward_id", "ward_name", "area_km2"])

    state = status.COMPLETED if prov.get("kind") in ("REAL", status.USER) else status.PARTIAL
    msg = f"{len(gdf)} wards, {summary['total_area_km2']} km2 total. Source: {prov.get('source')}. " \
          f"Vintage/licence NOT verified. " + "; ".join(notes)
    status.record("A2", state, msg, files=[paths.rel(f1), paths.rel(f2), "outputs/tables/ward_statistics.csv",
                                            "data/processed/wards_wgs84.geojson", "data/processed/wards_utm44n.geojson"],
                  datasets=[{"name": "Chennai ward boundaries", "kind": prov.get("kind"), "source": prov.get("source"),
                             "path": "data/processed/wards_wgs84.geojson"}],
                  requirements=["Confirm ward count/vintage against the official GCC list."], extra=summary,
                  seconds=time.time() - t0)


if __name__ == "__main__":
    main()
