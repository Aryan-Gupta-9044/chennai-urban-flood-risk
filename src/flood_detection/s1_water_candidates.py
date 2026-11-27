"""Sentinel-1 per-date DARK-BACKSCATTER (water/flood CANDIDATE) classification, review product v1 (V2.3). Pure NumPy/SciPy functions; no I/O.

WHAT THIS IS: a per-acquisition-date classification of dual-polarisation (VV and VH) low-backscatter cells into explicit classes, with a persistence screen made from the SAME Sentinel-1 stack, a
terrain (slope) screen, a minimum-cluster screen, and explicit UNKNOWN classes. Every date stays separate.
WHAT THIS IS NOT: a confirmed flood extent, a validated map, an accuracy result or an event map. Low backscatter is a common indicator of smooth open water, but it is NEITHER NECESSARY NOR SUFFICIENT: wind-roughened water, flooded vegetation and flooded urban areas are often not dark (omission), while smooth tarmac, bare/wet
sand, radar shadow, calm vegetation-free fields, aquaculture and seasonal tanks are also dark (commission). The
persistence screen comes from the same sensor, so it is NOT an independent permanent-water mask. Thresholds are starting values, not tuned for Chennai and not validated.
Unknown/invalid cells are NEVER turned into 'not dark' (class 0): they have their own codes."""
import numpy as np

NODATA = -9999.0
# class codes (uint8) ---------------------------------------------------------------------------------------------------------------------------------------------
NOT_DARK, TRANSIENT, PERSISTENT, TERRAIN, SMALL, VV_ONLY, UNASSESSED, TERRAIN_UNKNOWN, INVALID, OUTSIDE = 0, 1, 2, 3, 4, 5, 6, 7, 254, 255
CLASS_NAMES = {NOT_DARK: "valid, not dark (no dark-water signal; NOT 'no flood')", TRANSIENT: "transient dark candidate (dark on this date, not persistently dark, passed slope and size screens)",
               PERSISTENT: "persistently dark (excluded: permanent-water-like or radar-dark surface; from the same S1 stack)", TERRAIN: "dark but excluded: slope above limit (terrain/shadow risk)",
               SMALL: "dark but excluded: cluster smaller than the minimum size", VV_ONLY: "VV dark but VH not dark (weak; not a candidate)",
               UNASSESSED: "dark but persistence cannot be assessed (too few valid dates)", TERRAIN_UNKNOWN: "dark but slope unknown (not screened; not a candidate)",
               INVALID: "invalid/unknown inside the AOI (NoData, low valid fraction or one polarisation missing)", OUTSIDE: "outside the AOI"}
ORDER = [NOT_DARK, TRANSIENT, PERSISTENT, TERRAIN, SMALL, VV_ONLY, UNASSESSED, TERRAIN_UNKNOWN, INVALID, OUTSIDE]
DEFAULT_PARAMS = {"vv_dark_db": -18.0, "vh_dark_db": -24.0, "persistent_min_dark_dates": 6, "min_valid_dates": 6, "max_slope_deg": 5.0, "min_cluster_cells": 4, "min_valid_fraction": 0.5}
SENS_VV, SENS_VH = (-15.0, -18.0, -20.0), (-22.0, -24.0, -26.0)


def valid_pol(db, validfrac, valid_flag, min_frac, nodata=NODATA):
    """A cell is valid for one polarisation only if finite, not the NoData sentinel, valid fraction >= min_frac AND the stored valid flag is 1. Never zero-fills."""
    db = np.asarray(db, dtype="float64"); vf = np.asarray(validfrac, dtype="float64")
    return np.isfinite(db) & (db != nodata) & np.isfinite(vf) & (vf >= min_frac) & (np.asarray(valid_flag) == 1)


def dark_mask(vv, vh, vv_thr, vh_thr, valid):
    """Dual-polarisation dark: VV < vv_thr AND VH < vh_thr, evaluated only where valid (invalid cells are never dark and never 'not dark')."""
    with np.errstate(invalid="ignore"): return valid & (np.asarray(vv) < vv_thr) & (np.asarray(vh) < vh_thr)


def vv_only_dark(vv, vh, vv_thr, vh_thr, valid):
    with np.errstate(invalid="ignore"): return valid & (np.asarray(vv) < vv_thr) & ~(np.asarray(vh) < vh_thr)


def persistence(dark_stack, valid_stack, min_valid=6, min_dark=6):
    """(n_dark, n_valid, persistent, assessable) over the date axis. persistent = assessable AND n_dark >= min_dark."""
    n_dark = np.asarray(dark_stack).sum(0).astype("int16"); n_valid = np.asarray(valid_stack).sum(0).astype("int16"); assess = n_valid >= min_valid
    return n_dark, n_valid, assess & (n_dark >= min_dark), assess


def cluster_keep(mask, min_cells):
    """Keep only 8-neighbour connected components with >= min_cells cells. Returns (kept, removed) boolean arrays."""
    from scipy import ndimage as ndi
    m = np.asarray(mask, bool)
    if min_cells <= 1 or not m.any(): return m.copy(), np.zeros_like(m)
    lab, n = ndi.label(m, structure=np.ones((3, 3), int)); sizes = np.bincount(lab.ravel(), minlength=n + 1); big = sizes >= min_cells; big[0] = False
    kept = big[lab]; return kept, m & ~kept


def classify_date(valid_both, dark, vv_only, persistent, assessable, slope, inside, max_slope, min_cluster):
    """Per-date class raster. Precedence: outside AOI > invalid > (not dark: 0 or VV-only 5) > unassessed > persistent > slope unknown / steep > small cluster > transient candidate."""
    out = np.full(valid_both.shape, OUTSIDE, "uint8"); inside = np.asarray(inside, bool)
    out[inside] = INVALID
    v = inside & valid_both
    out[v] = NOT_DARK; out[v & vv_only] = VV_ONLY
    d = v & dark
    out[d] = TRANSIENT
    out[d & ~assessable] = UNASSESSED
    pers = d & assessable & persistent; out[pers] = PERSISTENT
    rest = d & assessable & ~persistent
    sl = np.asarray(slope, dtype="float64"); unknown = ~np.isfinite(sl) | (sl == NODATA)
    out[rest & unknown] = TERRAIN_UNKNOWN
    with np.errstate(invalid="ignore"): steep = rest & ~unknown & (sl > max_slope)
    out[steep] = TERRAIN
    cand = rest & ~unknown & ~steep
    kept, removed = cluster_keep(cand, min_cluster)
    out[removed] = SMALL; out[kept] = TRANSIENT
    return out


def class_counts(cls, cell_area_km2, n_aoi):
    rows = []
    for c in ORDER:
        n = int((cls == c).sum())
        if c == OUTSIDE: continue
        rows.append({"class_code": c, "class": CLASS_NAMES[c], "cells": n, "pct_of_aoi_cells": round(100 * n / n_aoi, 4) if n_aoi else None, "area_km2": round(n * cell_area_km2, 4)})
    return rows


def sensitivity_rows(date, vv, vh, valid, n_aoi):
    """Dark-cell counts before any exclusion for a small threshold grid (NOT a tuning step; no threshold is selected from it)."""
    rows = []
    nv = int(valid.sum())
    for tv in SENS_VV:
        for th in SENS_VH:
            n = int(dark_mask(vv, vh, tv, th, valid).sum()); rows.append({"date": date, "mode": "VV and VH", "vv_dark_db": tv, "vh_dark_db": th, "dark_cells": n, "pct_of_valid_cells": round(100 * n / nv, 4) if nv else None})
        n = int((valid & (np.asarray(vv) < tv)).sum()); rows.append({"date": date, "mode": "VV only", "vv_dark_db": tv, "vh_dark_db": None, "dark_cells": n, "pct_of_valid_cells": round(100 * n / nv, 4) if nv else None})
    return rows


def radiometric_shift(dates, vv_stack, vh_stack, valid_stack, vv_floor=-15.0):
    """Per-date median VV/VH over (a) all valid cells and (b) STABLE cells = valid on every date and never below vv_floor in VV. A shift of the stable-cell median between dates shows date-level radiometric
    change (wetness, roughness, wind, calibration). DIAGNOSTIC ONLY: nothing is normalised or corrected with it."""
    vs, hs, ok = np.asarray(vv_stack), np.asarray(vh_stack), np.asarray(valid_stack)
    stable = ok.all(0)
    with np.errstate(invalid="ignore"): stable &= ~(np.where(ok, vs, np.nan) < vv_floor).any(0)
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": d, "median_vv_all_valid_db": round(float(np.median(vs[i][ok[i]])), 3) if ok[i].any() else None, "median_vh_all_valid_db": round(float(np.median(hs[i][ok[i]])), 3) if ok[i].any() else None,
                     "median_vv_stable_db": round(float(np.median(vs[i][stable])), 3) if stable.any() else None, "median_vh_stable_db": round(float(np.median(hs[i][stable])), 3) if stable.any() else None, "stable_cells": int(stable.sum())})
    base_vv = np.mean([r["median_vv_stable_db"] for r in rows]) if stable.any() else None; base_vh = np.mean([r["median_vh_stable_db"] for r in rows]) if stable.any() else None
    for r in rows:
        r["vv_stable_minus_mean_of_dates_db"] = None if base_vv is None else round(r["median_vv_stable_db"] - base_vv, 3); r["vh_stable_minus_mean_of_dates_db"] = None if base_vh is None else round(r["median_vh_stable_db"] - base_vh, 3)
    return rows


def terrain_context(layers, cls, inside, drainage=None):
    """DESCRIPTIVE context of transient candidates vs all valid land cells (percentiles of elevation/slope/TWI/flow accumulation; share within 3 cells of the mapped drainage network). Not a screening criterion."""
    from scipy import ndimage as ndi
    rows = []; cand, allc = cls == TRANSIENT, np.isin(cls, (NOT_DARK, TRANSIENT, PERSISTENT, TERRAIN, SMALL, VV_ONLY, UNASSESSED, TERRAIN_UNKNOWN))
    for name, arr in layers.items():
        a = np.asarray(arr, dtype="float64"); ok = np.isfinite(a) & (a != NODATA)
        for label, m in (("transient candidates", cand), ("all valid AOI cells", allc)):
            v = a[m & ok]; rows.append({"layer": name, "group": label, "n_cells": int(v.size), **({f"p{p}": round(float(np.percentile(v, p)), 3) for p in (5, 25, 50, 75, 95)} if v.size else {})})
    if drainage is not None:
        net = (np.asarray(drainage) == 1)
        if net.any():
            near = ndi.distance_transform_edt(~net) <= 3
            for label, m in (("transient candidates", cand), ("all valid AOI cells", allc)): rows.append({"layer": "share within 3 cells (90 m) of mapped drainage network", "group": label, "n_cells": int(m.sum()), "p50": round(float(near[m].mean()), 4) if m.any() else None})
    return rows


def date_count(cls_stack, code=TRANSIENT, inside=None):
    """Number of acquisition dates on which a cell is in class `code` (explicit meaning: a COUNT OF DATES, not an event map). 255 outside the AOI."""
    out = (np.asarray(cls_stack) == code).sum(0).astype("uint8")
    if inside is not None: out[~np.asarray(inside, bool)] = 255
    return out
