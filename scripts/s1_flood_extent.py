#!/usr/bin/env python
"""Module S1B (V2) - Sentinel-1 flood extent for ONE event at a time (default: first PROCESSABLE event from S1A).
Outputs a SAR-derived PROXY label: raster (master grid), GeoJSON polygons, PNG, metadata JSON.
It is UNVALIDATED until compared with independent reference products (scripts/compare_reference.py).
Usage:  python scripts/s1_flood_extent.py [--event 2021_nov] [--local]
  --local : use user-supplied pre/post dB GeoTIFFs in data/external/sentinel1/<event>_pre.tif/_post.tif instead of Earth Engine"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from rasterio.warp import Resampling
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.study_area import load_study_area, master_grid
from src.flood_detection import export as ex
from src.visualization import plots

OUT = paths.DATA_PROC / "s1"


def plus1(d):
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="")
    ap.add_argument("--local", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    log = get_logger("S1B_flood")
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((paths.CONFIG / "s1_events.json").read_text(encoding="utf-8"))
    P = cfg["params"]
    events = {e["id"]: e for e in cfg["events"]}
    pairing = {}
    pf = paths.OUT_TAB / "s1_pairing.json"
    if pf.exists():
        pairing = json.loads(pf.read_text(encoding="utf-8"))
    ev_id = a.event or next((k for k, v in pairing.items() if v.get("verdict") == "PROCESSABLE"), "")
    if not ev_id or ev_id not in events:
        status.record("S1B", status.BLOCKED, "No event selected: run scripts/s1_availability.py first (needs a PROCESSABLE event) "
                      "or pass --event <id>.", requirements=["python scripts/s1_availability.py"], seconds=time.time() - t0)
        return
    ev = events[ev_id]
    pr = pairing.get(ev_id, {})
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    inside = G.inside_mask(grid, sa_utm.geometry)
    meta = {"event": ev_id, "name": ev["name"], "params": P, "label_status": "SAR PROXY - UNVALIDATED",
            "pairing_verdict": pr.get("verdict", "unknown (no availability run)"), "pairing": pr}
    flood = None
    if a.local:
        pre_f, post_f = paths.DATA_EXT / "sentinel1" / f"{ev_id}_pre.tif", paths.DATA_EXT / "sentinel1" / f"{ev_id}_post.tif"
        if not (pre_f.exists() and post_f.exists()):
            status.record("S1B", status.BLOCKED, f"--local needs {pre_f.name} and {post_f.name} in data/external/sentinel1/",
                          seconds=time.time() - t0)
            return
        from src.flood_detection.change_detection import detect_flood_change
        def load(f):
            with rasterio.open(f) as ds:
                return G.to_grid(ds.read(1).astype("float32"), ds.transform, ds.crs, grid, Resampling.bilinear,
                                 src_nodata=ds.nodata, dst_nodata=np.nan)
        slope = None
        sp = paths.DATA_PROC / "slope_deg_utm44n_30m.tif"
        if sp.exists():
            s, nd, _, _ = G.read_raster(sp)
            slope = np.where(s == nd, 0, s)
        flood = detect_flood_change(load(pre_f), load(post_f), P["diff_threshold_db"], P["post_max_db"], slope, P["max_slope_deg"])
        meta["backend"] = "local user-supplied backscatter (dB)"
    else:
        try:
            from src.flood_detection import gee_sentinel1 as g1, gee_s1_flood as g2
            import ee
            g1.init_ee(load_settings()["gee"].get("project") or None)
            from shapely.geometry import mapping
            u = sa_wgs.geometry.union_all() if hasattr(sa_wgs.geometry, "union_all") else sa_wgs.geometry.unary_union
            geom = ee.Geometry(mapping(u), proj="EPSG:4326", geodesic=False)
            orb = pr.get("orbit")
            if not orb:
                raise RuntimeError("no orbit pairing for this event - run s1_availability.py or choose another event")
            pre = (ev["pre"][0], plus1(ev["pre"][1]))
            post = (ev["post"][0], plus1(ev["post"][1]))
            fimg, dimg, pre_c, post_c = g2.build_flood_image(geom, pre, post, orb["direction"], orb["rel_orbit"], P)
            pre_ids, post_ids = g2.scene_ids(pre_c), g2.scene_ids(post_c)
            meta["gee_scene_ids"] = {"pre": pre_ids, "post": post_ids}
            if not pre_ids or not post_ids:
                raise RuntimeError(f"Earth Engine has {len(pre_ids)} pre / {len(post_ids)} post scenes for this orbit "
                                   "(catalogue says otherwise -> ingestion gap); cannot process")
            raw = paths.DATA_RAW / f"s1_flood_{ev_id}_gee_{grid.res:.0f}m.tif"
            if not raw.exists():
                g1.download_geotiff(ee, fimg, geom, raw, load_settings()["analysis_epsg"], grid.res)
            with rasterio.open(raw) as ds:
                flood = G.to_grid(ds.read(1).astype("float32"), ds.transform, ds.crs, grid, Resampling.nearest,
                                  src_nodata=ds.nodata, dst_nodata=255, dtype="uint8")
            meta["backend"] = f"Google Earth Engine COPERNICUS/S1_GRD, {orb['direction']} orbit {orb['rel_orbit']}"
        except Exception as e:
            msg = f"Sentinel-1 flood extent not produced for {ev_id}: {str(e)[:300]}"
            log.error(msg)
            status.record("S1B", status.BLOCKED, msg,
                          requirements=["One-time: .\\.venv\\Scripts\\earthengine authenticate and set gee.project in config/settings.json",
                                        "or use --local with your own pre/post Sentinel-1 backscatter files"], seconds=time.time() - t0)
            return
    flood = np.where(inside, flood, 255).astype("uint8")
    bu = sp_ = None
    lc = paths.DATA_PROC / "landcover_class_utm44n_30m.tif"
    if lc.exists():
        bu = G.read_raster(lc)[0]
    sl = paths.DATA_PROC / "slope_deg_utm44n_30m.tif"
    if sl.exists():
        s, nd, _, _ = G.read_raster(sl)
        sp_ = np.where(s == nd, np.nan, s)
    meta["descriptive_stats_NOT_ACCURACY"] = ex.summarise(flood, grid, inside, bu, sp_)
    rf = OUT / f"flood_{ev_id}_utm44n_30m.tif"
    G.write_raster(rf, flood, grid, 255, "flood_1_noflood_0", "uint8")
    gj = OUT / f"flood_{ev_id}.geojson"
    polys = ex.flood_polygons(flood, grid)
    polys.to_file(gj, driver="GeoJSON")
    png = paths.OUT_FIG / f"s1_flood_{ev_id}.png"
    plots.categorical_map(np.where(flood == 255, 0, flood + 1), grid, sa_utm,
                          {1: ("No flood detected", "#e8e8e8"), 2: ("Flood (SAR proxy)", "#0050c8")},
                          f"{ev['name']}\nSAR-derived PROXY - unvalidated", png)
    (OUT / f"flood_{ev_id}_metadata.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    status.record("S1B", status.PARTIAL, f"{ev_id}: flood proxy extent written ({meta['descriptive_stats_NOT_ACCURACY']['flooded_km2']} km2). "
                  "UNVALIDATED: compare with independent reference products before using as labels.",
                  files=[paths.rel(rf), paths.rel(gj), paths.rel(png), paths.rel(OUT / f"flood_{ev_id}_metadata.json")],
                  datasets=[{"name": f"Sentinel-1 flood extent {ev_id}", "kind": "DERIVED (SAR proxy, unvalidated)",
                             "source": meta["backend"], "path": paths.rel(rf)}],
                  requirements=["Validate against independent reference (ALOS-2 / RISAT-1A / EOS-04 products, citizen data)."],
                  extra=meta, seconds=time.time() - t0)


if __name__ == "__main__":
    main()
