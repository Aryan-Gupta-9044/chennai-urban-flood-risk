#!/usr/bin/env python
"""Sentinel-1 2021 per-date DARK-BACKSCATTER (water/flood CANDIDATE) review product v1 (S1WC-1). READ-ONLY on all inputs; additive; new versioned output directory.

NOT a flood extent, NOT validated, NOT independent ground truth, no accuracy/precision/recall/F1/IoU. Each acquisition date is classified separately and never merged into an event map. A dark pixel is
not automatically water or flood; unknown/invalid pixels keep their own class codes and are never reported as 'not flooded'. No Earth Engine / ASF / Copernicus; no resampling or reprojection of any
input (every raster must already be on the master grid, else the run STOPS). Nothing existing is overwritten; status.json is not touched.
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\s1_water_candidates_review.py
  .\\.venv\\Scripts\\python scripts\\s1_water_candidates_review.py --outdir outputs\\s1_water_candidates_review_v1 --no-rainfall
  (--allow-missing-metadata only if the per-date *_meta.json files are absent; the manifest then records that QA_PASS/AOI-fingerprint checks could not be made)"""
import argparse
import json
import platform as _platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.utils import paths
from src.geospatial import study_area as _sa
from src.geospatial.study_area import load_study_area, master_grid
from src.utils import config as _uconfig
from src.flood_detection import s1_persistence as sp, s1_water_candidates as wc

POLS = ("VV", "VH")
STEM = "s1_water_candidates"
CFG_LABEL = "configuration config/s1_water_candidates.json"
OUT_DEFAULT = "outputs/s1_water_candidates_review_v1"
PROTECTED_PREFIXES = ("s1_2021_persistence", "chirps_2021")


def fname(date, pol, kind): return f"S1A_IW_D092_{date.replace('-', '')}_{pol}_{kind}.tif"


def meta_name(date): return f"S1A_IW_D092_{date.replace('-', '')}_meta.json"


def parse_dates(dates):
    """Strict ISO YYYY-MM-DD, real calendar dates, no duplicates, returned ascending. Raises ValueError otherwise."""
    out = []
    for d in dates:
        s = str(d)
        if len(s) != 10 or s[4] != "-" or s[7] != "-": raise ValueError(f"date {s!r} is not strict YYYY-MM-DD")
        datetime.strptime(s, "%Y-%m-%d"); out.append(s)
    if len(set(out)) != len(out): raise ValueError("duplicate dates")
    if not out: raise ValueError("no dates")
    return sorted(out)


def planned_outputs(outdir, dates):
    o = Path(outdir); t, f, r, ra = o / "tables", o / "figures", o / "reports", o / "rasters"
    n = {"class_counts": t / f"{STEM}_class_counts_per_date.csv", "sensitivity": t / f"{STEM}_threshold_sensitivity.csv", "shift": t / f"{STEM}_radiometric_shift.csv", "terrain": t / f"{STEM}_terrain_context.csv",
         "input_qa": t / f"{STEM}_input_qa.csv", "rain_join": t / f"{STEM}_rainfall_join.csv", "manifest": r / f"{STEM}_manifest.json", "report": r / f"{STEM}_report.md",
         "fig_multiples": f / f"{STEM}_class_by_date_small_multiples.png", "fig_shares": f / f"{STEM}_class_share_by_date.png",
         "ras_n_valid": ra / f"{STEM}_n_valid_dates.tif", "ras_n_dark": ra / f"{STEM}_n_dark_dates.tif", "ras_persistent": ra / f"{STEM}_persistent_dark_mask.tif", "ras_transient_count": ra / f"{STEM}_transient_candidate_date_count.tif"}
    for d in dates: n[f"ras_class_{d}"] = ra / f"{STEM}_class_{d}.tif"
    return n


def tif_info(p):
    import rasterio
    with rasterio.open(p) as ds: return {"shape": (ds.height, ds.width), "crs": str(ds.crs), "transform": tuple(ds.transform)[:6], "count": ds.count, "dtype": ds.dtypes[0], "nodata": ds.nodata}


def read_tif(p):
    import rasterio
    with rasterio.open(p) as ds: return ds.read(1)


def versions():
    import geopandas, matplotlib, rasterio, scipy
    return {"python": _platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "rasterio": rasterio.__version__, "geopandas": geopandas.__version__, "scipy": scipy.__version__, "matplotlib": matplotlib.__version__}


def overlap_dirs(a, b):
    a, b = Path(a).resolve(), Path(b).resolve(); return a == b or a in b.parents or b in a.parents


def preflight():
    """Hash configuration, both AOI GeoJSON files, optional study_area_meta.json and settings.json BEFORE any is parsed/loaded. Returns (stops, pre)."""
    req = {CFG_LABEL: paths.CONFIG / "s1_water_candidates.json", "AOI study_area_wgs84.geojson": _sa.WGS, "AOI study_area_utm44n.geojson": _sa.UTM, "settings config/settings.json": _uconfig.CONFIG / "settings.json"}
    missing = [f"MISSING required input: {k}: {v}" for k, v in req.items() if not Path(v).exists()]
    if missing: return missing, None
    src = {k: Path(v) for k, v in req.items()}; absent = []
    if Path(_sa.META).exists(): src["AOI study_area_meta.json (optional)"] = Path(_sa.META)
    else: absent.append(str(_sa.META))
    return [], {"paths": src, "sha256": {k: sp.sha256_file(v) for k, v in src.items()}, "absent_optional": absent}


def run(indir, outdir, cfg, grid, aoi_geom_wgs, root, rainfall_csv=None, dates=None, shared_dirs=(), pre=None, allow_missing_metadata=False):
    """Returns (rc, info). rc 0 done; 2 STOP before any output; 3 an input hash changed."""
    t0 = time.time(); root = Path(root); indir, outdir = Path(indir).resolve(), Path(outdir).resolve(); stops = []
    try: dates = parse_dates(dates or cfg["dates"])
    except ValueError as e: return 2, {"stops": [f"invalid dates: {e}"]}
    if overlap_dirs(indir, outdir): return 2, {"stops": [f"output directory {outdir} overlaps the input directory {indir}"]}
    for sd in shared_dirs:
        if overlap_dirs(outdir, sd): return 2, {"stops": [f"output directory {outdir} overlaps the shared existing outputs folder {Path(sd).resolve()} (equal, inside, or ancestor); use a dedicated new directory"]}
    if any(outdir.name.startswith(p) or any(par.name.startswith(p) for par in outdir.parents) for p in PROTECTED_PREFIXES): return 2, {"stops": [f"output directory {outdir} is inside a protected existing output family {PROTECTED_PREFIXES}"]}
    outs = planned_outputs(outdir, dates); existing = [str(p) for p in outs.values() if p.exists()]
    if existing: return 2, {"stops": ["existing outputs would be overwritten; nothing was written. Existing: " + "; ".join(existing[:6]) + (" ..." if len(existing) > 6 else "")]}
    refs = {k: (Path(v) if Path(v).is_absolute() else root / v) for k, v in cfg["reference_layers"].items()}
    need = {}
    for d in dates:
        for pol in POLS:
            for k in ("dB", "validfrac", "valid"): need[f"{d} {pol} {k}"] = indir / fname(d, pol, k)
    miss = {k: str(v) for k, v in need.items() if not v.exists()}
    meta_present = {d: (indir / meta_name(d)).exists() for d in dates}
    if not all(meta_present.values()) and not allow_missing_metadata: miss.update({f"{d} metadata": str(indir / meta_name(d)) for d in dates if not meta_present[d]})
    for k in cfg.get("required_reference_layers", ["slope_deg"]):
        if not refs[k].exists(): miss[f"required reference layer {k}"] = str(refs[k])
    if miss: return 2, {"stops": [f"MISSING required input: {k}: {v}" for k, v in miss.items()]}
    # ---- hash everything BEFORE any content is parsed
    in_files = dict(need); in_files.update({f"{d} metadata": indir / meta_name(d) for d in dates if meta_present[d]}); ref_present = {k: v for k, v in refs.items() if v.exists()}
    in_files.update({f"reference {k}": v for k, v in ref_present.items()})
    if rainfall_csv is not None and Path(rainfall_csv).exists(): in_files["rainfall csv"] = Path(rainfall_csv)
    if pre: in_files.update(pre["paths"])
    in_files = {k: Path(v) for k, v in in_files.items()}
    before = {**(pre["sha256"] if pre else {}), **{k: sp.sha256_file(p) for k, p in in_files.items() if not (pre and k in pre["sha256"])}}
    # ---- metadata, grids, dtypes
    from src.geospatial.grid import inside_mask
    import geopandas as gpd
    from src.flood_detection import s1_inventory as inv
    fp_run = inv.query_fingerprint(aoi_geom_wgs)[0][:12]; fps = {}
    for d in dates:
        if not meta_present[d]: continue
        md = json.loads((indir / meta_name(d)).read_text(encoding="utf-8")); fps[d] = md.get("aoi_fingerprint")
        if md.get("status") != "QA_PASS": stops.append(f"{d}: metadata status {md.get('status')!r} is not QA_PASS")
        if md.get("date_utc") != d: stops.append(f"{d}: metadata date_utc {md.get('date_utc')!r} differs")
    if fps and len(set(fps.values())) != 1: stops.append(f"AOI fingerprints disagree across metadata: {fps}")
    elif fps and next(iter(fps.values())) != fp_run: stops.append("AOI fingerprint in the metadata != fingerprint of the AOI loaded for this run")
    infos = {}
    for k, v in {**need, **{f"reference {kk}": vv for kk, vv in ref_present.items()}}.items():
        i = tif_info(v); infos[k] = i; pr = sp.grid_problems(i, grid); kind = k.split()[-1]
        if kind == "dB" and (i["dtype"] != "float32" or i["nodata"] != cfg["nodata"]): pr.append(f"dB raster must be float32 with NoData {cfg['nodata']} (found {i['dtype']}, {i['nodata']})")
        if kind == "validfrac" and i["dtype"] != "float32": pr.append(f"validfrac must be float32 (found {i['dtype']})")
        if kind == "valid" and i["dtype"] != "uint8": pr.append(f"valid must be uint8 (found {i['dtype']})")
        stops += [f"{k}: {x} (no resampling/reprojection is performed)" for x in pr]
    stops += sp.cross_grid_problems({k: v for k, v in infos.items() if not k.startswith("reference")})
    if stops: return 2, {"stops": stops}
    rain_df, rain_info = (None, {"skipped_reason": "rainfall join not requested"}) if rainfall_csv is None else sp.read_rainfall(rainfall_csv, dates)
    P = cfg["params"]; inside = inside_mask(grid, [gpd.GeoSeries([aoi_geom_wgs], crs=4326).to_crs(grid.crs).iloc[0]]); n_aoi = int(inside.sum()); nd = cfg["nodata"]
    vv, vh, vboth, mism, qa_rows = {}, {}, {}, {}, []
    for d in dates:
        vp = {}
        for pol in POLS:
            a = read_tif(indir / fname(d, pol, "dB")).astype("float64"); vf = read_tif(indir / fname(d, pol, "validfrac")).astype("float64"); fl = read_tif(indir / fname(d, pol, "valid"))
            v = wc.valid_pol(a, vf, fl, P["min_valid_fraction"], nd); vp[pol] = v
            v_rule = sp.valid_cells(a, vf, np.ones(grid.shape, bool), P["min_valid_fraction"], nd); mism[f"{d} {pol}"] = int((v_rule != (fl == 1)).sum())
            (vv if pol == "VV" else vh)[d] = np.where(v, a, np.nan)
        vboth[d] = vp["VV"] & vp["VH"]
        qa_rows.append({"date_utc": d, "aoi_cells": n_aoi, "valid_vv_pct_of_aoi": round(100 * (vp["VV"] & inside).sum() / n_aoi, 3), "valid_vh_pct_of_aoi": round(100 * (vp["VH"] & inside).sum() / n_aoi, 3),
                        "valid_both_pct_of_aoi": round(100 * (vboth[d] & inside).sum() / n_aoi, 3), "invalid_inside_aoi_cells": int((inside & ~vboth[d]).sum()), "metadata_present": meta_present[d]})
    slope = read_tif(refs["slope_deg"]).astype("float64")
    layers = {k: read_tif(v).astype("float64") for k, v in ref_present.items() if k in ("dem_elevation_m", "slope_deg", "twi", "flow_accumulation")}
    drain = read_tif(refs["drainage_network"]) if "drainage_network" in ref_present else None
    after = {k: sp.sha256_file(p) for k, p in in_files.items()}; changed = [k for k in before if before[k] != after[k]]
    if changed: return 3, {"stops": [f"INPUT CHANGED during the run: {changed}"]}
    # ---- classify
    dark = {d: wc.dark_mask(vv[d], vh[d], P["vv_dark_db"], P["vh_dark_db"], vboth[d] & inside) for d in dates}
    vonly = {d: wc.vv_only_dark(vv[d], vh[d], P["vv_dark_db"], P["vh_dark_db"], vboth[d] & inside) for d in dates}
    vstack = np.stack([vboth[d] & inside for d in dates]); dstack = np.stack([dark[d] for d in dates])
    n_dark, n_valid, persistent, assess = wc.persistence(dstack, vstack, P["min_valid_dates"], P["persistent_min_dark_dates"])
    cls = {d: wc.classify_date(vboth[d] & inside, dark[d], vonly[d], persistent, assess, slope, inside, P["max_slope_deg"], P["min_cluster_cells"]) for d in dates}
    area = abs(grid.transform.a * grid.transform.e) / 1e6
    cc_rows = []
    for d in dates: cc_rows += [{"date_utc": d, **r} for r in wc.class_counts(cls[d], area, n_aoi)]
    sens = []; [sens.extend(wc.sensitivity_rows(d, vv[d], vh[d], vboth[d] & inside, n_aoi)) for d in dates]
    shift = wc.radiometric_shift(dates, np.stack([vv[d] for d in dates]), np.stack([vh[d] for d in dates]), vstack)
    cstack = np.stack([cls[d] for d in dates]); tcount = wc.date_count(cstack, wc.TRANSIENT, inside)
    tctx = wc.terrain_context(layers, _union_class(cstack, inside), inside, drain)
    # ---- write (new directory only)
    for p in outs.values(): p.parent.mkdir(parents=True, exist_ok=True)
    cc = pd.DataFrame(cc_rows); cc.to_csv(outs["class_counts"], index=False); pd.DataFrame(sens).to_csv(outs["sensitivity"], index=False); pd.DataFrame(shift).to_csv(outs["shift"], index=False)
    pd.DataFrame(tctx).to_csv(outs["terrain"], index=False); pd.DataFrame(qa_rows).to_csv(outs["input_qa"], index=False)
    rain_out = None
    if rain_df is not None:
        tr = {d: int((cls[d] == wc.TRANSIENT).sum()) for d in dates}; rain_out = rain_df.assign(transient_candidate_cells=[tr[d] for d in rain_df["s1_date"]], transient_candidate_pct_of_aoi=[round(100 * tr[d] / n_aoi, 4) for d in rain_df["s1_date"]])
        rain_out.to_csv(outs["rain_join"], index=False)
    from src.geospatial.grid import write_raster
    for d in dates: write_raster(outs[f"ras_class_{d}"], cls[d], grid, 255, f"S1 dark-backscatter candidate class, acquisition {d} UTC (0 not dark,1 transient candidate,2 persistent dark,3 slope-excluded,4 small cluster,5 VV-only,6 persistence unassessable,7 slope unknown,254 invalid,255 outside AOI). NOT a flood map", "uint8")
    write_raster(outs["ras_n_valid"], np.where(inside, n_valid, 255).astype("uint8"), grid, 255, "valid dates per cell (VV and VH both valid), 255 outside AOI", "uint8")
    write_raster(outs["ras_n_dark"], np.where(inside, n_dark, 255).astype("uint8"), grid, 255, "dark dates per cell (dual-pol dark), 255 outside AOI", "uint8")
    write_raster(outs["ras_persistent"], np.where(inside, np.where(assess, persistent.astype("uint8"), 2), 255).astype("uint8"), grid, 255, "persistently dark: 1 yes, 0 no, 2 not assessable (<min valid dates), 255 outside AOI", "uint8")
    write_raster(outs["ras_transient_count"], tcount, grid, 255, "COUNT OF DATES (not an event map) on which the cell is a transient dark candidate, 255 outside AOI", "uint8")
    make_figures(outs, dates, cc, cls, inside, grid)
    after2 = {k: sp.sha256_file(p) for k, p in in_files.items()}; preserved = after2 == before
    info = {"fp_run": fp_run, "fps": fps, "n_aoi": n_aoi, "mism": mism, "rain_info": rain_info, "preserved": preserved, "outs": {k: str(v) for k, v in outs.items()}, "indir": str(indir), "outdir": str(outdir), "meta_present": meta_present,
            "ref_present": {k: str(v) for k, v in ref_present.items()}, "ref_absent": [k for k in refs if k not in ref_present]}
    outs["report"].write_text(build_report(info, dates, cc, pd.DataFrame(shift), pd.DataFrame(qa_rows), pd.DataFrame(sens), cfg, rain_out), encoding="utf-8")
    man = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - t0, 1), "script": "scripts/s1_water_candidates_review.py", "version": cfg["version"], "dates": dates,
           "date_meaning": cfg["date_meaning"], "parameters": P, "aoi_fingerprint": {"metadata": fps, "loaded_aoi": fp_run, "aoi_cells": n_aoi}, "metadata_present": meta_present,
           "reference_layers_used": info["ref_present"], "reference_layers_absent": info["ref_absent"], "input_sha256_before": before, "input_sha256_after_all_outputs": after2, "input_hashes_unchanged": preserved,
           "valid_tif_vs_rule_mismatch_cells": mism, "software": versions(), "status_json_modified": False, "claims": "provisional S1-derived dark-backscatter candidates; not a flood extent; not validated; no accuracy metric",
           "outputs": {k: str(v) for k, v in outs.items() if k != "manifest"}}
    outs["manifest"].write_text(json.dumps(man, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return (0 if preserved else 3), info


def _union_class(cstack, inside):
    """Class raster used for the terrain-context table: TRANSIENT where a cell is a transient candidate on any date; otherwise the highest-priority valid class seen (not-dark if any date valid not dark); outside/invalid kept."""
    out = np.full(cstack.shape[1:], wc.OUTSIDE, "uint8"); out[inside] = wc.INVALID
    anyv = np.isin(cstack, (wc.NOT_DARK, wc.TRANSIENT, wc.PERSISTENT, wc.TERRAIN, wc.SMALL, wc.VV_ONLY, wc.UNASSESSED, wc.TERRAIN_UNKNOWN)).any(0)
    out[inside & anyv] = wc.NOT_DARK; out[(cstack == wc.TRANSIENT).any(0)] = wc.TRANSIENT; return out


def make_figures(outs, dates, cc, cls, inside, grid):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    cols = {wc.NOT_DARK: "#eeeeee", wc.TRANSIENT: "#2166ac", wc.PERSISTENT: "#084081", wc.TERRAIN: "#bf812d", wc.SMALL: "#9ecae1", wc.VV_ONLY: "#d9f0d3", wc.UNASSESSED: "#fdae61", wc.TERRAIN_UNKNOWN: "#f4a582", wc.INVALID: "#d73027"}
    short = {wc.NOT_DARK: "valid, not dark", wc.TRANSIENT: "transient dark candidate", wc.PERSISTENT: "persistently dark (excluded)", wc.TERRAIN: "slope-excluded", wc.SMALL: "small cluster (excluded)", wc.VV_ONLY: "VV-only dark", wc.UNASSESSED: "persistence unassessable", wc.TERRAIN_UNKNOWN: "slope unknown", wc.INVALID: "invalid/unknown"}
    codes = list(cols); cm = ListedColormap([cols[c] for c in codes]); idx = {c: i for i, c in enumerate(codes)}
    fig, axs = plt.subplots(2, 4, figsize=(15, 9.5))
    for ax, d in zip(axs.ravel(), dates):
        img = np.full(cls[d].shape, np.nan)
        for c in codes: img[cls[d] == c] = idx[c]
        ax.imshow(img, cmap=cm, vmin=-0.5, vmax=len(codes) - 0.5, extent=grid.extent, interpolation="nearest"); ax.set_xticks([]); ax.set_yticks([]); ax.set_title(f"acquisition {d} UTC", fontsize=8)
    fig.legend(handles=[Patch(color=cols[c], label=short[c]) for c in codes], loc="lower center", ncol=5, fontsize=8)
    fig.suptitle("Sentinel-1 dark-backscatter candidate classes per acquisition date (VV<-18 & VH<-24 dB). NOT a flood map; not validated; provisional OSM AOI", fontsize=10); fig.tight_layout(rect=(0, 0.06, 1, 0.96)); fig.savefig(outs["fig_multiples"], dpi=80); plt.close(fig)
    n_aoi = float(cc["cells"].groupby(cc["date_utc"]).sum().iloc[0]); fig, ax = plt.subplots(figsize=(10, 5)); bottom = np.zeros(len(dates))
    for c in (wc.TRANSIENT, wc.PERSISTENT, wc.TERRAIN, wc.SMALL, wc.UNASSESSED, wc.TERRAIN_UNKNOWN, wc.INVALID):
        v = np.array([cc[(cc.date_utc == d) & (cc.class_code == c)]["pct_of_aoi_cells"].iloc[0] for d in dates]); ax.bar(range(len(dates)), v, bottom=bottom, color=cols[c], label=short[c]); bottom += v
    ax.set_xticks(range(len(dates))); ax.set_xticklabels([d[5:] for d in dates]); ax.set_ylabel("% of AOI cells (excl. valid-not-dark)"); ax.legend(fontsize=8)
    ax.set_title("Dark-backscatter classes per date (share of AOI cells). Counts depend on date-level radiometry; not flood area", fontsize=9); fig.tight_layout(); fig.savefig(outs["fig_shares"], dpi=110); plt.close(fig)


def md_table(df, cols=None):
    d = df if cols is None else df[cols]
    f = lambda x: "" if (isinstance(x, float) and np.isnan(x)) or x is None else (f"{x:.4g}" if isinstance(x, float) else str(x))      # noqa: E731
    return "\n".join(["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)] + ["| " + " | ".join(f(v) for v in r) + " |" for r in d.itertuples(index=False)])


def build_report(info, dates, cc, shift, qa, sens, cfg, rain):
    P = cfg["params"]; L = []; ad = L.append
    ad("# Sentinel-1 2021 per-date dark-backscatter candidate product (S1WC-1)\n")
    ad("**PROVISIONAL, S1-DERIVED, NOT VALIDATED.** This is a per-acquisition-date classification of low-backscatter cells. It is not a confirmed flood extent, not independent ground truth, not an event map, and has no accuracy, precision, recall, F1 or IoU. "
       "A dark pixel is not automatically water or flood. Flooded vegetation and flooded urban areas are generally not dark, so omission is expected.\n")
    ad("## Dates\n")
    ad(cfg["date_meaning"] + " Each date is classified separately; no date is merged into an event map. The `transient_candidate_date_count` raster is a COUNT OF DATES, not an extent.\n")
    ad("## Definitions\n")
    ad(f"- Valid: finite, not NoData, valid fraction >= {P['min_valid_fraction']}, stored valid flag = 1, for BOTH VV and VH. Otherwise the cell is class 254 (invalid/unknown), never 'not dark'.")
    ad(f"- Dark: VV < {P['vv_dark_db']} dB AND VH < {P['vh_dark_db']} dB. Starting values from general SAR open-water practice; not tuned or validated for Chennai (see the sensitivity table).")
    ad(f"- Persistent: dark on >= {P['persistent_min_dark_dates']} dates with >= {P['min_valid_dates']} valid dates. Computed from the SAME S1 stack, so it is a radar-dark-surface screen, NOT an independent permanent-water mask. No JRC/landcover layer was available offline.")
    ad(f"- Slope screen: slope > {P['max_slope_deg']} deg excluded (terrain/shadow risk); missing slope = class 7 (unknown), never treated as 0. True shadow/layover masks are not available.")
    ad(f"- Cluster screen: 8-neighbour clusters < {P['min_cluster_cells']} cells excluded (class 4).")
    ad("- Classes: 0 valid not dark; 1 transient dark candidate; 2 persistently dark; 3 slope-excluded; 4 small cluster; 5 VV-only dark; 6 persistence unassessable; 7 slope unknown; 254 invalid inside AOI; 255 outside AOI.")
    ad("\n## Input QA\n"); ad(md_table(qa))
    bad = {k: v for k, v in info["mism"].items() if v}
    ad("\nStored valid flag vs the validity rule: " + ("identical for all products." if not bad else f"**DIFFERENCES (cells): {bad}**"))
    ad("Per-date metadata: " + ("all present." if all(info["meta_present"].values()) else "**missing for some dates; QA_PASS and AOI-fingerprint checks could not be made for them.**"))
    ad("\n## Class counts per date\n"); ad(md_table(cc[cc.class_code != wc.NOT_DARK][["date_utc", "class_code", "cells", "pct_of_aoi_cells", "area_km2"]]))
    ad("\n## Date-level radiometry (diagnostic only; nothing is normalised)\n"); ad(md_table(shift))
    ad("\nA whole-scene shift in stable cells changes how many cells cross a fixed threshold, so per-date counts are not comparable as flood area without radiometric reasoning.")
    ad("\n## Threshold sensitivity (dark counts before exclusions; no threshold was selected from it)\n"); ad(md_table(sens[sens.date == dates[-1]]) + f"\n\nAll dates: `{Path(info['outs']['sensitivity']).name}`.")
    ad("\n## Rainfall (CHIRPS; context only)\n")
    ad("CHIRPS is not a flood observation. " + ("Joined for context only: `" + Path(info["outs"]["rain_join"]).name + "`; no association is claimed." if rain is not None else f"Not joined: {info['rain_info'].get('skipped_reason')}."))
    ad("\n## Limitations\n")
    for t in ("No independent flood reference: nothing here is validation or accuracy evidence.", "Low backscatter is a common indicator of smooth open water but neither necessary nor sufficient: wind-roughened water and flooded vegetation/urban areas may not be dark (omission), while smooth tarmac, wet sand, radar shadow, calm bare fields, aquaculture and tanks are also dark (commission).",
              "Flooded vegetation/urban areas are not dark: omission is expected; double-bounce brightening is not modelled.", "Persistence screen is from the same sensor; permanent water and persistent dark surfaces cannot be separated.",
              "Radar shadow/layover are not modelled (slope screen only); no radiometric terrain flattening; products are 30 m block means of a 10 m lattice.", "Date-level radiometric offsets (see shift table) change counts; single orbit (descending 92); eight dates.",
              "AOI is the provisional OSM boundary (~435 km2), not the official GCC boundary.", "Acquisition date = single-scene observation date, not event date; dates are never merged into an event map."): ad("- " + t)
    ad("\n## Input preservation\n"); ad(f"SHA-256 of every input (S1 products, metadata if present, reference rasters, config, AOI files, settings, rainfall CSV) taken before parsing and again after all outputs were written: **{'IDENTICAL' if info['preserved'] else 'CHANGED'}**. status.json not modified; no existing output overwritten.")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default=OUT_DEFAULT); ap.add_argument("--indir", default=None); ap.add_argument("--no-rainfall", action="store_true"); ap.add_argument("--allow-missing-metadata", action="store_true")
    a = ap.parse_args(); root = paths.ROOT; rp = lambda x: Path(x) if Path(x).is_absolute() else root / x                 # noqa: E731
    pre_stops, pre = preflight()
    if pre_stops:
        print("STOP - nothing was written."); [print("  -", x) for x in pre_stops]; return 2
    cfg = json.loads(Path(pre["paths"][CFG_LABEL]).read_text(encoding="utf-8")); wgs, _, _ = load_study_area(); grid = master_grid()
    rain = None if a.no_rainfall else rp(cfg["rainfall_csv"])
    rc, info = run(rp(a.indir or cfg["input_dir"]), rp(a.outdir), cfg, grid, wgs.unary_union, root, rain, cfg["dates"], shared_dirs=(paths.OUT_REP, paths.OUT_TAB, paths.OUT_FIG), pre=pre, allow_missing_metadata=a.allow_missing_metadata)
    if rc == 2:
        print("STOP - nothing was written."); [print("  -", x) for x in info["stops"]]; return 2
    if rc == 3: print("ERROR: input hashes changed:", info.get("stops")); return 3
    print(f"done. outputs: {info['outdir']}\n  input SHA-256 before/after: {'IDENTICAL' if info['preserved'] else 'CHANGED'}\n  report: {info['outs']['report']}"); return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
