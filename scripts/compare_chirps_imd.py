#!/usr/bin/env python
"""Module CMP (V2.3) - SIDE-BY-SIDE CHIRPS v3 DAILY_SAT vs IMD 0.25 deg comparison for the Chennai AOI. NOT a validation and NOT a blend.

Reads the two sources' prepared daily GeoTIFFs (data/external/rainfall/imd_gridded_daily/daily and .../chirps_v3_daily/daily) read-only.
 * IMD cells overlapping the AOI are listed with their valid-day counts and the share of the AOI polygon they cover -> documents IMD's incomplete Chennai coverage.
 * For each IMD cell that has data, CHIRPS native cells are area-averaged over (a) the IMD cell footprint (only if the CHIRPS export window covers >= --min-support of it)
   and (b) the part of that footprint inside the AOI (always supported). Nothing is resampled; IMD is never interpolated.
 * Lag diagnostics (-2..+2 days) and a 1-2 December two-day-sum diagnostic address the daily TIMING question; they do not decide which product is right.
Usage: python scripts/compare_chirps_imd.py"""
import argparse
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import chirps, chirps_acquire as CA, rainfall as R, rainfall_compare as RC
from src.geospatial.study_area import load_study_area


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--event", default="2015_nov_dec")
    ap.add_argument("--imd-dir", default=str(paths.DATA_EXT / "rainfall" / "imd_gridded_daily" / "daily"))
    ap.add_argument("--chirps-dir", default=str(paths.DATA_EXT / "rainfall" / CA.SOURCE_ID / "daily"))
    ap.add_argument("--outputs-dir", default=str(paths.ROOT / "outputs"))
    ap.add_argument("--min-support", type=float, default=0.5, help="min share of an IMD cell footprint covered by the CHIRPS window for the footprint comparison")
    ap.add_argument("--focus", nargs=2, default=["2015-11-20", "2015-12-06"], help="provisional heavy-rain window for lag statistics")
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("compare_chirps_imd")
    od = Path(a.outputs_dir); tab, figd, repd = od / "tables", od / "figures", od / "reports"
    for p in (tab, figd, repd): p.mkdir(parents=True, exist_ok=True)
    ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"][a.event]
    dates = R.daterange(*ev["context_window"])
    try:
        imd, imd_tr, imd_crs, imd_present = RC.read_cube(Path(a.imd_dir), dates)
        chi, ch_tr, ch_crs, ch_present = RC.read_cube(Path(a.chirps_dir), dates)
    except (FileNotFoundError, ValueError) as e:
        status.record("CMP", status.BLOCKED, str(e)); print("BLOCKED:", e); return 2
    if str(imd_crs).upper() != "EPSG:4326" or str(ch_crs).upper() != "EPSG:4326":
        status.record("CMP", status.BLOCKED, f"expected both products in EPSG:4326, got IMD {imd_crs}, CHIRPS {ch_crs}"); print("BLOCKED: CRS"); return 2
    g, _, _ = load_study_area()
    aoi = g.geometry.union_all() if hasattr(g.geometry, "union_all") else g.geometry.unary_union
    cells = RC.imd_cells_over_aoi(imd_tr, imd.shape[1:], aoi)
    cov = RC.imd_aoi_coverage_by_day(imd, cells)
    n = len(dates)
    sup_rows, cols = [], {}
    for ce in cells:
        s = imd[:, ce["row"], ce["col"]]; nvalid = int(np.isfinite(s).sum())
        ce["valid_days"] = nvalid
        foot_series, foot_sup, foot_n = RC.chirps_area_mean(chi, ch_tr, ce["footprint"])
        part = ce["footprint"].intersection(aoi)
        part_series, part_sup, part_n = RC.chirps_area_mean(chi, ch_tr, part)
        ce.update(foot=(foot_series, foot_sup, foot_n), part=(part_series, part_sup, part_n))
        sup_rows.append({"imd_row": ce["row"], "imd_col": ce["col"], "imd_centre_lon": round(ce["centre"][0], 4), "imd_centre_lat": round(ce["centre"][1], 4),
                         "aoi_share": round(ce["aoi_share"], 4), "imd_valid_days": nvalid, "imd_days_in_window": n, "chirps_footprint_support": round(foot_sup, 3),
                         "chirps_cells_in_footprint": foot_n, "chirps_cells_in_aoi_part": part_n})
    pd_ = lambda p: p.exists()
    with open(tab / "chirps_vs_imd_support.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sup_rows[0].keys())); w.writeheader(); w.writerows(sup_rows)
    usable = [ce for ce in cells if ce["valid_days"] > 0]
    # full-AOI CHIRPS mean (strict) for context
    aoi_series, aoi_sup, _ = RC.chirps_area_mean(chi, ch_tr, aoi)
    daily_cols = {"date": [d.isoformat() for d in dates], "imd_aoi_area_coverage": np.round(cov, 4), "chirps_aoi_mean_mm": aoi_series}
    lag_rows = []; focus0, focus1 = (date.fromisoformat(x) for x in a.focus)
    fi = [i for i, d in enumerate(dates) if focus0 <= d <= focus1]
    notes = []; split_rows = []
    for ce in usable:
        tag = f"r{ce['row']}c{ce['col']}"; s = imd[:, ce["row"], ce["col"]]
        daily_cols[f"imd_{tag}_mm"] = s
        for mode, (ser, sup, nc) in (("footprint", ce["foot"]), ("aoi_part", ce["part"])):
            daily_cols[f"chirps_{mode}_{tag}_mm"] = ser
            if mode == "footprint" and sup < a.min_support:
                notes.append(f"IMD cell {tag}: footprint comparison NOT made - the CHIRPS export window covers only {sup:.0%} of the 0.25 deg cell (min {a.min_support:.0%}). "
                             "A wider CHIRPS window (user decision) would be needed."); continue
            for scope, idx in (("context_window", range(n)), ("focus_window", fi)):
                ii = list(idx)
                for r in RC.lag_stats(s[ii], ser[ii], [dates[i] for i in ii]): lag_rows.append({"imd_cell": tag, "mode": mode, "chirps_support": round(sup, 3), "scope": scope, **r})
            split_rows.append({"imd_cell": tag, "mode": mode, **RC.two_day_split(s, ser, dates, date(2015, 12, 1), date(2015, 12, 2))})
    with open(tab / "chirps_vs_imd_daily.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); keys = list(daily_cols.keys()); w.writerow(keys)
        for i in range(n): w.writerow([("" if isinstance(daily_cols[k][i], (float, np.floating)) and not np.isfinite(daily_cols[k][i]) else (round(float(daily_cols[k][i]), 4) if isinstance(daily_cols[k][i], (float, np.floating)) else daily_cols[k][i])) for k in keys])
    if lag_rows:
        with open(tab / "chirps_vs_imd_lags.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lag_rows[0].keys())); w.writeheader(); w.writerows(lag_rows)
    if split_rows:
        with open(tab / "chirps_vs_imd_dec1_2.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(split_rows[0].keys())); w.writeheader(); w.writerows(split_rows)
    # ---- figure: time series around the event + lag correlation
    figs = []
    if usable:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        z0, z1 = date(2015, 11, 15), date(2015, 12, 10); zi = [i for i, d in enumerate(dates) if z0 <= d <= z1]
        fig, ax = plt.subplots(figsize=(10, 4.5)); xs = [dates[i] for i in zi]
        ax.bar(xs, [aoi_series[i] if np.isfinite(aoi_series[i]) else 0 for i in zi], color="#9ecae1", label="CHIRPS AOI mean (native 0.05 deg)")
        for ce in usable:
            ax.plot(xs, [imd[i, ce["row"], ce["col"]] for i in zi], "o-", ms=4, label=f"IMD cell r{ce['row']}c{ce['col']} (0.25 deg, centre {ce['centre'][0]:.2f},{ce['centre'][1]:.2f})")
        ax.set_ylabel("mm per labelled day"); ax.set_title("CHIRPS v3 SAT vs IMD - labels as published; day definitions differ and are NOT verified; not validation", fontsize=9)
        ax.legend(fontsize=7); fig.autofmt_xdate(); fig.savefig(figd / "chirps_vs_imd_timeseries.png", dpi=150, bbox_inches="tight"); plt.close(fig); figs.append("chirps_vs_imd_timeseries.png")
        okl = [r for r in lag_rows if r["scope"] == "focus_window" and r["mode"] == "aoi_part" and r["pearson_r"] is not None]
        if okl:
            fig, ax = plt.subplots(figsize=(6, 3.5))
            for tagc in sorted({r["imd_cell"] for r in okl}):
                rr = [r for r in okl if r["imd_cell"] == tagc]; ax.plot([r["lag_days"] for r in rr], [r["pearson_r"] for r in rr], "o-", label=tagc)
            ax.set_xlabel("lag k: IMD[d] vs CHIRPS[d+k] (days)"); ax.set_ylabel("Pearson r (focus window)"); ax.legend(fontsize=7); ax.set_title("Lag diagnostic (not validation)", fontsize=9)
            fig.savefig(figd / "chirps_vs_imd_lag_correlation.png", dpi=150, bbox_inches="tight"); plt.close(fig); figs.append("chirps_vs_imd_lag_correlation.png")
    # ---- report
    cv_valid = cov[imd_present] if imd_present.any() else np.array([0.0])
    L = ["# CHIRPS v3 DAILY_SAT vs IMD 0.25 deg - side-by-side comparison", "",
         "**Not a validation.** Neither product is ground truth; CHIRPS blends station data (so it is not independent of gauges); the two products use different, unverified day definitions. They are never merged, gap-filled or blended here.", "",
         "## IMD coverage of the Chennai AOI (documented, not repaired)",
         f"- IMD native cells overlapping the AOI: {len(cells)}; with any valid data in the window: {len(usable)}. AOI-area share covered by valid IMD cells per day: min {cv_valid.min():.1%}, max {cv_valid.max():.1%}.",
         "- Per-cell table: `outputs/tables/chirps_vs_imd_support.csv`. IMD cells without data are NOT filled from CHIRPS.", "",
         "## Spatial support", f"- CHIRPS AOI support: {aoi_sup:.0%} of the AOI polygon lies inside the CHIRPS export window ({ch_present.sum()} of {n} CHIRPS days present, {imd_present.sum()} IMD days present).",
         "- CHIRPS is area-averaged over an IMD cell footprint (comparison only; no resampling of either product). 'footprint' needs the export window to cover the 0.25 deg cell; 'aoi_part' averages CHIRPS over (IMD cell ∩ AOI), always supported but a different spatial support from the IMD value."]
    L += [f"- {x}" for x in notes] + [""]
    L += ["## Daily timing (1-2 December 2015 and lags)",
          "Documented/expected day conventions (UNVERIFIED for these exact products): IMD - 24 h accumulation ending 08:30 IST, label convention (end vs start date) not confirmed; "
          "CHIRPS v3 SAT - daily labels from the IMERG-based disaggregation, expected UTC-day based (00-24 UTC = 05:30-05:30 IST) but NOT verified as local observation days. "
          "Candidate explanations to test (none established): (1) end-date vs start-date labelling of IMD; (2) the ~3 h offset between the 08:30 IST and 05:30 IST day boundaries; "
          "(3) the IMERG disaggregation of station pentads; (4) IMD gauge interpolation onto one valid cell. The lag table and the two-day-sum row below are diagnostics only.", ""]
    for r in split_rows:
        f = lambda v: "n/a" if v is None else f"{v:.1f}"
        L.append(f"- IMD cell {r['imd_cell']} / {r['mode']}: IMD 1 Dec {f(r['imd_d1'])}, 2 Dec {f(r['imd_d2'])} (sum {f(r['imd_2day_sum'])}); CHIRPS 1 Dec {f(r['chirps_d1'])}, 2 Dec {f(r['chirps_d2'])} (sum {f(r['chirps_2day_sum'])}); 2-day-sum ratio CHIRPS/IMD {f(r['two_day_sum_ratio_chirps_to_imd'])}")
    if not split_rows: L.append("- No comparable IMD cell: no timing diagnostic produced.")
    L += ["", f"Lag statistics (IMD[d] vs CHIRPS[d+k]) for the context window and the provisional focus window {a.focus[0]}..{a.focus[1]}: `outputs/tables/chirps_vs_imd_lags.csv` (r needs >= 8 pairs).", "",
          "Conclusion rule: until the day windows are verified, daily CHIRPS values must NOT be used as precise antecedent rainfall relative to a ~06:01 IST Sentinel-1 pass; use multi-day totals with the timing uncertainty stated.", "",
          "## Files", "- outputs/tables/chirps_vs_imd_{support,daily,lags,dec1_2}.csv", *[f"- outputs/figures/{x}" for x in figs]]
    rep = repd / "chirps_vs_imd_comparison.md"; rep.write_text("\n".join(L) + "\n", encoding="utf-8")
    status.record("CMP", status.PARTIAL, f"IMD valid cells {len(usable)}/{len(cells)}; comparison is side-by-side only, not validation", files=[rep], seconds=time.time() - t0)
    print("\n".join(L[:14])); print("Report:", rep); return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
