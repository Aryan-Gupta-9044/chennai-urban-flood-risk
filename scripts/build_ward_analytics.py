#!/usr/bin/env python
"""ML-EXP-1: evidence-aware ward-level exploratory analytics (read-only on all accepted products).

  .\\.venv\\Scripts\\python.exe scripts\\build_ward_analytics.py
  .\\.venv\\Scripts\\python.exe scripts\\build_ward_analytics.py --quick      (fewer permutations; for tests)

Writes ONLY to outputs/ml_exploratory_v1 (or --outdir). Produces no flood label, no flood probability and no
accuracy metric against proxy labels. See outputs/ml_exploratory_v1/ML_EXP1_REPORT.md.
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

from analytics import VERSION, explore, presence_only, ward_features  # noqa: E402

PROTECTED = ["outputs/susceptibility_v1", "outputs/susceptibility_review_v1", "outputs/s1_water_candidates_review_v1", "outputs/s1_water_candidates_review_v2",
             "outputs/s1_2021_persistence_v1_2", "outputs/chirps_2021", "outputs/dep2_local_run_01", "outputs/dep2_reference_exposure_vulnerability_2026",
             "outputs/tables", "outputs/reports", "outputs/figures", "data"]


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


def figures(out, t, wards, ids, Z, scores, ev, load, scan, k_sel, labels, pb, imp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    F = out / "figures"
    F.mkdir(parents=True, exist_ok=True)
    pal = plt.get_cmap("tab10")
    # PCA scatter coloured by cluster, presence markers
    d = t.set_index("ward_no").loc[ids]
    fig, ax = plt.subplots(figsize=(6.4, 5.0), dpi=200)
    for c in sorted(set(labels)):
        m = labels == c
        ax.scatter(scores.PC1[m], scores.PC2[m], s=22, color=pal(c), label=f"cluster {c} (n={m.sum()})", alpha=0.85, edgecolor="none")
    rep = d.reported_2021.notna().values
    ax.scatter(scores.PC1[rep], scores.PC2[rep], s=50, facecolor="none", edgecolor="black", linewidth=0.6, label="ward with >= 1 CDMP 2021 report (E3)")
    for f in load.sort_values("PC1", key=abs, ascending=False).feature.head(6):
        r = load.set_index("feature").loc[f]
        ax.annotate("", xy=(r.PC1 * 4, r.PC2 * 4), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="#555", lw=0.8))
        ax.text(r.PC1 * 4.3, r.PC2 * 4.3, f, fontsize=6, color="#333")
    ax.set_xlabel(f"PC1 ({ev.explained_variance_ratio[0]*100:.1f}% var.)")
    ax.set_ylabel(f"PC2 ({ev.explained_variance_ratio[1]*100:.1f}% var.)")
    ax.legend(fontsize=6, loc="best")
    ax.set_title("Ward indicator space (PCA of standardised indicators)", fontsize=9)
    fig.tight_layout(); fig.savefig(F / "fig_pca_clusters.png"); plt.close(fig)
    # cluster scan
    fig, ax = plt.subplots(figsize=(5.2, 3.2), dpi=200)
    ax.plot(scan.k, scan.silhouette, "o-", label="silhouette")
    ax.plot(scan.k, scan.bootstrap_ari_mean, "s--", label="bootstrap stability (ARI)")
    ax.axvline(k_sel, color="grey", lw=0.8, ls=":")
    ax.set_xlabel("k (k-means)"); ax.set_ylim(0, 1); ax.legend(fontsize=7); ax.set_title(f"Cluster number selection (selected k={k_sel})", fontsize=9)
    fig.tight_layout(); fig.savefig(F / "fig_cluster_scan.png"); plt.close(fig)
    # cluster map
    g = wards.merge(pd.DataFrame({"ward_no": ids, "cluster": labels}), on="ward_no", how="left")
    fig, ax = plt.subplots(figsize=(4.6, 7.0), dpi=200)
    g[g.cluster.isna()].plot(ax=ax, color="#d9d9d9", hatch="///", edgecolor="#999", linewidth=0.3)
    for c in sorted(set(labels)):
        g[g.cluster == c].plot(ax=ax, color=pal(c), edgecolor="white", linewidth=0.3)
    ax.set_axis_off(); ax.set_title("Exploratory ward clusters (indicator profiles)\ngrey = incomplete data (not assessed)", fontsize=8)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=pal(c), label=f"cluster {c}") for c in sorted(set(labels))] + [Patch(facecolor="#d9d9d9", hatch="///", label="not assessed")], fontsize=6, loc="lower left")
    x0, y0, x1, y1 = g.total_bounds
    ax.plot([x1 - 6000, x1 - 1000], [y0 + 1500, y0 + 1500], color="black", lw=2.5, solid_capstyle="butt")
    ax.text(x1 - 3500, y0 + 2000, "5 km", fontsize=6, ha="center")
    ax.annotate("N", xy=(0.92, 0.97), xytext=(0.92, 0.90), xycoords="axes fraction", ha="center", fontsize=8, arrowprops=dict(arrowstyle="-|>"))
    ax.text(0, -0.02, "EPSG:32644 | wards: TNGIS | inputs: SUS-1 A, S1WC-2, DEP2 local run", transform=ax.transAxes, fontsize=5)
    fig.tight_layout(); fig.savefig(F / "fig_cluster_map.png"); plt.close(fig)
    # PB-AUC chart
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=200)
    lab = [f"{r.event} {r.feature_set.split(' ')[0]} {'LR' if r.model == 'logistic_l2' else 'RF'}" for r in pb.itertuples()]
    y = np.arange(len(pb))
    ax.barh(y, pb.pb_auc_oof, color=["#3182bd" if r.event == 2015 else "#e6550d" for r in pb.itertuples()], alpha=0.85)
    ax.errorbar(pb.null_mean, y, xerr=[np.zeros(len(pb)), pb.null_p95 - pb.null_mean], fmt="|", color="black", lw=0.8, capsize=2,
                label="permutation null: mean (|) to 95th percentile")
    ax.axvline(0.5, color="grey", lw=0.6, ls=":")
    ax.set_yticks(y); ax.set_yticklabels(lab, fontsize=5.5); ax.set_xlim(0.3, 0.9); ax.set_xlabel("presence-background AUC (out-of-fold, zone blocks + 500 m buffer)")
    ax.set_title("Reported (E3) vs unlabelled wards - NOT accuracy", fontsize=8.5); ax.legend(fontsize=6, loc="lower right")
    fig.tight_layout(); fig.savefig(F / "fig_presence_background_auc.png"); plt.close(fig)
    # importance
    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=200)
    feats = imp.groupby("feature").oof_perm_importance_mean.mean().sort_values().index.tolist()
    for i, (e, c) in enumerate(((2015, "#3182bd"), (2021, "#e6550d"))):
        s = imp[imp.event == e].set_index("feature").oof_perm_importance_mean.reindex(feats)   # aligned to one feature order
        ax.barh(np.arange(len(feats)) + i * 0.4, s.values, height=0.4, color=c, label=str(e))
    ax.set_yticks(np.arange(len(feats)) + 0.2); ax.set_yticklabels(feats, fontsize=6); ax.axvline(0, color="black", lw=0.5)
    ax.set_xlabel("drop in out-of-fold PB-AUC when permuted (logistic, F2)"); ax.legend(fontsize=7); ax.set_title("Association drivers (exploratory)", fontsize=9)
    fig.tight_layout(); fig.savefig(F / "fig_importance.png"); plt.close(fig)
    # three-dimension scatter
    fig, ax = plt.subplots(figsize=(5.8, 4.4), dpi=200)
    sc = ax.scatter(d.sus_a_mean_pct, d.exposure_index_provisional, c=d.vulnerability_index_provisional, s=12 + 4 * d.cdmp_records_2021.fillna(0), cmap="OrRd", edgecolor="#333", linewidth=0.2)
    fig.colorbar(sc, ax=ax, label="partial vulnerability index (exploratory)")
    ax.set_xlabel("SUS-1 mean percentile (relative susceptibility)"); ax.set_ylabel("provisional exposure index")
    ax.set_title("Susceptibility x exposure x vulnerability (marker size = CDMP 2021 records)", fontsize=8)
    fig.tight_layout(); fig.savefig(F / "fig_three_dimensions.png"); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default=str(ROOT / "outputs" / "ml_exploratory_v1"))
    ap.add_argument("--dep2-dir", default=str(ROOT / "outputs" / "dep2_local_run_01"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--figures-only", action="store_true", help="re-draw figures from the saved tables")
    a = ap.parse_args(argv)
    t0 = time.time()
    out = Path(a.outdir)
    guard(out)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    from dep2 import layers
    wards = layers.load_wards(layers.Sources(ROOT / "data/external/dep2_sources"))
    if a.figures_only:
        T = out / "tables"
        t = pd.read_csv(T / "ward_feature_matrix.csv")
        cl = pd.read_csv(T / "ward_clusters_and_pcs.csv")
        ev = pd.read_csv(T / "pca_explained_variance.csv")
        figures(out, t, wards, cl.ward_no.values, None, cl[["PC1", "PC2", "PC3"]], ev, pd.read_csv(T / "pca_loadings.csv"), pd.read_csv(T / "cluster_scan.csv"),
                int(json.loads((out / "ml_exp1_summary.json").read_text())["k_selected"]), cl.cluster.values, pd.read_csv(T / "presence_background_cv.csv"),
                pd.read_csv(T / "association_importance.csv"))
        lines = [f"{sha(p)}  {p.relative_to(out).as_posix()}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
        (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("figures redrawn")
        return 0
    dep2_dir = Path(a.dep2_dir)
    watched = [ROOT / ward_features.SUS1 / "susceptibility_percentile.tif", ROOT / ward_features.SUS1 / "domain_class.tif",
               ROOT / ward_features.REVIEW / "index_C_reduced_no_twi.tif", dep2_dir / "B_exposure/exposure_indicators_by_ward.csv"]
    h0 = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
    t, prov = ward_features.build(ROOT, wards, dep2_dir)
    T = out / "tables"
    t.to_csv(T / "ward_feature_matrix.csv", index=False, lineterminator="\n")
    pd.DataFrame(ward_features.FEATURE_SPEC, columns=["feature", "group", "use_in_models", "description"]).to_csv(T / "feature_dictionary.csv", index=False, lineterminator="\n")
    # unsupervised
    ids, Z, dropped = explore.prepare(t)
    ev, load, scores = explore.pca(Z)
    scan, k_sel, labels = explore.cluster_scan(Z, n_boot=20 if a.quick else 100)
    prof = explore.profiles(t, ids, labels, Z)
    sim = explore.similarity(ids, Z)
    ev.to_csv(T / "pca_explained_variance.csv", index=False, lineterminator="\n")
    load.to_csv(T / "pca_loadings.csv", index=False, lineterminator="\n")
    scan.to_csv(T / "cluster_scan.csv", index=False, lineterminator="\n")
    prof.to_csv(T / "cluster_profiles.csv", index=False, lineterminator="\n")
    sim.to_csv(T / "ward_similarity_top5.csv", index=False, lineterminator="\n")
    pd.DataFrame({"ward_no": ids, "cluster": labels, "PC1": scores.PC1, "PC2": scores.PC2, "PC3": scores.PC3}).to_csv(T / "ward_clusters_and_pcs.csv", index=False, lineterminator="\n")
    # spatial autocorrelation
    W = explore.contiguity(wards)
    tt = t.set_index("ward_no")
    mor = []
    for c in ["sus_a_mean_pct", "pop_density_cdmp", "vulnerability_index_provisional", "cdmp_records_2015", "cdmp_records_2021", "s1_class1_any_share"]:
        mor.append({"variable": c, **explore.morans_i(tt[c], W, n_perm=199 if a.quick else 999)})
    pd.DataFrame(mor).to_csv(T / "morans_i_contiguity.csv", index=False, lineterminator="\n")
    # presence-background
    pb, d, folds, oof = presence_only.evaluate(t, wards, n_perm={"logistic_l2": 20, "random_forest": 5} if a.quick else None)
    pb.to_csv(T / "presence_background_cv.csv", index=False, lineterminator="\n")
    pd.DataFrame([{"test_zone": z, "n_train": len(tr), "n_test": len(te), "buffer_removed_wards": nb} for z, tr, te, nb in folds]).to_csv(T / "spatial_folds.csv", index=False, lineterminator="\n")
    tr = presence_only.transfer(d)
    tr.to_csv(T / "presence_background_event_transfer.csv", index=False, lineterminator="\n")
    imp = pd.concat([presence_only.importance(d, e, presence_only.FEATURE_SETS["F2_all_indicators"], folds, n_repeats=5 if a.quick else 20) for e in (2015, 2021)])
    imp.to_csv(T / "association_importance.csv", index=False, lineterminator="\n")
    ca = presence_only.count_associations(d, presence_only.FEATURE_SETS["F3_all_indicators + area"], n_perm=199 if a.quick else 999)
    ca.to_csv(T / "report_intensity_spearman.csv", index=False, lineterminator="\n")
    rel = pd.DataFrame({"ward_no": d.ward_no})
    for e in (2015, 2021):
        rel[f"pb_relative_score_{e}_F2_LR_oof"] = oof[(e, "F2_all_indicators", "logistic_l2")]
        rel[f"reported_{e}"] = d[f"reported_{e}"].values
    rel["_meaning"] = "out-of-fold presence-background relative score; NOT a flood probability; ranks only within this analysis"
    rel.to_csv(T / "ward_pb_relative_scores_oof.csv", index=False, lineterminator="\n")
    figures(out, t, wards, ids, Z, scores, ev, load, scan, k_sel, labels, pb, imp)
    h1 = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
    summary = {"version": VERSION, "seconds": round(time.time() - t0, 1), "quick": a.quick, "n_wards": len(t), "n_wards_multivariate": int(len(ids)),
               "wards_dropped_missing": dropped, "k_selected": k_sel, "pca_cum_var_pc1_3": float(ev.cumulative.iloc[2]),
               "presence_background": pb.to_dict("records"), "inputs_unchanged": h0 == h1, "input_hashes": h0, "provenance": prov,
               "claims_not_made": ["flood probability", "flood prediction", "accuracy / precision / recall / F1 / IoU", "negative labels"]}
    (out / "ml_exp1_summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n", encoding="utf-8")
    lines = [f"{sha(p)}  {p.relative_to(out).as_posix()}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"ML-EXP-1 done in {summary['seconds']} s; k={k_sel}; inputs unchanged: {summary['inputs_unchanged']}; outputs: {out}")
    return 0 if summary["inputs_unchanged"] else 2


if __name__ == "__main__":
    sys.exit(main())
