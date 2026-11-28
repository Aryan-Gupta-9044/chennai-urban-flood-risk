#!/usr/bin/env python
"""S1TC-1: multi-date context for the accepted S1WC-2 water-change candidates (read-only on all accepted products).

  .\\.venv\\Scripts\\python.exe scripts\\build_s1_temporal_context.py

Describes, for the eight 2021 Sentinel-1 dates, how class-1 "transient dark candidates" (E4, NOT confirmed floodwater)
vary in area, overlap between dates, concentrate in wards, and sit relative to the accepted SUS-1 percentile; and
lists CHIRPS antecedent rainfall beside them (E5 context; n = 8 dates, descriptive only).

Inputs (hash-guarded, never modified): S1WC-2 class rasters, SUS-1 percentile and domain rasters, TNGIS wards,
CHIRPS 2021 antecedent table. Writes ONLY to outputs/s1_temporal_context_v1 (or --outdir).

Caveats carried into every table: candidates are not floodwater; no independent flood reference exists for any date;
both S1WC-2 (slope screen) and SUS-1 (slope indicator) use DEM slope, so their association is not fully independent.
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

VERSION = "S1TC-1.0"
DATES = ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"]
S1 = ROOT / "outputs/s1_water_candidates_review_v2/rasters"
SUS = ROOT / "outputs/susceptibility_v1/rasters"
CHIRPS = ROOT / "outputs/chirps_2021/tables/rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1.csv"
PROTECTED = ["outputs/s1_water_candidates_review_v2", "outputs/susceptibility_v1", "outputs/chirps_2021", "outputs/dep2_local_run_01",
             "outputs/ml_exploratory_v1", "data"]
CELL_KM2 = 0.0009  # 30 m x 30 m


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


def read(p):
    import rasterio
    with rasterio.open(p) as ds:
        return ds.read(1), ds.transform, ds.crs, ds.shape


def gini(x):
    x = np.sort(np.asarray(x, float))
    if x.sum() == 0:
        return float("nan")
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default=str(ROOT / "outputs" / "s1_temporal_context_v1"))
    a = ap.parse_args(argv)
    t0 = time.time()
    out = Path(a.outdir)
    guard(out)
    T = out / "tables"
    T.mkdir(parents=True, exist_ok=True)
    rasters = [S1 / f"s1_water_candidates_v2_class_{d}.tif" for d in DATES]
    watched = rasters + [SUS / "susceptibility_percentile.tif", SUS / "domain_class.tif", CHIRPS]
    h0 = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}

    pct, tr, crs, shape = read(SUS / "susceptibility_percentile.tif")
    dom, tr2, crs2, shape2 = read(SUS / "domain_class.tif")
    stack = []
    for p in rasters:
        c, t_, c_, s_ = read(p)
        if s_ != shape or t_ != tr or c_ != crs:
            raise SystemExit(f"STOP: {p.name} is not on the SUS-1 master grid")
        stack.append(c)
    stack = np.stack(stack)
    aoi = stack[0] != 255
    scored = dom == 1
    pct = np.where(scored, pct, np.nan)

    # 1. per-date area
    rows = []
    for i, d in enumerate(DATES):
        c = stack[i]
        rows.append({"date": d, "class1_cells": int((c == 1).sum()), "class1_km2": round(float((c == 1).sum() * CELL_KM2), 4),
                     "class8_km2": round(float((c == 8).sum() * CELL_KM2), 4), "invalid_cells": int((c == 254).sum()),
                     "class1_pct_of_aoi": round(100 * float((c == 1).sum()) / aoi.sum(), 4),
                     "class1_in_sus1_not_assessed_cells": int(((c == 1) & ~scored & aoi).sum())})
    per = pd.DataFrame(rows)

    # 2. date-to-date overlap (Jaccard) and persistence of class-1 cells
    c1 = stack == 1
    J = np.zeros((8, 8))
    for i in range(8):
        for j in range(8):
            u = (c1[i] | c1[j]).sum()
            J[i, j] = (c1[i] & c1[j]).sum() / u if u else np.nan
    jac = pd.DataFrame(J, index=DATES, columns=DATES).round(4)
    ndates = c1.sum(0)
    pers = pd.DataFrame({"n_dates_class1": np.arange(1, 9), "cells": [int((ndates == k).sum()) for k in range(1, 9)]})
    pers["km2"] = (pers.cells * CELL_KM2).round(4)
    pers["share_of_ever_class1"] = (pers.cells / max(int((ndates > 0).sum()), 1)).round(4)

    # 3. relation to SUS-1 deciles (enrichment = share of class-1 cells in decile / share of scored cells in decile)
    dec = np.full(pct.shape, -1, int)
    dec[scored] = np.minimum((pct[scored] // 10).astype(int), 9)
    base = np.array([(dec == k).sum() for k in range(10)], float)
    base /= base.sum()
    enr = []
    for i, d in enumerate(DATES):
        m = c1[i] & scored
        n = m.sum()
        cnt = np.array([(m & (dec == k)).sum() for k in range(10)], float)
        for k in range(10):
            enr.append({"date": d, "sus1_decile": k + 1, "class1_cells": int(cnt[k]), "share_of_class1": round(cnt[k] / n, 4) if n else np.nan,
                        "share_of_scored_cells": round(base[k], 4), "enrichment_ratio": round((cnt[k] / n) / base[k], 3) if n else np.nan})
        per.loc[i, "class1_mean_sus1_pct"] = round(float(np.nanmean(pct[m])), 2) if n else np.nan
        per.loc[i, "class1_share_in_sus1_top_decile"] = round(cnt[9] / n, 4) if n else np.nan
    per["scored_mean_sus1_pct"] = round(float(np.nanmean(pct)), 2)
    enr = pd.DataFrame(enr)

    # 4. spatial concentration by ward
    import geopandas as gpd
    from rasterio.features import rasterize
    from dep2 import layers
    wards = layers.load_wards(layers.Sources(ROOT / "data/external/dep2_sources")).to_crs(crs)
    wid = rasterize(((g, int(w)) for g, w in zip(wards.geometry, wards.ward_no)), out_shape=shape, transform=tr, fill=0, dtype="int32")
    conc, ward_rows = [], []
    for i, d in enumerate(DATES):
        v = np.bincount(wid[c1[i]], minlength=int(wid.max()) + 1)[1:]
        ids = np.arange(1, len(v) + 1)
        keep = np.isin(ids, wards.ward_no.values)
        v, ids = v[keep], ids[keep]
        tot = v.sum()
        top10 = np.sort(v)[::-1][:10].sum()
        conc.append({"date": d, "class1_cells_in_gcc_wards": int(tot), "wards_with_any_class1": int((v > 0).sum()),
                     "top10_ward_share": round(top10 / tot, 4) if tot else np.nan, "gini_over_wards": round(gini(v), 4)})
        ward_rows += [{"date": d, "ward_no": int(w), "class1_km2": round(float(x * CELL_KM2), 4)} for w, x in zip(ids, v)]
    conc = pd.DataFrame(conc)
    wardt = pd.DataFrame(ward_rows).pivot(index="ward_no", columns="date", values="class1_km2").reset_index()

    # 5. rainfall context (descriptive; n = 8)
    from scipy.stats import spearmanr
    r = pd.read_csv(CHIRPS).rename(columns={"s1_date": "date"})
    rr = per.merge(r[["date", "prior_1d_aoi_mean_mm", "prior_3d_aoi_mean_mm", "prior_7d_aoi_mean_mm", "prior_14d_aoi_mean_mm"]], on="date", how="left")
    rain = []
    for col in ["prior_1d_aoi_mean_mm", "prior_3d_aoi_mean_mm", "prior_7d_aoi_mean_mm", "prior_14d_aoi_mean_mm"]:
        ok = rr[col].notna()
        rho, p = spearmanr(rr.loc[ok, col], rr.loc[ok, "class1_km2"]) if ok.sum() >= 4 else (np.nan, np.nan)
        rain.append({"rainfall": col, "metric": "class1_km2", "n_dates": int(ok.sum()), "spearman_rho": round(float(rho), 3), "p_naive": round(float(p), 3),
                     "note": "descriptive only; n = 8 dates; CHIRPS ~5 km cells (E5 context); not causal; no flood reference"})
    rain = pd.DataFrame(rain)

    per = per.merge(conc, on="date").merge(r[["date", "prior_3d_aoi_mean_mm", "prior_7d_aoi_mean_mm"]], on="date", how="left")
    per.to_csv(T / "s1tc_per_date_summary.csv", index=False, lineterminator="\n")
    jac.to_csv(T / "s1tc_class1_jaccard_between_dates.csv", lineterminator="\n")
    pers.to_csv(T / "s1tc_class1_persistence_histogram.csv", index=False, lineterminator="\n")
    enr.to_csv(T / "s1tc_class1_sus1_decile_enrichment.csv", index=False, lineterminator="\n")
    wardt.to_csv(T / "s1tc_class1_km2_by_ward_and_date.csv", index=False, lineterminator="\n")
    rain.to_csv(T / "s1tc_rainfall_context_spearman.csv", index=False, lineterminator="\n")

    # figure
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    (out / "figures").mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 3, figsize=(10.5, 3.2), dpi=200)
    x = np.arange(8)
    ax[0].bar(x, per.class1_km2, color="#0072B2")
    ax0b = ax[0].twinx()
    ax0b.plot(x, per.prior_7d_aoi_mean_mm, "o--", color="#E69F00", ms=3)
    ax0b.set_ylabel("CHIRPS prior 7-day mean (mm), E5", fontsize=6, color="#9a6700")
    ax[0].set_xticks(x); ax[0].set_xticklabels([d[5:] for d in DATES], rotation=60, fontsize=6)
    ax[0].set_ylabel("class-1 candidate area (km²)", fontsize=7); ax[0].set_title("Candidate area per date (E4)", fontsize=8)
    im = ax[1].imshow(jac.values, vmin=0, vmax=1, cmap="viridis")
    ax[1].set_xticks(x); ax[1].set_yticks(x); ax[1].set_xticklabels([d[5:] for d in DATES], rotation=60, fontsize=6); ax[1].set_yticklabels([d[5:] for d in DATES], fontsize=6)
    ax[1].set_title("Date-to-date overlap (Jaccard)", fontsize=8); fig.colorbar(im, ax=ax[1], fraction=0.046)
    e = enr.groupby("sus1_decile").enrichment_ratio.agg(["median", "min", "max"])
    ax[2].plot(e.index, e["median"], "o-", color="#009E73", label="median over 8 dates")
    ax[2].fill_between(e.index, e["min"], e["max"], color="#009E73", alpha=0.2, label="range over dates")
    ax[2].axhline(1, color="k", lw=0.6, ls=":")
    ax[2].set_xlabel("SUS-1 decile (1 = lowest relative)", fontsize=7); ax[2].set_ylabel("enrichment of class-1 cells", fontsize=7)
    ax[2].set_title("Candidates vs SUS-1 deciles", fontsize=8); ax[2].legend(fontsize=6)
    for a_ in ax:
        a_.tick_params(labelsize=6)
    fig.tight_layout(); fig.savefig(out / "figures/fig_s1tc_temporal_context.png"); plt.close(fig)

    h1 = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
    summary = {"version": VERSION, "seconds": round(time.time() - t0, 1), "dates": DATES,
               "class1_km2_min_max": [float(per.class1_km2.min()), float(per.class1_km2.max())],
               "jaccard_offdiag_median": float(np.nanmedian(J[~np.eye(8, dtype=bool)])),
               "ever_class1_km2": float((ndates > 0).sum() * CELL_KM2), "class1_on_1_date_share": float(pers.share_of_ever_class1.iloc[0]),
               "top_decile_enrichment_median": float(enr[enr.sus1_decile == 10].enrichment_ratio.median()),
               "rainfall_spearman": rain.to_dict("records"),
               "inputs_unchanged": h0 == h1, "input_hashes": h0,
               "claims_not_made": ["floodwater", "flood extent", "validation of SUS-1", "accuracy", "causal rainfall effect"]}
    (out / "s1tc_summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n", encoding="utf-8")
    lines = [f"{sha(p)}  {p.relative_to(out).as_posix()}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{VERSION} done in {summary['seconds']} s; inputs unchanged: {summary['inputs_unchanged']}")
    return 0 if summary["inputs_unchanged"] else 2


if __name__ == "__main__":
    sys.exit(main())
