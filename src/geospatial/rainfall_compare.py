"""Side-by-side CHIRPS-vs-IMD comparison helpers (pure NumPy/shapely; unit-tested on SYNTHETIC rasters). NOT a validation: neither product is ground truth,
CHIRPS blends station data, and the two use different (unverified) day definitions. Sources are compared only side by side - never merged or gap-filled.
No resampling of either product: CHIRPS native cells are AREA-AVERAGED over an IMD cell's footprint (a comparison-only aggregation, labelled as such)."""
from datetime import timedelta
import numpy as np
from shapely.geometry import box


def read_cube(dir_path, dates, pattern="{date:%Y%m%d}.tif"):
    """Load daily GeoTIFFs into (cube[nd,H,W] with NaN for nodata AND for absent days, transform, crs, present[nd]). All present files must share one grid."""
    import rasterio
    cube, tr, crs, shape, present = [], None, None, None, []
    for d in dates:
        p = dir_path / pattern.format(date=d)
        if not p.exists():
            cube.append(None); present.append(False); continue
        with rasterio.open(p) as ds:
            a = ds.read(1).astype("float64"); nd = ds.nodata
            if tr is None: tr, crs, shape = ds.transform, ds.crs, a.shape
            elif ds.transform != tr or a.shape != shape or ds.crs != crs: raise ValueError(f"{p.name}: grid differs from the first file")
        if nd is not None: a[a == nd] = np.nan
        a[~np.isfinite(a)] = np.nan
        cube.append(a); present.append(True)
    if tr is None: raise FileNotFoundError(f"no daily rasters in {dir_path}")
    full = np.stack([c if c is not None else np.full(shape, np.nan) for c in cube])
    return full, tr, crs, np.array(present)


def cell_box(tr, r, c):
    x0 = tr.c + c * tr.a; y1 = tr.f + r * tr.e
    return box(x0, y1 + tr.e, x0 + tr.a, y1)


def imd_cells_over_aoi(tr, shape, aoi):
    """Native IMD cells overlapping the AOI polygon: list of dicts(row, col, footprint, aoi_share = share of the AOI polygon's area inside that cell)."""
    out = []; total = aoi.area
    minx, miny, maxx, maxy = aoi.bounds
    c0 = int(np.floor((minx - tr.c) / tr.a)); c1 = int(np.floor((maxx - tr.c) / tr.a))
    r0 = int(np.floor((maxy - tr.f) / tr.e)); r1 = int(np.floor((miny - tr.f) / tr.e))
    for r in range(max(r0, 0), min(r1, shape[0] - 1) + 1):
        for c in range(max(c0, 0), min(c1, shape[1] - 1) + 1):
            b = cell_box(tr, r, c); a = b.intersection(aoi).area
            if a > 0: out.append({"row": r, "col": c, "footprint": b, "aoi_share": a / total, "centre": (b.centroid.x, b.centroid.y)})
    return out


def imd_aoi_coverage_by_day(imd_cube, cells):
    """Per day: share of the AOI polygon's area lying in IMD cells that have a value that day. (Days with no raster are NaN-filled -> 0.)"""
    cov = np.zeros(imd_cube.shape[0])
    for ce in cells:
        cov += np.where(np.isfinite(imd_cube[:, ce["row"], ce["col"]]), ce["aoi_share"], 0.0)
    return cov


def chirps_area_mean(ch_cube, ch_tr, region):
    """Area-weighted mean of CHIRPS native cells over `region` (shapely), per day. STRICT: NaN if any contributing cell is NaN that day.
    Returns (series[nd], support_fraction = area(region ∩ CHIRPS window) / area(region), n_cells)."""
    nd, H, W = ch_cube.shape
    wts = np.zeros((H, W))
    for r in range(H):
        for c in range(W):
            b = cell_box(ch_tr, r, c)
            if b.intersects(region): wts[r, c] = b.intersection(region).area
    area_in = float(wts.sum()); support = area_in / region.area if region.area else 0.0
    out = np.full(nd, np.nan)
    if area_in > 0:
        m = wts > 0
        for i in range(nd):
            v = ch_cube[i][m]
            if np.isfinite(v).all(): out[i] = float((v * wts[m]).sum() / wts[m].sum())
    return out, support, int((wts > 0).sum())


def lag_stats(imd, ch, dates, lags=(-2, -1, 0, 1, 2), min_pairs=8):
    """For each lag k pair IMD[d] with CHIRPS[d+k] (a positive k means the CHIRPS label for the same rain is LATER). Only days where BOTH are finite.
    Returns list of dicts: lag, n_pairs, pearson_r (None if undefined), sum_imd_mm, sum_chirps_mm, ratio_chirps_to_imd, mean_abs_diff_mm."""
    n = len(dates); rows = []
    for k in lags:
        a, b = [], []
        for i in range(n):
            j = i + k
            if 0 <= j < n and np.isfinite(imd[i]) and np.isfinite(ch[j]): a.append(imd[i]); b.append(ch[j])
        a, b = np.array(a), np.array(b)
        r = None
        if len(a) >= min_pairs and a.std() > 0 and b.std() > 0: r = float(np.corrcoef(a, b)[0, 1])
        rows.append({"lag_days": k, "n_pairs": int(len(a)), "pearson_r": r, "sum_imd_mm": float(a.sum()) if len(a) else None, "sum_chirps_mm": float(b.sum()) if len(b) else None,
                     "ratio_chirps_to_imd": float(b.sum() / a.sum()) if len(a) and a.sum() > 0 else None, "mean_abs_diff_mm": float(np.abs(a - b).mean()) if len(a) else None})
    return rows


def two_day_split(imd, ch, dates, d1, d2):
    """Side-by-side values for two adjacent labels plus their 2-day sums: if the DAILY values disagree but the 2-day sums agree, the difference is consistent with a
    day-boundary/labelling shift rather than a different amount of rain (a diagnostic, not proof)."""
    ix = {d: i for i, d in enumerate(dates)}
    g = lambda s, d: (None if d not in ix or not np.isfinite(s[ix[d]]) else float(s[ix[d]]))
    out = {"d1": d1.isoformat(), "d2": d2.isoformat(), "imd_d1": g(imd, d1), "imd_d2": g(imd, d2), "chirps_d1": g(ch, d1), "chirps_d2": g(ch, d2)}
    for k in ("imd", "chirps"):
        a, b = out[f"{k}_d1"], out[f"{k}_d2"]; out[f"{k}_2day_sum"] = None if a is None or b is None else a + b
    s1, s2 = out["imd_2day_sum"], out["chirps_2day_sum"]
    out["two_day_sum_ratio_chirps_to_imd"] = None if not s1 or s2 is None else s2 / s1
    return out
