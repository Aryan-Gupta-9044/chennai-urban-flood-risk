"""Sentinel-1 2021 cross-date bright-VV persistence diagnostic (V2.3, exploratory, READ-ONLY on existing products).

DESCRIPTIVE ONLY. The thresholds and persistence classes below are EXPLORATORY ANALYTICAL DEFINITIONS, not validated flood thresholds. Nothing here is a flood
label, a flood extent, a baseline or a validation. Missing / invalid cells are never treated as 0 (they simply are not counted as valid on that date).
Pure numpy/pandas functions: no file writes, no Earth Engine."""
import hashlib
import re
from pathlib import Path
import numpy as np
import pandas as pd

NODATA = -9999.0
THRESHOLDS = (0.0, 3.0, 5.0, 8.0, 10.0)            # exploratory cut-offs (dB); PRIMARY is +5 (the project's existing QA 'extreme_high_db' value)
PRIMARY = 5.0
MIN_VALID_DATES = 6                                # a cell needs >= this many valid dates to be classified at all
CUTOFFS = (5, 6, 7)                                # persistent = bright on >= cut dates (sensitivity); 6 is the primary definition
PRIMARY_CUT = 6
PCTS = (1, 5, 25, 50, 75, 95, 99)
NOT_ASSESSED, NEVER, SINGLE, RARE, RECURRENT, PERSISTENT = 255, 0, 1, 2, 3, 4
CLASS_NAMES = {NEVER: "never bright", SINGLE: "single-date", RARE: "rare (2 dates)", RECURRENT: "recurrent", PERSISTENT: "persistent", NOT_ASSESSED: "not assessed (<min valid dates)"}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------------------------------------ grids / validity
def grid_problems(info, grid, tol=1e-6):
    """info: dict(shape, crs, transform(6-tuple), count, dtype, nodata) of ONE raster. Returns a list of problems vs the master grid (empty = compatible)."""
    p = []
    if tuple(info["shape"]) != tuple(grid.shape): p.append(f"shape {tuple(info['shape'])} != master grid {tuple(grid.shape)}")
    if str(info["crs"]).upper().replace("EPSG:", "") != str(grid.crs).upper().replace("EPSG:", ""): p.append(f"CRS {info['crs']} != {grid.crs}")
    if any(abs(a - b) > tol for a, b in zip(tuple(info["transform"])[:6], tuple(grid.transform)[:6])): p.append(f"transform {tuple(info['transform'])[:6]} != master {tuple(grid.transform)[:6]}")
    if info.get("count") != 1: p.append(f"{info.get('count')} bands != 1")
    return p


def cross_grid_problems(infos):
    """infos: {name: info}. Every raster must equal the first on shape / CRS / transform (so dates are directly comparable cell by cell)."""
    names = list(infos); out = []
    if not names: return out
    ref = infos[names[0]]
    for n in names[1:]:
        i = infos[n]
        if tuple(i["shape"]) != tuple(ref["shape"]) or str(i["crs"]) != str(ref["crs"]) or any(abs(a - b) > 1e-6 for a, b in zip(tuple(i["transform"])[:6], tuple(ref["transform"])[:6])):
            out.append(f"{n} differs from {names[0]} in shape/CRS/transform")
    return out


def valid_cells(db, validfrac, inside, min_frac, nodata=NODATA):
    """The product validity rule (finite, not the NoData sentinel, valid fraction >= min_frac) AND inside the AOI. Never zero-fills."""
    db = np.asarray(db, dtype="float64"); vf = np.asarray(validfrac, dtype="float64")
    return np.isfinite(db) & (db != nodata) & np.isfinite(vf) & (vf >= min_frac) & np.asarray(inside, bool)


# ------------------------------------------------------------------------------------------------------------------------------ per-date statistics
def per_date_stats(db, valid, inside, thresholds=THRESHOLDS):
    n_aoi = int(np.asarray(inside).sum()); v = np.asarray(db, dtype="float64")[valid]; n = int(v.size)
    r = {"aoi_cells": n_aoi, "valid_cells": n, "valid_share_pct": round(100 * n / n_aoi, 4) if n_aoi else None}
    if n == 0: return r
    r.update(mean_db=round(float(v.mean()), 4), std_db=round(float(v.std()), 4), power_mean_db=round(float(10 * np.log10(np.mean(10 ** (v / 10)))), 4))
    for q, x in zip(PCTS, np.percentile(v, PCTS)): r[f"p{q:02d}_db"] = round(float(x), 4)
    for t in thresholds:
        c = int((v > t).sum()); k = f"gt{t:g}"; r[f"{k}_cells"] = c; r[f"{k}_pct_of_aoi"] = round(100 * c / n_aoi, 4); r[f"{k}_pct_of_valid"] = round(100 * c / n, 4)
    return r


def percentile_curve(db, valid, pcts=PCTS):
    v = np.asarray(db, dtype="float64")[valid]
    return {q: float(x) for q, x in zip(pcts, np.percentile(v, pcts))} if v.size else {}


def shift_vs_group(dbs, valids, dates, group_dates):
    """DESCRIPTIVE comparison against a comparison group (NOT a baseline): per date, (a) percentile curve minus the mean of the group's percentile curves and (b) the
    cell-wise difference to the per-cell median of the group, over cells valid on ALL group dates and on the date. dbs/valids: {date: array}. Returns a list of rows."""
    gv = np.logical_and.reduce([valids[d] for d in group_dates]); gmed = np.median(np.stack([np.where(valids[d], dbs[d], np.nan) for d in group_dates]), axis=0)
    gcurve = {q: np.mean([percentile_curve(dbs[d], valids[d])[q] for d in group_dates]) for q in PCTS}
    rows = []
    for d in dates:
        row = {"date_utc": d, "in_comparison_group": d in group_dates}
        c = percentile_curve(dbs[d], valids[d])
        for q in PCTS: row[f"d_p{q:02d}_db"] = round(c[q] - gcurve[q], 4) if c else None
        m = gv & valids[d]; row["paired_cells"] = int(m.sum())
        if m.any():
            dd = (dbs[d] - gmed)[m]; row["paired_median_diff_db"] = round(float(np.median(dd)), 4); row["paired_p05_diff_db"] = round(float(np.percentile(dd, 5)), 4); row["paired_p95_diff_db"] = round(float(np.percentile(dd, 95)), 4)
        rows.append(row)
    return rows


# ------------------------------------------------------------------------------------------------------------------------------ persistence
def persistence_counts(dbs, valids, dates, threshold):
    """n_valid[i,j] = number of dates on which the cell is valid; n_bright = number of valid dates with dB > threshold. Missing is NOT counted bright and NOT counted valid."""
    nv = np.sum([valids[d] for d in dates], axis=0).astype("uint8")
    nb = np.sum([valids[d] & (np.where(valids[d], dbs[d], -np.inf) > threshold) for d in dates], axis=0).astype("uint8")
    return nv, nb


def classify(n_bright, n_valid, persistent_cut=PRIMARY_CUT, min_valid=MIN_VALID_DATES):
    """Exploratory classes from the ABSOLUTE bright-date count: 0 never, 1 single-date, 2 rare (2 dates), 3 recurrent (3..cut-1), 4 persistent (>= cut). Cells with
    fewer than `min_valid` valid dates are NOT_ASSESSED (255). Frequency (n_bright / n_valid) is reported separately by `frequency`."""
    if persistent_cut < 4: raise ValueError("persistent_cut must be >= 4 so that 'recurrent' (3..cut-1) is non-empty")
    nb = np.asarray(n_bright).astype("int16"); nv = np.asarray(n_valid).astype("int16"); c = np.full(nb.shape, NOT_ASSESSED, dtype="uint8"); ok = nv >= min_valid
    c[ok & (nb == 0)] = NEVER; c[ok & (nb == 1)] = SINGLE; c[ok & (nb == 2)] = RARE; c[ok & (nb >= 3) & (nb < persistent_cut)] = RECURRENT; c[ok & (nb >= persistent_cut)] = PERSISTENT
    return c


def frequency(n_bright, n_valid, min_valid=MIN_VALID_DATES):
    nv = np.asarray(n_valid).astype("float64"); f = np.full(nv.shape, np.nan)
    ok = nv >= min_valid; f[ok] = np.asarray(n_bright, dtype="float64")[ok] / nv[ok]; return f


def class_counts(cls, inside, n_bright=None, n_valid=None):
    """Cells per class. If n_bright/n_valid are given, also the absolute bright-date count range and the MEAN FREQUENCY (n_bright / n_valid) of the class."""
    inside = np.asarray(inside, bool); n_aoi = int(inside.sum()); assessed = int((inside & (cls != NOT_ASSESSED)).sum()); rows = []
    for code in (NEVER, SINGLE, RARE, RECURRENT, PERSISTENT, NOT_ASSESSED):
        m = inside & (cls == code); c = int(m.sum())
        r = {"class": CLASS_NAMES[code], "code": code, "cells": c, "pct_of_aoi_cells": round(100 * c / n_aoi, 4) if n_aoi else None,
             "pct_of_assessed_cells": None if code == NOT_ASSESSED or not assessed else round(100 * c / assessed, 4)}
        if n_bright is not None and c and code != NOT_ASSESSED:
            nb = np.asarray(n_bright)[m].astype(float); nv = np.asarray(n_valid)[m].astype(float)
            r.update(min_bright_dates=int(nb.min()), max_bright_dates=int(nb.max()), mean_bright_frequency=round(float(np.mean(nb / nv)), 4))
        rows.append(r)
    return rows


def date_decomposition(dbs, valids, dates, cls, threshold, comparison_dates):
    """For each date: its bright cells (valid & dB > threshold) split by persistence class, plus the cells bright on this date and on NONE of the other comparison dates
    (descriptive 'bright here, not in the comparison dates'). Shares are of that date's bright cells."""
    rows = []
    for d in dates:
        b = valids[d] & (np.where(valids[d], dbs[d], -np.inf) > threshold); nb = int(b.sum())
        others = [x for x in comparison_dates if x != d]; oth = np.zeros_like(b) if not others else np.logical_or.reduce([valids[x] & (np.where(valids[x], dbs[x], -np.inf) > threshold) for x in others])
        r = {"date_utc": d, "bright_cells": nb}
        for code in (SINGLE, RARE, RECURRENT, PERSISTENT, NOT_ASSESSED):
            c = int((b & (cls == code)).sum()); r[f"{CLASS_NAMES[code]}_cells"] = c; r[f"{CLASS_NAMES[code]}_pct_of_date_bright"] = round(100 * c / nb, 4) if nb else None
        c = int((b & ~oth).sum()); r["bright_not_in_other_comparison_dates_cells"] = c; r["bright_not_in_other_comparison_dates_pct"] = round(100 * c / nb, 4) if nb else None
        rows.append(r)
    return rows


# ------------------------------------------------------------------------------------------------------------------------------ components
SIZE_BINS = ((1, 1), (2, 4), (5, 9), (10, 49), (50, 199), (200, 10 ** 9))


def components(mask, grid, label):
    """8-neighbour connected components of a boolean mask -> rows (id, cells, area_km2, centroid x/y in grid CRS, bbox rows/cols). Deterministic ordering (by label)."""
    from scipy import ndimage as ndi
    lab, n = ndi.label(np.asarray(mask, bool), structure=np.ones((3, 3), int)); rows = []
    if n == 0: return rows
    t = grid.transform; area = abs(t.a * t.e) / 1e6
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        sub = lab[sl] == i; rr, cc = np.nonzero(sub); rr = rr + sl[0].start; cc = cc + sl[1].start
        rows.append({"class": label, "component": i, "cells": int(sizes[i]), "area_km2": round(float(sizes[i]) * area, 6), "centroid_x": round(float(t.c + (cc.mean() + 0.5) * t.a), 1),
                     "centroid_y": round(float(t.f + (rr.mean() + 0.5) * t.e), 1), "bbox_rows": f"{int(rr.min())}-{int(rr.max())}", "bbox_cols": f"{int(cc.min())}-{int(cc.max())}"})
    return rows


def component_summary(rows, label, total_cells):
    sz = np.array([r["cells"] for r in rows], dtype=int)
    out = {"class": label, "cells": int(total_cells), "n_components": int(sz.size)}
    if sz.size:
        out.update(largest_component_cells=int(sz.max()), median_component_cells=float(np.median(sz)), single_cell_components=int((sz == 1).sum()),
                   pct_cells_in_single_cell_components=round(100 * float(sz[sz == 1].sum()) / sz.sum(), 4), pct_cells_in_components_ge10=round(100 * float(sz[sz >= 10].sum()) / sz.sum(), 4))
    for lo, hi in SIZE_BINS: out[f"n_comp_{lo}" + (f"_{hi}" if hi < 10 ** 9 else "_plus")] = int(((sz >= lo) & (sz <= hi)).sum())
    return out


# ------------------------------------------------------------------------------------------------------------------------------ rainfall (optional)
def read_rainfall(csv_path, dates):
    """Return (DataFrame|None, info). Only the VERIFIED columns present in the file are used (prior_<N>d_aoi_mean_mm); nothing is computed or filled. The join is skipped
    (DataFrame None, reason in info) if the file is absent, has no s1_date column, no recognised prior_* column, or its dates are not exactly the configured dates."""
    p = Path(csv_path); info = {"path": str(p), "used_columns": [], "skipped_reason": None, "sha256": None}
    if not p.exists(): info["skipped_reason"] = "file not found"; return None, info
    info["sha256"] = sha256_file(p)
    try: df = pd.read_csv(p)
    except Exception as e:                                                                       # noqa: BLE001
        info["skipped_reason"] = f"unreadable: {e}"; return None, info
    if "s1_date" not in df.columns: info["skipped_reason"] = "no s1_date column"; return None, info
    cols = [c for c in df.columns if re.fullmatch(r"prior_\d+d_aoi_mean_mm", c)]
    if not cols: info["skipped_reason"] = "no prior_<N>d_aoi_mean_mm column"; return None, info
    got = [str(x) for x in df["s1_date"]]
    if sorted(got) != sorted(dates) or len(set(got)) != len(got): info["skipped_reason"] = f"dates do not match the configured dates exactly (file: {sorted(got)})"; return None, info
    info["used_columns"] = cols; info["category_column_ignored"] = "category" in df.columns
    out = df[["s1_date"] + cols].copy(); out["s1_date"] = out["s1_date"].astype(str); return out.sort_values("s1_date").reset_index(drop=True), info


def spearman_rows(x_df, metrics_df, rain_cols, metric_cols):
    """DESCRIPTIVE rank correlations (n = number of dates). No p-values or significance are claimed; all series trend with the calendar date."""
    from scipy.stats import spearmanr
    rows = []
    for rc in rain_cols:
        for mc in metric_cols:
            x = x_df[rc].to_numpy(dtype=float); y = metrics_df[mc].to_numpy(dtype=float); ok = np.isfinite(x) & np.isfinite(y)
            rho = float(spearmanr(x[ok], y[ok])[0]) if ok.sum() >= 3 and np.ptp(x[ok]) > 0 and np.ptp(y[ok]) > 0 else None
            rows.append({"rainfall_column": rc, "metric": mc, "n_dates": int(ok.sum()), "spearman_rho": None if rho is None else round(rho, 3), "note": "descriptive only; not causal; CHIRPS day convention provisional"})
    return rows
