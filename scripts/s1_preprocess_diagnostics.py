#!/usr/bin/env python
"""Module S1PD (V2.3, M4C QA correction) - OFFLINE diagnostics of existing date-level products. READ ONLY: no raster is created, modified, clamped or masked
(file SHA-256 are checked before and after and reported). No Earth Engine unless --ee-native-tail. No flood classification, no baseline, no validation.

 1. High-VV diagnostic: cells above +5 dB (and an exceedance table at several cut-offs): count, AOI share, connected components, spatial distribution
    (block table + map), association with the other polarisation, the seam zone, and (if present) WorldCover class and slope.
 2. Overlap reconciliation: footprint overlap (M4B, outline polygons) vs acquisition-time overlap (slice ids) vs valid per-pixel overlap (M4C, 10 m).
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_diagnostics.py --date 2021-11-16
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_diagnostics.py --date 2021-11-16 --ee-native-tail      # adds native 10 m exceedance from Earth Engine (small query)"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial.study_area import load_study_area, master_grid
from src.flood_detection import s1_preprocess as pp, s1_date_level as dl

CFG = json.loads((paths.CONFIG / "s1_preprocess.json").read_text(encoding="utf-8"))
INV_CSV = paths.OUT_TAB / "s1_inventory_2021_nov_2021-09-01_2021-12-01.csv"
COV_CSV = paths.OUT_TAB / "s1_2021_date_level_coverage.csv"
THRESH = (0.0, 3.0, 5.0, 8.0, 10.0)


def fname(date, pol, kind): return f"S1A_IW_D092_{date.replace('-', '')}_{pol}_{kind}.tif"


def read(p):
    import rasterio
    with rasterio.open(p) as ds:
        return ds.read(1).astype("float64"), ds


def native_tail(ids, pol, grid, aoi_geom):
    """OPTIONAL Earth Engine query: share of native-10 m-lattice cells above each threshold in a plain diagnostic mosaic of the two slices (NOT the product;
    no overlap rule is needed because the slices do not overlap). Returns {threshold: share} or raises."""
    import ee
    from src.utils.config import load_settings
    from src.flood_detection import gee_sentinel1 as g1
    g1.init_ee(load_settings()["gee"].get("project") or None)
    aoi = ee.Geometry(aoi_geom.__geo_interface__, proj="EPSG:4326", geodesic=False)
    img = ee.ImageCollection(CFG["collection"]).filter(ee.Filter.inList("system:index", ids)).select(pol).mosaic()
    t10 = [10.0, 0, grid.transform.c, 0, -10.0, grid.transform.f]
    bands = [img.mask().rename("valid")] + [img.gt(t).rename(f"gt{t}") for t in THRESH]
    r = ee.Image.cat(bands).reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, crs=grid.crs, crsTransform=t10, maxPixels=1e10).getInfo()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=CFG["first_live_date"]); ap.add_argument("--threshold", type=float, default=CFG["qa"]["extreme_high_db"])
    ap.add_argument("--ee-native-tail", action="store_true"); ap.add_argument("--outdir", default=None); ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(); t0 = time.time(); log = get_logger("S1PD"); paths.ensure_dirs()
    d = a.date; outdir = Path(a.outdir) if a.outdir else paths.DATA_PROC / "s1_2021"
    stem = f"s1_2021_{d}"
    outs = {"report": paths.OUT_REP / f"{stem}_qa_diagnostics.md", "components": paths.OUT_TAB / f"{stem}_VV_high_components.csv", "exceed": paths.OUT_TAB / f"{stem}_exceedance.csv",
            "blocks": paths.OUT_TAB / f"{stem}_VV_high_blocks.csv", "overlap": paths.OUT_TAB / f"{stem}_overlap_reconciliation.csv", "enrich": paths.OUT_TAB / f"{stem}_VV_high_class_enrichment.csv",
            "map": paths.OUT_FIG / f"{stem}_VV_high_map.png"}
    if not a.overwrite and any(o.exists() for k, o in outs.items() if k != "enrich"):
        print("STOP: diagnostics outputs exist, not overwritten (use --overwrite):", [str(o) for o in outs.values() if o.exists()]); return
    mpath = outdir / f"S1A_IW_D092_{d.replace('-', '')}_meta.json"
    if not mpath.exists(): print(f"STOP: metadata not found: {mpath}"); return
    md = json.loads(mpath.read_text(encoding="utf-8")); ids = md["source_scene_ids"]
    prod = {f"{pol}_{k}": outdir / fname(d, pol, k) for pol in pp.POLS for k in ("dB", "validfrac", "valid")}
    missing = [str(p) for p in prod.values() if not p.exists()]
    if missing: print("STOP: products missing:", missing); return
    before = {k: pp.sha256_file(p) for k, p in prod.items()}                      # proof of read-only behaviour
    grid = master_grid(); wgs, _, aoi_meta = load_study_area(); aoi_geom = wgs.unary_union
    import geopandas as gpd
    from src.geospatial.grid import inside_mask
    inside = inside_mask(grid, [gpd.GeoSeries([aoi_geom], crs=4326).to_crs(grid.crs).iloc[0]])
    arr = {}
    for pol in pp.POLS:
        db, ds = read(prod[f"{pol}_dB"]); vf, _ = read(prod[f"{pol}_validfrac"])
        if tuple(ds.transform)[:6] != tuple(grid.transform)[:6] or db.shape != grid.shape: print(f"STOP: {pol} product is not on the current master grid"); return
        arr[pol] = (db, pp.valid_mask(db, vf, CFG["min_valid_fraction"], CFG["nodata"]), vf)
    fps = {}
    if INV_CSV.exists():
        inv = pd.read_csv(INV_CSV); fps = {r["id"]: dl.footprint_geom(r["footprint"]) for r in inv.to_dict("records") if r["id"] in ids}
    zone = pp.seam_zone(grid, fps[ids[0]], fps[ids[1]], aoi_geom, CFG["qa"]["seam_width_m"]) if len(fps) == 2 else None
    # ---------------- 1. high-VV diagnostic
    vv, vvv, _ = arr["VV"]; vh, vhv, _ = arr["VH"]
    exc = [dict(pol=pol, **r) for pol in pp.POLS for r in pp.exceedance_table(arr[pol][0], arr[pol][1], inside, THRESH)]
    summ, comps, blocks, lab = pp.high_value_diagnostics(vv, vvv, inside, grid, a.threshold, other_db=np.where(vhv, vh, np.nan), seam=zone)
    pd.DataFrame(exc).to_csv(outs["exceed"], index=False)
    pd.DataFrame(comps).sort_values("cells", ascending=False).to_csv(outs["components"], index=False); pd.DataFrame(blocks).to_csv(outs["blocks"], index=False)
    mask = vvv & inside & (vv > a.threshold)
    enrich_note = "WorldCover / slope rasters not found in data/processed: association with land cover and slope NOT assessed."; enrich = []
    lc_p, sl_p = paths.DATA_PROC / "landcover_class_utm44n_30m.tif", paths.DATA_PROC / "slope_deg_utm44n_30m.tif"
    anc = {}
    if lc_p.exists():
        lc, lds = read(lc_p)
        if lc.shape == grid.shape and tuple(lds.transform)[:6] == tuple(grid.transform)[:6]:
            enrich = pp.class_enrichment(mask, lc.astype(int), vvv & inside); pd.DataFrame(enrich).to_csv(outs["enrich"], index=False); anc["landcover"] = True
        else: enrich_note = "landcover raster is not on the master grid: association NOT assessed."
    if sl_p.exists():
        sl, sds = read(sl_p)
        if sl.shape == grid.shape and tuple(sds.transform)[:6] == tuple(grid.transform)[:6]:
            ok = np.isfinite(sl) & (sl != -9999.0) & vvv & inside
            anc["slope_high"] = float(sl[ok & mask].mean()) if (ok & mask).any() else None; anc["slope_rest"] = float(sl[ok & ~mask].mean()) if (ok & ~mask).any() else None
    # map
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 7)); ext = grid.extent
    bg = np.where(vvv, vv, np.nan); lo, hi = np.nanpercentile(bg[np.isfinite(bg)], [2, 98])
    ax[0].imshow(bg, cmap="gray", vmin=lo, vmax=hi, extent=ext); ov = np.zeros(grid.shape + (4,)); ov[mask] = [1, 0, 0, 0.9]; ax[0].imshow(ov, extent=ext)
    ax[0].set_title(f"{d} VV > {a.threshold:+.0f} dB (red) over VV (grey)\\n{summ['high_cells']} cells, {summ['pct_of_aoi_cells']} % of AOI cells, {summ['n_components']} components", fontsize=9)
    bdf = pd.DataFrame(blocks); H = bdf.pivot(index="block_row", columns="block_col", values="high_pct_of_block_aoi").values.astype(float)
    im = ax[1].imshow(H, cmap="magma", extent=ext, aspect="auto"); fig.colorbar(im, ax=ax[1], shrink=0.7, label="% of block AOI cells above threshold")
    ax[1].set_title("Spatial distribution: share by block (10 x 5 blocks over the grid)", fontsize=9)
    for x in ax: x.set_xlabel("Easting (m, EPSG:32644)"); x.set_ylabel("Northing (m)")
    fig.suptitle("Diagnostic only - not a flood map, no values were clamped or removed", fontsize=9); fig.savefig(outs["map"], dpi=110, bbox_inches="tight"); plt.close(fig)
    # native tail
    nat = None; nat_err = None
    if a.ee_native_tail:
        try: nat = native_tail(ids, "VV", grid, aoi_geom)
        except Exception as e: nat_err = str(e)[:250]                                # noqa: BLE001
    # ---------------- 2. overlap reconciliation
    tr = pp.slice_time_relation(ids[0], ids[1])
    fo = pp.footprint_overlap_geometry(fps[ids[0]], fps[ids[1]], aoi_geom) if len(fps) == 2 else None
    cov = pd.read_csv(COV_CSV) if COV_CSV.exists() else None
    cr = cov[cov["date_utc"].astype(str).str[:10] == d].iloc[0].to_dict() if cov is not None and (cov["date_utc"].astype(str).str[:10] == d).any() else {}
    ovd = (md.get("overlap_diagnostics") or {}).get("VV") or {}
    sz = None
    if zone is not None:
        z = zone & inside; vfv = arr["VV"][2]
        sz = {"seam_zone_cells": int(z.sum()), "seam_zone_min_validfrac": float(vfv[z].min()) if z.any() else None, "seam_zone_cells_validfrac_lt_1": int((vfv[z] < 1.0).sum()) if z.any() else None,
              "seam_zone_valid_pct": round(100.0 * float(arr['VV'][1][z].mean()), 4) if z.any() else None}
    exp_px = None if fo is None else fo["overlap_area_m2"] / 100.0
    row = {"date": d, "slice_a": ids[0], "slice_b": ids[1], "time_gap_s_between_slices": tr["gap_s"], "same_datatake": tr["same_datatake"],
           "m4b_footprint_overlap_pct_of_aoi": cr.get("overlap_pct_of_aoi"), "m4b_footprint_overlap_km2": cr.get("overlap_km2"), "m4b_gap_pct_of_aoi": cr.get("gap_pct_of_aoi"),
           "local_footprint_overlap_area_m2": None if fo is None else fo["overlap_area_m2"], "local_footprint_overlap_width_m": None if fo is None else fo["overlap_width_m"],
           "local_footprint_overlap_length_m": None if fo is None else fo["overlap_length_m"], "expected_10m_px_if_footprint_were_data": exp_px,
           "m4c_valid_10m_overlap_px_VV": ovd.get("n_overlap_px"), "m4c_valid_10m_overlap_px_VH": ((md.get("overlap_diagnostics") or {}).get("VH") or {}).get("n_overlap_px"),
           "source_valid_share_10m_VV": ((md.get("source_stats_10m") or {}).get("VV") or {}).get("valid_share_10m"), **{f"seam_{k}": v for k, v in (sz or {}).items()}}
    pd.DataFrame([row]).to_csv(outs["overlap"], index=False)
    after = {k: pp.sha256_file(p) for k, p in prod.items()}; unchanged = before == after
    # ---------------- report
    f4 = lambda v: "n/a" if v is None or (isinstance(v, float) and v != v) else (round(v, 4) if isinstance(v, float) else v)   # noqa: E731
    L = [f"# Sentinel-1 {d} QA diagnostics (M4C single-date review)", "",
         "READ-ONLY diagnostics of the existing products. No value was clamped, removed or masked; the original rasters are unchanged (SHA-256 of the six product files compared before/after: **" + ("identical" if unchanged else "DIFFERENT - investigate") + "**). Not a flood analysis, not a baseline, not validation.", "",
         f"- Scenes: `{ids[0]}`, `{ids[1]}`. AOI: {aoi_meta.get('kind')} (provisional). Product grid {grid.crs} {grid.res} m, default `{md.get('resampling_default')}`.", "",
         f"## 1. VV above {a.threshold:+.0f} dB", "",
         f"- Cells: **{summ['high_cells']}** = **{summ['pct_of_aoi_cells']} %** of AOI cells ({summ['pct_of_valid_aoi_cells']} % of valid AOI cells).",
         f"- Connected components (8-neighbour): **{summ['n_components']}**; largest {summ['largest_component_cells']} cells ({round(summ['largest_component_cells'] * 900 / 1e6, 4)} km2); median {summ['median_component_cells']} cells; single-cell components {summ['cells_in_components_of_1']}; share of flagged cells in components of >= 10 cells: {summ['pct_cells_in_components_ge_10']} %.",
         f"- Component size histogram (cells): {json.dumps(summ['size_histogram'])}.", "- Spatial distribution: see `" + paths.rel(outs['blocks']) + "` and the map `" + paths.rel(outs['map']) + "`; components with coordinates in `" + paths.rel(outs['components']) + "`.",
         "", "### Exceedance at several cut-offs (no single cut-off is implied)", "", "| pol | threshold dB | cells | % of AOI cells | % of valid AOI cells |", "|---|---|---|---|---|"]
    L += [f"| {r['pol']} | {r['threshold_db']:+.0f} | {r['cells']} | {r['pct_of_aoi_cells']} | {r['pct_of_valid_aoi_cells']} |" for r in exc]
    L += ["", "### Is the tail created by the 10 m -> 30 m aggregation? (from this date's metadata, server-side AOI statistics at 30 m)", "", "| option | VV mean dB | VV p95 dB | VV std dB |", "|---|---|---|---|"]
    for nm, st in ((md.get("speckle_options") or {}).get("VV") or {}).items(): L.append(f"| {nm} | {f4(st.get('mean_db'))} | {f4(st.get('p95_db'))} | {f4(st.get('std_db'))} |")
    L += ["", "If the unfiltered `point_db` option already has a similar p95, the bright tail is present before the linear block mean (aggregation is not what creates it). Linear averaging does weight bright scatterers more than a dB average, so the two can differ.", ""]
    if a.ee_native_tail:
        L += ["### Native 10 m exceedance (Earth Engine diagnostic mosaic, not the product)", ""]
        L += [f"- query FAILED: {nat_err}" if nat_err else "| threshold dB | share of native-lattice cells (of all cells incl. masked: see valid) |\n|---|---|\n" + "\n".join(f"| {t:+.0f} | {f4(nat.get(f'gt{t}'))} |" for t in THRESH) + f"\n\nvalid share in the diagnostic mosaic: {f4(nat.get('valid'))}. (`gt` shares are means over AOI cells including masked cells as 0 in the denominator-weighted sense of the reducer; compare with the 30 m table above only qualitatively.)"]
        L += [""]
    oth = summ.get("other_pol_mean_db_at_high_cells")
    L += ["### Association (descriptive, not causal)", "",
          f"- VH at the high-VV cells: mean {f4(oth)} dB versus {f4(summ.get('other_pol_mean_db_elsewhere'))} dB elsewhere.",
          (f"- Seam zone: {summ.get('high_cells_in_seam_zone')} high cells inside the seam zone, which is {summ.get('seam_zone_share_of_aoi_pct')} % of the AOI; high share within the zone {summ.get('high_share_in_seam_zone_pct')} % vs {summ['pct_of_valid_aoi_cells']} % overall." if "high_cells_in_seam_zone" in summ else "- Seam zone not available (inventory footprints not found).")]
    if enrich:
        L += ["", "| WorldCover class | % of valid AOI | % of flagged | enrichment | % of class flagged |", "|---|---|---|---|---|"] + [f"| {r['class']} {r['name']} | {r['share_of_valid_aoi_pct']} | {r['share_of_flagged_pct']} | {r['enrichment_ratio']} | {r['pct_of_class_flagged']} |" for r in enrich]
    else: L += ["", f"- {enrich_note}"]
    if "slope_high" in anc: L += ["", f"- Mean slope at high cells {f4(anc['slope_high'])} deg vs {f4(anc['slope_rest'])} deg elsewhere (DEM-derived, 30 m)."]
    L += ["", "**Interpretation limits.** Nothing here shows these values are errors, and nothing shows they are correct. Backscatter above 0 dB is commonly reported over dense built-up surfaces (corner/double-bounce reflectors) and the product is not radiometrically terrain-flattened, so slope-facing surfaces can also be bright; these are hypotheses to test against the class/slope association above and the preview, not findings. No clamping, masking or removal is applied or recommended on this evidence alone.", "",
          "## 2. Overlap reconciliation: three different things", "",
          "| notion | defined by | value for this date |", "|---|---|---|",
          f"| acquisition-time overlap | scene ids (start/stop): first slice stops {tr['first_stop']}, second starts {tr['second_start']} | gap = {tr['gap_s']} s; same data take: {tr['same_datatake']} |",
          f"| footprint (outline) overlap, M4B | intersection of slice footprint polygons inside the AOI | {f4(row['m4b_footprint_overlap_pct_of_aoi'])} % of AOI = {f4(row['m4b_footprint_overlap_km2'])} km2 (M4B file); local recomputation: area {f4(row['local_footprint_overlap_area_m2'])} m2, sliver width ~{f4(row['local_footprint_overlap_width_m'])} m, length ~{f4(row['local_footprint_overlap_length_m'])} m |",
          f"| valid per-pixel overlap, M4C | cells (10 m UTM lattice) where BOTH slices have data in the AOI | VV {row['m4c_valid_10m_overlap_px_VV']} px, VH {row['m4c_valid_10m_overlap_px_VH']} px |", ""]
    if tr["gap_s"] == 0:
        L.append(f"- The scene ids show a shared cut time ({tr['second_start']}, gap 0 s): the two slices are consecutive parts of one data take. This module does not assume that adjacent slices must, or must not, share pixels; the pixel overlap is reported as measured above.")
    if fo is not None and exp_px is not None:
        if fo["overlap_width_m"] < 10.0: L.append(f"- The footprint-overlap sliver is ~{round(fo['overlap_width_m'], 2)} m wide, narrower than one 10 m pixel: an outline overlap of this size is consistent with zero pixels where both slices have valid data (polygon edges, rounding of stored footprints and geodesic-vs-planar edges can create a thin outline overlap without any shared pixels).")
        else: L.append(f"- The footprint-overlap sliver is ~{round(fo['overlap_width_m'], 1)} m wide (about {round(exp_px)} 10 m cells if it were data), WIDER than one pixel, yet {row['m4c_valid_10m_overlap_px_VV']} valid overlapping pixels were found: this is NOT explained by sub-pixel width. Possible: the footprint outline includes border/no-data margins that carry no valid pixels. Not confirmed - inspect the slice edges.")
    if sz and sz["seam_zone_min_validfrac"] is not None:
        L.append(f"- Gap check across the seam: seam-zone cells {sz['seam_zone_cells']}; minimum valid fraction {f4(sz['seam_zone_min_validfrac'])}; cells with valid fraction < 1: {sz['seam_zone_cells_validfrac_lt_1']}; valid share of the zone {sz['seam_zone_valid_pct']} %. Whole-AOI valid share at 10 m: {f4(row['source_valid_share_10m_VV'])}.")
    L += ["- The overlap rule (linear-power mean of valid slices) is unchanged and was not forced to overlap anything; with zero overlapping valid pixels every output cell comes from exactly one slice.", ""]
    outs["report"].write_text("\n".join(L) + "\n", encoding="utf-8")
    status.record("S1PD", status.COMPLETED if unchanged else status.PARTIAL, f"{d}: {summ['high_cells']} VV cells > {a.threshold} dB in {summ['n_components']} components; footprint/time/pixel overlap reconciled; rasters unchanged: {unchanged}", files=[paths.rel(v) for v in outs.values() if v.exists()], seconds=time.time() - t0)
    print(f"report: {outs['report']}  (rasters unchanged: {unchanged})")


if __name__ == "__main__":
    main()
