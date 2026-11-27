"""Exploratory relative flood-SUSCEPTIBILITY framework (SUS-1): pure numpy/scipy functions, no file writes, no Earth Engine.

WHAT THIS IS: a transparent, uncalibrated, unvalidated, RELATIVE terrain/hydrology index over the provisional OSM study area. Scores only say "more or less
susceptible than other cells of THIS area under the stated assumptions". It is NOT a flood prediction model, NOT a flood extent, and NOT a flood-RISK assessment
(exposure and vulnerability are not integrated). No weight or threshold is fitted to any flood label; no flood labels are used.

NoData is never turned into 0 or into "non-flood": a cell with any missing ACTIVE indicator receives NaN (index) and is reported in the domain-class raster.
The flattened-water signature (DEM == 0 or a >= N-cell constant-value plateau) is a PROVISIONAL DEM-artefact flag re-implemented here independently from
the S1WC-2 design; it is not a water mask and not a ground-truth statement.
"""
import numpy as np
from scipy import ndimage as ndi
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.stats import rankdata

# domain classes (uint8 raster)
DOM_OUTSIDE, DOM_SCORED, DOM_WATER_SIG, DOM_MISSING = 255, 1, 2, 3
DOMAIN_NAMES = {DOM_SCORED: "scored (land, all active indicators valid)",
                DOM_WATER_SIG: "excluded: provisional DEM flattened-water signature",
                DOM_MISSING: "excluded: >=1 active indicator missing (NoData, not zero)",
                DOM_OUTSIDE: "outside provisional AOI"}


# ------------------------------------------------------------------------------------------------------------------------------ grid / alignment
def alignment_problems(info, grid, tol=1e-6):
    """info: dict(shape, crs, transform(6-tuple), count). Empty list = raster is exactly on the master grid (no resampling is ever done)."""
    p = []
    if tuple(info["shape"]) != tuple(grid.shape):
        p.append(f"shape {tuple(info['shape'])} != master grid {tuple(grid.shape)}")
    if str(info["crs"]).upper().replace("EPSG:", "") != str(grid.crs).upper().replace("EPSG:", ""):
        p.append(f"CRS {info['crs']} != {grid.crs}")
    if any(abs(a - b) > tol for a, b in zip(tuple(info["transform"])[:6], tuple(grid.transform)[:6])):
        p.append(f"transform {tuple(info['transform'])[:6]} != master {tuple(grid.transform)[:6]}")
    if info.get("count") != 1:
        p.append(f"{info.get('count')} bands != 1")
    return p


def to_float_nan(arr, nodata):
    """float64 copy with NoData (and non-finite) -> NaN. Never 0."""
    a = np.asarray(arr).astype("float64", copy=True)
    if nodata is not None:
        a[a == float(nodata)] = np.nan
    a[~np.isfinite(a)] = np.nan
    return a


# ------------------------------------------------------------------------------------------------------------------------------ water-signature
def plateau_signature(dem, inside, min_plateau_cells=30, nodata=-9999.0):
    """Provisional DEM flattened-water signature: DEM == 0 OR membership of a 4-connected constant-value plateau of >= min_plateau_cells cells.
    Re-implemented independently (idea documented in docs/s1_water_candidates_v2.md, not imported). Returns (signature_bool, n_zero, n_plateau_only).
    Only cells inside the AOI with finite, non-NoData DEM are considered; everything else is False (not asserted)."""
    d = np.asarray(dem, dtype="float64")
    ok = np.asarray(inside, bool) & np.isfinite(d) & (d != nodata)
    h, w = d.shape
    idx = np.arange(h * w).reshape(h, w)
    rows, cols = [], []
    eh = ok[:, :-1] & ok[:, 1:] & (d[:, :-1] == d[:, 1:])
    rows.append(idx[:, :-1][eh]); cols.append(idx[:, 1:][eh])
    ev = ok[:-1, :] & ok[1:, :] & (d[:-1, :] == d[1:, :])
    rows.append(idx[:-1, :][ev]); cols.append(idx[1:, :][ev])
    r = np.concatenate(rows); c = np.concatenate(cols)
    g = sparse.coo_matrix((np.ones(r.size, dtype=np.int8), (r, c)), shape=(h * w, h * w))
    _, lab = connected_components(g, directed=False)
    sizes = np.bincount(lab)
    plateau = (sizes[lab] >= min_plateau_cells).reshape(h, w) & ok
    zero = ok & (d == 0.0)
    sig = zero | plateau
    return sig, int(zero.sum()), int((plateau & ~zero).sum())


# ------------------------------------------------------------------------------------------------------------------------------ derived indicators
def nearest_drainage(drain, ok_cells=None):
    """Euclidean distance (in cells) and the (row, col) of the nearest drainage cell. drain: bool array (True = drainage cell).
    Distance is measured over the whole grid but only to drainage cells given (drainage outside the AOI is not available, so distances near the AOI
    edge are truncated - disclosed). Returns (dist_cells float64, rows int, cols int). If there is no drainage cell, returns NaN arrays."""
    drain = np.asarray(drain, bool)
    if not drain.any():
        nan = np.full(drain.shape, np.nan)
        zi = np.zeros(drain.shape, dtype=int)   # indices are meaningless when there is no drainage; distances/HAND are NaN
        return nan, zi, zi
    dist, (ir, ic) = ndi.distance_transform_edt(~drain, return_indices=True)
    return dist, ir, ic


def hand_proxy(dem_cond, ir, ic, dist_cells):
    """Height above the NEAREST drainage cell (Euclidean nearest, NOT flow-path HAND) = conditioned DEM - conditioned DEM at that drainage cell.
    Negative values (nearest drainage cell is higher than the cell) are clipped to 0 and counted. Returns (hand, n_clipped)."""
    z = np.asarray(dem_cond, dtype="float64")
    zd = z[ir, ic]
    raw = z - zd
    clipped = np.isfinite(raw) & (raw < 0)
    out = np.where(np.isfinite(raw), np.maximum(raw, 0.0), np.nan)
    return out, int(clipped.sum())


def twi_clamp_mask(slope_deg, min_slope_deg=0.1):
    """True where TWI used the slope clamp (slope < 0.1 deg; src/geospatial/hydrology.py). TWI there is a function of the clamp, not of the terrain."""
    s = np.asarray(slope_deg, dtype="float64")
    return np.isfinite(s) & (s < min_slope_deg)


# ------------------------------------------------------------------------------------------------------------------------------ normalisation
def _apply_transform(x, transform):
    x = np.asarray(x, dtype="float64")
    if transform in (None, "none", "linear"):
        return x.copy()
    if transform == "log10":
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.log10(x)
        out[~(x > 0)] = np.nan          # log of a non-positive value is undefined: NaN, not 0
        return out
    if transform == "log1p":
        with np.errstate(invalid="ignore"):
            out = np.log1p(x)
        out[~(x > -1)] = np.nan
        return out
    raise ValueError(f"unknown transform {transform!r}")


def normalise(x, domain, method="rank", direction="higher", transform=None, p_lo=2.0, p_hi=98.0):
    """Normalise one indicator to a 0..1 score where 1 = MORE susceptible, using ONLY `domain` cells to define the reference population.
    method 'rank': mid-rank percentile (ties get the average rank) -> (rank-0.5)/n.
    method 'robust_minmax': clip to the [p_lo, p_hi] percentiles of the domain, then linear 0..1.
    direction 'higher' (larger value = more susceptible) or 'lower' (smaller value = more susceptible; score is inverted).
    Cells outside `domain` or with a NaN value get NaN (never 0). A degenerate indicator (no spread) gives all-NaN and info['degenerate']=True.
    Returns (score, info)."""
    if direction not in ("higher", "lower"):
        raise ValueError("direction must be 'higher' or 'lower'")
    t = _apply_transform(x, transform)
    use = np.asarray(domain, bool) & np.isfinite(t)
    out = np.full(t.shape, np.nan)
    info = {"method": method, "direction": direction, "transform": transform or "none", "n_ref": int(use.sum()), "degenerate": False,
            "p_lo": None, "p_hi": None, "lo": None, "hi": None}
    if use.sum() < 2:
        info["degenerate"] = True
        return out, info
    v = t[use]
    if method == "rank":
        if np.nanmax(v) == np.nanmin(v):
            info["degenerate"] = True
            return out, info
        s = (rankdata(v, method="average") - 0.5) / v.size
    elif method == "robust_minmax":
        lo, hi = np.percentile(v, [p_lo, p_hi])
        info.update(p_lo=p_lo, p_hi=p_hi, lo=float(lo), hi=float(hi))
        if not hi > lo:
            info["degenerate"] = True
            return out, info
        s = (np.clip(v, lo, hi) - lo) / (hi - lo)
    else:
        raise ValueError(f"unknown method {method!r}")
    if direction == "lower":
        s = 1.0 - s
    out[use] = s
    return out, info


# ------------------------------------------------------------------------------------------------------------------------------ index
def normalise_weights(weights):
    """Weights must be finite and >= 0 with a positive sum. Returns weights scaled to sum 1 (zero-weight indicators stay 0 = inactive)."""
    w = {k: float(v) for k, v in weights.items()}
    if any((not np.isfinite(v)) or v < 0 for v in w.values()):
        raise ValueError("weights must be finite and non-negative")
    s = sum(w.values())
    if not s > 0:
        raise ValueError("at least one weight must be positive")
    return {k: v / s for k, v in w.items()}


def weighted_index(scores, weights):
    """Weighted arithmetic mean of the 0..1 scores of ACTIVE (weight > 0) indicators. A cell with a NaN in ANY active indicator is NaN (never 0).
    scores: {name: 2-D array}. Zero-weight indicators are ignored entirely (their NaNs do not propagate)."""
    w = normalise_weights(weights)
    active = [k for k, v in w.items() if v > 0]
    missing = [k for k in active if k not in scores]
    if missing:
        raise KeyError(f"no score for active indicator(s): {missing}")
    shape = scores[active[0]].shape
    acc = np.zeros(shape)
    for k in active:
        acc = acc + w[k] * scores[k]       # NaN propagates
    return acc


def percentile_of(index, domain):
    """Mid-rank percentile (0..100) of the index within the scored domain; NaN elsewhere."""
    out = np.full(index.shape, np.nan)
    use = np.asarray(domain, bool) & np.isfinite(index)
    if use.any():
        out[use] = 100.0 * (rankdata(index[use], method="average") - 0.5) / use.sum()
    return out


def relative_classes(index, domain, n=5):
    """Equal-count (quantile) relative classes 1..n over the scored domain: rank-based, NOT absolute levels, NOT risk categories. 0 = not scored."""
    out = np.zeros(index.shape, dtype="uint8")
    use = np.asarray(domain, bool) & np.isfinite(index)
    if use.any():
        p = percentile_of(index, use)[use]
        out[use] = (np.minimum((p / (100.0 / n)).astype(int), n - 1) + 1).astype("uint8")
    return out


# ------------------------------------------------------------------------------------------------------------------------------ hotspots
def top_mask(index, domain, quantile=0.90):
    """Cells at or above the `quantile` of the index within the scored domain (rank-based; the share is by construction ~ 1-quantile)."""
    use = np.asarray(domain, bool) & np.isfinite(index)
    m = np.zeros(index.shape, bool)
    if use.any():
        thr = np.quantile(index[use], quantile)
        m[use] = index[use] >= thr
    return m


def label_hotspots(mask, min_cells=25):
    """8-neighbour connected components of `mask` with >= min_cells cells. Returns (label_raster int32, n_hotspots, n_dropped_small_components).
    Labels are renumbered 1..n in raster-scan order (deterministic); they are NOT the ranking."""
    lab, n = ndi.label(mask, structure=np.ones((3, 3), int))
    if n == 0:
        return lab.astype("int32"), 0, 0
    sizes = np.bincount(lab.ravel())[1:]
    keep = np.where(sizes >= min_cells)[0] + 1
    remap = np.zeros(n + 1, dtype="int32")
    remap[keep] = np.arange(1, keep.size + 1, dtype="int32")
    return remap[lab], int(keep.size), int(n - keep.size)


def hotspot_table(label, index, raw_stack, score_stack, res_m, topfreq=None, scenario_means=None):
    """One row per hotspot: area, mean/max index, mean raw and mean normalised indicator values, and (optional) robustness across weight scenarios.
    scenario_means: {scenario_name: {hotspot_id: mean index of that fixed geometry under that scenario}}; the hotspot GEOMETRY (from the base index) is held
    fixed and re-ranked among hotspots under each scenario (rank 1 = highest mean index). Rank by BASE mean index; ties: larger area, then lower id."""
    n = int(label.max())
    rows = []
    for k in range(1, n + 1):
        m = label == k
        r = {"hotspot_id": k, "n_cells": int(m.sum()), "area_ha": float(m.sum() * res_m * res_m / 1e4),
             "mean_index": float(np.nanmean(index[m])), "max_index": float(np.nanmax(index[m])), "min_index": float(np.nanmin(index[m]))}
        for nme, a in raw_stack.items():
            r[f"mean_{nme}"] = float(np.nanmean(a[m])) if np.isfinite(a[m]).any() else float("nan")
        for nme, a in score_stack.items():
            r[f"score_{nme}"] = float(np.nanmean(a[m])) if np.isfinite(a[m]).any() else float("nan")
        if topfreq is not None:
            r["mean_top_decile_frequency"] = float(np.nanmean(topfreq[m]))
        rows.append(r)
    if not rows:
        return rows
    for i, r in enumerate(sorted(rows, key=lambda r: (-r["mean_index"], -r["n_cells"], r["hotspot_id"])), 1):
        r["rank_by_mean_index"] = i
    for i, r in enumerate(sorted(rows, key=lambda r: (-r["n_cells"], r["hotspot_id"])), 1):
        r["rank_by_area"] = i
    if scenario_means:
        ranks = {r["hotspot_id"]: [] for r in rows}
        for nm, means in scenario_means.items():
            srt = sorted(rows, key=lambda r: (-means[r["hotspot_id"]], -r["n_cells"], r["hotspot_id"]))
            for i, r in enumerate(srt, 1):
                ranks[r["hotspot_id"]].append(i)
        for r in rows:
            rk = np.array(ranks[r["hotspot_id"]])
            r["rank_min_across_scenarios"] = int(rk.min())
            r["rank_max_across_scenarios"] = int(rk.max())
            r["rank_median_across_scenarios"] = float(np.median(rk))
            r["frac_scenarios_in_top5"] = float((rk <= 5).mean())
            r["n_scenarios"] = int(rk.size)
    return sorted(rows, key=lambda r: r["rank_by_mean_index"])


# ------------------------------------------------------------------------------------------------------------------------------ sensitivity
def scenario_weights(base, spec):
    """Expand scenario spec into {name: weights}. spec: {'emphasis': {name: {group_weights_or_explicit}}, 'drop_one': bool, 'groups': {...}}.
    Kept simple and explicit: see config/susceptibility.json."""
    out = {}
    names = list(base)
    for nm, w in (spec.get("explicit") or {}).items():
        full = {k: float(w.get(k, 0.0)) for k in names}
        out[nm] = full
    if spec.get("drop_one"):
        for k in names:
            w = {j: (0.0 if j == k else float(base[j])) for j in names}
            out[f"drop_{k}"] = w
    return out


def random_weights(names, n, seed, concentration=5.0):
    """n seeded Dirichlet(concentration * ones) weight vectors (mean = equal weights). Deterministic for a given (names, n, seed, concentration)."""
    rng = np.random.default_rng(int(seed))
    d = rng.dirichlet(np.full(len(names), float(concentration)), size=int(n))
    return [dict(zip(names, row)) for row in d]


def compare_to_base(base_idx, idx, domain, quantile=0.90):
    """Spearman rank correlation and top-quantile Jaccard of a scenario index vs the base index over the scored domain."""
    use = np.asarray(domain, bool) & np.isfinite(base_idx) & np.isfinite(idx)
    a, b = base_idx[use], idx[use]
    ra, rb = rankdata(a), rankdata(b)
    ra = ra - ra.mean(); rb = rb - rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    rho = float((ra * rb).sum() / den) if den > 0 else float("nan")
    ta = a >= np.quantile(a, quantile); tb = b >= np.quantile(b, quantile)
    union = (ta | tb).sum()
    jac = float((ta & tb).sum() / union) if union else float("nan")
    return rho, jac


def indicator_correlation(stack, domain):
    """Spearman correlation matrix between normalised-score (or raw) indicators over the scored domain (pairs with NaN dropped)."""
    names = list(stack)
    use = np.asarray(domain, bool)
    for k in names:
        use = use & np.isfinite(stack[k])
    R = np.full((len(names), len(names)), np.nan)
    if use.sum() < 3:
        return names, R
    ranks = [rankdata(stack[k][use]) for k in names]
    ranks = [r - r.mean() for r in ranks]
    for i in range(len(names)):
        for j in range(len(names)):
            den = np.sqrt((ranks[i] ** 2).sum() * (ranks[j] ** 2).sum())
            R[i, j] = float((ranks[i] * ranks[j]).sum() / den) if den > 0 else np.nan
    return names, R


# ------------------------------------------------------------------------------------------------------------------------------ descriptive
def describe(arr, inside, domain=None, nodata=None):
    """Coverage/validity + descriptive statistics for one layer. arr may contain NaN (already NoData->NaN). Statistics are over valid inside-AOI cells."""
    a = np.asarray(arr, dtype="float64")
    ins = np.asarray(inside, bool)
    valid = ins & np.isfinite(a)
    row = {"n_inside_aoi": int(ins.sum()), "n_valid_inside_aoi": int(valid.sum()), "n_nodata_inside_aoi": int((ins & ~np.isfinite(a)).sum()),
           "valid_fraction_inside_aoi": float(valid.sum() / max(ins.sum(), 1))}
    if valid.any():
        v = a[valid]
        row.update(min=float(v.min()), p01=float(np.percentile(v, 1)), p05=float(np.percentile(v, 5)), p25=float(np.percentile(v, 25)),
                   median=float(np.median(v)), p75=float(np.percentile(v, 75)), p95=float(np.percentile(v, 95)), p99=float(np.percentile(v, 99)),
                   max=float(v.max()), mean=float(v.mean()), std=float(v.std()), n_distinct=int(np.unique(v).size))
    if domain is not None:
        dv = np.asarray(domain, bool) & np.isfinite(a)
        row["n_valid_in_scored_domain"] = int(dv.sum())
        if dv.any():
            row["domain_mean"] = float(a[dv].mean()); row["domain_median"] = float(np.median(a[dv]))
    return row
