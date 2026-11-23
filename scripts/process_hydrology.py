#!/usr/bin/env python
"""Module HYD (V2.3) - terrain-derived hydrology: depression diagnostics, conservative DEM conditioning, D8 direction/accumulation,
drainage extraction (+ optional TWI). TERRAIN-DERIVED and UNVERIFIED: not stormwater infrastructure, not validated.
The input DEM is only read, never modified (its SHA-256 is checked before and after).

Usage (PowerShell, project folder):
  .\\.venv\\Scripts\\python scripts\\process_hydrology.py
Options: --dem PATH  --slope PATH  --out-dir DIR (rasters, default data\\processed)  --outputs-dir DIR (figures/tables/reports root, default outputs)
         --threshold-km2 0.1 | --threshold-cells N   --max-fill-depth-m 1.0  --min-depth-m 0.01  --no-twi"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial import hydrology as H

ND = -9999.0
THRESH_SENS_KM2 = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def stat(rows, metric, value, unit="", note=""):
    rows.append({"metric": metric, "value": value, "unit": unit, "note": note})


def figure(arr, grid, title, path, cmap, label, vmin=None, vmax=None, boundary=None, overlay=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 8))
    im = ax.imshow(np.ma.masked_invalid(arr), extent=grid.extent, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    if overlay is not None:
        ax.imshow(np.ma.masked_where(~overlay, overlay), extent=grid.extent, cmap="autumn", vmin=0, vmax=1, interpolation="nearest")
    if boundary is not None:
        boundary.boundary.plot(ax=ax, color="black", linewidth=0.8)
    cb = fig.colorbar(im, ax=ax, shrink=0.75); cb.set_label(label)
    ax.set_title(title, fontsize=10); ax.ticklabel_format(style="plain", useOffset=False); ax.tick_params(labelsize=7)
    ax.set_xlabel("Easting (m, EPSG:32644)"); ax.set_ylabel("Northing (m)")
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", default=str(paths.DATA_PROC / "dem_elevation_utm44n_30m.tif"))
    ap.add_argument("--slope", default=str(paths.DATA_PROC / "slope_deg_utm44n_30m.tif"))
    ap.add_argument("--out-dir", default=str(paths.DATA_PROC))
    ap.add_argument("--outputs-dir", default=str(paths.ROOT / "outputs"))
    ap.add_argument("--threshold-km2", type=float, default=None, help="drainage threshold as contributing area (default 0.1 km2)")
    ap.add_argument("--threshold-cells", type=int, default=None, help="drainage threshold in cells (overrides --threshold-km2)")
    ap.add_argument("--max-fill-depth-m", type=float, default=1.0)
    ap.add_argument("--min-depth-m", type=float, default=0.01)
    ap.add_argument("--eps", type=float, default=1e-6)
    ap.add_argument("--expect-epsg", type=int, default=32644)
    ap.add_argument("--no-twi", action="store_true")
    ap.add_argument("--min-twi-slope-deg", type=float, default=0.1)
    ap.add_argument("--twi-max-clamped-pct", type=float, default=30.0)
    a = ap.parse_args()
    t0 = time.time()
    log = get_logger("HYD_hydrology")
    paths.ensure_dirs()
    out_dir, odir = Path(a.out_dir), Path(a.outputs_dir)
    fig_dir, tab_dir, rep_dir = odir / "figures", odir / "tables", odir / "reports"
    for d in (out_dir, fig_dir, tab_dir, rep_dir):
        d.mkdir(parents=True, exist_ok=True)

    dem_p = Path(a.dem)
    if not dem_p.exists():
        msg = f"DEM not found: {dem_p}. Run scripts\\process_dem.py first (or pass --dem)."
        log.error(msg); status.record("HYD", status.BLOCKED, msg, requirements=["python scripts/process_dem.py"], seconds=time.time() - t0); return
    names = {k: out_dir / f"{k}_utm44n_30m.tif" for k in ("dem_conditioned", "flow_direction_d8", "flow_accumulation", "drainage_network", "twi")}
    gpkg = out_dir / "drainage_network_utm44n_30m.gpkg"
    if dem_p.resolve() in {p.resolve() for p in list(names.values()) + [gpkg]}:
        msg = "refusing to run: an output path equals the input DEM (the original DEM must never be overwritten)"
        log.error(msg); status.record("HYD", status.BLOCKED, msg, seconds=time.time() - t0); return
    dem_hash = sha256(dem_p)

    with rasterio.open(dem_p) as ds:
        arr, tr, crs, nd = ds.read(1).astype("float64"), ds.transform, ds.crs, ds.nodata
    try:
        facts, valid = H.validate_dem(arr, tr, crs, nd, expect_epsg=a.expect_epsg)
        res = facts["res"]
        thr_cells, thr_km2 = H.threshold_from(res, a.threshold_cells, a.threshold_km2)
    except ValueError as e:
        log.error("input validation failed: %s", e); status.record("HYD", status.BLOCKED, f"Input validation failed: {e}", seconds=time.time() - t0); return
    grid = G.Grid(f"EPSG:{facts['epsg']}", tr, arr.shape[1], arr.shape[0], res)
    if not facts["nodata_defined"]:
        log.warning("DEM has no nodata value defined: only non-finite cells are treated as invalid")
    log.info("DEM %s: EPSG:%s, %gm, %dx%d, %d valid cells, z %.2f..%.2f m", dem_p.name, facts["epsg"], res, grid.width, grid.height,
             facts["valid_cells"], facts["min"], facts["max"])

    slope = None
    sp = Path(a.slope)
    if sp.exists():
        with rasterio.open(sp) as sd:
            if sd.shape == arr.shape and sd.transform == tr and sd.crs == crs:
                slope = sd.read(1).astype("float64"); slope[(slope == sd.nodata) | ~valid] = np.nan
            else:
                log.warning("slope raster %s is not aligned with the DEM: TWI will be skipped", sp.name)
    else:
        log.warning("slope raster not found (%s): TWI will be skipped", sp)

    log.info("diagnostics + conditioning (priority-flood, max fill depth %.2f m)", a.max_fill_depth_m)
    cond, info = H.condition_dem(arr, valid, a.max_fill_depth_m, a.min_depth_m, a.eps)
    clus, nsum = H.negative_clusters(arr, valid, info, res, tr)
    chg = H.change_stats(arr, cond, valid, res)
    log.info("negative cells %d (%.3f%%) in %d clusters; depressions %d (filled %d, kept %d)", nsum["negative_cells"], nsum["negative_pct"],
             nsum["clusters"], info["n_depressions"], info["n_filled"], info["n_kept"])
    log.info("D8 flow direction + topological accumulation")
    fd = H.d8_flow_direction(cond, valid)
    acc = H.flow_accumulation(fd)
    term = H.terminal_cells(fd)
    outl = H.outlet_mask(valid)
    conserve = float(np.nansum(acc[term])) == float(valid.sum())
    if not conserve:
        raise RuntimeError("flow accumulation is not conserved (sum at terminal cells != valid cells)")
    net = H.extract_drainage(acc, thr_cells)
    log.info("drainage threshold %d cells (%.4f km2): %d channel cells", thr_cells, thr_km2, int(net.sum()))

    # ---- rasters
    cdem = np.where(valid, cond, ND)
    G.write_raster(names["dem_conditioned"], cdem, grid, ND, "Conditioned DEM (float64: epsilon gradients); original DEM unchanged", "float64")
    G.write_raster(names["flow_direction_d8"], fd, grid, H.FD_NODATA, "D8 flow direction ESRI codes (0=outlet/sink)", "uint8")
    G.write_raster(names["flow_accumulation"], np.where(valid, np.nan_to_num(acc), ND), grid, ND, "D8 flow accumulation (cells incl. self), terrain-derived", "float32")
    G.write_raster(names["drainage_network"], np.where(valid, net, H.FD_NODATA).astype("uint8"), grid, H.FD_NODATA,
                   f"Terrain-derived drainage (acc >= {thr_cells} cells = {thr_km2:.4f} km2); NOT verified stormwater infrastructure", "uint8")
    written = list(names.values())[:4]

    # ---- TWI (guarded)
    twi_note, twi_arr, twi_info = "not generated", None, {}
    if a.no_twi:
        twi_note = "skipped by --no-twi"
    elif slope is None:
        twi_note = "skipped: no aligned slope raster"
    else:
        twi_arr, clamped = H.twi(acc, slope, res, a.min_twi_slope_deg)
        if 100 * clamped > a.twi_max_clamped_pct:
            twi_note = f"skipped: {100 * clamped:.1f}% of cells have slope < {a.min_twi_slope_deg} deg (> {a.twi_max_clamped_pct}% limit): TWI would be dominated by the clamp"
            twi_arr = None
        else:
            G.write_raster(names["twi"], np.where(np.isfinite(twi_arr), twi_arr, ND), grid, ND, "TWI = ln(a/tan(beta)); relative index, terrain-derived, unvalidated", "float32")
            written.append(names["twi"]); twi_note = f"generated (slope clamp {a.min_twi_slope_deg} deg affects {100 * clamped:.2f}% of cells)"
            twi_info = {"twi_min": float(np.nanmin(twi_arr)), "twi_mean": float(np.nanmean(twi_arr)), "twi_max": float(np.nanmax(twi_arr)), "clamped_pct": 100 * clamped}
    log.info("TWI: %s", twi_note)

    # ---- vector
    gpkg_note = "not written"
    try:
        import geopandas as gpd
        from shapely.geometry import LineString
        r, c, r2, c2, ln, idx = H.segments(fd, net, res)
        xs = lambda cc: tr.c + (cc + 0.5) * tr.a
        ys = lambda rr: tr.f + (rr + 0.5) * tr.e
        geoms = [LineString([(xs(cc), ys(rr)), (xs(cc2), ys(rr2))]) for rr, cc, rr2, cc2 in zip(r, c, r2, c2)]
        gdf = gpd.GeoDataFrame({"acc_cells": acc.ravel()[idx], "acc_km2": acc.ravel()[idx] * res * res / 1e6, "length_m": ln,
                                "label": "terrain-derived, unverified"}, geometry=geoms, crs=grid.crs)
        if gpkg.exists():
            gpkg.unlink()
        gdf.to_file(gpkg, layer="drainage_segments", driver="GPKG")
        written.append(gpkg); gpkg_note = f"{len(gdf)} segments, {gdf.length_m.sum() / 1000:.1f} km"
    except Exception as e:  # noqa
        gpkg_note = f"NOT written ({type(e).__name__}: {str(e)[:120]})"; log.warning("GeoPackage: %s", gpkg_note)

    # ---- tables
    rows = []
    stat(rows, "input_dem", dem_p.name, "", "read-only; sha256 " + dem_hash[:16] + "...")
    stat(rows, "crs", f"EPSG:{facts['epsg']}"); stat(rows, "resolution", res, "m")
    stat(rows, "grid_size", f"{grid.width}x{grid.height}", "cells"); stat(rows, "valid_cells", facts["valid_cells"], "cells")
    for k in ("min", "mean", "median", "max"):
        stat(rows, f"elevation_{k}", round(facts[k], 3), "m")
    stat(rows, "negative_elevation_cells", nsum["negative_cells"], "cells"); stat(rows, "negative_elevation_pct", round(nsum["negative_pct"], 4), "%")
    stat(rows, "negative_clusters", nsum["clusters"], "clusters"); stat(rows, "negative_largest_cluster", nsum["largest_cluster_cells"], "cells")
    stat(rows, "negative_share_within_300m_of_nodata_edge", round(nsum["share_within_300m_of_edge_pct"], 1), "%")
    stat(rows, "negative_share_in_closed_depressions", round(nsum["share_in_closed_depressions_pct"], 1), "%", "closed = fill depth > min-depth")
    stat(rows, "closed_depressions_total", info["n_depressions"], "count"); stat(rows, "depressions_filled", info["n_filled"], "count", f"max depth <= {a.max_fill_depth_m} m")
    stat(rows, "depressions_kept_unfilled", info["n_kept"], "count", "treated as internal sinks")
    for k, v in chg.items():
        stat(rows, f"conditioning_{k}", round(v, 6) if isinstance(v, float) else v)
    stat(rows, "conditioning_max_fill_depth_param", a.max_fill_depth_m, "m"); stat(rows, "conditioning_min_depth_param", a.min_depth_m, "m")
    stat(rows, "conditioning_epsilon", a.eps, "m/cell")
    stat(rows, "flow_terminal_cells", int(term.sum()), "cells", "no downslope neighbour")
    stat(rows, "flow_outlets_on_nodata_edge", int((term & outl).sum()), "cells"); stat(rows, "flow_internal_sinks", int((term & ~outl).sum()), "cells", "kept depressions / unresolved")
    stat(rows, "accumulation_conserved", conserve, "", "sum of accumulation at terminal cells == valid cells")
    stat(rows, "accumulation_max", int(np.nanmax(acc)), "cells"); stat(rows, "accumulation_max_area", round(float(np.nanmax(acc)) * res * res / 1e6, 3), "km2")
    stat(rows, "drainage_threshold_cells", thr_cells, "cells"); stat(rows, "drainage_threshold_area", round(thr_km2, 5), "km2")
    stat(rows, "drainage_channel_cells", int(net.sum()), "cells"); stat(rows, "drainage_vector", gpkg_note)
    stat(rows, "twi", twi_note)
    for k, v in twi_info.items():
        stat(rows, k, round(v, 3))
    pd.DataFrame(rows).to_csv(tab_dir / "hydrology_statistics.csv", index=False)
    pd.DataFrame(clus).to_csv(tab_dir / "hydrology_negative_clusters.csv", index=False)
    pd.DataFrame(H.depression_sensitivity(info, res)).to_csv(tab_dir / "hydrology_depression_sensitivity.csv", index=False)
    cell_km2 = res * res / 1e6
    ts = []
    for t in THRESH_SENS_KM2:
        tc = max(1, int(np.ceil(t / cell_km2))); n_ = H.extract_drainage(acc, tc)
        rr_, cc_, _, _, ll_, _ = H.segments(fd, n_, res)
        ts.append({"threshold_km2": t, "threshold_cells": tc, "channel_cells": int(n_.sum()), "network_length_km": round(float(ll_.sum()) / 1000, 2)})
    pd.DataFrame(ts).to_csv(tab_dir / "hydrology_drainage_threshold_sensitivity.csv", index=False)

    # ---- figures
    boundary = None
    try:
        from src.geospatial.study_area import load_study_area
        _, utm, _ = load_study_area(); boundary = utm
    except Exception:
        pass
    zshow = np.where(valid, arr, np.nan)
    figure(np.log10(np.where(valid, np.maximum(acc, 1), np.nan)), grid, "D8 flow accumulation (log10 cells) - terrain-derived, unvalidated",
           fig_dir / "flow_accumulation_map.png", "Blues", "log10(contributing cells)", boundary=boundary)
    figure(zshow, grid, f"Terrain-derived drainage network (>= {thr_km2:.3f} km2 = {thr_cells} cells) - NOT verified stormwater infrastructure",
           fig_dir / "drainage_network_map.png", "gray", "elevation (m)", boundary=boundary, overlay=net)
    figure(np.where(valid, cond - arr, np.nan), grid, f"Conditioning difference (conditioned - original, m); max fill depth {a.max_fill_depth_m} m",
           fig_dir / "dem_conditioning_difference.png", "viridis", "m", vmin=0, vmax=max(a.max_fill_depth_m, 0.1), boundary=boundary)
    figs = ["flow_accumulation_map.png", "drainage_network_map.png", "dem_conditioning_difference.png"]
    if twi_arr is not None:
        lo, hi = np.nanpercentile(twi_arr, [2, 98])
        figure(twi_arr, grid, "Topographic wetness index (relative, terrain-derived, unvalidated)", fig_dir / "twi_map.png", "YlGnBu", "TWI", vmin=lo, vmax=hi, boundary=boundary)
        figs.append("twi_map.png")

    # ---- report
    after_hash = sha256(dem_p)
    unchanged = after_hash == dem_hash
    big = sorted(clus, key=lambda x: -x["cells"])[:5]
    md = f"""# Hydrological terrain analysis - methodology and results (V2.3)

**All products are TERRAIN-DERIVED and UNVERIFIED.** The drainage network is not stormwater infrastructure; no hydrological validation exists or is claimed.

## Input
`{dem_p.name}`, EPSG:{facts['epsg']}, {res:g} m, {grid.width}x{grid.height} cells, {facts['valid_cells']} valid cells, elevation {facts['min']:.2f} to {facts['max']:.2f} m (mean {facts['mean']:.2f}, median {facts['median']:.3f}).
SHA-256 before/after the run: {'identical (DEM unchanged)' if unchanged else 'DIFFERENT - INVESTIGATE'} (`{dem_hash[:16]}...`).
The study-area boundary is the provisional OpenStreetMap polygon; NoData cells outside it are never used or crossed.

## Method
1. **Validation**: projected CRS = EPSG:{a.expect_epsg}, square north-up pixels, no rotation, at least one valid cell, NoData mask.
2. **Negative-elevation diagnostics**: {nsum['negative_cells']} cells ({nsum['negative_pct']:.3f}%) in {nsum['clusters']} clusters; {nsum['share_within_300m_of_edge_pct']:.1f}% lie within 300 m of the NoData edge; {nsum['share_in_closed_depressions_pct']:.1f}% lie in closed depressions. Per-cluster table: `hydrology_negative_clusters.csv`. Negative cells are NOT automatically treated as errors: they could be genuine below-datum low ground, vertical-datum effects or source artefacts, and this analysis cannot tell which.
3. **Conditioning (conservative priority-flood, Barnes et al. 2014 with epsilon {a.eps:g} m/cell)**: outlets are valid cells on the raster edge or touching NoData. The full fill gives spill-level depth D. Closed depressions are 8-connected groups with D > {a.min_depth_m} m. A depression whose maximum fill depth is <= {a.max_fill_depth_m} m is filled (micro-relief/artefact); a deeper one is **kept unfilled** as an internal sink. Result: {info['n_depressions']} depressions, {info['n_filled']} filled, {info['n_kept']} kept. Cells raised by more than {chg['tolerance_m']} m: {chg['cells_raised_gt_tol']} ({chg['pct_valid_changed']:.3f}% of valid cells, {chg['area_km2_raised']:.3f} km2); max raise {chg['max_raise_m']:.3f} m; volume added {chg['volume_added_m3']:.0f} m3; no cell is lowered. The conditioned DEM is stored as float64 because the epsilon gradients (1e-6 m) are lost in float32. Sensitivity to the depth limit: `hydrology_depression_sensitivity.csv`.
4. **D8 flow direction**: steepest strictly-descending neighbour (diagonals scaled by sqrt 2, ties broken in fixed E,SE,S,SW,W,NW,N,NE order, so results are deterministic). NoData is never a target. Codes: E1 SE2 S4 SW8 W16 NW32 N64 NE128, 0 outlet/sink, 255 NoData.
5. **Flow accumulation**: topological (Kahn) algorithm in cells including the cell itself; a cycle raises an error. Conservation check: accumulation summed over terminal cells = number of valid cells -> **{conserve}**. Terminal cells: {int(term.sum())} ({int((term & outl).sum())} outlets on the NoData edge, {int((term & ~outl).sum())} internal sinks).
6. **Drainage extraction**: contributing area >= {thr_km2:.4f} km2 = {thr_cells} cells -> {int(net.sum())} channel cells; vector: {gpkg_note}. Threshold sensitivity: `hydrology_drainage_threshold_sensitivity.csv`.
7. **TWI**: {twi_note}. Formula ln(a/tan beta), a = contributing area / cell size (D8), slope from `{sp.name}`, slopes clamped at {a.min_twi_slope_deg} deg, generated only if the clamp affects <= {a.twi_max_clamped_pct}% of cells.

## Largest negative clusters
""" + "\n".join(f"- cluster {b['cluster']}: {b['cells']} cells, min {b['min_elev_m']:.2f} m, {b['min_dist_to_nodata_edge_m']:.0f} m from NoData edge, closed depression: {b['closed_depression']}, kept unfilled: {b['kept_unfilled']}" for b in big) + f"""

## Assumptions and limitations
- The study-area edge acts as an outlet; contributing area from outside the boundary is ignored, so accumulation near the edge is underestimated (edge effect).
- A 30 m DEM (Copernicus GLO-30 is a surface model including buildings/vegetation) does not resolve culverts, drains, bridges or underpasses; urban flow paths can differ strongly from terrain-derived ones. No stormwater network was used.
- Kept (deep) depressions stop all flow, which breaks connectivity downstream of tanks/marsh; filled depressions assume micro-relief overflows. The 1 m limit is a configurable assumption, not a validated value.
- Coastal/tidal levels, rainfall, soil infiltration and channel/tank geometry are not modelled; D8 cannot represent divergent flow on flat terrain.
- TWI is a relative index; on very flat terrain it is unstable and sensitive to the slope clamp and to DEM noise.
- Independent reference data (e.g. mapped drains, surveyed flood points) were not used: the products are not validated.

## Outputs
Rasters in `{paths.rel(out_dir)}`: {', '.join(p.name for p in written)}. Figures: {', '.join(figs)}. Tables: hydrology_statistics.csv, hydrology_negative_clusters.csv, hydrology_depression_sensitivity.csv, hydrology_drainage_threshold_sensitivity.csv.
"""
    (rep_dir / "hydrology_methodology.md").write_text(md, encoding="utf-8")
    meta = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "dem": str(dem_p), "dem_sha256": dem_hash, "dem_unchanged": unchanged,
            "params": {k: getattr(a, k) for k in ("max_fill_depth_m", "min_depth_m", "eps", "threshold_km2", "threshold_cells")},
            "threshold_cells_used": thr_cells, "label": "terrain-derived, unverified"}
    (out_dir / "hydrology_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if not unchanged:
        raise RuntimeError("the input DEM changed during processing")
    st = status.COMPLETED if gpkg_note.startswith(("not", "NOT")) is False else status.PARTIAL
    status.record("HYD", st, f"Terrain-derived hydrology: {info['n_filled']} depressions filled, {info['n_kept']} kept, {int(net.sum())} channel cells at {thr_km2:.3f} km2. "
                  f"Unverified. TWI {twi_note}. Vector: {gpkg_note}.",
                  files=[paths.rel(p) for p in written] + [paths.rel(rep_dir / "hydrology_methodology.md")], extra={"threshold_cells": thr_cells}, seconds=time.time() - t0)
    log.info("done in %.1fs. report: %s", time.time() - t0, paths.rel(rep_dir / "hydrology_methodology.md"))


if __name__ == "__main__":
    main()
