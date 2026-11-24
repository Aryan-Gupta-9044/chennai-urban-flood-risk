#!/usr/bin/env python
"""Module S1PP (V2.3, M4C) - Sentinel-1 2021 date-level preprocessing: VV/VH backscatter products on the project master grid (EPSG:32644, 30 m).
PREPROCESSING ONLY: no flood classification, no flood extent, no baseline designation, no validation, no ML. Earth Engine steps are UNTESTED until you run them.

Per date: exact inventory slices -> identity check -> VV and VH independently: slice -> UTM 10 m lattice (aligned to the master grid) -> linear power ->
overlap rule (mean of valid slices) -> exact 3x3 block mean -> dB (default 'linear_area_mean'). Products: <pol>_dB, <pol>_validfrac, <pol>_valid (+ metadata JSON).
Stages are run per date with failure isolation; reruns skip up-to-date dates and refuse stale ones (see --force-stale).

Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_2021.py --plan-only                 # offline: slices, signatures, grid (no Earth Engine)
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_2021.py --dates 2021-11-16          # FIRST live run (one date)
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_2021.py --all                       # all eight dates (skips up-to-date ones)
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_2021.py --qa-only --all             # offline QA/report from existing products
Options: --force-stale (move products of a changed configuration to _superseded/ and regenerate)  --outdir DIR"""
import argparse
import json
import platform as _platform
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial.study_area import load_study_area, master_grid
from src.geospatial import chirps
from src.geospatial.chirps_acquire import tif_bytes_from_download
from src.flood_detection import s1_inventory as inv, s1_date_level as dl, s1_preprocess as pp

CFG = json.loads((paths.CONFIG / "s1_preprocess.json").read_text(encoding="utf-8"))
INV_CSV = paths.OUT_TAB / "s1_inventory_2021_nov_2021-09-01_2021-12-01.csv"
OUTDIR_DEFAULT = paths.DATA_PROC / "s1_2021"
SLICE_PROPS = ["system:index", "system:time_start", "platform_number", "orbitProperties_pass", "relativeOrbitNumber_start", "instrumentMode", "transmitterReceiverPolarisation"]


def fname(date, pol, kind):
    return f"S1A_IW_D092_{date.replace('-', '')}_{pol}_{kind}.tif"


def versions():
    import rasterio, shapely
    v = {"python": _platform.python_version(), "numpy": np.__version__, "rasterio": rasterio.__version__, "shapely": shapely.__version__}
    try:
        import ee
        v["earthengine-api"] = getattr(ee, "__version__", "unknown")
    except Exception:                                                          # noqa: BLE001
        v["earthengine-api"] = "not installed"
    return v


# ------------------------------------------------------------------ Earth Engine (UNTESTED live)
def ee_slice_meta(ee, ids):
    col = ee.ImageCollection(CFG["collection"]).filter(ee.Filter.inList("system:index", ids))

    def meta(img):
        return ee.Feature(None, {"id": img.get("system:index"), "t": img.get("system:time_start"), "platform": img.get("platform_number"), "pass": img.get("orbitProperties_pass"),
                                 "rel_orbit": img.get("relativeOrbitNumber_start"), "mode": img.get("instrumentMode"), "bands": img.bandNames(), "pols": img.get("transmitterReceiverPolarisation")})
    return col, [f["properties"] for f in col.map(meta).getInfo()["features"]]


def pick(d, suffix):
    """Value for a reducer output named `suffix` or `<band>_<suffix>` (Earth Engine names combined-reducer outputs either way); None if absent."""
    return next((v for k, v in (d or {}).items() if k == suffix or k.endswith("_" + suffix)), None)


def ee_pol_products(ee, col, ids, pol, grid, aoi, cfg):
    """Server-side images for ONE polarisation. Returns dict of ee images/stat dicts (nothing downloaded here)."""
    crs = grid.crs; x0, y0 = grid.transform.c, grid.transform.f
    t10 = [10.0, 0, x0, 0, -10.0, y0]; t30 = [30.0, 0, x0, 0, -30.0, y0]
    gcp = col.filter(ee.Filter.listContains("transmitterReceiverPolarisation", pol))

    def per(img):
        s = ee.Image(img).select(pol).reproject(crs=crs, crsTransform=t10)                  # geometric only: nearest neighbour onto the 10 m UTM lattice (NOT smoothing)
        lin = ee.Image(10).pow(s.divide(10)).rename("lin")                                  # dB -> linear power; masks propagate (no fill)
        return lin.addBands(s.rename("db")).addBands(s.mask().rename("valid")).set("system:time_start", img.get("system:time_start"))
    pc = gcp.map(per)
    lin10 = pc.select("lin").mean().setDefaultProjection(crs, t10)                         # OVERLAP RULE: mean (commutative reducer) of VALID slices in linear power
    valid10 = pc.select("valid").max().setDefaultProjection(crs, t10)                      # valid in >= 1 slice
    db10_pointmean = pc.select("db").mean().setDefaultProjection(crs, t10)
    lin30 = lin10.reduceResolution(ee.Reducer.mean(), bestEffort=False, maxPixels=64).reproject(crs=crs, crsTransform=t30)   # exact 3x3 block mean of linear power
    vf30 = valid10.reduceResolution(ee.Reducer.mean(), bestEffort=False, maxPixels=64).reproject(crs=crs, crsTransform=t30)  # share of the 30 m cell with valid source pixels
    db30 = lin30.log10().multiply(10.0).updateMask(vf30.gte(cfg["min_valid_fraction"]))
    point30 = db10_pointmean.reproject(crs=crs, crsTransform=t30)                           # unfiltered point sample (comparison only)
    focal30 = db30.focalMedian(radius=cfg["resampling"]["focal_median_radius_m"], kernelType="circle", units="meters")   # comparison only (not the default)
    red = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True).combine(ee.Reducer.percentile([5, 50, 95]), sharedInputs=True).combine(ee.Reducer.count(), sharedInputs=True)

    def stats(img, t):
        return img.reduceRegion(reducer=red, geometry=aoi, crs=crs, crsTransform=t, maxPixels=1e9).getInfo()

    def resid(img):
        r = img.subtract(img.focalMean(radius=1, kernelType="square", units="pixels"))
        return r.reduceRegion(reducer=ee.Reducer.stdDev(), geometry=aoi, crs=crs, crsTransform=t30, maxPixels=1e9).getInfo()
    opts = {}
    for name, img in (("point_db", point30), ("linear_area_mean", db30), ("linear_area_mean_focal_median", focal30)):
        st = stats(img, t30); rs = resid(img)
        opts[name] = {"n": pick(st, "count"), "mean_db": pick(st, "mean"),
                      "std_db": pick(st, "stdDev"), "p05_db": pick(st, "p5"),
                      "p50_db": pick(st, "p50"), "p95_db": pick(st, "p95"),
                      "local_residual_std_db": next(iter(rs.values()), None)}
    src = lin10.reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, crs=crs, crsTransform=t10, maxPixels=1e10).getInfo()
    srcv = valid10.reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, crs=crs, crsTransform=t10, maxPixels=1e10).getInfo()
    source = {"mean_linear": next(iter(src.values()), None), "valid_share_10m": next(iter(srcv.values()), None), "n_slices_with_band": gcp.size().getInfo()}
    overlap = {"n_overlap_px": None}
    sl = sorted(ids)
    if len(sl) == 2:
        a, b = (ee.Image(col.filter(ee.Filter.eq("system:index", i)).first()).select(pol).reproject(crs=crs, crsTransform=t10) for i in sl)
        d = a.subtract(b)
        r1 = d.reduceRegion(reducer=ee.Reducer.count().combine(ee.Reducer.mean(), sharedInputs=True), geometry=aoi, crs=crs, crsTransform=t10, maxPixels=1e10).getInfo()
        r2 = d.abs().reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.percentile([95]), sharedInputs=True), geometry=aoi, crs=crs, crsTransform=t10, maxPixels=1e10).getInfo()
        overlap = {"n_overlap_px": pick(r1, "count"), "mean_diff_db": pick(r1, "mean"),
                   "mean_abs_diff_db": pick(r2, "mean"), "p95_abs_diff_db": pick(r2, "p95")}
    pack = ee.Image.cat([db30.unmask(cfg["nodata"]).rename(f"{pol}_dB"), vf30.unmask(0).rename(f"{pol}_validfrac")]).toFloat()   # sentinel -9999 for masked dB; 0 = true valid FRACTION
    return {"pack": pack, "options": opts, "source": source, "overlap": overlap}


def ee_download(ee, image, grid, nbands, max_bytes):
    import requests
    H, W = grid.shape; est = H * W * 4 * nbands
    if est > max_bytes: raise RuntimeError(f"estimated download {est} bytes exceeds max_download_bytes {max_bytes}: tile the request")
    req = {"crs": grid.crs, "crs_transform": [grid.transform.a, 0.0, grid.transform.c, 0.0, grid.transform.e, grid.transform.f], "dimensions": [int(W), int(H)], "format": "GEO_TIFF"}
    chirps.sanitize_request(req)                                              # the recorded copy; ee gets a different copy (it mutates its argument)
    def go():
        url = image.getDownloadURL(dict(req)); r = requests.get(url, timeout=600); r.raise_for_status(); return tif_bytes_from_download(r.content)
    return pp.download_with_retry(go, retries=3, sleep=5.0)


def read_pack(tif_bytes, grid, nbands):
    from rasterio.io import MemoryFile
    with MemoryFile(tif_bytes) as mf, mf.open() as ds:
        p = []
        if ds.count != nbands: p.append(f"{ds.count} bands != {nbands}")
        if tuple((ds.height, ds.width)) != tuple(grid.shape): p.append(f"shape {(ds.height, ds.width)} != master grid {grid.shape}")
        if str(ds.crs).upper().replace("EPSG:", "") != grid.crs.upper().replace("EPSG:", ""): p.append(f"CRS {ds.crs} != {grid.crs}")
        if any(abs(a - b) > 1e-6 for a, b in zip(tuple(ds.transform)[:6], tuple(grid.transform)[:6])): p.append(f"transform {tuple(ds.transform)[:6]} != master {tuple(grid.transform)[:6]}")
        if p: raise RuntimeError("export grid check FAILED: " + "; ".join(p))
        return [ds.read(i + 1).astype("float64") for i in range(nbands)]


def write_outputs(outdir, date, pol, db, vf, grid, cfg):
    """Final per-pol rasters. dB has the explicit sentinel where invalid; the validity mask is derived by the documented rule (never zero)."""
    from src.geospatial.grid import write_raster
    vm = pp.valid_mask(db, vf, cfg["min_valid_fraction"], cfg["nodata"])
    dbo = np.where(vm, db, np.nan)
    write_raster(outdir / fname(date, pol, "dB"), pp.to_nodata(dbo, cfg["nodata"]), grid, cfg["nodata"], f"{pol} backscatter dB (linear-power area mean, overlap=mean of valid slices)", "float32")
    write_raster(outdir / fname(date, pol, "validfrac"), vf.astype("float32"), grid, None, f"{pol} valid-source-pixel fraction per 30 m cell", "float32")
    write_raster(outdir / fname(date, pol, "valid"), vm.astype("uint8"), grid, None, f"{pol} validity mask (1 valid; fraction >= {cfg['min_valid_fraction']})", "uint8")
    return [fname(date, pol, k) for k in ("dB", "validfrac", "valid")]


def make_exporter(ee, ctx):
    grid, aoi_ee, outdir, cfg = ctx["grid"], ctx["aoi_ee"], ctx["outdir"], CFG

    def exporter(date):
        ids = ctx["plan"][date]
        col, scenes = ee_slice_meta(ee, ids)
        bad = pp.verify_scene_identity(date, ids, scenes, cfg["expected"])
        if bad: raise RuntimeError("scene identity check FAILED: " + "; ".join(bad))
        pplan = pp.pol_plan(scenes)
        files, opts, srcs, ovl, produced = [], {}, {}, {}, []
        for pol in pp.POLS:
            if not pplan[pol]["producible"]: continue                                # missing polarisation in some slice: reported, never filled
            res = ee_pol_products(ee, col, ids, pol, grid, aoi_ee, cfg)
            data = read_pack(ee_download(ee, res["pack"], grid, 2, cfg["qa"]["max_download_bytes"]), grid, 2)
            files += write_outputs(outdir, date, pol, data[0], data[1], grid, cfg); produced.append(pol)
            opts[pol], srcs[pol], ovl[pol] = res["options"], res["source"], res["overlap"]
        if not produced: raise RuntimeError("no polarisation producible for this date: " + json.dumps(pplan))
        md = {"date_utc": date, "source_scene_ids": sorted(ids), "scenes": scenes, "collection": cfg["collection"], "platform": cfg["expected"]["platform"], "pass": cfg["expected"]["pass"],
              "rel_orbit": cfg["expected"]["rel_orbit"], "pols_present": produced, "pol_plan": pplan, "overlap_rule": cfg["overlap_rule"], "resampling_default": cfg["resampling"]["default"],
              "resampling_detail": cfg["resampling"], "min_valid_fraction": cfg["min_valid_fraction"], "output_crs": grid.crs, "output_resolution_m": grid.res, "output_transform": list(grid.transform)[:6],
              "output_shape": list(grid.shape), "nodata_value": cfg["nodata"], "units": "dB (10*log10 of linear power); validfrac 0-1; valid 0/1", "ee_processing_claims": cfg["earth_engine_processing_claims"],
              "dem_note": "Terrain correction DEM per Earth Engine catalog page: SRTM 30 m (ASTER above 60 deg latitude). The exact DEM version used at ingestion is NOT exposed per scene and is not recorded here.",
              "speckle_note": "No additional speckle filter in the default. The 10 m -> 30 m linear block mean is itself spatial averaging (multilooking, irreversible); comparison options are in `speckle_options`.",
              "speckle_options": opts, "source_stats_10m": srcs, "overlap_diagnostics": ovl, "run_signature": ctx["sigs"][date], "software": versions(), "aoi_fingerprint": ctx["fp"],
              "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": files, "status": "EXPORTED (QA pending)"}
        miss = pp.metadata_problems(md)
        if miss: raise RuntimeError(f"metadata incomplete: {miss}")
        mname = f"S1A_IW_D092_{date.replace('-', '')}_meta.json"
        (outdir / mname).write_text(json.dumps(chirps.json_safe(md), indent=1), encoding="utf-8")
        return {"files": files + [mname], "meta_file": mname}
    return exporter


# ------------------------------------------------------------------ QA / report (offline)
def read_tif(p):
    import rasterio
    with rasterio.open(p) as ds:
        return ds.read(1).astype("float64"), {"crs": str(ds.crs), "transform": tuple(ds.transform)[:6], "shape": (ds.height, ds.width)}


def qa_date(date, outdir, grid, inside, aoi_wgs, fps, rec):
    """QA rows (one per pol) for a date. No date is QA_PASS merely because files exist."""
    rows = []
    mpath = Path(outdir) / (rec.get("meta_file") or "")
    md = json.loads(mpath.read_text(encoding="utf-8")) if rec.get("meta_file") and mpath.exists() else {}
    miss = pp.metadata_problems(md) if md else ["metadata file missing"]
    expected = {"crs": grid.crs, "transform": tuple(grid.transform)[:6], "shape": grid.shape}
    ids = md.get("source_scene_ids", [])
    zone = pp.seam_zone(grid, fps[ids[0]], fps[ids[1]], aoi_wgs, CFG["qa"]["seam_width_m"]) if len(ids) == 2 and all(i in fps for i in ids) else np.zeros(grid.shape, bool)
    for pol in pp.POLS:
        row = {"date_utc": date, "pol": pol, "status": "NOT_PRODUCED", "failures": "", "run_signature": rec.get("signature"), "metadata_missing": ";".join(miss)}
        if pol not in md.get("pols_present", []):
            row["failures"] = "polarisation not producible: " + json.dumps(md.get("pol_plan", {}).get(pol)) if md else "no metadata"
            rows.append(row); continue
        try:
            db, gi = read_tif(Path(outdir) / fname(date, pol, "dB")); vf, gvf = read_tif(Path(outdir) / fname(date, pol, "validfrac")); vmask, _ = read_tif(Path(outdir) / fname(date, pol, "valid"))
        except Exception as e:                                                # noqa: BLE001
            row.update(status="QA_FAIL", failures=f"cannot read product: {e}"); rows.append(row); continue
        src = (md.get("source_stats_10m") or {}).get(pol)
        m, f = pp.qa_product(db, vf, gi, expected, inside, CFG["qa"], CFG["min_valid_fraction"], src, CFG["nodata"])
        if m.get("checked"):
            if not np.array_equal(vmask.astype(bool), pp.valid_mask(db, vf, CFG["min_valid_fraction"], CFG["nodata"])): f.append("stored validity mask differs from the documented rule")
            vm = pp.valid_mask(db, vf, CFG["min_valid_fraction"], CFG["nodata"])
            sd = pp.seam_diag(db, vm, zone, inside, CFG["qa"]["seam_flag_db"]); m.update({f"seam_{k}": v for k, v in sd.items()})
            ov = (md.get("overlap_diagnostics") or {}).get(pol) or {}; m.update({f"overlap_{k}": v for k, v in ov.items()})
            o = (md.get("speckle_options") or {}).get(pol) or {}
            for name, st in o.items(): m[f"opt_{name}_mean_db"] = st.get("mean_db"); m[f"opt_{name}_resid_std_db"] = st.get("local_residual_std_db")
            try:
                pp.preview_png(paths.OUT_FIG / f"s1_2021_preview_{date}_{pol}.png", db, vm, f"{date} {pol} dB (30 m, {md.get('resampling_default')}) - preprocessing preview, not a flood map", extent=(grid.extent[0], grid.extent[1], grid.extent[2], grid.extent[3]))
                m["preview"] = f"outputs/figures/s1_2021_preview_{date}_{pol}.png"
            except Exception as e:                                            # noqa: BLE001
                f.append(f"preview failed: {e}")
        if miss: f.append(f"metadata incomplete: {miss}")
        row.update(m); row["status"] = "QA_PASS" if not f else "QA_FAIL"; row["failures"] = "; ".join(f); rows.append(row)
    return rows


def write_report(path, qa_df, plan_all, state, grid, aoi_meta, fp, sigs, ran_ee, requested, overall):
    """Two separate levels: (1) QA of the dates requested in THIS run, (2) overall M4C status over ALL configured dates. Overall COMPLETE requires every
    configured date to have VV and VH QA_PASS with the current run signature; a partial run can never report completion."""
    nreq = len(requested); req_pass = [d for d in requested if overall["per_date"].get(d) == "QA_PASS"]
    L = ["# Sentinel-1 2021 date-level preprocessing report (M4C)", "",
         "PREPROCESSING ONLY. No flood classification, no flood extent, no baseline designation (4 Nov 2021 is NOT a dry reference), no validation, no ML.", "",
         "## Status", "",
         f"- **This run - dates requested ({nreq}): {', '.join(requested)}.** QA_PASS for VV and VH: **{len(req_pass)} of {nreq}**. QA_PASS = technical checks only (grid, valid share, NoData, extremes, source-vs-output power, metadata).",
         f"- **Overall M4C - all {overall['n_total']} configured dates: {overall['n_pass']} of {overall['n_total']} QA_PASS (VV and VH).** Overall status: **{'COMPLETE' if overall['complete'] else 'NOT COMPLETE'}**"
         + ("." if overall["complete"] else f" - not yet QA_PASS: {', '.join(d for d, v in overall['per_date'].items() if v != 'QA_PASS')}."),
         "- COMPLETE requires all configured dates to have both VV and VH QA_PASS with the current configuration signature; rows from an older configuration, failed, stale or not-yet-run dates do not count.",
         f"- Output grid: {grid.crs}, {grid.res} m, shape {list(grid.shape)}, transform {[round(x, 6) for x in list(grid.transform)[:6]]} (project master grid). AOI: {aoi_meta.get('kind')} - PROVISIONAL OSM boundary, not the official GCC boundary; fingerprint `{fp[:12]}`.",
         f"- Earth Engine run in this invocation: {'yes' if ran_ee else 'NO (offline QA of existing products)'}. Collection `{CFG['collection']}`; configuration `config/s1_preprocess.json` (version {CFG['version']}).",
         "- Metadata JSON `status` is updated to the date's final QA state after QA (the earlier export state is kept as `export_status`); the QA CSV `date_status`, this report and the run state show the same state.", "",
         "### Overall state by date", "", "| date | state |", "|---|---|"] + [f"| {d} | {v} |" for d, v in overall["per_date"].items()] + [""]
    L += [
         "## Processing chain: what is done where", "",
         "| step | applied by | notes |", "|---|---|---|",
         "| thermal noise removal | Earth Engine ingestion (catalog page) | not repeated |", "| radiometric calibration (sigma0) | Earth Engine ingestion | not repeated |",
         "| terrain correction | Earth Engine ingestion: SRTM 30 m (ASTER > 60 deg lat) | ellipsoid-based; DEM version per scene not exposed |",
         "| dB conversion | Earth Engine ingestion | values are dB; this workflow converts to linear power only to average, then back |",
         "| border-noise removal | NOT confirmed from the catalog page | checked empirically: edge/seam diagnostics + previews; no extra masking applied |",
         "| radiometric terrain flattening | **not applied, not claimed** | slope/aspect effects remain in backscatter |", "| incidence-angle normalisation | not applied | `angle` band is ~20 km pixels (approximate); documented, not used |",
         "| geometric resampling | this workflow | slice -> UTM 10 m lattice aligned to the master grid, nearest neighbour (geometric only) |",
         "| overlap rule | this workflow | linear-power mean of the slices valid at a pixel (order independent); one valid slice -> that slice; none -> NoData |",
         "| 10 m -> 30 m | this workflow | exact 3x3 block mean of linear power, then dB (default `linear_area_mean`); this is spatial averaging (multilooking) and irreversible |",
         "| additional speckle filter | none in the default | `point_db` and `linear_area_mean_focal_median` are compared only |",
         "| NoData | explicit sentinel -9999 for dB; `validfrac` and `valid` rasters; never 0 | cell valid if >= 50 % of its source pixels are valid |",
         "| native 10 m rasters | not exported (size) | native information kept as scene IDs, source 10 m statistics and diagnostics in the metadata JSON |", ""]
    L += ["## QA table (see outputs/tables/s1_2021_preprocessing_qa.csv)", "", "| date | pol | status | AOI valid % | NoData cells in AOI | extreme low / high | mean dB | power ratio out/source | overlap px | seam zone-rest dB | failures |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    g = lambda r, k: (lambda v: "n/a" if v is None or (isinstance(v, float) and v != v) else (round(v, 4) if isinstance(v, float) else v))(getattr(r, k, None))   # noqa: E731
    for r in qa_df.itertuples():
        L.append(f"| {r.date_utc} | {r.pol} | {r.status} | {g(r, 'aoi_valid_pct')} | {g(r, 'nodata_cells_in_aoi')} | {g(r, 'extreme_low_cells')} / {g(r, 'extreme_high_cells')} | {g(r, 'mean_db')} | {g(r, 'power_ratio_out_over_source')} | {g(r, 'overlap_n_overlap_px')} | {g(r, 'seam_zone_minus_rest_db')} | {r.failures} |")
    L += ["", "## 2021-11-16 (confirmed separately)", ""]
    s = qa_df[qa_df.date_utc == "2021-11-16"]
    L += ["- NOT PRODUCED / not yet run for 2021-11-16."] if s.empty or (s.status == "NOT_PRODUCED").all() else [f"- {r.pol}: **{r.status}**; AOI valid {g(r, 'aoi_valid_pct')} %; overlap px {g(r, 'overlap_n_overlap_px')}; seam zone-minus-rest {g(r, 'seam_zone_minus_rest_db')} dB; {r.failures or 'no failures recorded'}" for r in s.itertuples()]
    L += ["", "## Speckle / resampling option comparison (server-side AOI statistics at 30 m; NOT a ranking)", "",
          "| date | pol | option | mean dB | local residual std dB (lower = smoother) |", "|---|---|---|---|---|"]
    for r in qa_df.itertuples():
        for name in CFG["resampling"]["comparison_options"]:
            if getattr(r, f"opt_{name}_mean_db", None) is not None:
                L.append(f"| {r.date_utc} | {r.pol} | {name} | {g(r, f'opt_{name}_mean_db')} | {g(r, f'opt_{name}_resid_std_db')} |")
    L += ["", "**Default selection (rationale, not a measured optimum):** `linear_area_mean` is the least-processing way to move intensity to a coarser grid without aliasing or an extra filter. The focal median is an additional, irreversible smoothing and is not the default; `point_db` discards 8 of 9 source pixels. The comparison above shows how the options differ; it does not show which is more accurate for any later use.", "",
          "## Run state", "", "| date | state | signature | error |", "|---|---|---|---|"]
    for d in plan_all:
        rec = state.get(d, {}); L.append(f"| {d} | {rec.get('status', 'NOT RUN')} | `{sigs.get(d)}` | {rec.get('error') or ''} |")
    L += ["", "## Limitations", "", "- Backscatter is not terrain-flattened; steep or tilted surfaces and urban double-bounce affect values. The 30 m product does not carry 30 m of independent SAR information: it is an average of 10 m pixels.",
          "- Seam diagnostics are descriptive (zone mean vs rest of AOI, slice difference in overlap). A difference may be real land cover; inspect the previews.",
          "- Earth Engine steps were not executed by the developer of this module; only your run produces real products. Synthetic unit tests do not validate real-data behaviour.", ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")
    return overall["complete"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*"); ap.add_argument("--all", action="store_true"); ap.add_argument("--plan-only", action="store_true"); ap.add_argument("--qa-only", action="store_true")
    ap.add_argument("--force-stale", action="store_true"); ap.add_argument("--outdir", default=None)
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("S1PP"); paths.ensure_dirs()
    outdir = Path(a.outdir) if a.outdir else OUTDIR_DEFAULT; outdir.mkdir(parents=True, exist_ok=True)
    dates = CFG["dates"] if a.all else (a.dates or [CFG["first_live_date"]])
    bad = [d for d in dates if d not in CFG["dates"]]
    if bad: print("STOP: dates not in the verified list:", bad); return
    cov = pd.read_csv(paths.ROOT / CFG["coverage_csv"]); cov = cov.where(pd.notnull(cov), None).to_dict("records")
    plan_all = pp.plan_from_coverage(cov, CFG["dates"]); plan = {d: plan_all[d] for d in dates}
    wgs, _, aoi_meta = load_study_area(); aoi_geom = wgs.unary_union; grid = master_grid()
    fp_full, _ = inv.query_fingerprint(aoi_geom); fp = fp_full
    params = {k: CFG[k] for k in ("overlap_rule", "resampling", "min_valid_fraction", "nodata", "expected")}
    sigs_all = {d: pp.run_signature(d, plan_all[d], params, grid, fp[:12], CFG["collection"]) for d in CFG["dates"]}; sigs = {d: sigs_all[d] for d in dates}
    log.info("AOI fingerprint %s; grid %s %s m %s", fp[:12], grid.crs, grid.res, list(grid.shape))
    if a.plan_only:
        for d in dates: print(d, plan[d], sigs[d])
        print("grid:", grid.crs, grid.res, list(grid.shape), "AOI fingerprint", fp[:12]); return
    state_path = outdir / "preprocess_state.json"; ran_ee = False
    if not a.qa_only:
        try:
            import ee
            from src.flood_detection import gee_sentinel1 as g1
            g1.init_ee(load_settings()["gee"].get("project") or None)
            aoi_ee = ee.Geometry(aoi_geom.__geo_interface__, proj="EPSG:4326", geodesic=False); ran_ee = True
        except Exception as e:                                                # noqa: BLE001
            msg = f"Earth Engine NOT available: {str(e)[:250]}"; log.error(msg); status.record("S1PP", status.BLOCKED, msg, seconds=time.time() - t0); print(msg); return
        res = pp.run_dates(dates, sigs, make_exporter(ee, {"grid": grid, "aoi_ee": aoi_ee, "outdir": outdir, "plan": plan, "sigs": sigs, "fp": fp[:12]}), outdir, state_path, a.force_stale)
        for d, r in res.items(): log.info("%s -> %s", d, r); print(d, r)
    state = pp.load_state(state_path)
    inv_df = pd.read_csv(INV_CSV) if INV_CSV.exists() else None
    fps = {r["id"]: dl.footprint_geom(r["footprint"]) for r in inv_df.to_dict("records")} if inv_df is not None and "footprint" in inv_df.columns else {}
    import geopandas as gpd
    aoi_utm = gpd.GeoSeries([aoi_geom], crs=4326).to_crs(grid.crs).iloc[0]
    from src.geospatial.grid import inside_mask
    inside = inside_mask(grid, [aoi_utm])
    rows = []
    for d in dates:
        rec = state.get(d, {})
        if rec.get("status") in ("EXPORTED", "QA_PASS", "QA_FAIL") and rec.get("signature") == sigs[d]:
            rows += qa_date(d, outdir, grid, inside, aoi_geom, fps, rec)
        else:
            rows += [{"date_utc": d, "pol": p, "status": rec.get("status", "NOT_RUN") if rec.get("signature", sigs[d]) == sigs[d] else "STALE", "failures": rec.get("error") or ("signature changed; use --force-stale" if rec else "not run")} for p in pp.POLS]
    qa_csv = paths.OUT_TAB / "s1_2021_preprocessing_qa.csv"
    old_rows = pd.read_csv(qa_csv).astype(object).where(lambda x: x.notna(), None).to_dict("records") if qa_csv.exists() else []
    merged = pp.merge_qa(old_rows, rows)                                       # rows of dates not in this run are kept
    overall = pp.overall_status(merged, CFG["dates"], sigs_all)
    qa_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for d in dates:                                                            # reconcile metadata + run state with the final QA state of this run's dates
        prow = [r for r in rows if r["date_utc"] == d]; dstate = pp.date_status(prow); rec = state.get(d)
        if rec and rec.get("status") in ("EXPORTED", "QA_PASS", "QA_FAIL") and rec.get("signature") == sigs[d]:
            if rec.get("meta_file") and (outdir / rec["meta_file"]).exists():
                rec["files"][rec["meta_file"]] = pp.finalize_metadata(outdir / rec["meta_file"], dstate, prow, qa_utc)   # metadata only; rasters untouched; sha refreshed
            rec["status"] = dstate if dstate in ("QA_PASS", "QA_FAIL") else rec["status"]
    for r in merged: r["date_status"] = overall["per_date"].get(r["date_utc"])
    pp.save_state(state_path, state)
    qa_df = pd.DataFrame(merged); qa_df.to_csv(qa_csv, index=False)
    complete = write_report(paths.OUT_REP / "s1_2021_preprocessing_report.md", qa_df, plan_all, state, grid, aoi_meta, fp, sigs_all, ran_ee, dates, overall)
    st_ = status.COMPLETED if overall["complete"] else status.PARTIAL
    status.record("S1PP", st_, f"overall M4C {overall['n_pass']} of {overall['n_total']} configured dates QA_PASS (VV and VH): {'COMPLETE' if overall['complete'] else 'NOT COMPLETE'}; this run requested {len(dates)} date(s); Earth Engine run: {ran_ee}",
                  files=[paths.rel(qa_csv), "outputs/reports/s1_2021_preprocessing_report.md"], seconds=time.time() - t0)
    req_pass = sum(1 for d in dates if overall["per_date"].get(d) == "QA_PASS")
    print(f"this run: {req_pass} of {len(dates)} requested dates QA_PASS (VV+VH); overall M4C: {overall['n_pass']} of {overall['n_total']} -> {'COMPLETE' if overall['complete'] else 'NOT COMPLETE'}; report: outputs/reports/s1_2021_preprocessing_report.md")


if __name__ == "__main__":
    main()
