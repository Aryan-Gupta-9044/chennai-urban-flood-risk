"""ML-EXP-1.1: methodological review of the ML-EXP-1 presence-background (PB) test. Adds statistics; changes nothing.

Why this exists
---------------
ML-EXP-1 reported the *pooled* out-of-fold PB-AUC: scores from 15 separately trained leave-one-zone-out models are
pooled and ranked together. Scores from different models are not on a common scale, and report prevalence differs
between zones, so pooled AUC mixes (a) within-zone ranking skill with (b) between-zone score offsets. It was compared
with a null that has the same pooling, which keeps the test valid, but it is not a pure measure of ranking skill.

This module adds, for the same 16 feature-set x model x event combinations and the same buffered zone folds:

* **within-zone (stratified) PB-AUC**: AUC computed only over (presence, background) pairs that lie in the *same* test
  zone, i.e. each pair is ranked by one model. Equivalent to the pair-weighted mean of per-zone AUCs.
* **median per-zone AUC** (reported by ML-EXP-1 as `fold_pb_auc_median`), now with a null.
* two nulls, each re-running the full cross-validation:
  - *global* label permutation (as ML-EXP-1);
  - *zone-stratified* permutation: labels shuffled within each zone, which preserves every zone's report prevalence
    (removes the prevalence-shift component) and tests within-zone ranking only.
* Holm and Benjamini-Hochberg adjustment across the 16 combinations, per statistic and null.

Still presence-background: background wards are UNLABELLED, not negatives. Nothing here is accuracy, calibration or a
flood probability. Calibration is not estimable without true negatives and is not attempted.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from . import presence_only as po


def within_zone_auc(y, s, zones):
    """Pair-weighted within-zone AUC (ties count 1/2) and the list of per-zone AUCs (NaN if a zone lacks a class)."""
    num = den = 0.0
    per = []
    for z in np.unique(zones):
        m = (zones == z) & np.isfinite(s)
        yz, sz = y[m], s[m]
        pos, neg = sz[yz == 1], sz[yz == 0]
        if len(pos) == 0 or len(neg) == 0:
            per.append(np.nan)
            continue
        diff = pos[:, None] - neg[None, :]
        wins = (diff > 0).sum() + 0.5 * (diff == 0).sum()
        per.append(wins / diff.size)
        num += wins
        den += diff.size
    return (num / den if den else np.nan), np.array(per, dtype=float)


def stats(y, s, zones):
    wz, per = within_zone_auc(y, s, zones)
    return {"pooled": po.pb_auc(y, s), "within_zone": float(wz), "zone_median": float(np.nanmedian(per)) if np.isfinite(per).any() else np.nan,
            "zones_scored": int(np.isfinite(per).sum())}


def _perm(y, zones, rng, stratified):
    if not stratified:
        return rng.permutation(y)
    yp = y.copy()
    for z in np.unique(zones):
        idx = np.flatnonzero(zones == z)
        yp[idx] = y[rng.permutation(idx)]
    return yp


def _null_once(d, y, zones, feats, kind, folds, seed, stratified):
    rng = np.random.default_rng(seed)
    yp = _perm(y, zones, rng, stratified)
    return stats(yp, po.oof_scores(d, yp, feats, kind, folds), zones)


def holm(p):
    p = np.asarray(p, float)
    o = np.argsort(p)
    adj = np.empty_like(p)
    run = 0.0
    for r, i in enumerate(o):
        run = max(run, min(1.0, (len(p) - r) * p[i]))
        adj[i] = run
    return adj


def bh(p):
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)[::-1]
    adj = np.empty_like(p)
    run = 1.0
    for r, i in enumerate(o):
        run = min(run, p[i] * n / (n - r))
        adj[i] = run
    return adj


def review(t, wards, n_perm=None, buffer_m=500.0, seed=20261128, n_jobs=1, events=(2015, 2021)):
    """Return (per-combination table, null draws long table, folds)."""
    from joblib import Parallel, delayed
    n_perm = n_perm or {"logistic_l2": 200, "random_forest": 40}
    feats_all = sorted({f for v in po.FEATURE_SETS.values() for f in v})
    d = t.dropna(subset=feats_all).reset_index(drop=True)
    folds = po.buffered_zone_folds(d, wards, buffer_m)
    zones = d.zone_no.values
    rows, draws = [], []
    for ev in events:
        y = d[f"reported_{ev}"].notna().astype(int).values
        for name, feats in po.FEATURE_SETS.items():
            for kind in ("logistic_l2", "random_forest"):
                if name.startswith("F0") and kind == "random_forest":
                    continue
                s = po.oof_scores(d, y, feats, kind, folds)
                obs = stats(y, s, zones)
                row = {"event": ev, "feature_set": name, "model": kind, "n_wards": len(d), "n_presence": int(y.sum()),
                       "pooled_auc": obs["pooled"], "within_zone_auc": obs["within_zone"], "zone_median_auc": obs["zone_median"],
                       "zones_scored": obs["zones_scored"]}
                for stratified in (False, True):
                    tag = "zone_stratified" if stratified else "global"
                    base = seed + (1_000_000 if stratified else 0) + 1_000 * (ev % 100) + zlib.crc32(f'{name}|{kind}'.encode()) % 997 * 10_000
                    res = Parallel(n_jobs=n_jobs)(delayed(_null_once)(d, y, zones, feats, kind, folds, base + i, stratified) for i in range(n_perm[kind]))
                    for stat in ("pooled", "within_zone", "zone_median"):
                        nd = np.array([r[stat] for r in res], float)
                        nd = nd[np.isfinite(nd)]
                        row[f"{stat}__{tag}__null_mean"] = float(nd.mean()) if len(nd) else np.nan
                        row[f"{stat}__{tag}__null_p95"] = float(np.percentile(nd, 95)) if len(nd) else np.nan
                        row[f"{stat}__{tag}__p"] = float((np.sum(nd >= obs[stat]) + 1) / (len(nd) + 1)) if len(nd) else np.nan
                        draws += [{"event": ev, "feature_set": name, "model": kind, "null": tag, "stat": stat, "value": float(v)} for v in nd]
                    row[f"n_perm__{tag}"] = n_perm[kind]
                rows.append(row)
    tab = pd.DataFrame(rows)
    for col in [c for c in tab.columns if c.endswith("__p")]:
        tab[col.replace("__p", "__p_holm")] = holm(tab[col].values)
        tab[col.replace("__p", "__p_bh")] = bh(tab[col].values)
    return tab, pd.DataFrame(draws), folds
