#!/usr/bin/env python
"""S1WC-2 (additive refinement of the S1WC-1 dark-backscatter candidate product). READ-ONLY on every input including the S1WC-1 outputs; writes only to a NEW versioned directory.

Adds ONE class (8: dark candidate on a provisional DEM-indicated flattened-water signature) carved out of S1WC-1 class 1; adds comparability, TWI-clamp and before/after tables; records SHA-256 of all inputs and outputs.
NOT a flood extent, NOT validated, no normalisation, no new thresholds, no terrain flattening, no flood labels; the remaining class-1 cells are not confirmed floodwater.
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\s1_water_candidates_v2_review.py
  .\\.venv\\Scripts\\python scripts\\s1_water_candidates_v2_review.py --outdir outputs\\s1_water_candidates_review_v2 --s1wc1-dir outputs\\s1_water_candidates_review_v1"""
import argparse
import importlib.util
import json
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
from src.flood_detection import s1_persistence as sp, s1_water_candidates as wc, s1_water_candidates_v2 as w2


def _load_v1():
    spec = importlib.util.spec_from_file_location("s1_water_candidates_review", Path(__file__).resolve().parent / "s1_water_candidates_review.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


V1 = _load_v1()
POLS = V1.POLS
STEM = "s1_water_candidates_v2"
CFG_LABEL = "configuration config/s1_water_candidates_v2.json"
BASE_LABEL = "configuration config/s1_water_candidates.json (S1WC-1 parameters, reused verbatim)"
OUT_DEFAULT = "outputs/s1_water_candidates_review_v2"
PROTECTED_PREFIXES = ("s1_2021_persistence", "chirps_2021", "s1_water_candidates_review_v1")


def planned_outputs(outdir, dates):
    o = Path(outdir); t, f, r, ra = o / "tables", o / "figures", o / "reports", o / "rasters"
    n = {"before_after": t / f"{STEM}_before_after_counts_per_date.csv", "class_counts": t / f"{STEM}_class_counts_per_date.csv", "comparability": t / f"{STEM}_comparability_with_counts.csv",
         "signature": t / f"{STEM}_dem_signature_summary.csv", "signature_sens": t / f"{STEM}_dem_signature_plateau_size_sensitivity.csv", "twi_clamp": t / f"{STEM}_twi_clamp_summary.csv", "terrain": t / f"{STEM}_terrain_context.csv",
         "input_qa": t / f"{STEM}_input_qa.csv", "regression": t / f"{STEM}_regression_vs_s1wc1.csv", "manifest": r / f"{STEM}_manifest.json", "report": r / f"{STEM}_report.md",
         "fig_multiples": f / f"{STEM}_class_by_date_small_multiples.png", "fig_before_after": f / f"{STEM}_before_after_counts.png", "ras_signature": ra / f"{STEM}_dem_water_signature.tif",
         "ras_t1_count": ra / f"{STEM}_class1_candidate_date_count.tif", "ras_t8_count": ra / f"{STEM}_class8_signature_candidate_date_count.tif"}
    for d in dates: n[f"ras_class_{d}"] = ra / f"{STEM}_class_{d}.tif"
    return n


def preflight():
    req = {CFG_LABEL: paths.CONFIG / "s1_water_candidates_v2.json", BASE_LABEL: paths.CONFIG / "s1_water_candidates.json", "AOI study_area_wgs84.geojson": _sa.WGS, "AOI study_area_utm44n.geojson": _sa.UTM,
           "settings config/settings.json": _uconfig.CONFIG / "settings.json"}
    missing = [f"MISSING required input: {k}: {v}" for k, v in req.items() if not Path(v).exists()]
    if missing: return missing, None
    src = {k: Path(v) for k, v in req.items()}; absent = []
    if Path(_sa.META).exists(): src["AOI study_area_meta.json (optional)"] = Path(_sa.META)
    else: absent.append(str(_sa.META))
    return [], {"paths": src, "sha256": {k: sp.sha256_file(v) for k, v in src.items()}, "absent_optional": absent}


def run(indir, outdir, cfg2, cfg1, grid, aoi_geom_wgs, root, dates=None, shared_dirs=(), pre=None, allow_missing_metadata=False, s1wc1_dir=None):
    """Returns (rc, info). rc 0 done; 2 STOP before any output; 3 an input hash changed (including S1WC-1 outputs)."""
    t0 = time.time(); root = Path(root); indir, outdir = Path(indir).resolve(), Path(outdir).resolve(); stops = []
    try: dates = V1.parse_dates(dates or cfg1["dates"])
    except ValueError as e: return 2, {"stops": [f"invalid dates: {e}"]}
    if V1.overlap_dirs(indir, outdir): return 2, {"stops": [f"output directory {outdir} overlaps the input directory {indir}"]}
    for sd in list(shared_dirs) + ([s1wc1_dir] if s1wc1_dir else []):
        if V1.overlap_dirs(outdir, sd): return 2, {"stops": [f"output directory {outdir} overlaps the protected/shared existing folder {Path(sd).resolve()} (equal, inside, or ancestor); S1WC-2 must use its own new directory"]}
    if any(outdir.name.startswith(p) or any(par.name.startswith(p) for par in outdir.parents) for p in PROTECTED_PREFIXES): return 2, {"stops": [f"output directory {outdir} is inside a protected existing output family {PROTECTED_PREFIXES}"]}
    outs = planned_outputs(outdir, dates); existing = [str(p) for p in outs.values() if p.exists()]
    if existing: return 2, {"stops": ["existing outputs would be overwritten; nothing was written. Existing: " + "; ".join(existing[:6]) + (" ..." if len(existing) > 6 else "")]}
    refs = {k: (Path(v) if Path(v).is_absolute() else root / v) for k, v in cfg2["reference_layers"].items()}
    need = {}
    for d in dates:
        for pol in POLS:
            for k in ("dB", "validfrac", "valid"): need[f"{d} {pol} {k}"] = indir / V1.fname(d, pol, k)
    miss = {k: str(v) for k, v in need.items() if not v.exists()}
    meta_present = {d: (indir / V1.meta_name(d)).exists() for d in dates}
    if not all(meta_present.values()) and not allow_missing_metadata: miss.update({f"{d} metadata": str(indir / V1.meta_name(d)) for d in dates if not meta_present[d]})
    for k in cfg2.get("required_reference_layers", ["dem_elevation_m", "slope_deg"]):
        if not refs[k].exists(): miss[f"required reference layer {k}"] = str(refs[k])
    s1_files = {}
    if s1wc1_dir is not None and Path(s1wc1_dir).exists():
        for d in dates:
            p = Path(s1wc1_dir) / "rasters" / f"s1_water_candidates_class_{d}.tif"
            if p.exists(): s1_files[f"S1WC-1 class raster {d}"] = p
    if miss: return 2, {"stops": [f"MISSING required input: {k}: {v}" for k, v in miss.items()]}
    in_files = dict(need); in_files.update({f"{d} metadata": indir / V1.meta_name(d) for d in dates if meta_present[d]}); ref_present = {k: v for k, v in refs.items() if v.exists()}
    in_files.update({f"reference {k}": v for k, v in ref_present.items()}); in_files.update(s1_files)
    if pre: in_files.update(pre["paths"])
    in_files = {k: Path(v) for k, v in in_files.items()}
    before = {**(pre["sha256"] if pre else {}), **{k: sp.sha256_file(p) for k, p in in_files.items() if not (pre and k in pre["sha256"])}}
    from src.geospatial.grid import inside_mask
    import geopandas as gpd
    from src.flood_detection import s1_inventory as inv
    fp_run = inv.query_fingerprint(aoi_geom_wgs)[0][:12]; fps = {}
    for d in dates:
        if not meta_present[d]: continue
        md = json.loads((indir / V1.meta_name(d)).read_text(encoding="utf-8")); fps[d] = md.get("aoi_fingerprint")
        if md.get("status") != "QA_PASS": stops.append(f"{d}: metadata status {md.get('status')!r} is not QA_PASS")
        if md.get("date_utc") != d: stops.append(f"{d}: metadata date_utc {md.get('date_utc')!r} differs")
    if fps and len(set(fps.values())) != 1: stops.append(f"AOI fingerprints disagree across metadata: {fps}")
    elif fps and next(iter(fps.values())) != fp_run: stops.append("AOI fingerprint in the metadata != fingerprint of the AOI loaded for this run")
    infos = {}
    for k, v in {**need, **{f"reference {kk}": vv for kk, vv in ref_present.items()}, **s1_files}.items():
        i = V1.tif_info(v); infos[k] = i; pr = sp.grid_problems(i, grid); kind = k.split()[-1]
        if kind == "dB" and (i["dtype"] != "float32" or i["nodata"] != cfg1["nodata"]): pr.append(f"dB raster must be float32 with NoData {cfg1['nodata']} (found {i['dtype']}, {i['nodata']})")
        if kind == "validfrac" and i["dtype"] != "float32": pr.append(f"validfrac must be float32 (found {i['dtype']})")
        if kind == "valid" and i["dtype"] != "uint8": pr.append(f"valid must be uint8 (found {i['dtype']})")
        stops += [f"{k}: {x} (no resampling/reprojection is performed)" for x in pr]
    stops += sp.cross_grid_problems({k: v for k, v in infos.items() if not k.startswith("reference") and not k.startswith("S1WC-1")})
    if stops: return 2, {"stops": stops}
    P = cfg1["params"]; V = {**w2.DEFAULT_PARAMS, **cfg2["v2_params"]}; nd = cfg1["nodata"]
    inside = inside_mask(grid, [gpd.GeoSeries([aoi_geom_wgs], crs=4326).to_crs(grid.crs).iloc[0]]); n_aoi = int(inside.sum())
    vv, vh, vboth, mism, qa_rows = {}, {}, {}, {}, []
    for d in dates:
        vp = {}
        for pol in POLS:
            a = V1.read_tif(indir / V1.fname(d, pol, "dB")).astype("float64"); vf = V1.read_tif(indir / V1.fname(d, pol, "validfrac")).astype("float64"); fl = V1.read_tif(indir / V1.fname(d, pol, "valid"))
            v = wc.valid_pol(a, vf, fl, P["min_valid_fraction"], nd); vp[pol] = v
            v_rule = sp.valid_cells(a, vf, np.ones(grid.shape, bool), P["min_valid_fraction"], nd); mism[f"{d} {pol}"] = int((v_rule != (fl == 1)).sum())
            (vv if pol == "VV" else vh)[d] = np.where(v, a, np.nan)
        vboth[d] = vp["VV"] & vp["VH"]
        qa_rows.append({"date_utc": d, "aoi_cells": n_aoi, "valid_both_pct_of_aoi": round(100 * (vboth[d] & inside).sum() / n_aoi, 3), "invalid_inside_aoi_cells": int((inside & ~vboth[d]).sum()), "metadata_present": meta_present[d]})
    rl = lambda k: V1.read_tif(refs[k]).astype("float64") if k in ref_present else None                     # noqa: E731
    dem, slope, twi, acc = rl("dem_elevation_m"), rl("slope_deg"), rl("twi"), rl("flow_accumulation"); drain = V1.read_tif(refs["drainage_network"]) if "drainage_network" in ref_present else None
    s1_arr = {d: V1.read_tif(Path(s1wc1_dir) / "rasters" / f"s1_water_candidates_class_{d}.tif") for d in dates if f"S1WC-1 class raster {d}" in s1_files}
    after = {k: sp.sha256_file(p) for k, p in in_files.items()}; changed = [k for k in before if before[k] != after[k]]
    if changed: return 3, {"stops": [f"INPUT CHANGED during the run: {changed}"]}
    # ---- S1WC-1 classification (library functions, unchanged) then the S1WC-2 carve-out
    dark = {d: wc.dark_mask(vv[d], vh[d], P["vv_dark_db"], P["vh_dark_db"], vboth[d] & inside) for d in dates}; vonly = {d: wc.vv_only_dark(vv[d], vh[d], P["vv_dark_db"], P["vh_dark_db"], vboth[d] & inside) for d in dates}
    vstack = np.stack([vboth[d] & inside for d in dates]); dstack = np.stack([dark[d] for d in dates]); n_dark, n_valid, persistent, assess = wc.persistence(dstack, vstack, P["min_valid_dates"], P["persistent_min_dark_dates"])
    c1 = {d: wc.classify_date(vboth[d] & inside, dark[d], vonly[d], persistent, assess, slope, inside, P["max_slope_deg"], P["min_cluster_cells"]) for d in dates}
    zero, plateau, sig = w2.plateau_signature(dem, inside, V["min_plateau_cells"], nd); c2 = {d: w2.apply_signature(c1[d], sig) for d in dates}
    reg = []
    for d in dates:
        ok_fold = bool((w2.fold_back(c2[d]) == c1[d]).all()); other = bool(((c2[d] != 8) == (c1[d] != 1) | (c2[d] == c1[d])).all() and (c2[d][c2[d] != 8] == c1[d][c2[d] != 8]).all())
        row = {"date": d, "v2_folded_equals_s1wc1_recomputed": ok_fold, "classes_other_than_1_and_8_identical": other, "s1wc1_stored_raster_available": d in s1_arr, "recomputed_equals_stored_s1wc1": (bool((s1_arr[d] == c1[d]).all()) if d in s1_arr else None)}
        reg.append(row)
        if d in s1_arr and not row["recomputed_equals_stored_s1wc1"]: stops.append(f"{d}: recomputed S1WC-1 classes differ from the stored S1WC-1 raster ({int((s1_arr[d] != c1[d]).sum())} cells); inputs or parameters differ from the S1WC-1 run")
        if not ok_fold or not other: stops.append(f"{d}: internal S1WC-2 regression check failed")
    if stops: return 2, {"stops": stops}
    # ---- tables
    cell_area = abs(grid.transform.a * grid.transform.e) / 1e6; ba, cc = [], []
    for d in dates:
        a1, b1, b8 = int((c1[d] == 1).sum()), int((c2[d] == 1).sum()), int((c2[d] == 8).sum())
        ba.append({"date_utc": d, "s1wc1_class1_candidates": a1, "s2_class1_candidates_remaining": b1, "s2_class8_on_dem_signature": b8, "class1_plus_class8_equals_s1wc1": a1 == b1 + b8, "class8_share_of_s1wc1_class1_pct": round(100 * b8 / a1, 2) if a1 else None,
                   "s1wc1_class1_area_km2": round(a1 * cell_area, 4), "s2_class1_area_km2": round(b1 * cell_area, 4)})
        cc += [{"date_utc": d, **r} for r in wc.class_counts(c2[d], cell_area, n_aoi)] + [{"date_utc": d, "class_code": 8, "class": w2.CLASS_NAMES[8], "cells": b8, "pct_of_aoi_cells": round(100 * b8 / n_aoi, 4), "area_km2": round(b8 * cell_area, 4)}]
    ba = pd.DataFrame(ba); cc = pd.DataFrame(cc); u1 = np.any([c1[d] == 1 for d in dates], axis=0); u2 = np.any([c2[d] == 1 for d in dates], axis=0); u8 = np.any([c2[d] == 8 for d in dates], axis=0)
    ba = pd.concat([ba, pd.DataFrame([{"date_utc": "union over dates (cells; NOT an event extent)", "s1wc1_class1_candidates": int(u1.sum()), "s2_class1_candidates_remaining": int(u2.sum()), "s2_class8_on_dem_signature": int(u8.sum()),
                                       "class1_plus_class8_equals_s1wc1": bool((u2 | u8).sum() == u1.sum()), "class8_share_of_s1wc1_class1_pct": round(100 * u8.sum() / u1.sum(), 2)}])], ignore_index=True)
    shift = pd.DataFrame(wc.radiometric_shift(dates, np.stack([vv[d] for d in dates]), np.stack([vh[d] for d in dates]), vstack)); bu = pd.DataFrame(w2.block_uniformity(dates, np.stack([vv[d] for d in dates]), vstack, V["block_cells"], V["block_min_cells"]))
    vvh = pd.DataFrame(w2.vv_vh_stable(dates, np.stack([vv[d] for d in dates]), np.stack([vh[d] for d in dates]), vstack))
    comp = ba[ba.date_utc.isin(dates)].rename(columns={"date_utc": "date"}).merge(shift[["date", "vv_stable_minus_mean_of_dates_db", "vh_stable_minus_mean_of_dates_db", "stable_cells"]], on="date").merge(vvh, on="date").merge(bu.rename(columns={"block_sd_db": "vv_block_sd_db", "frac_blocks_within_1db": "vv_frac_blocks_within_1db"})[["date", "vv_block_sd_db", "vv_frac_blocks_within_1db"]], on="date")
    comp["interpretation_note"] = "descriptive; date-level radiometric offsets mean candidate counts are NOT comparable across dates; nothing is normalised"
    sens = []
    for n_ in (10, 20, 30, 50):
        z_, p_, s_ = w2.plateau_signature(dem, inside, n_, nd); sens.append({"min_plateau_cells": n_, "primary": n_ == V["min_plateau_cells"], "dem_zero_cells": int(z_.sum()), "plateau_cells": int(p_.sum()), "signature_cells": int(s_.sum()), "union_class1_cells_on_signature": int((u1 & s_).sum()),
                                                                                       "slope0_dem_positive_cells_not_flagged": int(((slope == 0) & inside & (dem > 0) & ~p_).sum())})
    from scipy import ndimage as ndi
    lab, nl = ndi.label(plateau, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])); szs = np.bincount(lab.ravel())[1:] if nl else np.array([0])
    sigsum = pd.DataFrame([{"quantity": "AOI cells", "value": n_aoi}, {"quantity": "DEM == 0 cells", "value": int(zero.sum())}, {"quantity": f"plateau cells (>= {V['min_plateau_cells']} identical-value cells, non-zero)", "value": int(plateau.sum())},
                           {"quantity": "plateau components (touching components may merge in this count)", "value": int(nl)}, {"quantity": "largest plateau component (cells)", "value": int(szs.max())}, {"quantity": "signature cells (zero OR plateau)", "value": int(sig.sum())},
                           {"quantity": "signature share of AOI (%)", "value": round(100 * sig.sum() / n_aoi, 3)}, {"quantity": "S1WC-1 union class-1 cells", "value": int(u1.sum())}, {"quantity": "of which on the signature (class 8 union)", "value": int(u8.sum())},
                           {"quantity": "slope == 0 & DEM > 0 cells NOT flagged (flat terrain without the plateau signature)", "value": int(((slope == 0) & inside & (dem > 0) & ~plateau).sum())},
                           {"quantity": "label", "value": "provisional DEM-indicated flattened-water signature; NOT a confirmed permanent-water mask or flood exclusion; Copernicus WBM NOT used"}])
    layers = {k: v for k, v in (("slope_deg", slope), ("dem_elevation_m", dem), ("twi", twi), ("flow_accumulation", acc)) if v is not None}; valid_cells = np.isin(np.stack([c2[d] for d in dates]), (0, 1, 2, 3, 4, 5, 6, 7, 8)).any(0) & inside
    clamped, clamp_bad = (w2.twi_clamp(slope, twi, acc, grid.res if hasattr(grid, "res") else abs(grid.transform.a), inside, V["twi_clamp_deg"], nd) if (twi is not None and acc is not None) else (None, None))
    groups = {"S2 class 1 remaining (union over dates)": u2, "S2 class 8 on DEM signature (union over dates)": u8, "S1WC-1 class 1 (union = class1 + class8)": u1}
    tstats = pd.DataFrame(w2.terrain_stats(layers, groups, valid_cells, clamped, nd)); near = None
    if drain is not None and (drain == 1).any():
        near = ndi.distance_transform_edt(~(drain == 1)) <= 3
        extra = [{"variant": "all cells", "layer": "share within 3 cells (90 m) of mapped drainage", "group": g, "n_cells": int(m.sum()), "p50": round(float(near[m].mean()), 4)} for g, m in {**groups, "reference: all valid AOI cells": valid_cells}.items()]
        tstats = pd.concat([tstats, pd.DataFrame(extra)], ignore_index=True)
    if clamped is not None:
        tc = [{"quantity": "TWI clamp threshold (deg)", "value": V["twi_clamp_deg"]}, {"quantity": "clamped AOI cells (slope < clamp)", "value": int((clamped & inside).sum())}, {"quantity": "clamped share of AOI (%)", "value": round(100 * (clamped & inside).sum() / n_aoi, 3)},
              {"quantity": "stored-TWI vs clamp-formula consistency failures among clamped cells", "value": clamp_bad}]
        for g, m in groups.items(): tc += [{"quantity": f"{g}: cells", "value": int(m.sum())}, {"quantity": f"{g}: share on clamped cells (%)", "value": round(100 * (m & clamped).sum() / max(m.sum(), 1), 2)}]
        tc.append({"quantity": "note", "value": "TWI = ln(acc*res/max(tan(slope), tan(clamp))); on clamped cells TWI depends only on flow accumulation. 'clamp-excluded' rows in the terrain table drop these cells from group and reference."}); twc = pd.DataFrame(tc)
    else: twc = pd.DataFrame([{"quantity": "TWI clamp analysis", "value": "skipped: TWI and/or flow accumulation raster not available (nothing was zero-filled)"}])
    # ---- write
    for p in outs.values(): p.parent.mkdir(parents=True, exist_ok=True)
    ba.to_csv(outs["before_after"], index=False); cc.to_csv(outs["class_counts"], index=False); comp.to_csv(outs["comparability"], index=False); sigsum.to_csv(outs["signature"], index=False); pd.DataFrame(sens).to_csv(outs["signature_sens"], index=False)
    twc.to_csv(outs["twi_clamp"], index=False); tstats.to_csv(outs["terrain"], index=False); pd.DataFrame(qa_rows).to_csv(outs["input_qa"], index=False); pd.DataFrame(reg).to_csv(outs["regression"], index=False)
    from src.geospatial.grid import write_raster
    for d in dates: write_raster(outs[f"ras_class_{d}"], c2[d], grid, 255, f"S1WC-2 class, acquisition {d} UTC (S1WC-1 codes 0-7,254,255 unchanged; 8 = dark candidate on provisional DEM-indicated flattened-water signature). NOT a flood map", "uint8")
    write_raster(outs["ras_signature"], np.where(inside, np.where(zero, 1, np.where(plateau, 2, 0)), 255).astype("uint8"), grid, 255, "provisional DEM-indicated flattened-water signature: 0 none, 1 DEM==0, 2 constant-elevation plateau, 255 outside AOI. NOT a confirmed water mask", "uint8")
    write_raster(outs["ras_t1_count"], wc.date_count(np.stack([c2[d] for d in dates]), 1, inside), grid, 255, "COUNT OF DATES (not an event map) as class 1 in S1WC-2, 255 outside AOI", "uint8")
    write_raster(outs["ras_t8_count"], wc.date_count(np.stack([c2[d] for d in dates]), 8, inside), grid, 255, "COUNT OF DATES (not an event map) as class 8 in S1WC-2, 255 outside AOI", "uint8")
    make_figures(outs, dates, ba, c2, inside, grid)
    after2 = {k: sp.sha256_file(p) for k, p in in_files.items()}; preserved = after2 == before
    info = {"fp_run": fp_run, "fps": fps, "n_aoi": n_aoi, "mism": mism, "preserved": preserved, "outs": {k: str(v) for k, v in outs.items()}, "indir": str(indir), "outdir": str(outdir), "meta_present": meta_present, "ref_present": {k: str(v) for k, v in ref_present.items()},
            "ref_absent": [k for k in refs if k not in ref_present], "s1wc1_compared": sorted(s1_arr), "regression": reg}
    outs["report"].write_text(build_report(info, dates, ba, comp, sigsum, pd.DataFrame(sens), twc, tstats, cfg2, V, P), encoding="utf-8")
    out_hashes = {k: sp.sha256_file(p) for k, p in outs.items() if k != "manifest"}
    man = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - t0, 1), "script": "scripts/s1_water_candidates_v2_review.py", "version": cfg2["version"], "dates": dates, "date_meaning": cfg1["date_meaning"],
           "s1wc1_parameters_reused": P, "v2_parameters": V, "aoi_fingerprint": {"metadata": fps, "loaded_aoi": fp_run, "aoi_cells": n_aoi}, "metadata_present": meta_present, "reference_layers_used": info["ref_present"], "reference_layers_absent": info["ref_absent"],
           "s1wc1_class_rasters_compared": info["s1wc1_compared"], "regression_vs_s1wc1": reg, "input_sha256_before": before, "input_sha256_after_all_outputs": after2, "input_hashes_unchanged": preserved, "output_sha256": out_hashes,
           "valid_tif_vs_rule_mismatch_cells": mism, "software": V1.versions(), "status_json_modified": False, "caveats": cfg2["caveats"], "claims": "provisional S1-derived dark-backscatter candidates; not a flood extent; not validated; no accuracy metric; DEM signature is provisional, not a water mask",
           "outputs": {k: str(v) for k, v in outs.items() if k != "manifest"}}
    outs["manifest"].write_text(json.dumps(man, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return (0 if preserved else 3), info


def make_figures(outs, dates, ba, c2, inside, grid):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    cols = {0: "#eeeeee", 1: "#2166ac", 8: "#e08214", 2: "#084081", 3: "#bf812d", 4: "#9ecae1", 5: "#d9f0d3", 6: "#fdae61", 7: "#f4a582", 254: "#d73027"}
    short = {0: "valid, not dark", 1: "class 1 candidate (remaining)", 8: "class 8: dark on provisional DEM-indicated flattened-water signature", 2: "persistently dark (excluded)", 3: "slope-excluded", 4: "small cluster", 5: "VV-only dark", 6: "persistence unassessable", 7: "slope unknown", 254: "invalid/unknown"}
    codes = list(cols); cm = ListedColormap([cols[c] for c in codes]); idx = {c: i for i, c in enumerate(codes)}
    fig, axs = plt.subplots(2, 4, figsize=(15, 9.5))
    for ax, d in zip(axs.ravel(), dates):
        img = np.full(c2[d].shape, np.nan)
        for c in codes: img[c2[d] == c] = idx[c]
        ax.imshow(img, cmap=cm, vmin=-0.5, vmax=len(codes) - 0.5, extent=grid.extent, interpolation="nearest"); ax.set_xticks([]); ax.set_yticks([]); ax.set_title(f"acquisition {d} UTC", fontsize=8)
    fig.legend(handles=[Patch(color=cols[c], label=short[c]) for c in codes], loc="lower center", ncol=3, fontsize=8)
    fig.suptitle("S1WC-2 per-date classes. NOT a flood map; not validated; class 8 is a provisional DEM-indicated flattened-water signature; provisional OSM AOI", fontsize=10); fig.tight_layout(rect=(0, 0.1, 1, 0.96)); fig.savefig(outs["fig_multiples"], dpi=80); plt.close(fig)
    b = ba[ba.date_utc.isin(dates)]; fig, ax = plt.subplots(figsize=(10, 5)); x = np.arange(len(dates))
    ax.bar(x, b.s2_class1_candidates_remaining, color=cols[1], label="class 1 remaining"); ax.bar(x, b.s2_class8_on_dem_signature, bottom=b.s2_class1_candidates_remaining, color=cols[8], label="class 8 on DEM signature (was class 1 in S1WC-1)")
    ax.set_xticks(x); ax.set_xticklabels([d[5:] for d in dates]); ax.set_ylabel("cells"); ax.legend(fontsize=8); ax.set_title("S1WC-1 class 1 split by the provisional DEM signature (bar height = S1WC-1 count). Counts are not comparable across dates (radiometric offsets); not flood area", fontsize=8)
    fig.tight_layout(); fig.savefig(outs["fig_before_after"], dpi=110); plt.close(fig)


def build_report(info, dates, ba, comp, sigsum, sens, twc, tstats, cfg2, V, P):
    L = []; ad = L.append; md = V1.md_table
    ad("# Sentinel-1 2021 dark-backscatter candidate product, S1WC-2 (additive refinement of S1WC-1)\n")
    ad("**PROVISIONAL, S1-DERIVED, NOT VALIDATED.** Not a confirmed flood extent, not independent ground truth, not an event map; no accuracy, precision, recall, F1 or IoU. The remaining class-1 cells are **not confirmed floodwater**, and a class-8 cell is not a confirmed permanent-water cell either.\n")
    ad("## What S1WC-2 changes\n")
    ad("- One new class, **8**: a dark candidate (S1WC-1 class 1) that lies on a **provisional DEM-indicated flattened-water signature**. Classes 0-7, 254 and 255 are unchanged; class1(S2) + class8(S2) = class1(S1WC-1) on every date (checked, see the regression table).")
    ad(f"- Signature: DEM == 0 exactly, or a non-zero constant-elevation plateau (4-neighbour component of identical DEM values, >= {V['min_plateau_cells']} cells). A generic slope == 0 rule is not used. It is **not** a confirmed permanent-water mask, **not** a flood exclusion, and **not** the Copernicus Water Body Mask (not used).")
    ad("- No radiometric normalisation, no new threshold, no terrain flattening, no flood label. S1WC-1 parameters are reused verbatim: " + ", ".join(f"{k}={v}" for k, v in P.items()) + ".")
    ad("\n## Before / after (cells)\n"); ad(md(ba[["date_utc", "s1wc1_class1_candidates", "s2_class1_candidates_remaining", "s2_class8_on_dem_signature", "class1_plus_class8_equals_s1wc1", "class8_share_of_s1wc1_class1_pct"]]))
    ad("\nThe union row counts cells that are class 1 (or 8) on at least one date; it is **not** an event extent.")
    ad("\n## Per-date comparability next to the counts (descriptive; nothing is corrected)\n"); ad(md(comp.drop(columns=["interpretation_note"])))
    ad("\nDate-level radiometric offsets (stable-cell shifts, VV-VH change and the spatial spread across 0.9 km blocks) mean that fixed-threshold counts are **not comparable across dates** and cannot be read as flood dynamics. No defensible correction exists with the supplied data (S1WC-1 Stage A radiometric investigation).")
    ad("\n## DEM signature summary\n"); ad(md(sigsum)); ad("\nPlateau-size sensitivity (reported only; the value used was fixed a priori):\n"); ad(md(sens))
    ad("\n## TWI clamp\n"); ad(md(twc))
    ad("\n## Terrain context (descriptive; not evidence of flooding)\n"); ad(md(tstats[tstats.layer.isin(["slope_deg", "dem_elevation_m", "twi"])][["variant", "layer", "group", "n_cells", "p5", "p25", "p50", "p75", "p95"]]))
    ad("\nOn clamped cells TWI depends only on flow accumulation; the clamp-excluded rows drop them. Terrain association is context, not validation.")
    ad("\n## Caveats\n"); [ad("- " + c) for c in cfg2["caveats"]]
    ad("- No independent flood reference exists in this workflow; nothing here is validation or accuracy evidence. The AOI is the provisional OSM boundary.")
    ad("\n## Regression against S1WC-1\n"); ad(md(pd.DataFrame(info["regression"])))
    ad("\nS1WC-1 stored class rasters compared: " + (", ".join(info["s1wc1_compared"]) if info["s1wc1_compared"] else "none (the S1WC-1 output directory was not available; S1WC-1 classes were recomputed in-process with the unchanged S1WC-1 library)."))
    ad("\n## Input preservation\n"); ad(f"SHA-256 of every input (S1 products, metadata if present, reference rasters, S1WC-1 class rasters if used, configs, AOI files, settings) was taken before parsing and after all outputs: **{'IDENTICAL' if info['preserved'] else 'CHANGED'}**. Output hashes are in the manifest. status.json not modified; nothing overwritten.")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default=OUT_DEFAULT); ap.add_argument("--indir", default=None); ap.add_argument("--s1wc1-dir", default=None); ap.add_argument("--allow-missing-metadata", action="store_true")
    a = ap.parse_args(); root = paths.ROOT; rp = lambda x: Path(x) if Path(x).is_absolute() else root / x                 # noqa: E731
    pre_stops, pre = preflight()
    if pre_stops:
        print("STOP - nothing was written."); [print("  -", x) for x in pre_stops]; return 2
    cfg2 = json.loads(Path(pre["paths"][CFG_LABEL]).read_text(encoding="utf-8")); cfg1 = json.loads(Path(pre["paths"][BASE_LABEL]).read_text(encoding="utf-8")); wgs, _, _ = load_study_area(); grid = master_grid()
    rc, info = run(rp(a.indir or cfg1["input_dir"]), rp(a.outdir), cfg2, cfg1, grid, wgs.union_all(), root, cfg1["dates"], shared_dirs=(paths.OUT_REP, paths.OUT_TAB, paths.OUT_FIG), pre=pre, allow_missing_metadata=a.allow_missing_metadata, s1wc1_dir=rp(a.s1wc1_dir or cfg2["s1wc1_output_dir"]))
    if rc == 2:
        print("STOP - nothing was written."); [print("  -", x) for x in info["stops"]]; return 2
    if rc == 3: print("ERROR: input hashes changed:", info.get("stops")); return 3
    print(f"done. outputs: {info['outdir']}\n  input SHA-256 before/after: {'IDENTICAL' if info['preserved'] else 'CHANGED'}\n  S1WC-1 rasters compared: {len(info['s1wc1_compared'])}\n  report: {info['outs']['report']}"); return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
