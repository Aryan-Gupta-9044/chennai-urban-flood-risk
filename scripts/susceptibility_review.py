"""SUS-1 methodology review: redundancy schemes, hotspot-ranking comparison, exclusion/coverage audit, proxy diagnostics. EXPERIMENTAL, READ-ONLY on SUS-1.

Run (PowerShell, project root, after SUS-1 has produced outputs/susceptibility_v1):
    python scripts/susceptibility_review.py            # -> outputs/susceptibility_review_v1  (~3-4 min)
Exit codes: 0 ok | 2 stopped before writing | 3 an input / SUS-1 output changed during the run | 4 audit found an inconsistency (outputs are still written).
Never overwrites; writes only inside outputs/susceptibility_review_*; does not modify SUS-1, S1WC-1, CHIRPS, status.json. No network. Not validation."""
import argparse, hashlib, json, platform, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.flood_detection import susceptibility as su  # noqa: E402
from src.flood_detection import susceptibility_review as rv  # noqa: E402
from src.geospatial.grid import make_master_grid, inside_mask  # noqa: E402

NODATA = -9999.0
TAG = "EXPERIMENTAL REVIEW of exploratory susceptibility - uncalibrated, not validated; alternatives are not adopted baselines; not flood risk"
INDS = ["elevation_m", "slope_deg", "twi", "flow_accumulation", "dist_to_drainage_m", "hand_proxy_m", "fill_depth_m"]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def overlap(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or a in b.parents or b in a.parents


def stop(msgs):
    print("STOP (nothing written):")
    for m in msgs:
        print("  -", m)
    return 2


def read_all(path):
    import rasterio
    with rasterio.open(path) as d:
        return d.read(), d.nodata, {"shape": d.shape, "crs": str(d.crs), "transform": tuple(d.transform)[:6], "count": d.count, "descr": list(d.descriptions)}


def wr(path, arr, grid, nodata, desc, dtype):
    from src.geospatial.grid import write_raster
    write_raster(path, arr, grid, nodata, desc, dtype)


def run(root, cfg_path, out_override=None):
    root = Path(root).resolve()
    cp = Path(cfg_path); cp = cp if cp.is_absolute() else root / cp
    if not cp.is_file():
        return stop([f"config not found: {cp}"])
    cfg = json.loads(cp.read_text(encoding="utf-8"))
    out = Path(out_override) if out_override else root / cfg["output_dir"]
    out = out if out.is_absolute() else root / out
    s1 = root / cfg["sus1_dir"]
    problems = []
    if not out.name.startswith("susceptibility_review"):
        problems.append("output dir name must start with 'susceptibility_review'")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        problems.append(f"output dir exists and is not empty (never overwrite): {out}")
    for pre in cfg["protected_output_prefixes"]:
        if overlap(out, root / pre):
            problems.append(f"output dir overlaps protected location '{pre}'")
    need = {"scores": s1 / "rasters/feature_stack_scores.tif", "raw": s1 / "rasters/feature_stack_raw.tif", "domain": s1 / "rasters/domain_class.tif",
            "index": s1 / "rasters/susceptibility_index.tif", "label": s1 / "rasters/hotspot_label.tif", "quintile": s1 / "rasters/susceptibility_relative_class_quintile.tif",
            "hotspots_csv": s1 / "tables/hotspot_ranking.csv", "sens_csv": s1 / "tables/sensitivity_scenarios.csv", "manifest": s1 / "reports/susceptibility_manifest.json",
            "sus1_config": root / cfg["sus1_config"], "settings": root / cfg["settings"], "aoi": root / cfg["aoi_geojson"], "review_config": cp}
    for k, v in cfg["raw_inputs"].items():
        need["raw_" + k] = root / v
    for k, p in need.items():
        if not p.is_file():
            problems.append(f"missing input: {k} -> {p}")
    if problems:
        return stop(problems)
    # also hash EVERY file in the SUS-1 output dir (it must be unchanged by this run)
    s1_files = {str(p.relative_to(root)).replace("\\", "/"): p for p in sorted(s1.rglob("*")) if p.is_file()}
    h0 = {k: sha(p) for k, p in need.items()}
    h0_s1 = {k: sha(p) for k, p in s1_files.items()}
    sus_cfg = json.loads(need["sus1_config"].read_text(encoding="utf-8"))
    P = sus_cfg["params"]
    base_min = P["hotspot_min_cells"]
    man1 = json.loads(need["manifest"].read_text(encoding="utf-8"))
    settings = json.loads(need["settings"].read_text(encoding="utf-8"))
    import geopandas as gpd
    aoi = gpd.read_file(need["aoi"])
    grid = make_master_grid(aoi.total_bounds, settings["grid_resolution_m"], settings["analysis_epsg"])
    inside = inside_mask(grid, aoi.geometry)
    res = grid.res
    cell_ha = res * res / 1e4
    # ---- load SUS-1 rasters; alignment
    sc, sc_nd, sc_i = read_all(need["scores"]); rw, rw_nd, rw_i = read_all(need["raw"]); dm, _, dm_i = read_all(need["domain"])
    ix, ix_nd, ix_i = read_all(need["index"]); lb, _, lb_i = read_all(need["label"]); qu, _, qu_i = read_all(need["quintile"])
    infos = {"scores": sc_i, "raw": rw_i, "domain": dm_i, "index": ix_i, "label": lb_i, "quintile": qu_i}
    for k, i in infos.items():
        i2 = dict(i); i2["count"] = 1
        pr = su.alignment_problems(i2, grid)
        if pr:
            problems.append(f"SUS-1 output {k}: " + "; ".join(pr))
    if sc_i["count"] != len(INDS) or sc_i["descr"] != [f"score_{k}" for k in INDS]:
        problems.append(f"score band order unexpected: {sc_i['descr']}")
    if problems:
        return stop(problems)
    out.mkdir(parents=True, exist_ok=True)
    for d in ("rasters", "tables", "vectors", "figures", "reports"):
        (out / d).mkdir(exist_ok=True)
    dom = dm[0]; label = lb[0].astype(int)
    scored = dom == su.DOM_SCORED
    audit = []

    def chk(name, ok, detail=""):
        audit.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        return ok

    # =============================================================================================================== TASK 3: exclusion / coverage audit
    scores = {k: sc[i].astype("float64") for i, k in enumerate(INDS)}
    raw = {k: rw[i].astype("float64") for i, k in enumerate(INDS)}
    for d_ in (scores, raw):
        for k in d_:
            d_[k][d_[k] == NODATA] = np.nan
    n_in = int(inside.sum())
    chk("AOI mask: domain != 255 exactly equals AOI polygon mask recomputed on the master grid", np.array_equal(dom != 255, inside), f"AOI cells {n_in}")
    chk("domain classes cover every AOI cell exactly once (1/2/3)", int(np.isin(dom[inside], [1, 2, 3]).all()), f"scored {int(scored.sum())}, excluded-water {int((dom == 2).sum())}, missing {int((dom == 3).sum())}")
    chk("scored count equals manifest", int(scored.sum()) == man1["domain"]["scored_cells"] and int((dom == 2).sum()) == man1["domain"]["water_signature_cells"], f"{int(scored.sum())} / {int((dom == 2).sum())}")
    chk("scored cells: all 7 normalised scores finite and within [0,1]", all(np.isfinite(scores[k][scored]).all() and (scores[k][scored] >= 0).all() and (scores[k][scored] <= 1).all() for k in INDS))
    chk("scored cells: all 7 raw indicators finite", all(np.isfinite(raw[k][scored]).all() for k in INDS))
    chk("scored cells: index finite and within [0,1]", bool(np.isfinite(ix[0][scored]).all() and (ix[0][scored] != ix_nd).all() and (ix[0][scored] >= 0).all() and (ix[0][scored] <= 1).all()))
    nsc = ~scored
    chk("non-scored cells (excluded + outside): index is NoData (-9999), never 0 or a score", bool((ix[0][nsc] == ix_nd).all()))
    chk("non-scored cells: all 7 score bands are NoData", all((sc[i][nsc] == sc_nd).all() for i in range(len(INDS))))
    chk("excluded water-signature cells carry no hotspot label", int((label[dom == 2] > 0).sum()) == 0)
    chk("quintile raster: scored cells 1-5, excluded cells 0 (distinct from class 1), outside 255",
        bool(np.isin(qu[0][scored], [1, 2, 3, 4, 5]).all() and (qu[0][dom == 2] == 0).all() and (qu[0][dom == 3] == 0).all() and (qu[0][dom == 255] == 255).all()))
    # independent recomputation of the signature from the raw DEM
    import rasterio
    with rasterio.open(root / cfg["raw_inputs"]["dem_elevation_m"]) as d:
        dem = d.read(1).astype("float64")
        dem_info = {"shape": d.shape, "crs": str(d.crs), "transform": tuple(d.transform)[:6], "count": d.count}
    chk("raw DEM is on the master grid", su.alignment_problems(dem_info, grid) == [])
    sig, nz, npl = su.plateau_signature(dem, inside, P["min_plateau_cells"], NODATA)
    chk("excluded cells (class 2) are exactly the independently recomputed DEM signature", np.array_equal(sig, dom == 2), f"recomputed {int(sig.sum())} (DEM==0 {nz}, plateau-only {npl})")
    chk("excluded cells have raw indicators present in the stack (derived for diagnostics) but are not scored", bool(np.isfinite(raw["elevation_m"][dom == 2]).all()))
    chk("hotspot raster 0 is ambiguous (none / excluded / outside): disclosed, resolved by domain_class", True,
        f"hotspot_label==0 cells: scored non-hotspot {int(((label == 0) & scored).sum())}, excluded {int(((label == 0) & (dom == 2)).sum())}, outside {int(((label == 0) & (dom == 255)).sum())}. Never read 0 as 'not flood-prone'.")
    # excluded-cell descriptive (what the exclusion hides)
    ex_rows = []
    for k in INDS:
        for nm, m in (("scored", scored), ("excluded_water_signature", dom == 2)):
            v = raw[k][m]
            ex_rows.append({"indicator": k, "group": nm, "n": int(m.sum()), "median": float(np.nanmedian(v)), "p05": float(np.nanpercentile(v, 5)), "p95": float(np.nanpercentile(v, 95))})
    pd.DataFrame(ex_rows).to_csv(out / "tables/excluded_vs_scored_indicator_summary.csv", index=False)
    # adjacency: do the exclusions sit inside/next to the susceptible areas?
    from scipy import ndimage as ndi
    near = ndi.binary_dilation(dom == 2, structure=np.ones((3, 3), bool), iterations=3) & scored
    top0 = (label > 0)
    base_top = su.top_mask(np.where(scored, ix[0].astype("float64"), np.nan), scored, P["hotspot_quantile"])
    adj = {"scored_cells_within_3_cells_of_exclusion": int(near.sum()), "top_decile_share_near_exclusion": float(base_top[near].mean()) if near.any() else float("nan"),
           "top_decile_share_elsewhere": float(base_top[scored & ~near].mean())}
    pd.DataFrame([adj]).to_csv(out / "tables/exclusion_adjacency.csv", index=False)

    # =============================================================================================================== reproduce SUS-1 index + scenarios (consistency)
    S = {k: scores[k][scored] for k in INDS}
    base_w = su.normalise_weights({k: d["weight"] for k, d in sus_cfg["indicators"].items()})
    B = su.weighted_index(S, base_w)
    maxdiff = float(np.abs(B - ix[0][scored].astype("float64")).max())
    chk("index recomputed from stored scores equals SUS-1 index raster (float32 storage tolerance)", maxdiff < 1e-5, f"max |diff| = {maxdiff:.2e}")
    thr_base = np.quantile(B, P["hotspot_quantile"])
    topv = B >= thr_base
    lab_vec_base = label[scored]
    n_dropped_cells = int((topv & (lab_vec_base == 0)).sum())
    chk("SUS-1 hotspot cells are a subset of the recomputed top decile", bool(((lab_vec_base > 0) <= topv).all()), f"top-decile cells {int(topv.sum())}; in kept hotspots {int((lab_vec_base > 0).sum())}; in dropped small components {n_dropped_cells}")
    # =============================================================================================================== TASK 1: redundancy
    names, R = rv.spearman_matrix(S)
    vif = rv.vif_from_corr(R)
    pd.DataFrame(R, index=names, columns=names).to_csv(out / "tables/t1_indicator_score_correlation.csv")
    twi_r2 = rv.rank_r2(S["twi"], [S["slope_deg"], S["flow_accumulation"]])
    twi_r2_alt = rv.rank_r2(raw["twi"][scored] if "twi" in raw else S["twi"], [raw["slope_deg"][scored], raw["flow_accumulation"][scored]])
    red = pd.DataFrame({"indicator": names, "VIF": vif}).assign(effective_n_independent_indicators=rv.effective_n(R), n_indicators=len(names))
    red.to_csv(out / "tables/t1_vif_and_effective_n.csv", index=False)
    pd.DataFrame([{"statement": "R2 of rank(TWI score) on ranks of slope & flow-accumulation scores", "R2": twi_r2},
                  {"statement": "R2 of rank(raw TWI) on ranks of raw slope & flow accumulation", "R2": twi_r2_alt}]).to_csv(out / "tables/t1_twi_dependence.csv", index=False)
    schemes = {}
    for nm, sp in cfg["schemes"].items():
        if sp["kind"] == "equal":
            w = {k: 1.0 / len(INDS) for k in INDS}
        elif sp["kind"] == "grouped":
            w = rv.group_weights(sp["groups"]); w = {k: w.get(k, 0.0) for k in INDS}
        else:
            ks = sp["indicators"]; w = {k: (1.0 / len(ks) if k in ks else 0.0) for k in INDS}
        schemes[nm] = su.normalise_weights(w)
    wrows, crows, vrows = [], [], []
    IDX = {}
    for nm, w in schemes.items():
        IDX[nm] = su.weighted_index(S, w)
        wrows.append({"scheme": nm, **{k: w[k] for k in INDS}, "note": cfg["schemes"][nm]["note"]})
        for r in rv.contribution_shares(S, w):
            crows.append({"scheme": nm, **r})
    pd.DataFrame(wrows).to_csv(out / "tables/t1_scheme_weights.csv", index=False)
    pd.DataFrame(crows).to_csv(out / "tables/t1_indicator_contribution_by_scheme.csv", index=False)
    q = P["hotspot_quantile"]
    cmp_rows = []
    TOP = {nm: v >= np.quantile(v, q) for nm, v in IDX.items()}
    for nm, v in IDX.items():
        rho, jac = su.compare_to_base(IDX["A_baseline_equal7"], v, np.ones(v.size, bool), q)
        cmp_rows.append({"scheme": nm, "mean": float(v.mean()), "sd": float(v.std()), "p05": float(np.percentile(v, 5)), "p50": float(np.median(v)), "p95": float(np.percentile(v, 95)),
                         "skew": float(((v - v.mean()) ** 3).mean() / v.std() ** 3), "spearman_vs_A": rho, "top_decile_jaccard_vs_A": jac})
    pd.DataFrame(cmp_rows).to_csv(out / "tables/t1_scheme_distribution_and_overlap.csv", index=False)
    # scheme rasters + agreement + percentile difference
    def to2d(v, fill=np.nan):
        a = np.full(grid.shape, fill); a[scored] = v; return a
    pctA = su.percentile_of(to2d(IDX["A_baseline_equal7"]), scored)
    PCT = {}
    for nm in schemes:
        if nm == "A_baseline_equal7":
            continue
        i2 = to2d(IDX[nm]); pct = su.percentile_of(i2, scored); PCT[nm] = pct
        tag = nm.split("_")[0]
        wr(out / f"rasters/index_{nm}.tif", np.where(np.isfinite(i2), i2, NODATA).astype("float32"), grid, NODATA, f"EXPERIMENTAL index scheme {nm}", "float32")
        wr(out / f"rasters/percentile_difference_{tag}_minus_A.tif", np.where(scored, pct - pctA, NODATA).astype("float32"), grid, NODATA, f"percentile points {nm} minus baseline", "float32")
        ag = rv.agreement_class(to2d(TOP["A_baseline_equal7"], 0).astype(bool), to2d(TOP[nm], 0).astype(bool), scored)
        wr(out / f"rasters/top_decile_agreement_{tag}_vs_A.tif", ag, grid, 255, "0 neither,1 baseline only,2 alternative only,3 both,255 not scored", "uint8")
    # hotspot changes: re-derive hotspots per scheme, compare with baseline hotspots
    hcfg = cfg["hotspot"]
    hs_rows, base_lab_n = [], int(label.max())
    base_means = rv.mean_by_label(B, lab_vec_base, base_lab_n)
    shift_tab = pd.DataFrame({"hotspot_id": np.arange(1, base_lab_n + 1), "n_cells": np.bincount(lab_vec_base, minlength=base_lab_n + 1)[1:], "mean_A": base_means})
    shift_tab["rank_A"] = rv.ranks_desc(base_means)
    for nm, v in IDX.items():
        m2 = to2d(TOP[nm], 0).astype(bool)
        lab2, n2, drop2 = su.label_hotspots(m2, base_min)
        cov = float(((lab2 > 0) & (label > 0)).sum() / max((label > 0).sum(), 1))
        hs_rows.append({"scheme": nm, "n_hotspots": n2, "dropped_small_components": drop2, "hotspot_cells": int((lab2 > 0).sum()), "hotspot_area_ha": float((lab2 > 0).sum() * cell_ha),
                        "frac_of_baseline_hotspot_cells_also_hotspot": cov, "frac_of_scheme_hotspot_cells_in_baseline_hotspot": float(((lab2 > 0) & (label > 0)).sum() / max((lab2 > 0).sum(), 1))})
        if nm != "A_baseline_equal7":
            mean_s = rv.mean_by_label(v, lab_vec_base, base_lab_n)
            shift_tab[f"mean_{nm.split('_')[0]}"] = mean_s
            shift_tab[f"rank_{nm.split('_')[0]}"] = rv.ranks_desc(mean_s)
            shift_tab[f"frac_cells_in_{nm.split('_')[0]}_top_decile"] = rv.mean_by_label(TOP[nm].astype(float), lab_vec_base, base_lab_n)
    pd.DataFrame(hs_rows).to_csv(out / "tables/t1_scheme_hotspot_comparison.csv", index=False)
    shift_tab.sort_values("rank_A").to_csv(out / "tables/t1_baseline_hotspots_under_schemes.csv", index=False)

    # =============================================================================================================== TASK 2: hotspot ranking
    # scenarios identical to SUS-1 (same functions, same seed)
    names7 = list(sus_cfg["indicators"])
    scen = {}
    for nm, w in su.scenario_weights(base_w, sus_cfg["scenarios"]).items():
        scen[nm] = (w, S)
    for nm, spec in sus_cfg["scenarios"].get("normalisation_alternatives", {}).items():
        S2 = {}
        for k, d in sus_cfg["indicators"].items():
            rawk = np.full(grid.shape, np.nan); rawk[scored] = raw[k][scored]
            s_, _ = su.normalise(rawk, scored, spec["method"], d["direction"], d["transform"], P["p_lo"], P["p_hi"]); S2[k] = s_[scored]
        scen[nm] = (base_w, S2)
    for j, w in enumerate(su.random_weights(names7, P["n_random_weight_scenarios"], P["random_seed"], P["dirichlet_concentration"])):
        scen[f"random_{j:03d}"] = (w, S)
    sus1_sens = pd.read_csv(need["sens_csv"]).set_index("scenario")
    # geometries: baseline (min cells sensitivity) + merged
    top2d = to2d(topv, 0).astype(bool)
    geoms = {}
    for mc in sorted(set(hcfg["min_cells_sensitivity"]) | {base_min}):
        l_, n_, d_ = su.label_hotspots(top2d, mc)
        geoms[f"base_min{mc}"] = (l_, n_)
    merged_by_it = {}
    for it in hcfg["merge_closing_iterations"]:
        mg = rv.merge_close(top2d, scored, it)
        lm_, nm__, _ = su.label_hotspots(mg, hcfg["merged_min_cells"])
        geoms[f"merged_close{it}_min{hcfg['merged_min_cells']}"] = (lm_, nm__)
        merged_by_it[it] = mg
    # fixed planning blocks (threshold-free geometry): n x n cells, kept if >= min fraction of its cells are scored
    rr, cc = np.indices(grid.shape)
    block_meta = {}
    for bc in sorted(set(hcfg["block_cells_sensitivity"]) | {hcfg["block_cells_primary"]}):
        bid = (rr // bc) * ((grid.width + bc - 1) // bc) + (cc // bc)
        nsc_blk = np.bincount(bid[scored], minlength=bid.max() + 1)
        keep_b = nsc_blk >= hcfg["block_min_scored_fraction"] * bc * bc
        remap = np.zeros(bid.max() + 1, int); remap[keep_b] = np.arange(1, keep_b.sum() + 1)
        geoms[f"block_{bc * int(res)}m"] = (np.where(scored, remap[bid], 0), int(keep_b.sum()))
        block_meta[bc] = keep_b
    bc = hcfg["block_cells_primary"]; keep_b = block_meta[bc]
    gv = {g: (l_[scored].astype(int), n_) for g, (l_, n_) in geoms.items()}
    acc = {g: {"mean": [], "excess": []} for g in gv}
    rho_check = []
    for nm, (w, SS) in scen.items():
        v = su.weighted_index(SS, w)
        thr = np.quantile(v, q)
        if nm in sus1_sens.index:
            r_, _ = su.compare_to_base(B, v, np.ones(v.size, bool), q); rho_check.append(abs(r_ - sus1_sens.loc[nm, "spearman_vs_base"]))
        for g, (lv, n_) in gv.items():
            acc[g]["mean"].append(rv.mean_by_label(v, lv, n_)); acc[g]["excess"].append(rv.excess_mass_by_label(v, lv, thr, n_, cell_ha))
    chk("scenario machinery reproduces SUS-1 sensitivity table (Spearman vs base, all scenarios)", max(rho_check) < 1e-4, f"max |diff| = {max(rho_check):.2e} over {len(rho_check)} scenarios")
    k_top = hcfg["top_k"]
    summ, topk_rows = [], []
    base_info = {}
    for g, (lv, n_) in gv.items():
        if n_ == 0:
            continue
        bm = rv.mean_by_label(B, lv, n_); be = rv.excess_mass_by_label(B, lv, thr_base, n_, cell_ha)
        ar = np.bincount(lv, minlength=n_ + 1)[1:] * cell_ha
        shp = rv.shape_metrics(geoms[g][0], res)
        cnt = np.bincount(lv, minlength=n_ + 1)[1:]
        base_info[g] = {"mean": bm, "excess": be, "area": ar, "shape": shp}
        for metric, base_vec, M in (("mean_index", bm, np.array(acc[g]["mean"])), ("excess_susceptibility_ha", be, np.array(acc[g]["excess"]))):
            st = rv.stability_summary(M, base_vec, k_top)
            summ.append({"geometry": g, "ranking": metric, "n_hotspots": n_, "top_cells_in_hotspots": int(cnt.sum()), "median_hotspot_area_ha": float(np.median(ar)),
                         "top10_mean_area_ha": float(np.mean(ar[rv.ranks_desc(base_vec) <= k_top])),
                         "top10_retention_across_511_scenarios": st["top_k_retention"], "median_rank_range_of_top10": st["median_rank_range_topk"],
                         "median_rank_range_top10_relative_to_n": st["median_rel_range_topk"], "mean_pearson_rank_vs_base": st["mean_rank_pearson_vs_base"]})
            base_info[g][metric + "_stab"] = st
        ar_rank = rv.ranks_desc(ar)
        summ.append({"geometry": g, "ranking": "area_only (scenario-independent control; says nothing about susceptibility)", "n_hotspots": n_, "top_cells_in_hotspots": int(cnt.sum()),
                     "median_hotspot_area_ha": float(np.median(ar)), "top10_mean_area_ha": float(ar[ar_rank <= k_top].mean()), "top10_retention_across_511_scenarios": 1.0,
                     "median_rank_range_of_top10": 0.0, "median_rank_range_top10_relative_to_n": 0.0, "mean_pearson_rank_vs_base": 1.0})
    pd.DataFrame(summ).to_csv(out / "tables/t2_ranking_stability_summary.csv", index=False)
    # per-hotspot tables for the baseline geometry (min 25) and the merged geometry
    gname_base = f"base_min{base_min}"; gname_merged = f"merged_close{hcfg['merge_closing_iterations'][0]}_min{hcfg['merged_min_cells']}"; gname_block = f"block_{bc * int(res)}m"; lm = geoms[gname_merged][0]
    hs_all = {}
    for g in (gname_base, gname_merged, gname_block):
        lv, n_ = gv[g]; bi = base_info[g]; shp = bi["shape"]
        sm, se = bi["mean_index_stab"], bi["excess_susceptibility_ha_stab"]
        df = pd.DataFrame({"hotspot_id": np.arange(1, n_ + 1), "n_cells": np.bincount(lv, minlength=n_ + 1)[1:], "area_ha": bi["area"], "mean_index": bi["mean"], "excess_susceptibility_ha": bi["excess"],
                           "rank_mean_index": sm["base_rank"], "rank_excess": se["base_rank"], "rank_area": rv.ranks_desc(bi["area"]),
                           "mean_rank_range_min": sm["rank_min"], "mean_rank_range_max": sm["rank_max"], "excess_rank_range_min": se["rank_min"], "excess_rank_range_max": se["rank_max"],
                           "compactness": [shp[i]["compactness"] for i in range(1, n_ + 1)], "bbox_fill_ratio": [shp[i]["bbox_fill_ratio"] for i in range(1, n_ + 1)],
                           "perimeter_m": [shp[i]["perimeter_m"] for i in range(1, n_ + 1)]})
        # dominant-indicator diagnostic
        for k in INDS:
            df[f"score_{k}"] = rv.mean_by_label(S[k], lv, n_)
        df["max_single_indicator_share_of_index"] = np.max([base_w[k] * df[f"score_{k}"].values for k in INDS], axis=0) / df["mean_index"].values
        # signal-to-noise for mean ranking: scenario SD of the hotspot mean vs gap to the next-ranked hotspot
        M = np.array(acc[g]["mean"]); df["scenario_sd_of_mean_index"] = M.std(0)
        srt = df.sort_values("rank_mean_index"); gaps = srt["mean_index"].diff(-1).abs().values
        df.loc[srt.index, "gap_to_next_ranked_mean_index"] = gaps
        hs_all[g] = df
        df.sort_values("rank_excess").to_csv(out / f"tables/t2_units_{'baseline_geometry' if g == gname_base else ('merged_geometry' if g == gname_merged else 'block_geometry')}_all_rankings.csv", index=False)
    # why #1 ranged 1..64: scenario that drives it
    h1 = hs_all[gname_base].sort_values("rank_mean_index").iloc[0]
    M = np.array(acc[gname_base]["mean"]); hid = int(h1.hotspot_id) - 1
    rk = np.vstack([rv.ranks_desc(r) for r in M])[:, hid]
    sn = list(scen)
    worst = np.argsort(-rk)[:8]
    pd.DataFrame([{"scenario": sn[i], "rank_of_baseline_top_hotspot": int(rk[i])} for i in worst]).to_csv(out / "tables/t2_worst_scenarios_for_baseline_top_hotspot.csv", index=False)
    pd.DataFrame([{"hotspot_id": int(h1.hotspot_id), "n_cells": int(h1.n_cells), "area_ha": h1.area_ha, "mean_index": h1.mean_index, "gap_to_next_ranked": h1.gap_to_next_ranked_mean_index,
                   "scenario_sd_of_mean_index": h1.scenario_sd_of_mean_index, "rank_min": int(rk.min()), "rank_max": int(rk.max()), "rank_median": float(np.median(rk)),
                   "max_single_indicator_share_of_index": h1.max_single_indicator_share_of_index, **{f"score_{k}": h1[f"score_{k}"] for k in INDS}}]).to_csv(out / "tables/t2_baseline_top_hotspot_diagnosis.csv", index=False)
    # fragmentation of the whole top decile
    sizes = rv.component_sizes(top2d)
    fr = {"top_decile_cells": int(top2d.sum()), "n_components_8conn": int(sizes.size), f"n_components_ge{base_min}": int((sizes >= base_min).sum()), f"cells_in_components_ge{base_min}": int(sizes[sizes >= base_min].sum()),
          f"share_cells_in_ge{base_min}": float(sizes[sizes >= base_min].sum() / sizes.sum()), "median_component_cells": float(np.median(sizes)), "largest_component_cells": int(sizes.max()),
          **{f"closing{it}_n_components": int(rv.component_sizes(m_).size) for it, m_ in merged_by_it.items()}, **{f"closing{it}_largest_component_cells": int(rv.component_sizes(m_).max()) for it, m_ in merged_by_it.items()}, **{f"closing{it}_cells_added_not_in_top_decile": int((m_ & ~top2d).sum()) for it, m_ in merged_by_it.items()}}
    pd.DataFrame([fr]).to_csv(out / "tables/t2_fragmentation_of_top_decile.csv", index=False)
    wr(out / "rasters/hotspot_label_baseline_min25_copy.tif", np.where(inside, label, 0).astype("int32"), grid, 0, "SUS-1 baseline hotspot ids reproduced (0 = none/not scored/outside: ambiguous, see domain_class)", "int32")
    wr(out / "rasters/hotspot_label_merged.tif", np.where(inside, lm, 0).astype("int32"), grid, 0, "EXPERIMENTAL merged (closing) hotspot ids", "int32")
    # vectors: merged + baseline with all ranks
    from rasterio import features
    from shapely.geometry import shape
    for g, lab_arr, nme in ((gname_base, geoms[gname_base][0], "baseline_geometry"), (gname_merged, lm, "merged_geometry")):  # blocks: raster + csv only
        gs = [(int(v), shape(s)) for s, v in features.shapes(lab_arr.astype("int32"), mask=lab_arr > 0, transform=grid.transform)]
        gdf = gpd.GeoDataFrame(pd.DataFrame(gs, columns=["hotspot_id", "geometry"]), geometry="geometry", crs=grid.crs).dissolve(by="hotspot_id").reset_index().merge(hs_all[g], on="hotspot_id")
        gdf["status"] = "EXPERIMENTAL review ranking of EXPLORATORY susceptibility hotspots; not validated; not flood extent"
        gdf.to_file(out / f"vectors/review_hotspots_{nme}.gpkg", layer=f"review_hotspots_{nme}", driver="GPKG")

    lb_ = geoms[gname_block][0]; dfk = hs_all[gname_block]
    bm = np.full(grid.shape, NODATA, dtype="float32"); lut_b = np.zeros(int(lb_.max()) + 1, "float32"); lut_b[dfk.hotspot_id.values] = dfk.mean_index.values
    bm = np.where(lb_ > 0, lut_b[lb_], NODATA).astype("float32")
    wr(out / "rasters/block_mean_index.tif", bm, grid, NODATA, "EXPERIMENTAL planning-block mean index (300 m blocks)", "float32")
    wr(out / "rasters/block_label.tif", np.where(inside, lb_, 0).astype("int32"), grid, 0, "planning block id (0 = not kept/outside)", "int32")
    topb = dfk.sort_values("rank_mean_index").head(200)
    from shapely.geometry import box as _box
    ncb = (grid.width + bc - 1) // bc
    # block id -> original block index (inverse of remap)
    inv = np.where(keep_b)[0]
    geoms_b = []
    for hid in topb.hotspot_id.values:
        o = inv[hid - 1]; br, bcol = divmod(o, ncb)
        x0 = grid.transform.c + bcol * bc * res; y1 = grid.transform.f - br * bc * res
        geoms_b.append(_box(x0, y1 - bc * res, x0 + bc * res, y1))
    gpd.GeoDataFrame(topb.assign(status="EXPERIMENTAL planning block; top 200 by mean index; not validated"), geometry=geoms_b, crs=grid.crs).to_file(out / "vectors/review_top200_blocks.gpkg", layer="top200_blocks", driver="GPKG")
    # =============================================================================================================== TASK 4: proxy diagnostics
    with rasterio.open(root / cfg["raw_inputs"]["dem_conditioned_m"]) as d:
        zc = d.read(1).astype("float64"); zc[zc == NODATA] = np.nan
    with rasterio.open(root / cfg["raw_inputs"]["drainage_network"]) as d:
        dr = d.read(1)
    drain = inside & (dr == 1)
    dist_c, ir, ic = su.nearest_drainage(drain)
    signed = zc - zc[ir, ic]
    sgn = signed[scored]
    clipped = sgn < 0
    hand_rows = [{"statistic": "scored cells with negative signed height above nearest drainage (clipped to 0 in SUS-1)", "value": float(clipped.mean())},
                 {"statistic": "  median signed value of those cells (m)", "value": float(np.median(sgn[clipped])) if clipped.any() else np.nan},
                 {"statistic": "  p05 signed value (m)", "value": float(np.percentile(sgn[clipped], 5)) if clipped.any() else np.nan},
                 {"statistic": "  median distance to nearest drainage cell of clipped cells (m)", "value": float(np.median(dist_c[scored][clipped] * res))},
                 {"statistic": "  median distance of non-clipped cells (m)", "value": float(np.median(dist_c[scored][~clipped] * res))},
                 {"statistic": "  median elevation of clipped cells (m)", "value": float(np.median(zc[scored][clipped]))},
                 {"statistic": "  median elevation of non-clipped cells (m)", "value": float(np.median(zc[scored][~clipped]))}]
    pd.DataFrame(hand_rows).to_csv(out / "tables/t4_hand_proxy_clipping.csv", index=False)
    # alternatives for the HAND treatment: (b) signed values kept, (c) clipped cells treated as missing (index recomputed on the remaining cells only)
    d_h = sus_cfg["indicators"]["hand_proxy_m"]
    sgn2d = np.full(grid.shape, np.nan); sgn2d[scored] = sgn
    s_signed, i_signed = su.normalise(sgn2d, scored, "robust_minmax", d_h["direction"], d_h["transform"], P["p_lo"], P["p_hi"])
    S_b = dict(S); S_b["hand_proxy_m"] = s_signed[scored]
    Ib = su.weighted_index(S_b, base_w)
    keep = ~clipped
    Ic = Ib.copy()
    r_b, j_b = su.compare_to_base(B, Ib, np.ones(B.size, bool), q)
    Bk = B[keep]; Ibk = Ib[keep]
    r_c, j_c = su.compare_to_base(Bk, Ibk, np.ones(Bk.size, bool), q)
    wo = su.weighted_index(S, su.normalise_weights({**{k: 1.0 for k in INDS}, "hand_proxy_m": 0.0}))
    r_d, j_d = su.compare_to_base(B, wo, np.ones(B.size, bool), q)
    pd.DataFrame([{"variant": "HAND clipped to 0 (SUS-1 baseline)", "spearman_vs_A": 1.0, "top_decile_jaccard_vs_A": 1.0},
                  {"variant": "signed HAND kept (negative = cell below nearest drainage cell)", "spearman_vs_A": r_b, "top_decile_jaccard_vs_A": j_b},
                  {"variant": "signed HAND, evaluated only on the non-clipped cells", "spearman_vs_A": r_c, "top_decile_jaccard_vs_A": j_c},
                  {"variant": "HAND indicator removed (6 indicators)", "spearman_vs_A": r_d, "top_decile_jaccard_vs_A": j_d}]).to_csv(out / "tables/t4_hand_variants.csv", index=False)
    # fill depth
    fill = raw["fill_depth_m"][scored]
    pos = fill > 0
    fm = np.zeros(grid.shape, bool); fm[scored] = pos
    fs = rv.component_sizes(fm)
    fill_rows = [{"statistic": "share of scored cells with fill > 0", "value": float(pos.mean())},
                 {"statistic": "median fill among fill>0 (m)", "value": float(np.median(fill[pos]))},
                 {"statistic": "p95 fill among fill>0 (m)", "value": float(np.percentile(fill[pos], 95))},
                 {"statistic": "share of fill>0 cells at the 1 m fill cap (>=0.99 m)", "value": float((fill[pos] >= 0.99).mean())},
                 {"statistic": "connected fill>0 patches (8-conn): count", "value": float(fs.size)},
                 {"statistic": "  median patch size (cells)", "value": float(np.median(fs))},
                 {"statistic": "  share of patches <=4 cells (<=0.36 ha: pit-scale, plausibly DSM noise or micro-sinks)", "value": float((fs <= 4).mean())},
                 {"statistic": "  share of fill>0 cells in patches >= 25 cells", "value": float(fs[fs >= 25].sum() / fs.sum())},
                 {"statistic": "SUS-1 robust min-max upper clip (p98) for fill (m)", "value": float(pd.read_csv(s1 / "tables/indicator_transformations.csv").set_index("indicator").loc["fill_depth_m", "clip_hi_value"])}]
    pd.DataFrame(fill_rows).to_csv(out / "tables/t4_fill_depth_diagnostics.csv", index=False)
    # wetness: TWI clamp
    clamp = su.twi_clamp_mask(raw["slope_deg"], P["twi_min_slope_deg"]) if "slope_deg" in raw else None
    pd.DataFrame([{"statistic": "scored cells with TWI slope clamp (slope<0.1 deg)", "value": int((clamp & scored).sum())},
                  {"statistic": "share of scored", "value": float((clamp & scored).sum() / scored.sum())},
                  {"statistic": "mean TWI score of clamped cells", "value": float(np.nanmean(scores["twi"][clamp & scored])) if (clamp & scored).any() else float("nan")},
                  {"statistic": "share of clamped cells in top decile", "value": float(base_top[clamp & scored].mean() if (clamp & scored).any() else np.nan)}]).to_csv(out / "tables/t4_twi_clamp.csv", index=False)
    near1 = ndi.binary_dilation(drain, structure=np.ones((3, 3), bool)) & scored
    pd.DataFrame([{"statistic": "drainage cells (DEM-derived network) inside AOI", "value": int(drain.sum())},
                  {"statistic": "share of scored drainage cells that are in the top decile", "value": float(base_top[drain & scored].mean()) if (drain & scored).any() else np.nan},
                  {"statistic": "share of scored cells within 1 cell of drainage that are in the top decile", "value": float(base_top[near1].mean())},
                  {"statistic": "share of top-decile cells within 1 cell of drainage", "value": float(near1[base_top].mean())},
                  {"statistic": "share of top-decile cells with HAND-proxy == 0 (clipped or on drainage)", "value": float((raw["hand_proxy_m"][base_top] == 0).mean())}]).to_csv(out / "tables/t4_drainage_cells_in_index.csv", index=False)
    pd.DataFrame(audit).to_csv(out / "tables/t3_audit_checks.csv", index=False)

    # =============================================================================================================== figures
    _figures(out, grid, inside, scored, dom, IDX, PCT, pctA, TOP, to2d, label, geoms, gname_base, gname_merged, hs_all, summ, R, names, vif, crows, hand_rows, schemes)
    # =============================================================================================================== manifest
    h1_ = {k: sha(p) for k, p in need.items()}
    h1_s1 = {k: sha(p) for k, p in s1_files.items()}
    changed = [k for k in h0 if h0[k] != h1_[k]] + [k for k in h0_s1 if h0_s1[k] != h1_s1[k]]
    import rasterio as _r, scipy, geopandas
    out_hashes = {str(p.relative_to(out)).replace("\\", "/"): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    failed = [a for a in audit if a["result"] == "FAIL"]
    man = {"version": cfg["version"], "label": TAG, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "command": "python scripts/susceptibility_review.py",
           "config": cfg, "sus1_manifest_sha256": h0["manifest"], "inputs_sha256": h0, "sus1_output_files_sha256": h0_s1, "inputs_or_sus1_changed_during_run": changed,
           "audit_failed": failed, "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "rasterio": _r.__version__, "geopandas": geopandas.__version__},
           "output_sha256": out_hashes, "note": "output_sha256 excludes the manifest itself."}
    (out / "reports/susceptibility_review_manifest.json").write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")
    if changed:
        print("INPUT / SUS-1 OUTPUT CHANGED DURING RUN:", changed); return 3
    if failed:
        print("AUDIT FAILURES:", [a["check"] for a in failed]); return 4
    print(f"OK: review outputs in {out}")
    return 0


def _figures(out, grid, inside, scored, dom, IDX, PCT, pctA, TOP, to2d, label, geoms, gb, gm, hs_all, summ, R, names, vif, crows, hand_rows, schemes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    ext = grid.extent
    bg = np.where(inside, 0.88, np.nan)
    def base(a, t):
        a.imshow(bg, cmap="gray", vmin=0, vmax=1, extent=ext); a.set_title(t, fontsize=8); a.set_xticks([]); a.set_yticks([])
    # fig 1: schemes
    alts = list(PCT)
    fig, ax = plt.subplots(2, 4, figsize=(20, 13), dpi=90)
    base(ax[0, 0], "A baseline (7 equal): percentile"); ax[0, 0].imshow(pctA, cmap="viridis", extent=ext, vmin=0, vmax=100)
    for j, nm in enumerate(alts):
        base(ax[0, j + 1], f"{nm}: percentile"); ax[0, j + 1].imshow(PCT[nm], cmap="viridis", extent=ext, vmin=0, vmax=100)
        base(ax[1, j], f"{nm} minus A (percentile pts)"); i2 = ax[1, j].imshow(np.where(scored, PCT[nm] - pctA, np.nan), cmap="RdBu_r", extent=ext, vmin=-30, vmax=30)
        fig.colorbar(i2, ax=ax[1, j], shrink=0.5)
    cm = ListedColormap(["#dddddd", "#4477aa", "#ee6677", "#222222"])
    nm = "C_reduced_no_twi"
    ag = np.full(grid.shape, np.nan); ag[scored] = (TOP["A_baseline_equal7"].astype(int) + 2 * TOP[nm].astype(int))
    base(ax[1, 3], "Top decile: blue = A only, red = C only, black = both"); ax[1, 3].imshow(ag, cmap=cm, extent=ext, vmin=0, vmax=3, interpolation="nearest")
    fig.suptitle(TAG, color="firebrick", fontsize=10); fig.tight_layout(); fig.savefig(out / "figures/review_schemes_maps.png"); plt.close(fig)
    # fig 2: ranking comparison
    dfb, dfm = hs_all[gb], hs_all[gm]
    fig, ax = plt.subplots(2, 2, figsize=(15, 13), dpi=100)
    base(ax[0, 0], "Baseline hotspots: log10 excess susceptibility (ha); labels = top 10 by excess")
    ex = np.full(grid.shape, np.nan); lv = label
    m = dict(zip(dfb.hotspot_id, dfb.excess_susceptibility_ha))
    lut = np.full(int(label.max()) + 1, np.nan);
    for k, v in m.items(): lut[k] = np.log10(max(v, 1e-3))
    ex = np.where(label > 0, lut[label], np.nan); im = ax[0, 0].imshow(ex, cmap="plasma", extent=ext); fig.colorbar(im, ax=ax[0, 0], shrink=0.5)
    for _, r in dfb.sort_values("rank_excess").head(10).iterrows():
        yy, xx = np.nonzero(label == r.hotspot_id); ax[0, 0].text(ext[0] + xx.mean() * grid.res, ext[3] - yy.mean() * grid.res, str(int(r.rank_excess)), fontsize=8, weight="bold", color="w", ha="center")
    base(ax[0, 1], "EXPERIMENTAL merged hotspots (closing x1): rank by excess susceptibility (top 10 labelled)")
    lutm = np.full(int(geoms[gm][0].max()) + 1, np.nan)
    for k, v in zip(dfm.hotspot_id, dfm.excess_susceptibility_ha): lutm[k] = np.log10(max(v, 1e-3))
    lmm = geoms[gm][0]; im = ax[0, 1].imshow(np.where(lmm > 0, lutm[lmm], np.nan), cmap="plasma", extent=ext); fig.colorbar(im, ax=ax[0, 1], shrink=0.5)
    for _, r in dfm.sort_values("rank_excess").head(10).iterrows():
        yy, xx = np.nonzero(lmm == r.hotspot_id); ax[0, 1].text(ext[0] + xx.mean() * grid.res, ext[3] - yy.mean() * grid.res, str(int(r.rank_excess)), fontsize=8, weight="bold", color="w", ha="center")
    sd = pd.DataFrame(summ)
    s2 = sd[sd.ranking.isin(["mean_index", "excess_susceptibility_ha"])]
    for g, mk in zip(s2.geometry.unique(), "osd^vPXh*"):
        for rk, col in (("mean_index", "C0"), ("excess_susceptibility_ha", "C3")):
            r = s2[(s2.geometry == g) & (s2.ranking == rk)].iloc[0]
            ax[1, 0].scatter(r.median_rank_range_top10_relative_to_n, r.top10_retention_across_511_scenarios, c=col, marker=mk, s=70)
            ax[1, 0].annotate(g.replace("base_", "").replace("merged_close1_min25", "merged1").replace("merged_close2_min25", "merged2"), (r.median_rank_range_top10_relative_to_n, r.top10_retention_across_511_scenarios), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax[1, 0].set_xlabel("median rank range of baseline top-10, relative to number of hotspots (lower = steadier)"); ax[1, 0].set_ylabel("top-10 retention across 511 scenarios (higher = steadier)")
    ax[1, 0].set_title("Rank stability: blue = mean index, red = excess susceptibility", fontsize=8)
    ax[1, 1].scatter(dfb.area_ha, dfb.mean_index, s=10, c=dfb.compactness, cmap="viridis"); ax[1, 1].set_xscale("log"); ax[1, 1].set_xlabel("hotspot area (ha, log)"); ax[1, 1].set_ylabel("mean index")
    ax[1, 1].set_title("Mean index vs area (colour = compactness): small fragments span the highest means", fontsize=8)
    fig.suptitle(TAG, color="firebrick", fontsize=10); fig.tight_layout(); fig.savefig(out / "figures/review_hotspot_ranking.png"); plt.close(fig)
    # fig 3: redundancy
    cr = pd.DataFrame(crows)
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.5), dpi=100)
    im = ax[0].imshow(R, cmap="coolwarm", vmin=-1, vmax=1); ax[0].set_xticks(range(len(names))); ax[0].set_xticklabels(names, rotation=60, ha="right", fontsize=7); ax[0].set_yticks(range(len(names))); ax[0].set_yticklabels(names, fontsize=7)
    for i in range(len(names)):
        for j in range(len(names)): ax[0].text(j, i, f"{R[i, j]:.2f}", ha="center", va="center", fontsize=6)
    ax[0].set_title("Spearman correlation of indicator scores (scored cells)", fontsize=8)
    ax[1].barh(names, vif, color="C1"); ax[1].set_title("Variance-inflation factor (1 = independent; >2 notable)", fontsize=8); ax[1].tick_params(labelsize=7)
    piv = cr.pivot(index="indicator", columns="scheme", values="variance_share_of_index").loc[names]
    piv.plot.barh(ax=ax[2], width=0.8); ax[2].set_title("Share of index variation driven by each indicator", fontsize=8); ax[2].tick_params(labelsize=7); ax[2].legend(fontsize=7)
    fig.suptitle(TAG, color="firebrick", fontsize=9); fig.tight_layout(); fig.savefig(out / "figures/review_redundancy.png"); plt.close(fig)
    # fig 4: exclusion map
    fig, a = plt.subplots(figsize=(7, 10), dpi=100)
    cm2 = ListedColormap(["#ffffff", "#bbbbbb", "#d62728", "#ff7f0e"])
    d2 = np.where(dom == 255, 0, np.where(dom == 1, 1, np.where(dom == 2, 2, 3)))
    a.imshow(d2, cmap=cm2, extent=ext, vmin=0, vmax=3, interpolation="nearest"); a.set_xticks([]); a.set_yticks([])
    a.set_title("Domain: grey = scored, red = EXCLUDED (provisional DEM flattened-water signature)\nexcluded is NOT 'not flooded' - it is not assessed", fontsize=8)
    fig.suptitle(TAG, color="firebrick", fontsize=8); fig.tight_layout(); fig.savefig(out / "figures/review_exclusion_map.png"); plt.close(fig)
    # summary
    fig = plt.figure(figsize=(16, 11), dpi=100)
    g = fig.add_gridspec(2, 3)
    a = fig.add_subplot(g[0, 0]); base(a, "A baseline index percentile"); a.imshow(pctA, cmap="viridis", extent=ext, vmin=0, vmax=100)
    a = fig.add_subplot(g[0, 1]); base(a, "B2 grouped (2 groups) minus A (percentile points)"); a.imshow(np.where(scored, PCT["B2_grouped_2groups"] - pctA, np.nan), cmap="RdBu_r", extent=ext, vmin=-30, vmax=30)
    a = fig.add_subplot(g[0, 2]); a.imshow(d2, cmap=cm2, extent=ext, vmin=0, vmax=3, interpolation="nearest"); a.set_xticks([]); a.set_yticks([]); a.set_title("Excluded cells (red): not assessed", fontsize=8)
    a = fig.add_subplot(g[1, 0]); a.barh(names, vif, color="C1"); a.set_title("Redundancy: VIF per indicator", fontsize=8); a.tick_params(labelsize=7)
    a = fig.add_subplot(g[1, 1]); base(a, "Merged hotspots, log10 excess susceptibility (EXPERIMENTAL)"); a.imshow(np.where(lmm > 0, lutm[lmm], np.nan), cmap="plasma", extent=ext)
    a = fig.add_subplot(g[1, 2])
    for g_, mk in zip(s2.geometry.unique(), "osd^vPXh*"):
        for rk, col in (("mean_index", "C0"), ("excess_susceptibility_ha", "C3")):
            r = s2[(s2.geometry == g_) & (s2.ranking == rk)].iloc[0]; a.scatter(r.median_rank_range_top10_relative_to_n, r.top10_retention_across_511_scenarios, c=col, marker=mk, s=60)
    a.set_xlabel("rel. rank range of top-10", fontsize=7); a.set_ylabel("top-10 retention", fontsize=7); a.set_title("Ranking stability (blue mean index, red excess)", fontsize=8)
    fig.suptitle(TAG, color="firebrick", fontsize=10); fig.tight_layout(); fig.savefig(out / "figures/susceptibility_review_summary.png"); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/susceptibility_review.json")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    return run(a.root, a.config, a.out_dir)


if __name__ == "__main__":
    sys.exit(main())
