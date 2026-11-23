#!/usr/bin/env python
"""Module G - Random Forest pipeline. Runs ONLY if verified-ish flood/non-flood labels and valid features exist.
Never fabricates results: if not ready, reports exactly what is missing."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.study_area import load_study_area, master_grid
from src.visualization import plots
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def find_labels():
    ext = sorted((paths.DATA_EXT / "flood_labels").glob("*.tif*"))
    sar = sorted(paths.DATA_PROC.glob("flood_extent_*_utm44n_30m.tif"))
    return [(p, paths.external_kind()) for p in ext] + [(p, "SAR PROXY") for p in sar]


def main():
    t0 = time.time()
    log = get_logger("G_rf")
    cfg = load_settings()["ml"]
    stack_p = paths.DATA_PROC / "feature_stack_utm44n_30m.tif"
    need = []
    labels = find_labels()
    if not stack_p.exists():
        need.append("feature stack (run Module E; needs DEM/land cover)")
    if not labels:
        need.append("flood/non-flood label raster(s): Sentinel-1 extents (Module F) or files in data/external/flood_labels/")
    if need:
        msg = "Random Forest NOT run - missing: " + "; ".join(need) + ". No metrics were produced."
        log.warning(msg)
        status.record("G", status.BLOCKED, msg,
                      files=["src/models/random_forest.py (pipeline code)"],
                      requirements=need + [f"At least {cfg['min_samples_per_class']} flood and {cfg['min_samples_per_class']} non-flood valid pixels."],
                      seconds=time.time() - t0)
        return
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    with rasterio.open(stack_p) as ds:
        X = ds.read().astype("float32")
        names = [ds.descriptions[i] or f"band{i+1}" for i in range(ds.count)]
    # Drop rainfall for a single-event study (near-constant over the city => no spatial information)
    keep = [i for i, n in enumerate(names) if np.nanstd(X[i]) > 1e-6]
    dropped = [names[i] for i in range(len(names)) if i not in keep]
    names = [names[i] for i in keep]
    X = X[keep]
    inside = G.inside_mask(grid, sa_utm.geometry)
    # pool all label rasters (first working version; event-wise temporal validation comes later)
    ys = []
    for p, k in labels:
        with rasterio.open(p) as ds:
            if ds.shape != grid.shape:
                log.warning("label %s not on master grid - skipped", p.name)
                continue
            ys.append(ds.read(1))
    if not ys:
        status.record("G", status.BLOCKED, "Label rasters exist but none are on the master grid.", seconds=time.time() - t0)
        return
    y = ys[0].astype("int16")
    for extra in ys[1:]:
        y = np.where((extra == 1) | (y == 1), 1, np.where((extra == 0) & (y == 0), 0, 255))
    valid = inside & np.isfinite(X).all(axis=0) & np.isin(y, [0, 1])
    n_pos, n_neg = int((valid & (y == 1)).sum()), int((valid & (y == 0)).sum())
    if min(n_pos, n_neg) < cfg["min_samples_per_class"]:
        msg = f"Random Forest NOT run: only {n_pos} flood / {n_neg} non-flood valid pixels (need >= {cfg['min_samples_per_class']} each)."
        status.record("G", status.BLOCKED, msg, requirements=["More/larger flood labels."], seconds=time.time() - t0)
        return

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score)
    from sklearn.model_selection import GroupKFold
    import joblib

    ii, jj = np.where(valid)
    rng = np.random.default_rng(cfg["random_state"])
    pos = np.where(y[ii, jj] == 1)[0]
    neg = np.where(y[ii, jj] == 0)[0]
    neg = rng.choice(neg, size=min(len(neg), len(pos) * cfg["neg_pos_ratio"]), replace=False)
    sel = np.concatenate([pos, neg])
    cap = cfg.get("max_train_samples", 100000)
    if len(sel) > cap:  # keep run time reasonable on a laptop; stratified by class
        keep_pos = rng.choice(pos, size=max(1, int(cap * len(pos) / len(sel))), replace=False)
        keep_neg = rng.choice(neg, size=max(1, cap - len(keep_pos)), replace=False)
        sel = np.concatenate([keep_pos, keep_neg])
        log.info("training sample capped at %d rows", len(sel))
    ii, jj = ii[sel], jj[sel]
    Xs = X[:, ii, jj].T
    ys_ = y[ii, jj].astype(int)
    blocks = (ii * grid.res // cfg["block_size_m"]).astype(int) * 10000 + (jj * grid.res // cfg["block_size_m"]).astype(int)
    log.info("training rows: %d (flood %d) from %d spatial blocks", len(ys_), int(ys_.sum()), len(np.unique(blocks)))
    n_splits = int(min(5, len(np.unique(blocks))))
    if n_splits < 2:
        status.record("G", status.BLOCKED, "Too few spatial blocks for spatial cross-validation.", seconds=time.time() - t0)
        return
    params = dict(n_estimators=cfg["n_estimators"], class_weight="balanced_subsample", n_jobs=-1,
                  random_state=cfg["random_state"], min_samples_leaf=3)
    oof = np.zeros(len(ys_))
    for tr, te in GroupKFold(n_splits=n_splits).split(Xs, ys_, blocks):
        m = RandomForestClassifier(**params).fit(Xs[tr], ys_[tr])
        oof[te] = m.predict_proba(Xs[te])[:, 1]
    pred = (oof >= 0.5).astype(int)
    metrics = {"validation": f"spatial block GroupKFold (k={n_splits}, {cfg['block_size_m']} m blocks)",
               "n_samples": int(len(ys_)), "n_flood": int(ys_.sum()), "features": names, "dropped_constant_features": dropped,
               "precision": float(precision_score(ys_, pred, zero_division=0)), "recall": float(recall_score(ys_, pred)),
               "f1": float(f1_score(ys_, pred)), "roc_auc": float(roc_auc_score(ys_, oof)),
               "confusion_matrix [[TN,FP],[FN,TP]]": confusion_matrix(ys_, pred).tolist(),
               "labels_used": [f"{p.name} ({k})" for p, k in labels],
               "caveats": ["Labels are SAR proxy / user-supplied; accuracy is relative to those labels only.",
                           "Slope is both a feature and part of the SAR flood-mask rule: possible circularity.",
                           "Spatial-block CV only; independent-event (2023) validation is a later stage.",
                           "Negatives were subsampled; metrics reflect that class balance."]}
    final = RandomForestClassifier(**params).fit(Xs, ys_)
    joblib.dump(final, paths.OUT_MODELS / "random_forest_v0.joblib")
    (paths.OUT_MODELS / "random_forest_v0_config.json").write_text(json.dumps({"params": params, "features": names}, indent=2, default=str))
    (paths.OUT_TAB / "rf_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    pd.DataFrame({"feature": names, "importance": final.feature_importances_}).sort_values("importance", ascending=False)\
        .to_csv(paths.OUT_TAB / "rf_feature_importance.csv", index=False)
    cm = np.array(metrics["confusion_matrix [[TN,FP],[FN,TP]]"])
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.imshow(cm, cmap="Blues")
    for a in range(2):
        for b in range(2):
            ax.text(b, a, cm[a, b], ha="center", va="center")
    ax.set_xticks([0, 1], ["No flood", "Flood"])
    ax.set_yticks([0, 1], ["No flood", "Flood"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Label")
    ax.set_title("RF confusion matrix (spatial CV)")
    fig.tight_layout()
    fig.savefig(paths.OUT_FIG / "rf_confusion_matrix.png", dpi=200)
    plt.close(fig)
    full = np.isfinite(X).all(axis=0) & inside
    fi, fj = np.where(full)
    prob = np.full(grid.shape, -9999.0, dtype="float32")
    prob[fi, fj] = final.predict_proba(X[:, fi, fj].T)[:, 1]
    G.write_raster(paths.DATA_PROC / "flood_susceptibility_rf_v0.tif", prob, grid, -9999.0, "rf_flood_probability")
    plots.raster_map(prob, grid, sa_utm, "Flood susceptibility (RF v0, probability)", paths.OUT_FIG / "susceptibility_rf_v0.png",
                     -9999.0, "YlOrRd", "P(flood)", vmin=0, vmax=1)
    status.record("G", status.COMPLETED,
                  f"RF trained on {len(ys_)} samples. Spatial-CV F1={metrics['f1']:.3f}, AUC={metrics['roc_auc']:.3f} "
                  "(relative to proxy labels - see caveats in rf_metrics.json).",
                  files=["outputs/tables/rf_metrics.json", "outputs/tables/rf_feature_importance.csv",
                         "outputs/figures/rf_confusion_matrix.png", "outputs/figures/susceptibility_rf_v0.png",
                         "data/processed/flood_susceptibility_rf_v0.tif", "outputs/models/random_forest_v0.joblib"],
                  requirements=["Independent-event validation (train 2015+2021, test 2023).", "XGBoost + SHAP."],
                  extra=metrics, seconds=time.time() - t0)


if __name__ == "__main__":
    main()
