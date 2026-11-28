"""Unsupervised exploratory analytics on the ward feature matrix: PCA, clustering with stability, ward similarity,
spatial autocorrelation. No labels are used here; reported-presence shares per cluster are descriptive only."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .ward_features import FEATURE_SPEC

LOG_FEATURES = {"pop_density_cdmp", "facilities_per_km2", "med_dist_to_drainage_m", "med_hand_proxy_m", "slum_area_share",
                "dist_public_health_km", "relief_capacity_per_1000", "s1_class1_any_share", "sus_a_share_top_decile"}


def model_features():
    return [n for n, _, use, _ in FEATURE_SPEC if use]


def prepare(t: pd.DataFrame, features=None):
    """log1p for skewed non-negative features, then z-score. Wards with any missing feature are dropped (listed)."""
    f = features or model_features()
    x = t[["ward_no"] + f].copy()
    dropped = x[x[f].isna().any(axis=1)].ward_no.tolist()
    x = x.dropna(subset=f).reset_index(drop=True)
    X = x[f].astype(float).copy()
    for c in f:
        if c in LOG_FEATURES:
            X[c] = np.log1p(X[c].clip(lower=0) * (100 if X[c].max() <= 1 else 1))
    mu, sd = X.mean(), X.std(ddof=0).replace(0, 1)
    Z = (X - mu) / sd
    return x.ward_no.values, Z, dropped


def pca(Z):
    from sklearn.decomposition import PCA
    p = PCA().fit(Z.values)
    ev = pd.DataFrame({"component": [f"PC{i+1}" for i in range(len(p.explained_variance_ratio_))], "explained_variance_ratio": p.explained_variance_ratio_,
                       "cumulative": np.cumsum(p.explained_variance_ratio_)})
    load = pd.DataFrame(p.components_.T, index=Z.columns, columns=ev.component).reset_index().rename(columns={"index": "feature"})
    scores = pd.DataFrame(p.transform(Z.values)[:, :3], columns=["PC1", "PC2", "PC3"])
    return ev, load, scores


def cluster_scan(Z, ks=range(2, 9), n_boot=100, seed=20261128):
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    rng = np.random.default_rng(seed)
    rows, fits = [], {}
    for k in ks:
        km = KMeans(n_clusters=k, n_init=20, random_state=seed).fit(Z.values)
        lab = km.labels_
        aris = []
        for _ in range(n_boot):
            idx = rng.choice(len(Z), len(Z), replace=True)
            kb = KMeans(n_clusters=k, n_init=5, random_state=int(rng.integers(1e9))).fit(Z.values[idx])
            aris.append(adjusted_rand_score(lab, kb.predict(Z.values)))
        ag = AgglomerativeClustering(n_clusters=k, linkage="ward").fit(Z.values).labels_
        rows.append({"k": k, "silhouette": silhouette_score(Z.values, lab), "bootstrap_ari_mean": float(np.mean(aris)),
                     "bootstrap_ari_p05": float(np.percentile(aris, 5)), "ari_vs_ward_linkage": adjusted_rand_score(lab, ag),
                     "smallest_cluster": int(np.bincount(lab).min())})
        fits[k] = lab
    scan = pd.DataFrame(rows)
    ok = scan[(scan.bootstrap_ari_mean >= 0.75) & (scan.smallest_cluster >= 8)]
    k_sel = int((ok if len(ok) else scan).sort_values(["silhouette", "k"], ascending=[False, True]).iloc[0].k)
    return scan, k_sel, fits[k_sel]


def profiles(t, ward_ids, labels, Z):
    d = t.set_index("ward_no").loc[ward_ids].copy()
    d["cluster"] = labels
    prof = d.groupby("cluster").agg(n_wards=("zone_no", "size"), mean_area_km2=("area_km2", "mean"),
                                    reported_share_2015=("reported_2015", lambda s: s.notna().mean()),
                                    reported_share_2021=("reported_2021", lambda s: s.notna().mean()),
                                    mean_records_2021=("cdmp_records_2021", "mean"))
    zc = pd.DataFrame(Z.values, columns=Z.columns)
    zc["cluster"] = labels
    centre = zc.groupby("cluster").mean().add_prefix("z_")
    return prof.join(centre).reset_index()


def similarity(ward_ids, Z, k=5):
    from sklearn.neighbors import NearestNeighbors
    nn = NearestNeighbors(n_neighbors=k + 1).fit(Z.values)
    d, i = nn.kneighbors(Z.values)
    rows = []
    for a in range(len(ward_ids)):
        for r in range(1, k + 1):
            rows.append({"ward_no": int(ward_ids[a]), "rank": r, "similar_ward_no": int(ward_ids[i[a, r]]), "feature_distance": float(d[a, r])})
    return pd.DataFrame(rows)


def contiguity(wards, tol_m=1.0):
    """Queen-style contiguity: wards whose boundaries are within tol_m."""
    import shapely
    geoms = wards.geometry.buffer(tol_m).values
    tree = shapely.STRtree(geoms)
    pairs = tree.query(geoms, predicate="intersects")
    W = {int(w): set() for w in wards.ward_no}
    ids = wards.ward_no.values
    for a, b in zip(*pairs):
        if a != b:
            W[int(ids[a])].add(int(ids[b]))
    return W


def morans_i(values: pd.Series, W: dict, n_perm=999, seed=20261128):
    """Global Moran's I (row-standardised contiguity) with a permutation p-value; NaN values are dropped with their links."""
    v = values.dropna()
    ids = list(v.index)
    pos = {w: i for i, w in enumerate(ids)}
    x = v.values.astype(float)
    n = len(x)
    rows, cols = [], []
    for w in ids:
        nb = [pos[j] for j in W.get(w, ()) if j in pos]
        for j in nb:
            rows.append(pos[w]); cols.append(j)
    rows, cols = np.array(rows), np.array(cols)
    deg = np.bincount(rows, minlength=n).astype(float)
    wts = 1.0 / deg[rows]

    def I(xx):
        z = xx - xx.mean()
        return (n / wts.sum()) * np.sum(wts * z[rows] * z[cols]) / np.sum(z * z)
    obs = I(x)
    rng = np.random.default_rng(seed)
    perm = np.array([I(rng.permutation(x)) for _ in range(n_perm)])
    return {"n": n, "morans_i": float(obs), "expected": -1 / (n - 1), "p_perm_two_sided": float((np.sum(np.abs(perm - perm.mean()) >= abs(obs - perm.mean())) + 1) / (n_perm + 1)),
            "isolated_units": int((deg == 0).sum())}
