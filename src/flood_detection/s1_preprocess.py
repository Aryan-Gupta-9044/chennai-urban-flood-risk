"""M4C - Sentinel-1 date-level preprocessing helpers (pure numpy/rasterio/shapely; Earth Engine calls live in scripts/s1_preprocess_2021.py).
PREPROCESSING ONLY: no flood classification, no flood extent, no baseline designation, no validation, no machine learning.

Overlap rule (deterministic): for each polarisation independently, a pixel's value is the LINEAR-POWER mean of the slices that have valid data there,
converted back to dB. One valid slice -> that slice; none -> NoData (NaN here / -9999 on disk). Never zero-filled. The result does not depend on slice order
(values are sorted before summation, so even floating-point results are permutation-invariant)."""
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

NODATA = -9999.0
POLS = ("VV", "VH")
REQUIRED_META = ["date_utc", "source_scene_ids", "collection", "platform", "pass", "rel_orbit", "pols_present", "overlap_rule", "resampling_default", "min_valid_fraction",
                 "output_crs", "output_resolution_m", "output_transform", "output_shape", "nodata_value", "units", "ee_processing_claims", "dem_note", "run_signature",
                 "software", "aoi_fingerprint", "created_utc", "files", "status"]


# ------------------------------------------------------------------ radiometry / overlap rule
def db_to_lin(db): return np.power(10.0, np.asarray(db, dtype="float64") / 10.0)


def lin_to_db(lin): return 10.0 * np.log10(np.asarray(lin, dtype="float64"))


def combine_slices(stack_db):
    """Overlap rule on a list of 2-D dB arrays (NaN = invalid). Returns (dB mean-of-valid in linear power, n_valid_slices). Order-independent."""
    a = np.stack([np.asarray(x, dtype="float64") for x in stack_db])
    valid = np.isfinite(a) & (a != NODATA)
    lin = np.where(valid, db_to_lin(np.where(valid, a, 0.0)), np.nan)
    lin = np.sort(lin, axis=0)                                  # NaN sorts last; fixed order -> bitwise permutation invariance
    n = valid.sum(axis=0)
    tot = np.nansum(lin, axis=0)
    out = np.full(n.shape, np.nan)
    ok = n > 0
    out[ok] = lin_to_db(tot[ok] / n[ok])
    return out, n


def overlap_diff_stats(a_db, b_db):
    """Seam/overlap diagnostic: dB difference between two slices where BOTH are valid. n=0 (no overlap) -> values None (not 0)."""
    a, b = np.asarray(a_db, dtype="float64"), np.asarray(b_db, dtype="float64")
    m = np.isfinite(a) & np.isfinite(b)
    n = int(m.sum())
    if n == 0:
        return {"n_overlap_px": 0, "mean_diff_db": None, "mean_abs_diff_db": None, "p95_abs_diff_db": None}
    d = a[m] - b[m]
    return {"n_overlap_px": n, "mean_diff_db": float(d.mean()), "mean_abs_diff_db": float(np.abs(d).mean()), "p95_abs_diff_db": float(np.percentile(np.abs(d), 95))}


def to_nodata(arr, nodata=NODATA):
    """float32 array with invalid -> explicit NoData sentinel. Never 0 (0 dB is a legitimate backscatter value)."""
    a = np.asarray(arr, dtype="float64")
    return np.where(np.isfinite(a), a, nodata).astype("float32")


def valid_mask(db, validfrac, min_frac, nodata=NODATA):
    """Product validity: finite, not the sentinel, and at least `min_frac` of the 30 m cell had valid source pixels."""
    db = np.asarray(db, dtype="float64"); vf = np.asarray(validfrac, dtype="float64")
    return np.isfinite(db) & (db != nodata) & np.isfinite(vf) & (vf >= min_frac)


# ------------------------------------------------------------------ identity / plan
def utc_date(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).date().isoformat()


def plan_from_coverage(rows, dates):
    """{date: [slice ids]} from the M4B date-level coverage rows (semicolon-joined `slice_ids`). A requested date missing from the file is an error."""
    by = {}
    for r in rows:
        by.setdefault(str(r["date_utc"])[:10], []).append(r)
    plan, missing = {}, []
    for d in dates:
        hit = by.get(d)
        if not hit or len(hit) != 1:
            missing.append(d); continue
        plan[d] = [s for s in str(hit[0]["slice_ids"]).split(";") if s]
    if missing:
        raise ValueError(f"dates not (uniquely) present in the date-level coverage file: {missing}")
    return plan


def verify_scene_identity(date, expected_ids, scenes, exp):
    """Problems (empty = ok). scenes = per-slice dicts from Earth Engine: id, t (ms), platform ('A'/'SENTINEL-1A'), pass, rel_orbit, mode, bands (list)."""
    p = []
    got = sorted(s.get("id") for s in scenes)
    if got != sorted(expected_ids):
        p.append(f"scene ids {got} != inventory ids {sorted(expected_ids)}")
    for s in scenes:
        if s.get("t") is None or utc_date(s["t"]) != date: p.append(f"{s.get('id')}: acquisition date {None if s.get('t') is None else utc_date(s['t'])} != {date}")
        pf = str(s.get("platform")); pf = f"SENTINEL-1{pf.upper()[-1]}" if len(pf) == 1 else pf
        if pf != exp["platform"]: p.append(f"{s.get('id')}: platform {pf} != {exp['platform']}")
        if s.get("pass") != exp["pass"]: p.append(f"{s.get('id')}: pass {s.get('pass')} != {exp['pass']}")
        if s.get("rel_orbit") != exp["rel_orbit"]: p.append(f"{s.get('id')}: relative orbit {s.get('rel_orbit')} != {exp['rel_orbit']}")
        if s.get("mode") != exp["mode"]: p.append(f"{s.get('id')}: mode {s.get('mode')} != {exp['mode']}")
    if len(scenes) != exp["n_slices"]: p.append(f"{len(scenes)} slices != expected {exp['n_slices']}")
    return p


def pol_plan(scenes, pols=POLS):
    """Per polarisation: producible only if EVERY slice has the band. A missing band is reported, never filled or substituted."""
    out = {}
    for pol in pols:
        miss = [s.get("id") for s in scenes if pol not in (s.get("bands") or [])]
        out[pol] = {"producible": not miss and bool(scenes), "missing_in": miss}
    return out


# ------------------------------------------------------------------ run signature / state / reruns
def run_signature(date, slice_ids, params, grid, aoi_fingerprint, collection):
    blob = json.dumps({"date": date, "slices": sorted(slice_ids), "params": params, "grid": [grid.crs, [round(x, 9) for x in list(grid.transform)[:6]], list(grid.shape)],
                       "aoi": aoi_fingerprint, "collection": collection}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_state(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(path, state):
    path = Path(path); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8"); os.replace(tmp, path)     # atomic


def files_intact(outdir, rec):
    """True only if every recorded file exists and still matches its recorded SHA-256."""
    fl = rec.get("files") or {}
    return bool(fl) and all((Path(outdir) / n).exists() and sha256_file(Path(outdir) / n) == h for n, h in fl.items())


def decide(rec, signature, outdir):
    """'RUN' (no record / failed / incomplete), 'SKIP' (same signature, files intact), 'STALE' (signature changed), 'REPAIR' (same signature, file missing/changed)."""
    if not rec or rec.get("status") not in ("EXPORTED", "QA_PASS", "QA_FAIL"):
        return "RUN"
    if rec.get("signature") != signature:
        return "STALE"
    return "SKIP" if files_intact(outdir, rec) else "REPAIR"


def supersede(outdir, rec):
    """Move (never delete) the files of a stale record into _superseded/<old signature>/."""
    dst = Path(outdir) / "_superseded" / str(rec.get("signature", "unknown")); dst.mkdir(parents=True, exist_ok=True)
    moved = []
    for n in list((rec.get("files") or {}).keys()) + [rec.get("meta_file")]:
        if n and (Path(outdir) / n).exists():
            shutil.move(str(Path(outdir) / n), str(dst / n)); moved.append(n)
    return moved


def run_dates(dates, sigs, exporter, outdir, state_path, force_stale=False, now=None):
    """Drive the per-date export with failure isolation and safe reruns. exporter(date) -> {'files': {name: path-relative-to-outdir}, 'meta_file': name, ...}
    (it must have written the files). A failure of one date is recorded (status FAILED + error) and never stops the others or marks anything successful."""
    outdir = Path(outdir); state = load_state(state_path); result = {}
    for d in dates:
        rec = state.get(d); act = decide(rec, sigs[d], outdir)
        if act == "SKIP":
            result[d] = "SKIPPED_UP_TO_DATE"; continue
        if act == "STALE":
            if not force_stale:
                result[d] = "STALE_NOT_RERUN"; state[d] = dict(rec, stale_signature_now=sigs[d]); save_state(state_path, state); continue
            supersede(outdir, rec)
        try:
            out = exporter(d)
            files = {n: sha256_file(outdir / n) for n in out["files"]}
            state[d] = {"status": "EXPORTED", "signature": sigs[d], "files": files, "meta_file": out.get("meta_file"), "error": None, "time_utc": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
            result[d] = "EXPORTED"
        except Exception as e:                                                # noqa: BLE001 - isolate the failure per date
            state[d] = {"status": "FAILED", "signature": sigs[d], "files": {}, "error": f"{type(e).__name__}: {str(e)[:300]}", "time_utc": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
            result[d] = "FAILED"
        save_state(state_path, state)
    return result


def metadata_problems(md):
    """Missing or empty required metadata fields (empty list = complete)."""
    return [k for k in REQUIRED_META if k not in md or md[k] in (None, "", [], {})]


# ------------------------------------------------------------------ QA
def qa_product(db, vf, grid_info, expected, inside, qa_cfg, min_frac, source=None, nodata=NODATA):
    """Technical QA of one polarisation product on the master grid. grid_info/expected = {'crs','transform'(6-tuple),'shape'}; inside = bool AOI mask on the grid.
    Returns (metrics dict, failures list). 'QA_PASS' means these technical checks passed - nothing about flood or accuracy."""
    f = []
    if tuple(grid_info["shape"]) != tuple(expected["shape"]): f.append(f"shape {grid_info['shape']} != master grid {expected['shape']}")
    if str(grid_info["crs"]).upper().replace("EPSG:", "") != str(expected["crs"]).upper().replace("EPSG:", ""): f.append(f"CRS {grid_info['crs']} != {expected['crs']}")
    if any(abs(a - b) > 1e-6 for a, b in zip(grid_info["transform"], expected["transform"])): f.append("transform differs from the master grid")
    db = np.asarray(db, dtype="float64"); vf = np.asarray(vf, dtype="float64")
    if db.shape != tuple(expected["shape"]) or inside.shape != db.shape:
        return {"checked": False}, f + ["cannot compute statistics: array shape mismatch"]
    nan_inf = int((~np.isfinite(db)).sum())            # NaN/inf in the file (NoData must be the sentinel, not NaN)
    vm = valid_mask(db, vf, min_frac, nodata)
    n_in = int(inside.sum()); n_valid_in = int((vm & inside).sum())
    valid_pct = 100.0 * n_valid_in / n_in if n_in else None
    if nan_inf: f.append(f"{nan_inf} NaN/inf cells in the file (NoData should be the sentinel {nodata})")
    lo, hi = qa_cfg["extreme_low_db"], qa_cfg["extreme_high_db"]
    v = db[vm & inside]
    lowc, highc = int((v < lo).sum()), int((v > hi).sum())
    zeros_suspect = int(((db == 0.0) & ~vm).sum())      # exact 0 where the product is invalid: sign of a zero-fill
    if zeros_suspect: f.append(f"{zeros_suspect} cells are exactly 0 but flagged invalid (possible zero-fill)")
    if valid_pct is None or valid_pct < qa_cfg["min_aoi_valid_pct"]: f.append(f"AOI valid {valid_pct} % < {qa_cfg['min_aoi_valid_pct']} %")
    m = {"checked": True, "aoi_cells": n_in, "aoi_valid_cells": n_valid_in, "aoi_valid_pct": None if valid_pct is None else round(valid_pct, 4), "nodata_cells_in_aoi": int((inside & ~vm).sum()),
         "nan_inf_cells": nan_inf, "extreme_low_cells": lowc, "extreme_high_cells": highc, "extreme_thresholds_db": [lo, hi]}
    if v.size:
        lin = db_to_lin(v)
        m.update({"mean_db": float(v.mean()), "std_db": float(v.std()), "p01_db": float(np.percentile(v, 1)), "p50_db": float(np.percentile(v, 50)), "p99_db": float(np.percentile(v, 99)),
                  "mean_linear": float(lin.mean()), "min_db": float(v.min()), "max_db": float(v.max())})
        if source and source.get("mean_linear"):
            r = m["mean_linear"] / source["mean_linear"]; m["power_ratio_out_over_source"] = float(r)
            if abs(r - 1.0) > qa_cfg["power_ratio_tol"]: f.append(f"mean linear power ratio output/source {r:.3f} outside 1 +/- {qa_cfg['power_ratio_tol']}")
        elif source is not None:
            m["power_ratio_out_over_source"] = None
    else:
        f.append("no valid cells inside the AOI")
    return m, f


def seam_zone(grid, fp_a_wgs, fp_b_wgs, aoi_wgs, width_m):
    """Boolean grid mask of the seam zone: within `width_m` of BOTH slice footprints (their shared edge), restricted to the AOI. Footprints from the inventory."""
    import geopandas as gpd
    from rasterio import features
    P = lambda g: gpd.GeoSeries([g], crs=4326).to_crs(grid.crs).iloc[0]       # noqa: E731
    z = P(fp_a_wgs).buffer(width_m).intersection(P(fp_b_wgs).buffer(width_m)).intersection(P(aoi_wgs))
    if z.is_empty:
        return np.zeros(grid.shape, dtype=bool)
    return features.geometry_mask([z], out_shape=grid.shape, transform=grid.transform, invert=True, all_touched=True)


def seam_diag(db, valid, zone, inside, flag_db):
    """Descriptive seam diagnostic: valid share and mean in the seam zone versus the rest of the AOI. A difference can be real land cover; it is a flag to
    LOOK at the preview, not proof of a seam artefact."""
    z = zone & inside; r = inside & ~zone
    n = int(z.sum())
    if n == 0:
        return {"seam_zone_cells": 0, "seam_zone_valid_pct": None, "seam_zone_mean_db": None, "rest_mean_db": None, "zone_minus_rest_db": None, "flag": None}
    zv = z & valid; rv = r & valid
    zm = float(np.mean(db[zv])) if zv.any() else None; rm = float(np.mean(db[rv])) if rv.any() else None
    d = None if zm is None or rm is None else zm - rm
    return {"seam_zone_cells": n, "seam_zone_valid_pct": round(100.0 * int(zv.sum()) / n, 3), "seam_zone_mean_db": zm, "rest_mean_db": rm, "zone_minus_rest_db": d,
            "flag": None if d is None else abs(d) > flag_db}


def preview_png(path, db, valid, title, extent=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    a = np.where(valid, db, np.nan)
    fin = a[np.isfinite(a)]
    lo, hi = (np.percentile(fin, 2), np.percentile(fin, 98)) if fin.size else (-25, 0)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    im = ax.imshow(a, cmap="gray", vmin=lo, vmax=hi, extent=extent)
    ax.set_title(title, fontsize=9); fig.colorbar(im, ax=ax, shrink=0.8, label="dB (2-98 % stretch; invalid = blank)")
    fig.savefig(path, dpi=110, bbox_inches="tight"); plt.close(fig)


def download_with_retry(fn, retries=3, sleep=5.0, sleeper=None):
    """Call fn() up to `retries` times (Earth Engine requests fail transiently). Raises the LAST error; never returns partial data."""
    import time
    sleeper = sleeper or time.sleep; last = None
    for k in range(retries):
        try:
            return fn()
        except Exception as e:                                                # noqa: BLE001
            last = e
            if k < retries - 1: sleeper(sleep * (k + 1))
    raise RuntimeError(f"request failed after {retries} attempts: {type(last).__name__}: {str(last)[:200]}") from last


# ================================================================== M4C single-date QA corrections: status logic, metadata finalisation, diagnostics
def date_status(pol_rows):
    """Final QA state of ONE date from its per-polarisation QA rows: 'QA_PASS' only if every polarisation is QA_PASS; otherwise 'QA_FAIL' when any
    row failed QA or a polarisation was not produced; the run states FAILED / STALE / NOT_RUN pass through (a missing polarisation never counts as pass)."""
    st = [r["status"] for r in pol_rows]
    if not st: return "NOT_RUN"
    for s in ("FAILED", "STALE", "NOT_RUN"):
        if s in st: return s
    return "QA_PASS" if all(s == "QA_PASS" for s in st) and len(st) == len(POLS) else "QA_FAIL"


def overall_status(rows, configured_dates, sigs):
    """Overall M4C state from the MERGED QA rows of ALL configured dates (not just the dates of the current run).
    complete = every configured date has VV and VH QA_PASS with the CURRENT run signature (a row from an older configuration does not count).
    Returns {'complete': bool, 'per_date': {date: state}, 'n_pass': int, 'n_total': int, 'missing': [dates without any current QA row]}"""
    per, missing = {}, []
    for d in configured_dates:
        rs = [r for r in rows if r.get("date_utc") == d and (r.get("run_signature") in (None, sigs.get(d)) or r.get("status") in ("FAILED", "NOT_RUN", "STALE"))]
        stale = [r for r in rows if r.get("date_utc") == d and r.get("run_signature") not in (None, sigs.get(d)) and r.get("status") not in ("FAILED", "NOT_RUN", "STALE")]
        if not rs and stale: per[d] = "STALE"
        elif not rs: per[d] = "NOT_RUN"; missing.append(d)
        else: per[d] = date_status(rs)
    n_pass = sum(1 for v in per.values() if v == "QA_PASS")
    return {"complete": n_pass == len(configured_dates) and len(configured_dates) > 0, "per_date": per, "n_pass": n_pass, "n_total": len(configured_dates), "missing": missing}


def merge_qa(existing_rows, new_rows):
    """Merge QA rows: rows of dates present in `new_rows` replace the old ones; rows of every other date are kept (a single-date run never drops the others)."""
    redone = {r["date_utc"] for r in new_rows}
    keep = [r for r in existing_rows if r.get("date_utc") not in redone]
    return sorted(keep + list(new_rows), key=lambda r: (r["date_utc"], r["pol"]))


def finalize_metadata(meta_path, date_state, pol_rows, qa_utc):
    """Write the FINAL QA state into a date's metadata JSON (export state is kept as `export_status`). Only the metadata file changes - never a raster.
    Returns the new SHA-256 so the run state can be updated and the edit is not mistaken for tampering."""
    p = Path(meta_path); md = json.loads(p.read_text(encoding="utf-8"))
    md.setdefault("export_status", md.get("status"))
    md["status"] = date_state
    md["qa"] = {"date_state": date_state, "qa_utc": qa_utc, "per_pol": {r["pol"]: {"status": r["status"], "failures": r.get("failures", "")} for r in pol_rows},
                "note": "QA_PASS = technical checks only (grid, valid share, NoData, extremes, source-vs-output power, metadata). Not a flood, accuracy or baseline statement."}
    tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(md, indent=1), encoding="utf-8"); os.replace(tmp, p)
    return sha256_file(p)


def parse_s1_id(scene_id):
    """Start/stop UTC times and datatake id from a Sentinel-1 scene id like S1A_IW_GRDH_1SDV_20211116T003147_20211116T003212_040589_04D094_DB41."""
    parts = str(scene_id).split("_")
    if len(parts) < 9: raise ValueError(f"unrecognised Sentinel-1 id: {scene_id}")
    f = lambda s: datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)   # noqa: E731
    return {"start": f(parts[4]), "stop": f(parts[5]), "abs_orbit": parts[6], "datatake": parts[7]}


def slice_time_relation(id_a, id_b):
    """Time relation of two slices of one data take, ordered by start: gap_s = start(next) - stop(previous). 0 = contiguous (shared cut time), >0 = a gap,
    <0 = the acquisitions overlap in time. Also whether both ids belong to the same data take."""
    a, b = sorted((parse_s1_id(id_a), parse_s1_id(id_b)), key=lambda x: x["start"])
    return {"first_stop": a["stop"].isoformat(), "second_start": b["start"].isoformat(), "gap_s": (b["start"] - a["stop"]).total_seconds(),
            "same_datatake": a["datatake"] == b["datatake"] and a["abs_orbit"] == b["abs_orbit"]}


def footprint_overlap_geometry(fp_a_wgs, fp_b_wgs, aoi_wgs, area_crs="EPSG:32644"):
    """Footprint-level overlap of two slices INSIDE the AOI, in metres: area, and the sliver's rotated-rectangle width/length (width = short side).
    This is a polygon (outline) property; it says nothing about whether valid pixels overlap."""
    import geopandas as gpd
    P = lambda g: gpd.GeoSeries([g], crs=4326).to_crs(area_crs).iloc[0]   # noqa: E731
    o = P(fp_a_wgs).intersection(P(fp_b_wgs)).intersection(P(aoi_wgs))
    if o.is_empty or o.area == 0: return {"overlap_area_m2": 0.0, "overlap_width_m": 0.0, "overlap_length_m": 0.0}
    r = o.minimum_rotated_rectangle; xs, ys = r.exterior.coords.xy
    e = sorted([float(np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i])) for i in range(2)])
    return {"overlap_area_m2": float(o.area), "overlap_width_m": e[0], "overlap_length_m": e[1]}


def exceedance_table(db, valid, inside, thresholds=(0.0, 3.0, 5.0, 8.0, 10.0)):
    """Counts and shares above several dB thresholds (no single 'correct' cut-off is implied)."""
    v = valid & inside; n_in = int(inside.sum()); n_v = int(v.sum()); out = []
    for t in thresholds:
        c = int((v & (db > t)).sum())
        out.append({"threshold_db": t, "cells": c, "pct_of_aoi_cells": round(100.0 * c / n_in, 4) if n_in else None, "pct_of_valid_aoi_cells": round(100.0 * c / n_v, 4) if n_v else None})
    return out


def high_value_diagnostics(db, valid, inside, grid, threshold_db=5.0, other_db=None, seam=None, block=(10, 5)):
    """Spatial diagnostic of cells with dB > threshold. NOTHING is clamped, removed or masked: inputs are only read. Returns (summary, components, blocks, labels).
    components = connected groups (8-neighbour) with size, area, centroid and bbox in grid coordinates; blocks = counts on a block x block lattice over the grid."""
    from scipy import ndimage as ndi
    m = valid & inside & (db > threshold_db)
    lab, n = ndi.label(m, structure=np.ones((3, 3), int))
    sizes = np.bincount(lab.ravel())[1:] if n else np.array([], int)
    cells = int(m.sum()); n_in = int(inside.sum()); n_v = int((valid & inside).sum())
    comps = []
    if n:
        idx = np.arange(1, n + 1)
        cen = ndi.center_of_mass(m, lab, idx); sl = ndi.find_objects(lab)
        for k, (c, s, size) in enumerate(zip(cen, sl, sizes), 1):
            r0, r1, c0, c1 = s[0].start, s[0].stop, s[1].start, s[1].stop
            comps.append({"component": k, "cells": int(size), "area_km2": round(size * grid.res ** 2 / 1e6, 6),
                          "centroid_x": grid.transform.c + (c[1] + 0.5) * grid.res, "centroid_y": grid.transform.f - (c[0] + 0.5) * grid.res,
                          "bbox_rows": [int(r0), int(r1)], "bbox_cols": [int(c0), int(c1)], "max_db": float(db[sl[k - 1]][lab[sl[k - 1]] == k].max())})
    bins = [(1, 1), (2, 4), (5, 9), (10, 49), (50, 199), (200, 10 ** 9)]
    hist = {f"{a}-{b if b < 10 ** 9 else 'inf'}": int(((sizes >= a) & (sizes <= b)).sum()) for a, b in bins}
    H, W = db.shape; br, bc = block
    blocks = []
    for i in range(br):
        for j in range(bc):
            r0, r1 = i * H // br, (i + 1) * H // br; c0, c1 = j * W // bc, (j + 1) * W // bc
            ins = int(inside[r0:r1, c0:c1].sum()); hv = int(m[r0:r1, c0:c1].sum())
            blocks.append({"block_row": i, "block_col": j, "aoi_cells": ins, "high_cells": hv, "high_pct_of_block_aoi": round(100.0 * hv / ins, 3) if ins else None})
    s = {"threshold_db": threshold_db, "high_cells": cells, "pct_of_aoi_cells": round(100.0 * cells / n_in, 4) if n_in else None, "pct_of_valid_aoi_cells": round(100.0 * cells / n_v, 4) if n_v else None,
         "n_components": int(n), "largest_component_cells": int(sizes.max()) if n else 0, "median_component_cells": float(np.median(sizes)) if n else 0.0,
         "cells_in_components_of_1": int((sizes == 1).sum()), "pct_cells_in_components_ge_10": round(100.0 * sizes[sizes >= 10].sum() / cells, 2) if cells else 0.0, "size_histogram": hist}
    if other_db is not None and cells:
        o = other_db[m]; ok = np.isfinite(o) & (o != NODATA)
        s["other_pol_mean_db_at_high_cells"] = float(o[ok].mean()) if ok.any() else None
        rest = (valid & inside & ~m) & np.isfinite(other_db) & (other_db != NODATA); s["other_pol_mean_db_elsewhere"] = float(other_db[rest].mean()) if rest.any() else None
    if seam is not None:
        s["high_cells_in_seam_zone"] = int((m & seam).sum()); s["seam_zone_share_of_aoi_pct"] = round(100.0 * int((seam & inside).sum()) / n_in, 4) if n_in else None
        s["high_share_in_seam_zone_pct"] = round(100.0 * int((m & seam).sum()) / max(int((seam & inside & valid).sum()), 1), 4)
    return s, comps, blocks, lab


WORLDCOVER = {10: "tree cover", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built-up", 60: "bare / sparse", 70: "snow / ice", 80: "permanent water", 90: "herbaceous wetland", 95: "mangroves", 100: "moss / lichen"}


def class_enrichment(mask, classes, valid_inside):
    """Where do the flagged cells fall by ancillary class? share_of_flagged vs share_of_valid_aoi (enrichment = ratio). Descriptive only: association, not cause."""
    out = []
    total_f = int((mask & valid_inside).sum()); total_v = int(valid_inside.sum())
    for c in sorted(int(x) for x in np.unique(classes[valid_inside])):
        inc = (classes == c) & valid_inside
        nv = int(inc.sum()); nf = int((inc & mask).sum())
        sv = 100.0 * nv / total_v if total_v else None; sf = 100.0 * nf / total_f if total_f else None
        out.append({"class": c, "name": WORLDCOVER.get(c, "unknown"), "valid_aoi_cells": nv, "flagged_cells": nf, "share_of_valid_aoi_pct": None if sv is None else round(sv, 3),
                    "share_of_flagged_pct": None if sf is None else round(sf, 3), "enrichment_ratio": None if not sv or sf is None else round(sf / sv, 3),
                    "pct_of_class_flagged": round(100.0 * nf / nv, 3) if nv else None})
    return out
