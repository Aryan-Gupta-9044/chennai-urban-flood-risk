"""Source-agnostic rainfall helpers (pure NumPy/rasterio; unit-tested on SYNTHETIC arrays).

Rules enforced here:
  * A missing/invalid value is NaN and STAYS NaN. It is never converted to 0 mm. Totals over a window are NaN where ANY day is missing
    (strict) unless a clearly labelled lower bound is requested.
  * Rainfall stays on its native grid. Resampling to another grid is a separate, labelled step and adds no spatial information.
  * Different sources (gauge-gridded, satellite-blended, reanalysis) are never mixed in one series or anomaly baseline."""
import math
from datetime import date, timedelta
import numpy as np
from rasterio.transform import Affine

UNIT_TO_MM = {"mm": 1.0, "mm/day": 1.0, "mm/d": 1.0, "kg m-2": 1.0, "kg/m2": 1.0, "kg m**-2": 1.0, "m": 1000.0, "cm": 10.0}
RATE_UNITS = {"mm/h", "mm/hr", "mm/hour"}
MAX_DAILY_MM = 1000.0        # physical-plausibility screen, not a statistical filter


def daterange(a, b):
    d, e = date.fromisoformat(a) if isinstance(a, str) else a, date.fromisoformat(b) if isinstance(b, str) else b
    out = []
    while d <= e:
        out.append(d); d += timedelta(days=1)
    return out


def missing_dates(expected, present):
    ps = set(present)
    return [d for d in expected if d not in ps]


def to_mm(arr, unit, hours=None):
    """Convert to millimetres of water (per accumulation period). Unknown units raise: no silent default."""
    u = str(unit).strip().lower()
    a = np.asarray(arr, dtype="float64")
    if u in RATE_UNITS:
        if not hours:
            raise ValueError("unit '%s' is a rate: pass the accumulation length in hours" % unit)
        return a * float(hours)
    if u not in UNIT_TO_MM:
        raise ValueError("unknown rainfall unit '%s' (known: %s, rates %s)" % (unit, sorted(UNIT_TO_MM), sorted(RATE_UNITS)))
    return a * UNIT_TO_MM[u]


def clean_day(arr, unit, nodata=None, hours=None, max_mm=MAX_DAILY_MM):
    """-> (mm array with NaN for invalid, counts dict). Invalid = nodata, non-finite, negative, or > max_mm. Nothing becomes 0."""
    raw = np.asarray(arr, dtype="float64")
    bad_nd = ~np.isfinite(raw)
    if nodata is not None and np.isfinite(nodata):
        bad_nd |= raw == nodata
    mm = to_mm(np.where(bad_nd, np.nan, raw), unit, hours)
    neg = np.isfinite(mm) & (mm < 0)
    over = np.isfinite(mm) & (mm > max_mm)
    mm = np.where(neg | over, np.nan, mm)
    return mm, {"nodata_cells": int(bad_nd.sum()), "negative_cells": int(neg.sum()), "over_range_cells": int(over.sum())}


def check_same_grid(grids, tol=1e-9):
    """grids: list of (transform, shape, crs). Raises ValueError listing the first mismatch."""
    t0, s0, c0 = grids[0]
    for i, (t, s, c) in enumerate(grids[1:], 1):
        if tuple(s) != tuple(s0):
            raise ValueError("raster %d has shape %s, expected %s" % (i, s, s0))
        if (c is None) != (c0 is None) or (c is not None and c != c0):
            raise ValueError("raster %d CRS %s != %s" % (i, c, c0))
        if any(abs(a - b) > tol for a, b in zip(tuple(t)[:6], tuple(t0)[:6])):
            raise ValueError("raster %d transform differs from the first raster (misaligned grid)" % i)
    return True


CELL_CONVENTION = ("AOI cell convention: a native cell is an 'AOI cell' if its intersection with the AOI polygon has POSITIVE area (any overlap, "
                   "including a tiny boundary sliver; cells that only touch along an edge or at a corner - overlap area <= 1e-10 of the cell area, i.e. float noise - are excluded). "
                   "Weight = exact polygon-cell intersection area / total AOI area; weights sum to the share of the AOI inside the raster extent.")


EDGE_TOUCH_REL_TOL = 1e-10   # intersection area below this fraction of the cell area = boundary contact (float noise), not overlap


def cell_weights(transform, shape, aoi_geom, oversample=None):
    """Exact fraction of the AOI polygon's area in each raster cell (same CRS as the raster; north-up grid). Sum = fraction of the AOI
    inside the raster extent (1.0 = fully covered). Cell convention: see CELL_CONVENTION (positive-area intersection). Boundary slivers
    are therefore counted, with their true (tiny) weight. `oversample` is accepted for backward compatibility and ignored (the former
    10x rasterisation was approximate and could miss sliver cells)."""
    from shapely.geometry import box
    H, W = shape
    total = float(aoi_geom.area)
    if total <= 0:
        raise ValueError("AOI has zero area")
    minx, miny, maxx, maxy = aoi_geom.bounds
    w = np.zeros((H, W), dtype="float64")
    for r in range(H):
        ytop = transform.f + r * transform.e; ybot = ytop + transform.e
        lo_y, hi_y = min(ytop, ybot), max(ytop, ybot)
        if hi_y < miny or lo_y > maxy:
            continue
        for c in range(W):
            xl = transform.c + c * transform.a; xr = xl + transform.a
            lo_x, hi_x = min(xl, xr), max(xl, xr)
            if hi_x < minx or lo_x > maxx:
                continue
            ar = box(lo_x, lo_y, hi_x, hi_y).intersection(aoi_geom).area
            if ar > EDGE_TOUCH_REL_TOL * (hi_x - lo_x) * (hi_y - lo_y):      # ignore floating-point edge/corner contact; real slivers are orders of magnitude larger
                w[r, c] = ar / total
    return w


def weighted_stats(mm, w):
    """AOI-area-weighted statistics over VALID cells only. coverage = share of the AOI area covered by valid cells (0..1)."""
    ok = np.isfinite(mm) & (w > 0)
    cov = float(w[ok].sum())
    if cov <= 0:
        return {"mean_mm": np.nan, "min_mm": np.nan, "max_mm": np.nan, "coverage": 0.0, "cells_valid": 0, "cells_in_aoi": int((w > 0).sum())}
    return {"mean_mm": float((mm[ok] * w[ok]).sum() / cov), "min_mm": float(mm[ok].min()), "max_mm": float(mm[ok].max()),
            "coverage": cov, "cells_valid": int(ok.sum()), "cells_in_aoi": int((w > 0).sum())}


def classify_day(mm, w, min_coverage=0.95):
    """MISSING (no raster) / INCOMPLETE_COVERAGE (valid cells cover < min_coverage of the AOI) / OK."""
    if mm is None:
        return "MISSING"
    return "OK" if weighted_stats(mm, w)["coverage"] >= min_coverage else "INCOMPLETE_COVERAGE"


def strict_total(days, allow_partial=False):
    """Sum a list of daily mm arrays (None = missing day). Strict: NaN wherever any day is missing/invalid.
    allow_partial=True returns a LOWER BOUND (sum of valid days) plus the per-cell valid-day count; it must be labelled as such."""
    if not days:
        raise ValueError("no days given")
    shape = next((d.shape for d in days if d is not None), None)
    if shape is None:
        raise ValueError("all days are missing")
    stack = np.stack([np.full(shape, np.nan) if d is None else d for d in days]).astype("float64")
    nvalid = np.isfinite(stack).sum(axis=0)
    if allow_partial:
        total = np.where(nvalid > 0, np.nansum(stack, axis=0), np.nan)
    else:
        total = np.where(nvalid == len(days), stack.sum(axis=0), np.nan)
    return total, nvalid


def window_total(day_map, end_date, n_days, include_end_day=False):
    """Total of the n_days ending at end_date (excluded by default = 'before' that date). day_map: {date: mm array or None}.
    Returns (total or None, missing_dates). None if any day is missing: never a partial number."""
    last = end_date if include_end_day else end_date - timedelta(days=1)
    dates = [last - timedelta(days=k) for k in range(n_days - 1, -1, -1)]
    miss = [d for d in dates if day_map.get(d) is None]
    if miss:
        return None, miss
    total, nv = strict_total([day_map[d] for d in dates])
    return total, []


def max_k_day(day_map, dates, k):
    """Maximum k-day accumulation per cell using only COMPLETE windows; (array or None, windows_used, windows_skipped)."""
    best, used, skipped = None, 0, 0
    for i in range(len(dates) - k + 1):
        win = dates[i:i + k]
        if any(day_map.get(d) is None for d in win):
            skipped += 1; continue
        t, _ = strict_total([day_map[d] for d in win])
        best = t if best is None else np.fmax(best, t)
        used += 1
    return best, used, skipped


def comparable(meta_a, meta_b):
    """Two rainfall products may be compared/combined only if source, version, native grid, unit and day definition match."""
    keys = ["source_id", "version", "native_resolution", "day_definition", "product_type"]
    why = [f"{k}: {meta_a.get(k)!r} != {meta_b.get(k)!r}" for k in keys if meta_a.get(k) != meta_b.get(k)]
    if any(t in str(m.get("day_definition")).upper() for m in (meta_a, meta_b) for t in ("UNCONFIRMED", "PROVISIONAL")):
        why.append("day definition unconfirmed/provisional")
    return (not why), why


def anomaly(total, clim_totals, min_years=10):
    """Event total vs the SAME-source climatology of same-calendar-window totals (stack: years x H x W, NaN = missing year).
    Non-parametric: difference, ratio to climatological mean, and empirical percentile rank. NaN where fewer than min_years valid years."""
    clim = np.asarray(clim_totals, dtype="float64")
    n = np.isfinite(clim).sum(axis=0)
    mean = np.where(n >= min_years, np.nanmean(np.where(np.isfinite(clim), clim, np.nan), axis=0), np.nan) if clim.size else np.full(total.shape, np.nan)
    rank = np.where(n >= min_years, (np.where(np.isfinite(clim), clim <= total[None], False)).sum(axis=0) / np.maximum(n, 1), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(mean > 0, total / mean, np.nan)
    return {"diff_mm": total - mean, "ratio": ratio, "percentile_rank": rank, "n_years": n, "clim_mean_mm": mean}
