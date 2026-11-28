"""Presence-background (PB) association analysis at ward x event level.

What it is: does a multi-source indicator profile rank wards that the GCC listed as inundated (presence, E3)
above the remaining, UNLABELLED wards (background)? This is the presence-background framing used for
presence-only data (e.g. species-distribution modelling). The background is NOT "not flooded".

What it is NOT: flood prediction, flood probability, or accuracy. PB-AUC measures discrimination of presences
from background; with an unknown share of unreported flooded wards inside the background, its ceiling is < 1
and it cannot be converted into precision/recall/accuracy.

Controls built in:
* leave-one-zone-out spatial blocks (15 GCC zones) + a buffer that removes training wards within `buffer_m` of the test zone;
* a ward-AREA-only model (reporting opportunity grows with area) and a POPULATION-DENSITY-only model (reporting effort proxy);
* label-permutation null (whole CV re-run) and cross-event transfer (2015 -> 2021, 2021 -> 2015), noting that both
  lists come from the same agency (not independent events in the statistical sense).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .explore import LOG_FEATURES

FEATURE_SETS = {
    "F0_area_only (control)": ["area_km2"],
    "F0b_pop_density_only (control)": ["pop_density_cdmp"],
    "F1_physical (SUS-1 + terrain + S1)": ["sus_a_mean_pct", "sus_a_share_top_decile", "med_elevation_m", "med_slope_deg", "med_hand_proxy_m",
                                          "med_dist_to_drainage_m", "p90_log10_flow_acc", "s1_class1_any_share"],
    "F2_all_indicators": ["sus_a_mean_pct", "sus_a_share_top_decile", "med_elevation_m", "med_slope_deg", "med_hand_proxy_m", "med_dist_to_drainage_m",
                          "p90_log10_flow_acc", "s1_class1_any_share", "pop_density_cdmp", "road_surface_share", "facilities_per_km2",
                          "slum_area_share", "dist_public_health_km", "relief_capacity_per_1000"],
}
FEATURE_SETS["F3_all_indicators + area"] = FEATURE_SETS["F2_all_indicators"] + ["area_km2"]


def _design(t, feats):
    X = t[feats].astype(float).copy()
    for c in feats:
        if c in LOG_FEATURES or c == "area_km2":
            X[c] = np.log1p(X[c].clip(lower=0) * (100 if X[c].max() <= 1 else 1))
    return X


def make_model(kind, seed=20261128):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "logistic_l2":
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
    if kind == "random_forest":
        return RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=5, random_state=seed, n_jobs=1)
    raise ValueError(kind)


def buffered_zone_folds(t, wards, buffer_m=500.0):
    """Leave-one-zone-out; training excludes wards within buffer_m of any test-zone ward."""
    g = wards.set_index("ward_no").loc[t.ward_no].geometry.reset_index(drop=True)
    zones = t.zone_no.values
    folds = []
    for z in np.unique(zones):
        test = np.flatnonzero(zones == z)
        tz = g.iloc[test].union_all().buffer(buffer_m)
        near = np.flatnonzero(g.intersects(tz).values)
        train = np.setdiff1d(np.arange(len(t)), np.union1d(test, near))
        folds.append((int(z), train, test, int(len(near) - len(test))))
    return folds


def oof_scores(t, y, feats, kind, folds, seed=20261128):
    X = _design(t, feats).values
    s = np.full(len(t), np.nan)
    for _, tr, te, _ in folds:
        if len(np.unique(y[tr])) < 2:
            continue
        m = make_model(kind, seed).fit(X[tr], y[tr])
        s[te] = m.predict_proba(X[te])[:, 1]
    return s


def pb_auc(y, s):
    from sklearn.metrics import roc_auc_score
    ok = np.isfinite(s)
    return float(roc_auc_score(y[ok], s[ok])) if len(np.unique(y[ok])) == 2 else np.nan


def evaluate(t, wards, events=(2015, 2021), kinds=("logistic_l2", "random_forest"), n_perm=None, buffer_m=500.0, seed=20261128):
    n_perm = n_perm or {"logistic_l2": 100, "random_forest": 20}
    feats_all = sorted({f for v in FEATURE_SETS.values() for f in v})
    d = t.dropna(subset=feats_all).reset_index(drop=True)
    folds = buffered_zone_folds(d, wards, buffer_m)
    rng = np.random.default_rng(seed)
    rows, oof = [], {}
    for ev in events:
        y = d[f"reported_{ev}"].notna().astype(int).values      # 1 = reported presence, 0 = BACKGROUND (unlabelled, not negative)
        for name, feats in FEATURE_SETS.items():
            for kind in kinds:
                if name.startswith("F0") and kind == "random_forest":
                    continue
                s = oof_scores(d, y, feats, kind, folds, seed)
                auc = pb_auc(y, s)
                null = []
                for _ in range(n_perm[kind]):
                    yp = rng.permutation(y)
                    null.append(pb_auc(yp, oof_scores(d, yp, feats, kind, folds, seed)))
                null = np.array(null)
                fold_auc = [pb_auc(y[te], s[te]) for _, _, te, _ in folds]
                rows.append({"event": ev, "feature_set": name, "model": kind, "n_wards": len(d), "n_presence": int(y.sum()), "n_background": int((1 - y).sum()),
                             "pb_auc_oof": auc, "null_mean": float(null.mean()), "null_p95": float(np.percentile(null, 95)),
                             "p_perm_one_sided": float((np.sum(null >= auc) + 1) / (len(null) + 1)), "n_perm": len(null),
                             "fold_pb_auc_median": float(np.nanmedian(fold_auc)), "folds_scored": int(np.sum(np.isfinite(fold_auc)))})
                oof[(ev, name, kind)] = s
    return pd.DataFrame(rows), d, folds, oof


def transfer(d, kinds=("logistic_l2", "random_forest"), seed=20261128):
    rows = []
    for a, b in ((2015, 2021), (2021, 2015)):
        ya = d[f"reported_{a}"].notna().astype(int).values
        yb = d[f"reported_{b}"].notna().astype(int).values
        for name, feats in FEATURE_SETS.items():
            X = _design(d, feats).values
            for kind in kinds:
                if name.startswith("F0") and kind == "random_forest":
                    continue
                m = make_model(kind, seed).fit(X, ya)
                rows.append({"train_event": a, "test_event": b, "feature_set": name, "model": kind, "pb_auc_test_event": pb_auc(yb, m.predict_proba(X)[:, 1]),
                             "wards_presence_both_events": int(((ya == 1) & (yb == 1)).sum()),
                             "note": "same wards, different event lists from the same agency: tests temporal transfer of the association, not independent validation"})
    return pd.DataFrame(rows)


def importance(d, ev, feats, folds, seed=20261128, n_repeats=20):
    """Out-of-fold permutation importance (drop in PB-AUC) for the logistic model, plus full-data standardised coefficients."""
    from sklearn.inspection import permutation_importance
    y = d[f"reported_{ev}"].notna().astype(int).values
    X = _design(d, feats)
    drops = {f: [] for f in feats}
    for _, tr, te, _ in folds:
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        m = make_model("logistic_l2", seed).fit(X.values[tr], y[tr])
        r = permutation_importance(m, X.values[te], y[te], scoring="roc_auc", n_repeats=n_repeats, random_state=seed)
        for f, v in zip(feats, r.importances_mean):
            drops[f].append(v)
    m = make_model("logistic_l2", seed).fit(X.values, y)
    coef = m[-1].coef_[0]
    return pd.DataFrame({"event": ev, "feature": feats, "oof_perm_importance_mean": [np.mean(drops[f]) if drops[f] else np.nan for f in feats],
                         "folds_used": [len(drops[f]) for f in feats], "std_logistic_coef_full_data": coef}).sort_values("oof_perm_importance_mean", ascending=False)


def count_associations(t, feats, n_perm=999, seed=20261128):
    """Spearman association of report INTENSITY (records per km2; 0 means 'no listed record', not 'no flooding')
    with each indicator; plain permutation p-values ignore spatial autocorrelation and are therefore optimistic."""
    from scipy.stats import spearmanr
    rng = np.random.default_rng(seed)
    rows = []
    for ev in (2015, 2021):
        y = (t[f"cdmp_records_{ev}"] / t.area_km2).values
        for f in feats:
            x = t[f].values.astype(float)
            ok = np.isfinite(x) & np.isfinite(y)
            rho = spearmanr(x[ok], y[ok]).statistic
            null = np.array([spearmanr(x[ok], rng.permutation(y[ok])).statistic for _ in range(n_perm)])
            rows.append({"event": ev, "feature": f, "n": int(ok.sum()), "spearman_rho": float(rho),
                         "p_perm_two_sided_naive": float((np.sum(np.abs(null) >= abs(rho)) + 1) / (n_perm + 1))})
    return pd.DataFrame(rows)
