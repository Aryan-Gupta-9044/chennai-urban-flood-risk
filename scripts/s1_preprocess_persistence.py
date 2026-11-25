#!/usr/bin/env python
"""Sentinel-1 2021 cross-date bright-VV PERSISTENCE diagnostic (V2.3). READ-ONLY on the existing date-level products; exploratory and descriptive only.

Not flood classification, not a flood extent, not a baseline, not validation. The thresholds (0/+3/+5/+8/+10 dB; +5 primary) and the persistence classes are EXPLORATORY
ANALYTICAL DEFINITIONS, not validated flood thresholds. The first five dates are a descriptive COMPARISON GROUP only (not a dry baseline). No Earth Engine / ASF / Copernicus.
No flood label, no clamping/masking of bright pixels, no regridding of any kind. Missing data are never treated as zero.

Safety: every required input is checked first (exact resolved paths reported, nothing substituted); the AOI fingerprint must agree across all eight metadata files AND with the AOI
actually loaded; every raster must match the master grid; outputs go to a NEW directory and nothing existing is overwritten (the run STOPS if an output exists; there is no overwrite
option); status.json is not touched; SHA-256 of all inputs (incl. configuration, AOI GeoJSON files, settings.json) are taken BEFORE they are parsed/loaded and compared after all outputs are written.
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_persistence.py
  .\\.venv\\Scripts\\python scripts\\s1_preprocess_persistence.py --no-rainfall"""
import argparse
import json
import platform as _platform
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.utils import paths
from src.geospatial import study_area as _sa
from src.geospatial.study_area import load_study_area, master_grid
from src.utils import config as _uconfig
from src.flood_detection import s1_persistence as sp, s1_inventory as inv

POLS = ("VV", "VH")
STEM = "s1_2021_persistence"
RAIN_DEFAULT = "outputs/chirps_2021/tables/rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1.csv"
OUT_DEFAULT = "outputs/s1_2021_persistence"
IN_DEFAULT = "data/processed/s1_2021"


def fname(date, pol, kind): return f"S1A_IW_D092_{date.replace('-', '')}_{pol}_{kind}.tif"


def meta_name(date): return f"S1A_IW_D092_{date.replace('-', '')}_meta.json"


def planned_outputs(outdir):
    o = Path(outdir); t, f, r, ra = o / "tables", o / "figures", o / "reports", o / "rasters"
    names = {"per_date": t / f"{STEM}_per_date_summary.csv", "shift": t / f"{STEM}_distribution_shift.csv", "class_counts": t / f"{STEM}_class_counts.csv",
             "decomp": t / f"{STEM}_date_decomposition.csv", "components": t / f"{STEM}_components.csv", "comp_summary": t / f"{STEM}_component_summary.csv",
             "rain_join": t / f"{STEM}_rainfall_join.csv", "rain_assoc": t / f"{STEM}_rainfall_association.csv", "manifest": r / f"{STEM}_manifest.json", "report": r / f"{STEM}_report.md",
             "fig_class_by_date": f / f"{STEM}_bright_share_by_class_per_date.png", "fig_shift": f / f"{STEM}_vv_percentile_shift.png", "fig_map": f / f"{STEM}_vv_gt5_persistence_map.png",
             "fig_multiples": f / f"{STEM}_vv_gt5_bright_by_date_small_multiples.png", "fig_components": f / f"{STEM}_component_sizes.png"}
    for tname in ("valid_date_count", "bright_frequency_gt5", "median_db_all_dates", "range_db_all_dates", "persistence_class_gt5_cut5", "persistence_class_gt5_cut6", "persistence_class_gt5_cut7"):
        names["ras_" + tname] = ra / f"{STEM}_vv_{tname}.tif"
    for t_ in sp.THRESHOLDS: names[f"ras_count_{t_:g}"] = ra / f"{STEM}_vv_bright_date_count_gt{t_:g}.tif"
    return names


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


CFG_LABEL = "configuration config/s1_preprocess.json"


def preflight():
    """Hash every SOURCE that is about to be parsed or loaded (configuration, the two AOI GeoJSON files that load_study_area() reads, the optional study_area_meta.json, and the
    settings.json that master_grid() reads for resolution/EPSG) BEFORE any of them is opened for content. Returns (stops, pre). Nothing is parsed or loaded here."""
    req = {CFG_LABEL: paths.CONFIG / "s1_preprocess.json", "AOI study_area_wgs84.geojson": _sa.WGS, "AOI study_area_utm44n.geojson": _sa.UTM,
           "settings config/settings.json (grid resolution, EPSG)": _uconfig.CONFIG / "settings.json"}
    missing = [f"MISSING required input: {k}: {v}" for k, v in req.items() if not Path(v).exists()]
    if missing: return missing, None
    src = {k: Path(v) for k, v in req.items()}; absent = []
    if Path(_sa.META).exists(): src["AOI study_area_meta.json (optional)"] = Path(_sa.META)
    else: absent.append(str(_sa.META))
    return [], {"paths": src, "sha256": {k: sp.sha256_file(v) for k, v in src.items()}, "absent_optional": absent}


def run(indir, outdir, cfg, grid, aoi_geom_wgs, rainfall_csv=None, dates=None, shared_dirs=(), pre=None):
    """Returns (rc, info). rc 0 = done; 2 = STOP before any output was written (missing input / mismatch / existing output); 3 = an input hash changed (never expected)."""
    t0 = time.time(); indir, outdir = Path(indir).resolve(), Path(outdir).resolve(); dates = list(dates or cfg["dates"]); stops = []
    if overlap_dirs(indir, outdir): return 2, {"stops": [f"output directory {outdir} overlaps the input directory {indir}; outputs must go to a separate new directory"]}
    for sd in shared_dirs:                                                                       # symmetric: equal, nested INSIDE, or an ANCESTOR of a shared folder (e.g. --outdir outputs) are all refused
        if overlap_dirs(outdir, sd): return 2, {"stops": [f"output directory {outdir} overlaps the shared existing outputs folder {Path(sd).resolve()} (equal, inside it, or an ancestor of it); use a dedicated new directory"]}
    outs = planned_outputs(outdir); existing = [str(p) for p in outs.values() if p.exists()]
    if existing: return 2, {"stops": ["existing outputs would be overwritten; nothing was written. Existing: " + "; ".join(existing[:6]) + (" ..." if len(existing) > 6 else "")]}
    # ---------------------------------------------------------------- 1. every required input must exist (exact resolved paths; no substitution)
    need = {}
    for d in dates:
        need[f"{d} metadata"] = indir / meta_name(d)
        for pol in POLS:
            for k in ("dB", "validfrac", "valid"): need[f"{d} {pol} {k}"] = indir / fname(d, pol, k)
    if not pre or CFG_LABEL not in pre["paths"]: need[CFG_LABEL] = paths.CONFIG / "s1_preprocess.json"      # direct callers; main() already hashed it in preflight()
    missing = {k: str(v) for k, v in need.items() if not Path(v).exists()}
    if missing: return 2, {"stops": [f"MISSING required input: {k}: {v}" for k, v in missing.items()]}
    resolved = {k: str(Path(v).resolve()) for k, v in need.items()}
    # ---------------------------------------------------------------- 1b. hash ALL required inputs BEFORE parsing any metadata or reading any raster / table content
    in_files = {k: Path(v) for k, v in need.items()}
    if rainfall_csv is not None and Path(rainfall_csv).exists(): in_files["rainfall csv"] = Path(rainfall_csv)
    if pre: in_files.update(pre["paths"])                                                      # sources hashed earlier by preflight(); re-hashed below after reading and after all outputs
    before = {**(pre["sha256"] if pre else {}), **{k: sp.sha256_file(p) for k, p in in_files.items() if not (pre and k in pre["sha256"])}}
    # ---------------------------------------------------------------- 2. metadata: QA state, grid and AOI fingerprint
    from src.geospatial.grid import inside_mask
    import geopandas as gpd
    fp_run = inv.query_fingerprint(aoi_geom_wgs)[0][:12]; metas, fps = {}, {}
    for d in dates:
        md = json.loads((indir / meta_name(d)).read_text(encoding="utf-8")); metas[d] = md; fps[d] = md.get("aoi_fingerprint")
        if md.get("status") != "QA_PASS": stops.append(f"{d}: metadata status is {md.get('status')!r}, not QA_PASS")
        if md.get("date_utc") != d: stops.append(f"{d}: metadata date_utc {md.get('date_utc')!r} differs")
        if str(md.get("output_crs", "")).upper().replace("EPSG:", "") != str(grid.crs).upper().replace("EPSG:", ""): stops.append(f"{d}: metadata output_crs {md.get('output_crs')} != master grid {grid.crs}")
        if list(md.get("output_shape", [])) != list(grid.shape): stops.append(f"{d}: metadata output_shape {md.get('output_shape')} != master grid {list(grid.shape)}")
    if len(set(fps.values())) != 1: stops.append(f"AOI fingerprints disagree across the metadata files: {dict(fps)}")
    elif next(iter(fps.values())) != fp_run: stops.append(f"AOI fingerprint in the metadata ({next(iter(fps.values()))}) != fingerprint of the AOI loaded for this run ({fp_run})")
    # ---------------------------------------------------------------- 3. raster grids / dtypes / NoData
    infos = {}
    for k, v in need.items():
        if not str(v).endswith(".tif"): continue
        i = tif_info(v); infos[k] = i; pr = sp.grid_problems(i, grid)
        kind = k.split()[-1]
        if kind == "dB" and (i["dtype"] != "float32" or i["nodata"] != cfg["nodata"]): pr.append(f"dB raster must be float32 with NoData {cfg['nodata']} (found {i['dtype']}, nodata {i['nodata']})")
        if kind == "validfrac" and i["dtype"] != "float32": pr.append(f"validfrac must be float32 (found {i['dtype']})")
        if kind == "valid" and i["dtype"] != "uint8": pr.append(f"valid must be uint8 (found {i['dtype']})")
        stops += [f"{k}: {x}" for x in pr]
    stops += sp.cross_grid_problems(infos)
    if stops: return 2, {"stops": stops, "resolved": resolved}
    # ---------------------------------------------------------------- 4. hash inputs BEFORE reading
    rain_df, rain_info = (None, {"skipped_reason": "rainfall join not requested"}) if rainfall_csv is None else sp.read_rainfall(rainfall_csv, dates)
    # ---------------------------------------------------------------- 5. read (read-only) and compute
    inside = inside_mask(grid, [gpd.GeoSeries([aoi_geom_wgs], crs=4326).to_crs(grid.crs).iloc[0]]); n_aoi = int(inside.sum())
    db, valid, mism = {p: {} for p in POLS}, {p: {} for p in POLS}, {}
    for d in dates:
        for pol in POLS:
            a = read_tif(indir / fname(d, pol, "dB")).astype("float64"); vf = read_tif(indir / fname(d, pol, "validfrac")).astype("float64")
            v_prod = sp.valid_cells(a, vf, np.ones(grid.shape, bool), cfg["min_valid_fraction"], cfg["nodata"]); vt = read_tif(indir / fname(d, pol, "valid"))
            mism[(d, pol)] = int((v_prod != (vt == 1)).sum())                                   # my rule vs the stored valid.tif (should be 0)
            db[pol][d] = np.where(v_prod, a, np.nan); valid[pol][d] = v_prod & inside
    after = {k: sp.sha256_file(p) for k, p in in_files.items()}
    changed = [k for k in before if before[k] != after[k]]
    if changed: return 3, {"stops": [f"INPUT CHANGED during the run: {changed}"], "resolved": resolved}
    group = dates[:5]; comp_label = f"first five dates ({group[0]}..{group[-1]})"
    # per-date summary (VV and VH)
    rows = []
    for d in dates:
        for pol in POLS: rows.append({"date_utc": d, "pol": pol, **sp.per_date_stats(db[pol][d], valid[pol][d], inside)})
    per_date = pd.DataFrame(rows)
    shift = []
    for pol in POLS:
        for r in sp.shift_vs_group(db[pol], valid[pol], dates, group): shift.append({"pol": pol, **r})
    shift = pd.DataFrame(shift)
    # persistence (VV) at every threshold; classes at the primary threshold for the three cut-offs
    vv_db, vv_valid = db["VV"], valid["VV"]; counts = {}
    for t in sp.THRESHOLDS: counts[t] = sp.persistence_counts(vv_db, vv_valid, dates, t)
    nv, nb5 = counts[sp.PRIMARY]; freq = sp.frequency(nb5, nv); cls = {c: sp.classify(nb5, nv, c) for c in sp.CUTOFFS}
    class_rows = []
    for t in sp.THRESHOLDS:
        for c in sp.CUTOFFS:
            for r in sp.class_counts(sp.classify(counts[t][1], counts[t][0], c), inside, counts[t][1], counts[t][0]): class_rows.append({"threshold_db": t, "persistent_cut_dates": c, "primary": t == sp.PRIMARY and c == sp.PRIMARY_CUT, **r})
    class_counts = pd.DataFrame(class_rows)
    decomp = []
    for c in sp.CUTOFFS:
        for r in sp.date_decomposition(vv_db, vv_valid, dates, cls[c], sp.PRIMARY, group): decomp.append({"threshold_db": sp.PRIMARY, "persistent_cut_dates": c, **r})
    decomp = pd.DataFrame(decomp)
    # median / range over valid dates (continuous check that does not depend on a hard threshold)
    stack = np.stack([np.where(vv_valid[d], vv_db[d], np.nan) for d in dates]); allnan = ~np.isfinite(stack).any(axis=0)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(stack, axis=0); rng = np.nanmax(stack, axis=0) - np.nanmin(stack, axis=0)
    med[allnan] = np.nan; rng[allnan] = np.nan
    # components at the primary definition
    comp_rows, comp_sum = [], []
    c6 = cls[sp.PRIMARY_CUT]
    for code in (sp.PERSISTENT, sp.RECURRENT, sp.RARE, sp.SINGLE):
        m = inside & (c6 == code); rr = sp.components(m, grid, sp.CLASS_NAMES[code]); comp_rows += rr; comp_sum.append(sp.component_summary(rr, sp.CLASS_NAMES[code], int(m.sum())))
    for d in dates:
        others = [x for x in group if x != d]
        b = vv_valid[d] & (np.where(vv_valid[d], vv_db[d], -np.inf) > sp.PRIMARY)
        oth = np.logical_or.reduce([vv_valid[x] & (np.where(vv_valid[x], vv_db[x], -np.inf) > sp.PRIMARY) for x in others]); m = b & ~oth
        lab = f"bright on {d}, not on other comparison dates"; rr = sp.components(m, grid, lab); comp_rows += rr; comp_sum.append(sp.component_summary(rr, lab, int(m.sum())))
    components = pd.DataFrame(comp_rows); comp_summary = pd.DataFrame(comp_sum)
    # rainfall join (optional, descriptive)
    rain_join = rain_assoc = None
    if rain_df is not None:
        pv = per_date[per_date.pol == "VV"].set_index("date_utc"); ph = per_date[per_date.pol == "VH"].set_index("date_utc"); dd = decomp[decomp.persistent_cut_dates == sp.PRIMARY_CUT].set_index("date_utc")
        met = pd.DataFrame({"s1_date": dates, "vv_mean_db": [pv.loc[d, "mean_db"] for d in dates], "vv_p50_db": [pv.loc[d, "p50_db"] for d in dates], "vh_mean_db": [ph.loc[d, "mean_db"] for d in dates],
                            "vv_gt5_pct_of_aoi": [pv.loc[d, "gt5_pct_of_aoi"] for d in dates],
                            "vv_gt5_nonpersistent_pct_of_aoi": [round(100 * (dd.loc[d, "bright_cells"] - dd.loc[d, "persistent_cells"]) / n_aoi, 4) for d in dates]})
        rain_join = rain_df.merge(met, on="s1_date"); rain_assoc = pd.DataFrame(sp.spearman_rows(rain_join, rain_join, rain_info["used_columns"], ["vv_mean_db", "vh_mean_db", "vv_gt5_pct_of_aoi", "vv_gt5_nonpersistent_pct_of_aoi"]))
    # ---------------------------------------------------------------- 6. write outputs (new directory only)
    for p in outs.values(): p.parent.mkdir(parents=True, exist_ok=True)
    per_date.to_csv(outs["per_date"], index=False); shift.to_csv(outs["shift"], index=False); class_counts.to_csv(outs["class_counts"], index=False); decomp.to_csv(outs["decomp"], index=False)
    components.to_csv(outs["components"], index=False); comp_summary.to_csv(outs["comp_summary"], index=False)
    if rain_join is not None: rain_join.to_csv(outs["rain_join"], index=False); rain_assoc.to_csv(outs["rain_assoc"], index=False)
    from src.geospatial.grid import write_raster
    na_u8 = lambda a, bad: np.where(bad, 255, a).astype("uint8")                                   # noqa: E731
    notass = nv < sp.MIN_VALID_DATES
    write_raster(outs["ras_valid_date_count"], nv, grid, None, "VV valid-date count per cell (0-8)", "uint8")
    write_raster(outs["ras_bright_frequency_gt5"], np.where(np.isfinite(freq), freq, -9999.0).astype("float32"), grid, -9999.0, "VV bright-date frequency (n_bright / n_valid) at > +5 dB; NoData where < 6 valid dates", "float32")
    write_raster(outs["ras_median_db_all_dates"], np.where(np.isfinite(med), med, -9999.0).astype("float32"), grid, -9999.0, "VV median dB over valid dates", "float32")
    write_raster(outs["ras_range_db_all_dates"], np.where(np.isfinite(rng), rng, -9999.0).astype("float32"), grid, -9999.0, "VV max-min dB over valid dates", "float32")
    for t in sp.THRESHOLDS: write_raster(outs[f"ras_count_{t:g}"], na_u8(counts[t][1], counts[t][0] < sp.MIN_VALID_DATES), grid, 255, f"VV bright-date count at > {t:g} dB (255 = fewer than {sp.MIN_VALID_DATES} valid dates)", "uint8")
    for c in sp.CUTOFFS: write_raster(outs[f"ras_persistence_class_gt5_cut{c}"], cls[c], grid, 255, f"exploratory VV >+5 dB persistence class (0 never,1 single,2 rare,3 recurrent,4 persistent>={c} dates,255 not assessed)", "uint8")
    bright = {d: vv_valid[d] & (np.where(vv_valid[d], vv_db[d], -np.inf) > sp.PRIMARY) for d in dates}
    make_figures(outs, dates, per_date, shift, decomp, comp_summary, bright, c6, inside, grid, sp.PRIMARY_CUT)
    # ---------------------------------------------------------------- 7. report + manifest; re-check input hashes after ALL outputs were written
    after2 = {k: sp.sha256_file(p) for k, p in in_files.items()}; preserved = after2 == before
    info = {"resolved": resolved, "fp_run": fp_run, "crs": str(grid.crs), "fps": fps, "n_aoi": n_aoi, "mism": {f"{d} {p}": v for (d, p), v in mism.items()}, "rain_info": rain_info, "preserved": preserved,
            "group": group, "comp_label": comp_label, "outs": {k: str(v) for k, v in outs.items()}, "indir": str(indir), "outdir": str(outdir)}
    outs["report"].write_text(build_report(info, dates, per_date, shift, class_counts, decomp, comp_summary, rain_join, rain_assoc, cfg), encoding="utf-8")
    man = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - t0, 1), "script": "scripts/s1_preprocess_persistence.py", "version": "S1PE-1",
           "dates": dates, "parameters": {"thresholds_db": list(sp.THRESHOLDS), "primary_db": sp.PRIMARY, "min_valid_dates": sp.MIN_VALID_DATES, "persistent_cuts": list(sp.CUTOFFS), "primary_cut": sp.PRIMARY_CUT,
                                           "comparison_group": group, "min_valid_fraction": cfg["min_valid_fraction"], "nodata": cfg["nodata"]},
           "aoi_fingerprint": {"metadata": fps, "loaded_aoi": fp_run, "aoi_cells": n_aoi}, "resolved_inputs": resolved, "rainfall": rain_info,
           "input_sha256_before": before, "input_sha256_after_all_outputs": after2, "input_hashes_unchanged": preserved, "valid_tif_vs_rule_mismatch_cells": info["mism"],
           "software": versions(), "input_hash_stage": "configuration, AOI GeoJSON files, optional study_area_meta.json and settings.json were hashed before they were parsed/loaded (preflight); all Sentinel-1 products/metadata (and the rainfall CSV) were hashed before any of their content was parsed",
           "preflight_sources": ({k: {"path": str(Path(v).resolve()), "sha256": pre["sha256"][k]} for k, v in pre["paths"].items()} if pre else {}), "preflight_absent_optional": (pre["absent_optional"] if pre else []),
           "aoi_source": "file-backed: load_study_area() reads study_area_wgs84.geojson and study_area_utm44n.geojson (+ optional study_area_meta.json); master_grid() also reads config/settings.json",
           "outputs": {k: str(v) for k, v in outs.items() if k != "manifest"}, "status_json_modified": False}
    outs["manifest"].write_text(json.dumps(man, indent=1, sort_keys=True), encoding="utf-8")
    return (0 if preserved else 3), info


def make_figures(outs, dates, per_date, shift, decomp, comp_summary, bright, c6, inside, grid, cut):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    cols = {sp.SINGLE: "#fdd49e", sp.RARE: "#fc8d59", sp.RECURRENT: "#d7301f", sp.PERSISTENT: "#7f0000", sp.NOT_ASSESSED: "#bdbdbd"}
    dd = decomp[decomp.persistent_cut_dates == cut]; n_aoi = float(per_date[per_date.pol == "VV"]["aoi_cells"].iloc[0])
    fig, ax = plt.subplots(figsize=(9, 4.8)); bottom = np.zeros(len(dates))
    for code in (sp.PERSISTENT, sp.RECURRENT, sp.RARE, sp.SINGLE, sp.NOT_ASSESSED):
        v = np.array([dd[dd.date_utc == d][f"{sp.CLASS_NAMES[code]}_cells"].iloc[0] for d in dates]) / n_aoi * 100
        ax.bar(range(len(dates)), v, bottom=bottom, color=cols[code], label=sp.CLASS_NAMES[code] + (f" (>= {cut} dates)" if code == sp.PERSISTENT else "")); bottom += v
    ax.set_xticks(range(len(dates))); ax.set_xticklabels([d[5:] for d in dates]); ax.set_ylabel("% of AOI cells with VV > +5 dB"); ax.legend(fontsize=8)
    ax.set_title("VV > +5 dB per date, split by cross-date persistence class\n(exploratory definitions; not flood labels)", fontsize=10); fig.tight_layout(); fig.savefig(outs["fig_class_by_date"], dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4.8)); sv = shift[shift.pol == "VV"]; pc = [c for c in sv.columns if c.startswith("d_p")]
    for _, r in sv.iterrows(): ax.plot([int(c[3:5]) for c in pc], [r[c] for c in pc], marker="o", ms=3, label=r["date_utc"][5:] + (" *" if r["in_comparison_group"] else ""))
    ax.axhline(0, color="k", lw=0.6); ax.set_xlabel("percentile"); ax.set_ylabel("VV percentile minus comparison-group mean (dB)"); ax.legend(fontsize=7, ncol=2)
    ax.set_title("Whole-scene VV distribution shift vs the first-five-date comparison group (* = member)\ndescriptive only; the group is NOT a dry baseline", fontsize=10); fig.tight_layout(); fig.savefig(outs["fig_shift"], dpi=110); plt.close(fig)
    cm = ListedColormap(["#eeeeee", cols[sp.SINGLE], cols[sp.RARE], cols[sp.RECURRENT], cols[sp.PERSISTENT], cols[sp.NOT_ASSESSED]])

    def show(ax, cl, mask):
        img = np.full(cl.shape, np.nan)
        for code, i in ((sp.NEVER, 0), (sp.SINGLE, 1), (sp.RARE, 2), (sp.RECURRENT, 3), (sp.PERSISTENT, 4), (sp.NOT_ASSESSED, 5)): img[mask & (cl == code)] = i
        ax.imshow(img, cmap=cm, vmin=-0.5, vmax=5.5, extent=grid.extent, interpolation="nearest"); ax.set_xticks([]); ax.set_yticks([])
    handles = [Patch(color="#eeeeee", label="never bright")] + [Patch(color=cols[c], label=sp.CLASS_NAMES[c]) for c in (sp.SINGLE, sp.RARE, sp.RECURRENT, sp.PERSISTENT)]
    fig, ax = plt.subplots(figsize=(6.5, 8.5)); show(ax, c6, inside); ax.legend(handles=handles, fontsize=8, loc="lower left")
    ax.set_title(f"VV > +5 dB cross-date persistence class (persistent >= {cut} of 8 dates)\nexploratory, descriptive; not flood labels. Provisional OSM AOI", fontsize=9); fig.tight_layout(); fig.savefig(outs["fig_map"], dpi=110); plt.close(fig)
    fig, axs = plt.subplots(2, 4, figsize=(15, 9.5))
    for ax, d in zip(axs.ravel(), dates):
        show(ax, c6, inside & bright[d]); base = np.where(inside & ~bright[d], 1.0, np.nan); ax.imshow(base, cmap=ListedColormap(["#f2f2f2"]), vmin=0, vmax=1, extent=grid.extent, zorder=0, interpolation="nearest")
        ax.set_title(f"{d}: bright cells coloured by persistence class", fontsize=8)
    fig.legend(handles=handles[1:], loc="lower center", ncol=4, fontsize=9); fig.suptitle("VV > +5 dB cells on each date (exploratory persistence classes; not flood labels)", fontsize=11); fig.tight_layout(rect=(0, 0.04, 1, 0.97)); fig.savefig(outs["fig_multiples"], dpi=80); plt.close(fig)
    cs = comp_summary[comp_summary["class"].isin([sp.CLASS_NAMES[c] for c in (sp.PERSISTENT, sp.RECURRENT, sp.RARE, sp.SINGLE)])]; bins = [c for c in cs.columns if c.startswith("n_comp_")]
    fig, ax = plt.subplots(figsize=(9, 4.8)); w = 0.2
    for k, (_, r) in enumerate(cs.iterrows()): ax.bar(np.arange(len(bins)) + k * w, [r[b] for b in bins], w, label=r["class"])
    ax.set_xticks(np.arange(len(bins)) + 1.5 * w); ax.set_xticklabels([b.replace("n_comp_", "").replace("_plus", "+").replace("_", "-") for b in bins]); ax.set_yscale("symlog"); ax.set_xlabel("component size (30 m cells, 8-neighbour)"); ax.set_ylabel("components")
    ax.legend(fontsize=8); ax.set_title("Connected-component sizes by persistence class (VV > +5 dB)", fontsize=10); fig.tight_layout(); fig.savefig(outs["fig_components"], dpi=110); plt.close(fig)


def md_table(df, cols=None, nd=None):
    d = df if cols is None else df[cols]
    f = lambda x: "" if (isinstance(x, float) and np.isnan(x)) or x is None else (f"{x:.4g}" if isinstance(x, float) else str(x))      # noqa: E731
    return "\n".join(["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)] + ["| " + " | ".join(f(v) for v in r) + " |" for r in d.itertuples(index=False)])


def build_report(info, dates, per_date, shift, class_counts, decomp, comp_summary, rain_join, rain_assoc, cfg):
    L = []; ad = L.append; o = info["outs"]
    ad("# Sentinel-1 2021 cross-date bright-VV persistence diagnostic (S1PE)\n")
    ad("**EXPLORATORY and DESCRIPTIVE ONLY.** Not flood classification, not a flood extent, not a baseline, not validation. The thresholds and persistence classes are exploratory analytical definitions, "
       "not validated flood thresholds. No bright pixel was clamped, masked or removed; the source rasters were only read.\n")
    ad("## Inputs (exact resolved paths; nothing substituted)\n")
    ad(f"- Input directory: `{info['indir']}`\n- Output directory: `{info['outdir']}`\n- Dates (config/s1_preprocess.json): {', '.join(dates)}")
    ad(f"- Rasters per date: VV/VH x dB, validfrac, valid ({3 * 2 * len(dates)} files) + {len(dates)} metadata files; all present, all on the master grid ({info['crs']}, 30 m), same shape/CRS/transform, dB float32 with NoData {cfg['nodata']}.")
    ad(f"- AOI fingerprint: all {len(dates)} metadata files = `{next(iter(info['fps'].values()))}`; fingerprint of the AOI loaded for this run = `{info['fp_run']}` (agree). AOI cells: {info['n_aoi']}. AOI is the PROVISIONAL OSM boundary, not the official GCC boundary.")
    bad = {k: v for k, v in info["mism"].items() if v}
    ad("- Stored `_valid.tif` vs the validity rule (finite, not NoData, valid fraction >= " + str(cfg["min_valid_fraction"]) + "): " + ("identical for all 16 products." if not bad else f"**DIFFERENCES (cells): {bad}**"))
    ri = info["rain_info"]
    ad("- Rainfall table: " + (f"`{ri['path']}` (sha256 `{ri['sha256'][:12]}`), columns used: {', '.join(ri['used_columns'])}" if ri.get("used_columns") else f"**not joined: {ri.get('skipped_reason')}**"))
    ad("\n## Definitions (exploratory)\n")
    ad(f"- Valid cell on a date: passes the product validity rule AND lies inside the AOI. Missing/invalid cells are not counted as valid and never as zero. A cell is classified only if valid on >= {sp.MIN_VALID_DATES} of {len(dates)} dates.")
    ad(f"- Thresholds (dB): {', '.join(f'{t:+g}' for t in sp.THRESHOLDS)}; **+5 dB is primary** (the project's existing QA value). Bright on a date = valid and VV > threshold.")
    ad(f"- Classes from the ABSOLUTE bright-date count: never (0), single-date (1), rare (2), recurrent (3 .. cut-1), persistent (>= cut). Primary cut = {sp.PRIMARY_CUT} dates; sensitivity at {', '.join(map(str, sp.CUTOFFS))}. "
       "The bright-date FREQUENCY (bright dates / valid dates) is written as a raster and as the class mean in the class table.")
    ad(f"- Comparison group (descriptive only, **not a dry baseline**): {info['comp_label']}. Shifts are percentile curves minus the group mean curve, and cell-wise differences to the per-cell group median.")
    ad("\n## Per-date summary (VV and VH; full table in the CSV)\n")
    ad(md_table(per_date, ["date_utc", "pol", "valid_cells", "valid_share_pct", "mean_db", "p50_db", "p95_db", "p99_db", "gt0_pct_of_aoi", "gt3_pct_of_aoi", "gt5_pct_of_aoi", "gt8_pct_of_aoi", "gt10_pct_of_aoi"]))
    ad("\n## Whole-scene distribution shift vs the comparison group (dB; descriptive)\n")
    ad(md_table(shift, ["pol", "date_utc", "in_comparison_group", "d_p05_db", "d_p50_db", "d_p95_db", "d_p99_db", "paired_cells", "paired_median_diff_db"]))
    ad("\nA shift that is similar across percentiles is a whole-scene change; a shift only in the upper percentiles is a tail change. Neither is interpreted as flooding here.")
    ad("\n## Cross-date persistence of VV > +5 dB (primary threshold; classes at the three cut-offs)\n")
    ad(md_table(class_counts[(class_counts.threshold_db == sp.PRIMARY)], ["persistent_cut_dates", "class", "cells", "pct_of_aoi_cells", "pct_of_assessed_cells", "min_bright_dates", "max_bright_dates", "mean_bright_frequency"]))
    ad("\nOther thresholds: see the class-count CSV.")
    ad("\n## Per-date bright cells by persistence class (primary cut)\n")
    ad(md_table(decomp[decomp.persistent_cut_dates == sp.PRIMARY_CUT], [c for c in decomp.columns if c not in ("threshold_db", "persistent_cut_dates") and "pct" not in c or c in ("bright_not_in_other_comparison_dates_pct",)]))
    ad("\n## Connected components (8-neighbour, 30 m cells)\n")
    ad(md_table(comp_summary, ["class", "cells", "n_components", "largest_component_cells", "median_component_cells", "pct_cells_in_single_cell_components", "pct_cells_in_components_ge10"]))
    ad("\nIsolated single-cell components are common for bright cells; a bright component is not assumed to be floodwater, a structure or an artefact.")
    ad("\n## Rainfall association (optional, descriptive)\n")
    if rain_join is None: ad(f"Not computed: {ri.get('skipped_reason')}.")
    else:
        ad(f"Source table (workflow output, AOI-weighted prior-window means from the provisional OSM AOI): `{ri['path']}`. Windows are [D-N, D-1] (the Sentinel-1 day is excluded); missing days are never zero-filled; "
           "the CHIRPS v3 DAILY_SAT day convention is PROVISIONAL (not verified against IST observation-day windows); the values are reported workflow outputs, not independently validated rainfall. "
           "Sentinel-1 overpass is ~00:31 UTC (~06:01 IST). Only the verified columns present in the file are used; no other window was computed.\n")
        ad(md_table(rain_join)); ad("\nRank correlations (n = 8 dates). **Descriptive only; no causation or significance is claimed.** Rainfall, season and the scene statistics all trend with the calendar date, so these cannot separate them.\n"); ad(md_table(rain_assoc))
    ad("\n## Limitations\n")
    for t in ("Exploratory definitions: thresholds and classes are analytical conventions, not validated flood thresholds; counts near a threshold are sensitive to small dB differences (the median/range rasters and the cut-off sensitivity are provided for this reason).",
              "Eight dates only; one relative orbit (descending 92). A cell bright on several dates is consistent with a persistent bright target, but its cause is NOT established.",
              "Land cover and terrain context were not assessed in this diagnostic; no cause (built-up structures, wet surfaces, geometry, calibration) is established or excluded.",
              "The November whole-scene shifts are not attributed to flooding or to rainfall without independent corroboration.",
              "Products are 30 m linear-power block means of a 10 m lattice (multilooked, irreversible), not native independent 30 m data; EE ingestion processing was not repeated; no radiometric terrain flattening was applied.",
              "The seam: footprint overlap ~35 m but 0 valid overlapping pixels (M4C diagnostics); the cause is unconfirmed and is not revisited here.",
              "AOI is the provisional OSM boundary (~435 km2); results must be recomputed if the official GCC boundary replaces it.",
              "No independent reference was used; nothing here is accuracy or validation evidence."): ad("- " + t)
    ad("\n## Source-raster preservation\n")
    ad(f"SHA-256 of every input file (56 products/metadata + configuration, AOI GeoJSON/meta and settings source files{' + rainfall CSV' if ri.get('sha256') else ''}) was computed before each was parsed/loaded and again after all outputs were written: **{'IDENTICAL' if info['preserved'] else 'CHANGED - see manifest'}**. "
       "No input was opened for writing, status.json was not modified, and no existing output was overwritten (the run stops if an output exists). Hashes: `reports/" + STEM + "_manifest.json`.")
    ad("\n## Outputs\n")
    for k, v in o.items():
        if k != "report": ad(f"- `{v}`")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--indir", default=IN_DEFAULT); ap.add_argument("--outdir", default=OUT_DEFAULT); ap.add_argument("--rainfall-csv", default=RAIN_DEFAULT); ap.add_argument("--no-rainfall", action="store_true")
    a = ap.parse_args(); root = paths.ROOT
    rp = lambda x: Path(x) if Path(x).is_absolute() else root / x                          # noqa: E731
    pre_stops, pre = preflight()                                                              # 1. hash config + AOI files + settings; nothing parsed/loaded yet
    if pre_stops:
        print("STOP - nothing was written."); [print("  -", x) for x in pre_stops]; return 2
    cfg = json.loads(Path(pre["paths"][CFG_LABEL]).read_text(encoding="utf-8"))               # 2. only now parse the configuration
    wgs, _, _ = load_study_area(); grid = master_grid()                                       # 3. only now load the AOI and build the master grid
    rc, info = run(rp(a.indir), rp(a.outdir), cfg, grid, wgs.unary_union, None if a.no_rainfall else rp(a.rainfall_csv), cfg["dates"], shared_dirs=(paths.OUT_REP, paths.OUT_TAB, paths.OUT_FIG), pre=pre)   # 4. hashes S1 inputs, then parses
    if rc == 2:
        print("STOP - nothing was written."); [print("  -", x) for x in info["stops"]]; return 2
    if rc == 3: print("ERROR: input hashes changed:", info.get("stops")); return 3
    ri = info["rain_info"]
    print(f"done. outputs: {info['outdir']}\n  input SHA-256 before/after: {'IDENTICAL' if info['preserved'] else 'CHANGED'}; rainfall join: " + ("used " + ", ".join(ri["used_columns"]) if ri.get("used_columns") else f"skipped ({ri.get('skipped_reason')})"))
    print(f"  report: {info['outs']['report']}"); return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
