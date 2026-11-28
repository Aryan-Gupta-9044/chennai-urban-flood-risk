"""S1WC-2: additive refinement of the S1WC-1 per-date dark-backscatter candidate product (pure NumPy/SciPy functions; no I/O). S1WC-1 code is NOT modified.

WHAT CHANGES: one new class, WATER_SIG (8) = 'dark candidate on a provisional DEM-indicated flattened-water signature'. It is assigned ONLY to cells that S1WC-1 labelled TRANSIENT (1), so
class1(v2) + class8(v2) == class1(S1WC-1) exactly, and every other class is identical. Nothing is normalised, no threshold changes, no flood label is created.
THE SIGNATURE (provisional; NOT a confirmed permanent-water mask, NOT a flood exclusion): the Copernicus GLO-30 surface model flattens water bodies, so (a) DEM == 0 exactly, or (b) a 4-neighbour
component of IDENTICAL non-zero DEM values with >= min_plateau_cells cells, marks cells that are plausibly sea/estuary/tank/lake surface. A generic slope == 0 rule is NOT used. The Copernicus Water Body Mask
is NOT used. A cell with the signature may be real standing water, a flooded water body, or an artefact; remaining class-1 cells are NOT confirmed floodwater either."""
import warnings
import numpy as np
from . import s1_water_candidates as wc

WATER_SIG = 8
CLASS_NAMES = dict(wc.CLASS_NAMES); CLASS_NAMES[WATER_SIG] = "dark candidate on provisional DEM-indicated flattened-water signature (DEM==0 or constant-elevation plateau; NOT a confirmed water mask, NOT a flood exclusion)"
ORDER = [0, 1, 8, 2, 3, 4, 5, 6, 7, 254, 255]
DEFAULT_PARAMS = {"min_plateau_cells": 30, "twi_clamp_deg": 0.1, "block_cells": 30, "block_min_cells": 300}


def plateau_signature(dem, inside, min_plateau_cells=30, nodata=wc.NODATA):
    """Returns (zero, plateau, signature) boolean arrays (all False outside `inside`). zero: DEM == 0 exactly. plateau: non-zero valid cells in a 4-neighbour component of exactly equal DEM values with >= min_plateau_cells cells.
    NoData / NaN cells never match and never join a component."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    z = np.asarray(dem, dtype="float64"); inside = np.asarray(inside, bool); ok = inside & np.isfinite(z) & (z != nodata)
    zero = ok & (z == 0); elig = ok & (z != 0); h, w = z.shape; idx = np.arange(h * w).reshape(h, w)
    eh = elig[:, :-1] & elig[:, 1:] & (z[:, :-1] == z[:, 1:]); ev = elig[:-1, :] & elig[1:, :] & (z[:-1, :] == z[1:, :])
    a = np.concatenate([idx[:, :-1][eh], idx[:-1, :][ev]]); b = np.concatenate([idx[:, 1:][eh], idx[1:, :][ev]])
    g = coo_matrix((np.ones(a.size, "int8"), (a, b)), shape=(h * w, h * w)); n, lab = connected_components(g, directed=False)
    size = np.bincount(lab, minlength=n); plateau = (elig.ravel() & (size[lab] >= min_plateau_cells)).reshape(h, w)
    return zero, plateau, zero | plateau


def apply_signature(cls_v1, signature):
    """S1WC-2 class raster: TRANSIENT cells on the signature become WATER_SIG; nothing else changes."""
    out = np.asarray(cls_v1).copy(); out[(out == wc.TRANSIENT) & np.asarray(signature, bool)] = WATER_SIG; return out


def fold_back(cls_v2):
    """Inverse of apply_signature (regression check against S1WC-1)."""
    out = np.asarray(cls_v2).copy(); out[out == WATER_SIG] = wc.TRANSIENT; return out


def twi_clamp(slope, twi, acc, res, inside, clamp_deg=0.1, nodata=wc.NODATA, tol=1e-3):
    """Replicates the repo rule (src/geospatial/hydrology.py): slope < clamp_deg is clamped to clamp_deg, so TWI = ln(acc*res / tan(clamp_deg)). Returns (clamped mask, number of clamped cells whose stored TWI does NOT equal
    that value within tol, i.e. consistency failures). Cells with NoData slope/TWI/acc are never 'clamped'."""
    s = np.asarray(slope, "float64"); t = np.asarray(twi, "float64"); a = np.asarray(acc, "float64")
    ok = np.asarray(inside, bool) & np.isfinite(s) & (s != nodata) & np.isfinite(t) & (t != nodata) & np.isfinite(a) & (a != nodata)
    clamped = ok & (s < clamp_deg)
    with np.errstate(all="ignore"): expect = np.log(a * res / np.tan(np.radians(clamp_deg)))
    return clamped, int((clamped & (np.abs(t - expect) > tol)).sum())


def block_uniformity(dates, stack, valid_stack, block=30, min_cells=300):
    """Per date: spatial spread of the date-level offset. Residual = value - per-pixel median over the dates on cells valid on ALL dates; block medians of the residual; SD of block medians and share of blocks within
    1 dB of the median block. DIAGNOSTIC ONLY (nothing is corrected)."""
    st = np.asarray(stack, "float64"); ok = np.asarray(valid_stack, bool); allv = ok.all(0)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning); med = np.nanmedian(np.where(allv[None], st, np.nan), axis=0)
    res = st - med[None]; h, w = allv.shape; rows = []
    for i, d in enumerate(dates):
        m = []
        for r in range(h // block):
            for c in range(w // block):
                s = (slice(r * block, (r + 1) * block), slice(c * block, (c + 1) * block)); v = res[i][s][allv[s]]
                if v.size >= min_cells: m.append(np.median(v))
        m = np.array(m); rows.append({"date": d, "n_blocks": int(m.size), "median_of_block_medians_db": round(float(np.median(m)), 3) if m.size else None, "block_sd_db": round(float(m.std()), 3) if m.size else None,
                                      "frac_blocks_within_1db": round(float((np.abs(m - np.median(m)) <= 1).mean()), 3) if m.size else None})
    return rows


def vv_vh_stable(dates, vv_stack, vh_stack, valid_stack, vv_floor=-15.0):
    """Median (VV - VH) in dB over the S1WC-1 'stable' cells (valid every date, never VV < vv_floor)."""
    vs, hs, ok = np.asarray(vv_stack), np.asarray(vh_stack), np.asarray(valid_stack); stable = ok.all(0)
    with np.errstate(invalid="ignore"): stable &= ~(np.where(ok, vs, np.nan) < vv_floor).any(0)
    return [{"date": d, "stable_vv_minus_vh_db": round(float(np.median((vs[i] - hs[i])[stable])), 3) if stable.any() else None} for i, d in enumerate(dates)]


def terrain_stats(layers, groups, ref_mask, clamped=None, nodata=wc.NODATA):
    """Descriptive percentiles of each layer for each group mask vs the reference (all valid AOI cells). For slope_deg and twi a second block excludes clamped cells from BOTH group and reference ('clamp-excluded').
    Descriptive context only - not evidence of flooding."""
    rows = []
    variants = [("all cells", None)] + ([("clamp-excluded", clamped)] if clamped is not None else [])
    for vn, ex in variants:
        for ln, arr in layers.items():
            if vn == "clamp-excluded" and ln not in ("slope_deg", "twi"): continue
            a = np.asarray(arr, "float64"); okl = np.isfinite(a) & (a != nodata)
            for gn, gm in {**groups, "reference: all valid AOI cells": ref_mask}.items():
                m = gm & okl & (~ex if ex is not None else True); v = a[m]
                rows.append({"variant": vn, "layer": ln, "group": gn, "n_cells": int(v.size), **({f"p{p}": round(float(np.percentile(v, p)), 3) for p in (5, 25, 50, 75, 95)} if v.size else {})})
    return rows
