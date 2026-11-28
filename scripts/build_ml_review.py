#!/usr/bin/env python
"""ML-EXP-1.1: review statistics for the ML-EXP-1 presence-background test (read-only on all accepted products).

  .\\.venv\\Scripts\\python.exe scripts\\build_ml_review.py            (about 10-25 min on 2 cores)
  .\\.venv\\Scripts\\python.exe scripts\\build_ml_review.py --quick    (few permutations; smoke test)

Reads outputs/ml_exploratory_v1/tables/ward_feature_matrix.csv (hash-guarded) and the TNGIS wards; writes ONLY to
outputs/ml_review_v1_1 (or --outdir). Does not modify ML-EXP-1. See src/analytics/pb_review.py for the method.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analytics import pb_review  # noqa: E402

VERSION = "ML-EXP-1.1"
PROTECTED = ["outputs/ml_exploratory_v1", "outputs/ml_exploratory_v1_rerun", "outputs/susceptibility_v1", "outputs/susceptibility_review_v1",
             "outputs/s1_water_candidates_review_v2", "outputs/dep2_local_run_01", "outputs/dep2_reference_exposure_vulnerability_2026", "data"]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def guard(out: Path):
    o = out.resolve()
    for p in PROTECTED:
        q = (ROOT / p).resolve()
        if o == q or q in o.parents or o in q.parents:
            raise SystemExit(f"STOP: {o} overlaps protected {q}")


def figure(out, tab):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    (out / "figures").mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6), dpi=200, sharey=True)
    for ax, ev in zip(axes, (2015, 2021)):
        d = tab[tab.event == ev].reset_index(drop=True)
        lab = [f"{r.feature_set.split(' ')[0].split('_')[0]} {'LR' if r.model == 'logistic_l2' else 'RF'}" for r in d.itertuples()]
        y = np.arange(len(d))
        ax.errorbar(d["within_zone__zone_stratified__null_mean"], y + 0.15,
                    xerr=[np.zeros(len(d)), d["within_zone__zone_stratified__null_p95"] - d["within_zone__zone_stratified__null_mean"]],
                    fmt="|", color="#888", capsize=2, label="zone-stratified null (mean to 95th pct)")
        ax.scatter(d.within_zone_auc, y + 0.15, color="#0072B2", s=18, zorder=3, label="within-zone PB-AUC")
        ax.scatter(d.pooled_auc, y - 0.15, color="#E69F00", marker="s", s=14, zorder=3, label="pooled PB-AUC (ML-EXP-1)")
        ax.axvline(0.5, color="k", lw=0.6, ls=":")
        ax.set_yticks(y); ax.set_yticklabels(lab, fontsize=7); ax.set_xlim(0.2, 0.85); ax.set_title(f"{ev} ward presences (E3)", fontsize=9)
        ax.set_xlabel("presence-background AUC (not accuracy)", fontsize=8)
    h, lb = axes[0].get_legend_handles_labels()
    fig.legend(h, lb, loc="lower center", ncol=3, fontsize=7, frameon=False)
    fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(out / "figures/fig_within_zone_vs_pooled_auc.png"); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default=str(ROOT / "outputs" / "ml_review_v1_1"))
    ap.add_argument("--features", default=str(ROOT / "outputs/ml_exploratory_v1/tables/ward_feature_matrix.csv"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=-1)
    ap.add_argument("--figures-only", action="store_true", help="redraw the figure from the saved table")
    a = ap.parse_args(argv)
    t0 = time.time()
    out = Path(a.outdir)
    guard(out)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    if a.figures_only:
        figure(out, pd.read_csv(out / "tables/pb_review_statistics.csv"))
        lines = [f"{sha(p)}  {p.relative_to(out).as_posix()}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
        (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("figure redrawn")
        return 0
    from dep2 import layers
    wards = layers.load_wards(layers.Sources(ROOT / "data/external/dep2_sources"))
    watched = [Path(a.features), ROOT / "data/external/dep2_sources/reclaimchennai/raw/tngis/gcc_ward_boundary.geojson.gz"]
    watched = [p for p in watched if p.exists()]
    h0 = {p.resolve().relative_to(ROOT).as_posix(): sha(p) for p in watched}
    t = pd.read_csv(a.features)
    n_perm = {"logistic_l2": 10, "random_forest": 3} if a.quick else None
    tab, draws, folds = pb_review.review(t, wards, n_perm=n_perm, n_jobs=a.jobs)
    tab.to_csv(out / "tables/pb_review_statistics.csv", index=False, lineterminator="\n")
    draws.to_csv(out / "tables/pb_review_null_draws.csv", index=False, lineterminator="\n")
    figure(out, tab)
    h1 = {p.resolve().relative_to(ROOT).as_posix(): sha(p) for p in watched}
    key = ["event", "feature_set", "model", "pooled_auc", "within_zone_auc", "zone_median_auc",
           "within_zone__zone_stratified__p", "within_zone__zone_stratified__p_holm", "within_zone__zone_stratified__p_bh",
           "pooled__global__p", "pooled__global__p_holm"]
    summary = {"version": VERSION, "seconds": round(time.time() - t0, 1), "quick": a.quick, "n_combinations": int(len(tab)),
               "n_perm": n_perm or {"logistic_l2": 200, "random_forest": 40},
               "any_within_zone_significant_holm_0.05": bool((tab["within_zone__zone_stratified__p_holm"] < 0.05).any()),
               "any_pooled_significant_holm_0.05": bool((tab["pooled__global__p_holm"] < 0.05).any()),
               "results": tab[key].to_dict("records"), "inputs_unchanged": h0 == h1, "input_hashes": h0,
               "claims_not_made": ["flood probability", "flood prediction", "accuracy / precision / recall / F1 / IoU", "calibration", "negative labels"]}
    (out / "ml_review_summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n", encoding="utf-8")
    lines = [f"{sha(p)}  {p.relative_to(out).as_posix()}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{VERSION} done in {summary['seconds']} s; inputs unchanged: {summary['inputs_unchanged']}; outputs: {out}")
    return 0 if summary["inputs_unchanged"] else 2


if __name__ == "__main__":
    sys.exit(main())
