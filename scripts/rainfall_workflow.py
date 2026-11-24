#!/usr/bin/env python
"""Module C2 (V2.3) - SOURCE-AGNOSTIC rainfall workflow for an event window, from daily rasters you place in data/external/rainfall/<source_id>/.
No downloads and no source-specific logic: pick a source first, copy config/rainfall_source_template.json to <dir>/source.json and fill it in.
Produces (native grid, never silently resampled): per-day completeness + AOI statistics time series, daily-map montage, strict event total
(NaN if any day is missing), valid-day count, k-day maxima statistics, antecedent totals before event-configured Sentinel-1 dates, report.
Missing / invalid days are NEVER treated as 0 mm. Anomaly is NOT computed without a same-source multi-year baseline.
Usage:  .\\.venv\\Scripts\\python scripts\\rainfall_workflow.py --source-id <id> [--event 2015_nov_dec] [--allow-partial] [--resample-to-master]"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import rainfall as R
from src.geospatial.raster_io import read_bounds

ND = -9999.0
REQUIRED = ["source_id", "unit", "day_definition", "file_pattern", "expected_crs", "native_resolution", "product_type", "version"]


def write_native(path, arr, transform, crs, desc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="float32", crs=crs,
                       transform=transform, nodata=ND, compress="deflate") as d:
        d.write(np.where(np.isfinite(arr), arr, ND).astype("float32"), 1)
        d.set_band_description(1, desc)


def block(a, b, status_, msg, t0, **kw):
    a.error(msg); status.record("C2", b, msg, seconds=time.time() - t0, **kw)



def load_s1_observations(event_config, config_dir=None):
    """Load Sentinel-1 dates from the source explicitly declared by a rainfall event.

    Candidate roles retain their configured categories. Preprocessing dates are
    observations only and receive category="unassigned".
    """
    config_dir = Path(config_dir) if config_dir is not None else paths.CONFIG
    source = event_config.get("sentinel1_dates_from")
    if not source:
        raise ValueError("rainfall event has no sentinel1_dates_from configuration")

    source_name = Path(source).name
    if source_name == "s1_candidate_roles.json":
        payload = json.loads((config_dir / source_name).read_text(encoding="utf-8"))
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"{source_name} has no candidate list")
        observations = [
            {"date": item["date"], "category": item["category"], "kind": "candidate"}
            for item in candidates
        ]
    elif source_name == "s1_preprocess.json":
        payload = json.loads((config_dir / source_name).read_text(encoding="utf-8"))
        dates = payload.get("dates")
        if not isinstance(dates, list) or not dates:
            raise ValueError(f"{source_name} has no processed dates")
        observations = [
            {"date": value, "category": "unassigned", "kind": "processed-observation"}
            for value in dates
        ]
    else:
        raise ValueError(f"unsupported Sentinel-1 date source in rainfall event: {source}")

    seen = set()
    for item in observations:
        value = item.get("date")
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid Sentinel-1 date in {source_name}: {item!r}") from exc
        if parsed.isoformat() != value:
            raise ValueError(f"Sentinel-1 dates must use YYYY-MM-DD in {source_name}: {item!r}")
        if value in seen:
            raise ValueError(f"duplicate Sentinel-1 date in {source_name}: {value}")
        seen.add(value)

    label = ("Sentinel-1 candidate date" if source_name == "s1_candidate_roles.json"
             else "Sentinel-1 processed-observation date")
    return observations, label, source_name

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--event", default="2015_nov_dec")
    ap.add_argument("--input-dir", default="")
    ap.add_argument("--out-dir", default=str(paths.DATA_PROC / "rainfall"))
    ap.add_argument("--outputs-dir", default=str(paths.ROOT / "outputs"))
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--allow-partial", action="store_true", help="also write a LOWER-BOUND event total when days are missing (clearly labelled)")
    ap.add_argument("--resample-to-master", action="store_true", help="also write a LABELLED nearest-neighbour resampling on the 30 m master grid")
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("C2_rainfall"); paths.ensure_dirs()
    odir = Path(a.outputs_dir); tab, figd, repd = odir / "tables", odir / "figures", odir / "reports"
    for d in (tab, figd, repd, Path(a.out_dir)):
        d.mkdir(parents=True, exist_ok=True)
    ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"].get(a.event)
    if not ev:
        return block(log, status.BLOCKED, None, f"unknown rainfall event '{a.event}' in config/rainfall_events.json", t0)
    in_dir = Path(a.input_dir) if a.input_dir else paths.DATA_EXT / "rainfall" / a.source_id
    sj = in_dir / "source.json"
    if not sj.exists():
        return block(log, status.BLOCKED, None, f"{sj} not found. Choose a source, place daily rasters in {in_dir} and copy "
                     "config/rainfall_source_template.json to source.json (filled in). No data are downloaded by this module.", t0,
                     requirements=["dataset-source confirmation (Agent 1 / user)"])
    src = json.loads(sj.read_text(encoding="utf-8"))
    miss_keys = [k for k in REQUIRED if not src.get(k) or "FILL_ME" in str(src.get(k))]
    if miss_keys:
        return block(log, status.BLOCKED, None, f"source.json incomplete: {miss_keys}", t0)
    try:
        R.to_mm(np.zeros(1), src["unit"], src.get("accumulation_hours"))
    except ValueError as e:
        return block(log, status.BLOCKED, None, f"unit problem: {e}", t0)
    import geopandas as gpd
    from src.geospatial.study_area import load_study_area, bounds_wgs84, master_grid
    wgs, utm, _ = load_study_area()
    aoi_wgs = wgs.geometry.union_all() if hasattr(wgs.geometry, "union_all") else wgs.unary_union
    bb = bounds_wgs84(pad=0.15)

    ctx = R.daterange(*ev["context_window"])
    raw, rec, grids = {}, [], []
    for d in ctx:
        p = in_dir / src["file_pattern"].format(date=d)
        row = {"date": d.isoformat(), "file": p.name, "status": "MISSING", "note": ""}
        if p.exists():
            try:
                r = read_bounds(p, bb)
                if r is None:
                    row.update(status="MISSING", note="file does not overlap the study area")
                else:
                    arr, tr, crs, nd = r
                    if crs is None or crs.to_string().upper().replace("EPSG:", "") != str(src["expected_crs"]).upper().replace("EPSG:", ""):
                        return block(log, status.BLOCKED, None, f"{p.name}: CRS {crs} != expected {src['expected_crs']}", t0)
                    raw[d] = (arr, tr, crs, nd); grids.append((tr, arr.shape, crs)); row["status"] = "READ"
            except Exception as e:  # noqa
                row.update(status="UNREADABLE", note=str(e)[:120])
        rec.append(row)
    if not raw:
        return block(log, status.BLOCKED, None, f"no readable daily raster found in {in_dir} for {ctx[0]}..{ctx[-1]}", t0)
    try:
        R.check_same_grid(grids)
    except ValueError as e:
        return block(log, status.BLOCKED, None, f"daily rasters are not on one grid: {e}", t0)
    tr0, sh0, crs0 = grids[0]
    aoi = gpd.GeoSeries([aoi_wgs], crs=4326).to_crs(crs0).iloc[0]
    w = R.cell_weights(tr0, sh0, aoi)
    aoi_cov = float(w.sum())
    log.info("grid %s %s, native cells intersecting the AOI: %d, AOI inside raster extent: %.1f%%", crs0, sh0, int((w > 0).sum()), 100 * aoi_cov)

    day_map, series = {}, []
    for row in rec:
        d = date.fromisoformat(row["date"])
        if d in raw:
            mm, cnt = R.clean_day(raw[d][0], src["unit"], src.get("nodata", raw[d][3]), src.get("accumulation_hours"))
            st = R.weighted_stats(mm, w)
            row["status"] = R.classify_day(mm, w, a.min_coverage)
            row.update(aoi_mean_mm=st["mean_mm"], aoi_min_mm=st["min_mm"], aoi_max_mm=st["max_mm"], aoi_valid_coverage=round(st["coverage"], 4),
                       cells_valid=st["cells_valid"], **cnt)
            day_map[d] = mm if row["status"] == "OK" else None
            if row["status"] != "OK":
                row["note"] = f"valid cells cover {100 * st['coverage']:.1f}% of the AOI (< {100 * a.min_coverage:.0f}%): excluded from totals"
        else:
            day_map[d] = None
        series.append(row)
    ts = pd.DataFrame(series)
    base = f"rainfall_{a.source_id}_{a.event}"
    ts.to_csv(tab / f"{base}_daily_series.csv", index=False)

    e0, e1 = (date.fromisoformat(x) for x in ev["event_window_proposed"])
    ev_days = R.daterange(e0, e1)
    miss_ev = [d for d in ev_days if day_map.get(d) is None]
    total, nvalid = R.strict_total([day_map.get(d) for d in ev_days], allow_partial=False)
    files, outd = [str(tab / f"{base}_daily_series.csv")], Path(a.out_dir) / a.source_id
    total_state = "COMPUTED (all event-window days valid)"
    if miss_ev:
        total_state = f"NOT COMPUTED: {len(miss_ev)} of {len(ev_days)} event-window days missing/unusable ({', '.join(d.isoformat() for d in miss_ev[:6])}{' ...' if len(miss_ev) > 6 else ''})"
        if a.allow_partial and any(day_map.get(d) is not None for d in ev_days):
            lb, nv = R.strict_total([day_map.get(d) for d in ev_days], allow_partial=True)
            write_native(outd / f"{a.event}_event_total_mm_native_LOWER_BOUND_partial.tif", lb, tr0, crs0,
                         f"LOWER BOUND: sum of valid days only ({len(ev_days) - len(miss_ev)}/{len(ev_days)} days); NOT a true total")
            files.append(paths.rel(outd / f"{a.event}_event_total_mm_native_LOWER_BOUND_partial.tif"))
            total_state += " | LOWER-BOUND file written (labelled, not a total)"
    else:
        write_native(outd / f"{a.event}_event_total_mm_native.tif", total, tr0, crs0, f"event total mm, native grid ({src['native_resolution']}), source {src['source_id']}")
        files.append(paths.rel(outd / f"{a.event}_event_total_mm_native.tif"))
    write_native(outd / f"{a.event}_event_valid_days_native.tif", nvalid.astype("float64"), tr0, crs0, f"number of valid days of {len(ev_days)}")
    ev_stat = R.weighted_stats(total, w) if not miss_ev else None

    kdf = []
    for k in ev["max_k_day"]:
        mx, used, skipped = R.max_k_day(day_map, ev_days, k)
        s = R.weighted_stats(mx, w) if mx is not None else None
        kdf.append({"k_days": k, "complete_windows": used, "windows_skipped_missing_days": skipped,
                    "aoi_mean_of_max_mm": None if s is None else round(s["mean_mm"], 2), "cell_max_mm": None if s is None else round(s["max_mm"], 2)})
    pd.DataFrame(kdf).to_csv(tab / f"{base}_max_k_day.csv", index=False)

    try:
        s1_observations, s1_plot_label, s1_source_name = load_s1_observations(ev)
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        return block(log, status.BLOCKED, None, f"invalid Sentinel-1 date configuration for event '{a.event}': {exc}", t0)
    outside_context = [
        item["date"] for item in s1_observations
        if not ctx[0] <= date.fromisoformat(item["date"]) <= ctx[-1]
    ]
    if outside_context:
        return block(log, status.BLOCKED, None,
                     f"Sentinel-1 dates fall outside event context window {ctx[0]}..{ctx[-1]}: {outside_context}", t0)
    ante = []
    for observation in s1_observations:
        d0 = date.fromisoformat(observation["date"])
        row = {"s1_date": observation["date"], "category": observation["category"]}
        for n in ev["antecedent_windows_days"]:
            t, miss = R.window_total(day_map, d0, n, include_end_day=False)
            row[f"prior_{n}d_aoi_mean_mm"] = None if t is None else round(R.weighted_stats(t, w)["mean_mm"], 2)
            row[f"prior_{n}d_missing_days"] = len(miss)
        ante.append(row)
    pd.DataFrame(ante).to_csv(tab / f"{base}_antecedent_before_s1.csv", index=False)
    files += [str(tab / f"{base}_max_k_day.csv"), str(tab / f"{base}_antecedent_before_s1.csv")]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    md0, md1 = (date.fromisoformat(x) for x in ev["daily_map_window"])
    mdays = R.daterange(md0, md1)
    vmax = max([np.nanmax(day_map[d]) for d in mdays if day_map.get(d) is not None and np.isfinite(day_map[d]).any()] or [1.0])
    nc = 7; nr = int(np.ceil(len(mdays) / nc))
    fig, axs = plt.subplots(nr, nc, figsize=(2.2 * nc, 2.3 * nr), squeeze=False)
    ext = (tr0.c, tr0.c + tr0.a * sh0[1], tr0.f + tr0.e * sh0[0], tr0.f)
    for ax in axs.ravel():
        ax.axis("off")
    for ax, d in zip(axs.ravel(), mdays):
        ax.axis("on"); ax.set_xticks([]); ax.set_yticks([])
        m = day_map.get(d)
        if m is None:
            ax.text(0.5, 0.5, "MISSING /\nUNUSABLE", ha="center", va="center", fontsize=8, color="red", transform=ax.transAxes)
        else:
            im = ax.imshow(np.ma.masked_invalid(m), extent=ext, cmap="Blues", vmin=0, vmax=vmax, interpolation="nearest")
        gpd.GeoSeries([aoi]).boundary.plot(ax=ax, color="k", linewidth=0.6)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_title(d.strftime("%d %b %Y"), fontsize=7)
    fig.suptitle(f"{src['source_id']} daily rainfall (mm/day), NATIVE {src['native_resolution']} cells, common scale 0-{vmax:.0f} mm. Day definition: {src['day_definition']}", fontsize=8)
    fig.tight_layout(); fig.savefig(figd / f"{base}_daily_maps.png", dpi=170); plt.close(fig); files.append(str(figd / f"{base}_daily_maps.png"))
    if not miss_ev:
        fig, ax = plt.subplots(figsize=(5, 6))
        im = ax.imshow(np.ma.masked_invalid(total), extent=ext, cmap="Blues", interpolation="nearest"); fig.colorbar(im, ax=ax, label="mm")
        gpd.GeoSeries([aoi]).boundary.plot(ax=ax, color="k", linewidth=0.8)
        ax.set_title(f"{src['source_id']} event total {e0}..{e1}\nnative {src['native_resolution']} cells (no resampling)", fontsize=9)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); fig.tight_layout(); fig.savefig(figd / f"{base}_event_total_native.png", dpi=170); plt.close(fig)
        files.append(str(figd / f"{base}_event_total_native.png"))


    # time-series plot (gaps and unusable days are marked, never drawn as zero) + map of the wettest usable day
    s1_dates = [date.fromisoformat(item["date"]) for item in s1_observations]
    fig, ax = plt.subplots(figsize=(11, 4))
    okd = [d for d in ctx if day_map.get(d) is not None]
    vals = [R.weighted_stats(day_map[d], w)["mean_mm"] for d in okd]
    ax.bar(okd, vals, color="#2b7bba", width=0.9, label="AOI-weighted mean (native cells)")
    bad = [d for d in ctx if day_map.get(d) is None]
    if bad:
        ax.plot(bad, [0] * len(bad), "rx", markersize=5, label="missing/unusable day (NOT zero)")
    for k, dd in enumerate(s1_dates):
        if ctx[0] <= dd <= ctx[-1]:
            ax.axvline(dd, color="k", ls="--", lw=0.7, label=s1_plot_label if k == 0 else None)
    ax.axvspan(e0, e1, color="orange", alpha=0.12, label="event window (PROVISIONAL)")
    ax.set_ylabel("mm per labelled day"); ax.set_title(f"{src['source_id']} daily rainfall, study-area mean - day definition: {str(src['day_definition'])[:70]}...", fontsize=8)
    ax.legend(fontsize=7); fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(figd / f"{base}_timeseries.png", dpi=170); plt.close(fig)
    files.append(str(figd / f"{base}_timeseries.png"))
    if okd:
        pk = okd[int(np.nanargmax(vals))]
        fig, ax = plt.subplots(figsize=(5, 6))
        im = ax.imshow(np.ma.masked_invalid(day_map[pk]), extent=ext, cmap="Blues", interpolation="nearest"); fig.colorbar(im, ax=ax, label="mm")
        gpd.GeoSeries([aoi]).boundary.plot(ax=ax, color="k", linewidth=0.8)
        ax.set_title(f"{src['source_id']}: wettest usable day {pk} (AOI mean {max(vals):.1f} mm)\nnative {src['native_resolution']} cells", fontsize=9)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); fig.tight_layout(); fig.savefig(figd / f"{base}_wettest_day_native.png", dpi=170); plt.close(fig)
        files.append(str(figd / f"{base}_wettest_day_native.png"))

    res_note = "not requested"
    if a.resample_to_master and not miss_ev:
        from rasterio.warp import Resampling
        from src.geospatial import grid as G
        g = master_grid()
        out = G.to_grid(np.where(np.isfinite(total), total, ND), tr0, crs0, g, Resampling.nearest, src_nodata=ND, dst_nodata=ND)
        pr = outd / f"{a.event}_event_total_mm_RESAMPLED_nearest_to_{int(g.res)}m.tif"
        G.write_raster(pr, out, g, ND, f"RESAMPLED nearest-neighbour copy of native {src['native_resolution']} rainfall; contains NO {int(g.res)} m information")
        res_note = f"written: {pr.name} (nearest-neighbour copy of native cells; no added spatial information)"; files.append(paths.rel(pr))

    n_ok = int((ts["status"] == "OK").sum())
    day_unconf = any(t in str(src["day_definition"]).upper() for t in ("UNCONFIRMED", "PROVISIONAL"))
    L = [f"# Rainfall workflow report - {src['source_id']} / {a.event}", "",
         "**Rainfall from the stated source only. No value was filled, interpolated or set to zero. Window dates are PROPOSED, not confirmed.**", "",
         f"- Source: {src.get('name')} (version {src['version']}, {src['product_type']}); obtained from: {src.get('obtained_from')} on {src.get('obtained_on')}; licence note: {src.get('licence_note')}",
         f"- Unit in files: {src['unit']} -> converted to mm. Day definition: **{src['day_definition']}**{' (UNCONFIRMED/PROVISIONAL: day-label convention not verified against local observation windows)' if day_unconf else ''}.",
         f"- Data completeness: {n_ok} of {len(ctx)} context-window days OK (valid file, AOI coverage >= {100 * a.min_coverage:.0f}%)" + (" - the daily data are COMPLETE." if n_ok == len(ctx) else " - the daily data are INCOMPLETE.")
         + (f" Overall run status: PARTIALLY COMPLETED - solely because the day definition is provisional (a convention caveat, NOT missing data)." if (day_unconf and n_ok == len(ctx) and not miss_ev) else ""),
         f"- Native grid: {crs0}, {sh0[1]}x{sh0[0]} cells, resolution {src['native_resolution']}. Native cells intersecting the study area: {int((w > 0).sum())} (convention: any positive-area overlap with the AOI polygon; weights = exact intersection area / AOI area, so boundary slivers count with their true small weight). "
         f"Share of the AOI inside the raster extent: {100 * aoi_cov:.1f}%. Rainfall varies across the AOI only at this cell size.",
         f"- Context window {ctx[0]}..{ctx[-1]}: {len(ctx)} days; OK {n_ok}; missing {(ts['status'] == 'MISSING').sum()}; unreadable {(ts['status'] == 'UNREADABLE').sum()}; "
         f"incomplete coverage {(ts['status'] == 'INCOMPLETE_COVERAGE').sum()} (min coverage {100 * a.min_coverage:.0f}%).",
         f"- Event window (proposed) {e0}..{e1}: event total **{total_state}**.",
         (f"- Event total AOI-weighted mean {ev_stat['mean_mm']:.1f} mm; min/max cell {ev_stat['min_mm']:.1f}/{ev_stat['max_mm']:.1f} mm." if ev_stat else "- No event-total statistics (incomplete window)."),
         f"- Resampling to the master grid: {res_note}.",
         "- Anomaly / comparison: **NOT COMPUTED** - requires a same-source, same-grid multi-year same-calendar-window record (>= 10 years) that has not been supplied.",
         "- Sentinel-1 date source: " + ("candidate dates/categories from config/s1_candidate_roles.json; categories remain candidate labels, not confirmed hydrological truth." if s1_source_name == "s1_candidate_roles.json" else "processed-observation dates from config/s1_preprocess.json; category is `unassigned` and no dry, flood, baseline or recovery role is inferred."),
         "- Antecedent totals: prior-N-day window = the N labelled days D-N..D-1 for each configured Sentinel-1 date D (the label D itself is EXCLUDED); a window with any missing/unusable day is NOT computed (empty, never a partial sum, never zero-filled). Sentinel-1 acquisition ~00:31 UTC / ~06:01 IST. WARNING: " + ("the CHIRPS daily labels are NOT verified against IST observation windows, so whether label D-1 ends before the overpass is unverified." if "chirps" in str(src["source_id"]).lower() else "IMD daily totals are nominally 24 h ending 08:30 IST, but the label convention is unconfirmed, so the overpass-relative timing of label D-1 is unverified."), "",
         "Tables: `*_daily_series.csv`, `*_max_k_day.csv`, `*_antecedent_before_s1.csv`. Figures: daily-map montage" + (", native event total." if not miss_ev else ".")]
    report_path = repd / f"{base}_report.md"
    report_path.write_text("\\n".join(L), encoding="utf-8")
    files.append(str(report_path))
    state = status.COMPLETED if (not miss_ev and not day_unconf and n_ok == len(ctx)) else status.PARTIAL
    status.record("C2", state, f"{a.source_id}/{a.event}: {n_ok}/{len(ctx)} days OK; event total {total_state.split(':')[0]}.", files=files,
                  extra={"source": a.source_id, "native_resolution": src["native_resolution"]}, seconds=time.time() - t0)
    log.info("report: %s", report_path)


if __name__ == "__main__":
    main()
