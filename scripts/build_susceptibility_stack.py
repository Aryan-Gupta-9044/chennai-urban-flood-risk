"""SUS-1: aligned feature stack + EXPLORATORY relative flood-susceptibility index, sensitivity and hotspots.

Run (Windows PowerShell, from the project root):
    python scripts/build_susceptibility_stack.py                       # full run -> outputs/susceptibility_v1
    python scripts/build_susceptibility_stack.py --stack-only          # feature stack + diagnostics only (no index)
Exit codes: 0 ok | 2 stopped BEFORE writing (bad input/config/output location) | 3 an input changed during the run.
Never overwrites (output dir must not exist or be empty), writes only inside the output dir, never touches status.json / S1WC-1 / CHIRPS / persistence /
reference outputs, no Earth Engine, no network. Not a validated flood prediction model; not a flood-risk assessment."""
import argparse, hashlib, json, platform, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.flood_detection import susceptibility as sus  # noqa: E402
from src.geospatial.grid import make_master_grid, inside_mask, Grid  # noqa: E402

NODATA = -9999.0
LABEL = "EXPLORATORY relative susceptibility - uncalibrated, not independently validated; not a flood prediction, not a flood extent, not flood risk"


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


def info_of(path):
    import rasterio
    with rasterio.open(path) as d:
        return {"shape": d.shape, "crs": str(d.crs), "transform": tuple(d.transform)[:6], "count": d.count, "dtype": d.dtypes[0], "nodata": d.nodata}


def read1(path):
    import rasterio
    with rasterio.open(path) as d:
        return d.read(1), d.nodata


def write_stack(path, bands, grid, descriptions, dtype="float32", nodata=NODATA):
    import rasterio
    with rasterio.open(path, "w", driver="GTiff", height=grid.height, width=grid.width, count=len(bands), dtype=dtype, crs=grid.crs,
                       transform=grid.transform, nodata=nodata, compress="deflate", tiled=True) as dst:
        for i, (b, d) in enumerate(zip(bands, descriptions), 1):
            a = np.where(np.isfinite(b), b, nodata).astype(dtype)
            dst.write(a, i)
            dst.set_band_description(i, d)


def write1(path, arr, grid, nodata, desc, dtype):
    from src.geospatial.grid import write_raster
    write_raster(path, arr, grid, nodata, desc, dtype)


def run(root, cfg_path, out_override=None, stack_only=False):
    root = Path(root).resolve()
    cfg_p = Path(cfg_path); cfg_p = cfg_p if cfg_p.is_absolute() else root / cfg_p
    if not cfg_p.is_file():
        return stop([f"config not found: {cfg_p}"])
    cfg_hash = sha(cfg_p)
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    P = cfg["params"]
    out = Path(out_override) if out_override else root / cfg["output_dir"]
    out = out if out.is_absolute() else root / out
    problems = []
    # ---- output location safeguards
    if not out.name.startswith("susceptibility_"):
        problems.append("output dir name must start with 'susceptibility_' (separate versioned directory)")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        problems.append(f"output dir exists and is not empty (never overwrite): {out}")
    for pre in cfg.get("protected_output_prefixes", []):
        if overlap(out, root / pre):
            problems.append(f"output dir overlaps protected location '{pre}'")
    # ---- input files
    files = {}
    for k, v in cfg["inputs"].items():
        files[k] = root / v
    for k, v in cfg["context_inputs"].items():
        files[k] = root / v
    aux = {"config": cfg_p, "settings": root / cfg["settings"], "antecedent_csv": root / cfg["antecedent_csv"]}
    for i, a in enumerate(cfg["aoi_geojsons"]):
        aux[f"aoi_{i}"] = root / a
    if (root / cfg["study_area_meta"]).is_file():
        aux["study_area_meta"] = root / cfg["study_area_meta"]
    for k, p in {**files, **aux}.items():
        if not p.is_file():
            problems.append(f"missing input: {k} -> {p}")
    for k, p in files.items():
        if overlap(out, p):
            problems.append(f"output dir overlaps input {k}")
    if problems:
        return stop(problems)
    # ---- HASH BEFORE PARSE
    hashes_before = {k: sha(p) for k, p in {**files, **aux}.items()}
    settings = json.loads(aux["settings"].read_text(encoding="utf-8"))
    import geopandas as gpd
    aoi_utm = gpd.read_file(aux["aoi_0"])
    grid = make_master_grid(aoi_utm.total_bounds, settings["grid_resolution_m"], settings["analysis_epsg"])
    inside = inside_mask(grid, aoi_utm.geometry)
    # ---- alignment: every raster must already be ON the master grid (no resampling) -- except native CHIRPS which is handled explicitly
    infos = {k: info_of(p) for k, p in files.items()}
    for k, i in infos.items():
        if k == "chirps_event_total_mm_native":
            continue
        pr = sus.alignment_problems(i, grid)
        if pr:
            problems.append(f"{k}: " + "; ".join(pr))
    if problems:
        return stop(problems + ["no silent resampling is performed; fix the input or the grid"])
    out.mkdir(parents=True, exist_ok=True)
    for d in ("rasters", "tables", "vectors", "figures", "reports"):
        (out / d).mkdir(exist_ok=True)

    # ---- read layers (NoData -> NaN, never 0)
    L = {}
    for k in cfg["inputs"]:
        a, nd = read1(files[k])
        L[k] = sus.to_float_nan(a, nd)
    drain_raw, dnd = read1(files["drainage_network"])
    drain_valid = inside & (drain_raw != dnd) & np.isin(drain_raw, [0, 1])
    drain = drain_valid & (drain_raw == 1)
    # ---- water-signature (provisional, DEM-artefact flag)
    dem_for_sig = np.where(np.isfinite(L["dem_elevation_m"]), L["dem_elevation_m"], NODATA)
    sig, n_zero, n_plat = sus.plateau_signature(dem_for_sig, inside, P["min_plateau_cells"], NODATA)
    # ---- derived indicators
    dist_c, ir, ic = sus.nearest_drainage(drain)
    dist_m = dist_c * grid.res
    hand, n_hand_clip = sus.hand_proxy(L["dem_conditioned_m"], ir, ic, dist_c)
    fill = L["dem_conditioned_m"] - L["dem_elevation_m"]
    n_fill_neg = int((np.isfinite(fill) & (fill < -1e-6)).sum())
    fill = np.where(np.isfinite(fill), np.maximum(fill, 0.0), np.nan)
    derived = {"dist_to_drainage_m": dist_m, "hand_proxy_m": hand, "fill_depth_m": fill}
    if not drain.any():
        derived["dist_to_drainage_m"] = np.full(grid.shape, np.nan)
        derived["hand_proxy_m"] = np.full(grid.shape, np.nan)
    raw = {}
    for name, d in cfg["indicators"].items():
        a = derived[name] if d["source"] == "derived" else L[d["source"]]
        raw[name] = np.where(inside, a, np.nan)
    twi_clamped = sus.twi_clamp_mask(L["slope_deg"], P["twi_min_slope_deg"]) & inside
    # ---- context layers
    ctx = {}
    for k in ("s1wc1_n_dark_dates", "s1wc1_n_valid_dates", "s1wc1_persistent_dark_mask", "s1wc1_transient_candidate_date_count"):
        a, nd = read1(files[k])
        ctx[k] = np.where(inside, sus.to_float_nan(a, nd), np.nan)
    chirps = _chirps_to_grid(files["chirps_event_total_mm_native"], grid)
    ctx["chirps_event_total_mm_context_only"] = np.where(inside, chirps, np.nan)

    # ---- domain
    active_ind = [k for k, d in cfg["indicators"].items() if d["weight"] > 0]
    allvalid = inside.copy()
    for k in active_ind:
        allvalid &= np.isfinite(raw[k])
    scored = allvalid & ~sig
    domain_cls = np.full(grid.shape, sus.DOM_OUTSIDE, dtype="uint8")
    domain_cls[inside] = sus.DOM_MISSING
    domain_cls[inside & sig] = sus.DOM_WATER_SIG
    domain_cls[scored] = sus.DOM_SCORED
    # a cell that is water-signature AND missing is reported as water-signature (signature needs a valid DEM, so overlap is impossible by construction)

    # ---- normalisation (reference population = scored domain)
    scores, ninfo = {}, {}
    for name, d in cfg["indicators"].items():
        scores[name], ninfo[name] = sus.normalise(raw[name], scored, d["method"], d["direction"], d["transform"], P["p_lo"], P["p_hi"])
    degenerate = [k for k, v in ninfo.items() if v["degenerate"]]

    # ---- layer statistics / coverage tables
    stat_rows = []
    for name, a in {**{k: L[k] for k in cfg["inputs"] if k != "drainage_network"}, **derived, **ctx}.items():
        r = sus.describe(np.where(inside, a, np.nan), inside, scored)
        r.update(layer=name, role=("index indicator input" if name in cfg["indicators"] or name in {c["source"] for c in cfg["indicators"].values()} else "context/derived"))
        stat_rows.append(r)
    r = sus.describe(np.where(drain_valid, drain_raw.astype(float), np.nan), inside, scored); r.update(layer="drainage_network (0/1)", role="index input (via distance/HAND)"); stat_rows.append(r)
    stats = pd.DataFrame(stat_rows)
    stats = stats[["layer", "role"] + [c for c in stats.columns if c not in ("layer", "role")]]
    stats.to_csv(out / "tables/layer_statistics_and_coverage.csv", index=False)
    dom_rows = [{"class_code": c, "class": sus.DOMAIN_NAMES[c], "n_cells": int((domain_cls == c).sum()),
                 "pct_of_aoi": float(100 * (domain_cls == c).sum() / inside.sum()) if c != sus.DOM_OUTSIDE else float("nan")} for c in (1, 2, 3, 255)]
    dom_rows += [{"class_code": "info", "class": "DEM==0 cells in signature", "n_cells": n_zero, "pct_of_aoi": 100 * n_zero / inside.sum()},
                 {"class_code": "info", "class": "constant-plateau-only cells in signature", "n_cells": n_plat, "pct_of_aoi": 100 * n_plat / inside.sum()},
                 {"class_code": "info", "class": "scored cells with TWI slope-clamp (slope<0.1 deg)", "n_cells": int((twi_clamped & scored).sum()),
                  "pct_of_aoi": 100 * (twi_clamped & scored).sum() / inside.sum()},
                 {"class_code": "info", "class": "HAND-proxy cells clipped from negative to 0 (AOI)", "n_cells": n_hand_clip, "pct_of_aoi": 100 * n_hand_clip / inside.sum()},
                 {"class_code": "info", "class": "fill-depth cells negative->0 (should be 0)", "n_cells": n_fill_neg, "pct_of_aoi": 100 * n_fill_neg / inside.sum()},
                 {"class_code": "info", "class": "drainage cells inside AOI", "n_cells": int(drain.sum()), "pct_of_aoi": 100 * drain.sum() / inside.sum()}]
    pd.DataFrame(dom_rows).to_csv(out / "tables/domain_summary.csv", index=False)
    trows = []
    for name, d in cfg["indicators"].items():
        i = ninfo[name]
        trows.append({"indicator": name, "source": d["source"], "transform": d["transform"], "normalisation": d["method"], "direction_more_susceptible": d["direction"],
                      "p_lo": i["p_lo"], "p_hi": i["p_hi"], "clip_lo_value": i["lo"], "clip_hi_value": i["hi"], "n_reference_cells": i["n_ref"],
                      "degenerate_no_spread": i["degenerate"], "default_weight": d["weight"], "rationale": d["rationale"], "status": "ASSUMPTION (not calibrated)"})
    pd.DataFrame(trows).to_csv(out / "tables/indicator_transformations.csv", index=False)

    # ---- feature stack rasters (always written)
    raw_names = list(cfg["indicators"]) + list(ctx)
    write_stack(out / "rasters/feature_stack_raw.tif", [raw[k] for k in cfg["indicators"]] + [ctx[k] for k in ctx], grid, raw_names)
    names_idx = list(cfg["indicators"])
    write1(out / "rasters/domain_class.tif", domain_cls, grid, 255, "domain: 1 scored, 2 water-signature excluded, 3 missing indicator, 255 outside AOI", "uint8")
    write1(out / "rasters/twi_slope_clamp_flag.tif", np.where(inside, twi_clamped.astype("uint8"), 255), grid, 255, "1 = TWI slope-clamped cell", "uint8")
    schema = [{"band": i + 1, "name": n, "file": "feature_stack_raw.tif", "kind": ("derived/observed-DEM indicator" if i < len(cfg["indicators"]) else "context only (not in index)"),
               "units": {"elevation_m": "m", "slope_deg": "deg", "twi": "-", "flow_accumulation": "cells", "dist_to_drainage_m": "m", "hand_proxy_m": "m",
                         "fill_depth_m": "m"}.get(n, "see docs"), "nodata": NODATA} for i, n in enumerate(raw_names)]
    pd.DataFrame(schema).to_csv(out / "tables/feature_stack_schema.csv", index=False)
    outputs_note = "stack_only"
    result = {"degenerate": degenerate}
    if not stack_only and not degenerate and scored.sum() > 0:
        outputs_note = "full"
        write_stack(out / "rasters/feature_stack_scores.tif", [scores[k] for k in names_idx], grid, [f"score_{k}" for k in names_idx])
        result.update(_index_and_sensitivity(cfg, P, grid, inside, scored, raw, scores, ctx, ninfo, out))
    elif not stack_only:
        pd.DataFrame([{"reason": f"index NOT produced: degenerate indicators={degenerate}; scored_cells={int(scored.sum())}"}]).to_csv(out / "tables/index_not_produced.csv", index=False)

    # ---- manifest
    hashes_after = {k: sha(p) for k, p in {**files, **aux}.items()}
    changed = [k for k in hashes_before if hashes_before[k] != hashes_after[k]]
    ant = pd.read_csv(aux["antecedent_csv"]).to_dict(orient="records")
    import rasterio, scipy, geopandas, shapely
    out_hashes = {str(p.relative_to(out)).replace("\\", "/"): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = {"version": cfg["version"], "label": LABEL, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": outputs_note,
                "command": "python scripts/build_susceptibility_stack.py" + (" --stack-only" if stack_only else ""),
                "config_sha256": cfg_hash, "params": P, "indicators": cfg["indicators"], "scenarios": cfg["scenarios"],
                "grid": {"crs": grid.crs, "resolution_m": grid.res, "shape_hw": list(grid.shape), "transform": list(grid.transform)[:6], "bounds_lbrt": list(grid.bounds),
                         "aoi_cells": int(inside.sum()), "aoi_note": "PROVISIONAL OSM boundary, not the official GCC boundary"},
                "domain": {"scored_cells": int(scored.sum()), "water_signature_cells": int((domain_cls == 2).sum()), "missing_indicator_cells": int((domain_cls == 3).sum())},
                "inputs": {k: {"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": hashes_before[k]} for k, p in {**files, **aux}.items()},
                "inputs_changed_during_run": changed, "antecedent_rainfall_context_only": ant, "s1wc1_caveats": cfg["s1wc1_caveats"],
                "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                             "rasterio": rasterio.__version__, "geopandas": geopandas.__version__, "shapely": shapely.__version__},
                "results": {k: v for k, v in result.items() if k in ("degenerate", "summary")}, "output_sha256": out_hashes,
                "note": "output_sha256 lists every file in the output dir at the time the manifest was built (the manifest itself is excluded)."}
    (out / "reports/susceptibility_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    if changed:
        print("INPUT CHANGED DURING RUN:", changed)
        return 3
    print(f"OK: {outputs_note} outputs in {out}")
    return 0


def _chirps_to_grid(path, grid):
    """Nearest-neighbour replication of the native 0.05 deg CHIRPS cells onto the 30 m grid (NO interpolation); NoData stays NoData. Context only."""
    import rasterio
    from rasterio.warp import reproject, Resampling
    dst = np.full(grid.shape, NODATA, dtype="float32")
    with rasterio.open(path) as s:
        reproject(rasterio.band(s, 1), dst, src_transform=s.transform, src_crs=s.crs, src_nodata=s.nodata, dst_transform=grid.transform,
                  dst_crs=grid.crs, dst_nodata=NODATA, resampling=Resampling.nearest)
    return sus.to_float_nan(dst, NODATA)


def _index_and_sensitivity(cfg, P, grid, inside, scored, raw, scores, ctx, ninfo, out):
    import geopandas as gpd
    from rasterio import features
    from shapely.geometry import shape
    names = list(cfg["indicators"])
    base_w = sus.normalise_weights({k: d["weight"] for k, d in cfg["indicators"].items()})
    idx = sus.weighted_index(scores, base_w)
    idx = np.where(scored, idx, np.nan)
    assert np.isfinite(idx[scored]).all()
    pct = sus.percentile_of(idx, scored)
    cls5 = sus.relative_classes(idx, scored, 5)
    write1(out / "rasters/susceptibility_index.tif", np.where(np.isfinite(idx), idx, NODATA).astype("float32"), grid, NODATA,
           "EXPLORATORY relative susceptibility index 0-1 (uncalibrated, not validated)", "float32")
    write1(out / "rasters/susceptibility_percentile.tif", np.where(np.isfinite(pct), pct, NODATA).astype("float32"), grid, NODATA, "percentile of index within scored domain", "float32")
    c5 = np.where(inside, cls5, 255).astype("uint8")
    write1(out / "rasters/susceptibility_relative_class_quintile.tif", c5, grid, 255, "relative quintile 1(lowest)-5; 0 = not scored; rank-based, NOT risk levels", "uint8")

    # ---- scenarios, evaluated on domain vectors (same scored cells, same base normalisation unless a normalisation alternative)
    zdom = np.ones(int(scored.sum()), bool)
    S = {k: scores[k][scored] for k in names}
    B = idx[scored]
    scen = {}
    sw = sus.scenario_weights(base_w, cfg["scenarios"])
    for nm, w in sw.items():
        scen[nm] = ("weights", w, S)
    for nm, spec in cfg["scenarios"].get("normalisation_alternatives", {}).items():
        S2 = {}
        for k, d in cfg["indicators"].items():
            sc, _ = sus.normalise(raw[k], scored, spec["method"], d["direction"], d["transform"], P["p_lo"], P["p_hi"])
            S2[k] = sc[scored]
        scen[nm] = ("normalisation", base_w, S2)
    named = list(scen)
    for j, w in enumerate(sus.random_weights(names, P["n_random_weight_scenarios"], P["random_seed"], P["dirichlet_concentration"])):
        scen[f"random_{j:03d}"] = ("random_weights", w, S)
    hs_mask = sus.top_mask(idx, scored, P["hotspot_quantile"])
    label, n_hs, n_small = sus.label_hotspots(hs_mask, P["hotspot_min_cells"])
    lab_vec = label[scored]
    srows, topcount = [], np.zeros(B.size)
    imin, imax = B.copy(), B.copy()
    means = {}
    q = P["hotspot_quantile"]
    topcount += (B >= np.quantile(B, q))
    for nm, (kind, w, SS) in scen.items():
        v = sus.weighted_index(SS, w)
        rho, jac = sus.compare_to_base(B, v, zdom, q)
        srows.append({"scenario": nm, "kind": kind, "spearman_vs_base": rho, "top_decile_jaccard_vs_base": jac,
                      **{f"w_{k}": float(sus.normalise_weights(w)[k]) for k in names}})
        topcount += (v >= np.quantile(v, q))
        imin = np.minimum(imin, v); imax = np.maximum(imax, v)
        if n_hs:
            cnt = np.bincount(lab_vec, weights=v, minlength=n_hs + 1); num = np.bincount(lab_vec, minlength=n_hs + 1)
            means[nm] = {k: float(cnt[k] / num[k]) for k in range(1, n_hs + 1)}
    n_all = len(scen) + 1
    topfreq = np.full(grid.shape, np.nan); topfreq[scored] = topcount / n_all
    rng_r = np.full(grid.shape, np.nan); rng_r[scored] = imax - imin
    write1(out / "rasters/top_decile_frequency.tif", np.where(np.isfinite(topfreq), topfreq, NODATA).astype("float32"), grid, NODATA,
           "fraction of weight/normalisation scenarios (incl. base) in which the cell is in the top decile", "float32")
    write1(out / "rasters/index_range_across_scenarios.tif", np.where(np.isfinite(rng_r), rng_r, NODATA).astype("float32"), grid, NODATA, "max-min index across scenarios", "float32")
    write1(out / "rasters/hotspot_label.tif", label.astype("int32"), grid, 0, "exploratory top-decile hotspot id (0 = none); id is NOT the rank", "int32")
    sdf = pd.DataFrame(srows)
    sdf.to_csv(out / "tables/sensitivity_scenarios.csv", index=False)
    wdf = pd.DataFrame([{"scenario": "base_equal", **{k: float(base_w[k]) for k in names}}] +
                       [{"scenario": r["scenario"], **{k: r[f"w_{k}"] for k in names}} for r in srows if not r["scenario"].startswith("random_")])
    wdf.to_csv(out / "tables/weights_scenarios.csv", index=False)
    summ = []
    for grp, sub in (("named (weights/drop-one/normalisation)", sdf[sdf.scenario.isin(named)]), ("random Dirichlet weights", sdf[sdf.scenario.str.startswith("random_")])):
        if len(sub):
            summ.append({"group": grp, "n": len(sub), "spearman_min": sub.spearman_vs_base.min(), "spearman_median": sub.spearman_vs_base.median(),
                         "jaccard_min": sub.top_decile_jaccard_vs_base.min(), "jaccard_median": sub.top_decile_jaccard_vs_base.median()})
    pd.DataFrame(summ).to_csv(out / "tables/sensitivity_summary.csv", index=False)
    # ---- hotspots
    rawk = {k: raw[k] for k in names}
    rows = sus.hotspot_table(label, idx, rawk, {k: scores[k] for k in names}, grid.res, topfreq, means) if n_hs else []
    hdf = pd.DataFrame(rows)
    # S1WC-1 descriptive context (NOT validation)
    if len(hdf):
        dark_frac = ctx["s1wc1_n_dark_dates"] / ctx["s1wc1_n_valid_dates"]
        for r in rows:
            m = label == r["hotspot_id"]
            r["ctx_s1wc1_mean_dark_date_fraction"] = float(np.nanmean(dark_frac[m]))
            r["ctx_s1wc1_persistent_dark_cell_fraction"] = float(np.nanmean(ctx["s1wc1_persistent_dark_mask"][m]))
            r["ctx_s1wc1_mean_transient_date_count"] = float(np.nanmean(ctx["s1wc1_transient_candidate_date_count"][m]))
            r["ctx_chirps_event_total_mm"] = float(np.nanmean(ctx["chirps_event_total_mm_context_only"][m])) if np.isfinite(ctx["chirps_event_total_mm_context_only"][m]).any() else float("nan")
        hdf = pd.DataFrame(rows)
        hdf["status"] = "EXPLORATORY susceptibility hotspot; ctx_* columns are descriptive S1WC-1/CHIRPS context, NOT validation"
        hdf.to_csv(out / "tables/hotspot_ranking.csv", index=False)
        base_ctx = {"domain_mean_dark_date_fraction": float(np.nanmean(dark_frac[scored])), "domain_persistent_dark_cell_fraction": float(np.nanmean(ctx["s1wc1_persistent_dark_mask"][scored])),
                    "domain_mean_transient_date_count": float(np.nanmean(ctx["s1wc1_transient_candidate_date_count"][scored]))}
        pd.DataFrame([base_ctx]).to_csv(out / "tables/s1wc1_context_domain_baseline.csv", index=False)
        # vectors
        geoms = [(int(v), shape(g)) for g, v in features.shapes(label.astype("int32"), mask=label > 0, transform=grid.transform)]
        gdf = gpd.GeoDataFrame(pd.DataFrame(geoms, columns=["hotspot_id", "geometry"]), geometry="geometry", crs=grid.crs).dissolve(by="hotspot_id").reset_index()
        gdf = gdf.merge(hdf, on="hotspot_id")
        gdf.to_file(out / "vectors/susceptibility_hotspots_exploratory.gpkg", layer="exploratory_susceptibility_hotspots", driver="GPKG")
        gdf.to_crs(4326).to_file(out / "vectors/susceptibility_hotspots_exploratory_wgs84.geojson", driver="GeoJSON")
    corr_names, R = sus.indicator_correlation({k: scores[k] for k in names}, scored)
    cdf = pd.DataFrame(R, index=corr_names, columns=corr_names); cdf.to_csv(out / "tables/indicator_score_correlation_spearman.csv")
    _figures(out, grid, inside, scored, idx, label, topfreq, hdf, sdf, scores, names, cdf)
    summary = {"n_hotspots": n_hs, "dropped_small_components": n_small, "n_scenarios": len(scen), "scored_cells": int(scored.sum())}
    return {"summary": summary}


def _figures(out, grid, inside, scored, idx, label, topfreq, hdf, sdf, scores, names, cdf):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ext = grid.extent
    tag = "EXPLORATORY relative susceptibility - uncalibrated, not validated; not flood risk"
    def base(ax, title):
        ax.set_title(title, fontsize=9); ax.set_xticks([]); ax.set_yticks([])
    bg = np.where(inside, 0.85, np.nan)
    fig, ax = plt.subplots(2, 2, figsize=(13, 13), dpi=110)
    a = ax[0, 0]; a.imshow(bg, cmap="gray", vmin=0, vmax=1, extent=ext)
    im = a.imshow(idx, cmap="viridis", extent=ext, vmin=0, vmax=1); base(a, "Relative susceptibility index (0-1, equal weights)")
    fig.colorbar(im, ax=a, shrink=0.6)
    a = ax[0, 1]; a.imshow(bg, cmap="gray", vmin=0, vmax=1, extent=ext)
    a.imshow(np.where(label > 0, label, np.nan), cmap="autumn", extent=ext)
    if len(hdf):
        for _, r in hdf.head(10).iterrows():
            m = label == r.hotspot_id; yy, xx = np.nonzero(m)
            a.text(ext[0] + xx.mean() * grid.res, ext[3] - yy.mean() * grid.res, str(int(r.rank_by_mean_index)), fontsize=8, color="k", ha="center", weight="bold")
    base(a, "Exploratory hotspots (top decile, >=25 cells); numbers = rank by mean index (top 10)")
    a = ax[1, 0]; a.imshow(bg, cmap="gray", vmin=0, vmax=1, extent=ext)
    im = a.imshow(topfreq, cmap="magma", extent=ext, vmin=0, vmax=1); base(a, "Fraction of weight scenarios placing the cell in the top decile"); fig.colorbar(im, ax=a, shrink=0.6)
    a = ax[1, 1]
    if len(hdf):
        h = hdf.head(15)
        y = np.arange(len(h))[::-1]
        a.hlines(y, h.rank_min_across_scenarios, h.rank_max_across_scenarios, color="0.4"); a.plot(h.rank_by_mean_index, y, "o", color="C3")
        a.set_yticks(y); a.set_yticklabels([f"#{int(i)} ({c:.0f} ha)" for i, c in zip(h.rank_by_mean_index, h.area_ha)], fontsize=8)
        a.set_xlabel("hotspot rank: dot = base, bar = range across all scenarios"); a.set_title("Hotspot rank stability (top 15)", fontsize=9)
    fig.suptitle(tag, fontsize=11, color="firebrick")
    fig.tight_layout(); fig.savefig(out / "figures/susceptibility_summary.png"); plt.close(fig)
    n = len(names); fig, ax = plt.subplots(2, 4, figsize=(16, 9), dpi=100)
    for a, k in zip(ax.ravel(), names):
        a.imshow(bg, cmap="gray", vmin=0, vmax=1, extent=ext); im = a.imshow(scores[k], cmap="viridis", extent=ext, vmin=0, vmax=1); base(a, f"score: {k}")
    for a in ax.ravel()[n:]:
        a.axis("off")
    fig.suptitle("Normalised indicator scores (1 = more susceptible); " + tag, fontsize=10, color="firebrick"); fig.tight_layout(); fig.savefig(out / "figures/indicator_scores_panel.png"); plt.close(fig)
    fig, ax = plt.subplots(1, 3, figsize=(16, 5), dpi=100)
    named = sdf[~sdf.scenario.str.startswith("random_")]; rnd = sdf[sdf.scenario.str.startswith("random_")]
    ax[0].hist(rnd.spearman_vs_base, bins=30, color="C0"); ax[0].set_title("Random-weight runs: Spearman vs base", fontsize=9)
    ax[1].hist(rnd.top_decile_jaccard_vs_base, bins=30, color="C1"); ax[1].set_title("Random-weight runs: top-decile Jaccard vs base", fontsize=9)
    ax[2].barh(named.scenario, named.top_decile_jaccard_vs_base, color="C2"); ax[2].set_title("Named scenarios: top-decile Jaccard vs base", fontsize=9); ax[2].tick_params(labelsize=7)
    fig.suptitle(tag, fontsize=10, color="firebrick"); fig.tight_layout(); fig.savefig(out / "figures/sensitivity.png"); plt.close(fig)
    fig, a = plt.subplots(figsize=(7, 6), dpi=100)
    im = a.imshow(cdf.values, cmap="coolwarm", vmin=-1, vmax=1); a.set_xticks(range(len(cdf))); a.set_xticklabels(cdf.columns, rotation=60, ha="right", fontsize=8)
    a.set_yticks(range(len(cdf))); a.set_yticklabels(cdf.index, fontsize=8)
    for i in range(len(cdf)):
        for j in range(len(cdf)):
            a.text(j, i, f"{cdf.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=a, shrink=0.7); a.set_title("Spearman correlation of indicator scores (scored cells)\nhigh |rho| = overlapping information (implicit double weighting)", fontsize=9)
    fig.tight_layout(); fig.savefig(out / "figures/indicator_correlation.png"); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/susceptibility.json")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-dir", default=None, help="override output dir (must start with 'susceptibility_', must not exist or be empty)")
    ap.add_argument("--stack-only", action="store_true")
    a = ap.parse_args(argv)
    return run(a.root, a.config, a.out_dir, a.stack_only)


if __name__ == "__main__":
    sys.exit(main())
