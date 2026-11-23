#!/usr/bin/env python
"""Module F - historical flood inventory foundation.
Creates the event inventory table, and produces flood extents ONLY from real Sentinel-1 data:
  (a) user-supplied pre/post backscatter GeoTIFFs in data/external/sentinel1/<event>_pre.tif / _post.tif (dB, VV), or
  (b) Google Earth Engine (needs one-time authentication).
No flood labels are ever fabricated. Extents are SAR-derived PROXY labels, not verified ground truth."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.study_area import load_study_area, master_grid
from src.flood_detection.change_detection import detect_flood_change
from src.visualization import plots


def local_detection(ev, grid, sa_utm, p, log):
    pre_f = paths.DATA_EXT / "sentinel1" / f"{ev['id']}_pre.tif"
    post_f = paths.DATA_EXT / "sentinel1" / f"{ev['id']}_post.tif"
    if not (pre_f.exists() and post_f.exists()):
        return None
    def load(f):
        with rasterio.open(f) as ds:
            return G.to_grid(ds.read(1).astype("float32"), ds.transform, ds.crs, grid, Resampling.bilinear,
                             src_nodata=ds.nodata, dst_nodata=np.nan)
    pre, post = load(pre_f), load(post_f)
    slope = None
    sp = paths.DATA_PROC / "slope_deg_utm44n_30m.tif"
    if sp.exists():
        s, nd, _, _ = G.read_raster(sp)
        slope = np.where(s == nd, 0, s)
    out = detect_flood_change(pre, post, p["diff_threshold_db"], p["post_max_db"], slope, p["max_slope_deg"])
    log.info("local change detection for %s: %d flood cells", ev["id"], int((out == 1).sum()))
    return out


def main():
    t0 = time.time()
    log = get_logger("F_inventory")
    cfg = load_settings()
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    fp = cfg["flood_detection"]
    rows, files, made, notes = [], [], [], []
    ee = None
    gee_msg = "not attempted"
    try:
        from src.flood_detection import gee_sentinel1 as gs
        ee = gs.init_ee(cfg["gee"].get("project") or None)
        gee_msg = "initialised"
    except Exception as e:
        gee_msg = f"not available: {str(e)[:160]}"
    log.info("Google Earth Engine: %s", gee_msg)

    from shapely.geometry import mapping
    geom = None
    if ee is not None:
        union = sa_wgs.geometry.union_all() if hasattr(sa_wgs.geometry, "union_all") else sa_wgs.geometry.unary_union
        geom = ee.Geometry(mapping(union), proj="EPSG:4326", geodesic=False)

    for ev in cfg["flood_events"]:
        row = {"event_id": ev["id"], "name": ev["name"], "approx_period_unverified": ev["approx_period"],
               "s1_pre_window_proposed": " to ".join(ev["s1_pre"]), "s1_post_window_proposed": " to ".join(ev["s1_post"]),
               "s1_images_pre": "unknown", "s1_images_post": "unknown", "flood_extent_file": "", "label_status": "NOT AVAILABLE"}
        out = local_detection(ev, grid, sa_utm, fp, log)
        src_note = "user-supplied Sentinel-1 backscatter (local change detection)"
        if out is None and ee is not None:
            try:
                c_pre = gs.count_images(ee, geom, *ev["s1_pre"])
                c_post = gs.count_images(ee, geom, *ev["s1_post"])
                row["s1_images_pre"], row["s1_images_post"] = str(c_pre), str(c_post)
                passes = [k for k in ("DESCENDING", "ASCENDING") if c_pre[k] > 0 and c_post[k] > 0]
                if not passes:
                    notes.append(f"{ev['id']}: no orbit pass has Sentinel-1 images in BOTH windows - adjust windows")
                else:
                    img = gs.flood_image(ee, geom, ev["s1_pre"], ev["s1_post"], passes[0], fp)
                    tmp = paths.DATA_RAW / f"s1_flood_{ev['id']}_gee_30m.tif"
                    if not tmp.exists():
                        gs.download_geotiff(ee, img, geom, tmp, cfg["analysis_epsg"], grid.res)
                    with rasterio.open(tmp) as ds:
                        arr = G.to_grid(ds.read(1).astype("float32"), ds.transform, ds.crs, grid, Resampling.nearest,
                                        src_nodata=ds.nodata, dst_nodata=255, dtype="uint8")
                    out = arr
                    src_note = f"Google Earth Engine Sentinel-1 ({passes[0]} pass)"
            except Exception as e:
                notes.append(f"{ev['id']}: GEE step failed: {str(e)[:200]}")
                log.warning(notes[-1])
        if out is not None:
            inside = G.inside_mask(grid, sa_utm.geometry)
            out = np.where(inside, out, 255).astype("uint8")
            f = paths.DATA_PROC / f"flood_extent_{ev['id']}_utm44n_30m.tif"
            G.write_raster(f, out, grid, 255, "flood_1_noflood_0", "uint8")
            plots.categorical_map(np.where(out == 255, 0, out + 1), grid, sa_utm,
                                  {1: ("No flood detected", "#e8e8e8"), 2: ("Flood (SAR proxy)", "#0050c8")},
                                  f"{ev['name']}: SAR-derived flood extent\n{src_note}\nPROXY label - not verified ground truth",
                                  paths.OUT_FIG / f"flood_extent_{ev['id']}.png")
            row.update(flood_extent_file=paths.rel(f), label_status="SAR PROXY (unverified)")
            files += [paths.rel(f), f"outputs/figures/flood_extent_{ev['id']}.png"]
            made.append(ev["id"])
        rows.append(row)
    pd.DataFrame(rows).to_csv(paths.OUT_TAB / "flood_event_inventory.csv", index=False)
    files.append("outputs/tables/flood_event_inventory.csv")

    # user-supplied verified labels (e.g. Copernicus EMS / field-verified) are noted for module G
    ext_labels = sorted((paths.DATA_EXT / "flood_labels").glob("*.tif*"))
    if made or ext_labels:
        state = status.PARTIAL if len(made) < len(cfg["flood_events"]) and not ext_labels else status.COMPLETED
        msg = f"Flood extents for: {', '.join(made) or 'none'}; user-supplied label rasters: {len(ext_labels)}. SAR extents are PROXY labels."
    else:
        state = status.PARTIAL
        msg = ("Inventory table created (events + proposed Sentinel-1 windows). NO flood extents yet: "
               f"Google Earth Engine {gee_msg}; no user-supplied Sentinel-1 files found.")
    if notes:
        msg += " Notes: " + " | ".join(notes)
    reqs = []
    if not made and not ext_labels:
        reqs = ["One-time GEE auth: .\\.venv\\Scripts\\earthengine authenticate  (then put your Cloud project id in "
                "config/settings.json -> gee.project and re-run).",
                "OR place pre/post Sentinel-1 VV backscatter (dB) GeoTIFFs in data/external/sentinel1/ named "
                "<event_id>_pre.tif / <event_id>_post.tif.",
                "OR place verified flood/non-flood rasters (1/0) in data/external/flood_labels/.",
                "Verify event dates and Sentinel-1 availability (2015 coverage may be sparse)."]
    status.record("F", state, msg, files=files, datasets=[
        {"name": "Flood event inventory (metadata only)", "kind": "REFERENCE (unverified dates)", "source": "config/settings.json",
         "path": "outputs/tables/flood_event_inventory.csv"}] +
        [{"name": f"Flood extent {e}", "kind": "DERIVED (SAR proxy)", "source": "Sentinel-1", "path": f"data/processed/flood_extent_{e}_utm44n_30m.tif"} for e in made],
        requirements=reqs, extra={"gee": gee_msg, "events_with_extent": made}, seconds=time.time() - t0)


if __name__ == "__main__":
    main()
