#!/usr/bin/env python
"""Module S1B (V2.2) - Sentinel-1 flood-extent PROXY for a pinned event (default 2015_nov).

SAR-derived proxy, UNVALIDATED, not an accuracy claim. Scenes are pinned in config/s1_events.json and processing is
refused unless the live Earth Engine verification table (scripts/s1_gee_check.py) passes the gate for every scene.

Usage (PowerShell, project folder):
  .\\.venv\\Scripts\\python scripts\\s1b_flood_extent.py --event 2015_nov            # plan only, no Earth Engine work (safe)
  .\\.venv\\Scripts\\python scripts\\s1b_flood_extent.py --event 2015_nov --run      # tiled download + local processing + report
  .\\.venv\\Scripts\\python scripts\\s1b_flood_extent.py --event 2015_nov --mode drive   # Export.image.toDrive task (watch in Tasks tab)
  .\\.venv\\Scripts\\python scripts\\s1b_flood_extent.py --event 2015_nov --from-tif C:\\path\\export.tif   # process a Drive export
Options: --set diff_threshold_db=-2.5 (override a parameter; changes the run id)  --tile-px 512  --force (ignore cached tiles)"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.study_area import load_study_area, master_grid
from src.flood_detection import export as ex
from src.flood_detection import s1_gate, s1_params, s1_proxy, s1_report
from src.flood_detection.s1_params import NODATA

PROC_RES = 10.0


def write_outputs(stack10, grid, inside30, boundary_utm, meta, run_dir, params, event, scene_rows, mode_label):
    """Aggregate, write rasters/GeoJSON/PNGs/metadata/report. Pure local step (testable with synthetic stacks)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from src.visualization import plots
    f = int(round(grid.res / PROC_RES))
    run_dir.mkdir(parents=True, exist_ok=True)
    prod = s1_report.aggregate(stack10, f, params["flood_fraction_threshold"])
    stats = s1_report.compute_stats(stack10, prod, inside30, grid, f)
    files = []
    g10 = G.Grid(grid.crs, rasterio.Affine(PROC_RES, 0, grid.transform.c, 0, -PROC_RES, grid.transform.f),
                 grid.width * f, grid.height * f, PROC_RES)
    idx = {n: i for i, n in enumerate(s1_proxy.LAYERS)}
    fl10 = np.where(stack10[idx["valid"]] == 1, stack10[idx["flood_proxy"]], 255).astype("uint8")
    p = run_dir / "flood_proxy_10m.tif"; G.write_raster(p, fl10, g10, 255, "SAR flood proxy 10 m (1=proxy, 0=no, 255=no valid SAR) UNVALIDATED", "uint8"); files.append(p)
    p = run_dir / "flood_proxy_30m.tif"; G.write_raster(p, prod["flood_proxy_30m"], grid, 255, "SAR flood proxy 30 m master grid UNVALIDATED", "uint8"); files.append(p)
    for n in s1_report.CONTINUOUS:
        p = run_dir / f"{n}_30m.tif"; G.write_raster(p, prod[n], grid, NODATA, n, "float32"); files.append(p)
    for n in ("candidate", "mask_prev_dark", "mask_perm_water", "mask_steep", "mask_hand"):
        p = run_dir / f"{n}_frac_30m.tif"; G.write_raster(p, prod[n + "_frac"], grid, NODATA, n + " (fraction of valid 10 m pixels)", "float32"); files.append(p)
    p = run_dir / "valid_sar_30m.tif"; G.write_raster(p, prod["valid_30m"], grid, 255, "1 = enough valid SAR data", "uint8"); files.append(p)
    gdf = ex.flood_polygons(np.where(prod["flood_proxy_30m"] == 1, 1, 0).astype("uint8") * inside30, grid, min_cells=1)
    gdf["label"] = "SAR_PROXY_UNVALIDATED"
    gdf["event"] = event["id"]
    p = run_dir / "flood_proxy_30m.geojson"; gdf.to_file(p, driver="GeoJSON"); files.append(p)
    stats["flood_proxy_polygons"] = int(len(gdf))

    rid, ev = meta["run_id"], event["id"]
    maps = []
    def save_map(arr, title, name, **kw):
        out = paths.OUT_MAPS / f"s1b_{ev}_{rid}_{name}.png"
        plots.raster_map(arr, grid, boundary_utm, title, out, nodata=NODATA, **kw); maps.append((title, out)); files.append(out)
    save_map(prod["pre_median_db"], "Pre-event composite: median VV (dB), 4 scenes, speckle-filtered", "pre_composite", cmap="gray", label="dB", vmin=-25, vmax=0)
    save_map(prod["post_db"], "Post-event VV (dB), 12 Nov 2015, speckle-filtered", "post", cmap="gray", label="dB", vmin=-25, vmax=0)
    save_map(prod["diff_db"], "Change: post - pre median (dB)", "diff", cmap="RdBu", label="dB", vmin=-10, vmax=10)
    save_map(prod["pre_std_db"], "Pre-event temporal std dev (dB)", "pre_std", cmap="viridis", label="dB")
    save_map(prod["slope_deg"], "Slope (deg, NASADEM) - terrain diagnostic", "slope", cmap="magma", label="deg", vmin=0, vmax=10)
    save_map(prod["hand_m"], "HAND (m, MERIT Hydro) - diagnostic", "hand", cmap="cividis", label="m", vmin=0, vmax=30)
    # overlay map
    fig, ax = plt.subplots(figsize=(7.5, 8))
    base = np.ma.masked_where(prod["post_db"] == NODATA, prod["post_db"])
    ax.imshow(base, extent=grid.extent, cmap="gray", vmin=-25, vmax=0, interpolation="nearest")
    fl = np.ma.masked_where(prod["flood_proxy_30m"] != 1, prod["flood_proxy_30m"])
    ax.imshow(fl, extent=grid.extent, cmap="autumn", vmin=0, vmax=1, interpolation="nearest")
    pw = np.ma.masked_where(~(prod["mask_perm_water_frac"] >= 0.5), prod["mask_perm_water_frac"])
    ax.imshow(pw, extent=grid.extent, cmap="winter", vmin=0, vmax=1, alpha=0.7, interpolation="nearest")
    boundary_utm.boundary.plot(ax=ax, color="black", linewidth=1.0)
    ax.set_title(f"SAR flood PROXY (red) - {ev} - UNVALIDATED\nblue = permanent water mask (JRC)", fontsize=10)
    ax.ticklabel_format(style="plain", useOffset=False); ax.tick_params(labelsize=7)
    out = paths.OUT_MAPS / f"s1b_{ev}_{rid}_flood_proxy.png"; fig.tight_layout(); fig.savefig(out, dpi=200); plt.close(fig)
    maps.insert(0, ("Flood proxy overlay (UNVALIDATED)", out)); files.append(out)

    lims = s1_report.limitations(params, {"post_date": scene_rows[-1].get("date", "")})
    full_meta = dict(meta, label="SAR_PROXY_UNVALIDATED", validation="none - not independently verified; no accuracy claimed",
                     statistics=stats, limitations=lims, mode=mode_label, scenes=scene_rows)
    jp = run_dir / "metadata.json"; jp.write_text(json.dumps(full_meta, indent=2, default=str), encoding="utf-8"); files.append(jp)
    rp = paths.OUT_REP / f"s1b_{ev}_{rid}_report.html"
    images = [(t, "../maps/" + Path(pth).name) for t, pth in maps]
    rp.write_text(s1_report.render_html(full_meta, stats, lims, images, scene_rows), encoding="utf-8"); files.append(rp)
    tp = paths.OUT_TAB / f"s1b_{ev}_{rid}_stats.json"; tp.write_text(json.dumps(stats, indent=2), encoding="utf-8"); files.append(tp)
    return stats, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2015_nov")
    ap.add_argument("--run", action="store_true", help="actually query Earth Engine / process (default: plan only)")
    ap.add_argument("--mode", choices=["local", "drive"], default="local")
    ap.add_argument("--from-tif", default="", help="process a multi-band GeoTIFF exported by --mode drive")
    ap.add_argument("--set", action="append", default=[], metavar="PARAM=VALUE")
    ap.add_argument("--tile-px", type=int, default=512)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    log = get_logger("S1B_v22")
    paths.ensure_dirs()

    cfg = s1_params.load_events()
    ev = next((e for e in cfg["events"] if e["id"] == a.event), None)
    if not ev or not ev.get("scene_ids"):
        status.record("S1B", status.BLOCKED, f"Event '{a.event}' has no pinned scene_ids in config/s1_events.json.", seconds=time.time() - t0)
        log.error("no pinned scenes for %s", a.event); return
    try:
        params = s1_params.get_params(dict(x.split("=", 1) for x in a.set))
    except (KeyError, ValueError) as e:
        log.error("%s", e); status.record("S1B", status.BLOCKED, str(e), seconds=time.time() - t0); return

    # ---- gate: every pinned scene must be verified in the live Earth Engine table ----
    csv = paths.OUT_TAB / f"s1_gee_availability_{a.event}.csv"
    if not csv.exists():
        msg = f"{csv.name} not found - run: .\\.venv\\Scripts\\python scripts\\s1_gee_check.py --event {a.event}"
        log.error(msg); status.record("S1B", status.BLOCKED, msg, requirements=[msg], seconds=time.time() - t0); return
    rows = pd.read_csv(csv).where(lambda d: d.notna(), None).to_dict("records")
    gate = s1_gate.verify_scenes(ev, rows, min_pre=params["min_pre_obs"])
    if not gate["ok"]:
        for pr in gate["problems"]:
            log.error("GATE: %s", pr)
        status.record("S1B", status.BLOCKED, "Scene verification gate failed: " + "; ".join(gate["problems"][:4]),
                      extra={"problems": gate["problems"]}, seconds=time.time() - t0)
        return
    log.info("gate passed: %d scenes verified (exact EE id, date, pass, rel orbit %s, VV)", len(gate["scenes"]), ev["orbit"]["rel_orbit"])

    try:
        grid = master_grid()
        _, utm, _ = load_study_area()
    except FileNotFoundError as e:
        status.record("S1B", status.BLOCKED, str(e), requirements=["python scripts/download_boundaries.py"], seconds=time.time() - t0)
        log.error("%s", e); return
    inside30 = G.inside_mask(grid, utm.geometry)
    sids = ev["scene_ids"]
    rid = s1_params.run_id(a.event, sids, params, grid)
    tiles = s1_proxy.tile_plan(grid, a.tile_px, PROC_RES)
    run_dir = paths.DATA_PROC / "s1b" / a.event / rid
    log.info("run id %s | grid %s %dx%d cells @%gm | 10 m processing | %d tiles of <=%d px | output dir %s",
             rid, grid.crs, grid.width, grid.height, grid.res, len(tiles), a.tile_px, paths.rel(run_dir))
    if not (a.run or a.from_tif or a.mode == "drive"):
        msg = f"Plan only (run id {rid}, {len(tiles)} tiles). Re-run with --run to query Earth Engine."
        log.info(msg); status.record("S1B", status.PARTIAL, msg, extra={"run_id": rid, "tiles": len(tiles), "gate": "passed"}, seconds=time.time() - t0)
        return

    meta = {"event": a.event, "run_id": rid, "generated": datetime.now().isoformat(timespec="seconds"), "crs": grid.crs,
            "processing_res_m": PROC_RES, "output_res_m": grid.res, "grid_shape": [grid.height, grid.width],
            "grid_origin": [grid.transform.c, grid.transform.f], "params": params, "scene_ids": sids,
            "orbit": ev["orbit"], "ee_project": load_settings()["gee"].get("project") or None,
            "gate": "passed (live Earth Engine table)", "mode": a.mode}
    f = int(round(grid.res / PROC_RES))

    try:
        if a.from_tif:
            with rasterio.open(a.from_tif) as ds:
                tr = ds.transform
                t = {"row": 0, "col": 0, "r0": 0, "c0": 0, "w": ds.width, "h": ds.height, "x0": tr.c, "ytop": tr.f, "res": PROC_RES}
            if (t["w"], t["h"]) != (grid.width * f, grid.height * f) or abs(t["x0"] - grid.transform.c) > 1e-3 or abs(t["ytop"] - grid.transform.f) > 1e-3:
                raise ValueError("exported GeoTIFF extent/origin does not match the master grid at 10 m - re-export with --mode drive")
            stack10 = s1_report.assemble([a.from_tif], [t], grid, f)
            mode_label = "drive export processed locally"
        else:
            import ee
            from src.flood_detection import gee_sentinel1 as g1
            g1.init_ee(meta["ee_project"])
            probs = s1_proxy.verify_live(ee, ev)
            if probs:
                for pr in probs:
                    log.error("LIVE CHECK: %s", pr)
                status.record("S1B", status.BLOCKED, "Live Earth Engine re-check failed: " + "; ".join(probs[:3]), seconds=time.time() - t0); return
            log.info("live Earth Engine re-check of all pinned scenes passed")
            img = s1_proxy.build_layers(ee, ev, params)
            epsg = int(str(grid.crs).split(":")[-1])
            if a.mode == "drive":
                name = f"s1b_{a.event}_{rid}"
                task = s1_proxy.start_drive_export(ee, img, grid, epsg, name)
                msg = (f"Export task started: '{name}' (id {task.id}). Monitor: https://code.earthengine.google.com -> Tasks tab, or "
                       f".\\.venv\\Scripts\\earthengine task list ; when COMPLETED download the GeoTIFF from Google Drive folder chennai_flood_s1b, then run: "
                       f"python scripts\\s1b_flood_extent.py --event {a.event} --from-tif <path>")
                log.info(msg); status.record("S1B", status.PARTIAL, msg, extra={"task_id": task.id, "run_id": rid}, seconds=time.time() - t0); return
            tdir = run_dir / "tiles"; tdir.mkdir(parents=True, exist_ok=True)
            files = []
            for i, t in enumerate(tiles, 1):
                tp = tdir / f"tile_r{t['row']:02d}_c{t['col']:02d}.tif"
                if a.force and tp.exists():
                    tp.unlink()
                _, how = s1_proxy.download_tile(ee, img, t, epsg, tp)
                files.append(tp); log.info("tile %d/%d %s (%s)", i, len(tiles), tp.name, how)
            stack10 = s1_report.assemble(files, tiles, grid, f)
            mode_label = "local tiled getDownloadURL"
    except Exception as e:  # noqa
        log.error("S1B failed: %s", e)
        status.record("S1B", status.BLOCKED, f"{type(e).__name__}: {str(e)[:300]}", extra={"run_id": rid}, seconds=time.time() - t0)
        return

    stats, files = write_outputs(stack10, grid, inside30, utm, meta, run_dir, params, ev, gate["scenes"], mode_label)
    log.info("flood PROXY: %s km2 (30 m) / %s km2 (10 m) of %s km2 study area - UNVALIDATED", stats["flood_proxy_km2_30m"],
             stats["flood_proxy_km2_10m"], stats["study_area_km2"])
    status.record("S1B", status.COMPLETED,
                  f"SAR flood PROXY for {a.event} (run {rid}): {stats['flood_proxy_km2_30m']} km2 at 30 m. UNVALIDATED - no accuracy claimed.",
                  files=[paths.rel(x) for x in files], datasets=["COPERNICUS/S1_GRD (pinned scenes)", "JRC/GSW1_4", "NASA/NASADEM_HGT/001", "MERIT/Hydro/v1_0_1"],
                  extra={"run_id": rid, "label": "SAR_PROXY_UNVALIDATED"}, seconds=time.time() - t0)
    log.info("report: %s", paths.rel(paths.OUT_REP / f"s1b_{a.event}_{rid}_report.html"))


if __name__ == "__main__":
    main()
