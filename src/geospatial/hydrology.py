"""Terrain-derived hydrology on a regular projected DEM (pure NumPy/SciPy; no extra dependencies).

Everything here is TERRAIN-DERIVED and UNVERIFIED: no stormwater infrastructure, no tidal/coastal water levels, no hydrological validation.

Pipeline: validate -> diagnostics -> conservative conditioning (depth-limited priority-flood with epsilon gradient)
          -> D8 flow direction -> topological D8 accumulation -> drainage extraction -> (guarded) TWI.
D8 codes (ESRI): E=1, SE=2, S=4, SW=8, W=16, NW=32, N=64, NE=128; 0 = no downslope neighbour (outlet on the NoData edge or internal sink); 255 = NoData."""
import heapq
import math
import numpy as np
from scipy import ndimage as ndi

# (drow, dcol) for E, SE, S, SW, W, NW, N, NE  (rows increase southwards)
OFFS = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
CODES = [1, 2, 4, 8, 16, 32, 64, 128]
S8 = np.ones((3, 3), dtype=bool)
FD_NODATA = 255


# ---------------------------------------------------------------- validation
def validate_dem(arr, transform, crs, nodata, expect_epsg=32644, expect_res=None, res_tol=1e-3):
    """Raise ValueError with a specific message if the DEM cannot be used; return a dict of facts and the valid mask."""
    if crs is None:
        raise ValueError("DEM has no CRS")
    epsg = crs.to_epsg()
    if not crs.is_projected:
        raise ValueError(f"DEM CRS {crs} is geographic; a projected metric CRS (EPSG:{expect_epsg}) is required")
    if expect_epsg is not None and epsg != expect_epsg:
        raise ValueError(f"DEM CRS is EPSG:{epsg}, expected EPSG:{expect_epsg}")
    if abs(transform.b) > 1e-9 or abs(transform.d) > 1e-9:
        raise ValueError("DEM transform is rotated/sheared; not supported")
    rx, ry = transform.a, -transform.e
    if ry <= 0 or abs(rx - ry) > res_tol * rx:
        raise ValueError(f"DEM pixels must be square with north-up orientation (got {rx} x {ry})")
    if expect_res is not None and abs(rx - expect_res) > res_tol * expect_res:
        raise ValueError(f"DEM resolution {rx} m != expected {expect_res} m")
    a = np.asarray(arr)
    if a.ndim != 2:
        raise ValueError("DEM must be a single-band 2-D array")
    valid = np.isfinite(a)
    if nodata is not None and np.isfinite(nodata):
        valid &= a != nodata
    n = int(valid.sum())
    if n == 0:
        raise ValueError("DEM contains no valid cells")
    return {"epsg": epsg, "res": float(rx), "shape": a.shape, "valid_cells": n, "nodata": nodata,
            "nodata_defined": nodata is not None, "min": float(a[valid].min()), "max": float(a[valid].max()),
            "mean": float(a[valid].mean()), "median": float(np.median(a[valid]))}, valid


def outlet_mask(valid):
    """Valid cells on the raster edge or touching NoData (8-neighbourhood): water can leave the study area there."""
    interior = ndi.binary_erosion(valid, structure=S8, border_value=0)
    return valid & ~interior


# ---------------------------------------------------------------- conditioning
def priority_flood_eps(z, valid, eps=1e-6):
    """Barnes et al. (2014) priority-flood with epsilon: fills every depression to its spill level plus a tiny gradient (eps per cell)
    so that every non-outlet cell has a strictly lower neighbour. Outlets = outlet_mask. float64 result (NoData -> nan)."""
    H, W = z.shape
    W2 = W + 2
    zp = np.full((H + 2, W2), np.nan)
    zp[1:-1, 1:-1] = np.where(valid, z, np.nan)
    vp = np.zeros((H + 2, W2), dtype=bool)
    vp[1:-1, 1:-1] = valid
    op = np.zeros((H + 2, W2), dtype=bool)
    op[1:-1, 1:-1] = outlet_mask(valid)
    f = zp.ravel().tolist()
    ok = vp.ravel().tolist()
    closed = op.ravel().tolist()
    heap = [(f[i], i) for i in np.flatnonzero(op.ravel()).tolist()]
    heapq.heapify(heap)
    nb = [dy * W2 + dx for dy, dx in OFFS]
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        zc, i = pop(heap)
        lim = zc + eps
        for d in nb:
            j = i + d
            if ok[j] and not closed[j]:
                closed[j] = True
                if f[j] < lim:
                    f[j] = lim
                push(heap, (f[j], j))
    out = np.array(f, dtype="float64").reshape(H + 2, W2)[1:-1, 1:-1]
    out[~valid] = np.nan
    return out


def condition_dem(z, valid, max_fill_depth_m=1.0, min_depth_m=0.01, eps=1e-6):
    """Conservative, configurable conditioning.
    1. Full priority-flood gives the spill-level surface F and fill depth D = F - z.
    2. Closed depressions = 8-connected components of D > min_depth_m (smaller D is only the epsilon gradient on flats).
    3. A depression whose MAXIMUM fill depth <= max_fill_depth_m is treated as a DEM artefact/micro-relief and filled;
       a deeper one is kept as it is (terminal internal sink) - it may be a genuine depression (tank, marsh, low-lying ground).
    Cells outside deep depressions take F (so flats drain). Returns (conditioned float64 with nan outside, info dict)."""
    F = priority_flood_eps(z, valid, eps)
    D = np.where(valid, F - z, 0.0)
    dep = valid & (D > min_depth_m)
    lab, n = ndi.label(dep, structure=S8)
    if n:
        ids = np.arange(1, n + 1)
        maxd = np.asarray(ndi.maximum(D, lab, ids))
        cells = np.asarray(ndi.sum(dep, lab, ids)).astype(int)
    else:
        ids, maxd, cells = np.array([], int), np.array([]), np.array([], int)
    deep_ids = ids[maxd > max_fill_depth_m]
    deep = np.isin(lab, deep_ids) & (lab > 0)
    cond = F.copy()
    cond[deep] = z[deep]
    cond[~valid] = np.nan
    info = {"label": lab, "fill_depth": D, "n_depressions": int(n), "dep_max_depth": maxd, "dep_cells": cells,
            "n_filled": int(len(ids) - len(deep_ids)), "n_kept": int(len(deep_ids)), "kept_mask": deep, "spill_surface": F}
    return cond, info


def depression_sensitivity(info, res, thresholds=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)):
    rows = []
    for t in thresholds:
        m = info["dep_max_depth"] <= t
        rows.append({"max_fill_depth_m": t, "depressions_filled": int(m.sum()), "depressions_kept": int((~m).sum()),
                     "cells_in_filled_depressions": int(info["dep_cells"][m].sum()), "area_km2_filled": round(float(info["dep_cells"][m].sum() * res * res / 1e6), 4)})
    return rows


# ---------------------------------------------------------------- D8
def d8_flow_direction(z, valid):
    """Steepest strictly-descending neighbour (ties: first in E,SE,S,SW,W,NW,N,NE order -> deterministic). 0 = none. 255 = NoData.
    NoData neighbours are never targets, so no flow enters or crosses invalid areas."""
    H, W = z.shape
    zz = np.where(valid, z, np.nan)
    zp = np.pad(zz, 1, constant_values=np.nan)
    best = np.zeros((H, W))
    fd = np.zeros((H, W), dtype="uint8")
    for (dy, dx), code in zip(OFFS, CODES):
        nbz = zp[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
        dist = math.hypot(dy, dx)
        with np.errstate(invalid="ignore"):
            drop = (zz - nbz) / dist
        better = np.isfinite(drop) & valid & (drop > best)
        best = np.where(better, drop, best)
        fd = np.where(better, code, fd).astype("uint8")
    fd[~valid] = FD_NODATA
    return fd


def downstream_index(fd):
    """Flat index of each cell's downstream cell, -1 for none/NoData."""
    H, W = fd.shape
    yy, xx = np.mgrid[0:H, 0:W]
    tgt = np.full((H, W), -1, dtype=np.int64)
    for (dy, dx), code in zip(OFFS, CODES):
        m = fd == code
        ny, nx = yy[m] + dy, xx[m] + dx
        inside = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
        idx = np.flatnonzero(m.ravel())[inside]
        tgt.ravel()[idx] = ny[inside] * W + nx[inside]
    return tgt.ravel()


def flow_accumulation(fd):
    """Topological (Kahn) D8 accumulation in cells, each valid cell contributing 1 (itself included).
    Raises if a cycle exists. Flow never enters NoData cells because directions never point to them."""
    tgt = downstream_index(fd)
    valid = (fd != FD_NODATA).ravel()
    N = tgt.size
    acc = valid.astype("float64")
    has = tgt >= 0
    indeg = np.bincount(tgt[has], minlength=N).astype(np.int64)
    frontier = np.flatnonzero(valid & (indeg == 0))
    done = 0
    while frontier.size:
        done += frontier.size
        f = frontier[has[frontier]]
        t = tgt[f]
        np.add.at(acc, t, acc[f])
        np.subtract.at(indeg, t, 1)
        cand = np.unique(t)
        frontier = cand[indeg[cand] == 0]
    if done != int(valid.sum()):
        raise RuntimeError("flow-direction cycle detected: accumulation incomplete (%d of %d cells)" % (done, int(valid.sum())))
    out = acc.reshape(fd.shape)
    out[fd == FD_NODATA] = np.nan
    return out


def terminal_cells(fd):
    """Valid cells with no downstream cell (outlets on the NoData edge and internal sinks)."""
    return (fd == 0)


def extract_drainage(acc, threshold_cells):
    return np.isfinite(acc) & (acc >= threshold_cells)


def threshold_from(res, threshold_cells=None, threshold_km2=None, default_km2=0.1):
    """Return (cells, km2). If both are given, cells win. Thresholds are in CONTRIBUTING AREA (including the cell itself)."""
    cell_km2 = res * res / 1e6
    if threshold_cells is not None:
        c = int(threshold_cells)
    else:
        c = int(math.ceil((threshold_km2 if threshold_km2 is not None else default_km2) / cell_km2))
    if c < 1:
        raise ValueError("drainage threshold must be >= 1 cell")
    return c, c * cell_km2


def segments(fd, net, res):
    """Channel cell -> downstream channel cell links as (row, col, row2, col2, length_m)."""
    tgt = downstream_index(fd)
    H, W = fd.shape
    idx = np.flatnonzero(net.ravel() & (tgt >= 0))
    idx = idx[net.ravel()[tgt[idx]]]
    r, c = divmod(idx, W)
    r2, c2 = divmod(tgt[idx], W)
    length = np.hypot(r2 - r, c2 - c) * res
    return r, c, r2, c2, length, idx


def twi(acc, slope_deg, res, min_slope_deg=0.1):
    """ln(a / tan(beta)); a = specific catchment area = A_contrib / res (D8, flow width = cell size).
    Slopes below min_slope_deg are clamped (zero slopes would give infinity). Returns (twi float32 with nan, fraction_clamped)."""
    ok = np.isfinite(acc) & np.isfinite(slope_deg)
    a = acc * res                       # (cells * res^2) / res
    tb_min = math.tan(math.radians(min_slope_deg))
    tb = np.tan(np.radians(np.where(ok, slope_deg, 0.0)))
    clamped = ok & (tb < tb_min)
    tb = np.maximum(tb, tb_min)
    out = np.where(ok, np.log(np.where(ok, a, 1.0) / tb), np.nan).astype("float32")
    return out, float(clamped.sum() / max(1, ok.sum()))


# ---------------------------------------------------------------- diagnostics
def negative_clusters(z, valid, info, res, transform=None):
    """Spatial diagnostics of z < 0 cells. No cell is declared an error: flags only describe evidence."""
    neg = valid & (z < 0)
    lab, n = ndi.label(neg, structure=S8)
    dist_nd = ndi.distance_transform_edt(valid) * res           # distance to nearest NoData/edge cell (m)
    D = info["fill_depth"]
    kept = info["kept_mask"]
    rows = []
    for k in range(1, n + 1):
        m = lab == k
        ys, xs = np.nonzero(m)
        cx, cy = ((transform.c + (xs.mean() + 0.5) * transform.a, transform.f + (ys.mean() + 0.5) * transform.e) if transform is not None
                  else (float(xs.mean()), float(ys.mean())))
        md = float(D[m].max())
        rows.append({"cluster": k, "cells": int(m.sum()), "area_m2": float(m.sum() * res * res), "min_elev_m": float(z[m].min()),
                     "mean_elev_m": float(z[m].mean()), "centroid_x": float(cx), "centroid_y": float(cy),
                     "min_dist_to_nodata_edge_m": float(dist_nd[m].min()), "closed_depression": bool(md > 0.01),
                     "max_fill_depth_m": md, "kept_unfilled": bool(kept[m].any()),
                     "interpretation": "UNVERIFIED: cannot be classified as terrain or source artefact without independent data"})
    summary = {"negative_cells": int(neg.sum()), "negative_pct": float(100 * neg.sum() / max(1, valid.sum())), "clusters": int(n),
               "largest_cluster_cells": int(max([r["cells"] for r in rows], default=0)),
               "share_within_300m_of_edge_pct": float(100 * (dist_nd[neg] <= 300).mean()) if neg.any() else 0.0,
               "share_in_closed_depressions_pct": float(100 * ((D[neg] > 0.01).mean())) if neg.any() else 0.0}
    return rows, summary


def change_stats(z, cond, valid, res, tol=0.01):
    d = np.where(valid, cond - z, 0.0)
    ch = valid & (d > tol)
    return {"cells_raised_gt_tol": int(ch.sum()), "area_km2_raised": float(ch.sum() * res * res / 1e6),
            "max_raise_m": float(d[valid].max()), "mean_raise_over_changed_m": float(d[ch].mean()) if ch.any() else 0.0,
            "volume_added_m3": float(d[valid & (d > 0)].sum() * res * res), "cells_lowered": int((valid & (d < -1e-9)).sum()),
            "pct_valid_changed": float(100 * ch.sum() / max(1, valid.sum())), "tolerance_m": tol}
