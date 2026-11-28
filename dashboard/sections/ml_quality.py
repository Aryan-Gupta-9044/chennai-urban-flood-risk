"""J. ML and exploratory analytics; K. Data quality, uncertainty and reproducibility."""
from __future__ import annotations

import hashlib

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from lib import maps, ui
from lib import registry as R
from lib.data import ward_table


def cluster_label(c: int, n: int) -> str:
    """Legend label from the cluster profile table: the two indicators with the largest |z|, never a risk word."""
    p = R.csv("mlx_profiles")
    short = {"z_sus_a_mean_pct": "SUS-1", "z_pop_density_cdmp": "pop. density", "z_med_elevation_m": "elevation", "z_road_surface_share": "road share",
             "z_facilities_per_km2": "facilities", "z_med_hand_proxy_m": "HAND proxy", "z_p90_log10_flow_acc": "flow acc.", "z_s1_class1_any_share": "S1 dark share",
             "z_dist_public_health_km": "dist. to health"}
    try:
        row = p[p.cluster == c].iloc[0]
        zs = sorted(((k, float(row[k])) for k in short if k in row), key=lambda kv: -abs(kv[1]))[:2]
        desc = ", ".join(f"{'higher' if v > 0 else 'lower'} {short[k]}" for k, v in zs)
        return f"cluster {c} ({n} wards): {desc}"
    except Exception:  # noqa: BLE001
        return f"cluster {c} ({n} wards)"


def render_ml():
    st.header("J. ML and exploratory analytics (ML-EXP-1)")
    ui.badges("EXPLORATORY", "PRESENCE_ONLY", "NOT VALIDATED")
    ui.note("The available labels are <b>E3 presences</b>: wards with at least one GCC-listed inundated location in a monsoon year. "
            "Unreported wards are <b>unlabelled</b>, not negative. So no supervised flood classifier is trained or scored here. ML-EXP-1 answers four narrower questions:\n"
            "<ol style='margin:0.3rem 0 0.3rem 1.2rem;padding:0'>"
            "<li>How are wards structured across the indicators (PCA, clusters with bootstrap stability)?</li>"
            "<li>Which wards are alike (feature-space neighbours)?</li>"
            "<li>Is there spatial dependence (Moran's I)?</li>"
            "<li>Do the indicators rank reported wards above unlabelled ones beyond chance?</li>"
            "</ol>"
            "The last uses presence-background AUC with zone-blocked, buffered cross-validation, a label-permutation null, an area-only control and cross-event transfer.")
    if not R.exists("mlx_summary"):
        ui.missing(R.rel("mlx_summary"))
        st.code(".\\.venv\\Scripts\\python.exe scripts\\build_ward_analytics.py")
        return
    s = R.js("mlx_summary", {})
    ui.kpis([("wards in multivariate analysis", s.get("n_wards_multivariate")), ("selected clusters (k)", s.get("k_selected")),
             ("PC1–3 cumulative variance", f"{s.get('pca_cum_var_pc1_3', 0)*100:.1f}%"), ("hash-guarded run inputs", ui.guard_text(s)[0].replace(" guarded inputs", "").replace(" guarded input", ""))])
    st.caption("Run integrity: " + ui.guard_text(s)[1])
    t1, t2, t3, t4, t5 = st.tabs(["Ward structure (PCA, clusters)", "Ward similarity", "Spatial dependence", "Presence-background analysis", "Contract and legacy RF"])
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            sc = R.csv("mlx_scan")
            if sc is not None:
                st.markdown("**Cluster number selection**: silhouette and bootstrap stability (ARI)")
                ui.table(sc.round(3), height=280)
        with c2:
            p = R.csv("mlx_profiles")
            if p is not None:
                st.markdown("**Cluster profiles** (z-scores; reported shares are descriptive, not flood rates)")
                ui.table(p.round(2).T.reset_index(), height=280)
        W = ward_table()
        if W is not None and "cluster" in W:
            st.markdown("**Ward map of the exploratory clusters.** Groups of wards with similar indicator profiles "
                        "(k-means on standardised indicators). They are *not* flood-severity or risk classes.")
            m = maps.base_map()
            pal = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]
            vc = W["cluster"].dropna().astype(int).value_counts().sort_index()
            classes = {int(c): (pal[i % len(pal)], cluster_label(int(c), int(n))) for i, (c, n) in enumerate(vc.items())}
            maps.ward_categorical(m, W, "cluster", "Exploratory indicator-profile cluster", classes, fields=["ward_no", "cluster", "PC1", "PC2"],
                                  aliases=["Ward", "Cluster", "PC1", "PC2"], nodata_label="excluded: incomplete indicators")
            maps.render(m, height=560)
            chk = maps.geometry_check(W, "ward_no", "cluster")
            miss = sorted(W.loc[W["cluster"].isna(), "ward_no"].astype(int).tolist())
            st.caption(f"Map data check: {chk['n_features']} ward polygons ({chk['crs']}), {chk['n_invalid']} invalid, {chk['n_empty']} empty, "
                       f"{chk['n_duplicate_keys']} duplicate ward IDs, extent {chk['bounds_wgs84']} "
                       f"({'inside' if chk['within_study_region'] else 'OUTSIDE'} the study region); clusters joined on ward_no for "
                       f"{chk['n_with_value']} wards; not clustered (incomplete indicators): {miss or 'none'}.")
        ld = R.csv("mlx_pca_load")
        if ld is not None:
            with st.expander("PCA loadings"):
                ui.table(ld[["feature", "PC1", "PC2", "PC3"]].round(3), height=330)
    with t2:
        sim = R.csv("mlx_similarity")
        f = R.csv("mlx_features")
        if sim is not None and f is not None:
            w = st.selectbox("Ward", sorted(sim.ward_no.unique()))
            nb = sim[sim.ward_no == w].merge(f, left_on="similar_ward_no", right_on="ward_no", suffixes=("", "_n"))
            cols = ["rank", "similar_ward_no", "feature_distance", "sus_a_mean_pct", "pop_density_cdmp", "slum_area_share", "cdmp_records_2021"]
            st.markdown(f"Five wards most similar to ward **{w}** in standardised indicator space. Reported counts are shown only for context.")
            ui.table(pd.concat([f[f.ward_no == w].assign(rank=0, similar_ward_no=w, feature_distance=0.0)[cols], nb[cols]]).round(3), height=260)
    with t3:
        mo = R.csv("mlx_moran")
        if mo is not None:
            ui.table(mo.round(3), height=260)
            st.caption("Strong positive spatial autocorrelation (contiguity weights) is why folds are whole zones with a 500 m buffer, not random wards.")
    with t4:
        pb = R.csv("mlx_pb")
        if pb is not None:
            pb = pb.assign(model_label=pb.feature_set + " · " + pb.model)
            ch = alt.Chart(pb).mark_bar().encode(
                y=alt.Y("model_label:N", sort=None, title=None), x=alt.X("pb_auc_oof:Q", title="presence-background AUC (out-of-fold)", scale=alt.Scale(domain=[0.2, 0.9])),
                color=alt.Color("event:N"), row=alt.Row("event:N"),
                tooltip=["event", "feature_set", "model", alt.Tooltip("pb_auc_oof", format=".3f"), alt.Tooltip("null_mean", format=".3f"),
                         alt.Tooltip("null_p95", format=".3f"), alt.Tooltip("p_perm_one_sided", format=".3f")]).properties(height=150)
            ui.chart(ch)
            ui.table(pb.drop(columns=["model_label"]).round(3), height=330)
            st.markdown("**Reading:** a value inside the permutation null (p ≥ 0.05) means the indicator set does not rank reported wards above unlabelled ones beyond chance. "
                        "Pooled out-of-fold AUC ranks scores from 15 separately trained zone models together; those scores are not on a common scale and zone prevalence differs, "
                        "so pooled values below 0.5 are expected and every value is compared with its own null. 16 combinations were tested and these p-values are "
                        "**not corrected** for multiple testing; see the review below. **These are not accuracy figures.**")
            _ml_review()
        tr = R.csv("mlx_transfer")
        if tr is not None:
            with st.expander("Cross-event transfer (2015 → 2021, 2021 → 2015)"):
                ui.table(tr.round(3), height=330)
        ci = R.csv("mlx_intensity")
        if ci is not None:
            with st.expander("Report intensity (records/km²) vs indicators: Spearman with naive permutation p (spatially optimistic)"):
                ui.table(ci.round(3), height=330)
        im = R.csv("mlx_importance")
        if im is not None:
            with st.expander("Association drivers: out-of-fold permutation importance (logistic, all indicators)"):
                ui.table(im.round(3), height=330)
        sc = R.csv("mlx_scores")
        if sc is not None:
            with st.expander("Ward relative scores (out-of-fold). NOT flood probabilities"):
                ui.table(sc.round(3), height=300)
    with t5:
        c = R.js("ml_contract", {})
        st.json({k: c.get(k) for k in ("status", "label_policy", "rows_with_independent_labels", "label_strength")})
        lk = R.csv("ml_leakage")
        if lk is not None:
            ui.table(lk, height=260)
        st.markdown("**Required before supervised flood ML can be evaluated:**")
        for x in c.get("required_before_supervised_ml", []):
            st.markdown(f"- {x}")
        st.subheader("Legacy RF v0")
        ui.badges("RETIRED")
        st.markdown("`scripts/train_random_forest.py` is preserved unchanged for traceability, but it is **retired**. Its problems:\n\n"
                    "- it trains on SAR proxy masks;\n"
                    "- slope is both a predictor and part of the proxy label;\n"
                    "- it pools events and draws random negatives;\n"
                    "- it uses no spatial buffer.\n\n"
                    "Its metrics would describe agreement with a proxy, not flood prediction. "
                    "The pipeline runner skips module G unless `CHENNAI_ALLOW_LEGACY_RF=1` is set. The dashboard never draws its raster as a prediction.")
        st.caption(f"Legacy raster present in this checkout: {R.exists('legacy_rf_raster')} (not displayed).")
    ui.cannot_claim("flood probability, predictive skill, accuracy, or that unreported wards are flood-free. The relative scores rank wards only within this analysis.")


def _verify_sums(path, root):
    bad, n = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        h, rel = line.split("  ", 1)
        p = root / rel
        n += 1
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            bad.append(rel)
    return n, bad


def render_quality():
    st.header("K. Data quality, uncertainty and reproducibility")
    st.markdown("Every view in this application reads a file listed here. A missing file is reported, never replaced.")
    t1, t2, t3, t4, t5 = st.tabs(["Pipeline status", "Datasets and provenance", "Missing files", "Checksums", "Reproduce"])
    with t1:
        st_ = R.js("status", {"modules": {}}).get("modules", {})
        if st_:
            ui.table(pd.DataFrame([{"module": k, "state": v.get("state"), "title": v.get("title"), "message": (v.get("message") or "")[:220]} for k, v in sorted(st_.items())]), height=420)
    with t2:
        p = R.csv("provenance")
        if p is not None:
            ui.table(p, height=360)
            ui.source(R.rel("provenance") + " (DEP2 documentation package; the local DEP2 run wrote no E_documentation files, same code)")
        a = R.js("acq_log", {})
        if a:
            st.markdown(f"Acquisition log: **{a.get('n_files')} files**, all hashes verified: **{a.get('all_hashes_verified')}** ({a.get('verified_utc')}).")
        li = R.csv("layer_inventory")
        if li is not None:
            with st.expander("Dashboard layer inventory (DEP2 handoff)"):
                ui.table(li, height=300)
    with t3:
        miss = R.missing_report()
        st.write(f"{len(miss)} registered files are missing in this checkout.")
        if miss:
            ui.table(pd.DataFrame(miss), height=260)
    with t4:
        for label, path, root in (("DEP2 local run", R.P["dep2_sums"], R.DEP2), ("ML-EXP-1", R.MLX / "SHA256SUMS.txt", R.MLX),
                                  ("ML-EXP-1.1 review", R.P["mlr_sums"], R.MLR), ("S1 temporal context", R.P["s1tc_sums"], R.S1TC)):
            if path.is_file() and st.button(f"Verify {label} checksums ({path.relative_to(R.ROOT).as_posix()})"):
                n, bad = _verify_sums(path, root)
                (st.success if not bad else st.error)(f"{n - len(bad)}/{n} files match" + (f"; mismatches: {bad[:10]}" if bad else ""))
        st.markdown("**Hash guards recorded by each analysis run** (counts come from the run records)")
        gl = []
        for label, key in (("ML-EXP-1", "mlx_summary"), ("ML-EXP-1.1 review", "mlr_summary"), ("S1 temporal context", "s1tc_summary")):
            rec = R.js(key, {})
            if rec:
                gl.append({"run": label, "guard": ui.guard_text(rec)[0], "files": ui.guard_text(rec)[1]})
        if gl:
            ui.table(pd.DataFrame(gl), height=150)
        st.markdown("**Map geometry checks** (ward polygons used by every ward map)")
        from lib.data import wards as _w
        Wg = _w()
        if Wg is not None:
            ui.table(pd.DataFrame([maps.geometry_check(Wg, "ward_no")]), height=80)
        u = R.js("sus1_overlay_unchanged", {})
        if u:
            st.markdown(f"SUS-1 rasters unchanged during the DEP2 overlay: **{u.get('unchanged')}**")
    with t5:
        st.code("""# from the repository root, Windows PowerShell
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt -r requirements-dep2.txt
.\\.venv\\Scripts\\python.exe scripts\\dep2_run.py all --config config\\dep2.local.json
.\\.venv\\Scripts\\python.exe scripts\\build_ward_analytics.py
.\\.venv\\Scripts\\python.exe -m pytest -q
.\\.venv\\Scripts\\streamlit.exe run dashboard\\app.py""", language="powershell")
        st.markdown("Full instructions: `docs/final/INTEGRATION_AND_RUN_GUIDE.md`.")


def _ml_review():
    """FINAL-02: ML-EXP-1.1 within-zone AUC, zone-stratified permutation null and multiplicity correction."""
    st.markdown("#### Review (ML-EXP-1.1): within-zone ranking, zone-stratified null, multiple testing")
    if not R.exists("mlr_stats"):
        ui.missing(R.rel("mlr_stats"))
        st.code(".\\.venv\\Scripts\\python.exe scripts\\build_ml_review.py")
        return
    m = R.csv("mlr_stats")
    s = R.js("mlr_summary", {})
    st.markdown("Within-zone AUC uses only presence–background pairs inside the same test zone, so every pair is ranked by one model. "
                "The zone-stratified null shuffles labels **within** zones (each zone keeps its report prevalence). "
                "Holm and Benjamini–Hochberg adjust across the 16 combinations.")
    cols = ["event", "feature_set", "model", "pooled_auc", "within_zone_auc", "zone_median_auc",
            "within_zone__zone_stratified__null_mean", "within_zone__zone_stratified__p", "within_zone__zone_stratified__p_holm",
            "within_zone__zone_stratified__p_bh", "pooled__global__p", "pooled__global__p_holm"]
    ui.table(m[[c for c in cols if c in m]].round(3), height=360)
    if R.exists("mlr_fig"):
        st.image(str(R.P["mlr_fig"]), width=760)
    verdict = "at least one" if s.get("any_within_zone_significant_holm_0.05") else "no"
    st.caption(f"After Holm correction, {verdict} combination ranks presences above background within zones at α = 0.05 "
               f"({s.get('n_perm', {})} permutations per null). " + ui.guard_text(s)[0] + ". Not accuracy; not calibration; background is unlabelled.")
