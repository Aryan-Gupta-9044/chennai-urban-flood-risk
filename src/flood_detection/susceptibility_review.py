"""SUS-1 methodology-review helpers (experimental, additive, pure numpy/scipy; no file writes).

Everything here compares ALTERNATIVE EXPLORATORY constructions with the accepted SUS-1 baseline. None of it is validation: no flood labels, no S1WC-1 label use,
no accuracy metric. Agreement between alternatives measures robustness to construction choices, not correctness against reality."""
import numpy as np
from scipy import ndimage as ndi
from scipy.stats import rankdata


# ------------------------------------------------------------------------------------------------------------------------------ redundancy
def group_weights(groups, group_w=None):
    """Indicator weights from {group: [indicators]} with group-level weights (default equal) split equally within each group. Sums to 1."""
    names = list(groups)
    gw = {g: 1.0 for g in names} if group_w is None else {g: float(group_w[g]) for g in names}
    tot = sum(gw.values())
    out = {}
    for g, members in groups.items():
        for m in members:
            if m in out:
                raise ValueError(f"indicator {m} is in more than one group")
            out[m] = gw[g] / tot / len(members)
    return out


def spearman_matrix(vectors):
    """Spearman correlation matrix for {name: 1-D array} (all finite, same length)."""
    names = list(vectors)
    r = [rankdata(vectors[k]) for k in names]
    r = [x - x.mean() for x in r]
    n = len(names)
    R = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            den = np.sqrt((r[i] ** 2).sum() * (r[j] ** 2).sum())
            R[i, j] = R[j, i] = (r[i] * r[j]).sum() / den if den > 0 else np.nan
    return names, R


def vif_from_corr(R):
    """Variance-inflation factors = diagonal of the inverse correlation matrix. VIF_i = 1/(1-R2_i) of regressing indicator i on all the others."""
    return np.diag(np.linalg.inv(R))


def effective_n(R):
    """Participation ratio (sum lambda)^2 / sum lambda^2 of the correlation matrix: the number of 'equally informative independent' indicators."""
    lam = np.linalg.eigvalsh(R)
    return float(lam.sum() ** 2 / (lam ** 2).sum())


def contribution_shares(S, w):
    """For weights w (sum 1) and score vectors S: Spearman(score_i, index) and the covariance share cov(w_i s_i, index)/var(index) (shares sum to 1).
    The share shows how much of the index VARIATION each indicator drives - this is where redundancy turns into implicit double weighting."""
    names = [k for k in S if w.get(k, 0) > 0]
    idx = sum(w[k] * S[k] for k in names)
    vi = idx.var()
    rows = []
    ri = rankdata(idx)
    for k in S:
        wk = w.get(k, 0.0)
        cov = np.mean((wk * S[k] - (wk * S[k]).mean()) * (idx - idx.mean()))
        rk = rankdata(S[k])
        rho = float(np.corrcoef(rk, ri)[0, 1]) if wk > 0 else float("nan")
        rows.append({"indicator": k, "weight": wk, "variance_share_of_index": float(cov / vi) if vi > 0 else float("nan"), "spearman_with_index": rho})
    return rows


def rank_r2(y, xs):
    """R^2 of an OLS of rank(y) on the ranks of xs (list of arrays). Used to show TWI is (nearly) a function of slope and flow accumulation."""
    Y = rankdata(y).astype(float)
    X = np.column_stack([np.ones(len(Y))] + [rankdata(x).astype(float) for x in xs])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    res = Y - X @ beta
    return float(1 - (res ** 2).sum() / ((Y - Y.mean()) ** 2).sum())


# ------------------------------------------------------------------------------------------------------------------------------ hotspot geometry / metrics
def merge_close(mask, domain, iterations=2):
    """Exploratory continuity merge: binary closing (3x3, `iterations` times) of the top mask, restricted to the scored domain so excluded/outside cells are never absorbed."""
    if iterations <= 0:
        return np.asarray(mask, bool).copy()
    st = np.ones((3, 3), bool)
    padded = np.pad(np.asarray(mask, bool), iterations + 1)
    closed = ndi.binary_closing(padded, structure=st, iterations=iterations)[iterations + 1:-(iterations + 1), iterations + 1:-(iterations + 1)]
    return closed & np.asarray(domain, bool)


def shape_metrics(label, res_m):
    """Per-hotspot perimeter (exposed 4-neighbour edges x res), compactness 4*pi*A/P^2 (1 = disc-like; low = ragged/fragmented), bounding-box fill ratio,
    and number of 8-connected holes-free 'pieces' check (always 1 by construction). Returns {id: dict}."""
    n = int(label.max())
    out = {}
    if n == 0:
        return out
    sl = ndi.find_objects(label)
    for k in range(1, n + 1):
        s = sl[k - 1]
        sub = label[s] == k
        pad = np.pad(sub, 1)
        edges = (pad[1:-1, 1:-1] & ~pad[:-2, 1:-1]).sum() + (pad[1:-1, 1:-1] & ~pad[2:, 1:-1]).sum() + (pad[1:-1, 1:-1] & ~pad[1:-1, :-2]).sum() + (pad[1:-1, 1:-1] & ~pad[1:-1, 2:]).sum()
        A = sub.sum() * res_m ** 2
        P = edges * res_m
        out[k] = {"perimeter_m": float(P), "compactness": float(4 * np.pi * A / P ** 2) if P > 0 else float("nan"),
                  "bbox_fill_ratio": float(sub.sum() / sub.size)}
    return out


def excess_mass_by_label(v, lab_vec, thr, n, cell_area_ha):
    """Area-weighted susceptibility contribution of each hotspot: sum over its cells of max(index - thr, 0) x cell area (ha). thr = the top-decile threshold of that scenario."""
    ex = np.maximum(v - thr, 0.0)
    s = np.bincount(lab_vec, weights=ex, minlength=n + 1)[1:]
    return s * cell_area_ha


def mean_by_label(v, lab_vec, n):
    s = np.bincount(lab_vec, weights=v, minlength=n + 1)[1:]
    c = np.bincount(lab_vec, minlength=n + 1)[1:]
    return s / np.maximum(c, 1)


def ranks_desc(x):
    """Rank 1 = largest; ties broken by position (deterministic)."""
    order = np.lexsort((np.arange(len(x)), -np.asarray(x)))
    r = np.empty(len(x), int)
    r[order] = np.arange(1, len(x) + 1)
    return r


def stability_summary(metric_by_scenario, base_metric, k=10):
    """metric_by_scenario: (n_scen, n_hot) values; base_metric: (n_hot,). Returns per-hotspot rank min/max/median and summary figures for the BASE top-k.
    top_k_retention = mean over scenarios of |top-k(base) & top-k(scenario)| / k;  rel_range = (max-min)/n_hot."""
    M = np.asarray(metric_by_scenario)
    n_hot = M.shape[1]
    base_rank = ranks_desc(base_metric)
    R = np.vstack([ranks_desc(row) for row in M])
    kk = min(k, n_hot)
    top_base = set(np.where(base_rank <= kk)[0])
    ret = float(np.mean([len(top_base & set(np.where(r <= kk)[0])) / kk for r in R]))
    rmin, rmax, rmed = R.min(0), R.max(0), np.median(R, 0)
    tb = np.where(base_rank <= kk)[0]
    srho = float(np.mean([np.corrcoef(base_rank, r)[0, 1] for r in R]))
    return {"base_rank": base_rank, "rank_min": rmin, "rank_max": rmax, "rank_median": rmed,
            "top_k_retention": ret, "median_rank_range_topk": float(np.median((rmax - rmin)[tb])) if len(tb) else float("nan"),
            "median_rel_range_topk": float(np.median((rmax - rmin)[tb]) / n_hot) if len(tb) else float("nan"),
            "mean_rank_pearson_vs_base": srho, "n_hot": n_hot}


def agreement_class(base_top, alt_top, domain):
    """uint8: 0 neither, 1 baseline only, 2 alternative only, 3 both; 255 not scored."""
    out = np.full(base_top.shape, 255, dtype="uint8")
    d = np.asarray(domain, bool)
    out[d] = (base_top[d].astype(int) + 2 * alt_top[d].astype(int)).astype("uint8") * 0
    out[d] = np.where(base_top[d] & alt_top[d], 3, np.where(base_top[d], 1, np.where(alt_top[d], 2, 0))).astype("uint8")
    return out


def component_sizes(mask, connectivity8=True):
    st = np.ones((3, 3), int) if connectivity8 else None
    lab, n = ndi.label(mask, structure=st)
    return np.bincount(lab.ravel())[1:] if n else np.array([], int)
